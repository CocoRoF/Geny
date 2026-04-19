/**
 * v2 EnvironmentManifest types.
 *
 * Mirrors `geny_executor.EnvironmentManifest` and the backend
 * `service/environment/schemas.py` Pydantic models. Kept separate
 * from `types/index.ts` so the Environment Builder can evolve its
 * schema without dragging the rest of the type surface along.
 *
 * Source of truth on the backend side:
 *   - geny-executor: src/geny_executor/environment.py
 *   - Geny backend: backend/service/environment/schemas.py
 */

export interface EnvironmentMetadata {
  id: string;
  name: string;
  description: string;
  author?: string;
  tags: string[];
  created_at: string;
  updated_at: string;
  base_preset?: string;
}

export interface StageToolBinding {
  mode: 'inherit' | 'allowlist' | 'blocklist';
  patterns: string[];
}

export interface StageModelOverride {
  model?: string;
  system_prompt?: string;
  max_tokens?: number;
  temperature?: number;
  top_p?: number;
  [key: string]: unknown;
}

export interface StageManifestEntry {
  order: number;
  name: string;
  active: boolean;
  artifact: string;
  strategies: Record<string, string>;
  strategy_configs: Record<string, Record<string, unknown>>;
  config: Record<string, unknown>;
  tool_binding?: StageToolBinding | null;
  model_override?: StageModelOverride | null;
  chain_order: Record<string, string[]>;
}

export interface ToolsSnapshot {
  adhoc: Array<Record<string, unknown>>;
  mcp_servers: Array<Record<string, unknown>>;
  global_allowlist: string[];
  global_blocklist: string[];
}

export interface EnvironmentManifest {
  version: string;
  metadata: EnvironmentMetadata;
  model: Record<string, unknown>;
  pipeline: Record<string, unknown>;
  stages: StageManifestEntry[];
  tools?: ToolsSnapshot;
}

// ── Request/response shapes for the v2 endpoints ──────────────────

export type CreateEnvironmentMode = 'blank' | 'from_session' | 'from_preset';

export interface CreateEnvironmentPayload {
  mode: CreateEnvironmentMode;
  name: string;
  description?: string;
  tags?: string[];
  session_id?: string;
  preset_name?: string;
}

export interface UpdateEnvironmentPayload {
  name?: string;
  description?: string;
  tags?: string[];
}

export interface UpdateStageTemplatePayload {
  artifact?: string;
  strategies?: Record<string, string>;
  strategy_configs?: Record<string, Record<string, unknown>>;
  config?: Record<string, unknown>;
  tool_binding?: StageToolBinding | null;
  model_override?: StageModelOverride | null;
  chain_order?: Record<string, string[]>;
  active?: boolean;
}

export interface EnvironmentSummary {
  id: string;
  name: string;
  description: string;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface EnvironmentDetail extends EnvironmentSummary {
  manifest?: EnvironmentManifest | null;
  snapshot?: Record<string, unknown> | null;
}

export interface EnvironmentDiffResult {
  added: string[];
  removed: string[];
  changed: Array<{
    path: string;
    before: unknown;
    after: unknown;
  }>;
}

// ── Catalog (stage/artifact/strategy introspection) ──────────────
//
// Byte-compatible with `backend/service/artifact/schemas.py` — which is in
// turn a port of the executor's `StageIntrospection.to_dict()` shape.
// Every field matches the Pydantic model so the UI can read backend
// responses with zero translation.

export interface ArtifactInfo {
  stage: string;
  name: string;
  description?: string;
  version?: string;
  stability?: string;
  requires: string[];
  is_default: boolean;
  provides_stage: boolean;
  extra: Record<string, unknown>;
}

export interface SlotIntrospection {
  slot_name: string;
  description?: string;
  required: boolean;
  current_impl: string;
  available_impls: string[];
  impl_schemas: Record<string, Record<string, unknown> | null>;
  impl_descriptions: Record<string, string>;
}

export interface ChainIntrospection {
  chain_name: string;
  description?: string;
  current_impls: string[];
  available_impls: string[];
  impl_schemas: Record<string, Record<string, unknown> | null>;
  impl_descriptions: Record<string, string>;
}

/** Full introspection for one (stage, default-artifact) pair. */
export interface StageIntrospection {
  stage: string;
  artifact: string;
  order: number;
  name: string;
  category?: string;
  artifact_info: ArtifactInfo;
  config_schema?: Record<string, unknown> | null;
  config: Record<string, unknown>;
  strategy_slots: Record<string, SlotIntrospection>;
  strategy_chains: Record<string, ChainIntrospection>;
  tool_binding_supported: boolean;
  model_override_supported: boolean;
  required: boolean;
  extra: Record<string, unknown>;
}

/** Compact stage row returned by `/api/catalog/stages`. */
export interface StageSummary {
  order: number;
  module: string;
  name: string;
  category?: string;
  default_artifact: string;
  artifact_count: number;
}

/** Response of `/api/catalog/full`. */
export interface CatalogResponse {
  stages: StageIntrospection[];
}

/** Response of `/api/catalog/stages/{order}/artifacts`. */
export interface StageArtifactList {
  stage: string;
  artifacts: ArtifactInfo[];
}

// ── Reverse-lookup: sessions bound to an environment ─────

/** Per-session snippet returned by `/api/environments/{id}/sessions`. */
export interface EnvironmentSessionSummary {
  session_id: string;
  session_name?: string | null;
  status?: string | null;
  role?: string | null;
  env_id?: string | null;
  created_at?: string | null;
  is_deleted: boolean;
  deleted_at?: string | null;
  error_message?: string | null;
}

/** Response of `/api/environments/{id}/sessions`. */
export interface EnvironmentSessionsResponse {
  env_id: string;
  sessions: EnvironmentSessionSummary[];
  active_count: number;
  deleted_count: number;
  error_count: number;
}

/** One entry in the bulk `/api/environments/session-counts` response. */
export interface EnvironmentSessionCountEntry {
  env_id: string;
  active_count: number;
  deleted_count: number;
  error_count: number;
}

/** Response of `/api/environments/session-counts`. */
export interface EnvironmentSessionCountsResponse {
  counts: EnvironmentSessionCountEntry[];
}
