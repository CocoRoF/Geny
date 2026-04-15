import { create } from 'zustand';
import { vtuberApi, ttsApi } from '@/lib/api';
import { getAudioManager } from '@/lib/audioManager';
import type { Live2dModelInfo, AvatarState, VTuberLogEntry } from '@/types';

const MAX_LOGS = 500;
let _logIdCounter = 0;

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
    set((s) => ({ ttsEnabled: !s.ttsEnabled }));
  },

  setTTSVolume: (vol) => {
    const clamped = Math.max(0, Math.min(1, vol));
    set({ ttsVolume: clamped });
    getAudioManager().setVolume(clamped);
  },

  speakResponse: async (sessionId, text, emotion) => {
    const { ttsEnabled } = get();
    if (!ttsEnabled) return;

    try {
      set((s) => ({
        ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: true },
      }));
      get().addLog(sessionId, 'info', 'TTS', `Speaking: "${text.slice(0, 50)}..." (${emotion})`);

      const response = await ttsApi.speak(sessionId, text, emotion);
      const audioManager = getAudioManager();
      audioManager.setVolume(get().ttsVolume);

      await audioManager.playTTSResponse(
        response,
        () => {
          get().addLog(sessionId, 'debug', 'TTS', 'Audio playback started');
        },
        () => {
          set((s) => ({
            ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: false },
          }));
          get().addLog(sessionId, 'debug', 'TTS', 'Audio playback ended');
        },
      );
    } catch (err) {
      console.error('[VTuber] TTS speak error:', err);
      set((s) => ({
        ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: false },
      }));
      get().addLog(sessionId, 'error', 'TTS', `Speak failed: ${err}`);
    }
  },

  stopSpeaking: (sessionId) => {
    getAudioManager().stop();
    set((s) => ({
      ttsSpeaking: { ...s.ttsSpeaking, [sessionId]: false },
    }));
    get().addLog(sessionId, 'info', 'TTS', 'Playback stopped');
  },
}));
