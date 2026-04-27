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

/** Default ToolsSnapshot with required fields populated. Used when
 *  draft.tools is undefined and the user hits a patchTools(). */
function emptyTools(): ToolsSnapshot {
  return {
    built_in: [],
    adhoc: [],
    mcp_servers: [],
    external: [],
    scope: {},
  };
}

/** Run all draft-wide invariants and return the new validationErrors
 *  list. PR-F: lightweight checks — required fields + obvious
 *  configuration mistakes. PR-G+ can wire in artifact ConfigSchema
 *  required-field checks via catalogApi. */
function runValidation(draft: EnvironmentManifest): ValidationError[] {
  const errors: ValidationError[] = [];
  const stages = draft.stages ?? [];

  // ── Hard errors (block save) ──

  // Pipeline ceilings sanity.
  const maxIter = (draft.pipeline as Record<string, unknown> | undefined)
    ?.max_iterations;
  if (typeof maxIter === 'number' && maxIter < 1) {
    errors.push({
      path: 'pipeline.max_iterations',
      message: 'Pipeline max_iterations must be at least 1.',
      severity: 'error',
    });
  }

  // ── Soft warnings (surfaced but non-blocking) ──

  // Stage 6 (api) inactive — LLM never called. Not strictly invalid
  // (a headless preview pipeline might want this) but worth a heads-up.
  const stage6 = stages.find((s) => s.order === 6);
  if (stage6 && !stage6.active) {
    errors.push({
      path: 'stages.6.active',
      message: 'Stage 6 (api) is inactive — the LLM will never be called.',
      severity: 'warning',
    });
  }

  // Stage 1 (input) inactive.
  const stage1 = stages.find((s) => s.order === 1);
  if (stage1 && !stage1.active) {
    errors.push({
      path: 'stages.1.active',
      message: 'Stage 1 (input) is inactive — required by every pipeline.',
      severity: 'warning',
    });
  }

  // Stage 11 (tool_review) active with empty chain.
  const stage11 = stages.find((s) => s.order === 11);
  if (stage11?.active) {
    const chains = stage11.chain_order ?? {};
    const chainKeys = Object.keys(chains);
    if (chainKeys.length > 0) {
      const allEmpty = chainKeys.every(
        (k) => !Array.isArray(chains[k]) || (chains[k] as string[]).length === 0,
      );
      if (allEmpty) {
        errors.push({
          path: 'stages.11.chain_order',
          message:
            'Stage 11 (tool_review) is active but has no reviewers — every tool call will pass through unchecked.',
          severity: 'warning',
        });
      }
    }
  }

  // No tools registered AND stage 10 active.
  const stage10 = stages.find((s) => s.order === 10);
  const builtInTools =
    ((draft.tools as Record<string, unknown> | undefined)?.built_in as string[] | undefined) ?? [];
  if (stage10?.active && builtInTools.length === 0) {
    errors.push({
      path: 'tools.built_in',
      message:
        'No framework tools are registered — the agent will only be able to chat. Add tools in Global > Tools or Stage 10.',
      severity: 'warning',
    });
  }

  return errors;
}

// ─── Store shape ──────────────────────────────────────────

export interface ValidationError {
  path: string;
  message: string;
  /** 'error' blocks Save; 'warning' is surfaced in the UI but the
   *  user can still save. */
  severity?: 'error' | 'warning';
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
  /** Cycle 20260427_1 PR-F — seed a draft from an existing env's
   *  manifest (clone-style start). Used by "Start from preset". The
   *  draft loses the original env's id + name + description + tags
   *  so the user has to type fresh metadata before saving (and the
   *  saved env will be a separate record from the source). */
  newDraftFromExisting: (envId: string) => Promise<void>;
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
          validationErrors: runValidation(fresh),
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

    newDraftFromExisting: async (envId) => {
      set({ seeding: true, error: null });
      try {
        const detail = await environmentApi.get(envId);
        if (!detail.manifest) {
          throw new Error('Source environment has no manifest');
        }
        const fresh = cloneManifest(detail.manifest);
        // Wipe identity / metadata so the user types fresh values and
        // the saved env is a separate record. base_preset records the
        // source so audit trails stay traceable.
        const sourceName = fresh.metadata.name || '';
        fresh.metadata = {
          ...fresh.metadata,
          id: '',
          name: '',
          description: '',
          tags: [],
          base_preset: sourceName,
        };
        set({
          draft: fresh,
          stageDirty: new Set<number>(),
          metadataDirty: false,
          modelDirty: false,
          pipelineDirty: false,
          toolsDirty: false,
          validationErrors: runValidation(fresh),
          error: null,
          seeding: false,
        });
      } catch (e) {
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
      next.metadata = { ...next.metadata, ...patch };
      set({
        draft: next,
        metadataDirty: true,
        validationErrors: runValidation(next),
      });
    },

    patchModel: (patch) => {
      const { draft } = get();
      if (!draft) return;
      const next = cloneManifest(draft);
      next.model = { ...(next.model ?? {}), ...patch };
      set({
        draft: next,
        modelDirty: true,
        validationErrors: runValidation(next),
      });
    },

    patchPipeline: (patch) => {
      const { draft } = get();
      if (!draft) return;
      const next = cloneManifest(draft);
      next.pipeline = { ...(next.pipeline ?? {}), ...patch };
      set({
        draft: next,
        pipelineDirty: true,
        validationErrors: runValidation(next),
      });
    },

    patchTools: (patch) => {
      const { draft } = get();
      if (!draft) return;
      const next = cloneManifest(draft);
      next.tools = { ...(next.tools ?? emptyTools()), ...patch };
      set({
        draft: next,
        toolsDirty: true,
        validationErrors: runValidation(next),
      });
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
      set({
        draft: next,
        stageDirty: nextDirty,
        validationErrors: runValidation(next),
      });
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

    hasBlockingErrors: () =>
      get().validationErrors.some((e) => e.severity === 'error'),

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
