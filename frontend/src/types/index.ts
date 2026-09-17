// ==================== Session Types ====================

export interface SessionInfo {
  session_id: string;
  session_name: string | null;
  status: 'running' | 'stopped' | 'error' | 'idle' | string;
  model: string | null;
  role: 'worker' | 'developer' | 'researcher' | 'planner' | 'vtuber';
  linked_session_id?: string | null;
  session_type?: string | null;
  chat_room_id?: string | null;
  /** This session's OWN persona preset; null/absent = follow the
   *  environment. `effective_*` and `persona_source` say what actually
   *  runs and where it came from — a persona resolved from somewhere else
   *  is exactly what an operator cannot deduce from the screen. */
  persona_preset_id?: string | null;
  effective_persona_preset_id?: string | null;
  persona_source?: 'session' | 'environment' | 'none' | string | null;
  persona_name?: string | null;
  /** The user's own keep-awake choice for THIS session. `true` keeps it
   *  resident whatever the host's idle policy says, `false` lets it be
   *  reclaimed even while the host keeps everything else awake, and
   *  `null`/absent follows the host policy (Settings → Session Lifecycle). */
  always_on?: boolean | null;
  /** Id of the persistent companion sub-agent this agent owns, when its env
   *  declares one (host_selections.extras.owned_subagent). Env-driven, not
   *  role-driven. Absent/null → the agent owns no companion. */
  executor_sub_agent_id?: string | null;
  max_turns: number | null;
  timeout: number | null;
  max_iterations: number | null;
  storage_path: string | null;
  created_at: string | null;
  pid: number | null;
  pod_name: string | null;
  pod_ip: string | null;
  workflow_id: string | null;
  graph_name: string | null;
  tool_preset_id: string | null;
  total_cost: number | null;
  env_id?: string | null;
  /** Human name of the session's environment (manifest metadata.name). */
  env_name?: string | null;
  /** Active Stage-6 provider of the environment ("anthropic" | "openai" | …). */
  model_provider?: string | null;
  memory_config?: Record<string, unknown> | null;
  is_deleted?: boolean;
  deleted_at?: string | null;
  // Tamagotchi creature state snapshot. Present only when the session
  // has a state_provider attached (cycle 20260422_5 / X7). Classic
  // sessions omit this field entirely or receive null.
  creature_state?: CreatureStateSnapshot | null;
}

export interface CreatureStateSnapshot {
  character_id: string;
  owner_user_id: string;
  mood: {
    joy: number;
    sadness: number;
    anger: number;
    fear: number;
    calm: number;
    excitement: number;
  };
  mood_dominant: string;
  bond: {
    affection: number;
    trust: number;
    familiarity: number;
    dependency: number;
  };
  vitals: {
    hunger: number;      // 0=fully attended, 100=craving attention (Plan/Phase01)
    energy: number;      // 0=exhausted, 100=peak
    stress: number;      // 0=calm, 100=extreme
    cleanliness: number; // 0=filthy, 100=spotless
  };
  progression: {
    age_days: number;
    life_stage: string;
    xp: number;
    milestones: string[];
    manifest_id: string;
  };
  last_interaction_at: string | null;
  last_tick_at: string | null;
  recent_events: string[];
}

export interface CreateAgentRequest {
  session_name?: string;
  working_dir?: string;
  model?: string;
  max_turns?: number;
  timeout?: number;
  max_iterations?: number;
  role?: string;
  system_prompt?: string;
  enable_checkpointing?: boolean;
  workflow_id?: string;
  graph_name?: string;
  tool_preset_id?: string;
  sub_worker_system_prompt?: string;
  sub_worker_model?: string;
  sub_worker_env_id?: string;
  // Phase 6 — adopt EnvironmentManifest pipeline at session creation,
  // and override the per-session MemoryProvider config. Backend treats
  // both as optional; legacy preset path runs when env_id is absent.
  env_id?: string;
  memory_config?: Record<string, unknown>;
  /**
   * Trigger preset id (VTuber sessions only). When omitted, the
   * thinking-trigger runtime falls back to the bundled defaults.
   * Managed in the "트리거 관리" tab on the environments page.
   */
  trigger_preset_id?: string;
}

export interface ExecuteRequest {
  prompt: string;
  timeout?: number;
  skip_permissions?: boolean;
  system_prompt?: string;
  max_turns?: number;
}

export interface ExecuteResponse {
  success: boolean;
  session_id: string;
  output?: string;
  error?: string;
  cost_usd?: number;
  duration_ms?: number;
}

// ==================== Chat Room Types ====================

export interface ChatRoom {
  id: string;
  name: string;
  session_ids: string[];
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ChatRoomListResponse {
  rooms: ChatRoom[];
  total: number;
}

/**
 * One memory subsystem event emitted by the backend during an
 * execution turn. Mirrors :func:`SessionLogger.log_memory_event` /
 * :func:`extract_memory_events_from_cache` on the backend side.
 *
 * The frontend chat handler turns each record into a row in the
 * VTuber LOGS panel via ``useVTuberStore.addLog`` with the matching
 * `source` bucket (Memory / Vector / Curated / Knowledge).
 */
export interface MemoryEvent {
  ts?: string;
  event_type: string;
  source: string;
  message: string;
  layer?: string;
  backend?: string;
  engine?: string;
  importance?: string;
  category?: string;
  path?: string;
  chars?: number;
  chunks?: number;
  score?: number;
  duration_ms?: number;
  extra?: Record<string, unknown>;
}

export interface ChatRoomMessage {
  id: string;
  type: 'user' | 'agent' | 'system';
  content: string;
  timestamp: string;
  session_id?: string | null;
  session_name?: string | null;
  role?: string | null;
  duration_ms?: number | null;
  file_changes?: FileChanges[];
  /**
   * Memory subsystem events recorded during this turn (note writes,
   * vector indexing, curated promotions, knowledge searches). Drives
   * the VTuber LOGS panel rendering downstream.
   */
  memory_events?: MemoryEvent[];
  /** Attachment metadata (image / file refs uploaded via POST /api/uploads). */
  attachments?: ChatAttachment[];
  meta?: Record<string, unknown>;
  /**
   * TTS-fix (2026-04-26): backend-tagged origin so the frontend can
   * suppress auto-TTS for messages the user didn't initiate.
   *
   * Known values:
   * - ``thinking_trigger`` — VTuber idle / heartbeat output.
   * - ``sub_worker_reply`` — VTuber's response to a [SUB_WORKER_RESULT].
   * - ``inbox_drain`` — sub-worker output forwarded to the VTuber.
   * - ``undefined`` — direct user-initiated reply (default; spoken).
   */
  source?: string | null;
}

/**
 * Attachment metadata stored on user chat messages and forwarded to the
 * agent pipeline. Mirrors the backend ``UploadedFile`` /
 * ``BroadcastAttachment`` schemas.
 *
 * The frontend uploads files via ``POST /api/uploads`` first and only
 * passes back the metadata reference here — raw bytes never go through
 * the broadcast endpoint.
 */
export interface ChatAttachment {
  kind: 'image' | 'audio' | 'file';
  name?: string;
  mime_type?: string;
  size?: number;
  sha256?: string;
  /** sha256 hex returned by POST /api/uploads. */
  attachment_id?: string;
  /** Static URL such as /static/uploads/ab/<sha>.<ext>. */
  url?: string;
  /** Inline base64 fallback (for tiny pasted images). */
  data?: string;
  /** Provenance discriminator. ``screen_observation`` = an auto-captured
   *  screen frame (ambient context); the backend keeps it out of chat
   *  history and honours the screen-image kill-switch. */
  source?: string;
}

export interface ChatRoomMessageListResponse {
  room_id: string;
  messages: ChatRoomMessage[];
  total: number;
  has_more?: boolean;
}

export interface ChatRoomBroadcastRequest {
  message: string;
  attachments?: ChatAttachment[];
}

export interface ChatRoomBroadcastResponse {
  user_message: ChatRoomMessage;
  broadcast_id: string | null;
  target_count: number;
}

// WebSocket event types from room event stream
export type ChatEventType =
  | 'message'
  | 'broadcast_status'
  | 'broadcast_done'
  | 'agent_progress'
  | 'heartbeat';

export interface BroadcastStatus {
  broadcast_id: string;
  total: number;
  completed: number;
  responded: number;
  finished: boolean;
}

// Per-agent execution state during broadcast
export interface AgentProgressState {
  session_id: string;
  session_name: string;
  role: string;
  status: 'pending' | 'executing' | 'completed' | 'failed' | 'queued';
  thinking_preview: string | null;
  streaming_text: string | null;
  elapsed_ms?: number;
  last_activity_ms?: number;
  last_tool_name?: string;
  recent_logs?: AgentLogEntry[];
  log_cursor?: number;
}

export interface AgentLogEntry {
  level: string;
  message: string;
  ts?: string | null;
  tool_name?: string;
  node_name?: string;
  /** What the call was, so the timeline can describe it rather than print
   *  the log line. Present on TOOL / TOOL_RES entries. */
  tool_id?: string;
  input_preview?: string;
  result_preview?: string;
  duration_ms?: number;
  is_error?: boolean;
}

export interface AgentProgressEvent {
  broadcast_id: string;
  agents: AgentProgressState[];
}

export interface ChatWsEvent {
  type: ChatEventType;
  data: ChatRoomMessage | BroadcastStatus | AgentProgressEvent | { ts?: number };
}


// ==================== Health Types ====================

export interface HealthStatus {
  status: string;
  pod_name: string;
  pod_ip: string;
  redis: string;
  total_sessions?: number;
  local_sessions?: number;
  running_sessions?: number;
  error_sessions?: number;
}

// ==================== Log Types ====================

/** Structured file change hunk for diff display */
export interface FileChangeHunk {
  old_str?: string;
  new_str?: string;
}

/** File change data attached to tool_use logs for IDE-like diff display */
export interface FileChanges {
  file_path: string;
  operation: 'write' | 'create' | 'edit' | 'multi_edit';
  changes: FileChangeHunk[];
  lines_added: number;
  lines_removed: number;
  is_content_truncated?: boolean;
  total_edits?: number;
}

/** Command/shell data for terminal-like display */
export interface CommandData {
  command: string;
  working_dir?: string;
}

/** File read data for code viewer */
export interface FileReadData {
  file_path: string;
  start_line?: number;
  end_line?: number;
}

/** Rich metadata for log entries — matches backend SessionLogger output */
export interface LogEntryMetadata {
  // Common
  type?: 'command' | 'response' | 'tool_use' | 'tool_result' | 'iteration_complete' | 'stream_event' | string;
  is_truncated?: boolean;
  preview?: string;

  // Command metadata
  prompt_length?: number;
  timeout?: number;
  system_prompt_preview?: string;
  max_turns?: number;

  // Response metadata
  success?: boolean;
  duration_ms?: number;
  cost_usd?: number;
  output_length?: number;
  tool_call_count?: number;
  num_turns?: number;

  // Tool use metadata
  tool_name?: string;
  tool_id?: string;
  detail?: string;
  input_preview?: string;
  input_length?: number;

  // Tool result metadata
  is_error?: boolean;
  result_preview?: string;
  result_length?: number;

  // Iteration metadata
  iteration?: number;
  is_complete?: boolean;
  stop_reason?: string;

  // Stage event metadata (mirrors geny-executor Environment pipeline stages)
  event_id?: string;
  event_type?: string;
  node_name?: string;           // legacy mirror of stage_name for older readers
  stage_name?: string;
  stage_order?: number;
  stage_display_name?: string;  // e.g. "s16_yield"
  state_snapshot?: Record<string, unknown>;
  data?: Record<string, unknown>;

  // Per-turn context — which environment + role produced this entry.
  // Threaded through log_command / log_response in agent_executor.
  env_id?: string;
  role?: string;

  // Delegation events (event === 'delegation.sent' | 'delegation.received')
  event?: string;
  tag?: string;
  from_session_id?: string;
  to_session_id?: string;
  from_role?: string;
  to_role?: string;
  task_id?: string;

  // Rich structured data for IDE display (injected by enhanced logger)
  file_changes?: FileChanges;
  command_data?: CommandData;
  file_read?: FileReadData;

  // Executor error code (since executor 2.1.0). Carries the stable
  // ``exec.<component>.<reason>`` identifier so the UI can render the
  // error via i18n key (``executor.<code>``) instead of the raw
  // English message text. Also surfaces on response-type entries and
  // stage_error events.
  error_code?: string;
  // Fully-qualified exception class for Sentry / log grouping when no
  // structured code is attached.
  exception_type?: string;

  // Catch-all
  [key: string]: unknown;
}

export interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
  metadata?: LogEntryMetadata;
}

export interface SessionLogsResponse {
  session_id: string;
  log_file: string;
  entries: LogEntry[];
  total_entries: number;
}

// ==================== Storage Types ====================

export interface StorageFile {
  path: string;
  size: number;
  /** Backend field name is is_dir; is_directory kept for back-compat. */
  is_dir?: boolean;
  is_directory?: boolean;
  /** ISO mtime from the backend — the canvas cache-buster key. */
  modified_at?: string | null;
}

export interface StorageListResponse {
  session_id: string;
  storage_path: string;
  files: StorageFile[];
}

export interface StorageFileContent {
  session_id: string;
  path: string;
  content: string;
  size?: number;
}

// ==================== Config Types ====================

export interface ConfigField {
  name: string;
  label: string;
  type: 'string' | 'boolean' | 'number' | 'select' | 'textarea' | 'url' | 'email' | 'password';
  description?: string;
  placeholder?: string;
  default?: unknown;
  required?: boolean;
  secure?: boolean;
  group?: string;
  options?: Array<{ value: string; label: string; group?: string }>;
  min?: number;
  max?: number;
  depends_on?: string;  // Sibling field name whose value filters this field's options (matched via option.group)
  visible_when?: Record<string, string[]>;  // Field shows only when EVERY {siblingField: [allowedValues]} holds (e.g. { memory_engine: ['composite'] })
}

export interface ConfigI18nLocale {
  display_name?: string;
  description?: string;
  groups?: Record<string, string>;
  fields?: Record<string, {
    label?: string;
    description?: string;
    placeholder?: string;
  }>;
}

export interface ConfigSchema {
  name: string;
  display_name: string;
  description: string;
  category?: string;
  icon?: string;
  fields: ConfigField[];
  i18n?: Record<string, ConfigI18nLocale>;
  /** Optional per-locale Markdown setup guide (rendered in a modal). */
  setup_guide?: Record<string, string>;
}

export interface ConfigItem {
  schema: ConfigSchema;
  values: Record<string, unknown>;
  valid: boolean;
  errors?: string[];
}

export interface ConfigCategory {
  name: string;
  label: string;
}

export interface ConfigListResponse {
  configs: ConfigItem[];
  categories: ConfigCategory[];
}

// ==================== Tool Settings (per-environment) ====================

/**
 * Schema describing one configurable per-environment tool (e.g. `web_search`).
 * Fields share the exact shape of {@link ConfigField} used by global settings,
 * so the existing `ConfigFieldInput` / localization helpers render them as-is.
 * Values are stored on the manifest draft at
 * `host_selections.extras.tool_settings[<key>]` and ride the normal save.
 */
export interface ToolSettingSchema {
  key: string;
  display_name: string;
  description: string;
  icon?: string;
  fields: ConfigField[];
  i18n?: Record<string, ConfigI18nLocale>;
  /** Optional per-locale Markdown setup guide (rendered in a modal). */
  setup_guide?: Record<string, string>;
}

export interface ToolSettingSchemasResponse {
  schemas: ToolSettingSchema[];
}

// ==================== Graph Types ====================

export interface GraphNode {
  id: string;
  label: string;
  type: 'start' | 'end' | 'node' | 'resilience';
  description?: string;
  prompt?: string;
  path?: string;
  prompt_template?: string;
  metadata?: Record<string, unknown> & {
    path?: string;
    inner_graph?: {
      description?: string;
      nodes: { id: string; label: string }[];
    };
  };
}

export interface GraphEdge {
  source: string;
  target: string;
  label?: string;
  conditional?: boolean;
  condition_map?: Record<string, string>;
}

export interface GraphStructure {
  session_id: string;
  session_name: string;
  graph_type: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ==================== Prompt Types ====================

export interface PromptInfo {
  name: string;
  filename: string;
  description?: string;
}

export interface PromptListResponse {
  prompts: PromptInfo[];
  total: number;
}

// ==================== Workflow Types ====================

export interface AvailableServerInfo {
  name: string;
  type: string;
  description: string;
}

export interface AvailableToolInfo {
  name: string;
  description: string;
}

export interface AvailableToolsResponse {
  servers: AvailableServerInfo[];
  tools: AvailableToolInfo[];
}

// ==================== Tool Preset Types ====================

export type BuiltInMode = 'inherit' | 'allowlist' | 'blocklist';

export interface ToolPresetDefinition {
  id: string;
  name: string;
  description: string;
  icon?: string;
  custom_tools: string[];
  mcp_servers: string[];
  // PR-F.5.1 — per-preset framework built-in selection.
  built_in_mode?: BuiltInMode;
  built_in_tools?: string[];
  built_in_deny?: string[];
  created_at: string;
  updated_at: string;
  is_template: boolean;
  template_name?: string;
}

export interface ToolInfo {
  name: string;
  description: string;
  category: string;    // "built_in" or "custom"
  group?: string;      // source file stem
  parameters?: Record<string, unknown>;
}

export interface MCPServerInfo {
  name: string;
  type: string;        // "stdio", "http", "sse"
  description?: string;
  is_built_in?: boolean; // true for mcp/built_in/ servers (always included)
  source?: string;      // "built_in" or "custom"
}

export interface ToolCatalogResponse {
  built_in: ToolInfo[];
  custom: ToolInfo[];
  mcp_servers: MCPServerInfo[];
  total_python_tools: number;
  total_mcp_servers: number;
}

export interface ToolPresetListResponse {
  presets: ToolPresetDefinition[];
  total: number;
}

// ==================== Memory Types ====================

export interface MemoryFileInfo {
  filename: string;
  /** The INDEX's id for this note (`<scope>/<category>/<filename>`), when
   *  it came from the catalogue. The client must never build one: the
   *  format is the index's business and includes parts the browser cannot
   *  know — reconstructing it as `<category>/<filename>` silently matched
   *  nothing, so the graph came back empty whenever a note was selected. */
  node_id?: string;
  title: string;
  category: string;
  tags: string[];
  importance: string;
  created: string;
  modified: string;
  source: string;
  char_count: number;
  links_to: string[];
  linked_from: string[];
  summary: string | null;
}

export interface MemoryFileDetail {
  /** Host-extension sidecar (usually empty). NOT the frontmatter —
   * category/importance/title/tags arrive as the top-level fields. */
  metadata: Record<string, unknown>;
  body: string;
  filename: string;
  title?: string;
  category?: string;
  importance?: string;
  tags?: string[];
  frontmatter?: Record<string, unknown>;
  links_to?: string[];
  linked_from?: string[];
  created?: string;
  modified?: string;
}

export interface MemoryStats {
  long_term_entries: number;
  short_term_entries: number;
  long_term_chars: number;
  short_term_chars: number;
  total_files: number;
  last_write: string | null;
  categories: Record<string, number>;
  total_tags: number;
  total_links: number;
}

export interface MemoryIndex {
  files: Record<string, MemoryFileInfo>;
  tag_map: Record<string, string[]>;
  total_files: number;
  total_chars: number;
}

export interface MemoryIndexResponse {
  index: MemoryIndex;
  stats: MemoryStats;
}

export interface MemorySearchEntry {
  source: string;
  content: string;
  timestamp: string | null;
  filename: string | null;
  title: string | null;
  category: string | null;
  tags: string[];
  importance: string;
  links_to: string[];
  linked_from: string[];
  summary: string | null;
  char_count: number;
  metadata: Record<string, unknown>;
}

export interface MemorySearchResult {
  entry: MemorySearchEntry;
  score: number;
  snippet: string;
  match_type: string;
}

export interface MemorySearchResponse {
  query: string;
  results: MemorySearchResult[];
  total: number;
}

export interface MemoryGraphNode {
  id: string;
  label: string;
  category: string;
  importance: string;
  tags?: string[];
  connectionCount?: number;
  summary?: string;
  charCount?: number;
}

export interface MemoryGraphEdge {
  source: string;
  target: string;
  type?: 'wikilink' | 'tag' | 'backlink' | 'semantic';
  weight?: number;
  label?: string;
}

export interface MemoryGraphResponse {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
}

/** One row of `/memory/files` — index metadata plus a first-paragraph
 *  preview. NOT a `MemoryFileDetail`: there is no body here, and the
 *  listing has never returned one. */
export interface MemoryFileSummary {
  filename: string;
  title: string;
  category: string;
  tags: string[];
  importance: string;
  char_count: number;
  modified: string;
  created?: string;
  source?: string;
  links_to?: string[];
  linked_from?: string[];
  first_paragraph?: string | null;
}

export interface MemoryFileListResponse {
  files: MemoryFileSummary[];
  /** Notes in the vault matching the filter — NOT the page size.
   *  (It used to be the latter, which made a full page indistinguishable
   *  from a full vault.) */
  total: number;
  returned?: number;
  limit?: number;
  offset?: number;
  has_more?: boolean;
}

// ==================== Vault catalogue (progressive disclosure) ====================
//
// Three steps, each paying only for what the user just asked to see:
// counts → a day's notes → a note's body. The shapes below mirror
// /memory/overview, /memory/day/{day} and /memory/graph/around; the
// bodies never appear here on purpose.

export interface MemoryOverview {
  total: number;
  kinds: { kind: string; count: number }[];
  /** Newest day first; days with zero notes are absent. */
  days: { day: string; count: number }[];
}

/** One note as the catalogue knows it — index metadata, no body. */
export interface MemoryDayNote {
  id: string;
  filename: string;
  category: string;
  title: string;
  updated_at: string | null;
  char_count: number;
  pinned: boolean;
}

export interface MemoryDayResponse {
  day: string;
  notes: MemoryDayNote[];
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface MemoryNeighbourhoodNode {
  id: string;
  kind: string;
  title: string;
  updated_at: string | null;
  text_len: number;
  pinned: boolean;
  /** The index's ranking WEIGHT (a REAL, default 1.0) — NOT the
   *  'critical' | 'high' | 'medium' | 'low' label the UI colours by.
   *  Typed as it actually arrives so nothing can hand it to a string
   *  method by mistake; convert through `importanceLabel`. */
  importance: number | string | null;
  /** The label the backend derived from that weight. Preferred when
   *  present: the scale lives on the server, so the client does not need
   *  a second copy of "2.0 means critical" to drift from. */
  importance_label?: string | null;
}

export interface MemoryNeighbourhoodEdge {
  src: string;
  dst: string;
  type: string;
  w: number;
}

export interface MemoryNeighbourhood {
  nodes: MemoryNeighbourhoodNode[];
  edges: MemoryNeighbourhoodEdge[];
  /** The bound was hit — what is shown is a screen's worth, not all of it. */
  truncated: boolean;
}

// ==================== InteractionEvent / Transcripts (cycle 20260430_3) ====================
//
// Wire shapes returned by /api/agents/{sid}/transcripts*. Mirror the
// backend's TranscriptListResponse / TranscriptDetailResponse /
// CounterpartListResponse exactly — drift is caught by the controller's
// schema-parity test (cycle 20260430_3 A).

/** Summary shape used by the list endpoint and by the detail endpoint's
 *  `linked.parent`. Same key set as the LLM tool memory_event uses. */
export interface InteractionEventSummary {
  event_id: string;
  ts: string | null;
  kind: string | null;
  direction: string | null;
  counterpart_id: string | null;
  counterpart_role: string | null;
  summary: string | null;
  linked_event_id?: string | null;
  status?: string;
  files_written_count?: number;
  tools_used_count?: number;
}

/** Full payload returned by GET /transcripts/{event_id}. */
export interface InteractionEventDetail {
  event_id: string;
  ts: string | null;
  kind: string | null;
  direction: string | null;
  counterpart_id: string | null;
  counterpart_role: string | null;
  linked_event_id: string | null;
  content: string;
  payload: Record<string, unknown>;
}

export interface TranscriptListResponse {
  events: InteractionEventSummary[];
  next_cursor: string | null;
  has_more: boolean;
  total_estimate: number;
}

export interface TranscriptDetailLinked {
  parent?: InteractionEventSummary | { event_id: string; missing: true };
}

export interface TranscriptDetailResponse {
  event: InteractionEventDetail;
  linked: TranscriptDetailLinked;
}

export interface CounterpartCard {
  id: string;
  role: string | null;
  events: number;
  last_ts: string | null;
}

export interface CounterpartListResponse {
  counterparts: CounterpartCard[];
}

export interface ArtifactReadResponse {
  event_id: string;
  path: string;
  size_bytes: number;
  truncated: boolean;
  content: string;
}

// ==================== VTuber / Live2D Types ====================

export interface Live2dModelInfo {
  name: string;
  display_name: string;
  description: string;
  url: string;
  thumbnail: string | null;
  kScale: number;
  initialXshift: number;
  initialYshift: number;
  idleMotionGroupName: string;
  emotionMap: Record<string, number>;
  tapMotions: Record<string, Record<string, number>>;
  hiddenParts?: string[];
  // Phase C.1 (geny-avatar integration): the backend now tags every
  // entry with `runtime` so the frontend dispatcher can route to the
  // right canvas. Pre-v2 registries (no runtime field) fall back to
  // "live2d" on the backend, so undefined here means "treat as live2d".
  // 'mmd' (3D PMX/PMD via babylon-mmd) joined with the MMD runtime.
  runtime?: 'live2d' | 'spine' | 'mmd';
  // Spine-only: URL of the .atlas sibling of `url` (.skel/.json).
  // Live2D entries leave this null/undefined.
  atlas_url?: string | null;
  // MMD-only: renderer config bag from the editor's avatar-editor.json
  // sidecar (passed through the backend registry verbatim).
  mmdConfig?: MmdModelConfig | null;
}

/** MMD renderer config — see backend Live2dModelInfo.mmdConfig. */
export interface MmdModelConfig {
  /** emotion key → morph NAME (MMD morphs are name-addressed) */
  emotionMorphMap?: Record<string, string>;
  /** mouth morph driven by TTS amplitude; null/absent = auto-detect */
  lipSyncMorph?: string | null;
  /** saved default camera pose from the editor */
  camera?: {
    alpha: number;
    beta: number;
    radius: number;
    targetX: number;
    targetY: number;
    targetZ: number;
  } | null;
  hiddenMaterials?: string[];
  hiddenMaterialIndices?: number[];
  morphs?: { name: string; panel: 'brow' | 'eye' | 'mouth' | 'other' }[];
  /** VMD motions in the installed bundle — paths relative to the zip
   *  root (== the model URL's directory tree). The renderer loops the
   *  one whose name matches Live2dModelInfo.idleMotionGroupName. */
  vmds?: { name: string; path: string }[];
}

export interface AvatarState {
  session_id: string;
  emotion: string;
  expression_index: number;
  motion_group: string;
  // `null` means "the backend left index unspecified — let the Live2D
  // engine pick a random motion in the group". Explicit numeric values
  // come from tap interactions or hand-set motion overrides.
  motion_index: number | null;
  intensity: number;
  transition_ms: number;
  trigger: string;
  timestamp: string;
}

export interface VTuberLogEntry {
  id: number;
  timestamp: string;
  level: 'info' | 'state' | 'error' | 'warn' | 'debug';
  source: string;
  message: string;
  detail?: Record<string, unknown>;
}
