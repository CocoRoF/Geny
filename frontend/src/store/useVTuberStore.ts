import { create } from 'zustand';
import { vtuberApi, ttsApi, configApi } from '@/lib/api';
import { getAudioManager } from '@/lib/audioManager';
import { consumeSentenceStream } from '@/lib/ttsSentenceStream';
import { dispatchSpeakChunks } from '@/lib/ttsChunkStream';
import { SentenceStreamExtractor } from '@/lib/sentenceBoundaryDetector';
import { voiceSentence } from '@/lib/speechEmotion';
import type { Live2dModelInfo, AvatarState, VTuberLogEntry } from '@/types';

const MAX_LOGS = 500;
let _logIdCounter = 0;

// ── Overlay tuning settings — persisted to localStorage so the avatar
//    window remembers TTS volume / STT tuning / screen-capture choices
//    across reloads + connector restarts. ──
const OVERLAY_SETTINGS_KEY = 'geny_vtuber_overlay_settings';
export interface OverlaySettings {
  // ON/OFF toggle states — remembered per-machine so the avatar comes back
  // the way the user left it. STT/screen-observation auto-RESUME on reload
  // (their consuming hooks start capture when their `enabled` is true at
  // mount); in a plain browser, screen-share can't auto-start without a user
  // gesture, so the hook self-corrects the flag back to false in that case.
  ttsEnabled: boolean;
  sttEnabled: boolean;
  screenObservationEnabled: boolean;
  realtimePartialsEnabled: boolean; // live "you're saying…" captions in hands-free
  // Audio device routing, by LABEL ('' = system default). deviceId isn't
  // portable across origins, so we remember the label and resolve it here.
  audioOutputLabel: string;   // TTS output device (e.g. a VoiceMeeter cable)
  audioInputLabel: string;    // mic input device
  ttsVolume: number;          // 0..1 output volume
  sttSensitivity: number;     // VAD speech threshold (lower = more sensitive)
  sttSilenceMs: number;       // silence trail before an utterance ends (ms)
  sttEchoCancellation: boolean;
  sttNoiseSuppression: boolean;
  sttAutoGain: boolean;
  screenIntervalMs: number;   // auto-capture cadence (ms)
  screenSourceId: string | null; // chosen capture source id (null = first screen)
  // How proactively the avatar comments on the screen while observation is ON.
  // Sent to the backend, which maps it to (min_gap, change_threshold, max_silence)
  // and a speak-bias. Also drives the default capture cadence below.
  screenTalkativeness: ScreenTalkativeness;
}
export type ScreenTalkativeness = 'chatty' | 'balanced' | 'calm';
// Default capture cadence per level (ms). The change-gate on the backend means
// a fast cadence still only triggers speech when the screen actually changes.
export const SCREEN_INTERVAL_BY_LEVEL: Record<ScreenTalkativeness, number> = {
  chatty: 45_000,
  balanced: 75_000,
  calm: 120_000,
};
const OVERLAY_SETTINGS_DEFAULTS: OverlaySettings = {
  ttsEnabled: true,           // audio output on by default
  sttEnabled: false,          // mic opt-in
  screenObservationEnabled: false, // screen-capture opt-in
  realtimePartialsEnabled: true,   // live captions on by default (lightweight)
  audioOutputLabel: '',            // '' = system default output
  audioInputLabel: '',             // '' = system default mic
  ttsVolume: 0.7,
  sttSensitivity: 0.04,
  sttSilenceMs: 1200,
  sttEchoCancellation: true,
  sttNoiseSuppression: true,
  sttAutoGain: true,
  screenTalkativeness: 'chatty',     // user-chosen default: 웬만하면 발화
  screenIntervalMs: SCREEN_INTERVAL_BY_LEVEL.chatty,
  screenSourceId: null,
};
function loadOverlaySettings(): OverlaySettings {
  if (typeof window === 'undefined') return { ...OVERLAY_SETTINGS_DEFAULTS };
  try {
    const raw = window.localStorage.getItem(OVERLAY_SETTINGS_KEY);
    if (!raw) return { ...OVERLAY_SETTINGS_DEFAULTS };
    return { ...OVERLAY_SETTINGS_DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return { ...OVERLAY_SETTINGS_DEFAULTS };
  }
}
function persistOverlaySettings(patch: Partial<OverlaySettings>): void {
  if (typeof window === 'undefined') return;
  try {
    const merged = { ...loadOverlaySettings(), ...patch };
    window.localStorage.setItem(OVERLAY_SETTINGS_KEY, JSON.stringify(merged));
  } catch {
    /* ignore quota / privacy-mode errors */
  }
}

// TTS fetch 취소용 AbortController (세션별)
const _ttsAbortControllers: Map<string, AbortController> = new Map();

// ── Live-stream sentence TTS (chat-stream pre-emit) ──────────────
// LLM 토큰이 쏟아지는 동안 이미 완성된 문장을 즉시 /speak/chunks 로 보내서
// 사용자가 첫 음성을 듣는 시점을 agent_message turn-end 이전으로 앞당긴다.
//
// 턴 ID 규칙:  `${sessionId}:${turnIndex}`
//   - 사용자가 새 메시지를 보낼 때 turnIndex++ 하여 새 스코프를 연다.
//   - **이전 턴의 잔여 클립은 폐기하지 않고** 자연스럽게 완주시킨다.
//     (사용자가 STOP 버튼을 누른 경우만 명시적 폐기 — stopSpeaking)
//   - AudioManager 의 큐는 turn 단위 FIFO 로 누적 — 챗0 클립 전부가
//     끝난 다음에야 챗1 클립이 재생되므로 자연스러운 대화 순서 유지.
//
// AbortController 키는 **턴별** (sessionId:turnIndex). 세션별 단일 컨트
// 롤러로 묶으면 새 턴에서 만든 컨트롤러가 이전 턴의 in-flight HTTP 까지
// 끊어 챗0 의 합성된 오디오가 영영 안 도착함 → 같은 챗 안에서 잠식.
const _liveTurnIndex: Map<string, number> = new Map();
const _liveAbortControllersByTurn: Map<string, AbortController> = new Map();
const _liveEmittedByTurn: Map<string, number> = new Map(); // turnId → next seq
// turnId → the emotion the next sentence inherits (a cue carries until the next).
const _liveEmotionByTurn: Map<string, string> = new Map();
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

  // Singleton SSE subscription for `/api/vtuber/models/stream`.
  // Established lazily on first fetchModels() and stays open for the
  // app's lifetime — the dropdown reflects auto-publish renames /
  // installs / deletes in real time off this stream.
  _modelsStreamSub: { close: () => void } | null;
  _assignmentStreamSub: { close: () => void } | null;

  // TTS state
  ttsEnabled: boolean;
  ttsSpeaking: Record<string, boolean>;
  ttsVolume: number;

  // Per-session live subtitle (the avatar overlay's bottom dialogue box). Mirrors
  // what the VTuber is saying: `streaming` true while the response streams in,
  // false once the turn's final message lands / the broadcast is done. The
  // overlay shows it and dismisses ~3s after it settles (and, with TTS, after the
  // voice finishes).
  subtitle: Record<string, { text: string; streaming: boolean }>;

  // STT (V2 voice-notes follow-up) — when on, the user's mic is
  // streamed via the VAD recorder into the inbox as audio captures
  // + auto-spotlighted so the VTuber sees [USER_SHARED] triggers
  // for each utterance. Default OFF — must be explicitly enabled
  // per session.
  sttEnabled: boolean;

  // Screen observation (V3) — when on, the browser holds a
  // persistent ``getDisplayMedia`` MediaStream and a 3-min timer
  // captures a frame, ships it to ``/api/vtuber/screen-observation/upload``
  // along with the session id. Backend persists into session
  // storage, vision-captions, and (subject to cooldown) fires
  // ``[USER_OBSERVATION]``. Default OFF — must be explicitly
  // enabled per session, browser permission requested once.
  screenObservationEnabled: boolean;

  // Realtime voice mode (2026-07) — full-duplex hands-free conversation via
  // the /ws/voice/realtime WebSocket. Mutually exclusive with sttEnabled
  // (both drive the mic). Transient (not persisted) — a live mode, defaults
  // OFF each session. See RealtimeVoiceDriver.
  realtimeVoiceEnabled: boolean;
  // Input pipeline for realtime voice:
  //   'server_vad' — stream raw PCM; the backend Silero VAD decides
  //                  end-of-speech (true realtime, default).
  //   'client_vad' — the browser segments utterances and uploads blobs.
  realtimeInputMode: 'server_vad' | 'client_vad';
  // Live feedback so the user SEES realtime voice working:
  //   realtimeListening — true while the server VAD hears speech.
  //   realtimePartial   — interim transcript of the current utterance.
  realtimeListening: boolean;
  realtimePartial: string;
  //   realtimePartialStable — char count of the settled prefix of realtimePartial
  //   (rendered solid; the tail after it is faded, so the caption doesn't flicker).
  realtimePartialStable: number;
  //   realtimePartialsEnabled — show live captions while speaking (persisted).
  realtimePartialsEnabled: boolean;
  //   audio device routing by label (persisted; '' = system default).
  audioOutputLabel: string;
  audioInputLabel: string;

  // ── Persisted overlay tuning (see OverlaySettings) ──
  sttSensitivity: number;
  sttSilenceMs: number;
  sttEchoCancellation: boolean;
  sttNoiseSuppression: boolean;
  sttAutoGain: boolean;
  screenIntervalMs: number;
  screenSourceId: string | null;
  screenTalkativeness: ScreenTalkativeness;

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

  // Subtitle actions
  /** Set the live subtitle text + whether it's still streaming. */
  setSubtitle: (sessionId: string, text: string, streaming: boolean) => void;
  /** Mark the subtitle as no longer streaming (turn done) without changing text. */
  settleSubtitle: (sessionId: string) => void;

  // STT actions
  toggleSTT: () => void;
  setSTTEnabled: (enabled: boolean) => void;

  // Realtime voice actions (mutually exclusive with STT)
  toggleRealtimeVoice: () => void;
  setRealtimeVoiceEnabled: (enabled: boolean) => void;
  setRealtimeInputMode: (mode: 'server_vad' | 'client_vad') => void;
  setRealtimeListening: (listening: boolean) => void;
  setRealtimePartial: (text: string, stable?: number) => void;
  setRealtimePartialsEnabled: (enabled: boolean) => void;
  setAudioDevices: (patch: { audioOutputLabel?: string; audioInputLabel?: string }) => void;

  // Screen-observation actions (V3)
  toggleScreenObservation: () => void;
  setScreenObservationEnabled: (enabled: boolean) => void;

  // Persisted overlay tuning setters (write-through to localStorage)
  setSttSettings: (patch: Partial<Pick<VTuberState,
    'sttSensitivity' | 'sttSilenceMs' | 'sttEchoCancellation' | 'sttNoiseSuppression' | 'sttAutoGain'>>) => void;
  setScreenSettings: (patch: Partial<Pick<VTuberState, 'screenIntervalMs' | 'screenSourceId' | 'screenTalkativeness'>>) => void;
  /** Pick a talkativeness level → also resets the capture cadence to that
   *  level's default (the user can still fine-tune the interval after). */
  setScreenTalkativeness: (level: ScreenTalkativeness) => void;

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
  _modelsStreamSub: null,
  _assignmentStreamSub: null,
  ttsSpeaking: {},
  subtitle: {},
  realtimeVoiceEnabled: false,  // transient live mode — always OFF on load
  realtimeInputMode: 'server_vad',  // backend Silero VAD by default
  realtimeListening: false,
  realtimePartial: '',
  realtimePartialStable: 0,
  // realtimePartialsEnabled is hydrated below via ...loadOverlaySettings().
  // Persisted per-machine settings hydrated from localStorage: ON/OFF toggles
  // (ttsEnabled default ON; sttEnabled / screenObservationEnabled default OFF)
  // AND the tuning knobs (TTS volume, STT thresholds, screen interval/source).
  // Hydrating an "on" toggle auto-resumes its capture on load (user opted in).
  ...loadOverlaySettings(),

  fetchModels: async () => {
    try {
      const res = await vtuberApi.listModels();
      set({ models: res.models, modelsLoaded: true });
    } catch (err) {
      console.error('[VTuber] Failed to fetch models:', err);
    }
    // Wire the live model-registry stream on first fetch so subsequent
    // auto-publish renames / installs / deletes propagate to the
    // dropdown without the user having to refresh the page. Singleton —
    // a single SSE connection serves every VTuberPanel mount.
    if (!get()._modelsStreamSub) {
      const sub = vtuberApi.subscribeToModelChanges(() => {
        // Backend signalled a registry change — pull the new list.
        // Active assignments are keyed by model.name which the backend
        // preserves across renames, so the dropdown re-renders the new
        // display_name automatically once `models` updates.
        void get().fetchModels();
      });
      set({ _modelsStreamSub: sub });
    }
    // Live assignment stream — keeps web / connector / overlay in sync the
    // instant a model is (re)assigned anywhere, NO polling. Singleton too.
    if (!get()._assignmentStreamSub) {
      const sub = vtuberApi.subscribeToAssignmentChanges((sessionId, modelName) => {
        set((s) => {
          const next = { ...s.assignments };
          if (modelName) next[sessionId] = modelName;
          else delete next[sessionId];
          return { assignments: next };
        });
      });
      set({ _assignmentStreamSub: sub });
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
    persistOverlaySettings({ ttsEnabled: newEnabled });

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
    persistOverlaySettings({ ttsVolume: clamped });
  },

  // ─── STT Actions ───

  toggleSTT: () => {
    const next = !get().sttEnabled;
    set({ sttEnabled: next });
    persistOverlaySettings({ sttEnabled: next });
    // STT and realtime voice both own the mic — never both on.
    if (next && get().realtimeVoiceEnabled) {
      set({ realtimeVoiceEnabled: false });
    }
  },

  setSTTEnabled: (enabled) => {
    set({ sttEnabled: enabled });
    persistOverlaySettings({ sttEnabled: enabled });
    // STT and realtime voice both own the mic — never both on.
    if (enabled && get().realtimeVoiceEnabled) {
      set({ realtimeVoiceEnabled: false });
    }
  },

  // ─── Realtime voice Actions (mutually exclusive with STT) ───

  toggleRealtimeVoice: () => {
    const next = !get().realtimeVoiceEnabled;
    set({ realtimeVoiceEnabled: next });
    // Turning realtime on releases the STT mic path (single mic owner).
    if (next && get().sttEnabled) {
      set({ sttEnabled: false });
      persistOverlaySettings({ sttEnabled: false });
    }
  },

  setRealtimeVoiceEnabled: (enabled) => {
    set({ realtimeVoiceEnabled: enabled });
    if (enabled && get().sttEnabled) {
      set({ sttEnabled: false });
      persistOverlaySettings({ sttEnabled: false });
    }
  },

  setRealtimeInputMode: (mode) => set({ realtimeInputMode: mode }),
  setRealtimeListening: (listening) => set({ realtimeListening: listening }),
  setRealtimePartial: (text, stable) => set({ realtimePartial: text, realtimePartialStable: stable ?? 0 }),
  setRealtimePartialsEnabled: (enabled) => {
    set({ realtimePartialsEnabled: enabled });
    persistOverlaySettings({ realtimePartialsEnabled: enabled });
  },
  setAudioDevices: (patch) => {
    set(patch);
    persistOverlaySettings(patch);
    // Apply to the live routing layer (TTS output sink + mic input target).
    void import('@/lib/audioDevices').then(({ audioRouting }) => {
      if (typeof patch.audioOutputLabel === 'string') audioRouting.setOutputLabel(patch.audioOutputLabel);
      if (typeof patch.audioInputLabel === 'string') audioRouting.setInputLabel(patch.audioInputLabel);
    });
  },

  // ─── Screen-observation Actions (V3) ───

  toggleScreenObservation: () => {
    const next = !get().screenObservationEnabled;
    set({ screenObservationEnabled: next });
    persistOverlaySettings({ screenObservationEnabled: next });
  },

  setScreenObservationEnabled: (enabled) => {
    set({ screenObservationEnabled: enabled });
    persistOverlaySettings({ screenObservationEnabled: enabled });
  },

  // ─── Persisted overlay tuning ───

  setSttSettings: (patch) => {
    set(patch);
    persistOverlaySettings(patch);
  },

  setScreenSettings: (patch) => {
    set(patch);
    persistOverlaySettings(patch);
  },

  setScreenTalkativeness: (level) => {
    // Switching level also snaps the capture cadence to that level's default.
    const patch = {
      screenTalkativeness: level,
      screenIntervalMs: SCREEN_INTERVAL_BY_LEVEL[level],
    };
    set(patch);
    persistOverlaySettings(patch);
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
    // 진행 중인 단발 TTS fetch 취소
    const controller = _ttsAbortControllers.get(sessionId);
    if (controller) {
      controller.abort();
      _ttsAbortControllers.delete(sessionId);
    }
    // **명시적 STOP 경로** — 이 세션의 모든 live turn HTTP 도 함께 abort.
    // 평상시(beginTTSTurn) 에서는 절대 abort 하면 안 됨 — 이전 턴 클립이
    // 잠식되어 사라짐. 사용자가 STOP 버튼을 누른 경우만 여기로 들어옴.
    const sessionPrefix = `${sessionId}:`;
    for (const [turnId, ac] of _liveAbortControllersByTurn) {
      if (turnId.startsWith(sessionPrefix)) {
        ac.abort();
        _liveAbortControllersByTurn.delete(turnId);
      }
    }
    // clearQueue: 큐의 모든 대기 아이템 비우기 + 현재 재생 중지
    // 각 아이템의 onEnd 콜백이 호출되어 ttsSpeaking 상태가 정리됨
    getAudioManager().clearQueue();
    set((s) => ({
      ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: false },
    }));
    get().addLog(sessionId, 'info', 'TTS', 'Playback stopped (queue cleared)');
  },

  // ── Subtitle (avatar overlay bottom dialogue box) ─────────────────
  setSubtitle: (sessionId, text, streaming) =>
    set((s) => ({ subtitle: { ...s.subtitle, [sessionId]: { text, streaming } } })),
  settleSubtitle: (sessionId) =>
    set((s) =>
      s.subtitle[sessionId] && s.subtitle[sessionId].streaming
        ? { subtitle: { ...s.subtitle, [sessionId]: { ...s.subtitle[sessionId], streaming: false } } }
        : s,
    ),

  // ── Live chat-stream pre-emit TTS ─────────────────────────────────
  //
  // 새 유저 메시지 시작 시 호출. **이전 턴은 손대지 않는다** — AudioManager
  // 큐가 turn 단위로 FIFO 누적되어 챗0 클립이 모두 재생된 다음 챗1 클립이
  // 자연스럽게 이어지도록 한다. (이전엔 clearTurn + abort 로 챗0 클립을
  // 파괴해서 "앞선 챗 잠식" 버그 발생.)
  //
  // 명시적 폐기는 사용자가 STOP 버튼을 눌렀을 때 (stopSpeaking) 만.
  beginTTSTurn: (sessionId) => {
    // 이전 턴이 finalize 되지 않은 상태에서 새 턴이 시작되면 (예: assistant
    // _message 가 아직 안 왔거나, 빈 응답으로 early return 됐거나), AudioManager
    // 가 영영 이전 턴 drain 을 기다리며 새 턴 클립 재생을 막을 수 있다.
    // → 새 턴 시작 자체가 "이전 턴엔 더 이상 dispatch 가 없다" 는 강한 신호.
    const prevTurn = _currentTurnId(sessionId);
    if (_liveTurnIndex.has(sessionId)) {
      getAudioManager().markTurnFinalized(prevTurn);
    }

    const nextIdx = (_liveTurnIndex.get(sessionId) ?? 0) + 1;
    _liveTurnIndex.set(sessionId, nextIdx);
    const newTurn = `${sessionId}:${nextIdx}`;
    _liveEmittedByTurn.set(newTurn, 0);
    _liveEmotionByTurn.delete(newTurn);
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

    for (const raw of newSentences) {
      // The sentence in its own voice, with the cues taken out of it.
      const voiced = voiceSentence(raw, _liveEmotionByTurn.get(turnId) ?? emotion);
      _liveEmotionByTurn.set(turnId, voiced.carry);
      const sentence = voiced.text;
      if (!sentence) continue;
      const nextSeq = _liveEmittedByTurn.get(turnId) ?? 0;
      _liveEmittedByTurn.set(turnId, nextSeq + 1);

      // **턴별** AbortController. 세션별 단일 컨트롤러로 묶으면 새 턴이
      // 시작될 때 이전 턴의 in-flight HTTP 까지 끊겨서 합성된 오디오가
      // 영영 도착 안 함 (= 앞선 챗 잠식 버그).
      let controller = _liveAbortControllersByTurn.get(turnId);
      if (!controller) {
        controller = new AbortController();
        _liveAbortControllersByTurn.set(turnId, controller);
      }

      set((s) => ({ ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: true } }));

      // Inter-turn FIFO 신호: dispatch 주 바로 앞에서 +1, 응답이 끝나면 -1.
      // 이 카운터가 0 이고 markTurnFinalized 가 숨으면 턴이 drained 되어
      // AudioManager 가 다음 턴 클립 재생을 개시한다.
      getAudioManager().noteTurnDispatch(turnId);

      // 문장당 1 HTTP 요청 — TCP 레이어에서 자연스러운 파이프라이닝을 얻고
      // 한 요청의 지연이 다른 문장의 재생에 영향을 주지 않는다. 응답 seq
      // 는 단일-문장이라 항상 0 이므로, `seqOffset` 으로 턴 전역 seq 공간
      // 으로 매핑하여 AudioManager 가 엄격 순서로 재생하도록 한다.
      void dispatchSpeakChunks(
        { sentences: [sentence], emotion: voiced.emotion, turn_id: turnId },
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
      )
        .catch((err) => {
          if (err instanceof DOMException && err.name === 'AbortError') return;
          console.warn('[VTuber] live chunk dispatch failed:', err);
        })
        .finally(() => {
          // 성공/실패/취소 무관 pending counter 원상복구
          getAudioManager().noteTurnReceive(turnId);
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
      _liveEmotionByTurn.delete(turnId);
      const trimmed = (fullText ?? '').trim();
      if (!trimmed) return;
      toSend = [trimmed];
    } else {
      toSend = _liveExtractor.flush(turnId, fullText);
      if (toSend.length === 0) return;
    }

    for (const raw of toSend) {
      const voiced = voiceSentence(raw, _liveEmotionByTurn.get(turnId) ?? emotion);
      _liveEmotionByTurn.set(turnId, voiced.carry);
      const sentence = voiced.text;
      if (!sentence) continue;
      const nextSeq = _liveEmittedByTurn.get(turnId) ?? 0;
      _liveEmittedByTurn.set(turnId, nextSeq + 1);
      // 턴별 AbortController 재사용 (pushStreamingText 가 만든 것과 동일).
      let controller = _liveAbortControllersByTurn.get(turnId);
      if (!controller) {
        controller = new AbortController();
        _liveAbortControllersByTurn.set(turnId, controller);
      }
      set((s) => ({ ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: true } }));
      getAudioManager().noteTurnDispatch(turnId);
      void dispatchSpeakChunks(
        { sentences: [sentence], emotion: voiced.emotion, turn_id: turnId },
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
      )
        .catch((err) => {
          if (err instanceof DOMException && err.name === 'AbortError') return;
          console.warn('[VTuber] live finalize dispatch failed:', err);
        })
        .finally(() => {
          getAudioManager().noteTurnReceive(turnId);
        });
    }
    // 더 이상 새 dispatch 가 없을 것임을 AudioManager 에 알린다.
    // 이 호출 다음, pending=0 이 되는 순간 턴은 drained 가 되어
    // 다음 턴으로 이행 가능하다.
    getAudioManager().markTurnFinalized(turnId);
  },
}));

