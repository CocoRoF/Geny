'use client';

/**
 * useEnvironmentDraftStore — in-progress EnvironmentManifest for the
 * Library (NEW) tab (cycle 20260427_1).
 *
 * Owns a single draft manifest plus per-stage dirty flags + validation
 * messages. Discarded on tab unmount unless persisted via saveDraft().
 *
 * This store is intentionally separate from useEnvironmentStore (which
 * deals only with persisted EnvironmentDetail) so the new builder can
 * evolve without coupling to the legacy CRUD surface.
 *
 * Save flow (PR-A):
 *   newDraft() → asks the backend to mint a blank manifest via
 *   environmentApi.create({mode:'blank', name:'__draft__'}) and pulls
 *   the manifest back via environmentApi.get(envId). The seed env is
 *   then deleted so the user only sees a real env after Save. (Slight
 *   dance because the executor's blank_manifest() factory lives Python-
 *   side and we don't want to mirror its 21-stage scaffold in TS.)
 *   Future: backend can expose GET /api/environments/blank-manifest
 *   if the create+delete round-trip becomes noisy.
 *
 *   saveDraft() → environmentApi.create({mode:'blank',
 *   manifest_override: draft, name, description, tags}). Backend forces
 *   metadata.name/description/tags onto the manifest (cycle 20260427_1
 *   service patch).
 */

import { create } from 'zustand';
import { environmentApi } from '@/lib/environmentApi';
import type {
  EnvironmentManifest,
  EnvironmentMetadata,
  StageManifestEntry,
  ToolsSnapshot,
} from '@/types/environment';

// ─── Helpers ──────────────────────────────────────────────

const TEMP_DRAFT_NAME = '__library_new_draft_seed__';

/** Deep-clone a JSON-serialisable manifest so callers cannot mutate
 *  the store's internal reference. */
function cloneManifest(m: EnvironmentManifest): EnvironmentManifest {
  return JSON.parse(JSON.stringify(m)) as EnvironmentManifest;
}

function shallowMerge<T extends Record<string, unknown>>(
  base: T,
  patch: Partial<T>,
): T {
  return { ...base, ...patch } as T;
}

// ─── Store shape ──────────────────────────────────────────

export interface ValidationError {
  path: string;
  message: string;
}

export interface EnvironmentDraftState {
  /** The in-progress manifest. `null` until newDraft() succeeds. */
  draft: EnvironmentManifest | null;
  /** True while newDraft() is fetching the seed manifest from the
   *  backend, so the UI can show a spinner instead of an empty canvas. */
  seeding: boolean;
  /** Stage orders the user has touched since newDraft(). */
  stageDirty: Set<number>;
  /** Top-level dirty flags for non-stage sections. */
  metadataDirty: boolean;
  modelDirty: boolean;
  pipelineDirty: boolean;
  toolsDirty: boolean;
  /** Per-path validation errors keyed by dotted path
   *  (e.g. `metadata.name`, `stages.6.config.system_prompt`). */
  validationErrors: ValidationError[];
  /** Last error from save / seed for surface in the top bar. */
  error: string | null;
  /** True while saveDraft() is in flight. */
  saving: boolean;

  // ── Actions ──
  newDraft: () => Promise<void>;
  resetDraft: () => void;

  patchMetadata: (patch: Partial<EnvironmentMetadata>) => void;
  patchModel: (patch: Record<string, unknown>) => void;
  patchPipeline: (patch: Record<string, unknown>) => void;
  patchTools: (patch: Partial<ToolsSnapshot>) => void;
  /** Replace one stage entry. Caller passes the full new entry; the
   *  store merges it in by `order`. */
  patchStage: (
    order: number,
    patch: Partial<StageManifestEntry>,
  ) => void;

  setValidationError: (path: string, message: string | null) => void;
  clearError: () => void;

  /** Returns true if anything has been edited since newDraft(). */
  isDirty: () => boolean;
  /** Returns true if there are any blocking validation errors. */
  hasBlockingErrors: () => boolean;

  /**
   * Persist the draft as a fresh environment via the backend's
   * mode=blank + manifest_override path.
   * Returns the new env id so the caller can navigate.
   */
  saveDraft: (meta: {
    name: string;
    description?: string;
    tags?: string[];
  }) => Promise<{ id: string }>;
}

// ─── Implementation ───────────────────────────────────────

export const useEnvironmentDraftStore = create<EnvironmentDraftState>(
  (set, get) => ({
    draft: null,
    seeding: false,
    stageDirty: new Set<number>(),
    metadataDirty: false,
    modelDirty: false,
    pipelineDirty: false,
    toolsDirty: false,
    validationErrors: [],
    error: null,
    saving: false,

    newDraft: async () => {
      set({ seeding: true, error: null });
      let seedId: string | null = null;
      try {
        const created = await environmentApi.create({
          mode: 'blank',
          name: TEMP_DRAFT_NAME,
          description: '',
          tags: [],
        });
        seedId = created.id;
        const detail = await environmentApi.get(seedId);
        // Drop the seed env so it doesn't litter the env list — the
        // user will only see a real env when they hit Save.
        try {
          await environmentApi.delete(seedId);
        } catch {
          /* silent — seed cleanup is best-effort. */
        }
        if (!detail.manifest) {
          throw new Error('Backend returned no manifest for blank draft');
        }
        const fresh = cloneManifest(detail.manifest);
        // Wipe the auto-generated id + name so the seed metadata
        // doesn't bleed into the user's draft.
        fresh.metadata = {
          ...fresh.metadata,
          id: '',
          name: '',
          description: '',
          tags: [],
        };
        set({
          draft: fresh,
          stageDirty: new Set<number>(),
          metadataDirty: false,
          modelDirty: false,
          pipelineDirty: false,
          toolsDirty: false,
          validationErrors: [],
          error: null,
          seeding: false,
        });
      } catch (e) {
        // If we created a seed but failed to load, try to clean up.
        if (seedId) {
          environmentApi.delete(seedId).catch(() => {});
        }
        set({
          seeding: false,
          error: e instanceof Error ? e.message : String(e),
        });
        throw e;
      }
    },

    resetDraft: () =>
      set({
        draft: null,
        seeding: false,
        stageDirty: new Set<number>(),
        metadataDirty: false,
        modelDirty: false,
        pipelineDirty: false,
        toolsDirty: false,
        validationErrors: [],
        error: null,
        saving: false,
      }),

    patchMetadata: (patch) => {
      const { draft } = get();
      if (!draft) return;
      const next = cloneManifest(draft);
      next.metadata = shallowMerge(
        next.metadata as unknown as Record<string, unknown>,
        patch as Record<string, unknown>,
      ) as EnvironmentMetadata;
      set({ draft: next, metadataDirty: true });
    },

    patchModel: (patch) => {
      const { draft } = get();
      if (!draft) return;
      const next = cloneManifest(draft);
      next.model = shallowMerge(next.model ?? {}, patch);
      set({ draft: next, modelDirty: true });
    },

    patchPipeline: (patch) => {
      const { draft } = get();
      if (!draft) return;
      const next = cloneManifest(draft);
      next.pipeline = shallowMerge(next.pipeline ?? {}, patch);
      set({ draft: next, pipelineDirty: true });
    },

    patchTools: (patch) => {
      const { draft } = get();
      if (!draft) return;
      const next = cloneManifest(draft);
      next.tools = shallowMerge(
        next.tools ?? {
          built_in: [],
          adhoc: [],
          mcp_servers: [],
          external: [],
          scope: {},
        },
        patch,
      );
      set({ draft: next, toolsDirty: true });
    },

    patchStage: (order, patch) => {
      const { draft, stageDirty } = get();
      if (!draft) return;
      const next = cloneManifest(draft);
      const idx = next.stages.findIndex((s) => s.order === order);
      if (idx < 0) {
        // Stage not present — append it (preserves order).
        const seeded: StageManifestEntry = {
          order,
          name: `s${String(order).padStart(2, '0')}_unknown`,
          active: false,
          artifact: 'default',
          strategies: {},
          strategy_configs: {},
          config: {},
          tool_binding: null,
          model_override: null,
          chain_order: {},
          ...patch,
        };
        next.stages.push(seeded);
        next.stages.sort((a, b) => a.order - b.order);
      } else {
        next.stages[idx] = { ...next.stages[idx], ...patch };
      }
      const nextDirty = new Set(stageDirty);
      nextDirty.add(order);
      set({ draft: next, stageDirty: nextDirty });
    },

    setValidationError: (path, message) => {
      const { validationErrors } = get();
      const filtered = validationErrors.filter((v) => v.path !== path);
      if (message) {
        filtered.push({ path, message });
      }
      set({ validationErrors: filtered });
    },

    clearError: () => set({ error: null }),

    isDirty: () => {
      const s = get();
      return (
        s.stageDirty.size > 0 ||
        s.metadataDirty ||
        s.modelDirty ||
        s.pipelineDirty ||
        s.toolsDirty
      );
    },

    hasBlockingErrors: () => get().validationErrors.length > 0,

    saveDraft: async ({ name, description = '', tags = [] }) => {
      const { draft, hasBlockingErrors } = get();
      if (!draft) {
        throw new Error('No draft to save');
      }
      if (hasBlockingErrors()) {
        throw new Error('Validation errors must be resolved before saving');
      }
      if (!name.trim()) {
        throw new Error('Environment name is required');
      }
      set({ saving: true, error: null });
      try {
        const res = await environmentApi.create({
          mode: 'blank',
          name: name.trim(),
          description,
          tags,
          manifest_override: draft,
        });
        // Caller owns post-save navigation; clear local state.
        set({
          draft: null,
          stageDirty: new Set<number>(),
          metadataDirty: false,
          modelDirty: false,
          pipelineDirty: false,
          toolsDirty: false,
          validationErrors: [],
          saving: false,
        });
        return res;
      } catch (e) {
        set({
          saving: false,
          error: e instanceof Error ? e.message : String(e),
        });
        throw e;
      }
    },
  }),
);
