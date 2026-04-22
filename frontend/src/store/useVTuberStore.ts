import { create } from 'zustand';
import { vtuberApi, ttsApi } from '@/lib/api';
import { getAudioManager } from '@/lib/audioManager';
import { consumeSentenceStream } from '@/lib/ttsSentenceStream';
import type { Live2dModelInfo, AvatarState, VTuberLogEntry } from '@/types';

const MAX_LOGS = 500;
let _logIdCounter = 0;

// TTS fetch 취소용 AbortController (세션별)
const _ttsAbortControllers: Map<string, AbortController> = new Map();

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

      // ── Sentence-streaming path (preferred) ─────────────────────
      // 백엔드의 /speak/stream은 NDJSON으로 문장 단위 wav를 흘려보내고,
      // 첫 문장이 합성되는 즉시 client에 도착하므로 체감 latency가
      // 전체 합성 시간의 ~1/N로 줄어든다. 엔진이 sentence streaming을
      // 지원하지 않는 경우 백엔드가 단일 ``seq=0`` 프레임으로 자동
      // 폴백하므로 클라이언트 분기는 필요 없다.
      let streamResponse: Response | null = null;
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
}));
