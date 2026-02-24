import { create } from 'zustand';
import type { SessionInfo, PromptInfo } from '@/types';
import { agentApi, commandApi, healthApi } from '@/lib/api';

// Session-scoped tab IDs (must match TabNavigation)
const SESSION_TAB_IDS = new Set(['command', 'dashboard', 'logs', 'storage', 'graph', 'info']);

// ==================== Session Data Cache ====================
export interface SessionData {
  input: string;
  output: string;
  status: string;
  statusText: string;
}

// ==================== App Store ====================
interface AppState {
  // Sessions
  sessions: SessionInfo[];
  deletedSessions: SessionInfo[];
  selectedSessionId: string | null;
  sessionDataCache: Record<string, SessionData>;

  // Health
  healthStatus: string;
  healthData: { pod_name: string; pod_ip: string; redis: string } | null;

  // Prompts
  prompts: PromptInfo[];
  promptContents: Record<string, string>;

  // UI state
  activeTab: string;
  sidebarCollapsed: boolean;
  isExecuting: boolean;
  deletedSectionOpen: boolean;

  // Actions
  loadSessions: () => Promise<void>;
  loadDeletedSessions: () => Promise<void>;
  selectSession: (id: string | null) => void;
  createSession: (data: Parameters<typeof agentApi.create>[0]) => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  permanentDeleteSession: (id: string) => Promise<void>;
  restoreSession: (id: string) => Promise<void>;
  setActiveTab: (tab: string) => void;
  toggleSidebar: () => void;
  toggleDeletedSection: () => void;
  checkHealth: () => Promise<void>;
  loadPrompts: () => Promise<void>;
  loadPromptContent: (name: string) => Promise<string | null>;
  getSessionData: (id: string) => SessionData;
  updateSessionData: (id: string, data: Partial<SessionData>) => void;
  setIsExecuting: (v: boolean) => void;
}

const defaultSessionData: SessionData = {
  input: '',
  output: 'No output yet',
  status: '',
  statusText: '',
};

export const useAppStore = create<AppState>((set, get) => ({
  sessions: [],
  deletedSessions: [],
  selectedSessionId: null,
  sessionDataCache: {},
  healthStatus: 'connecting',
  healthData: null,
  prompts: [],
  promptContents: {},
  activeTab: 'main',
  sidebarCollapsed: false,
  isExecuting: false,
  deletedSectionOpen: false,

  loadSessions: async () => {
    try {
      const sessions = await agentApi.list();
      set({ sessions });
    } catch (e) {
      console.error('Failed to load sessions:', e);
    }
  },

  loadDeletedSessions: async () => {
    try {
      const deletedSessions = await agentApi.listDeleted();
      set({ deletedSessions });
    } catch {
      // ignore
    }
  },

  selectSession: (id) => {
    const { activeTab } = get();
    const updates: Partial<AppState> = { selectedSessionId: id };
    if (id && !SESSION_TAB_IDS.has(activeTab)) {
      // Selecting a session while on a global tab → jump to Command
      updates.activeTab = 'command';
    } else if (!id && SESSION_TAB_IDS.has(activeTab)) {
      // Deselecting session while on a session tab → fall back to Main
      updates.activeTab = 'main';
    }
    set(updates);
  },

  createSession: async (data) => {
    await agentApi.create(data);
    await get().loadSessions();
  },

  deleteSession: async (id) => {
    await agentApi.delete(id);
    const state = get();
    if (state.selectedSessionId === id) {
      set({ selectedSessionId: null });
    }
    const { sessionDataCache, ...rest } = state;
    const newCache = { ...sessionDataCache };
    delete newCache[id];
    set({ sessionDataCache: newCache });
    await state.loadSessions();
    await state.loadDeletedSessions();
  },

  permanentDeleteSession: async (id) => {
    await agentApi.permanentDelete(id);
    await get().loadDeletedSessions();
  },

  restoreSession: async (id) => {
    await agentApi.restore(id);
    await get().loadSessions();
    await get().loadDeletedSessions();
  },

  setActiveTab: (tab) => set({ activeTab: tab }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  toggleDeletedSection: () => set((s) => ({ deletedSectionOpen: !s.deletedSectionOpen })),

  checkHealth: async () => {
    try {
      const health = await healthApi.check();
      set({
        healthStatus: health.status === 'healthy' ? 'connected' : 'disconnected',
        healthData: { pod_name: health.pod_name, pod_ip: health.pod_ip, redis: health.redis },
      });
    } catch {
      set({ healthStatus: 'disconnected' });
    }
  },

  loadPrompts: async () => {
    try {
      const res = await commandApi.getPrompts();
      set({ prompts: res.prompts || [] });
    } catch {
      // ignore
    }
  },

  loadPromptContent: async (name) => {
    const cached = get().promptContents[name];
    if (cached) return cached;
    try {
      const res = await commandApi.getPromptContent(name);
      set((s) => ({ promptContents: { ...s.promptContents, [name]: res.content } }));
      return res.content;
    } catch {
      return null;
    }
  },

  getSessionData: (id) => {
    return get().sessionDataCache[id] || { ...defaultSessionData };
  },

  updateSessionData: (id, data) => {
    set((s) => ({
      sessionDataCache: {
        ...s.sessionDataCache,
        [id]: { ...(s.sessionDataCache[id] || { ...defaultSessionData }), ...data },
      },
    }));
  },

  setIsExecuting: (v) => set({ isExecuting: v }),
}));
