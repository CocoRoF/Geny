/**
 * WebSocket hook for chat room event streaming.
 *
 * Replaces the SSE-based subscribeToRoom pattern with a persistent
 * WebSocket connection that receives real-time room events.
 *
 * Protocol:
 *   Client -> {"type": "subscribe", "after": "last_msg_id"}
 *   Server -> {"type": "message"|"broadcast_status"|"agent_progress"|"broadcast_done"|"heartbeat", "data": {...}}
 */

import { useRef, useCallback } from 'react';

export interface ChatWsEvent {
  type: string;
  data: Record<string, unknown>;
}

/**
 * Build the WebSocket URL for a chat room.
 */
function getChatWsUrl(roomId: string): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl !== undefined && envUrl !== '') {
    const wsBase = envUrl.replace(/^http/, 'ws');
    return `${wsBase}/ws/chat/rooms/${roomId}`;
  }

  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';

    const backendPort = process.env.NEXT_PUBLIC_BACKEND_PORT;
    if (backendPort) {
      return `${proto}//${window.location.hostname}:${backendPort}/ws/chat/rooms/${roomId}`;
    }

    return `${proto}//${window.location.host}/ws/chat/rooms/${roomId}`;
  }

  return `ws://localhost:8000/ws/chat/rooms/${roomId}`;
}

export function useChatWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);

  /**
   * Subscribe to a chat room's events.
   *
   * @param roomId      Chat room to subscribe to
   * @param afterId     Last seen message ID (null for fresh start)
   * @param onEvent     Callback for each event from the server
   * @param getLatestMsgId  Optional function returning the latest message ID for reconnection
   * @returns Object with close() method
   */
  const subscribe = useCallback(
    (
      roomId: string,
      afterId: string | null,
      onEvent: (eventType: string, eventData: Record<string, unknown>) => void,
      getLatestMsgId?: () => string | null,
    ): { close: () => void } => {
      // Close existing connection
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
      let closed = false;
      let attempts = 0;
      const maxAttempts = 20;
      const reconnectDelay = 3000;

      const connect = () => {
        if (closed) return;

        const wsUrl = getChatWsUrl(roomId);
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          attempts = 0;
          const currentAfter = getLatestMsgId ? getLatestMsgId() : afterId;
          ws.send(
            JSON.stringify({
              type: 'subscribe',
              after: currentAfter,
            }),
          );
        };

        ws.onmessage = (ev) => {
          try {
            const event: ChatWsEvent = JSON.parse(ev.data);
            onEvent(event.type, event.data);
          } catch {
            // ignore
          }
        };

        ws.onerror = () => {
          wsRef.current = null;
        };

        ws.onclose = () => {
          wsRef.current = null;
          if (!closed && attempts < maxAttempts) {
            attempts++;
            reconnectTimer = setTimeout(connect, reconnectDelay);
          }
        };
      };

      connect();

      return {
        close: () => {
          closed = true;
          if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
          }
          if (wsRef.current) {
            wsRef.current.close();
            wsRef.current = null;
          }
        },
      };
    },
    [],
  );

  return { subscribe };
}
