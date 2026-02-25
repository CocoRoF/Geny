// ==================== Session Types ====================

export interface SessionInfo {
  session_id: string;
  session_name: string | null;
  status: 'running' | 'stopped' | 'error' | 'idle' | string;
  model: string | null;
  role: 'worker' | 'manager';
  autonomous: boolean;
  max_turns: number | null;
  timeout: number | null;
  autonomous_max_iterations: number | null;
  storage_path: string | null;
  created_at: string | null;
  pid: number | null;
  pod_name: string | null;
  pod_ip: string | null;
  manager_id: string | null;
  workflow_id: string | null;
  is_deleted?: boolean;
  deleted_at?: string | null;
}

export interface CreateAgentRequest {
  session_name?: string;
  working_dir?: string;
  model?: string;
  max_turns?: number;
  timeout?: number;
  autonomous?: boolean;
  autonomous_max_iterations?: number;
  role?: string;
  manager_id?: string;
  system_prompt?: string;
  enable_checkpointing?: boolean;
  workflow_id?: string;
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

export interface AutonomousExecuteRequest {
  prompt: string;
  max_iterations?: number;
  timeout_per_iteration?: number;
  system_prompt?: string;
  max_turns?: number;
  skip_permissions?: boolean;
}

export interface AutonomousExecuteResponse {
  success: boolean;
  session_id: string;
  is_complete: boolean;
  total_iterations: number;
  original_request: string;
  final_output: string;
  all_outputs?: string[];
  error?: string;
  total_duration_ms: number;
  stop_reason: string;
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

export interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
  metadata?: {
    is_truncated?: boolean;
    preview?: string;
    prompt_length?: number;
    output_length?: number;
  };
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
  options?: Array<{ value: string; label: string }>;
  min?: number;
  max?: number;
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
  graph_type: 'simple' | 'autonomous';
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ==================== Dashboard Types ====================

export interface WorkerInfo {
  worker_id: string;
  worker_name: string;
  status: string;
  is_busy: boolean;
  current_task?: string;
}

export interface ManagerEvent {
  timestamp: string;
  event_type: string;
  message: string;
  worker_id?: string;
}

export interface ManagerDashboard {
  manager_id: string;
  manager_name: string;
  workers: WorkerInfo[];
  recent_events: ManagerEvent[];
  active_delegations: number;
  completed_delegations: number;
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
