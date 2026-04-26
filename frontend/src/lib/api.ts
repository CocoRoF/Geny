/**
 * API Communication Layer
 * Mirrors all legacy frontend-legacy/static/components/api.js endpoints
 */

import { getToken } from '@/lib/authApi';

// ==================== Base Fetch Wrapper ====================

async function apiCall<T = unknown>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const authHeaders: Record<string, string> = {};
  if (token) authHeaders['Authorization'] = `Bearer ${token}`;

  const res = await fetch(endpoint, {
    headers: { 'Content-Type': 'application/json', ...authHeaders, ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    let message: string;
    try {
      const json = JSON.parse(body);
      const raw = json.detail || json.message || json.error;
      message = typeof raw === 'string' ? raw : raw ? JSON.stringify(raw) : `HTTP ${res.status}`;
    } catch {
      message = body || `HTTP ${res.status}`;
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

// ==================== Backend Direct URL ====================
// In production behind a reverse proxy (nginx), NEXT_PUBLIC_API_URL should be
// set to '' (empty) so that the browser uses relative paths through nginx.
export function getBackendUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  // Explicitly set (including empty string '' for reverse-proxy setups)
  if (envUrl !== undefined) return envUrl;
  // Fallback: same hostname as the browser page, backend port from env (local dev)
  const port = process.env.NEXT_PUBLIC_BACKEND_PORT || '8000';
  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:${port}`;
  }
  return `http://localhost:${port}`;
}

// ==================== WebSocket URL ====================
// Converts the backend HTTP URL to a WebSocket URL for streaming.
/**
 * Convert the backend HTTP URL to a WebSocket URL.
 * Uses the SAME logic as getBackendUrl() to ensure consistency —
 * both HTTP API calls and WebSocket connections go to the same host.
 */
function _getWsBase(): string {
  const httpBase = getBackendUrl();
  if (!httpBase) {
    // Production: relative path through nginx
    if (typeof window !== 'undefined') {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      return `${proto}//${window.location.host}`;
    }
    return 'ws://localhost:8000';
  }
  return httpBase.replace(/^http/, 'ws');
}

function getWsUrl(sessionId: string): string {
  return `${_getWsBase()}/ws/execute/${sessionId}`;
}

function getChatWsUrl(roomId: string): string {
  return `${_getWsBase()}/ws/chat/rooms/${roomId}`;
}

// ==================== Agent API ====================

import type {
  SessionInfo,
  CreateAgentRequest,
  ExecuteRequest,
  ExecuteResponse,
  GraphStructure,
  StorageListResponse,
  StorageFileContent,
  CreateChatRoomRequest,
  UpdateChatRoomRequest,
  ChatRoom,
  ChatRoomListResponse,
  ChatRoomMessageListResponse,
  ChatRoomBroadcastRequest,
  ChatRoomBroadcastResponse,
  ChatRoomMessage,
  ChatAttachment,
  Live2dModelInfo,
  AvatarState,
} from '@/types';

export const agentApi = {
  /** GET /api/agents — list all sessions */
  list: () => apiCall<SessionInfo[]>('/api/agents'),

  /** GET /api/agents/store/deleted — list deleted sessions */
  listDeleted: () => apiCall<SessionInfo[]>('/api/agents/store/deleted'),

  /** POST /api/agents — create new session */
  create: (data: CreateAgentRequest) =>
    apiCall<SessionInfo>('/api/agents', { method: 'POST', body: JSON.stringify(data) }),

  /** DELETE /api/agents/{id} — soft-delete session */
  delete: (id: string) =>
    apiCall<{ success: boolean }>(`/api/agents/${id}`, { method: 'DELETE' }),

  /** DELETE /api/agents/{id}/permanent — permanent delete */
  permanentDelete: (id: string) =>
    apiCall<{ success: boolean }>(`/api/agents/${id}/permanent`, { method: 'DELETE' }),

  /** POST /api/agents/{id}/restore — restore deleted session */
  restore: (id: string) =>
    apiCall<{ success: boolean }>(`/api/agents/${id}/restore`, { method: 'POST' }),

  /** GET /api/agents/{id} — get session details */
  get: (id: string) => apiCall<SessionInfo>(`/api/agents/${id}`),

  /** GET /api/agents/store/{id} — get stored (deleted) session detail */
  getStore: (id: string) => apiCall<SessionInfo>(`/api/agents/store/${id}`),

  /** POST /api/agents/{id}/execute — execute single command */
  execute: (id: string, data: ExecuteRequest) =>
    apiCall<ExecuteResponse>(`/api/agents/${id}/execute`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /**
   * WebSocket streaming execute.
   *
   * Opens a single WebSocket connection to /ws/execute/{id} and sends
   * the execute command. Events are pushed in real time without polling.
   */
  executeStream: async (
    id: string,
    data: ExecuteRequest,
    onEvent: (eventType: string, eventData: Record<string, unknown>) => void,
  ): Promise<void> => {
    const wsUrl = getWsUrl(id);
    const _tag = `[ExecWS:${id.slice(0, 8)}]`;
    console.debug(`${_tag} executeStream called, wsUrl=${wsUrl}, prompt=${data.prompt.slice(0, 60)}...`);

    return new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(wsUrl);
      let resolved = false;

      const finish = () => {
        if (!resolved) {
          resolved = true;
          console.debug(`${_tag} stream finished`);
          resolve();
        }
      };

      ws.onopen = () => {
        console.debug(`${_tag} connected, sending execute command`);
        ws.send(JSON.stringify({
          type: 'execute',
          prompt: data.prompt,
          timeout: data.timeout ?? null,
          system_prompt: data.system_prompt ?? null,
          max_turns: data.max_turns ?? null,
        }));
      };

      ws.onmessage = (ev) => {
        try {
          const event = JSON.parse(ev.data);
          if (event.type !== 'heartbeat') {
            console.debug(`${_tag} event: ${event.type}`, event.data);
          }
          onEvent(event.type, event.data);
          if (event.type === 'done') {
            finish();
          }
        } catch (err) {
          console.warn(`${_tag} failed to parse WS message:`, ev.data, err);
        }
      };

      ws.onerror = (err) => {
        console.error(`${_tag} WebSocket error, url=${wsUrl}`, err);
        if (!resolved) {
          resolved = true;
          onEvent('error', { error: `WebSocket connection failed: ${wsUrl}` });
          reject(new Error(`WebSocket connection failed: ${wsUrl}`));
        }
      };

      ws.onclose = (ev) => {
        console.info(`${_tag} closed (code=${ev.code}, reason=${ev.reason || 'none'})`);
        finish();
      };
    });
  },

  /** POST /api/agents/{id}/stop — stop execution */
  stop: (id: string) =>
    apiCall<{ success: boolean }>(`/api/agents/${id}/stop`, {
      method: 'POST',
    }),

  /** GET /api/agents/{id}/execute/status — check if execution is active */
  getExecutionStatus: (id: string) =>
    apiCall<{ active: boolean; done?: boolean; has_error?: boolean; session_id: string; elapsed_ms?: number; last_activity_ms?: number; last_event_level?: string; last_tool_name?: string }>(
      `/api/agents/${id}/execute/status`,
    ),

  /**
   * Reconnect to a running execution via WebSocket.
   *
   * Used when the page reloads or the user returns after locking the phone.
   * Sends a "reconnect" message to resume streaming from the current position.
   */
  reconnectStream: (
    id: string,
    onEvent: (eventType: string, eventData: Record<string, unknown>) => void,
  ): { close: () => void } => {
    const wsUrl = getWsUrl(id);
    const _tag = `[ReconnWS:${id.slice(0, 8)}]`;
    console.debug(`${_tag} reconnectStream called, wsUrl=${wsUrl}`);
    let ws: WebSocket | null = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.debug(`${_tag} connected, sending reconnect`);
      ws!.send(JSON.stringify({ type: 'reconnect' }));
    };

    ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data);
        if (event.type !== 'heartbeat') {
          console.debug(`${_tag} event: ${event.type}`, event.data);
        }
        onEvent(event.type, event.data);
      } catch (err) {
        console.warn(`${_tag} failed to parse WS message:`, ev.data, err);
      }
    };

    ws.onerror = (err) => {
      console.error(`${_tag} WebSocket error, url=${wsUrl}`, err);
      onEvent('error', { error: `WebSocket reconnection failed: ${wsUrl}` });
      ws = null;
    };

    ws.onclose = (ev) => {
      console.info(`${_tag} closed (code=${ev.code}, reason=${ev.reason || 'none'})`);
      ws = null;
    };

    return {
      close: () => {
        if (ws) {
          ws.close();
          ws = null;
        }
      },
    };
  },

  /**
   * HITL (Human-in-the-loop) — Stage 15 approval surface (G2.5+G4.1).
   *
   * Backend endpoints registered by `controller.agent_controller`. The
   * modal opens on a `hitl_request` log event and closes once the
   * decision lands as a `hitl_decision` event on the same WS stream.
   * `hitlPending` is a defensive fallback for cases where a request
   * lands before the page mounts (or after a forced reload).
   */
  hitlPending: (id: string) =>
    apiCall<{
      session_id: string;
      pending: Array<{ token: string }>;
    }>(`/api/agents/${id}/hitl/pending`),

  /** POST /api/agents/{id}/hitl/resume — resume a pending HITL token. */
  hitlResume: (
    id: string,
    body: { token: string; decision: 'approve' | 'reject' | 'cancel' },
  ) =>
    apiCall<{ session_id: string; token: string; decision: string; resumed: boolean }>(
      `/api/agents/${id}/hitl/resume`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  /** DELETE /api/agents/{id}/hitl/{token} — cancel a pending HITL token. */
  hitlCancel: (id: string, token: string) =>
    apiCall<{ session_id: string; token: string; cancelled: boolean }>(
      `/api/agents/${id}/hitl/${encodeURIComponent(token)}`,
      { method: 'DELETE' },
    ),

  /**
   * Crash-recovery checkpoint endpoints (G7.1 / G7.2).
   *
   * `checkpointsList` returns the available checkpoint ids for a
   * session (empty when the persist write side hasn't fired or the
   * preset keeps Stage 20 off). `checkpointsRestore` rebuilds
   * pipeline state from a single checkpoint — runtime fields
   * (llm_client, persister, hook_runner) stay bound from the
   * original attach_runtime call; only the message/iteration/tasks
   * snapshot is restored.
   */
  checkpointsList: (id: string) =>
    apiCall<{
      session_id: string;
      checkpoints: Array<{ checkpoint_id: string; written_at: number; size_bytes: number }>;
    }>(`/api/agents/${id}/checkpoints`),

  /** POST /api/agents/{id}/checkpoints/restore — restore a checkpoint. */
  checkpointsRestore: (id: string, checkpointId: string) =>
    apiCall<{ session_id: string; checkpoint_id: string; restored: boolean; messages_restored: number }>(
      `/api/agents/${id}/checkpoints/restore`,
      { method: 'POST', body: JSON.stringify({ checkpoint_id: checkpointId }) },
    ),

  /** GET /api/skills/list — registered SKILL.md inventory (G7.4). */
  skillsList: () =>
    apiCall<{
      skills: Array<{
        id: string | null;
        name: string | null;
        description: string | null;
        model: string | null;
        allowed_tools: string[];
      }>;
    }>(`/api/skills/list`),

  /** Admin viewers (G13). Read-only — operators still hand-edit YAML. */
  permissionsList: () =>
    apiCall<{
      mode: string;
      rules: Array<{ tool_name: string; pattern: string | null; behavior: string; source: string; reason: string | null }>;
      sources_consulted: string[];
    }>(`/api/permissions/list`),

  hooksList: () =>
    apiCall<{
      enabled: boolean;
      env_opt_in: boolean;
      config_path: string;
      entries: Array<{ event: string; command: string[]; timeout_ms: number | null; tool_filter: string[] }>;
    }>(`/api/hooks/list`),

  /** Pipeline introspection (G15) — drives Dashboard heatmap. */
  pipelineIntrospect: (id: string) =>
    apiCall<{
      session_id: string;
      stages: Array<{
        order: number;
        name: string;
        artifact: string;
        strategy_slots: Record<string, { active: string | null; registered: string[] }>;
        strategy_chains: Record<string, { items: string[]; registered: string[] }>;
      }>;
    }>(`/api/agents/${id}/pipeline/introspect`),

  /** Per-session MCP admin endpoints (G8.1 / G8.3). */
  mcpServersList: (id: string) =>
    apiCall<{
      session_id: string;
      servers: Array<{ name: string; state: string; last_error: string | null }>;
    }>(`/api/agents/${id}/mcp/servers`),

  mcpServerAdd: (id: string, name: string, config: Record<string, unknown>) =>
    apiCall<{ session_id: string; server: { name: string; state: string; last_error: string | null } }>(
      `/api/agents/${id}/mcp/servers`,
      { method: 'POST', body: JSON.stringify({ name, config }) },
    ),

  mcpServerDisconnect: (id: string, name: string) =>
    apiCall<{ session_id: string; name: string; disconnected: boolean }>(
      `/api/agents/${id}/mcp/servers/${encodeURIComponent(name)}`,
      { method: 'DELETE' },
    ),

  mcpServerControl: (id: string, name: string, action: 'disable' | 'enable' | 'test') =>
    apiCall<{
      session_id: string; name: string; action: string; result: string;
      server: { name: string; state: string; last_error: string | null };
    }>(
      `/api/agents/${id}/mcp/servers/${encodeURIComponent(name)}/${action}`,
      { method: 'POST' },
    ),

  /** GET /api/agents/{id}/graph — graph structure */
  getGraph: (id: string) => apiCall<GraphStructure>(`/api/agents/${id}/graph`),

  /** GET /api/agents/{id}/workflow — pipeline preset info */
  getWorkflow: (id: string) =>
    apiCall<{ id: string; name: string; preset: string; execution_backend: string }>(`/api/agents/${id}/workflow`),

  /** PUT /api/agents/{id}/system-prompt — update system prompt */
  updateSystemPrompt: (id: string, systemPrompt: string | null) =>
    apiCall<{ success: boolean; length: number }>(`/api/agents/${id}/system-prompt`, {
      method: 'PUT',
      body: JSON.stringify({ system_prompt: systemPrompt }),
    }),

  /** GET /api/agents/{id}/thinking-trigger — get thinking trigger status */
  getThinkingTrigger: (id: string) =>
    apiCall<{
      session_id: string;
      enabled: boolean;
      registered: boolean;
      consecutive_triggers: number;
      current_threshold_seconds: number;
      base_threshold_seconds: number;
      max_threshold_seconds: number;
    }>(`/api/agents/${id}/thinking-trigger`),

  /** PUT /api/agents/{id}/thinking-trigger — enable/disable thinking trigger */
  updateThinkingTrigger: (id: string, enabled: boolean) =>
    apiCall<{ success: boolean; enabled: boolean }>(`/api/agents/${id}/thinking-trigger`, {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),

  /** GET /api/agents/{id}/storage — list storage files */
  listStorage: (id: string) => apiCall<StorageListResponse>(`/api/agents/${id}/storage`),

  /** GET /api/agents/{id}/storage/{path} — read file from storage */
  getStorageFile: (id: string, path: string) =>
    apiCall<StorageFileContent>(`/api/agents/${id}/storage/${encodeURIComponent(path)}`),

  /** GET /api/agents/{id}/download-folder — download storage as ZIP */
  downloadFolder: async (id: string) => {
    const res = await fetch(`/api/agents/${id}/download-folder`);
    if (!res.ok) {
      const body = await res.text();
      throw new Error(body || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `session-${id.slice(0, 8)}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};

// ==================== Background Tasks API (PR-A.5.5) ===========
//
// Wraps /api/agents/{sid}/tasks/ shipped in PR-A.5.4. session_id
// scopes the URL but task state is process-global per the runner's
// registry until a per-session backend is wired.

export interface BackgroundTaskRecord {
  task_id: string;
  kind: string;
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled';
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  payload: Record<string, unknown>;
  output_path: string | null;
}

export interface BackgroundTaskListResponse {
  tasks: BackgroundTaskRecord[];
}

export interface BackgroundTaskCreateResponse {
  task_id: string;
  status: string;
}

export const backgroundTaskApi = {
  list: (
    sessionId: string,
    opts: { status?: string; kind?: string; limit?: number } = {},
  ) => {
    const params = new URLSearchParams();
    if (opts.status) params.set('status', opts.status);
    if (opts.kind) params.set('kind', opts.kind);
    if (opts.limit !== undefined) params.set('limit', String(opts.limit));
    const qs = params.toString();
    return apiCall<BackgroundTaskListResponse>(
      `/api/agents/${encodeURIComponent(sessionId)}/tasks${qs ? '?' + qs : ''}`,
    );
  },

  create: (sessionId: string, kind: string, payload: Record<string, unknown> = {}) =>
    apiCall<BackgroundTaskCreateResponse>(
      `/api/agents/${encodeURIComponent(sessionId)}/tasks`,
      { method: 'POST', body: JSON.stringify({ kind, payload }) },
    ),

  get: (sessionId: string, taskId: string) =>
    apiCall<BackgroundTaskRecord>(
      `/api/agents/${encodeURIComponent(sessionId)}/tasks/${encodeURIComponent(taskId)}`,
    ),

  stop: (sessionId: string, taskId: string) =>
    apiCall<{ task_id: string; stopped: boolean }>(
      `/api/agents/${encodeURIComponent(sessionId)}/tasks/${encodeURIComponent(taskId)}`,
      { method: 'DELETE' },
    ),

  outputUrl: (sessionId: string, taskId: string) =>
    `${getBackendUrl()}/api/agents/${encodeURIComponent(sessionId)}/tasks/${encodeURIComponent(taskId)}/output`,
};

// ==================== Framework Tool Catalog API (PR-E.1.1) =====

export interface FrameworkToolCapabilities {
  concurrency_safe?: boolean;
  read_only?: boolean;
  destructive?: boolean;
  idempotent?: boolean;
  network_egress?: boolean;
  interrupt?: string;
  max_result_chars?: number;
}

export interface FrameworkToolDetail {
  name: string;
  description: string;
  feature_group: string;
  capabilities: FrameworkToolCapabilities;
  input_schema: Record<string, unknown>;
}

export interface FrameworkCatalogResponse {
  tools: FrameworkToolDetail[];
  groups: string[];
  total: number;
}

export const frameworkToolApi = {
  list: () => apiCall<FrameworkCatalogResponse>('/api/tools/catalog/framework'),
};

// ==================== Permissions CRUD API (PR-E.2.1) ============
//
// Read-only inspection lives at /api/permissions/list (admin viewer
// — see permissionAdminApi below). The CRUD surface mutates the
// user-scope settings.json. After every write the backend reloads the
// executor's SettingsLoader so live sessions pick up the change.

export type PermissionBehavior = 'allow' | 'deny' | 'ask';
export type PermissionSource = 'user' | 'project' | 'local' | 'cli' | 'preset';

export interface PermissionRulePayload {
  tool_name: string;
  behavior: PermissionBehavior;
  pattern?: string | null;
  source?: PermissionSource;
  reason?: string | null;
}

export interface PermissionRulesResponse {
  rules: PermissionRulePayload[];
  settings_path: string;
}

// Admin viewer's enriched response (cascade-merged + sources_consulted).
export interface PermissionListResponse {
  mode: string;  // advisory | enforce
  rules: Array<{
    tool_name: string;
    pattern: string | null;
    behavior: string;
    source: string;
    reason: string | null;
  }>;
  sources_consulted: string[];
}

// ==================== Hooks CRUD API (PR-E.3.1) =================

export const HOOK_EVENTS = [
  'PRE_TOOL_USE',
  'POST_TOOL_USE',
  'USER_PROMPT_SUBMIT',
  'STOP',
  'SESSION_START',
  'SESSION_END',
  'SUBAGENT_STOP',
  'PRE_COMPACT',
] as const;
export type HookEvent = typeof HOOK_EVENTS[number];

export interface HookEntryPayload {
  event: HookEvent;
  command: string[];
  timeout_ms?: number | null;
  tool_filter?: string[];
}

export interface HookEntryRow {
  event: string;
  idx: number;
  command: string[];
  timeout_ms?: number | null;
  tool_filter: string[];
}

export interface HookEntriesResponse {
  enabled: boolean;
  audit_log_path?: string | null;
  entries: HookEntryRow[];
  settings_path: string;
}

export interface HookListResponse {
  enabled: boolean;
  env_opt_in: boolean;
  config_path: string;
  entries: Array<{
    event: string;
    command: string[];
    timeout_ms?: number | null;
    tool_filter: string[];
  }>;
}

export interface HookFireRecord {
  record: Record<string, unknown>;
}

export interface HookFiresResponse {
  audit_path?: string | null;
  exists: boolean;
  fires: HookFireRecord[];
  truncated: boolean;
}

export const hookApi = {
  // Editable file content (user-scope settings.json only).
  listEditable: () => apiCall<HookEntriesResponse>('/api/hooks/entries'),

  append: (entry: HookEntryPayload) =>
    apiCall<HookEntriesResponse>('/api/hooks/entries', {
      method: 'POST',
      body: JSON.stringify(entry),
    }),

  replace: (event: string, idx: number, entry: HookEntryPayload) =>
    apiCall<HookEntriesResponse>(`/api/hooks/entries/${event}/${idx}`, {
      method: 'PUT',
      body: JSON.stringify(entry),
    }),

  remove: (event: string, idx: number) =>
    apiCall<HookEntriesResponse>(`/api/hooks/entries/${event}/${idx}`, {
      method: 'DELETE',
    }),

  setEnabled: (enabled: boolean) =>
    apiCall<HookEntriesResponse>('/api/hooks/enabled', {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),

  // Cascade-merged inspection (config_path + env_opt_in gate).
  inspect: () => apiCall<HookListResponse>('/api/hooks/list'),

  // Recent fire ring (PR-E.3.2 — JSONL tail).
  recentFires: (limit = 100) =>
    apiCall<HookFiresResponse>(`/api/admin/hook-fires?limit=${limit}`),
};

export const permissionApi = {
  // Editable file content (user-scope settings.json only).
  listEditable: () => apiCall<PermissionRulesResponse>('/api/permissions/rules'),

  append: (rule: PermissionRulePayload) =>
    apiCall<PermissionRulesResponse>('/api/permissions/rules', {
      method: 'POST',
      body: JSON.stringify(rule),
    }),

  replace: (idx: number, rule: PermissionRulePayload) =>
    apiCall<PermissionRulesResponse>(`/api/permissions/rules/${idx}`, {
      method: 'PUT',
      body: JSON.stringify(rule),
    }),

  remove: (idx: number) =>
    apiCall<PermissionRulesResponse>(`/api/permissions/rules/${idx}`, {
      method: 'DELETE',
    }),

  // Cascade-merged inspection (advisory|enforce + every source).
  inspect: () => apiCall<PermissionListResponse>('/api/permissions/list'),
};

// ==================== Slash Commands API (PR-A.6.2) =============

export interface SlashCommandSummary {
  name: string;
  description: string;
  category: string;
  aliases: string[];
}

export interface SlashExecuteResponse {
  matched: boolean;
  success: boolean;
  content: string | null;
  follow_up_prompt: string | null;
  metadata: Record<string, unknown>;
}

export const slashCommandApi = {
  list: () => apiCall<{ commands: SlashCommandSummary[] }>('/api/slash-commands'),

  execute: (input_text: string) =>
    apiCall<SlashExecuteResponse>('/api/slash-commands/execute', {
      method: 'POST',
      body: JSON.stringify({ input_text }),
    }),
};

// ==================== Cron API (PR-A.8.3) ======================

export interface CronJobRecord {
  name: string;
  cron_expr: string;
  target_kind: string;
  payload: Record<string, unknown>;
  description: string | null;
  status: string;
  created_at: string | null;
  last_fired_at: string | null;
  last_task_id: string | null;
}

export interface CronJobCreateRequest {
  name: string;
  cron_expr: string;
  target_kind: string;
  payload?: Record<string, unknown>;
  description?: string;
}

export const cronApi = {
  list: (onlyEnabled = false) =>
    apiCall<CronJobRecord[]>(`/api/cron/jobs?only_enabled=${onlyEnabled}`),

  get: (name: string) =>
    apiCall<CronJobRecord>(`/api/cron/jobs/${encodeURIComponent(name)}`),

  create: (req: CronJobCreateRequest) =>
    apiCall<CronJobRecord>('/api/cron/jobs', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  delete: (name: string) =>
    apiCall<{ deleted: string }>(`/api/cron/jobs/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  runNow: (name: string) =>
    apiCall<{ task_id: string; name: string }>(
      `/api/cron/jobs/${encodeURIComponent(name)}/run-now`,
      { method: 'POST' },
    ),
};

// ==================== Shared Folder API ====================

export interface SharedFileItem {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  modified_at: string | null;
}

export interface SharedFileListResponse {
  shared_path: string;
  files: SharedFileItem[];
  total: number;
}

export interface SharedFileContentResponse {
  file_path: string;
  content: string;
  size: number;
  encoding: string;
}

export interface SharedFolderInfoResponse {
  path: string;
  exists: boolean;
  total_files: number;
  total_size: number;
}

export const sharedFolderApi = {
  /** GET /api/shared-folder/info */
  getInfo: () => apiCall<SharedFolderInfoResponse>('/api/shared-folder/info'),

  /** GET /api/shared-folder/files */
  listFiles: (path = '') =>
    apiCall<SharedFileListResponse>(`/api/shared-folder/files${path ? `?path=${encodeURIComponent(path)}` : ''}`),

  /** GET /api/shared-folder/files/{path} */
  getFile: (filePath: string) =>
    apiCall<SharedFileContentResponse>(`/api/shared-folder/files/${encodeURIComponent(filePath)}`),

  /** POST /api/shared-folder/files */
  writeFile: (filePath: string, content: string, overwrite = true) =>
    apiCall<{ success: boolean; file_path: string; size: number }>('/api/shared-folder/files', {
      method: 'POST',
      body: JSON.stringify({ file_path: filePath, content, overwrite }),
    }),

  /** DELETE /api/shared-folder/files/{path} */
  deleteFile: (filePath: string) =>
    apiCall<{ success: boolean }>(`/api/shared-folder/files/${encodeURIComponent(filePath)}`, {
      method: 'DELETE',
    }),

  /** POST /api/shared-folder/upload */
  uploadFile: async (file: File, path = '', overwrite = true) => {
    const formData = new FormData();
    formData.append('file', file);
    const params = new URLSearchParams();
    if (path) params.set('path', path);
    params.set('overwrite', String(overwrite));
    const uploadToken = getToken();
    const uploadHeaders: Record<string, string> = {};
    if (uploadToken) uploadHeaders['Authorization'] = `Bearer ${uploadToken}`;
    const res = await fetch(`/api/shared-folder/upload?${params}`, {
      method: 'POST',
      headers: uploadHeaders,
      body: formData,
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(body || `HTTP ${res.status}`);
    }
    return res.json();
  },

  /** POST /api/shared-folder/directory */
  createDirectory: (path: string) =>
    apiCall<{ success: boolean; path: string }>('/api/shared-folder/directory', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  /** GET /api/shared-folder/download */
  download: async () => {
    const res = await fetch('/api/shared-folder/download');
    if (!res.ok) {
      const body = await res.text();
      throw new Error(body || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'shared-folder.zip';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};

// ==================== Command API ====================

import type { PromptListResponse, SessionLogsResponse } from '@/types';

export const commandApi = {
  /** GET /api/command/prompts — list prompt templates */
  getPrompts: () => apiCall<PromptListResponse>('/api/command/prompts'),

  /** GET /api/command/prompts/{name} — get prompt content */
  getPromptContent: (name: string) =>
    apiCall<{ name: string; content: string }>(`/api/command/prompts/${encodeURIComponent(name)}`),

  /** GET /api/command/logs/{id} — get session logs */
  getLogs: (id: string, limit = 200, level?: string, offset = 0) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (level) params.set('level', level);
    return apiCall<SessionLogsResponse>(`/api/command/logs/${id}?${params}`);
  },

  /** POST /api/command/batch — batch execute */
  executeBatch: (data: { session_ids: string[]; prompt: string; timeout?: number; parallel?: boolean }) =>
    apiCall<{ results: Array<{ session_id: string; success: boolean; output?: string; error?: string; duration_ms?: number }> }>(
      '/api/command/batch',
      { method: 'POST', body: JSON.stringify(data) },
    ),
};

// ==================== Health API ====================

import type { HealthStatus } from '@/types';

export const healthApi = {
  /** GET /health — server health check */
  check: () => apiCall<HealthStatus>('/health'),
};

// ==================== Config API ====================

import type { ConfigListResponse, ConfigSchema } from '@/types';

export const configApi = {
  /** GET /api/config — list all configs */
  list: () => apiCall<ConfigListResponse>('/api/config'),

  /** GET /api/config/{name} — get config detail */
  get: (name: string) =>
    apiCall<{ schema: ConfigSchema; values: Record<string, unknown> }>(`/api/config/${encodeURIComponent(name)}`),

  /** PUT /api/config/{name} — update config */
  update: (name: string, values: Record<string, unknown>) =>
    apiCall<{ success: boolean }>(`/api/config/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify({ values }),
    }),

  /** DELETE /api/config/{name} — reset config to defaults */
  reset: (name: string) =>
    apiCall<{ success: boolean }>(`/api/config/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  /** POST /api/config/export — export all configs */
  exportAll: () =>
    apiCall<{ success: boolean; configs: Record<string, unknown> }>('/api/config/export', { method: 'POST' }),

  /** POST /api/config/import — import configs */
  importAll: (data: Record<string, unknown>) =>
    apiCall<{ success: boolean; message?: string }>('/api/config/import', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};

// ==================== Chat API ====================

export const chatApi = {
  /** GET /api/chat/rooms — list all chat rooms */
  listRooms: () =>
    apiCall<ChatRoomListResponse>('/api/chat/rooms'),

  /** POST /api/chat/rooms — create a new chat room */
  createRoom: (data: CreateChatRoomRequest) =>
    apiCall<ChatRoom>('/api/chat/rooms', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** GET /api/chat/rooms/:id — get a single room */
  getRoom: (roomId: string) =>
    apiCall<ChatRoom>(`/api/chat/rooms/${roomId}`),

  /** PATCH /api/chat/rooms/:id — update room name/sessions */
  updateRoom: (roomId: string, data: UpdateChatRoomRequest) =>
    apiCall<ChatRoom>(`/api/chat/rooms/${roomId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  /** DELETE /api/chat/rooms/:id — delete room & history */
  deleteRoom: (roomId: string) =>
    apiCall<{ success: boolean; room_id: string }>(`/api/chat/rooms/${roomId}`, {
      method: 'DELETE',
    }),

  /** GET /api/chat/rooms/:id/messages — get room message history (supports pagination) */
  getRoomMessages: (roomId: string, opts?: { limit?: number; before?: string }) => {
    const params = new URLSearchParams();
    if (opts?.limit) params.set('limit', String(opts.limit));
    if (opts?.before) params.set('before', opts.before);
    const qs = params.toString();
    return apiCall<ChatRoomMessageListResponse>(
      `/api/chat/rooms/${roomId}/messages${qs ? `?${qs}` : ''}`,
    );
  },

  /**
   * POST /api/chat/rooms/:id/broadcast — fire-and-forget broadcast.
   * Returns the saved user message and broadcast info immediately.
   * Agent processing continues in the background.
   */
  broadcastToRoom: (roomId: string, data: ChatRoomBroadcastRequest) =>
    apiCall<ChatRoomBroadcastResponse>(`/api/chat/rooms/${roomId}/broadcast`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** POST /api/chat/rooms/:id/broadcast/cancel — cancel active broadcast */
  cancelBroadcast: (roomId: string) =>
    apiCall<{ status: string; broadcast_id: string; cancelled_agents: number }>(
      `/api/chat/rooms/${roomId}/broadcast/cancel`,
      { method: 'POST' },
    ),

  /**
   * POST /api/uploads — multipart upload of one or more files.
   *
   * Returns ``ChatAttachment`` references that the caller embeds in a
   * subsequent ``broadcastToRoom`` request via the ``attachments``
   * field. Files are content-addressed (sha256) on the server, so
   * uploading the same image twice is idempotent.
   */
  uploadAttachments: async (files: File[]): Promise<ChatAttachment[]> => {
    if (!files || files.length === 0) return [];
    const form = new FormData();
    for (const f of files) form.append('files', f, f.name);

    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    // NB: do NOT set Content-Type — the browser fills in the multipart
    // boundary automatically.

    const res = await fetch('/api/uploads', {
      method: 'POST',
      headers,
      body: form,
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(body || `Upload failed: HTTP ${res.status}`);
    }
    const json = (await res.json()) as { files: ChatAttachment[] };
    return json.files || [];
  },

  /**
   * Subscribe to chat room events via WebSocket.
   *
   * Opens a WebSocket connection to /ws/chat/rooms/{roomId} for real-time
   * push-based event streaming with automatic reconnection.
   */
  subscribeToRoom: (
    roomId: string,
    afterId: string | null,
    onEvent: (eventType: string, eventData: Record<string, unknown>) => void,
    getLatestMsgId?: () => string | null,
  ): { close: () => void; reconnect: () => void } => {
    const wsUrl = getChatWsUrl(roomId);
    const _tag = `[ChatWS:${roomId.slice(0, 8)}]`;
    let ws: WebSocket | null = null;
    let closed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    const maxAttempts = 30;

    console.info(`${_tag} subscribeToRoom wsUrl=${wsUrl}`);

    const connect = () => {
      if (closed) return;

      const delay = attempts === 0 ? 0 : Math.min(500 * Math.pow(2, attempts - 1), 10000);
      if (delay > 0) {
        console.info(`${_tag} reconnecting in ${delay}ms (attempt=${attempts}/${maxAttempts})`);
        reconnectTimer = setTimeout(_doConnect, delay);
      } else {
        _doConnect();
      }
    };

    const _doConnect = () => {
      if (closed) return;
      reconnectTimer = null;

      console.info(`${_tag} connecting to ${wsUrl} (attempt=${attempts})...`);

      try {
        ws = new WebSocket(wsUrl);
      } catch (err) {
        console.error(`${_tag} WebSocket constructor failed for ${wsUrl}:`, err);
        return;
      }

      const connectTimeout = setTimeout(() => {
        if (ws && ws.readyState === WebSocket.CONNECTING) {
          console.warn(`${_tag} connection timeout (5s), url=${wsUrl}`);
          ws.close();
        }
      }, 5000);

      ws.onopen = () => {
        clearTimeout(connectTimeout);
        const wasReconnecting = attempts > 0;
        attempts = 0;
        const currentAfter = getLatestMsgId?.() ?? afterId;
        console.info(`${_tag} connected, subscribe after=${currentAfter}`);
        ws!.send(JSON.stringify({ type: 'subscribe', after: currentAfter }));
        // 연결 상태를 이벤트로 전달
        onEvent('_ws_connected', { reconnected: wasReconnecting });
      };

      ws.onmessage = (ev) => {
        try {
          const event = JSON.parse(ev.data);
          if (event.type !== 'heartbeat') {
            console.debug(`${_tag} event: ${event.type}`, event.data);
          }
          onEvent(event.type, event.data);
        } catch (err) {
          console.warn(`${_tag} parse error:`, err);
        }
      };

      ws.onerror = (err) => {
        clearTimeout(connectTimeout);
        console.error(`${_tag} WebSocket error, url=${wsUrl}`, err);
        ws = null;
      };

      ws.onclose = (ev) => {
        clearTimeout(connectTimeout);
        if (!closed) {
          console.warn(`${_tag} closed (code=${ev.code}, reason=${ev.reason || 'none'}, url=${wsUrl})`);
        }
        ws = null;
        if (closed) return;

        if (attempts < maxAttempts) {
          attempts++;
          // 재연결 중임을 이벤트로 알림
          onEvent('_ws_reconnecting', { attempt: attempts, maxAttempts });
          connect();
        } else {
          console.error(`${_tag} max reconnect attempts (${maxAttempts}) reached, url=${wsUrl}`);
          // 최대 재연결 실패 시 이벤트로 알림 — UI에서 수동 재연결 버튼 표시 가능
          onEvent('_ws_failed', { attempts: maxAttempts, url: wsUrl });
        }
      };
    };

    connect();

    return {
      close: () => {
        closed = true;
        if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
        if (ws) { ws.close(); ws = null; }
      },
      /** 수동 재연결: 최대 시도 횟수 리셋 후 재연결 시작 */
      reconnect: () => {
        if (closed) return;
        // 기존 연결 정리
        if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
        if (ws) { ws.close(); ws = null; }
        // 카운터 리셋 후 재연결
        attempts = 0;
        connect();
      },
    };
  },
};

// ==================== Docs API ====================

export interface DocEntry {
  slug: string;
  filename: string;
  title: string;
}

export interface DocContent extends DocEntry {
  content: string;
}

export const docsApi = {
  /** GET /api/docs — list all documentation files */
  list: (lang: string = 'en') =>
    apiCall<{ docs: DocEntry[] }>(`/api/docs?lang=${encodeURIComponent(lang)}`),

  /** GET /api/docs/{slug} — get single document content */
  get: (slug: string, lang: string = 'en') =>
    apiCall<DocContent>(`/api/docs/${encodeURIComponent(slug)}?lang=${encodeURIComponent(lang)}`),
};

// ==================== Memory API ====================

export const memoryApi = {
  /** GET /api/agents/{sid}/memory — get index + stats */
  getIndex: (sessionId: string) =>
    apiCall<import('@/types').MemoryIndexResponse>(`/api/agents/${sessionId}/memory`),

  /** GET /api/agents/{sid}/memory/stats */
  getStats: (sessionId: string) =>
    apiCall<import('@/types').MemoryStats>(`/api/agents/${sessionId}/memory/stats`),

  /** GET /api/agents/{sid}/memory/tags */
  getTags: (sessionId: string) =>
    apiCall<{ tags: Record<string, number> }>(`/api/agents/${sessionId}/memory/tags`),

  /** GET /api/agents/{sid}/memory/graph */
  getGraph: (sessionId: string) =>
    apiCall<import('@/types').MemoryGraphResponse>(`/api/agents/${sessionId}/memory/graph`),

  /** GET /api/agents/{sid}/memory/files — list files */
  listFiles: (sessionId: string, params?: { category?: string; tag?: string }) => {
    const qs = new URLSearchParams();
    if (params?.category) qs.set('category', params.category);
    if (params?.tag) qs.set('tag', params.tag);
    const q = qs.toString();
    return apiCall<import('@/types').MemoryFileListResponse>(
      `/api/agents/${sessionId}/memory/files${q ? `?${q}` : ''}`
    );
  },

  /** GET /api/agents/{sid}/memory/files/{filename} — read a file */
  readFile: (sessionId: string, filename: string) =>
    apiCall<import('@/types').MemoryFileDetail>(`/api/agents/${sessionId}/memory/files/${filename}`),

  /** POST /api/agents/{sid}/memory/files — create a note */
  createFile: (sessionId: string, data: {
    title: string;
    content: string;
    category?: string;
    tags?: string[];
    importance?: string;
    source?: string;
    links_to?: string[];
  }) =>
    apiCall<{ filename: string; message: string }>(`/api/agents/${sessionId}/memory/files`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** PUT /api/agents/{sid}/memory/files/{filename} — update a note */
  updateFile: (sessionId: string, filename: string, data: {
    content?: string;
    tags?: string[];
    importance?: string;
    links_to?: string[];
  }) =>
    apiCall<{ filename: string; message: string }>(
      `/api/agents/${sessionId}/memory/files/${filename}`,
      { method: 'PUT', body: JSON.stringify(data) },
    ),

  /** DELETE /api/agents/{sid}/memory/files/{filename} */
  deleteFile: (sessionId: string, filename: string) =>
    apiCall<{ message: string }>(
      `/api/agents/${sessionId}/memory/files/${filename}`,
      { method: 'DELETE' },
    ),

  /** GET /api/agents/{sid}/memory/search?q=... */
  search: (sessionId: string, query: string, params?: { max_results?: number; category?: string; tag?: string }) => {
    const qs = new URLSearchParams({ q: query });
    if (params?.max_results) qs.set('max_results', String(params.max_results));
    if (params?.category) qs.set('category', params.category);
    if (params?.tag) qs.set('tag', params.tag);
    return apiCall<import('@/types').MemorySearchResponse>(
      `/api/agents/${sessionId}/memory/search?${qs.toString()}`
    );
  },

  /** POST /api/agents/{sid}/memory/links — create link */
  createLink: (sessionId: string, sourceFilename: string, targetFilename: string) =>
    apiCall<{ message: string }>(`/api/agents/${sessionId}/memory/links`, {
      method: 'POST',
      body: JSON.stringify({ source_filename: sourceFilename, target_filename: targetFilename }),
    }),

  /** POST /api/agents/{sid}/memory/reindex */
  reindex: (sessionId: string) =>
    apiCall<{ message: string; total_files: number }>(`/api/agents/${sessionId}/memory/reindex`, {
      method: 'POST',
    }),

  /** POST /api/agents/{sid}/memory/migrate */
  migrate: (sessionId: string) =>
    apiCall<{ message: string; summary: string }>(`/api/agents/${sessionId}/memory/migrate`, {
      method: 'POST',
    }),

  /** POST /api/agents/{sid}/memory/promote — promote to global */
  promote: (sessionId: string, filename: string) =>
    apiCall<{ message: string; global_filename: string }>(`/api/agents/${sessionId}/memory/promote`, {
      method: 'POST',
      body: JSON.stringify({ filename }),
    }),
};

// ==================== Global Memory API ====================

export const globalMemoryApi = {
  /** GET /api/memory/global */
  getIndex: () =>
    apiCall<import('@/types').MemoryIndexResponse>('/api/memory/global'),

  /** GET /api/memory/global/files */
  listFiles: (params?: { category?: string; tag?: string }) => {
    const qs = new URLSearchParams();
    if (params?.category) qs.set('category', params.category);
    if (params?.tag) qs.set('tag', params.tag);
    const q = qs.toString();
    return apiCall<import('@/types').MemoryFileListResponse>(
      `/api/memory/global/files${q ? `?${q}` : ''}`
    );
  },

  /** GET /api/memory/global/files/{filename} */
  readFile: (filename: string) =>
    apiCall<import('@/types').MemoryFileDetail>(`/api/memory/global/files/${filename}`),

  /** POST /api/memory/global/files */
  createFile: (data: {
    title: string;
    content: string;
    category?: string;
    tags?: string[];
    importance?: string;
  }) =>
    apiCall<{ filename: string; message: string }>('/api/memory/global/files', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** PUT /api/memory/global/files/{filename} */
  updateFile: (filename: string, data: {
    content?: string;
    tags?: string[];
    importance?: string;
  }) =>
    apiCall<{ filename: string; message: string }>(
      `/api/memory/global/files/${filename}`,
      { method: 'PUT', body: JSON.stringify(data) },
    ),

  /** DELETE /api/memory/global/files/{filename} */
  deleteFile: (filename: string) =>
    apiCall<{ message: string }>(
      `/api/memory/global/files/${filename}`,
      { method: 'DELETE' },
    ),

  /** GET /api/memory/global/search?q=... */
  search: (query: string, maxResults?: number) => {
    const qs = new URLSearchParams({ q: query });
    if (maxResults) qs.set('max_results', String(maxResults));
    return apiCall<import('@/types').MemorySearchResponse>(
      `/api/memory/global/search?${qs.toString()}`
    );
  },
};

// ==================== VTuber API ====================

export const vtuberApi = {
  /** GET /api/vtuber/models — list all registered Live2D models */
  listModels: () =>
    apiCall<{ models: Live2dModelInfo[] }>('/api/vtuber/models'),

  /** GET /api/vtuber/models/{name} — get single model details */
  getModel: (name: string) =>
    apiCall<Live2dModelInfo>(`/api/vtuber/models/${encodeURIComponent(name)}`),

  /** PUT /api/vtuber/agents/{sessionId}/model — assign model to session */
  assignModel: (sessionId: string, modelName: string) =>
    apiCall<{ status: string; session_id: string; model_name: string }>(
      `/api/vtuber/agents/${sessionId}/model`,
      { method: 'PUT', body: JSON.stringify({ model_name: modelName }) },
    ),

  /** GET /api/vtuber/agents/{sessionId}/model — get assigned model */
  getAgentModel: (sessionId: string) =>
    apiCall<{ session_id: string; model: Live2dModelInfo | null }>(
      `/api/vtuber/agents/${sessionId}/model`,
    ),

  /** DELETE /api/vtuber/agents/{sessionId}/model — unassign model */
  unassignModel: (sessionId: string) =>
    apiCall<{ status: string; session_id: string }>(
      `/api/vtuber/agents/${sessionId}/model`,
      { method: 'DELETE' },
    ),

  /** GET /api/vtuber/assignments — list all agent-model assignments */
  listAssignments: () =>
    apiCall<{ assignments: Record<string, string> }>('/api/vtuber/assignments'),

  /** GET /api/vtuber/agents/{sessionId}/state — current avatar state */
  getAvatarState: (sessionId: string) =>
    apiCall<AvatarState>(`/api/vtuber/agents/${sessionId}/state`),

  /** POST /api/vtuber/agents/{sessionId}/interact — touch/click interaction */
  interact: (sessionId: string, hitArea: string, x?: number, y?: number) =>
    apiCall<{ status: string; hit_area: string }>(
      `/api/vtuber/agents/${sessionId}/interact`,
      { method: 'POST', body: JSON.stringify({ hit_area: hitArea, x, y }) },
    ),

  /** POST /api/vtuber/agents/{sessionId}/emotion — manual emotion override */
  setEmotion: (sessionId: string, emotion: string, intensity = 1.0, transitionMs = 300) =>
    apiCall<{ status: string; emotion: string; expression_index: number }>(
      `/api/vtuber/agents/${sessionId}/emotion`,
      { method: 'POST', body: JSON.stringify({ emotion, intensity, transition_ms: transitionMs }) },
    ),

  /**
   * Subscribe to avatar state changes via WebSocket.
   */
  subscribeToAvatarState: (
    sessionId: string,
    onState: (state: AvatarState) => void,
  ): { close: () => void } => {
    const wsBase = _getWsBase();
    const wsUrl = `${wsBase}/ws/vtuber/agents/${sessionId}/state`;
    const _tag = `[AvatarWS:${sessionId.slice(0, 8)}]`;
    let ws: WebSocket | null = null;
    let closed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    const maxAttempts = 15;

    const connect = () => {
      if (closed) return;
      const delay = attempts === 0 ? 0 : Math.min(500 * Math.pow(2, attempts - 1), 10000);
      if (delay > 0) {
        reconnectTimer = setTimeout(_doConnect, delay);
      } else {
        _doConnect();
      }
    };

    const _doConnect = () => {
      if (closed) return;
      reconnectTimer = null;
      try {
        ws = new WebSocket(wsUrl);
      } catch {
        console.error(`${_tag} WebSocket constructor failed`);
        return;
      }

      ws.onopen = () => {
        attempts = 0;
        console.debug(`${_tag} connected, subscribing`);
        ws!.send(JSON.stringify({ type: 'subscribe' }));
      };

      ws.onmessage = (ev) => {
        try {
          const event = JSON.parse(ev.data);
          if (event.type === 'avatar_state') {
            onState(event.data as AvatarState);
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onerror = (err) => {
        console.error(`${_tag} WebSocket error, url=${wsUrl}`, err);
        ws = null;
      };

      ws.onclose = (ev) => {
        if (!closed) {
          console.warn(`${_tag} closed (code=${ev.code}, reason=${ev.reason || 'none'})`);
        }
        ws = null;
        if (!closed && attempts < maxAttempts) {
          attempts++;
          connect();
        } else if (!closed) {
          console.error(`${_tag} max reconnect attempts (${maxAttempts}) reached`);
          // 30초 후 카운터 리셋하여 다시 시도 (영구 연결 끊김 방지)
          reconnectTimer = setTimeout(() => {
            if (!closed) {
              console.info(`${_tag} resetting reconnect counter, retrying`);
              attempts = 0;
              connect();
            }
          }, 30000);
        }
      };
    };

    connect();

    return {
      close: () => {
        closed = true;
        if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
        if (ws) { ws.close(); ws = null; }
      },
    };
  },
};

// ==================== User Opsidian API ====================

export const userOpsidianApi = {
  /** GET /api/opsidian — index + stats */
  getIndex: () =>
    apiCall<import('@/types').MemoryIndexResponse & { username: string }>('/api/opsidian'),

  /** GET /api/opsidian/stats */
  getStats: () =>
    apiCall<{ total_files: number; total_chars: number; categories: Record<string, number>; total_tags: number }>('/api/opsidian/stats'),

  /** GET /api/opsidian/graph */
  getGraph: () =>
    apiCall<import('@/types').MemoryGraphResponse>('/api/opsidian/graph'),

  /** GET /api/opsidian/tags */
  getTags: () =>
    apiCall<{ tags: Record<string, string[]> }>('/api/opsidian/tags'),

  /** GET /api/opsidian/files */
  listFiles: (params?: { category?: string; tag?: string }) => {
    const qs = new URLSearchParams();
    if (params?.category) qs.set('category', params.category);
    if (params?.tag) qs.set('tag', params.tag);
    const q = qs.toString();
    return apiCall<{ files: Array<Record<string, unknown>>; total: number }>(
      `/api/opsidian/files${q ? `?${q}` : ''}`
    );
  },

  /** GET /api/opsidian/files/{filename} */
  readFile: (filename: string) =>
    apiCall<import('@/types').MemoryFileDetail>(`/api/opsidian/files/${filename}`),

  /** POST /api/opsidian/files */
  createFile: (data: {
    title: string;
    content: string;
    category?: string;
    tags?: string[];
    importance?: string;
    source?: string;
    links_to?: string[];
  }) =>
    apiCall<{ filename: string; message: string }>('/api/opsidian/files', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** PUT /api/opsidian/files/{filename} */
  updateFile: (filename: string, data: {
    content?: string;
    tags?: string[];
    importance?: string;
    category?: string;
  }) =>
    apiCall<{ filename: string; message: string }>(
      `/api/opsidian/files/${filename}`,
      { method: 'PUT', body: JSON.stringify(data) },
    ),

  /** DELETE /api/opsidian/files/{filename} */
  deleteFile: (filename: string) =>
    apiCall<{ message: string }>(
      `/api/opsidian/files/${filename}`,
      { method: 'DELETE' },
    ),

  /** GET /api/opsidian/search?q=... */
  search: (query: string, maxResults?: number) => {
    const qs = new URLSearchParams({ q: query });
    if (maxResults) qs.set('max_results', String(maxResults));
    return apiCall<{ query: string; results: Array<Record<string, unknown>>; total: number }>(
      `/api/opsidian/search?${qs.toString()}`
    );
  },

  /** POST /api/opsidian/links */
  createLink: (sourceFilename: string, targetFilename: string) =>
    apiCall<{ message: string }>('/api/opsidian/links', {
      method: 'POST',
      body: JSON.stringify({ source_filename: sourceFilename, target_filename: targetFilename }),
    }),

  /** POST /api/opsidian/reindex */
  reindex: () =>
    apiCall<{ message: string; total_files: number }>('/api/opsidian/reindex', {
      method: 'POST',
    }),
};

// ==================== Curated Knowledge API ====================

export const curatedKnowledgeApi = {
  /** GET /api/curated — index + stats */
  getIndex: () =>
    apiCall<import('@/types').MemoryIndexResponse & { username: string }>('/api/curated'),

  /** GET /api/curated/stats */
  getStats: () =>
    apiCall<{ total_files: number; total_chars: number; categories: Record<string, number>; total_tags: number; vector_enabled: boolean }>('/api/curated/stats'),

  /** GET /api/curated/graph */
  getGraph: () =>
    apiCall<import('@/types').MemoryGraphResponse>('/api/curated/graph'),

  /** GET /api/curated/tags */
  getTags: () =>
    apiCall<{ tags: Record<string, string[]> }>('/api/curated/tags'),

  /** GET /api/curated/files */
  listFiles: (params?: { category?: string; tag?: string }) => {
    const qs = new URLSearchParams();
    if (params?.category) qs.set('category', params.category);
    if (params?.tag) qs.set('tag', params.tag);
    const q = qs.toString();
    return apiCall<{ files: Array<Record<string, unknown>>; total: number }>(
      `/api/curated/files${q ? `?${q}` : ''}`
    );
  },

  /** GET /api/curated/files/{filename} */
  readFile: (filename: string) =>
    apiCall<import('@/types').MemoryFileDetail>(`/api/curated/files/${filename}`),

  /** POST /api/curated/files */
  createFile: (data: {
    title: string;
    content: string;
    category?: string;
    tags?: string[];
    importance?: string;
    source?: string;
    links_to?: string[];
  }) =>
    apiCall<{ filename: string; message: string }>('/api/curated/files', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** PUT /api/curated/files/{filename} */
  updateFile: (filename: string, data: {
    content?: string;
    tags?: string[];
    importance?: string;
    category?: string;
  }) =>
    apiCall<{ filename: string; message: string }>(
      `/api/curated/files/${filename}`,
      { method: 'PUT', body: JSON.stringify(data) },
    ),

  /** DELETE /api/curated/files/{filename} */
  deleteFile: (filename: string) =>
    apiCall<{ message: string }>(
      `/api/curated/files/${filename}`,
      { method: 'DELETE' },
    ),

  /** GET /api/curated/search?q=... */
  search: (query: string, maxResults?: number) => {
    const qs = new URLSearchParams({ q: query });
    if (maxResults) qs.set('max_results', String(maxResults));
    return apiCall<{ query: string; results: Array<Record<string, unknown>>; total: number }>(
      `/api/curated/search?${qs.toString()}`
    );
  },

  /** POST /api/curated/links */
  createLink: (sourceFilename: string, targetFilename: string) =>
    apiCall<{ message: string }>('/api/curated/links', {
      method: 'POST',
      body: JSON.stringify({ source_filename: sourceFilename, target_filename: targetFilename }),
    }),

  /** POST /api/curated/reindex */
  reindex: () =>
    apiCall<{ message: string; total_files: number }>('/api/curated/reindex', {
      method: 'POST',
    }),

  /** POST /api/curated/curate — run 5-stage curation pipeline */
  curateNote: (data: {
    source_filename: string;
    method?: string;
    extra_tags?: string[];
    use_llm?: boolean;
  }) =>
    apiCall<{
      success: boolean;
      curated_filename?: string;
      method_used?: string;
      quality_score?: number;
      reason?: string;
    }>('/api/curated/curate', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** POST /api/curated/curate/batch — batch curation */
  curateBatch: (data: { filenames: string[]; use_llm?: boolean }) =>
    apiCall<{
      total: number;
      success_count: number;
      results: Array<{
        success: boolean;
        curated_filename?: string;
        method_used?: string;
        quality_score?: number;
        reason?: string;
      }>;
    }>('/api/curated/curate/batch', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** POST /api/curated/curate/all — curate all uncurated user notes */
  curateAll: (use_llm?: boolean) =>
    apiCall<{
      total: number;
      success_count: number;
      results: Array<{
        success: boolean;
        curated_filename?: string;
        quality_score?: number;
        reason?: string;
      }>;
      message?: string;
    }>('/api/curated/curate/all', {
      method: 'POST',
      body: JSON.stringify({ use_llm: use_llm ?? true }),
    }),
};

// ==================== TTS API ====================

export interface VoiceInfo {
  id: string;
  name: string;
  language: string;
  gender: string;
  engine: string;
  preview_text?: string;
}

export interface VoiceProfile {
  name: string;
  display_name: string;
  language?: string;
  is_template?: boolean;
  prompt_text?: string;
  prompt_lang?: string;
  emotion_refs?: Record<string, { file: string; prompt_text?: string; prompt_lang?: string }>;
  has_refs?: Record<string, boolean>;
  active?: boolean;
  gpt_sovits_settings?: Record<string, unknown>;
}

export const ttsApi = {
  /** POST /api/tts/agents/{sessionId}/speak — TTS 오디오 스트리밍 요청 */
  speak: async (
    sessionId: string,
    text: string,
    emotion: string = 'neutral',
    language?: string,
    engine?: string,
    signal?: AbortSignal,
  ): Promise<Response> => {
    const backendUrl = getBackendUrl();
    return fetch(`${backendUrl}/api/tts/agents/${sessionId}/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, emotion, language, engine }),
      signal,
    });
  },

  /**
   * POST /api/tts/agents/{sessionId}/speak/stream — 문장 단위 NDJSON 스트림.
   *
   * 각 줄이 한 문장의 완성된 wav 오디오(base64). 첫 문장이 도착하는
   * 즉시 재생을 시작하면 전체 합성 종료까지 기다리지 않고도 화자가
   * 말하기 시작하므로 체감 latency가 크게 줄어든다.
   *
   * 응답 본문 파싱은 호출자(ttsClient.consumeSentenceStream)에서 처리.
   * 이 메서드는 단순히 fetch Response를 반환한다.
   */
  speakStream: async (
    sessionId: string,
    text: string,
    emotion: string = 'neutral',
    language?: string,
    engine?: string,
    signal?: AbortSignal,
  ): Promise<Response> => {
    const backendUrl = getBackendUrl();
    return fetch(`${backendUrl}/api/tts/agents/${sessionId}/speak/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, emotion, language, engine }),
      signal,
    });
  },

  /** GET /api/tts/voices — 보이스 목록 */
  voices: (language?: string) =>
    apiCall<Record<string, VoiceInfo[]>>(
      `/api/tts/voices${language ? `?language=${language}` : ''}`,
    ),

  /** GET /api/tts/voices/{engine}/{voiceId}/preview — 보이스 미리듣기 */
  preview: async (engine: string, voiceId: string, text?: string): Promise<Response> => {
    const backendUrl = getBackendUrl();
    const params = text ? `?text=${encodeURIComponent(text)}` : '';
    return fetch(
      `${backendUrl}/api/tts/voices/${encodeURIComponent(engine)}/${encodeURIComponent(voiceId)}/preview${params}`,
    );
  },

  /** GET /api/tts/status — TTS 서비스 상태 */
  status: () =>
    apiCall<Record<string, { available: boolean; engine: string }>>('/api/tts/status'),

  /** GET /api/tts/engines — 엔진 목록 */
  engines: () =>
    apiCall<{ engines: string[]; default: string }>('/api/tts/engines'),

  // ── Voice Profile Management ──

  /** GET /api/tts/profiles — 보이스 프로필 목록 */
  listProfiles: () =>
    apiCall<{ profiles: VoiceProfile[] }>('/api/tts/profiles'),

  /** GET /api/tts/profiles/{name} — 프로필 상세 */
  getProfile: (name: string) =>
    apiCall<VoiceProfile>(`/api/tts/profiles/${encodeURIComponent(name)}`),

  /** POST /api/tts/profiles — 새 프로필 생성 */
  createProfile: (body: { name: string; display_name: string; language?: string; prompt_text?: string; prompt_lang?: string }) =>
    apiCall<VoiceProfile>('/api/tts/profiles', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** PUT /api/tts/profiles/{name} — 프로필 수정 */
  updateProfile: (name: string, body: { display_name?: string; language?: string; prompt_text?: string; prompt_lang?: string }) =>
    apiCall<VoiceProfile>(`/api/tts/profiles/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  /** POST /api/tts/profiles/{name}/ref — 레퍼런스 오디오 업로드 */
  uploadRef: async (name: string, emotion: string, file: File, text?: string, lang?: string): Promise<{ success: boolean }> => {
    const form = new FormData();
    form.append('file', file);
    form.append('emotion', emotion);
    if (text) form.append('text', text);
    if (lang) form.append('lang', lang);
    const refToken = getToken();
    const refHeaders: Record<string, string> = {};
    if (refToken) refHeaders['Authorization'] = `Bearer ${refToken}`;
    const res = await fetch(`/api/tts/profiles/${encodeURIComponent(name)}/ref`, {
      method: 'POST',
      headers: refHeaders,
      body: form,
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(body || `HTTP ${res.status}`);
    }
    return res.json();
  },

  /** DELETE /api/tts/profiles/{name}/ref/{emotion} — 레퍼런스 오디오 삭제 */
  deleteRef: (name: string, emotion: string) =>
    apiCall<{ success: boolean }>(`/api/tts/profiles/${encodeURIComponent(name)}/ref/${encodeURIComponent(emotion)}`, {
      method: 'DELETE',
    }),

  /** POST /api/tts/profiles/{name}/activate — 프로필 활성화 */
  activateProfile: (name: string) =>
    apiCall<{ success: boolean }>(`/api/tts/profiles/${encodeURIComponent(name)}/activate`, {
      method: 'POST',
    }),

  /** GET /api/tts/profiles/{name}/ref/{emotion}/audio — 레퍼런스 오디오 URL */
  getRefAudioUrl: (name: string, emotion: string): string =>
    `/api/tts/profiles/${encodeURIComponent(name)}/ref/${encodeURIComponent(emotion)}/audio`,

  /** PUT /api/tts/profiles/{name}/ref/{emotion} — 개별 emotion prompt 수정 */
  updateEmotionRef: (name: string, emotion: string, body: { prompt_text?: string; prompt_lang?: string }) =>
    apiCall<{ success: boolean }>(`/api/tts/profiles/${encodeURIComponent(name)}/ref/${encodeURIComponent(emotion)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  // ── Per-Session Voice Profile ──

  /** GET /api/tts/agents/{sessionId}/profile — 세션 보이스 프로필 조회 */
  getSessionProfile: (sessionId: string) =>
    apiCall<{ session_id: string; tts_voice_profile: string | null }>(`/api/tts/agents/${sessionId}/profile`),

  /** PUT /api/tts/agents/{sessionId}/profile — 세션에 보이스 프로필 할당 */
  assignSessionProfile: (sessionId: string, profileName: string) =>
    apiCall<{ success: boolean; session_id: string; tts_voice_profile: string }>(`/api/tts/agents/${sessionId}/profile`, {
      method: 'PUT',
      body: JSON.stringify({ profile_name: profileName }),
    }),

  /** DELETE /api/tts/agents/{sessionId}/profile — 세션 보이스 프로필 해제 */
  unassignSessionProfile: (sessionId: string) =>
    apiCall<{ success: boolean; session_id: string }>(`/api/tts/agents/${sessionId}/profile`, {
      method: 'DELETE',
    }),
};
