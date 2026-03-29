import { create } from 'zustand';
import { vtuberApi } from '@/lib/api';
import type { Live2dModelInfo, AvatarState } from '@/types';

interface VTuberState {
  // Models
  models: Live2dModelInfo[];
  modelsLoaded: boolean;

  // Per-session: assigned model name
  assignments: Record<string, string>;

  // Per-session: latest avatar state
  avatarStates: Record<string, AvatarState>;

  // SSE subscriptions (keyed by session_id)
  _subs: Record<string, { close: () => void }>;

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
}

export const useVTuberStore = create<VTuberState>((set, get) => ({
  models: [],
  modelsLoaded: false,
  assignments: {},
  avatarStates: {},
  _subs: {},

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
    } catch (err) {
      console.error('[VTuber] Failed to assign model:', err);
      throw err;
    }
  },

  unassignModel: async (sessionId) => {
    try {
      await vtuberApi.unassignModel(sessionId);
      set((s) => {
        const { [sessionId]: _, ...rest } = s.assignments;
        return { assignments: rest };
      });
      // Cleanup SSE subscription
      get().unsubscribeAvatar(sessionId);
    } catch (err) {
      console.error('[VTuber] Failed to unassign model:', err);
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
    });

    set((s) => ({
      _subs: { ...s._subs, [sessionId]: sub },
    }));
  },

  unsubscribeAvatar: (sessionId) => {
    const { _subs } = get();
    _subs[sessionId]?.close();
    set((s) => {
      const { [sessionId]: _, ...rest } = s._subs;
      return { _subs: rest };
    });
  },

  setEmotion: async (sessionId, emotion) => {
    try {
      await vtuberApi.setEmotion(sessionId, emotion);
    } catch (err) {
      console.error('[VTuber] Failed to set emotion:', err);
    }
  },

  interact: async (sessionId, hitArea, x, y) => {
    try {
      await vtuberApi.interact(sessionId, hitArea, x, y);
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
}));
