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
  memory_config?: Record<string, unknown> | null;
  is_deleted?: boolean;
  deleted_at?: string | null;
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

export interface CreateChatRoomRequest {
  name: string;
  session_ids: string[];
}

export interface UpdateChatRoomRequest {
  name?: string;
  session_ids?: string[];
}

export interface ChatRoomListResponse {
  rooms: ChatRoom[];
  total: number;
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
  meta?: Record<string, unknown>;
}

export interface ChatRoomMessageListResponse {
  room_id: string;
  messages: ChatRoomMessage[];
  total: number;
  has_more?: boolean;
}

export interface ChatRoomBroadcastRequest {
  message: string;
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

  // Graph event metadata
  event_id?: string;
  event_type?: string;
  node_name?: string;
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
  is_directory?: boolean;
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

export interface ToolPresetDefinition {
  id: string;
  name: string;
  description: string;
  icon?: string;
  custom_tools: string[];
  mcp_servers: string[];
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
  metadata: Record<string, unknown>;
  body: string;
  filename: string;
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
  type?: 'wikilink' | 'tag' | 'backlink';
  weight?: number;
  label?: string;
}

export interface MemoryGraphResponse {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
}

export interface MemoryFileListResponse {
  files: MemoryFileDetail[];
  total: number;
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
}

export interface AvatarState {
  session_id: string;
  emotion: string;
  expression_index: number;
  motion_group: string;
  motion_index: number;
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
