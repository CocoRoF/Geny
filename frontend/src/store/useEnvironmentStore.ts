/**
 * Environment Store — Zustand state for EnvironmentManifest CRUD and
 * the stage/artifact catalog. Mirrors the patterns used by
 * `useToolPresetStore` so component code stays consistent across the
 * frontend.
 *
 * The store is Phase 6b infrastructure: it holds the data and actions
 * the Environment list / Builder UI (Phase 6c+) will consume. No
 * component currently subscribes — the store is inert until a UI lands.
 */

import { create } from 'zustand';
import { toast } from 'sonner';

import { catalogApi, environmentApi } from '@/lib/environmentApi';
import type {
  CatalogResponse,
  CreateEnvironmentPayload,
  EnvironmentDetail,
  EnvironmentManifest,
  EnvironmentSessionSummary,
  EnvironmentSummary,
  UpdateEnvironmentPayload,
  UpdateStageTemplatePayload,
} from '@/types/environment';

export type EnvSessionCountBucket = {
  active: number;
  deleted: number;
  error: number;
};

export type DrawerSessionsEntry = {
  sessions: EnvironmentSessionSummary[];
  fetchedAt: number;
};

function drawerKey(envId: string, includeDeleted: boolean): string {
  return `${envId}:${includeDeleted ? 'all' : 'active'}`;
}

/**
 * D.3 (cycle 20260426_1) — surface a sonner toast after a manifest
 * write completes if there are active sessions still running on the
 * pre-edit snapshot.
 *
 * Called by ``replaceManifest`` and ``updateStage``. The backend
 * populates ``affected_sessions`` on these endpoint responses so the
 * UI can warn the operator without a separate round-trip.
 *
 * No-ops when affected_sessions is missing (older backend) or count
 * is zero (no warning needed).
 */
function _warnAffectedSessions(
  affected: { count: number; session_names: string[] } | null | undefined,
): void {
  if (!affected || affected.count <= 0) return;
  const preview =
    affected.session_names.length > 3
      ? `${affected.session_names.slice(0, 3).join(', ')} +${affected.session_names.length - 3} more`
      : affected.session_names.join(', ');
  const headline = `${affected.count} active session${
    affected.count === 1 ? '' : 's'
  } still running on the pre-edit manifest.`;
  const body = preview
    ? `Restart to pick up the change: ${preview}`
    : 'Restart them to pick up the change.';
  toast.warning(headline, { description: body, duration: 8000 });
}

// Module-scope inflight guard for prefetch — deduplicates rapid hover
// fire-and-forget calls so a user skimming cards doesn't detonate N
// parallel requests to the same env.
const inflightDrawerFetches = new Set<string>();

interface EnvironmentState {
  // Data
  environments: EnvironmentSummary[];
  selectedEnvironment: EnvironmentDetail | null;
  catalog: CatalogResponse | null;
  sessionCounts: Record<string, EnvSessionCountBucket> | null;
  sessionCountsFetchedAt: number | null;
  drawerSessions: Record<string, DrawerSessionsEntry>;
  isLoading: boolean;
  isLoadingCatalog: boolean;
  error: string | null;

  // List + selection
  loadEnvironments: () => Promise<void>;
  loadEnvironment: (envId: string) => Promise<EnvironmentDetail>;
  clearSelection: () => void;
  refreshSessionCounts: () => Promise<void>;
  refreshSessionCountsIfStale: (ttlMs: number) => Promise<void>;

  // Drawer linked-sessions cache
  loadDrawerSessions: (envId: string, includeDeleted: boolean) => Promise<EnvironmentSessionSummary[]>;
  refreshDrawerSessions: (envId: string, includeDeleted: boolean) => Promise<EnvironmentSessionSummary[]>;
  refreshDrawerSessionsIfStale: (envId: string, includeDeleted: boolean, ttlMs: number) => Promise<void>;
  prefetchDrawerSessions: (envId: string, includeDeleted: boolean) => void;
  invalidateDrawerSessionsForEnv: (envId: string) => void;

  // Mutations
  createEnvironment: (payload: CreateEnvironmentPayload) => Promise<{ id: string }>;
  updateEnvironment: (envId: string, changes: UpdateEnvironmentPayload) => Promise<void>;
  deleteEnvironment: (envId: string) => Promise<void>;
  duplicateEnvironment: (envId: string, newName: string) => Promise<{ id: string }>;
  replaceManifest: (envId: string, manifest: EnvironmentManifest) => Promise<void>;
  updateStage: (
    envId: string,
    order: number,
    payload: UpdateStageTemplatePayload,
  ) => Promise<void>;

  // Builder tab routing
  builderEnvId: string | null;
  openInBuilder: (envId: string) => void;
  closeBuilder: () => void;

  // External-tab drawer trigger. GraphTab (and any other surface that
  // wants to deep-link into an env detail drawer) writes here, then
  // navigates to the Environments tab. EnvironmentsTab consumes the
  // value on mount/update and clears it.
  pendingDrawerEnvId: string | null;
  requestOpenEnvDrawer: (envId: string) => void;
  consumePendingDrawerEnvId: () => string | null;
  exportEnvironment: (envId: string) => Promise<string>;
  importEnvironment: (data: Record<string, unknown>) => Promise<{ id: string }>;
  markPreset: (envId: string) => Promise<void>;
  unmarkPreset: (envId: string) => Promise<void>;

  // Catalog
  loadCatalog: () => Promise<void>;
}

function _msg(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

export const useEnvironmentStore = create<EnvironmentState>((set, get) => ({
  environments: [],
  selectedEnvironment: null,
  catalog: null,
  sessionCounts: null,
  sessionCountsFetchedAt: null,
  drawerSessions: {},
  isLoading: false,
  isLoadingCatalog: false,
  error: null,

  loadEnvironments: async () => {
    set({ isLoading: true, error: null });
    try {
      const list = await environmentApi.list();
      set({ environments: list, isLoading: false });
    } catch (e) {
      set({ error: _msg(e, 'Failed to load environments'), isLoading: false });
    }
  },

  refreshSessionCounts: async () => {
    try {
      const res = await environmentApi.sessionCounts();
      const map: Record<string, EnvSessionCountBucket> = {};
      for (const c of res.counts) {
        map[c.env_id] = {
          active: c.active_count,
          deleted: c.deleted_count,
          error: c.error_count,
        };
      }
      set({ sessionCounts: map, sessionCountsFetchedAt: Date.now() });
    } catch {
      // Leave the existing value in place; consumers fall back to
      // client-side aggregation when the map is null.
    }
  },

  refreshSessionCountsIfStale: async (ttlMs) => {
    const { sessionCountsFetchedAt } = get();
    if (
      sessionCountsFetchedAt !== null &&
      Date.now() - sessionCountsFetchedAt < ttlMs
    ) {
      return;
    }
    await get().refreshSessionCounts();
  },

  loadDrawerSessions: async (envId, includeDeleted) => {
    const key = drawerKey(envId, includeDeleted);
    const cached = get().drawerSessions[key];
    if (cached) return cached.sessions;
    return get().refreshDrawerSessions(envId, includeDeleted);
  },

  refreshDrawerSessions: async (envId, includeDeleted) => {
    const key = drawerKey(envId, includeDeleted);
    const res = await environmentApi.linkedSessions(envId, includeDeleted);
    set((s) => ({
      drawerSessions: {
        ...s.drawerSessions,
        [key]: { sessions: res.sessions, fetchedAt: Date.now() },
      },
    }));
    return res.sessions;
  },

  refreshDrawerSessionsIfStale: async (envId, includeDeleted, ttlMs) => {
    const key = drawerKey(envId, includeDeleted);
    const cached = get().drawerSessions[key];
    if (cached && Date.now() - cached.fetchedAt < ttlMs) return;
    try {
      await get().refreshDrawerSessions(envId, includeDeleted);
    } catch {
      // Preserve the prior cache; the drawer surfaces its own error
      // message via the imperative fetch path.
    }
  },

  prefetchDrawerSessions: (envId, includeDeleted) => {
    const key = drawerKey(envId, includeDeleted);
    if (get().drawerSessions[key]) return;
    if (inflightDrawerFetches.has(key)) return;
    inflightDrawerFetches.add(key);
    void get()
      .refreshDrawerSessions(envId, includeDeleted)
      .catch(() => {
        // Swallow — prefetch is best-effort. The drawer's imperative
        // fetch path will surface any real failure when the user opens it.
      })
      .finally(() => {
        inflightDrawerFetches.delete(key);
      });
  },

  invalidateDrawerSessionsForEnv: (envId) =>
    set((s) => {
      const activeKey = drawerKey(envId, false);
      const allKey = drawerKey(envId, true);
      if (!(activeKey in s.drawerSessions) && !(allKey in s.drawerSessions)) {
        return s;
      }
      const next = { ...s.drawerSessions };
      delete next[activeKey];
      delete next[allKey];
      return { drawerSessions: next };
    }),

  loadEnvironment: async (envId) => {
    set({ isLoading: true, error: null });
    try {
      const env = await environmentApi.get(envId);
      set({ selectedEnvironment: env, isLoading: false });
      return env;
    } catch (e) {
      set({ error: _msg(e, 'Failed to load environment'), isLoading: false });
      throw e;
    }
  },

  clearSelection: () => set({ selectedEnvironment: null }),

  createEnvironment: async (payload) => {
    const result = await environmentApi.create(payload);
    await get().loadEnvironments();
    void get().refreshSessionCounts();
    return result;
  },

  updateEnvironment: async (envId, changes) => {
    const updated = await environmentApi.update(envId, changes);
    set((s) => ({
      environments: s.environments.map((e) =>
        e.id === envId ? { ...e, ...changes } : e,
      ),
      selectedEnvironment:
        s.selectedEnvironment && s.selectedEnvironment.id === envId
          ? updated
          : s.selectedEnvironment,
    }));
  },

  deleteEnvironment: async (envId) => {
    await environmentApi.delete(envId);
    set((s) => {
      const next: Partial<EnvironmentState> = {
        environments: s.environments.filter((e) => e.id !== envId),
        selectedEnvironment:
          s.selectedEnvironment && s.selectedEnvironment.id === envId
            ? null
            : s.selectedEnvironment,
        builderEnvId: s.builderEnvId === envId ? null : s.builderEnvId,
      };
      if (s.sessionCounts && envId in s.sessionCounts) {
        const { [envId]: _dropped, ...rest } = s.sessionCounts;
        void _dropped;
        next.sessionCounts = rest;
      }
      const activeKey = drawerKey(envId, false);
      const allKey = drawerKey(envId, true);
      if (activeKey in s.drawerSessions || allKey in s.drawerSessions) {
        const cache = { ...s.drawerSessions };
        delete cache[activeKey];
        delete cache[allKey];
        next.drawerSessions = cache;
      }
      return next as EnvironmentState;
    });
    void get().refreshSessionCounts();
  },

  duplicateEnvironment: async (envId, newName) => {
    const result = await environmentApi.duplicate(envId, newName);
    await get().loadEnvironments();
    void get().refreshSessionCounts();
    return result;
  },

  replaceManifest: async (envId, manifest) => {
    const updated = await environmentApi.replaceManifest(envId, manifest);
    set((s) => ({
      selectedEnvironment:
        s.selectedEnvironment && s.selectedEnvironment.id === envId
          ? updated
          : s.selectedEnvironment,
    }));
    _warnAffectedSessions(updated.affected_sessions);
  },

  updateStage: async (envId, order, payload) => {
    const updated = await environmentApi.updateStage(envId, order, payload);
    set((s) => ({
      selectedEnvironment:
        s.selectedEnvironment && s.selectedEnvironment.id === envId
          ? updated
          : s.selectedEnvironment,
    }));
    _warnAffectedSessions(updated.affected_sessions);
  },

  builderEnvId: null,
  openInBuilder: (envId) => set({ builderEnvId: envId }),
  closeBuilder: () => set({ builderEnvId: null }),

  pendingDrawerEnvId: null,
  requestOpenEnvDrawer: (envId) => set({ pendingDrawerEnvId: envId }),
  consumePendingDrawerEnvId: () => {
    const id = get().pendingDrawerEnvId;
    if (id !== null) set({ pendingDrawerEnvId: null });
    return id;
  },

  exportEnvironment: (envId) => environmentApi.exportEnv(envId),

  importEnvironment: async (data) => {
    const result = await environmentApi.importEnv(data);
    await get().loadEnvironments();
    void get().refreshSessionCounts();
    return result;
  },

  markPreset: async (envId) => {
    await environmentApi.markPreset(envId);
  },

  unmarkPreset: async (envId) => {
    await environmentApi.unmarkPreset(envId);
  },

  loadCatalog: async () => {
    set({ isLoadingCatalog: true });
    try {
      const catalog = await catalogApi.full();
      set({ catalog, isLoadingCatalog: false });
    } catch (e) {
      set({
        error: _msg(e, 'Failed to load stage/artifact catalog'),
        isLoadingCatalog: false,
      });
    }
  },
}));
