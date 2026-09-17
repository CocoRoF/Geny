/**
 * API Communication Layer
 * Mirrors all legacy frontend-legacy/static/components/api.js endpoints
 */

import { getToken, removeToken } from '@/lib/authApi';

// ==================== Base Fetch Wrapper ====================

async function apiCall<T = unknown>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const authHeaders: Record<string, string> = {};
  if (token) authHeaders['Authorization'] = `Bearer ${token}`;

  const res = await fetch(endpoint, {
    headers: { 'Content-Type': 'application/json', ...authHeaders, ...options.headers },
    ...options,
  });
  if (res.status === 401) {
    // Expired / invalid token → clear it + signal re-login (same path as the
    // 4401 WS close), so the connector opens its login window instead of
    // silently rendering empty data.
    handleAuthFailure();
  }
  if (!res.ok) {
    const body = await res.text();
    let message: string;
    try {
      const json = JSON.parse(body);
      const raw = json.detail || json.message || json.error;
      message = typeof raw === 'string' ? raw : raw ? JSON.stringify(raw) : `HTTP ${res.status}`;
    } catch {
      // Non-JSON error body. A gateway error page (Cloudflare/nginx 502
      // during a backend restart) is a full HTML document — dumping it
      // verbatim into error UI is noise, not information.
      message =
        body.trimStart().startsWith('<') || body.length > 500
          ? `서버가 응답하지 않습니다 (HTTP ${res.status}) — 잠시 후 다시 시도해 주세요.`
          : body || `HTTP ${res.status}`;
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

/**
 * Merge an Authorization: Bearer header into a fetch headers object when a
 * token exists. Used by the raw-`fetch` helpers (TTS speak/chunks, voice
 * studio synth) that bypass `apiCall` because they need the streaming/blob
 * Response directly. Same-origin prod also carries the cookie, but the Bearer
 * header works cross-origin (dev :8000) too, so it is the robust path.
 */
export function withAuthHeaders(
  base: Record<string, string> = {},
): Record<string, string> {
  const token = getToken();
  if (token) return { ...base, Authorization: `Bearer ${token}` };
  return { ...base };
}

// ==================== STT (on-demand transcribe) ====================
export interface TranscribeResult {
  text: string;
  language?: string;
  source?: string;
}
export const sttApi = {
  /** POST /api/stt/transcribe — transcribe an audio blob (push-to-talk). */
  transcribe: async (blob: Blob, language?: string): Promise<TranscribeResult> => {
    const fd = new FormData();
    fd.append('file', blob, 'utterance.webm');
    if (language) fd.append('language', language);
    const res = await fetch(`${getBackendUrl()}/api/stt/transcribe`, {
      method: 'POST',
      headers: withAuthHeaders(), // no Content-Type → multipart boundary auto
      body: fd,
    });
    if (!res.ok) throw new Error(`stt/transcribe HTTP ${res.status}`);
    return res.json() as Promise<TranscribeResult>;
  },
};

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

// ==================== Authenticated WebSocket ====================
// Browsers cannot set arbitrary headers on `new WebSocket(...)`, but they CAN
// pass subprotocols. We smuggle the JWT through as the second subprotocol after
// a 'geny-auth' marker: the server validates it during the handshake and echoes
// 'geny-auth' back via accept(subprotocol='geny-auth'). When no token is present
// (dev / no-auth mode) we fall back to an unauthenticated connect, which the
// server still accepts when auth is not configured.
const WS_AUTH_SUBPROTOCOL = 'geny-auth';

/** Custom close code the server uses to signal "unauthorized". */
export const WS_UNAUTHORIZED_CODE = 4401;

function makeAuthedWs(url: string): WebSocket {
  const token = getToken();
  if (token) {
    return new WebSocket(url, [WS_AUTH_SUBPROTOCOL, token]);
  }
  return new WebSocket(url);
}

/** Open the connector capability-bridge WS (inverse MCP) for a session. */
export function openConnectorBridgeWs(sessionId: string): WebSocket {
  return makeAuthedWs(`${_getWsBase()}/ws/connector/${encodeURIComponent(sessionId)}`);
}

/** Open the realtime voice conversation WS (full-duplex audio) for a session. */
export function openRealtimeVoiceWs(sessionId: string): WebSocket {
  return makeAuthedWs(`${_getWsBase()}/ws/voice/realtime/${encodeURIComponent(sessionId)}`);
}

/**
 * Token is stale/invalid (REST 401 or 4401 WS close). Clear it and emit a
 * global ``geny:auth-failed`` signal the UI listens for to prompt re-login
 * (connector: open the login window; browser: drop to logged-out) — rather
 * than letting reconnect loops hammer the server with a dead token.
 */
export function handleAuthFailure(): void {
  removeToken();
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('geny:auth-failed'));
  }
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

  /** DELETE /api/agents/store/deleted — permanently purge ALL soft-deleted sessions */
  purgeDeleted: () =>
    apiCall<{ success: boolean; purged: number; errors: number }>(
      '/api/agents/store/deleted',
      { method: 'DELETE' },
    ),

  /** POST /api/agents/{id}/restore — restore deleted session */
  restore: (id: string) =>
    apiCall<{ success: boolean }>(`/api/agents/${id}/restore`, { method: 'POST' }),

  /** POST /api/agents/{id}/resume — lazily re-hydrate a dormant (post-restart)
   *  session. Idempotent: returns the live session info. */
  resume: (id: string) =>
    apiCall<SessionInfo>(`/api/agents/${id}/resume`, { method: 'POST' }),

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
      const ws = makeAuthedWs(wsUrl);
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
        if (ev.code === WS_UNAUTHORIZED_CODE) {
          console.warn(`${_tag} authentication failed (4401) — clearing token`);
          handleAuthFailure();
          onEvent('error', { error: 'Authentication failed', code: WS_UNAUTHORIZED_CODE });
        }
        finish();
      };
    });
  },

  /** POST /api/agents/{id}/stop — stop execution */
  stop: (id: string) =>
    apiCall<{ success: boolean }>(`/api/agents/${id}/stop`, {
      method: 'POST',
    }),

  /** PUT /api/agents/{id}/persona — give THIS session its own persona.
   *
   * `null` clears the override so the session follows its environment
   * again. Persisted, so it survives eviction and restart; a live idle
   * session rebuilds immediately (`applied_now`), a busy one picks it up
   * between turns rather than being torn down mid-answer. */
  setPersona: (id: string, presetId: string | null) =>
    apiCall<{
      success: boolean;
      persona_preset_id: string | null;
      effective_preset_id: string | null;
      persona_source: string;
      applied_now: boolean;
      live: boolean;
    }>(`/api/agents/${id}/persona`, {
      method: 'PUT',
      body: JSON.stringify({ persona_preset_id: presetId }),
    }),

  /** POST /api/agents/{id}/restart — rebuild now, keeping memory.
   *
   * 409 while a turn is running: a rebuild mid-answer loses the answer. */
  restart: (id: string) =>
    apiCall<{ success: boolean; restarted: boolean; reason?: string }>(
      `/api/agents/${id}/restart`,
      { method: 'POST' },
    ),

  /** PUT /api/agents/{id}/always-on — pin this session awake.
   *
   * `true` keeps it resident whatever the host's idle policy says,
   * `false` lets it be reclaimed even while the host keeps everything
   * else awake, `null` follows the host policy. Persisted, so the choice
   * survives the eviction (and the restart) it exists to prevent — which
   * is why a dormant session can be pinned too. */
  setAlwaysOn: (id: string, alwaysOn: boolean | null) =>
    apiCall<{ session_id: string; always_on: boolean | null; applied_live: boolean }>(
      `/api/agents/${id}/always-on`,
      { method: 'PUT', body: JSON.stringify({ always_on: alwaysOn }) },
    ),

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
    let ws: WebSocket | null = makeAuthedWs(wsUrl);

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
      if (ev.code === WS_UNAUTHORIZED_CODE) {
        console.warn(`${_tag} authentication failed (4401) — clearing token`);
        handleAuthFailure();
        onEvent('error', { error: 'Authentication failed', code: WS_UNAUTHORIZED_CODE });
      }
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

  /** GET /api/skills/list — registered SKILL.md inventory (G7.4).
   *  ``source_kind`` (Phase 10 follow-up) is one of:
   *  ``executor`` — shipped with geny-executor;
   *  ``geny``     — first-party Geny bundled tree;
   *  ``user``     — operator-supplied under ~/.geny/skills/;
   *  ``mcp``      — bridged from an MCP server's prompts;
   *  ``unknown``  — couldn't classify (very old shape / in-code register). */
  skillsList: () =>
    apiCall<{
      skills: Array<{
        id: string | null;
        name: string | null;
        description: string | null;
        model: string | null;
        allowed_tools: string[];
        category?: string | null;
        effort?: string | null;
        examples?: string[];
        source_kind?: SkillSourceKind;
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

  // Cycle G — MCP OAuth start.
  mcpAuthStart: (id: string, name: string) =>
    apiCall<{
      session_id: string;
      server_name: string;
      authorization_url: string;
      callback_path: string;
      state: string;
    }>(
      `/api/agents/${id}/mcp/servers/${encodeURIComponent(name)}/auth/start`,
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

  /**
   * PUT /api/agents/{id}/env — rebind a session to a different environment.
   * The session keeps its id/storage/memory/conversation; the pipeline
   * reloads from the new manifest between turns. For a VTuber pair, call
   * once per session id (the VTuber's and the Sub-Worker's) to set each
   * side independently.
   */
  changeEnv: (id: string, envId: string) =>
    apiCall<{
      success: boolean;
      session_id: string;
      env_id: string;
      previous_env_id: string | null;
      live: boolean;
      applies: string;
    }>(`/api/agents/${id}/env`, {
      method: 'PUT',
      body: JSON.stringify({ env_id: envId }),
    }),

  /**
   * GET /api/agents/{id}/sub-agent — view the executor persistent sub-agent
   * a VTuber owns (status + recent conversation + pending notifications).
   * 404 when the session has no executor sub-agent (bespoke mode / non-VTuber).
   */
  getSubAgent: (id: string) =>
    apiCall<{
      sub_agent_id: string;
      owner_session_id?: string;
      agent_type?: string;
      status: string;
      messages?: number;
      conversation: Array<{ role: string; content: string }>;
      inbox_count: number;
    }>(`/api/agents/${id}/sub-agent`),

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
  listStorage: (id: string, scope: 'workspace' | 'all' = 'all') =>
    apiCall<StorageListResponse>(`/api/agents/${id}/storage?scope=${scope}`),

  uploadToWorkspace: async (id: string, file: globalThis.File, subdir = 'uploads') => {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`${getBackendUrl()}/api/agents/${id}/storage/upload?subdir=${encodeURIComponent(subdir)}`, {
      method: 'POST',
      headers: withAuthHeaders(), // no Content-Type → browser sets multipart boundary
      body: fd,
    });
    if (!res.ok) throw new Error(`upload HTTP ${res.status}`);
    return res.json() as Promise<{ ok: boolean; path: string; workspace_path: string; size: number }>;
  },

  /** GET /api/agents/{id}/storage/{path} — read file from storage */
  getStorageFile: (id: string, path: string) =>
    apiCall<StorageFileContent>(`/api/agents/${id}/storage/${encodeURIComponent(path)}`),

  /** GET /api/agents/{id}/doc-preview?path= — on-demand office/pdf preview
   *  (pptx→per-slide SVG, docx/xlsx→PNG, pdf→PNG), rendered + cached server-side.
   *  Returns page paths (relative to storage) to load via storage-raw. */
  docPreview: (id: string, path: string) =>
    apiCall<{ kind: 'svg' | 'png' | 'unsupported'; count: number; pages: string[] }>(
      `/api/agents/${id}/doc-preview?path=${encodeURIComponent(path)}`,
    ),

  /** GET /api/agents/{id}/download-folder — download storage as ZIP */
  mkdirStorage: (id: string, path: string) =>
    apiCall<{ ok: boolean; path: string }>(
      `/api/agents/${id}/storage/mkdir?path=${encodeURIComponent(path)}`,
      { method: 'POST' },
    ),

  renameStorage: (id: string, src: string, dst: string) =>
    apiCall<{ ok: boolean; path: string }>(`/api/agents/${id}/storage/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ src, dst }),
    }),

  deleteStorageEntry: (id: string, path: string) =>
    apiCall<{ ok: boolean }>(
      `/api/agents/${id}/storage/entry?path=${encodeURIComponent(path)}`,
      { method: 'DELETE' },
    ),

  /** Authed fetch of a raw storage file → object URL (caller revokes). */
  fetchStorageBlobUrl: async (id: string, path: string) => {
    const res = await fetch(
      `${getBackendUrl()}/api/agents/${id}/storage-raw/${path.split('/').map(encodeURIComponent).join('/')}`,
      { headers: withAuthHeaders() },
    );
    if (!res.ok) throw new Error(`storage-raw HTTP ${res.status}`);
    return URL.createObjectURL(await res.blob());
  },

  downloadStorageFile: async (id: string, path: string, filename: string) => {
    const url = await agentApi.fetchStorageBlobUrl(id, path);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  downloadFolder: async (id: string, path = '') => {
    const qs = path ? `?path=${encodeURIComponent(path)}` : '';
    const res = await fetch(`/api/agents/${id}/download-folder${qs}`);
    if (!res.ok) {
      const body = await res.text();
      throw new Error(body || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = path ? `${path.split('/').pop()}.zip` : `session-${id.slice(0, 8)}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  /** Connector replicas currently syncing this workspace (Drive-style). */
  syncDevices: (id: string) =>
    apiCall<{ devices: Array<{ device_id: string; device_name: string; user: string }> }>(
      `/api/agents/${id}/storage/sync-devices`,
    ),
  /** Workspace subdirectories that are LINKED FOLDERS — folders living on
   *  a user's computer, shared into this agent through GenyDrive. */
  /** Agents connected to the caller's GenyCloud. */
  cloudMembers: () => apiCall<{ sessions: string[] }>(`/api/agents/cloud/members`),
  /** Newest-first "who changed what" history for a storage scope. */
  storageHistory: (id: string, limit = 200, beforeId = 0) =>
    apiCall<{
      events: Array<{
        id: number; ts: number; actor_kind: string; actor: string;
        action: string; path: string; size: number; detail: string;
      }>;
      has_more: boolean;
    }>(`/api/agents/${id}/storage/history?limit=${limit}&before_id=${beforeId}`),
  /** The caller's computers attached to the cloud, with the folders each
   *  shares. Offline machines stay listed — a sleeping laptop is paired,
   *  not gone, and its folders belong to it either way. */
  cloudDevices: () =>
    apiCall<{
      devices: Array<{
        device_id: string;
        device_name: string;
        online: boolean;
        last_seen: number | null;
        links: Array<{ name: string }>;
      }>;
      unassigned_links: Array<{ name: string }>;
    }>(`/api/agents/cloud/devices`),
  /** Connect/disconnect ONE agent to the cloud. Disconnecting removes the
   *  agent's reference; nothing in the cloud is deleted. */
  setCloudConnection: (id: string, connected: boolean) =>
    apiCall<{ connected: boolean; sessions: string[] }>(`/api/agents/${id}/cloud`, {
      method: 'PUT',
      body: JSON.stringify({ connected }),
    }),
  storageLinks: (id: string) =>
    apiCall<{ links: Array<{ name: string; device: string }> }>(
      `/api/agents/${id}/storage/links`,
    ),
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

  /** Fetch the task's output as text (auth header + cookie). Used by the
   *  Output modal — avoids the new-tab download/cross-origin quirks of a raw
   *  link, and surfaces sub-agent results (now stashed server-side). */
  output: async (sessionId: string, taskId: string): Promise<string> => {
    const token = getToken();
    const res = await fetch(
      `${getBackendUrl()}/api/agents/${encodeURIComponent(sessionId)}/tasks/${encodeURIComponent(taskId)}/output`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: 'include',
      },
    );
    if (!res.ok) throw new Error(`output fetch failed: ${res.status}`);
    return res.text();
  },
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

// T.1 (cycle 20260426_2) — Geny external tool catalog (manifest.tools.external).
//
// ``source_kind`` (cycle 20260525_1 follow-up) is the operator-facing
// classification:
//
//   * "geny_builtin"     — backend/tools/built_in/*_tools.py
//                          (memory_*, knowledge_*, geny_tools, etc.)
//   * "geny_custom_file" — backend/tools/custom/*_tools.py
//                          (browser_*, web_search_*, web_fetch_*)
//   * "custom_db"        — DB-backed (python_inline / http / mcp_proxy)
//                          — operator-authored via the Custom Tools tab.
//
// The legacy ``category`` field stays for backwards compat but the
// Stage 10 sidebar groups by ``source_kind``.
export type ExternalToolSourceKind =
  | 'geny_builtin'
  | 'geny_custom_file'
  | 'custom_db';

export interface ExternalToolEntry {
  name: string;
  category: string; // legacy: "built_in" | "custom"
  source_kind: ExternalToolSourceKind;
  description: string;
}

export interface ExternalToolCatalogResponse {
  tools: ExternalToolEntry[];
  note: string;
}

export const externalToolCatalogApi = {
  list: (lang?: 'en' | 'ko') =>
    apiCall<ExternalToolCatalogResponse>(
      lang
        ? `/api/tools/catalog/external?lang=${encodeURIComponent(lang)}`
        : '/api/tools/catalog/external',
    ),
};

// ==================== env-defaults (Phase 1, PR #552) ============
//
// Per-category id list of host registrations marked default-on for
// new envs. Storage uses Geny's `persistent_configs` table; the
// id derivation rules per category live in `lib/envDefaultsApi.ts`
// alongside the helpers (`hookId` / `skillId` / `permissionId` /
// `mcpServerId`) so the toggle endpoint and the seeder agree on
// what id a given row has.
//
// Empty list per category = "uncurated" — the new-draft seeder
// falls back to wildcard for hooks/skills/permissions, or no-op
// for mcp_servers (snapshot model — empty means no auto-add).

export type EnvDefaultsCategory =
  | 'hooks'
  | 'skills'
  | 'permissions'
  | 'mcp_servers'
  // Audit 2026-06-17 (C6) — custom (DB) tools ★-marked as a default for
  // new envs. Id = tool name (what lands in manifest.tools.external).
  | 'custom_tools';

export interface EnvDefaultsResponse {
  hooks: string[];
  skills: string[];
  permissions: string[];
  mcp_servers: string[];
  // Optional for backward-compat with backends that predate the C6
  // category (the useEnvDefaults store coalesces missing keys to []).
  custom_tools?: string[];
}

export interface EnvDefaultsCategoryResponse {
  category: EnvDefaultsCategory;
  ids: string[];
}

export const envDefaultsApi = {
  /** All four categories in one round-trip. */
  getAll: () => apiCall<EnvDefaultsResponse>('/api/env-defaults'),

  /** Single category — used when only one tab is mounted. */
  get: (category: EnvDefaultsCategory) =>
    apiCall<EnvDefaultsCategoryResponse>(
      `/api/env-defaults/${encodeURIComponent(category)}`,
    ),

  /** Replace a category's id list outright. */
  set: (category: EnvDefaultsCategory, ids: string[]) =>
    apiCall<EnvDefaultsCategoryResponse>(
      `/api/env-defaults/${encodeURIComponent(category)}`,
      {
        method: 'PUT',
        body: JSON.stringify({ ids }),
      },
    ),

  /** Flip one id on/off, response is the new full list. */
  toggle: (category: EnvDefaultsCategory, itemId: string) =>
    apiCall<EnvDefaultsCategoryResponse>(
      `/api/env-defaults/${encodeURIComponent(category)}/toggle/${encodeURIComponent(itemId)}`,
      { method: 'POST' },
    ),
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
  // R.1 (cycle 20260426_2) — currently-resolved modes (null = absent).
  mode?: string | null;
  executor_mode?: string | null;
}

export interface PermissionModePatch {
  mode?: string | null;
  executor_mode?: string | null;
}

export const PERMISSION_MODES = ['advisory', 'enforce'] as const;
export const EXECUTOR_PERMISSION_MODES = [
  'default',
  'plan',
  'auto',
  'bypass',
  'acceptEdits',
  'dontAsk',
] as const;

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

// ==================== Hooks CRUD API ===========================
//
// H.1 (cycle 20260426_2) rewrote the schema to match
// ``geny_executor.hooks.HookConfigEntry`` exactly. Lowercase event
// values, single ``command: string`` + separate ``args``, ``match``
// dict instead of ``tool_filter`` list, plus ``env`` / ``working_dir``
// / ``audit_log_path``.

export const HOOK_EVENTS = [
  'session_start',
  'session_end',
  'pipeline_start',
  'pipeline_end',
  'stage_enter',
  'stage_exit',
  'user_prompt_submit',
  'pre_tool_use',
  'post_tool_use',
  'post_tool_failure',
  'permission_request',
  'permission_denied',
  'loop_iteration_end',
  'cwd_changed',
  'mcp_server_state',
  'notification',
] as const;
export type HookEvent = typeof HOOK_EVENTS[number];

export interface HookEntryPayload {
  event: HookEvent;
  command: string;
  args?: string[];
  timeout_ms?: number | null;
  match?: Record<string, unknown>;
  env?: Record<string, string>;
  working_dir?: string | null;
}

export interface HookEntryRow {
  event: string;
  idx: number;
  command: string;
  args: string[];
  timeout_ms?: number | null;
  match: Record<string, unknown>;
  env: Record<string, string>;
  working_dir?: string | null;
}

export interface HookEntriesResponse {
  enabled: boolean;
  audit_log_path?: string | null;
  entries: HookEntryRow[];
  settings_path: string;
  known_events: string[];
}

export interface HookListResponse {
  enabled: boolean;
  env_opt_in: boolean;
  config_path: string;
  entries: Array<{
    event: string;
    command?: string | string[];
    args?: string[];
    timeout_ms?: number | null;
    match?: Record<string, unknown>;
    tool_filter?: string[]; // legacy admin endpoint may still report this
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

// NOTE: the env-management lifecycle-hooks EDITOR (hookApi CRUD over
// /api/hooks/entries) was removed — user hooks are now agent-created automations
// (see hooksApi → /api/automations). The executor lifecycle-hook primitive +
// its read-only admin diagnostics (agentApi.hooksList, recent-tool-events) stay.

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

  // R.1 (cycle 20260426_2) — set advisory↔enforce + executor_mode.
  patchMode: (patch: PermissionModePatch) =>
    apiCall<PermissionRulesResponse>('/api/permissions/mode', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  // Cascade-merged inspection (advisory|enforce + every source).
  inspect: () => apiCall<PermissionListResponse>('/api/permissions/list'),
};

// ==================== Admin telemetry rings (PR-E.4.1/2) =========

export interface RecentToolEvent {
  ts: number;
  kind: 'start' | 'complete' | string;
  tool_name: string;
  tool_use_id?: string | null;
  session_id?: string | null;
  is_error?: boolean | null;
  duration_ms?: number | null;
  extra?: Record<string, unknown> | null;
}

export interface RecentToolEventsResponse {
  events: RecentToolEvent[];
  capacity: number;
  returned: number;
}

export interface RecentPermissionDecision {
  ts: number;
  decision: string;
  tool_name?: string | null;
  rule_tool?: string | null;
  rule_pattern?: string | null;
  rule_source?: string | null;
  rule_reason?: string | null;
  session_id?: string | null;
  message?: string | null;
  extra?: Record<string, unknown> | null;
}

export interface RecentPermissionsResponse {
  decisions: RecentPermissionDecision[];
  capacity: number;
  returned: number;
}

export interface ToolUsageRow {
  tool_name: string;
  calls: number;
  completes: number;
  errors: number;
  total_duration_ms: number;
  last_at: number;
}

export interface ToolUsageResponse {
  counts: ToolUsageRow[];
  window_size: number;
}

export interface InProcessHookHandlerRow {
  event: string;
  handler_count: number;
}

export interface InProcessHandlersResponse {
  enabled: boolean;
  handlers: InProcessHookHandlerRow[];
  total: number;
}

export interface SettingsMigrationStatusResponse {
  legacy_files_present: string[];
  settings_json_path: string | null;
  settings_json_exists: boolean;
  settings_json_sections: string[];
  notes: string[];
}

export const adminTelemetryApi = {
  recentToolEvents: (limit = 50) =>
    apiCall<RecentToolEventsResponse>(`/api/admin/recent-tool-events?limit=${limit}`),
  recentPermissions: (limit = 50) =>
    apiCall<RecentPermissionsResponse>(`/api/admin/recent-permissions?limit=${limit}`),
  // PR-F.6.1/2/5
  systemStatus: () => apiCall<SystemStatusResponse>('/api/admin/system-status'),
  // Cycle G — usage / handlers / migration
  toolUsage: () => apiCall<ToolUsageResponse>('/api/admin/tool-usage'),
  hookInProcessHandlers: () => apiCall<InProcessHandlersResponse>('/api/admin/hook-in-process-handlers'),
  settingsMigrationStatus: () => apiCall<SettingsMigrationStatusResponse>('/api/admin/settings-migration-status'),
  // C.2 (cycle 20260426_1) — single-call wiring snapshot.
  integrationHealth: () => apiCall<IntegrationHealthResponse>('/api/admin/integration-health'),
  // E.1 (cycle 20260426_1) — between-turn runtime refresh.
  // O.1 (cycle 20260426_3) — extended scopes: memory_tuning + affect.
  reloadRuntime: (scope: 'permissions' | 'hooks' | 'memory_tuning' | 'affect' | 'all') =>
    apiCall<ReloadRuntimeResponse>('/api/admin/reload-runtime', {
      method: 'POST',
      body: JSON.stringify({ scope }),
    }),
};

// E.1 (cycle 20260426_1).
export interface ReloadRuntimeResponse {
  scope: string;
  queued_session_ids: string[];
  skipped_session_ids: string[];
  queued_count: number;
  note: string;
}

// C.2 (cycle 20260426_1) — Admin Integration Health card.
export interface RingFill {
  capacity: number;
  filled: number;
}

export interface IntegrationHealthResponse {
  settings_path: string;
  settings_exists: boolean;
  hooks_yaml_legacy_present: boolean;
  hooks_env_gate: boolean;
  task_runner_running: boolean;
  tool_event_ring: RingFill;
  permission_ring: RingFill;
  cron_history: RingFill;
  notes: string[];
}

export interface SubsystemStatusRow {
  name: string;
  present: boolean;
  detail: string | null;
  extra: Record<string, unknown> | null;
}

export interface SystemStatusResponse {
  subsystems: SubsystemStatusRow[];
  cron: { running?: boolean; cycle_seconds?: number | null; jobs?: number | null } | null;
  task_runner: { running?: boolean; in_flight?: number | null; max_concurrency?: number | null } | null;
  started_at: string | null;
}

// PR-F.6.3
export interface CronStatusResponse {
  running: boolean;
  cycle_seconds: number | null;
  jobs_total: number;
  jobs_enabled: number;
}

// ==================== Per-agent workspace (PR-E.4.3) =============

export interface WorkspaceFrame {
  cwd?: string | null;
  git_branch?: string | null;
  lsp_session_id?: string | null;
  env_vars: Record<string, string>;
  metadata: Record<string, unknown>;
}

export interface AgentWorkspaceResponse {
  available: boolean;
  depth: number;
  current?: WorkspaceFrame | null;
  stack: WorkspaceFrame[];
}

export interface WorkspaceCleanupResponse {
  available: boolean;
  popped: number;
  final_depth: number;
}

export const agentWorkspaceApi = {
  get: (sessionId: string) =>
    apiCall<AgentWorkspaceResponse>(`/api/agents/${sessionId}/workspace`),
  cleanup: (sessionId: string) =>
    apiCall<WorkspaceCleanupResponse>(`/api/agents/${sessionId}/workspace/cleanup`, {
      method: 'POST',
    }),
};

// ==================== Framework settings (PR-F.1.x) ==============

export interface FrameworkSectionSummary {
  name: string;
  has_schema: boolean;
  has_data: boolean;
  // D.2 (cycle 20260426_1) — modules that read this section at runtime.
  readers: string[];
}

export interface FrameworkSectionResponse {
  name: string;
  has_schema: boolean;
  schema: Record<string, unknown> | null;
  values: Record<string, unknown>;
  settings_path: string;
}

// ==================== Skills CRUD (PR-F.2.x) =====================

/** Origin classification for a loaded skill. Drives the SkillsTab
 *  badge and the SkillPanel chip styling. Phase 10 follow-up. */
export type SkillSourceKind =
  | 'executor'
  | 'geny'
  | 'user'
  | 'mcp'
  | 'unknown';

export interface SkillDetail {
  id: string;
  name: string | null;
  description: string | null;
  model: string | null;
  allowed_tools: string[];
  category: string | null;
  effort: string | null;
  examples: string[];
  body: string;
  source: string | null;
  is_user_skill: boolean;
  source_kind?: SkillSourceKind;
  // K.1 (cycle 20260426_2) — additional executor SkillMetadata fields.
  version?: string | null;
  execution_mode?: string | null;
  extras?: Record<string, unknown> | null;
}

export interface UserSkillUpsertRequest {
  id: string;
  name: string;
  description: string;
  body?: string;
  model_override?: string | null;
  allowed_tools?: string[];
  category?: string | null;
  effort?: string | null;
  examples?: string[];
  // K.1 (cycle 20260426_2).
  version?: string | null;
  execution_mode?: string | null;
  extras?: Record<string, string | number | boolean>;
}

// ==================== Notifications (Cycle G) ==================

export interface NotificationEndpointRow {
  name: string;
  type: string | null;
  target: string | null;
  enabled: boolean;
  extra: Record<string, unknown>;
}

export interface SendMessageChannelRow {
  name: string;
  impl: string | null;
}

export const notificationsApi = {
  listEndpoints: () =>
    apiCall<{ endpoints: NotificationEndpointRow[] }>('/api/notifications/endpoints'),
  listChannels: () =>
    apiCall<{ channels: SendMessageChannelRow[] }>('/api/notifications/channels'),
};

// ==================== Custom MCP Servers (Cycle G) ==============

export interface CustomMcpServerSummary {
  name: string;
  path: string;
  type?: string | null;
  description?: string | null;
}

export interface CustomMcpServerDetail {
  name: string;
  path: string;
  config: Record<string, unknown>;
}

export interface MCPTestConnectionResponse {
  success: boolean;
  latency_ms: number;
  tools_discovered: number;
  error: string | null;
}

export const customMcpApi = {
  list: () => apiCall<{ servers: CustomMcpServerSummary[]; custom_dir: string }>('/api/mcp/custom'),
  get: (name: string) => apiCall<CustomMcpServerDetail>(`/api/mcp/custom/${encodeURIComponent(name)}`),
  create: (name: string, config: Record<string, unknown>, description?: string) =>
    apiCall<CustomMcpServerDetail>('/api/mcp/custom', {
      method: 'POST',
      body: JSON.stringify({ name, config, description }),
    }),
  replace: (name: string, config: Record<string, unknown>, description?: string) =>
    apiCall<CustomMcpServerDetail>(`/api/mcp/custom/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify({ name, config, description }),
    }),
  remove: (name: string) =>
    apiCall<{ deleted: boolean; name: string }>(`/api/mcp/custom/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),
  /** Dry-run a server config without saving — invokes the executor's
   *  `MCPManager.test_connection`. Used by the modal's "연결 테스트"
   *  button so beginners can verify before committing. */
  test: (name: string, config: Record<string, unknown>) =>
    apiCall<MCPTestConnectionResponse>('/api/mcp/custom/test', {
      method: 'POST',
      body: JSON.stringify({ name, config }),
    }),
};

// ==================== Custom Tools (Phase B — DB-backed) ==========

export type CustomToolBackendKind =
  | 'http'
  | 'mcp_proxy'
  | 'builtin_alias'
  | 'python_inline';

export interface CustomToolSummary {
  id: string;
  name: string;
  description: string;
  backend_kind: CustomToolBackendKind;
  enabled: boolean;
  is_sample: boolean;
}

export interface CustomToolDetail extends CustomToolSummary {
  input_schema: Record<string, unknown>;
  config: Record<string, unknown>;
  capabilities: Record<string, unknown>;
}

export interface CustomToolPayload {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  backend_kind: CustomToolBackendKind;
  config: Record<string, unknown>;
  capabilities?: Record<string, unknown>;
  enabled?: boolean;
}

export interface CustomToolTestResponse {
  ok: boolean;
  result?: string;
  error?: string;
  duration_ms?: number;
}

export const customToolsApi = {
  list: () => apiCall<{ tools: CustomToolSummary[] }>('/api/custom-tools'),
  get: (toolId: string) =>
    apiCall<CustomToolDetail>(`/api/custom-tools/${encodeURIComponent(toolId)}`),
  create: (payload: CustomToolPayload) =>
    apiCall<CustomToolDetail>('/api/custom-tools', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  replace: (toolId: string, payload: CustomToolPayload) =>
    apiCall<CustomToolDetail>(`/api/custom-tools/${encodeURIComponent(toolId)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  remove: (toolId: string) =>
    apiCall<{ ok: boolean }>(`/api/custom-tools/${encodeURIComponent(toolId)}`, {
      method: 'DELETE',
    }),
  setEnabled: (toolId: string, enabled: boolean) =>
    apiCall<CustomToolDetail>(`/api/custom-tools/${encodeURIComponent(toolId)}/enabled`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),
  duplicate: (toolId: string) =>
    apiCall<CustomToolDetail>(`/api/custom-tools/${encodeURIComponent(toolId)}/duplicate`, {
      method: 'POST',
    }),
  test: (toolId: string, args: Record<string, unknown>, dryRun = true) =>
    apiCall<CustomToolTestResponse>(`/api/custom-tools/${encodeURIComponent(toolId)}/test`, {
      method: 'POST',
      body: JSON.stringify({ arguments: args, dry_run: dryRun }),
    }),
};

// ==================== Subagent Types (PR-F.3.1) ==================

export interface SubagentTypeRow {
  agent_type: string;
  description: string;
  allowed_tools: string[];
}

export const subagentTypeApi = {
  list: () => apiCall<{ types: SubagentTypeRow[] }>('/api/subagent-types'),
};

export interface SkillTestResponse {
  ok: boolean;
  skill_md: string;
  metadata: Record<string, unknown> | null;
  body_chars: number;
  body_lines: number;
  warnings: string[];
  errors: string[];
}

export const skillsApi = {
  get: (skillId: string) => apiCall<SkillDetail>(`/api/skills/${encodeURIComponent(skillId)}`),

  createUserSkill: (req: UserSkillUpsertRequest) =>
    apiCall<{ id: string; path: string }>('/api/skills/user', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  replaceUserSkill: (req: UserSkillUpsertRequest) =>
    apiCall<{ id: string; path: string }>(`/api/skills/user/${encodeURIComponent(req.id)}`, {
      method: 'PUT',
      body: JSON.stringify(req),
    }),

  deleteUserSkill: (skillId: string) =>
    apiCall<{ deleted: boolean; id: string }>(`/api/skills/user/${encodeURIComponent(skillId)}`, {
      method: 'DELETE',
    }),

  /** Dry-run a draft skill against the executor's parser without
   *  saving (Phase 9.7). Used by the form modal's "테스트 / Test"
   *  button so beginners can verify before committing. */
  test: (req: UserSkillUpsertRequest) =>
    apiCall<SkillTestResponse>('/api/skills/test', {
      method: 'POST',
      body: JSON.stringify(req),
    }),
};

export const frameworkSettingsApi = {
  list: () =>
    apiCall<{ sections: FrameworkSectionSummary[] }>('/api/framework-settings'),
  get: (name: string) =>
    apiCall<FrameworkSectionResponse>(`/api/framework-settings/${encodeURIComponent(name)}`),
  patch: (name: string, values: Record<string, unknown>) =>
    apiCall<FrameworkSectionResponse>(`/api/framework-settings/${encodeURIComponent(name)}`, {
      method: 'PATCH',
      body: JSON.stringify({ values }),
    }),
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
  next_fire_at?: string | null;
}

export interface CronJobHistoryEntry {
  fired_at: string;
  task_id: string | null;
  status: string | null;
  error: string | null;
}

export interface CronJobHistoryResponse {
  name: string;
  fires: CronJobHistoryEntry[];
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

  // PR-F.4.1
  setStatus: (name: string, status: 'enabled' | 'disabled') =>
    apiCall<CronJobRecord>(`/api/cron/jobs/${encodeURIComponent(name)}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),

  // PR-F.4.4
  history: (name: string, limit = 20) =>
    apiCall<CronJobHistoryResponse>(
      `/api/cron/jobs/${encodeURIComponent(name)}/history?limit=${limit}`,
    ),

  // PR-F.6.3
  status: () => apiCall<CronStatusResponse>('/api/cron/status'),
};

// ==================== Hooks (user automation) API ====================
// Agent-created automations. Created via the HookCreate tool in chat (no create
// endpoint here); this client just lists / pauses / deletes them.

export interface HookRecord {
  name: string;
  kind: string; // "schedule" | "event"
  cron_expr: string;
  status: string; // "enabled" | "disabled"
  description?: string | null;
  action_prompt?: string | null;
  session_id?: string | null;
  last_fired_at?: string | null;
  next_fire_at?: string | null;
}

export const hooksApi = {
  list: (sessionId?: string) =>
    apiCall<HookRecord[]>(
      `/api/automations${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''}`,
    ),
  setStatus: (name: string, status: 'enabled' | 'disabled') =>
    apiCall<HookRecord>(`/api/automations/${encodeURIComponent(name)}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),
  delete: (name: string) =>
    apiCall<{ deleted: string; ok: boolean }>(
      `/api/automations/${encodeURIComponent(name)}`,
      { method: 'DELETE' },
    ),
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

// ==================== GAPT API ====================

export interface GaptStatus {
  /** GAPT_BASE_URL is set on the backend */
  configured: boolean;
  /** GAPT control plane answered /health */
  running: boolean;
  base_url: string;
  /** same-origin path to the GAPT SPA (via nginx) */
  ui_path: string;
}

export const gaptApi = {
  /** GET /api/gapt/status — is the GAPT platform wired up + reachable? */
  status: () => apiCall<GaptStatus>('/api/gapt/status'),
  /** GET /api/gapt/sso — establish a GAPT browser session (login bypass) for the
   *  authenticated Geny user; the Set-Cookie lands same-origin so opening the
   *  GAPT SPA skips its login. No-op cookie when GENY_GAPT_SSO_BYPASS=false. */
  sso: () => apiCall<{ bypass: boolean; ui_path: string; established?: string[] }>('/api/gapt/sso'),
};

/** Proxy to a connected GAPT instance's own settings (Cloudflare etc.). All
 *  endpoints 412 when GAPT isn't configured; the GAPT category only renders
 *  when gaptApi.status().running, so callers don't normally hit that. */
export const gaptSettingsApi = {
  getCloudflare: () => apiCall<any>('/api/gapt/settings/cloudflare'),
  putCloudflare: (body: { api_token?: string; config: Record<string, any> }) =>
    apiCall<any>('/api/gapt/settings/cloudflare', { method: 'PUT', body: JSON.stringify(body) }),
  deleteCloudflare: () =>
    apiCall<any>('/api/gapt/settings/cloudflare', { method: 'DELETE' }),
  verifyCloudflare: (body?: Record<string, any>) =>
    apiCall<any>('/api/gapt/settings/cloudflare/verify', { method: 'POST', body: JSON.stringify(body || {}) }),
  tunnelSnapshot: () => apiCall<any>('/api/gapt/settings/cloudflare/tunnel/snapshot'),
  ensureWildcard: (body?: Record<string, any>) =>
    apiCall<any>('/api/gapt/settings/cloudflare/tunnel/ensure-wildcard', { method: 'POST', body: JSON.stringify(body || {}) }),
  certStatus: () => apiCall<any>('/api/gapt/settings/cloudflare/cert/status'),
  enableTotalTls: (body?: Record<string, any>) =>
    apiCall<any>('/api/gapt/settings/cloudflare/cert/enable-total-tls', { method: 'POST', body: JSON.stringify(body || {}) }),
  diagnose: () => apiCall<any>('/api/gapt/settings/diagnose'),
  llmHealth: () => apiCall<any>('/api/gapt/settings/llm-health'),
};

/** geny-avatar integration — status + settings (image-gen keys) proxy. */
export const avatarApi = {
  status: () => apiCall<{ configured: boolean; running: boolean; base_url: string }>('/api/avatar/status'),
  getKeys: () => apiCall<any>('/api/avatar/settings/keys'),
  putKeys: (body: { set?: Record<string, string>; clear?: string[] }) =>
    apiCall<any>('/api/avatar/settings/keys', { method: 'PUT', body: JSON.stringify(body) }),
};

// ==================== Google Workspace API ====================
//
// Connect a Google account entirely from the UI via the OAuth authorization-code
// flow in a popup. The operator first stores a "Web application" OAuth client
// (id + secret), then clicks Connect: the UI fetches authUrl() (passing the
// page-origin redirect_uri the operator registered in Google Cloud), opens the
// returned consent URL in a popup, and the backend's public /api/google/callback
// page posts a `google-oauth` message back to window.opener on completion. Once
// connected, the Gmail / Calendar / Drive / Tasks tools become available to
// agents automatically.

export interface GoogleStatus {
  /** An OAuth client (id + secret) has been stored. */
  has_client: boolean;
  /** A Google account is connected (tokens present). */
  connected: boolean;
  /** The stored client_id (not a secret) — shown so the operator can verify it. */
  client_id?: string;
}

export interface GoogleSetClientResponse {
  ok: boolean;
  has_client: boolean;
}

export interface GoogleAuthUrlResponse {
  /** The Google OAuth consent URL to open in the popup. */
  auth_url: string;
  /** Echo of the redirect_uri the URL was built for. */
  redirect_uri: string;
}

export const googleApi = {
  /** GET /api/google/status — is a client stored / an account connected? */
  status: () => apiCall<GoogleStatus>('/api/google/status'),
  /** PUT /api/google/client — store the OAuth client id + secret. */
  setClient: (clientId: string, clientSecret: string) =>
    apiCall<GoogleSetClientResponse>('/api/google/client', {
      method: 'PUT',
      body: JSON.stringify({ client_id: clientId, client_secret: clientSecret }),
    }),
  /**
   * GET /api/google/auth-url — build the OAuth consent URL for the given
   * redirect_uri (the page-origin /api/google/callback the operator
   * registered in Google Cloud). 412 if no client is stored. The returned
   * auth_url is opened in a popup; the backend callback posts a
   * `google-oauth` message back to window.opener on completion.
   */
  authUrl: (redirectUri: string) =>
    apiCall<GoogleAuthUrlResponse>(
      `/api/google/auth-url?redirect_uri=${encodeURIComponent(redirectUri)}`,
    ),
  /** POST /api/google/disconnect — drop the connected account. */
  disconnect: () =>
    apiCall<{ ok: boolean }>('/api/google/disconnect', { method: 'POST' }),
};

// ==================== MCP Ecosystem Connectors ====================
//
// One-click MCP ecosystem connectors (GitHub, Notion, Composio, Slack,
// Postgres, Brave, custom HTTP). Enabling a connector makes its MCP tools
// available to agents automatically — gated until its required fields are
// configured. Secure field values come back masked ("••••xxxx"); a value left
// as the masked placeholder is ignored server-side, so the UI must not resend
// masked secrets.

/** Transport the connector's MCP server speaks over. */
export type ConnectorTransport = 'http' | 'stdio';

export interface ConnectorField {
  name: string;
  label: string;
  required: boolean;
  /** Render as a password input; value comes back masked from GET. */
  secure: boolean;
  placeholder?: string;
  description?: string;
}

export interface Connector {
  id: string;
  name: string;
  description: string;
  icon: string;
  transport: ConnectorTransport;
  docs_url?: string;
  config_name?: string;
  enabled: boolean;
  /** All required fields have values. */
  configured: boolean;
  fields: ConnectorField[];
}

export interface ConnectorDetail {
  id: string;
  enabled: boolean;
  /** Current field values; secure ones are masked ("••••xxxx"). */
  values: Record<string, string>;
}

export const connectorsApi = {
  /** GET /api/connectors — list every connector + its enabled/configured state. */
  list: () => apiCall<{ connectors: Connector[] }>('/api/connectors'),
  /** GET /api/connectors/{id} — current values (secure fields masked). */
  get: (id: string) =>
    apiCall<ConnectorDetail>(`/api/connectors/${encodeURIComponent(id)}`),
  /** PUT /api/connectors/{id} — set enabled + field values. Values left as the
   *  masked placeholder are ignored server-side; don't resend masked secrets. */
  update: (id: string, body: { enabled: boolean; values: Record<string, string> }) =>
    apiCall<{ ok: boolean; id: string }>(`/api/connectors/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
};

/** Cross-service settings sync — Geny propagates shared provider keys to GAPT + avatar. */
export const syncApi = {
  /** Which sync targets are wired (no network probe). */
  targets: () => apiCall<{ targets: Record<string, { configured: boolean }> }>('/api/sync/targets'),
  /** Re-push every set provider key to all connected targets. */
  providerKeysNow: () => apiCall<{ ok: boolean; results: Record<string, any> }>('/api/sync/provider-keys', { method: 'POST' }),
};

// ==================== Config API ====================

import type {
  ConfigListResponse,
  ConfigSchema,
  ToolSettingSchemasResponse,
} from '@/types';

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

// ==================== SSH (server connection test) =========================

export interface SshServer {
  name: string;
  host: string;
  port: number;
  user: string;
  password?: string;
  private_key?: string;
  passphrase?: string;
  description?: string;
  strict_host_key?: boolean;
}

export interface SshTestResponse {
  success: boolean;
  latency_ms?: number | null;
  error?: string | null;
}

export const sshApi = {
  /** POST /api/ssh/test — dry-run a single server draft (need not be saved).
   *  Verifies reachability + auth via the executor's SSH helper. */
  testServer: (server: Partial<SshServer>) =>
    apiCall<SshTestResponse>('/api/ssh/test', {
      method: 'POST',
      body: JSON.stringify(server),
    }),
};

// ==================== Tool Settings API (per-environment) ====================

/**
 * Schema-driven per-environment tool configuration (e.g. `web_search`).
 * Only the schemas are fetched from the backend; values live on the
 * environment manifest draft (`host_selections.extras.tool_settings`) and
 * persist via the normal manifest save — there is no per-value endpoint.
 */
export const toolSettingsApi = {
  /** GET /api/tool-settings/schemas — list configurable tool schemas */
  getSchemas: () =>
    apiCall<ToolSettingSchemasResponse>('/api/tool-settings/schemas').then(
      (res) => res.schemas ?? [],
    ),
};

// ==================== LLM Backends API (Phase E4 / F2) ====================

export interface ProviderHealth {
  provider: string;
  label: string;
  kind: 'api' | 'cli';
  available: boolean;
  detail?: string | null;
  detail_code?: string | null;
  detail_params?: Record<string, string> | null;
  binary_path?: string | null;
  binary_version?: string | null;
  auth_ok?: boolean | null;
  auth_method?: 'api_key' | 'subscription' | 'extension' | null;
  install_help?: string | null;
  install_help_code?: string | null;
}

export interface BackendsHealthResponse {
  providers: ProviderHealth[];
}

export interface LocalModelsResponse {
  provider: string;
  base_url: string;
  reachable: boolean;
  models: string[];
  detail_code?: string | null;
}

export interface ProviderModel {
  id: string;
  display_name?: string | null;
}

export interface ProviderModelsResponse {
  provider: string;
  /** "live" = real backend list; "unavailable" = fall back to static catalog. */
  source: string;
  models: ProviderModel[];
  error?: string | null;
}

export interface LocalContextWindowResponse {
  provider: string;
  base_url: string;
  model: string;
  context_window?: number | null;
}

export interface SubagentInfo {
  agent_type: string;
  description: string;
  provider?: string | null;
  allowed_tools: string[];
  model_override?: string | null;
}

export interface SubagentsResponse {
  items: SubagentInfo[];
}

// Phase G — auth flow shapes.

export interface ClaudeCodeAuthStatus {
  raw: Record<string, unknown>;
  logged_in?: boolean | null;
  auth_method?: string | null;       // "claude.ai" | "console" | ...
  subscription_type?: string | null; // "max" | "pro" | ...
  email?: string | null;
  org_name?: string | null;
}

export interface ClaudeCodeVersionStatus {
  package: string;
  current: string | null;
  latest: string | null;
  pinned: string | null;
  previous: string | null;
  history: string[];
  update_available: boolean;
  can_rollback: boolean;
  ok?: boolean;
  installed?: string;
  error?: string;
}

export interface AuthLoginStartResponse {
  job_id: string;
  kind: 'claude_code';
  argv: string[];
  hint: string;
}

export interface AuthJobEvent {
  channel: 'stdout' | 'stderr' | 'exit';
  text: string;
  ts: number;
  exit_code?: number;
}

export interface TestConnectionResponse {
  ok: boolean;
  duration_ms: number;
  detail: string;
  raw_stdout_tail?: string | null;
  raw_stderr_tail?: string | null;
}

export const llmBackendsApi = {
  /** GET /api/llm-backends/health — every provider's status.
   *  ``revalidate`` re-probes cloud API keys against their providers
   *  (bypasses the per-key verdict cache). */
  health: (revalidate = false) =>
    apiCall<BackendsHealthResponse>(
      `/api/llm-backends/health${revalidate ? '?revalidate=true' : ''}`,
    ),

  /** POST /api/llm-backends/cli/claude-code/recheck */
  recheckClaudeCode: () =>
    apiCall<ProviderHealth>('/api/llm-backends/cli/claude-code/recheck', { method: 'POST' }),

  /** GET /api/llm-backends/subagents */
  subagents: () => apiCall<SubagentsResponse>('/api/llm-backends/subagents'),

  // ── Local (OpenAI-compatible) backends — discovery + context probe ──

  /** GET /api/llm-backends/local-models — discover models served by a
   *  local backend (Ollama / LM Studio / custom). ``baseUrl`` overrides
   *  the stored/default endpoint so "Test" works before save. */
  localModels: (provider: string, baseUrl?: string) => {
    const params = new URLSearchParams({ provider });
    if (baseUrl) params.set('base_url', baseUrl);
    return apiCall<LocalModelsResponse>(
      `/api/llm-backends/local-models?${params.toString()}`,
    );
  },

  /** GET /api/llm-backends/models — live-list the models a provider serves
   *  (cloud + local). source="live" → real list; "unavailable" → caller
   *  falls back to the static catalog. */
  providerModels: (provider: string, baseUrl?: string) => {
    const params = new URLSearchParams({ provider });
    if (baseUrl) params.set('base_url', baseUrl);
    return apiCall<ProviderModelsResponse>(
      `/api/llm-backends/models?${params.toString()}`,
    );
  },

  /** GET /api/llm-backends/local-context-window — probe a local model's
   *  real context window (Ollama /api/show) to auto-fill num_ctx. */
  localContextWindow: (provider: string, model: string, baseUrl?: string) => {
    const params = new URLSearchParams({ provider, model });
    if (baseUrl) params.set('base_url', baseUrl);
    return apiCall<LocalContextWindowResponse>(
      `/api/llm-backends/local-context-window?${params.toString()}`,
    );
  },

  // ── Claude Code CLI version management (keep-latest + rollback) ──

  claudeCodeVersion: () =>
    apiCall<ClaudeCodeVersionStatus>('/api/llm-backends/claude-code/version'),

  claudeCodeUpdate: (version = 'latest') =>
    apiCall<ClaudeCodeVersionStatus>('/api/llm-backends/claude-code/version/update', {
      method: 'POST',
      body: JSON.stringify({ version }),
    }),

  claudeCodeRollback: () =>
    apiCall<ClaudeCodeVersionStatus>('/api/llm-backends/claude-code/version/rollback', {
      method: 'POST',
    }),

  // ── Phase G — Claude Code auth ────────────────────────────────

  claudeCodeStatus: () =>
    apiCall<ClaudeCodeAuthStatus>('/api/llm-backends/cli/claude-code/auth/status'),

  claudeCodeStartLogin: (opts?: { useConsole?: boolean; email?: string }) => {
    const params = new URLSearchParams();
    if (opts?.useConsole) params.set('use_console', 'true');
    if (opts?.email) params.set('email', opts.email);
    const qs = params.toString();
    return apiCall<AuthLoginStartResponse>(
      `/api/llm-backends/cli/claude-code/auth/login${qs ? `?${qs}` : ''}`,
      { method: 'POST' },
    );
  },

  claudeCodeLogout: () =>
    apiCall<{ ok: boolean }>('/api/llm-backends/cli/claude-code/auth/logout', { method: 'POST' }),

  claudeCodeTest: () =>
    apiCall<TestConnectionResponse>('/api/llm-backends/cli/claude-code/test', { method: 'POST' }),

  // ── Phase G — Shared SSE / cancel ─────────────────────────────

  /** Polling fallback / full snapshot of an auth job. */
  authJobState: (jobId: string) =>
    apiCall<{
      job_id: string;
      kind: string;
      argv: string[];
      started_at: number;
      finished_at: number | null;
      exit_code: number | null;
      history: AuthJobEvent[];
    }>(`/api/llm-backends/auth/login/${encodeURIComponent(jobId)}`),

  cancelAuthJob: (jobId: string) =>
    apiCall<{ ok: boolean; already_finished?: boolean }>(
      `/api/llm-backends/auth/login/${encodeURIComponent(jobId)}/cancel`,
      { method: 'POST' },
    ),

  /** Forward one line (or raw bytes) to the auth subprocess's stdin.
   *  Used by the modal to deliver the OAuth auth code the user pastes
   *  back from the browser into the CLI's prompt. */
  submitAuthJobInput: (jobId: string, text: string, appendNewline = true) =>
    apiCall<{ ok: boolean }>(
      `/api/llm-backends/auth/login/${encodeURIComponent(jobId)}/input`,
      {
        method: 'POST',
        body: JSON.stringify({ text, append_newline: appendNewline }),
      },
    ),

  /** Returns the SSE URL the modal opens an EventSource against.
   *  Browser's EventSource carries cookies for same-origin requests,
   *  which is how we authenticate. */
  authJobEventsUrl: (jobId: string) =>
    `${getBackendUrl()}/api/llm-backends/auth/login/${encodeURIComponent(jobId)}/events`,
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
        ws = makeAuthedWs(wsUrl);
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

        // Auth failure: the token is dead. Stop the reconnect loop, clear the
        // token and surface a re-login signal instead of hammering forever.
        if (ev.code === WS_UNAUTHORIZED_CODE) {
          console.warn(`${_tag} authentication failed (4401) — stopping reconnect, clearing token`);
          closed = true;
          handleAuthFailure();
          onEvent('_ws_auth_failed', { code: WS_UNAUTHORIZED_CODE, url: wsUrl });
          return;
        }

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

  /** GET /api/agents/{sid}/memory/overview — counts only, no bodies.
   *
   * Step 1 of the vault's progressive disclosure: what a sidebar needs to
   * render before anyone expands anything is a number per category and per
   * day. Measured at 1.2ms against the 5,384-note production vault, versus
   * 3.2s for the listing it replaces. */
  getOverview: (sessionId: string, params?: { kind?: string }) => {
    const qs = new URLSearchParams();
    if (params?.kind) qs.set('kind', params.kind);
    const q = qs.toString();
    return apiCall<import('@/types').MemoryOverview>(
      `/api/agents/${sessionId}/memory/overview${q ? `?${q}` : ''}`,
    );
  },

  /** GET /api/agents/{sid}/memory/day/{day} — one day's notes, metadata only.
   *
   * Step 2: expanding a day costs a read proportional to THAT day. Bodies
   * still arrive only through `readFile`, when a note is actually opened. */
  getDay: (
    sessionId: string,
    day: string,
    params?: { kind?: string; limit?: number; offset?: number },
  ) => {
    const qs = new URLSearchParams();
    if (params?.kind) qs.set('kind', params.kind);
    if (params?.limit != null) qs.set('limit', String(params.limit));
    if (params?.offset != null) qs.set('offset', String(params.offset));
    const q = qs.toString();
    return apiCall<import('@/types').MemoryDayResponse>(
      `/api/agents/${sessionId}/memory/day/${encodeURIComponent(day)}${q ? `?${q}` : ''}`,
    );
  },

  /** GET /api/agents/{sid}/memory/graph/around — the subgraph around a seed.
   *
   * `getGraph` returns the WHOLE vault (4.3 MB measured); this asks the same
   * question at the scale a screen is read at and reports `truncated` when it
   * had to stop. With no seed it returns nothing — a full download must never
   * be the default. */
  getGraphAround: (
    sessionId: string,
    params: {
      node?: string[];
      /** A note FILENAME for the server to resolve into an index id. Use
       *  this rather than assembling an id here — the format belongs to
       *  the index and includes the scope, which the browser cannot know. */
      file?: string;
      day?: string;
      kind?: string;
      depth?: number;
      maxNodes?: number;
    },
  ) => {
    const qs = new URLSearchParams();
    (params.node ?? []).forEach((n) => qs.append('node', n));
    if (params.file) qs.set('file', params.file);
    if (params.day) qs.set('day', params.day);
    if (params.kind) qs.set('kind', params.kind);
    if (params.depth != null) qs.set('depth', String(params.depth));
    if (params.maxNodes != null) qs.set('max_nodes', String(params.maxNodes));
    return apiCall<import('@/types').MemoryNeighbourhood>(
      `/api/agents/${sessionId}/memory/graph/around?${qs.toString()}`,
    );
  },

  /** GET /api/agents/{sid}/memory/files — list files */
  listFiles: (
    sessionId: string,
    params?: { category?: string; tag?: string; limit?: number; offset?: number },
  ) => {
    const qs = new URLSearchParams();
    if (params?.category) qs.set('category', params.category);
    if (params?.tag) qs.set('tag', params.tag);
    if (params?.limit != null) qs.set('limit', String(params.limit));
    if (params?.offset != null) qs.set('offset', String(params.offset));
    const q = qs.toString();
    return apiCall<import('@/types').MemoryFileListResponse>(
      `/api/agents/${sessionId}/memory/files${q ? `?${q}` : ''}`
    );
  },

  /** GET /api/agents/{sid}/memory/files/{filename} — read a file */
  /** Relative URL for a memory attachment (observation frame) — usable as <img src>. */
  attachmentUrl: (sessionId: string, filename: string): string =>
    `/api/agents/${encodeURIComponent(sessionId)}/memory/attachments/${encodeURIComponent(
      filename.replace(/^.*\//, ''),
    )}`,

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

  /** GET /api/agents/{sid}/memory/search?q=...
   *
   * Cycle 20260430_3 E — `counterpart` / `kinds` narrow only
   * InteractionEvent hits server-side. Non-event memories (LTM
   * notes, curated knowledge) pass through unchanged. */
  search: (
    sessionId: string,
    query: string,
    params?: {
      max_results?: number;
      category?: string;
      tag?: string;
      counterpart?: string;
      kinds?: string | string[];
    },
  ) => {
    const qs = new URLSearchParams({ q: query });
    if (params?.max_results) qs.set('max_results', String(params.max_results));
    if (params?.category) qs.set('category', params.category);
    if (params?.tag) qs.set('tag', params.tag);
    if (params?.counterpart) qs.set('counterpart', params.counterpart);
    if (params?.kinds) {
      const csv = Array.isArray(params.kinds) ? params.kinds.join(',') : params.kinds;
      if (csv) qs.set('kinds', csv);
    }
    return apiCall<import('@/types').MemorySearchResponse>(
      `/api/agents/${sessionId}/memory/search?${qs.toString()}`
    );
  },

  /** GET /api/agents/{sid}/memory/categories — every category folder
   * (canonical + host-defined) with file_count + description. Used by
   * the Opsidian sidebar so empty folders also surface.
   */
  listCategories: (sessionId: string) =>
    apiCall<{
      categories: Array<{
        name: string;
        file_count: number;
        path: string;
        exists: boolean;
        description?: string;
      }>;
    }>(`/api/agents/${sessionId}/memory/categories`),

  /** GET /api/agents/{sid}/memory/summary — the compressed-first view: the
   *  rolling digest (Stage-2 L1) + the durable evergreen (pinned critical).
   *  These are what the agent is served before any raw memory. */
  getSummary: (sessionId: string) =>
    apiCall<{
      digest: string;
      evergreen: string;
      has_digest: boolean;
      has_evergreen: boolean;
    }>(`/api/agents/${sessionId}/memory/summary`),

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

// ==================== Transcripts API (cycle 20260430_3) ====================
//
// Read-only view over the InteractionEvent stream stored in STM.
// Backed by `controller/transcripts_controller.py`. Renders to the
// MemoryTab Stream sub-tab (Stage D).

export const transcriptsApi = {
  /** GET /api/agents/{sid}/transcripts — list with cursor + filters */
  list: (
    sessionId: string,
    params?: {
      limit?: number;
      cursor?: string;
      counterpart?: string;
      /** Comma-joined or array of kind names. */
      kinds?: string | string[];
      direction?: 'in' | 'out' | 'internal';
      since?: string;
    },
  ) => {
    const qs = new URLSearchParams();
    if (params?.limit !== undefined) qs.set('limit', String(params.limit));
    if (params?.cursor) qs.set('cursor', params.cursor);
    if (params?.counterpart) qs.set('counterpart', params.counterpart);
    if (params?.kinds) {
      const csv = Array.isArray(params.kinds) ? params.kinds.join(',') : params.kinds;
      if (csv) qs.set('kinds', csv);
    }
    if (params?.direction) qs.set('direction', params.direction);
    if (params?.since) qs.set('since', params.since);
    const q = qs.toString();
    return apiCall<import('@/types').TranscriptListResponse>(
      `/api/agents/${sessionId}/transcripts${q ? `?${q}` : ''}`,
    );
  },

  /** GET /api/agents/{sid}/transcripts/{event_id} */
  get: (sessionId: string, eventId: string) =>
    apiCall<import('@/types').TranscriptDetailResponse>(
      `/api/agents/${sessionId}/transcripts/${encodeURIComponent(eventId)}`,
    ),

  /** GET /api/agents/{sid}/transcripts/counterparts */
  counterparts: (sessionId: string) =>
    apiCall<import('@/types').CounterpartListResponse>(
      `/api/agents/${sessionId}/transcripts/counterparts`,
    ),

  /** GET /api/agents/{sid}/transcripts/{event_id}/artifact?path=... */
  artifact: (
    sessionId: string,
    eventId: string,
    path: string,
    maxBytes?: number,
  ) => {
    const qs = new URLSearchParams({ path });
    if (maxBytes !== undefined) qs.set('max_bytes', String(maxBytes));
    return apiCall<import('@/types').ArtifactReadResponse>(
      `/api/agents/${sessionId}/transcripts/${encodeURIComponent(eventId)}/artifact?${qs.toString()}`,
    );
  },
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

  /** GET /api/vtuber/models/stream — server-sent stream of model
   *  registry changes. Backend emits a `models_changed` event every
   *  time a model is added/replaced/removed (auto-publish renames,
   *  fresh installs, library deletes). Caller refetches `/api/vtuber
   *  /models` on each event so the dropdown reflects the current
   *  state without polling. */
  subscribeToModelChanges: (
    onChange: () => void,
  ): { close: () => void } => {
    const base = getBackendUrl();
    // EventSource constructor doesn't accept custom headers, so any
    // auth must be encoded into the URL — but this endpoint mirrors
    // /api/vtuber/models which is already unauthenticated, so a plain
    // URL is fine here too. Same-origin in the reverse-proxy setup.
    const url = `${base}/api/vtuber/models/stream`;
    let closed = false;
    let es: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;

    const connect = () => {
      if (closed) return;
      try {
        es = new EventSource(url);
      } catch (err) {
        console.warn('[VTuber] models stream EventSource construct failed:', err);
        scheduleReconnect();
        return;
      }
      es.onopen = () => {
        attempts = 0;
      };
      es.onmessage = (ev) => {
        // The backend only emits the `models_changed` event so we
        // don't bother parsing — every message is a refresh signal.
        try {
          onChange();
        } catch (err) {
          console.warn('[VTuber] models stream onChange handler threw:', err);
        }
        void ev;
      };
      es.onerror = () => {
        // EventSource's default reconnect doesn't back off, and on
        // some errors it stays in CLOSED forever. Manually back off.
        try {
          es?.close();
        } catch {
          // ignore
        }
        es = null;
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (closed) return;
      attempts = Math.min(attempts + 1, 8);
      const delay = Math.min(500 * 2 ** (attempts - 1), 10_000);
      reconnectTimer = setTimeout(connect, delay);
    };

    connect();

    return {
      close: () => {
        closed = true;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        try {
          es?.close();
        } catch {
          // ignore
        }
      },
    };
  },

  /**
   * Subscribe to model-ASSIGNMENT changes (session → model bindings). Emits the
   * exact change the moment any client (re)assigns, so web / connector / overlay
   * stay in sync without polling. Mirrors subscribeToModelChanges (unauth SSE).
   */
  subscribeToAssignmentChanges: (
    onChange: (sessionId: string, modelName: string | null) => void,
  ): { close: () => void } => {
    const base = getBackendUrl();
    const url = `${base}/api/vtuber/assignments/stream`;
    let closed = false;
    let es: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;

    const connect = () => {
      if (closed) return;
      try {
        es = new EventSource(url);
      } catch (err) {
        console.warn('[VTuber] assignments stream construct failed:', err);
        scheduleReconnect();
        return;
      }
      es.onopen = () => {
        attempts = 0;
      };
      es.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data) as {
            event?: string;
            session_id?: string;
            model_name?: string | null;
          };
          if (data.event === 'assignment_changed' && data.session_id) {
            onChange(data.session_id, data.model_name ?? null);
          }
        } catch (err) {
          console.warn('[VTuber] assignments stream parse failed:', err);
        }
      };
      es.onerror = () => {
        try {
          es?.close();
        } catch {
          // ignore
        }
        es = null;
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (closed) return;
      attempts = Math.min(attempts + 1, 8);
      const delay = Math.min(500 * 2 ** (attempts - 1), 10_000);
      reconnectTimer = setTimeout(connect, delay);
    };

    connect();

    return {
      close: () => {
        closed = true;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        try {
          es?.close();
        } catch {
          // ignore
        }
      },
    };
  },

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

  /** POST /api/vtuber/screen-observation/upload — V3 proactive
   *  screen-observation. Periodic frame from the user's screen-
   *  share stream + optional ``forceTrigger`` (bypass cooldown for
   *  the "Show Now" button). */
  uploadScreenObservation: async (params: {
    sessionId: string;
    blob: Blob;
    filename?: string;
    forceTrigger?: boolean;
    /** Perceptual hash (dHash hex) of this frame — lets the backend skip the
     *  vision call + trigger when the screen hasn't meaningfully changed. */
    frameHash?: string | null;
    /** Reaction cadence/sensitivity level: 'chatty' | 'balanced' | 'calm'. */
    talkativeness?: string | null;
  }): Promise<{
    observation_id: string;
    session_id: string;
    image_path: string | null;
    note_path: string | null;
    caption: string;
    vision_source: string;
    trigger_fired: boolean;
    skipped_reason: string | null;
  }> => {
    const form = new FormData();
    form.append('session_id', params.sessionId);
    form.append('file', params.blob, params.filename ?? 'screen.png');
    if (params.forceTrigger) form.append('force_trigger', 'true');
    if (params.frameHash) form.append('frame_hash', params.frameHash);
    if (params.talkativeness) form.append('talkativeness', params.talkativeness);
    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(
      '/api/vtuber/screen-observation/upload',
      { method: 'POST', headers, body: form },
    );
    if (!res.ok) {
      const body = await res.text();
      throw new Error(body || `HTTP ${res.status}`);
    }
    return res.json();
  },

  /** POST /api/vtuber/agents/{sessionId}/emotion — manual emotion override */
  setEmotion: (sessionId: string, emotion: string, intensity = 1.0, transitionMs = 300) =>
    apiCall<{ status: string; emotion: string; expression_index: number }>(
      `/api/vtuber/agents/${sessionId}/emotion`,
      { method: 'POST', body: JSON.stringify({ emotion, intensity, transition_ms: transitionMs }) },
    ),

  // ── Baked-imports inbox (geny-avatar integration, Phase C) ────
  // Pending zip files written by avatar-editor's "send to Geny" land
  // in a shared docker volume; backend exposes list/install/delete.

  /** GET /api/vtuber/baked-imports/list — pending zips in the inbox.
   *  Each entry is flagged `already_installed` so the modal can show
   *  "already in library" instead of a plain install button — under
   *  auto-publish, almost every zip in the inbox is already registered
   *  by the watcher. */
  listBakedImports: () =>
    apiCall<{
      inbox: string;
      exists: boolean;
      entries: Array<{
        filename: string;
        size_bytes: number;
        modified_iso: string;
        runtime: string | null;
        suggested_name: string | null;
        schema_version: number | null;
        puppet_id: string | null;
        already_installed: boolean;
        installed_display_name: string | null;
      }>;
    }>('/api/vtuber/baked-imports/list'),

  /** POST /api/vtuber/baked-imports/install — unpack + register a zip.
   *  When `replaceExisting` is true, prior `(Editor)` / `(Editor N)`
   *  registry entries with the same base display name are pruned
   *  before this install lands; the new entry then takes the clean
   *  `(Editor)` slot. The response's `replaced` array lists what was
   *  removed so the caller can surface it. */
  installBakedImport: (
    filename: string,
    displayNameOverride?: string,
    replaceExisting = false,
  ) =>
    apiCall<{
      status: string;
      warning?: string;
      model: Live2dModelInfo;
      replaced: Array<{ name: string; display_name: string }>;
    }>('/api/vtuber/baked-imports/install', {
      method: 'POST',
      body: JSON.stringify({
        filename,
        display_name_override: displayNameOverride,
        replace_existing: replaceExisting,
      }),
    }),

  /** DELETE /api/vtuber/baked-imports/{filename} — discard a pending zip. */
  deleteBakedImport: (filename: string) =>
    apiCall<{ status: string; deleted: string }>(
      `/api/vtuber/baked-imports/${encodeURIComponent(filename)}`,
      { method: 'DELETE' },
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
        ws = makeAuthedWs(wsUrl);
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
        // Auth failure: stop reconnecting and clear the dead token.
        if (!closed && ev.code === WS_UNAUTHORIZED_CODE) {
          console.warn(`${_tag} authentication failed (4401) — stopping reconnect, clearing token`);
          closed = true;
          handleAuthFailure();
          return;
        }
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

  /** POST /api/opsidian/files/batch-delete — drop N notes in one pass.
   *  Backs the sidebar multi-select UI. */
  batchDeleteFiles: (filenames: readonly string[]) =>
    apiCall<{
      requested: number;
      deleted: number;
      outcomes: Array<{ filename: string; deleted: boolean }>;
    }>('/api/opsidian/files/batch-delete', {
      method: 'POST',
      body: JSON.stringify({ filenames }),
    }),

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
      headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
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
      headers: withAuthHeaders({ 'Content-Type': 'application/json' }),
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

// ==================== Whiteboard API (Phase 0+) ====================
// Captures, attachments, and ViewLedger inspection. The endpoints live
// under /api/opsidian/* alongside the existing user-opsidian routes —
// see docs/knowledge-whiteboard/02_ARCHITECTURE.md.

export type WhiteboardCaptureType =
  | 'text'
  | 'image'
  | 'screenshot'
  | 'audio'
  | 'drawing'
  | 'link'
  | 'file'
  | 'code';

export interface WhiteboardCapturePayloadIn {
  inline_text?: string | null;
  attachment_path?: string | null;
  inline_base64?: string | null;
  ref_url?: string | null;
}

export interface WhiteboardCaptureCreatedResponse {
  capture_id: string;
  draft_note_filename: string;
  attachment_path: string | null;
  /** Set when ``auto_spotlight=true`` was sent on the upload — the
   *  resulting spotlight item id so the caller knows USER_SHARED
   *  was queued for this session. Absent on the default path. */
  spotlight_item_id?: string | null;
}

export interface WhiteboardCaptureLogEntry {
  capture_id: string;
  ts: string;
  username: string;
  session_id: string | null;
  type: WhiteboardCaptureType;
  source: string;
  draft_note: string;
  attachment_path: string | null;
  ref_url?: string | null;
  metadata?: Record<string, unknown>;
}

export interface WhiteboardViewStats {
  agent_id: string;
  username: string;
  total_notes_seen: number;
  events: Record<string, number>;
}

export interface KnowledgeDoc {
  filename: string | null;
  title: string;
  doc_id: string;
  status: 'processing' | 'ready' | 'failed' | string;
  source_type: string;
  source_ref: string;
  chunk_count: number;
  modified: string;
  /** Provider/model that embedded this document (recorded per doc). */
  embedding_provider?: string;
  embedding_model?: string;
  /** True when the doc's model ≠ the current embedding setting. */
  embedding_stale?: boolean;
  /** Clean human filename (Unicode preserved), for the download name. */
  original_filename?: string;
  /** Vault-relative path to the original bytes (_attachments/…). */
  attachment?: string;
}

export interface KnowledgeHit {
  score: number;
  text: string;
  doc_id: string;
  title: string;
  page: number | null;
  heading: string | null;
  source_type: string;
  filename: string;
}

export interface KnowledgeSourceRunReport {
  started_at: string;
  ok: boolean;
  fetched?: number;
  ingested?: number;
  unchanged?: number;
  failed?: number;
  error?: string;
}

export interface KnowledgeSource {
  id: string;
  name: string;
  type: 'api' | 'web' | 'db' | string;
  schedule: string;
  enabled: boolean;
  config: Record<string, unknown>;
  last_run_at?: string | null;
  last_result?: KnowledgeSourceRunReport | null;
}

/** Knowledge repository — documents in the user vault, qdrant-searchable. */
export const knowledgeApi = {
  status: () =>
    apiCall<{
      enabled: boolean;
      embedding_provider: string;
      embedding_model: string;
      embedding_dim: number;
      embedding_ready: boolean;
      collection: string;
    }>('/api/opsidian/knowledge/status'),

  /** Multipart upload — resolves once accepted (processing continues server-side). */
  upload: async (file: File) => {
    const form = new FormData();
    form.append('file', file, file.name);
    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch('/api/opsidian/knowledge/upload', {
      method: 'POST',
      headers,
      body: form,
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(body || `HTTP ${res.status}`);
    }
    return res.json() as Promise<{ accepted: boolean; filename: string }>;
  },

  listDocuments: () =>
    apiCall<{ documents: KnowledgeDoc[] }>('/api/opsidian/knowledge/documents'),

  deleteDocument: (docId: string) =>
    apiCall<{ deleted: string }>(
      `/api/opsidian/knowledge/documents/${encodeURIComponent(docId)}`,
      { method: 'DELETE' },
    ),

  /** Re-embed one document under the CURRENT embedding model. */
  reembedDocument: (docId: string) =>
    apiCall<{ accepted: boolean; doc_id: string }>(
      `/api/opsidian/knowledge/documents/${encodeURIComponent(docId)}/reembed`,
      { method: 'POST' },
    ),

  /** Re-embed every ready document whose recorded model is stale. */
  reembedStale: () =>
    apiCall<{ accepted: boolean; count: number }>(
      '/api/opsidian/knowledge/reembed',
      { method: 'POST' },
    ),

  /** Every stored chunk of a document, ordered, with page/heading. */
  documentChunks: (docId: string) =>
    apiCall<{
      doc_id: string;
      title: string;
      embedding_model: string;
      chunk_count: number;
      chunks: Array<{
        chunk_index: number;
        text: string;
        page: number | null;
        heading: string | null;
        sheet: string | null;
      }>;
    }>(`/api/opsidian/knowledge/documents/${encodeURIComponent(docId)}/chunks`),

  /** Reassembled full text of a document. */
  documentText: (docId: string) =>
    apiCall<{ doc_id: string; title: string; chunk_count: number; text: string }>(
      `/api/opsidian/knowledge/documents/${encodeURIComponent(docId)}/text`,
    ),

  search: (query: string, topK = 8) =>
    apiCall<{ hits: KnowledgeHit[]; total: number }>(
      '/api/opsidian/knowledge/search',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, top_k: topK }),
      },
    ),

  // ── continuous collection sources (api / web / db connectors) ──
  listSources: () =>
    apiCall<{ sources: KnowledgeSource[] }>('/api/opsidian/knowledge/sources'),

  saveSource: (source: Partial<KnowledgeSource> & { name: string; type: string }) =>
    apiCall<{ source: KnowledgeSource }>('/api/opsidian/knowledge/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(source),
    }),

  deleteSource: (sourceId: string) =>
    apiCall<{ deleted: string }>(
      `/api/opsidian/knowledge/sources/${encodeURIComponent(sourceId)}`,
      { method: 'DELETE' },
    ),

  runSource: (sourceId: string) =>
    apiCall<{ accepted: boolean; source_id: string }>(
      `/api/opsidian/knowledge/sources/${encodeURIComponent(sourceId)}/run`,
      { method: 'POST' },
    ),
};

export const whiteboardApi = {
  /** POST /api/opsidian/captures — JSON ingest (text/link/clipboard-text). */
  createCapture: (data: {
    type: WhiteboardCaptureType;
    source?: string;
    payload: WhiteboardCapturePayloadIn;
    metadata?: Record<string, unknown>;
    session_id?: string | null;
    title?: string | null;
    suggested_filename?: string | null;
  }) =>
    apiCall<WhiteboardCaptureCreatedResponse>('/api/opsidian/captures', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** POST /api/opsidian/captures/upload — multipart (binary attachment). */
  uploadCapture: async (params: {
    file: Blob;
    type: WhiteboardCaptureType;
    source?: string;
    title?: string | null;
    sessionId?: string | null;
    metadata?: Record<string, unknown>;
    inlineText?: string | null;
    filename?: string | null;
    /** V2 voice-notes — when true, the backend awaits the
     *  post-capture hook synchronously and immediately stages a
     *  spotlight item + USER_SHARED trigger for the resulting note.
     *  Used by the VTuber STT mode so each utterance reaches the
     *  persona without a separate Share-with-VTuber click. */
    autoSpotlight?: boolean;
  }): Promise<WhiteboardCaptureCreatedResponse> => {
    const form = new FormData();
    form.append('file', params.file, params.filename ?? 'capture.bin');
    form.append('type', params.type);
    form.append('source', params.source ?? 'manual');
    if (params.title) form.append('title', params.title);
    if (params.sessionId) form.append('session_id', params.sessionId);
    if (params.inlineText) form.append('inline_text', params.inlineText);
    if (params.metadata) form.append('metadata_json', JSON.stringify(params.metadata));
    if (params.autoSpotlight) form.append('auto_spotlight', 'true');

    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch('/api/opsidian/captures/upload', {
      method: 'POST',
      headers,
      body: form,
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(body || `HTTP ${res.status}`);
    }
    return res.json() as Promise<WhiteboardCaptureCreatedResponse>;
  },

  /** GET /api/opsidian/captures — recent capture audit log entries. */
  listRecentCaptures: (limit = 50) =>
    apiCall<{ captures: WhiteboardCaptureLogEntry[]; total: number }>(
      `/api/opsidian/captures?limit=${encodeURIComponent(String(limit))}`,
    ),

  /** Fully-qualified URL for an attachment — usable as <img src=...>. */
  attachmentUrl: (relativePath: string): string => {
    const cleaned = relativePath.replace(/^\/+/, '');
    const stripped = cleaned.startsWith('_attachments/') ? cleaned.slice('_attachments/'.length) : cleaned;
    return `/api/opsidian/attachments/${encodeURI(stripped)}`;
  },

  /** Download an attachment through an AUTHENTICATED fetch (so the Bearer
   *  token rides along — a plain <a download> can only send the cookie,
   *  which expires before the token) and save it under ``downloadName``. */
  downloadAttachment: async (relativePath: string, downloadName?: string): Promise<void> => {
    const cleaned = relativePath.replace(/^\/+/, '');
    const stripped = cleaned.startsWith('_attachments/')
      ? cleaned.slice('_attachments/'.length)
      : cleaned;
    let url = `/api/opsidian/attachments/${encodeURI(stripped)}`;
    if (downloadName) url += `?download=${encodeURIComponent(downloadName)}`;
    const token = getToken();
    const res = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = downloadName || stripped.replace(/^.*\//, '');
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objectUrl);
  },

  /** DELETE /api/opsidian/captures/{capture_id} — remove draft + attachment. */
  deleteCapture: (captureId: string) =>
    apiCall<{ capture_id: string; note_deleted: boolean; attachment_deleted: boolean }>(
      `/api/opsidian/captures/${encodeURIComponent(captureId)}`,
      { method: 'DELETE' },
    ),

  /** POST /api/opsidian/captures/batch-delete — drop N captures + their
   *  attachments in one pass. Backs the inbox multi-select UI. */
  batchDeleteCaptures: (captureIds: readonly string[]) =>
    apiCall<{
      requested: number;
      deleted: number;
      missing: string[];
      outcomes: Array<{
        capture_id: string;
        note_deleted: boolean;
        attachment_deleted: boolean;
        missing: boolean;
      }>;
    }>('/api/opsidian/captures/batch-delete', {
      method: 'POST',
      body: JSON.stringify({ capture_ids: captureIds }),
    }),

  /** GET /api/opsidian/views/stats — ViewLedger sanity check. */
  getViewStats: (agentId?: string) => {
    const qs = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : '';
    return apiCall<WhiteboardViewStats>(`/api/opsidian/views/stats${qs}`);
  },

  /** POST /api/opsidian/library — explicit Library share (no quality gate). */
  shareToLibrary: (data: {
    source_filename: string;
    note_kind?: 'user' | 'curated';
    extra_tags?: string[];
  }) =>
    apiCall<{ success: boolean; curated_filename: string; title: string; category: string }>(
      '/api/opsidian/library',
      {
        method: 'POST',
        body: JSON.stringify(data),
      },
    ),

  /** POST /api/opsidian/spotlight — Spotlight-mode share. */
  shareToSpotlight: (data: {
    source_filename: string;
    session_id?: string | null;
    title?: string | null;
    excerpt?: string | null;
    note_kind?: 'user' | 'curated';
    ttl_minutes?: number;
    pinned?: boolean;
  }) =>
    apiCall<{ item: Record<string, unknown> }>(
      '/api/opsidian/spotlight',
      {
        method: 'POST',
        body: JSON.stringify(data),
      },
    ),

  /** POST /api/opsidian/organizer/run — fire the organizer once. */
  organizerRun: (strategies?: string[]) =>
    apiCall<{ total: number; suggestions: WhiteboardOrganizerSuggestion[] }>(
      '/api/opsidian/organizer/run',
      {
        method: 'POST',
        body: JSON.stringify({ strategies: strategies ?? null }),
      },
    ),

  /** GET /api/opsidian/organizer/suggestions — active list. */
  organizerList: () =>
    apiCall<{ total: number; suggestions: WhiteboardOrganizerSuggestion[] }>(
      '/api/opsidian/organizer/suggestions',
    ),

  /** POST /api/opsidian/organizer/suggestions/{id}/accept */
  organizerAccept: (suggestionId: string, cooldownDays = 30) =>
    apiCall<{ suggestion: WhiteboardOrganizerSuggestion }>(
      `/api/opsidian/organizer/suggestions/${encodeURIComponent(suggestionId)}/accept`,
      {
        method: 'POST',
        body: JSON.stringify({ cooldown_days: cooldownDays }),
      },
    ),

  /** POST /api/opsidian/organizer/suggestions/{id}/reject */
  organizerReject: (suggestionId: string, cooldownDays = 30) =>
    apiCall<{ suggestion: WhiteboardOrganizerSuggestion }>(
      `/api/opsidian/organizer/suggestions/${encodeURIComponent(suggestionId)}/reject`,
      {
        method: 'POST',
        body: JSON.stringify({ cooldown_days: cooldownDays }),
      },
    ),
};

export interface WhiteboardOrganizerSuggestion {
  suggestion_id: string;
  kind: 'cluster' | 'duplicate' | 'topic_promotion' | 'stale_unseen' | string;
  note_filenames: string[];
  proposed_label: string;
  proposed_action: 'group' | 'merge' | 'promote_to_library' | 'archive' | 'tag' | string;
  confidence: number;
  rationale: string;
  strategy_name: string;
  status: 'active' | 'accepted' | 'rejected' | 'snoozed' | string;
  created_at: string;
  decided_at: string | null;
  cooldown_until: string | null;
  extra: Record<string, unknown>;
}

// ==================== Sandbox Tool Packs API ====================
//
// A pack = an independent GAPT environment (workspace restorable from a
// snapshot) + the tools whose code runs inside it + the skills documenting
// them. Agents author + save packs from chat (env save_pack); this surface
// lists/inspects them, gates them (enabled), and deletes them.

export interface SandboxToolPackSummary {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  tool_count: number;
  skill_count: number;
  workspace_ref: string;
  snapshot_ref: string;
  project_ref: string;
}

export interface SandboxToolSpecDTO {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  runtime: string;
  entrypoint: string;
  argv: string[];
  timeout_s: number;
  workdir: string;
  network_egress: boolean;
  read_only: boolean;
}

export interface PackSkillDTO {
  id: string;
  description: string;
  body: string;
  allowed_tools: string[];
}

export interface SandboxToolPackDetail extends SandboxToolPackSummary {
  tools: SandboxToolSpecDTO[];
  skills: PackSkillDTO[];
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

// Activity = the agent's chat + tool trail captured in a snapshot (ground truth
// of what happened in the sandbox). Diff = the unified diff the snapshot added.
export interface SnapshotToolUse {
  tool: string;
  input?: string | null;
  output?: string | null;
  is_error?: boolean;
}
export interface SnapshotTurn {
  user?: string;
  assistant?: string;
  cost_usd?: number;
  tool_uses?: SnapshotToolUse[];
}
export interface SnapshotActivity {
  turns?: SnapshotTurn[];
  total_cost_usd?: number;
}
export interface SnapshotActivityResponse {
  snapshot_ref?: string;
  snapshot_id?: string;
  activity?: SnapshotActivity;
  stats?: Record<string, unknown>;
}
export interface SnapshotDiffResponse {
  snapshot_ref?: string;
  unified?: string;
  truncated?: boolean;
  stats?: Record<string, unknown>;
}

export const sandboxToolPacksApi = {
  list: () =>
    apiCall<{ packs: SandboxToolPackSummary[] }>('/api/sandbox-tool-packs'),
  get: (packId: string) =>
    apiCall<SandboxToolPackDetail>(
      `/api/sandbox-tool-packs/${encodeURIComponent(packId)}`,
    ),
  setEnabled: (packId: string, enabled: boolean) =>
    apiCall<SandboxToolPackSummary>(
      `/api/sandbox-tool-packs/${encodeURIComponent(packId)}/enabled`,
      { method: 'PATCH', body: JSON.stringify({ enabled }) },
    ),
  remove: (packId: string) =>
    apiCall<{ ok: boolean; pack_id: string }>(
      `/api/sandbox-tool-packs/${encodeURIComponent(packId)}`,
      { method: 'DELETE' },
    ),
  activity: (packId: string) =>
    apiCall<SnapshotActivityResponse>(
      `/api/sandbox-tool-packs/${encodeURIComponent(packId)}/activity`,
    ),
  diff: (packId: string) =>
    apiCall<SnapshotDiffResponse>(
      `/api/sandbox-tool-packs/${encodeURIComponent(packId)}/diff`,
    ),
};

// ==================== Persona Presets (persona builder) ====================

export interface PersonaPresetSummary {
  id: string;
  name: string;
  description: string;
  mbti: string;
  enneagram: string;
  archetype: string;
  is_template: boolean;
}

export interface OceanTraits {
  openness: number;
  conscientiousness: number;
  extraversion: number;
  agreeableness: number;
  neuroticism: number;
}
export interface StyleTraits {
  warmth: number;
  humor: number;
  playfulness: number;
  formality: number;
  assertiveness: number;
  verbosity: number;
  emoji: number;
  enthusiasm: number;
  directness: number;
}
export interface SpeechStyle {
  honorific: string;
  self_reference: string;
  catchphrases: string[];
  verbal_tics: string[];
}
export interface EmotionDefaults {
  default_mood: string;
  expressiveness: number;
  preferred_tags: string[];
}
export interface PersonaIdentity {
  display_name: string;
  age_vibe: string;
  role: string;
  interests: string[];
  backstory: string;
}
export interface PersonaPresetDefinition {
  id?: string;
  name: string;
  description: string;
  mbti: string;
  enneagram: string;
  archetype: string;
  ocean: OceanTraits;
  style: StyleTraits;
  speech: SpeechStyle;
  emotion: EmotionDefaults;
  identity: PersonaIdentity;
  prompt_override: string;
  is_template?: boolean;
  compiled_prompt?: string;
}

export interface PersonaFrameworks {
  mbti: { code: string; label_ko: string }[];
  enneagram: { code: string; label_ko: string }[];
  archetypes: { code: string; label_ko: string }[];
  ocean_axes: { key: string; label_ko: string; label_en: string; low: string; high: string }[];
  style_axes: { key: string; label_ko: string; label_en: string; low: string; high: string }[];
  honorifics: { code: string; label_ko: string }[];
  emotion_tags: string[];
}

export const personaPresetsApi = {
  list: () =>
    apiCall<{ presets: PersonaPresetSummary[] }>('/api/persona-presets'),
  frameworks: () => apiCall<PersonaFrameworks>('/api/persona-presets/frameworks'),
  get: (id: string) =>
    apiCall<PersonaPresetDefinition>(
      `/api/persona-presets/${encodeURIComponent(id)}`,
    ),
  compile: (defn: PersonaPresetDefinition) =>
    apiCall<{ compiled_prompt: string; char_count: number }>(
      '/api/persona-presets/compile',
      { method: 'POST', body: JSON.stringify(defn) },
    ),
  create: (defn: PersonaPresetDefinition) =>
    apiCall<PersonaPresetDefinition>('/api/persona-presets', {
      method: 'POST',
      body: JSON.stringify(defn),
    }),
  update: (id: string, defn: PersonaPresetDefinition) =>
    apiCall<PersonaPresetDefinition>(
      `/api/persona-presets/${encodeURIComponent(id)}`,
      { method: 'PUT', body: JSON.stringify(defn) },
    ),
  remove: (id: string) =>
    apiCall<{ ok: boolean; id: string }>(
      `/api/persona-presets/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    ),
};

// ==================== Sandbox Logs (observability) ====================

export interface SandboxSummary {
  id: string;
  name: string | null;
  status: string | null;
  snapshot_count: number;
}
export interface SnapshotSummary {
  id: string;
  kind: string;
  label: string;
  created_at: string | null;
  stats: Record<string, unknown>;
  summary: { turns: number; tool_calls: number };
}

export const sandboxLogsApi = {
  list: () => apiCall<{ sandboxes: SandboxSummary[] }>('/api/sandboxes'),
  snapshots: (workspaceId: string) =>
    apiCall<{ workspace_id: string; snapshots: SnapshotSummary[] }>(
      `/api/sandboxes/${encodeURIComponent(workspaceId)}/snapshots`,
    ),
  snapshot: (snapshotId: string) =>
    apiCall<SnapshotActivityResponse>(
      `/api/sandboxes/snapshots/${encodeURIComponent(snapshotId)}`,
    ),
  diff: (snapshotId: string) =>
    apiCall<SnapshotDiffResponse>(
      `/api/sandboxes/snapshots/${encodeURIComponent(snapshotId)}/diff`,
    ),
};
