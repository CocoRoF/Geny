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

import { catalogApi, environmentApi } from '@/lib/environmentApi';
import type {
  CatalogResponse,
  CreateEnvironmentPayload,
  EnvironmentDetail,
  EnvironmentManifest,
  EnvironmentSummary,
  UpdateEnvironmentPayload,
  UpdateStageTemplatePayload,
} from '@/types/environment';

export type EnvSessionCountBucket = {
  active: number;
  deleted: number;
  error: number;
};

interface EnvironmentState {
  // Data
  environments: EnvironmentSummary[];
  selectedEnvironment: EnvironmentDetail | null;
  catalog: CatalogResponse | null;
  sessionCounts: Record<string, EnvSessionCountBucket> | null;
  isLoading: boolean;
  isLoadingCatalog: boolean;
  error: string | null;

  // List + selection
  loadEnvironments: () => Promise<void>;
  loadEnvironment: (envId: string) => Promise<EnvironmentDetail>;
  clearSelection: () => void;
  refreshSessionCounts: () => Promise<void>;

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
      set({ sessionCounts: map });
    } catch {
      // Leave the existing value in place; consumers fall back to
      // client-side aggregation when the map is null.
    }
  },

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
  },

  updateStage: async (envId, order, payload) => {
    const updated = await environmentApi.updateStage(envId, order, payload);
    set((s) => ({
      selectedEnvironment:
        s.selectedEnvironment && s.selectedEnvironment.id === envId
          ? updated
          : s.selectedEnvironment,
    }));
  },

  builderEnvId: null,
  openInBuilder: (envId) => set({ builderEnvId: envId }),
  closeBuilder: () => set({ builderEnvId: null }),

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
