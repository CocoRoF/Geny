import { create } from 'zustand';
import type { SessionInfo, PromptInfo } from '@/types';
import { agentApi, commandApi, healthApi, configApi } from '@/lib/api';

// Sessions with an in-flight resume() — dedupes rapid opens so selecting the
// same dormant session repeatedly can't storm re-hydration.
const _resumingIds = new Set<string>();

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
  userName: string;
  userTitle: string;

  // Actions
  loadSessions: () => Promise<void>;
  loadDeletedSessions: () => Promise<void>;
  selectSession: (id: string | null) => void;
  createSession: (data: Parameters<typeof agentApi.create>[0]) => Promise<SessionInfo>;
  deleteSession: (id: string) => Promise<void>;
  permanentDeleteSession: (id: string) => Promise<void>;
  purgeDeletedSessions: () => Promise<void>;
  restoreSession: (id: string) => Promise<void>;
  resumeSession: (id: string) => Promise<void>;
  setActiveTab: (tab: string) => void;
  /** Path (session-storage relative) the Canvas tab should auto-open —
   *  set by chat "open in canvas" affordances, consumed once by CanvasTab. */
  canvasFocus: string | null;
  openCanvasAt: (path: string) => void;
  clearCanvasFocus: () => void;
  setEnvSubTab: (id: string) => void;
  setSessionEnvSubTab: (id: string) => void;
  toggleSidebar: () => void;
  setMobileSidebarOpen: (open: boolean) => void;
  toggleDeletedSection: () => void;
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
  canvasFocus: null,
  envSubTab: 'library',
  sessionEnvSubTab: 'manifest',
  sidebarCollapsed: false,
  mobileSidebarOpen: false,
  deletedSectionOpen: false,
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
    // Activate a dormant / idle session the moment it's opened, so its
    // pipeline + chat room come live and the chat stops sitting on
    // "채팅방을 준비하고 있어요…". Scoped to the ONE opened session and guarded
    // (resumeSession is in-flight-deduped + idempotent server-side), so this
    // can't storm re-hydration the way an unscoped version once did.
    if (id) {
      const session = sessions.find((s) => s.session_id === id);
      if (session && session.status !== 'running' && session.status !== 'error') {
        void get().resumeSession(id);
      }
    }
  },

  createSession: async (data) => {
    const session = await agentApi.create(data);
    await get().loadSessions();
    if (session.env_id) {
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
    }
  },

  permanentDeleteSession: async (id) => {
    await agentApi.permanentDelete(id);
    await get().loadDeletedSessions();
  },

  purgeDeletedSessions: async () => {
    // Empty the trash — permanently delete every soft-deleted session.
    await agentApi.purgeDeleted();
    await get().loadDeletedSessions();
  },

  restoreSession: async (id) => {
    await agentApi.restore(id);
    await get().loadSessions();
    await get().loadDeletedSessions();
  },

  resumeSession: async (id) => {
    // Lazy re-hydrate a dormant (post-restart / idle) session, then refresh
    // the list so its status flips to live + its chat_room_id surfaces (this
    // is what unblocks the chat's "채팅방을 준비하고 있어요…" gate). The
    // in-flight guard makes repeated opens of the same session idempotent so
    // rapid selection can't storm re-hydration.
    if (_resumingIds.has(id)) return;
    _resumingIds.add(id);
    try {
      await agentApi.resume(id);
      await get().loadSessions();
    } catch (e) {
      console.error('Failed to resume session:', e);
    } finally {
      _resumingIds.delete(id);
    }
  },

  openCanvasAt: (path) => set({ canvasFocus: path, activeTab: 'canvas' }),
  clearCanvasFocus: () => set({ canvasFocus: null }),
  setActiveTab: (tab) => {
    // Back-compat for legacy persisted activeTab values + sidebar
    // entry points that bypassed setActiveTab.
    //
    // Cycle 20260429 Phase 6 — the main-app `library` tab is gone.
    // Anything that used to land in Library/<sub-tab> now navigates
    // to /environments?tab=<sub> instead. Hooks/skills/permissions/
    // mcpServers all became top-level tabs over there in #553.
    //
    // setActiveTab can't push routes (Zustand outside React), so for
    // legacy ids we fall back to window.location. Real call sites in
    // the new code path use Next.js Link directly; this branch only
    // catches stale localStorage state.
    const ENV_ROUTE_REDIRECT: Record<string, string> = {
      library: '',
      environments: '',
      builder: '',
      toolSets: 'mcp', // ToolSets tab dissolved; closest replacement is MCP
      toolCatalog: 'mcp',
      permissions: 'permissions',
      // NOTE: `hooks` is NOT redirected — it is now the top-level user-automation
      // ("Hooks") session tab. The env-management lifecycle-hooks editor moved
      // under /environments and is reached via its own Link, not this id.
      skills: 'skills',
      mcpServers: 'mcp',
    };
    const SESSION_ENV_SUB_REDIRECT: Record<string, string> = {
      environment: 'manifest', // legacy session-env id
      graph: 'manifest',
      sessionTools: 'tools',
    };
    if (tab in ENV_ROUTE_REDIRECT) {
      const sub = ENV_ROUTE_REDIRECT[tab];
      const url = sub ? `/environments?tab=${sub}` : '/environments';
      if (typeof window !== 'undefined') {
        window.location.href = url;
      }
      return;
    }
    if (SESSION_ENV_SUB_REDIRECT[tab]) {
      set({
        activeTab: 'sessionEnvironment',
        sessionEnvSubTab: SESSION_ENV_SUB_REDIRECT[tab],
      });
      return;
    }
    // Cycle 20260503_3 — the in-app ``memory`` tab was retired in
    // favour of opening the canonical Opsidian app in a new tab.
    // ``TabNavigation`` uses an ``external`` shortcut so a fresh
    // click never reaches here, but persisted-localStorage state
    // from before the cutover (or a programmatic call from older
    // code) lands on this branch — pop the new window AND fall
    // back to the default session tab so the in-app view stays
    // valid.
    if (tab === 'memory') {
      if (typeof window !== 'undefined') {
        const sid = get().selectedSessionId;
        const href = sid
          ? `/opsidian?sessionId=${encodeURIComponent(sid)}`
          : '/opsidian';
        window.open(href, '_blank', 'noopener,noreferrer');
      }
      set({ activeTab: 'command' });
      return;
    }
    set({ activeTab: tab });
  },
  setEnvSubTab: (id) => set({ envSubTab: id }),
  setSessionEnvSubTab: (id) => set({ sessionEnvSubTab: id }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setMobileSidebarOpen: (open) => set({ mobileSidebarOpen: open }),
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
