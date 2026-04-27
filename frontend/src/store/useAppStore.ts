import { create } from 'zustand';
import type { SessionInfo, PromptInfo } from '@/types';
import { agentApi, commandApi, healthApi, configApi } from '@/lib/api';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';

// Session-scoped tab IDs (must match TabNavigation)
const SESSION_TAB_IDS = new Set([
  'command',
  'logs',
  'storage',
  'sessionEnvironment', // consolidated session-env tab
  'environment',        // back-compat alias
  'graph',              // back-compat alias
  'info',
  'sessionTools',       // legacy direct mount
  'tools',              // legacy
  'dashboard',
  'memory',
  'tasks',
  'cron',
  'vtuber',
]);

// ==================== Session Data Cache ====================

/**
 * A pending HITL approval surfaced by Stage 15 (geny-executor 1.0+).
 *
 * Mirrors the payload the backend emits via `session_logger.log_stage_event`
 * with `event_type='hitl_request'` (see `service/executor/agent_session.py`
 * around line 1682). The full executor-side payload comes through under
 * `data` so the modal can render whatever the reviewer attached
 * (tool name, args, guard chain, …) without us having to model it
 * field-by-field.
 */
export interface PendingHitlRequest {
  token: string;
  reason: string;
  severity: string;
  /** Raw event payload (tool name, args, guard chain hits, …). */
  data: Record<string, unknown>;
  /** Wall-clock instant when the request entered the cache. */
  receivedAt: number;
}

export interface SessionData {
  input: string;
  output: string;
  status: string;
  statusText: string;
  logEntries?: Array<{ timestamp: string; level: string; message: string; metadata?: Record<string, unknown> }>;
  /**
   * Pending Stage 15 (HITL) approval, if any. Set by the WS event
   * handler on `hitl_request`, cleared on `hitl_decision` / `hitl_timeout`
   * for the same token, or on a successful resume from the modal.
   */
  pendingHitl?: PendingHitlRequest | null;
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
  // Sub-tab selection inside the consolidated Environment tab.
  // Keyed separately because the global Environment tab and the
  // session-scoped Environment tab share no semantics.
  envSubTab: string;       // global: library/toolSets/toolCatalog/permissions/hooks/skills/mcpServers
  sessionEnvSubTab: string; // session: manifest/tools/workspace
  sidebarCollapsed: boolean;
  mobileSidebarOpen: boolean;
  deletedSectionOpen: boolean;
  devMode: boolean;
  userName: string;
  userTitle: string;

  // Actions
  loadSessions: () => Promise<void>;
  loadDeletedSessions: () => Promise<void>;
  selectSession: (id: string | null) => void;
  createSession: (data: Parameters<typeof agentApi.create>[0]) => Promise<SessionInfo>;
  deleteSession: (id: string) => Promise<void>;
  permanentDeleteSession: (id: string) => Promise<void>;
  restoreSession: (id: string) => Promise<void>;
  setActiveTab: (tab: string) => void;
  setEnvSubTab: (id: string) => void;
  setSessionEnvSubTab: (id: string) => void;
  toggleSidebar: () => void;
  setMobileSidebarOpen: (open: boolean) => void;
  toggleDeletedSection: () => void;
  toggleDevMode: () => void;
  hydrateDevMode: () => void;
  checkHealth: () => Promise<void>;
  loadPrompts: () => Promise<void>;
  loadPromptContent: (name: string) => Promise<string | null>;
  loadUserName: () => Promise<void>;
  getSessionData: (id: string) => SessionData;
  updateSessionData: (id: string, data: Partial<SessionData>) => void;
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
  envSubTab: 'library',
  sessionEnvSubTab: 'manifest',
  sidebarCollapsed: false,
  mobileSidebarOpen: false,
  deletedSectionOpen: false,
  devMode: true,
  userName: '',
  userTitle: '',

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
    const { activeTab, sessions } = get();
    const updates: Partial<AppState> = { selectedSessionId: id };
    if (id && !SESSION_TAB_IDS.has(activeTab)) {
      // Selecting a session while on a global tab → jump to appropriate tab
      const session = sessions.find(s => s.session_id === id);
      updates.activeTab = session?.role === 'vtuber' ? 'vtuber' : 'command';
    } else if (!id && SESSION_TAB_IDS.has(activeTab)) {
      // Deselecting session while on a session tab → fall back to Main
      updates.activeTab = 'main';
    }
    set(updates);
  },

  createSession: async (data) => {
    const session = await agentApi.create(data);
    await get().loadSessions();
    if (session.env_id) {
      useEnvironmentStore.getState().invalidateDrawerSessionsForEnv(session.env_id);
    }
    return session;
  },

  deleteSession: async (id) => {
    const state = get();
    const priorEnvId = state.sessions.find(s => s.session_id === id)?.env_id;
    await agentApi.delete(id);
    if (state.selectedSessionId === id) {
      set({ selectedSessionId: null });
    }
    const { sessionDataCache } = state;
    const newCache = { ...sessionDataCache };
    delete newCache[id];
    set({ sessionDataCache: newCache });
    await state.loadSessions();
    await state.loadDeletedSessions();
    if (priorEnvId) {
      useEnvironmentStore.getState().invalidateDrawerSessionsForEnv(priorEnvId);
    }
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

  setActiveTab: (tab) => {
    // Back-compat: pipeline-component tabs that became sub-tabs
    // redirect to the right scope:
    //   - Global pipeline-design sub-tabs   → `library`
    //   - Per-session env sub-tabs          → `sessionEnvironment`
    //
    // CRITICAL: legacy `environment` was always the session-scoped
    // tab (sidebar / persisted state). It MUST redirect to
    // sessionEnvironment, not the global Library — that collision
    // was the bug that bounced operators back to "select a session"
    // when clicking Library.
    const LIBRARY_SUB_REDIRECT: Record<string, string> = {
      toolSets: 'toolSets',
      // PR-Merge — toolCatalog collapsed into the unified Tool Sets tab.
      toolCatalog: 'toolSets',
      permissions: 'permissions',
      hooks: 'hooks',
      skills: 'skills',
      mcpServers: 'mcpServers',
      environments: 'library',
      builder: 'library',
    };
    const SESSION_ENV_SUB_REDIRECT: Record<string, string> = {
      environment: 'manifest', // legacy session-env id
      graph: 'manifest',
      sessionTools: 'tools',
    };
    if (LIBRARY_SUB_REDIRECT[tab]) {
      set({ activeTab: 'library', envSubTab: LIBRARY_SUB_REDIRECT[tab] });
      return;
    }
    if (SESSION_ENV_SUB_REDIRECT[tab]) {
      set({
        activeTab: 'sessionEnvironment',
        sessionEnvSubTab: SESSION_ENV_SUB_REDIRECT[tab],
      });
      return;
    }
    set({ activeTab: tab });
  },
  setEnvSubTab: (id) => set({ envSubTab: id }),
  setSessionEnvSubTab: (id) => set({ sessionEnvSubTab: id }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setMobileSidebarOpen: (open) => set({ mobileSidebarOpen: open }),
  toggleDeletedSection: () => set((s) => ({ deletedSectionOpen: !s.deletedSectionOpen })),
  toggleDevMode: () => set((s) => {
    const next = !s.devMode;
    localStorage.setItem('geny-dev-mode', String(next));
    // If switching to normal mode while on a dev-only tab, fall back to main
    const devOnlyTabs = new Set(['toolSets', 'tools', 'settings', 'logs', 'environment', 'graph', 'sessionTools']);
    const activeTab = !next && devOnlyTabs.has(s.activeTab) ? 'main' : s.activeTab;
    return { devMode: next, activeTab };
  }),
  hydrateDevMode: () => {
    // Force normal mode on mobile
    if (typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches) {
      set({ devMode: false });
      return;
    }
    const stored = localStorage.getItem('geny-dev-mode');
    if (stored === 'false') {
      set({ devMode: false });
    }
  },

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

  loadUserName: async () => {
    try {
      const res = await configApi.get('user');
      set({
        userName: (res.values?.user_name as string) || '',
        userTitle: (res.values?.user_title as string) || '',
      });
    } catch {
      // ignore
    }
  },
}));
