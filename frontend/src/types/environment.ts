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

/**
 * StageToolBinding — mirrors geny-executor's
 * ``geny_executor.tools.stage_binding.StageToolBinding.to_dict()``
 * shape (allowed/blocked sets + extra_context dict). Both lists are
 * optional; ``null`` means "inherit everything for that axis".
 *
 * Earlier shape ({mode, patterns}) was a placeholder that never
 * matched the executor's serialization — fixed in cycle 20260427_1
 * (Library NEW Stage 10 editor needs the real shape to write into).
 */
export interface StageToolBinding {
  stage_order?: number;
  allowed?: string[] | null;
  blocked?: string[] | null;
  extra_context?: Record<string, unknown>;
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
  // Names of geny-executor BUILT_IN_TOOL_CLASSES tools enabled for this env.
  built_in?: string[];
  // Adhoc tool definitions, MCP servers, and external (host-provided)
  // tool whitelists.
  adhoc: Array<Record<string, unknown>>;
  mcp_servers: Array<Record<string, unknown>>;
  external?: string[];
  scope?: Record<string, unknown>;
  global_allowlist?: string[];
  global_blocklist?: string[];
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
  // Cycle 20260427_1 — Library (NEW) tab posts a fully-assembled draft
  // manifest in one shot. Only honoured when mode='blank'; the backend
  // forces caller-supplied name/description/tags onto the manifest's
  // metadata so the env list view stays consistent with the create form.
  manifest_override?: EnvironmentManifest;
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
  // S.1 / S.2 (cycle 20260426_2) — typed payload keys widened to
  // ``Record<string, unknown>`` to match the backend's
  // ``Optional[Dict[str, Any]]`` and the JSON-textarea editor's
  // schema-loose semantics. The strongly-typed
  // ``StageToolBinding`` / ``StageModelOverride`` interfaces remain
  // for read paths (manifest display) where the on-disk shape is
  // canonical.
  tool_binding?: Record<string, unknown> | null;
  model_override?: Record<string, unknown> | null;
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
  base_preset?: string;
}

// D.3 (cycle 20260426_1) — populated by manifest-write endpoints to
// surface active sessions still running on the pre-edit snapshot.
export interface AffectedSessionsSummary {
  count: number;
  session_ids: string[];
  session_names: string[];
}

export interface EnvironmentDetail extends EnvironmentSummary {
  manifest?: EnvironmentManifest | null;
  snapshot?: Record<string, unknown> | null;
  affected_sessions?: AffectedSessionsSummary | null;
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

// ── Bulk diff (matrix UI) ────────────────────────────────────────

export interface DiffBulkPair {
  env_id_a: string;
  env_id_b: string;
}

export interface DiffBulkRequest {
  pairs: DiffBulkPair[];
}

export interface DiffBulkResultEntry {
  env_id_a: string;
  env_id_b: string;
  ok: boolean;
  identical?: boolean;
  summary?: { added: number; removed: number; changed: number };
  error?: string | null;
}

export interface DiffBulkResponse {
  total: number;
  ok: number;
  failed: number;
  results: DiffBulkResultEntry[];
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

export interface ImportBulkEntry {
  env_id?: string;
  data: Record<string, unknown>;
}

export interface ImportEnvironmentsBulkRequest {
  version?: string;
  entries: ImportBulkEntry[];
}

export interface ImportBulkResultEntry {
  env_id?: string;
  new_id?: string;
  ok: boolean;
  error?: string;
}

export interface ImportEnvironmentsBulkResponse {
  total: number;
  succeeded: number;
  failed: number;
  results: ImportBulkResultEntry[];
}
