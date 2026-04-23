import { create } from 'zustand';
import { vtuberApi, ttsApi, configApi } from '@/lib/api';
import { getAudioManager } from '@/lib/audioManager';
import { consumeSentenceStream } from '@/lib/ttsSentenceStream';
import { dispatchSpeakChunks } from '@/lib/ttsChunkStream';
import { SentenceStreamExtractor } from '@/lib/sentenceBoundaryDetector';
import type { Live2dModelInfo, AvatarState, VTuberLogEntry } from '@/types';

const MAX_LOGS = 500;
let _logIdCounter = 0;

// TTS fetch 취소용 AbortController (세션별)
const _ttsAbortControllers: Map<string, AbortController> = new Map();

// ── Live-stream sentence TTS (chat-stream pre-emit) ──────────────
// LLM 토큰이 쏟아지는 동안 이미 완성된 문장을 즉시 /speak/chunks 로 보내서
// 사용자가 첫 음성을 듣는 시점을 agent_message turn-end 이전으로 앞당긴다.
//
// 턴 ID 규칙:  `${sessionId}:${turnIndex}`
//   - 사용자가 새 메시지를 보낼 때 turnIndex++ 하고 이전 턴의 잔여 클립을
//     AudioManager.clearTurn 으로 버림으로써 overlap 을 원천 차단.
const _liveTurnIndex: Map<string, number> = new Map();
const _liveAbortControllers: Map<string, AbortController> = new Map();
const _liveEmittedByTurn: Map<string, number> = new Map(); // turnId → next seq
// 짧은 문장은 묶어서 내보낸다. TTS 요청 1건당 fixed 오버헤드 (커넥션 풀
// + GPU 워밍업 + RTF 비효율) 가 크기 때문에, "안녕!" (3자) 같은 미니
// 클립 여러 개로 GPU/네트워크를 도배하면 오히려 전체 지연이 늘어난다.
//
// 20자 임계값은 한국어 1-2 어절 ≈ 한 호흡 분량. 이 정도면 fixed 오버
// 헤드 대비 합성 시간 비율이 충분히 합리적.
const LIVE_TTS_MIN_CHARS = 20;
const _liveExtractor = new SentenceStreamExtractor({ minChars: LIVE_TTS_MIN_CHARS });

function _currentTurnId(sessionId: string): string {
  const idx = _liveTurnIndex.get(sessionId) ?? 0;
  return `${sessionId}:${idx}`;
}

/**
 * Debug/introspection — VTuberChatPanel 에서 "이번 턴에 이미 live 로 재생되고
 * 있으니 agent_message 시점의 단발성 speakResponse 는 건너뛰자" 는 판단에 쓴다.
 */
export function hasLiveChunksThisTurn(sessionId: string): boolean {
  const turnId = _currentTurnId(sessionId);
  return (_liveEmittedByTurn.get(turnId) ?? 0) > 0;
}

// ── Cached tts_general settings (refresh every 30s) ──────────────
// Why: speakResponse는 매 응답마다 호출되는데, 매번 /api/config/tts_general을
// fetch하면 latency만 늘고 별 의미가 없다. 30초 TTL로 충분히 신선.
interface TTSGeneralSnapshot {
  streamingMode: 'off' | 'auto' | 'always';
  streamingMinChars: number;
  fetchedAt: number;
}
let _ttsGeneralCache: TTSGeneralSnapshot | null = null;
const _TTS_GENERAL_TTL_MS = 30_000;

async function getTTSGeneral(): Promise<TTSGeneralSnapshot> {
  const now = Date.now();
  if (_ttsGeneralCache && now - _ttsGeneralCache.fetchedAt < _TTS_GENERAL_TTL_MS) {
    return _ttsGeneralCache;
  }
  try {
    const res = await configApi.get('tts_general');
    const v = res.values as Record<string, unknown>;
    const mode = String(v.streaming_mode ?? 'off').toLowerCase();
    _ttsGeneralCache = {
      streamingMode: (mode === 'always' || mode === 'auto' ? mode : 'off') as TTSGeneralSnapshot['streamingMode'],
      streamingMinChars: Number(v.streaming_min_chars ?? 80) || 80,
      fetchedAt: now,
    };
  } catch (err) {
    console.warn('[VTuber] failed to load tts_general, defaulting to off:', err);
    _ttsGeneralCache = { streamingMode: 'off', streamingMinChars: 80, fetchedAt: now };
  }
  return _ttsGeneralCache;
}

/** 외부에서 streaming_mode 변경 직후 캐시 무효화하고 싶을 때 사용. */
export function invalidateTTSGeneralCache(): void {
  _ttsGeneralCache = null;
}

interface VTuberState {
  // Models
  models: Live2dModelInfo[];
  modelsLoaded: boolean;

  // Per-session: assigned model name
  assignments: Record<string, string>;

  // Per-session: latest avatar state
  avatarStates: Record<string, AvatarState>;

  // Per-session: log entries
  logs: Record<string, VTuberLogEntry[]>;

  // WebSocket subscriptions (keyed by session_id)
  _subs: Record<string, { close: () => void }>;

  // TTS state
  ttsEnabled: boolean;
  ttsSpeaking: Record<string, boolean>;
  ttsVolume: number;

  // Actions
  fetchModels: () => Promise<void>;
  assignModel: (sessionId: string, modelName: string) => Promise<void>;
  unassignModel: (sessionId: string) => Promise<void>;
  fetchAssignment: (sessionId: string) => Promise<void>;
  subscribeAvatar: (sessionId: string) => void;
  unsubscribeAvatar: (sessionId: string) => void;
  setEmotion: (sessionId: string, emotion: string) => Promise<void>;
  interact: (sessionId: string, hitArea: string, x?: number, y?: number) => Promise<void>;
  getModelForSession: (sessionId: string) => Live2dModelInfo | null;
  addLog: (sessionId: string, level: VTuberLogEntry['level'], source: string, message: string, detail?: Record<string, unknown>) => void;
  clearLogs: (sessionId: string) => void;

  // TTS actions
  toggleTTS: () => void;
  setTTSVolume: (vol: number) => void;
  speakResponse: (sessionId: string, text: string, emotion: string) => Promise<void>;
  stopSpeaking: (sessionId: string) => void;

  // ── Live chat-stream pre-emit TTS ──
  /** 새 유저 메시지 시작 시 호출 — 턴 인덱스 증가 + 이전 턴 잔여 클립 폐기. */
  beginTTSTurn: (sessionId: string) => void;
  /** 스트리밍 토큰 청크를 주입. 내부 extractor가 완성된 문장만 뽑아 /speak/chunks 로 전송. */
  pushStreamingText: (sessionId: string, fullText: string, emotion: string) => void;
  /** 턴 종료(=agent_message 도착) 시 호출 — 꼬리 문장 강제 flush. */
  finalizeTTSTurn: (sessionId: string, fullText: string, emotion: string) => void;
}

export const useVTuberStore = create<VTuberState>((set, get) => ({
  models: [],
  modelsLoaded: false,
  assignments: {},
  avatarStates: {},
  logs: {},
  _subs: {},
  ttsEnabled: true,
  ttsSpeaking: {},
  ttsVolume: 0.7,

  fetchModels: async () => {
    try {
      const res = await vtuberApi.listModels();
      set({ models: res.models, modelsLoaded: true });
    } catch (err) {
      console.error('[VTuber] Failed to fetch models:', err);
    }
  },

  assignModel: async (sessionId, modelName) => {
    try {
      await vtuberApi.assignModel(sessionId, modelName);
      set((s) => ({
        assignments: { ...s.assignments, [sessionId]: modelName },
      }));
      get().addLog(sessionId, 'info', 'Model', `Assigned model: ${modelName}`);
    } catch (err) {
      console.error('[VTuber] Failed to assign model:', err);
      get().addLog(sessionId, 'error', 'Model', `Failed to assign model: ${err}`);
      throw err;
    }
  },

  unassignModel: async (sessionId) => {
    try {
      await vtuberApi.unassignModel(sessionId);
      get().addLog(sessionId, 'info', 'Model', 'Model unassigned');
      set((s) => {
        const { [sessionId]: _, ...rest } = s.assignments;
        return { assignments: rest };
      });
      // Cleanup WebSocket subscription
      get().unsubscribeAvatar(sessionId);
    } catch (err) {
      console.error('[VTuber] Failed to unassign model:', err);
      get().addLog(sessionId, 'error', 'Model', `Failed to unassign: ${err}`);
      throw err;
    }
  },

  fetchAssignment: async (sessionId) => {
    try {
      const res = await vtuberApi.getAgentModel(sessionId);
      if (res.model) {
        set((s) => ({
          assignments: { ...s.assignments, [sessionId]: res.model!.name },
        }));
      }
    } catch {
      // Session may not have a model — that's fine
    }
  },

  subscribeAvatar: (sessionId) => {
    const { _subs } = get();
    // Already subscribed
    if (_subs[sessionId]) return;

    const sub = vtuberApi.subscribeToAvatarState(sessionId, (state) => {
      set((s) => ({
        avatarStates: { ...s.avatarStates, [sessionId]: state },
      }));
      // Log the state change
      get().addLog(sessionId, 'state', 'WS', `${state.trigger}: ${state.emotion} (expr=${state.expression_index}, motion=${state.motion_group}[${state.motion_index}])`, state as unknown as Record<string, unknown>);
    });

    get().addLog(sessionId, 'info', 'WS', 'Avatar WS connected');
    set((s) => ({
      _subs: { ...s._subs, [sessionId]: sub },
    }));
  },

  unsubscribeAvatar: (sessionId) => {
    const { _subs } = get();
    _subs[sessionId]?.close();
    get().addLog(sessionId, 'info', 'WS', 'Avatar WS disconnected');
    set((s) => {
      const { [sessionId]: _, ...rest } = s._subs;
      return { _subs: rest };
    });
  },

  setEmotion: async (sessionId, emotion) => {
    try {
      await vtuberApi.setEmotion(sessionId, emotion);
      get().addLog(sessionId, 'info', 'UI', `Emotion override: ${emotion}`);
    } catch (err) {
      console.error('[VTuber] Failed to set emotion:', err);
      get().addLog(sessionId, 'error', 'UI', `Failed to set emotion: ${err}`);
    }
  },

  interact: async (sessionId, hitArea, x, y) => {
    try {
      await vtuberApi.interact(sessionId, hitArea, x, y);
      get().addLog(sessionId, 'debug', 'UI', `Interact: ${hitArea} (${x?.toFixed(2)}, ${y?.toFixed(2)})`);
    } catch (err) {
      console.error('[VTuber] Failed to interact:', err);
    }
  },

  getModelForSession: (sessionId) => {
    const { assignments, models } = get();
    const modelName = assignments[sessionId];
    if (!modelName) return null;
    return models.find((m) => m.name === modelName) ?? null;
  },

  addLog: (sessionId, level, source, message, detail) => {
    const entry: VTuberLogEntry = {
      id: ++_logIdCounter,
      timestamp: new Date().toISOString(),
      level,
      source,
      message,
      detail,
    };
    set((s) => {
      const existing = s.logs[sessionId] ?? [];
      const updated = [...existing, entry].slice(-MAX_LOGS);
      return { logs: { ...s.logs, [sessionId]: updated } };
    });
  },

  clearLogs: (sessionId) => {
    set((s) => ({
      logs: { ...s.logs, [sessionId]: [] },
    }));
  },

  // ─── TTS Actions ───

  toggleTTS: () => {
    const newEnabled = !get().ttsEnabled;
    set({ ttsEnabled: newEnabled });

    // TTS 켤 때 AudioContext 초기화 — user gesture(onClick) 컨텍스트에서 실행되므로
    // iOS/iPadOS WebKit에서도 AudioContext.resume()이 성공한다.
    if (newEnabled) {
      getAudioManager().ensureResumed();
    }
  },

  setTTSVolume: (vol) => {
    const clamped = Math.max(0, Math.min(1, vol));
    set({ ttsVolume: clamped });
    getAudioManager().setVolume(clamped);
  },

  speakResponse: async (sessionId, text, emotion) => {
    const { ttsEnabled } = get();
    if (!ttsEnabled) return;

    // 이전 TTS fetch가 아직 진행 중이면 abort하여 네트워크 낭비 방지
    const prevController = _ttsAbortControllers.get(sessionId);
    if (prevController) {
      prevController.abort();
    }
    const controller = new AbortController();
    _ttsAbortControllers.set(sessionId, controller);

    const markEnd = () => {
      set((s) => ({
        ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: false },
      }));
    };

    try {
      set((s) => ({
        ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: true },
      }));
      get().addLog(sessionId, 'info', 'TTS', `Speaking: "${text.slice(0, 50)}..." (${emotion})`);

      // ── Decide path: legacy /speak vs /speak/stream ─────────────
      // Off  → 단일 요청 (Pascal-class GPU에서 가장 빠름; 문장당 setup 오버헤드 없음)
      // Auto → 길이 ≥ streamingMinChars일 때만 스트리밍
      // Always → 항상 스트리밍 (체감 첫음성 지연 최단)
      const ttsGeneral = await getTTSGeneral();
      const wantStream =
        ttsGeneral.streamingMode === 'always' ||
        (ttsGeneral.streamingMode === 'auto' && text.length >= ttsGeneral.streamingMinChars);

      get().addLog(
        sessionId, 'debug', 'TTS',
        `Path decision: streamingMode=${ttsGeneral.streamingMode} chars=${text.length} threshold=${ttsGeneral.streamingMinChars} -> ${wantStream ? 'stream' : 'single'}`,
      );

      // ── Sentence-streaming path ─────────────────────────────────
      let streamResponse: Response | null = null;
      if (wantStream) {
        try {
          streamResponse = await ttsApi.speakStream(
            sessionId, text, emotion, undefined, undefined, controller.signal,
          );
        } catch (err) {
          if (err instanceof DOMException && err.name === 'AbortError') {
            get().addLog(sessionId, 'debug', 'TTS', 'Previous TTS fetch aborted (new request)');
            return;
          }
          get().addLog(sessionId, 'warn', 'TTS', `speak/stream fetch failed, falling back: ${err}`);
          streamResponse = null;
        }
      }

      // Stale 응답 방지
      if (_ttsAbortControllers.get(sessionId) !== controller) {
        get().addLog(sessionId, 'debug', 'TTS', 'Stale TTS response discarded (newer request in flight)');
        markEnd();
        return;
      }

      const audioManager = getAudioManager();
      audioManager.setVolume(get().ttsVolume);

      if (streamResponse && streamResponse.ok) {
        try {
          const { enqueued, errors } = await consumeSentenceStream(streamResponse, {
            sessionId,
            onFirstSentence: () => {
              get().addLog(sessionId, 'debug', 'TTS', 'First sentence enqueued (streaming)');
            },
            onSentenceError: (seq, err) => {
              get().addLog(sessionId, 'warn', 'TTS', `Sentence ${seq} failed: ${err}`);
            },
            onClipEnd: () => {
              // AudioManager가 큐의 클립을 순서대로 재생하므로 마지막
              // 클립의 onEnd가 곧 전체 음성 종료. set은 idempotent하니
              // 중간 클립 종료마다 호출돼도 안전.
              markEnd();
            },
            onComplete: (total) => {
              get().addLog(sessionId, 'debug', 'TTS', `Sentence stream complete: ${total} clips enqueued`);
              if (total === 0) markEnd();
            },
          });
          if (enqueued === 0 && errors === 0) {
            // 빈 응답 (sanitize 후 empty 등) — 즉시 풀어줌.
            markEnd();
          }
          return;
        } catch (err) {
          if (err instanceof DOMException && err.name === 'AbortError') {
            return;
          }
          get().addLog(sessionId, 'warn', 'TTS', `Sentence stream consume failed, retrying single-shot: ${err}`);
          // fall through to legacy path
        }
      } else if (streamResponse && streamResponse.status === 204) {
        // No speakable text after sanitization
        markEnd();
        return;
      } else if (streamResponse && streamResponse.status !== 404) {
        get().addLog(
          sessionId, 'warn', 'TTS',
          `speak/stream HTTP ${streamResponse.status}, falling back to /speak`,
        );
      }

      // ── Fallback: legacy single-clip /speak ─────────────────────
      // 백엔드가 구버전이거나 sentence-stream 라우트가 일시적으로 실패한 경우.
      const response = await ttsApi.speak(
        sessionId, text, emotion, undefined, undefined, controller.signal,
      );

      if (_ttsAbortControllers.get(sessionId) !== controller) {
        get().addLog(sessionId, 'debug', 'TTS', 'Stale TTS response discarded (newer request in flight)');
        markEnd();
        return;
      }
      _ttsAbortControllers.delete(sessionId);

      if (response.status === 204 || !response.ok) {
        get().addLog(sessionId, 'debug', 'TTS', `TTS skipped: status=${response.status}`);
        markEnd();
        return;
      }

      // 큐에 추가 — 이전 재생을 중단하지 않고 순차 재생
      await audioManager.enqueue(
        response,
        sessionId,
        () => {
          get().addLog(sessionId, 'debug', 'TTS', 'Audio playback started');
        },
        () => {
          markEnd();
          get().addLog(sessionId, 'debug', 'TTS', 'Audio playback ended');
        },
      );
    } catch (err) {
      // AbortError는 정상적인 취소 — 에러 로그 생략
      if (err instanceof DOMException && err.name === 'AbortError') {
        get().addLog(sessionId, 'debug', 'TTS', 'Previous TTS fetch aborted (new request)');
        return;
      }
      console.error('[VTuber] TTS speak error:', err);
      markEnd();
      get().addLog(sessionId, 'error', 'TTS', `Speak failed: ${err}`);
    }
  },

  stopSpeaking: (sessionId) => {
    // 진행 중인 TTS fetch 취소
    const controller = _ttsAbortControllers.get(sessionId);
    if (controller) {
      controller.abort();
      _ttsAbortControllers.delete(sessionId);
    }
    // clearQueue: 큐의 모든 대기 아이템 비우기 + 현재 재생 중지
    // 각 아이템의 onEnd 콜백이 호출되어 ttsSpeaking 상태가 정리됨
    getAudioManager().clearQueue();
    set((s) => ({
      ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: false },
    }));
    get().addLog(sessionId, 'info', 'TTS', 'Playback stopped (queue cleared)');
  },

  // ── Live chat-stream pre-emit TTS ─────────────────────────────────
  //
  // 새 유저 메시지 시작 시 호출. 이전 턴의 잔여 클립을 AudioManager 에서
  // 제거하고 turnIndex++ 하여 새 스코프를 연다. extractor 버퍼도 리셋.
  beginTTSTurn: (sessionId) => {
    const prevTurn = _currentTurnId(sessionId);
    // 이전 턴 고유 폐기
    getAudioManager().clearTurn(prevTurn, /* stopCurrent */ false);
    _liveAbortControllers.get(sessionId)?.abort();
    _liveAbortControllers.delete(sessionId);
    _liveEmittedByTurn.delete(prevTurn);
    _liveExtractor.reset(prevTurn);

    const nextIdx = (_liveTurnIndex.get(sessionId) ?? 0) + 1;
    _liveTurnIndex.set(sessionId, nextIdx);
    const newTurn = `${sessionId}:${nextIdx}`;
    _liveEmittedByTurn.set(newTurn, 0);
    // **중요**: AudioManager 의 expected seq 를 0 으로 미리 박아둔다.
    // 이거 안 하면 seq=1 응답이 seq=0 보다 빨리 도착했을 때 expected=1
    // 로 잠겨 seq=0 이 영영 재생 안 되는 순서 뒤바뀜 버그 발생.
    getAudioManager().registerTurnStart(newTurn, 0);
    get().addLog(sessionId, 'debug', 'TTS', `Live turn started: ${newTurn}`);
  },

  //
  // 에이전트가 토큰을 쏟아낼 때마다 호출. 누적된 streaming_text 전체를
  // 넘기면 SentenceStreamExtractor 가 이전 호출 이후 새로 완성된 문장만
  // 추출한다. 문장별로 /speak/chunks 로 단일-문장 요청을 보내서 백엔드가
  // 프런트엔드 분할을 그대로 1:1 클립으로 돌려주게 한다.
  //
  // Why 문장당 1 요청? — OmniVoice 서버 `/tts/stream` 의 parallel 구조가
  // **한 번의 HTTP 요청 안에서** 동작하지만, 우리는 이미 문장을 따로따로
  // 추출했으므로 요청 자체도 독립적으로 흘려보낼 수 있고, 그러면 TCP/HTTP
  // 레이어에서 자연스러운 파이프라이닝을 얻는다. 게다가 문장 하나가 늦어도
  // 다른 문장의 HTTP 응답은 영향을 받지 않는다 (큐 순서는 AudioManager 가
  // seq 로 엄격히 보장).
  pushStreamingText: (sessionId, fullText, emotion) => {
    if (!get().ttsEnabled) return;
    const turnId = _currentTurnId(sessionId);
    const newSentences = _liveExtractor.push(turnId, fullText);
    if (newSentences.length === 0) return;

    for (const sentence of newSentences) {
      const nextSeq = _liveEmittedByTurn.get(turnId) ?? 0;
      _liveEmittedByTurn.set(turnId, nextSeq + 1);

      // 세션당 단일 AbortController 로 턴 취소를 전파
      let controller = _liveAbortControllers.get(sessionId);
      if (!controller) {
        controller = new AbortController();
        _liveAbortControllers.set(sessionId, controller);
      }

      set((s) => ({ ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: true } }));

      // 문장당 1 HTTP 요청 — TCP 레이어에서 자연스러운 파이프라이닝을 얻고
      // 한 요청의 지연이 다른 문장의 재생에 영향을 주지 않는다. 응답 seq
      // 는 단일-문장이라 항상 0 이므로, `seqOffset` 으로 턴 전역 seq 공간
      // 으로 매핑하여 AudioManager 가 엄격 순서로 재생하도록 한다.
      void dispatchSpeakChunks(
        { sentences: [sentence], emotion, turn_id: turnId },
        {
          sessionId,
          seqOffset: nextSeq,
          onFirstClip: () => {
            get().addLog(sessionId, 'debug', 'TTS', `Live chunk enqueued seq=${nextSeq} (${sentence.slice(0, 40)}...)`);
          },
          onClipError: (_s, err) => {
            get().addLog(sessionId, 'warn', 'TTS', `Live chunk error seq=${nextSeq}: ${err}`);
          },
          onClipEnd: () => {
            const am = getAudioManager();
            if (am.queueLength === 0 && !am.isPlaying) {
              set((s) => ({ ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: false } }));
            }
          },
        },
        controller.signal,
      ).catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        console.warn('[VTuber] live chunk dispatch failed:', err);
      });
    }
  },

  //
  // 턴 종료. agent_message 가 도착한 시점이거나 user abort 시점.
  // 1) live 로 이미 클립을 뿌렸으면: extractor 의 꼬리만 flush 하여 마지막
  //    문장(들)까지 전송한다.
  // 2) live 로 아무것도 안 뿌렸으면 (스트리밍 미진입 / agent.session_id
  //    불일치 / 토큰이 한꺼번에 도착해 push 가 한 번도 호출 안 됨 등):
  //    fullText 전체를 한 클립으로 합성해 큐에 넣는다. 이 경우 별도의
  //    speakResponse 를 부르면 같은 텍스트가 두 번 발화되므로 절대 금지.
  finalizeTTSTurn: (sessionId, fullText, emotion) => {
    if (!get().ttsEnabled) return;
    const turnId = _currentTurnId(sessionId);
    const emittedSoFar = _liveEmittedByTurn.get(turnId) ?? 0;

    // extractor 잔여 + 미발화 fallback 분기
    let toSend: string[];
    if (emittedSoFar === 0) {
      // live 미발화 → fullText 전체를 한 발에. extractor 버퍼를 명시적으로
      // 비워서 이후 호출의 holding 잔여를 차단.
      _liveExtractor.reset(turnId);
      const trimmed = (fullText ?? '').trim();
      if (!trimmed) return;
      toSend = [trimmed];
    } else {
      toSend = _liveExtractor.flush(turnId, fullText);
      if (toSend.length === 0) return;
    }

    for (const sentence of toSend) {
      const nextSeq = _liveEmittedByTurn.get(turnId) ?? 0;
      _liveEmittedByTurn.set(turnId, nextSeq + 1);
      let controller = _liveAbortControllers.get(sessionId);
      if (!controller) {
        controller = new AbortController();
        _liveAbortControllers.set(sessionId, controller);
      }
      set((s) => ({ ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: true } }));
      void dispatchSpeakChunks(
        { sentences: [sentence], emotion, turn_id: turnId },
        {
          sessionId,
          seqOffset: nextSeq,
          onFirstClip: () => {
            get().addLog(sessionId, 'debug', 'TTS', `Finalize chunk enqueued seq=${nextSeq} (${sentence.slice(0, 40)}...)`);
          },
          onClipError: (_s, err) => {
            get().addLog(sessionId, 'warn', 'TTS', `Finalize chunk error seq=${nextSeq}: ${err}`);
          },
          onClipEnd: () => {
            const am = getAudioManager();
            if (am.queueLength === 0 && !am.isPlaying) {
              set((s) => ({ ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: false } }));
            }
          },
        },
        controller.signal,
      ).catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        console.warn('[VTuber] live finalize dispatch failed:', err);
      });
    }
  },
}));
