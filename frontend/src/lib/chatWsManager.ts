/**
 * ChatRoomWSManager — 채팅방 WebSocket 연결 관리자 (싱글턴)
 *
 * 문제:
 *   VTuberChatPanel, MessengerStore, ChatTab이 동일한 roomId에 대해
 *   독립적으로 WebSocket을 생성하여 중복 연결이 발생.
 *
 * 해결:
 *   roomId당 하나의 WebSocket만 유지하고, 여러 컴포넌트가 리스너로 등록.
 *   레퍼런스 카운팅으로 마지막 리스너가 해제되면 WS 닫기.
 *
 * 사용법:
 *   const unsub = getChatWSManager().subscribe(roomId, afterId, handler, getLatestMsgId);
 *   // ... 나중에
 *   unsub(); // 리스너 제거, 마지막이면 WS 자동 종료
 */

import { chatApi } from '@/lib/api';

export type ChatWSEventHandler = (eventType: string, eventData: Record<string, unknown>) => void;

interface RoomConnection {
  /** chatApi.subscribeToRoom에서 반환된 close/reconnect 핸들 */
  sub: { close: () => void; reconnect: () => void };
  /** 등록된 이벤트 리스너들 */
  listeners: Set<ChatWSEventHandler>;
  /** 현재까지 본 마지막 메시지 ID (재연결 시 활용) */
  lastMsgId: string | null;
  /** 자동 복구 타이머 */
  _recoveryTimer?: ReturnType<typeof setTimeout>;
}

export class ChatRoomWSManager {
  private connections: Map<string, RoomConnection> = new Map();

  /**
   * roomId에 대해 이벤트 리스너를 등록.
   * 해당 방의 WS가 없으면 새로 생성, 이미 있으면 리스너만 추가.
   *
   * @returns 구독 해제 함수. 호출 시 리스너 제거, 마지막이면 WS 종료.
   */
  subscribe(
    roomId: string,
    afterId: string | null,
    handler: ChatWSEventHandler,
    getLatestMsgId?: () => string | null,
  ): () => void {
    const existing = this.connections.get(roomId);

    if (existing) {
      // 이미 연결이 있으면 리스너만 추가
      existing.listeners.add(handler);
      return () => this._removeListener(roomId, handler);
    }

    // 새 연결 생성
    const listeners = new Set<ChatWSEventHandler>();
    listeners.add(handler);

    const conn: RoomConnection = {
      sub: null as unknown as { close: () => void },
      listeners,
      lastMsgId: afterId,
    };

    // 내부 dispatcher: 등록된 모든 리스너에게 이벤트 전달
    const dispatcher: ChatWSEventHandler = (eventType, eventData) => {
      // 메시지 이벤트 시 lastMsgId 업데이트
      if (eventType === 'message' && eventData && typeof eventData === 'object' && 'id' in eventData) {
        conn.lastMsgId = eventData.id as string;
      }

      // 연결 실패 시 30초 후 자동 복구 시도
      if (eventType === '_ws_failed') {
        if (conn._recoveryTimer) clearTimeout(conn._recoveryTimer);
        console.info(`[ChatWSManager:${roomId.slice(0, 8)}] scheduling auto-recovery in 30s`);
        conn._recoveryTimer = setTimeout(() => {
          if (conn.listeners.size > 0) {
            console.info(`[ChatWSManager:${roomId.slice(0, 8)}] auto-recovery: triggering reconnect`);
            conn.sub.reconnect();
          }
        }, 30000);
      }

      // 재연결 성공 시 복구 타이머 정리
      if (eventType === '_ws_connected') {
        if (conn._recoveryTimer) {
          clearTimeout(conn._recoveryTimer);
          conn._recoveryTimer = undefined;
        }
      }

      for (const listener of conn.listeners) {
        try {
          listener(eventType, eventData);
        } catch (err) {
          console.error(`[ChatWSManager:${roomId.slice(0, 8)}] listener error:`, err);
        }
      }
    };

    // getLatestMsgId는 연결의 lastMsgId를 우선 사용
    const getMsgId = () => {
      return conn.lastMsgId ?? getLatestMsgId?.() ?? afterId;
    };

    conn.sub = chatApi.subscribeToRoom(roomId, afterId, dispatcher, getMsgId);
    this.connections.set(roomId, conn);

    return () => this._removeListener(roomId, handler);
  }

  /**
   * 특정 방의 리스너 제거. 마지막 리스너면 WS 종료.
   */
  private _removeListener(roomId: string, handler: ChatWSEventHandler): void {
    const conn = this.connections.get(roomId);
    if (!conn) return;

    conn.listeners.delete(handler);

    if (conn.listeners.size === 0) {
      // 마지막 리스너 — WS 종료
      conn.sub.close();
      this.connections.delete(roomId);
    }
  }

  /**
   * 특정 방의 연결을 강제 종료 (방 삭제 시 등).
   */
  disconnect(roomId: string): void {
    const conn = this.connections.get(roomId);
    if (!conn) return;

    if (conn._recoveryTimer) clearTimeout(conn._recoveryTimer);
    conn.sub.close();
    conn.listeners.clear();
    this.connections.delete(roomId);
  }

  /**
   * 모든 연결 종료.
   */
  disconnectAll(): void {
    for (const [, conn] of this.connections) {
      if (conn._recoveryTimer) clearTimeout(conn._recoveryTimer);
      conn.sub.close();
      conn.listeners.clear();
    }
    this.connections.clear();
  }

  /**
   * 현재 활성 연결된 방 수.
   */
  get activeCount(): number {
    return this.connections.size;
  }

  /**
   * 특정 방이 연결되어 있는지 확인.
   */
  isConnected(roomId: string): boolean {
    return this.connections.has(roomId);
  }

  /**
   * 특정 방의 리스너 수.
   */
  getListenerCount(roomId: string): number {
    return this.connections.get(roomId)?.listeners.size ?? 0;
  }
}

// 싱글턴
let _chatWSManager: ChatRoomWSManager | null = null;
export function getChatWSManager(): ChatRoomWSManager {
  if (!_chatWSManager) {
    _chatWSManager = new ChatRoomWSManager();
  }
  return _chatWSManager;
}
