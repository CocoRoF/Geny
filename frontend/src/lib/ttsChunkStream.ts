/**
 * ttsChunkStream — 프런트엔드가 미리 분할한 문장들을
 * `POST /api/tts/agents/:sid/speak/chunks` 로 보내고 NDJSON
 * 응답을 ``AudioManager`` 에 순서대로 enqueue 하는 헬퍼.
 *
 * ``ttsSentenceStream.ts`` 와 유사하지만:
 *  - 입력 쪽에서 이미 문장 분할이 끝나 있음 (서버가 분할하지 않음)
 *  - ``turn_id`` 로 오디오 큐 스코프를 관리 — 새 턴이 시작되면
 *    이전 턴의 잔여 클립을 ``AudioManager.clearTurn`` 으로 버릴 수 있음
 *  - seq 순서대로 도착이 보장되므로 별도 버퍼링 없이 그대로 enqueue
 */

import { getAudioManager } from './audioManager';
import { getBackendUrl } from './api';

interface ChunkFrame {
  seq?: number;
  text?: string;
  format?: string;
  sample_rate?: number;
  audio_b64?: string;
  error?: string;
  done?: boolean;
  total?: number;
  turn_id?: string;
}

const FORMAT_TO_MIME: Record<string, string> = {
  wav: 'audio/wav',
  mp3: 'audio/mpeg',
  ogg: 'audio/ogg',
  pcm: 'audio/wav',
};

function base64ToBlob(b64: string, mime: string): Blob {
  const binary = atob(b64);
  const len = binary.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

export interface SpeakChunksBody {
  sentences: string[];
  emotion?: string;
  language?: string;
  engine?: string;
  /** opaque turn identifier — 클라이언트가 audio queue 를 스코프하는데 사용 */
  turn_id: string;
}

export interface ConsumeChunkOptions {
  sessionId: string;
  /** 이 턴의 첫 오디오가 큐에 들어간 순간 */
  onFirstClip?: (seq: number) => void;
  onClipError?: (seq: number, err: string) => void;
  onComplete?: (totalEnqueued: number) => void;
  /** 각 클립 재생 종료 콜백 — AudioManager가 idempotent 하게 호출 */
  onClipEnd?: (seq: number) => void;
  /**
   * 응답의 ``seq`` 에 더할 오프셋. 백엔드는 입력 배열 인덱스를 그대로
   * 응답 seq 로 쓰므로 (단일-문장이면 항상 0), 턴 전역 seq 공간으로
   * 매핑하려면 이 값을 지정한다. 예: turn 에 5 번째 문장을 이 요청으로
   * 보낼 때 ``seqOffset=5`` 로 주면 AudioManager 큐에 seq=5 로 들어간다.
   */
  seqOffset?: number;
}

/**
 * 지정된 문장들을 백엔드로 전송하고, 응답 NDJSON을 순서대로
 * ``AudioManager.enqueue`` 에 넣는다.
 *
 * 반환: { enqueued, errors }
 */
export async function dispatchSpeakChunks(
  body: SpeakChunksBody,
  opts: ConsumeChunkOptions,
  signal?: AbortSignal,
): Promise<{ enqueued: number; errors: number }> {
  const backendUrl = getBackendUrl();
  const response = await fetch(
    `${backendUrl}/api/tts/agents/${opts.sessionId}/speak/chunks`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    },
  );

  if (response.status === 204) {
    // 산이타이저 이후 빈 텍스트
    opts.onComplete?.(0);
    return { enqueued: 0, errors: 0 };
  }

  if (!response.ok || !response.body) {
    throw new Error(`speak/chunks HTTP ${response.status}`);
  }

  const audioManager = getAudioManager();
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let enqueued = 0;
  let errors = 0;
  let firstFired = false;

  const handleLine = (line: string) => {
    if (!line.trim()) return;
    let frame: ChunkFrame;
    try {
      frame = JSON.parse(line) as ChunkFrame;
    } catch (err) {
      console.warn('[ttsChunkStream] malformed frame:', err, line.slice(0, 120));
      return;
    }
    if (frame.done) return;
    if (frame.error) {
      errors += 1;
      opts.onClipError?.(frame.seq ?? -1, frame.error);
      return;
    }
    if (!frame.audio_b64) return;

    const seq = (frame.seq ?? 0) + (opts.seqOffset ?? 0);
    const mime = FORMAT_TO_MIME[frame.format ?? 'wav'] ?? 'audio/wav';
    let blob: Blob;
    try {
      blob = base64ToBlob(frame.audio_b64, mime);
    } catch (err) {
      errors += 1;
      console.warn('[ttsChunkStream] base64 decode failed seq=', seq, err);
      return;
    }
    if (blob.size === 0) return;

    const wrapped = new Response(blob, {
      status: 200,
      headers: { 'Content-Type': mime },
    });

    if (!firstFired) {
      firstFired = true;
      opts.onFirstClip?.(seq);
    }

    void audioManager.enqueue(wrapped, opts.sessionId, undefined, () => {
      opts.onClipEnd?.(seq);
    }, { turnId: body.turn_id, seq });
    enqueued += 1;
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl = buffer.indexOf('\n');
      while (nl !== -1) {
        const line = buffer.slice(0, nl);
        buffer = buffer.slice(nl + 1);
        handleLine(line);
        nl = buffer.indexOf('\n');
      }
    }
    if (buffer.trim()) handleLine(buffer);
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      // 정상 취소
    } else {
      throw err;
    }
  } finally {
    try { reader.releaseLock(); } catch { /* noop */ }
  }

  opts.onComplete?.(enqueued);
  return { enqueued, errors };
}
