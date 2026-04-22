/**
 * ttsSentenceStream — NDJSON sentence-stream consumer.
 *
 * 백엔드의 ``POST /api/tts/agents/:sid/speak/stream`` 응답을 한 줄씩
 * 파싱해서 각 문장을 ``AudioManager.enqueue``에 즉시 넣어주는 헬퍼.
 *
 * 핵심 동작:
 *  - Response.body를 라인 단위로 읽음 (TextDecoder + \n split)
 *  - 각 줄을 JSON으로 파싱 → ``{seq, text, format, sample_rate, audio_b64}``
 *  - audio_b64 → Blob([wav bytes], type="audio/wav") → 새 Response로 감싸
 *    audioManager.enqueue 호출 (기존 큐 기반 순차재생 그대로 활용)
 *  - 첫 문장이 도착하는 즉시 재생이 시작되고, 뒤이은 문장은 큐의
 *    pre-fetch 슬롯에 들어가 끊김 없이 이어진다.
 *
 * iOS WebKit 호환성: AudioManager가 이미 AudioBufferSourceNode 경로를
 * 쓰므로 Blob → Response 래핑만으로 동일한 재생 경로를 탄다. 새 코드
 * 추가 없음.
 */

import { getAudioManager } from './audioManager';

interface SentenceFrame {
  seq?: number;
  text?: string;
  format?: string;
  sample_rate?: number;
  audio_b64?: string;
  error?: string;
  done?: boolean;
  total?: number;
}

const FORMAT_TO_MIME: Record<string, string> = {
  wav: 'audio/wav',
  mp3: 'audio/mpeg',
  ogg: 'audio/ogg',
  pcm: 'audio/wav', // browsers can't play raw PCM; backend wraps to WAV anyway
};

function base64ToBlob(b64: string, mime: string): Blob {
  const binary = atob(b64);
  const len = binary.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

export interface ConsumeOptions {
  sessionId: string;
  /** Called once when the *first* sentence is enqueued — useful to
   *  switch UI from "thinking" to "speaking" before all sentences
   *  finish synthesising. */
  onFirstSentence?: () => void;
  /** Per-sentence error log hook. */
  onSentenceError?: (seq: number, err: string) => void;
  /** Called after the terminator frame is observed and the final
   *  sentence has been enqueued. Receives the count of successfully
   *  enqueued audio sentences (excluding errors). */
  onComplete?: (totalEnqueued: number) => void;
  /** Called every time *any* enqueued clip finishes playback. Because
   *  ``AudioManager`` plays clips strictly in order, the last
   *  invocation corresponds to the final sentence ending. Use this
   *  to clear "speaking" UI state — multiple calls are idempotent
   *  for a state setter. */
  onClipEnd?: () => void;
}

/**
 * Drain a sentence-stream Response and enqueue each clip.
 *
 * Returns when the stream ends (terminator observed or body
 * exhausted). Throws on network / decode errors so callers can
 * fall back to single-clip /speak. The returned promise resolves
 * *before* playback finishes — the audio queue is detached.
 */
export async function consumeSentenceStream(
  response: Response,
  opts: ConsumeOptions,
): Promise<{ enqueued: number; errors: number }> {
  if (!response.ok || !response.body) {
    throw new Error(`speak/stream HTTP ${response.status}`);
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
    let frame: SentenceFrame;
    try {
      frame = JSON.parse(line) as SentenceFrame;
    } catch (err) {
      console.warn('[ttsSentenceStream] malformed frame, skipping:', err, line.slice(0, 120));
      return;
    }

    if (frame.done) return;

    if (frame.error) {
      errors += 1;
      opts.onSentenceError?.(frame.seq ?? -1, frame.error);
      return;
    }

    if (!frame.audio_b64) return;

    const mime = FORMAT_TO_MIME[frame.format ?? 'wav'] ?? 'audio/wav';
    let blob: Blob;
    try {
      blob = base64ToBlob(frame.audio_b64, mime);
    } catch (err) {
      errors += 1;
      console.warn('[ttsSentenceStream] base64 decode failed seq=', frame.seq, err);
      return;
    }

    if (blob.size === 0) return;

    const wrapped = new Response(blob, {
      status: 200,
      headers: { 'Content-Type': mime },
    });

    if (!firstFired) {
      firstFired = true;
      opts.onFirstSentence?.();
    }

    // Fire-and-forget: enqueue returns when the clip finishes
    // playback, but we don't await it — letting the next sentence
    // arrive and queue up while the current one is still playing
    // is the whole point of this code path.
    void audioManager.enqueue(wrapped, opts.sessionId, undefined, opts.onClipEnd);
    enqueued += 1;
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nlIdx = buffer.indexOf('\n');
      while (nlIdx !== -1) {
        const line = buffer.slice(0, nlIdx);
        buffer = buffer.slice(nlIdx + 1);
        handleLine(line);
        nlIdx = buffer.indexOf('\n');
      }
    }
    // Flush any trailing line without a newline (shouldn't happen
    // with our backend, but be defensive).
    if (buffer.trim()) handleLine(buffer);
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      // Aborted by AbortController — not an error.
    } else {
      throw err;
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* already released */
    }
  }

  opts.onComplete?.(enqueued);
  return { enqueued, errors };
}
