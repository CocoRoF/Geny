/**
 * API Communication Layer
 * Mirrors all legacy frontend-legacy/static/components/api.js endpoints
 */

// ==================== Base Fetch Wrapper ====================

async function apiCall<T = unknown>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(endpoint, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
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
// Next.js rewrites() proxy buffers ALL responses (including SSE streams),
// so EventSource must connect directly to the backend, bypassing the proxy.
// In production behind a reverse proxy (nginx), NEXT_PUBLIC_API_URL should be
// set to '' (empty) so that the browser uses relative paths through nginx.
function getBackendUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  // Explicitly set (including empty string '' for reverse-proxy setups)
  if (envUrl !== undefined) return envUrl;
  // Fallback: same hostname as the browser page, port 8000 (local dev)
  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return 'http://localhost:8000';
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
   * Two-step SSE streaming execute.
   *
   * Step 1: POST /api/agents/{id}/execute/start — starts execution in background.
   * Step 2: GET  /api/agents/{id}/execute/events — EventSource SSE stream.
   *
   * Uses native EventSource (GET-based SSE) which bypasses Next.js proxy
   * buffering that affects POST-based streams.
   */
  executeStream: async (
    id: string,
    data: ExecuteRequest,
    onEvent: (eventType: string, eventData: Record<string, unknown>) => void,
  ): Promise<void> => {
    // Step 1: start execution (returns immediately)
    const startRes = await fetch(`/api/agents/${id}/execute/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });

    if (!startRes.ok) {
      const body = await startRes.text();
      let message: string;
      try {
        const json = JSON.parse(body);
        const raw = json.detail || json.message || json.error;
        message = typeof raw === 'string' ? raw : raw ? JSON.stringify(raw) : `HTTP ${startRes.status}`;
      } catch {
        message = body || `HTTP ${startRes.status}`;
      }
      throw new Error(message);
    }

    // Step 2: connect EventSource DIRECTLY to backend (bypass Next.js proxy buffering)
    // Supports auto-reconnection: if the SSE connection drops while execution is
    // still running, reconnect to /execute/events (the holder persists on backend).
    return new Promise<void>((resolve) => {
      const backendUrl = getBackendUrl();
      let evtSource: EventSource | null = null;
      let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
      let done = false;
      const MAX_RECONNECT_ATTEMPTS = 20;
      const RECONNECT_DELAY = 3_000;
      let reconnectAttempts = 0;

      const cleanup = () => {
        done = true;
        if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
        evtSource?.close();
        evtSource = null;
      };

      const connect = () => {
        if (done) return;
        evtSource = new EventSource(`${backendUrl}/api/agents/${id}/execute/events`);

        evtSource.addEventListener('log', (e) => {
          reconnectAttempts = 0;
          try { onEvent('log', JSON.parse(e.data)); } catch { /* skip */ }
        });
        evtSource.addEventListener('status', (e) => {
          reconnectAttempts = 0;
          try { onEvent('status', JSON.parse(e.data)); } catch { /* skip */ }
        });
        evtSource.addEventListener('result', (e) => {
          reconnectAttempts = 0;
          try { onEvent('result', JSON.parse(e.data)); } catch { /* skip */ }
        });
        evtSource.addEventListener('heartbeat', () => {
          reconnectAttempts = 0; // connection alive
        });
        evtSource.addEventListener('error', (e) => {
          // SSE error event — could be connection error or custom error event
          if (e instanceof MessageEvent && e.data) {
            try { onEvent('error', JSON.parse(e.data)); } catch { /* skip */ }
          }
        });
        evtSource.addEventListener('done', () => {
          onEvent('done', {});
          cleanup();
          resolve();
        });

        // Handle connection errors — reconnect instead of giving up
        evtSource.onerror = () => {
          if (done) return;
          evtSource?.close();
          evtSource = null;

          if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            // Exhausted retries — give up
            cleanup();
            resolve();
            return;
          }
          reconnectAttempts++;
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY);
        };
      };

      connect();
    });
  },

  /** POST /api/agents/{id}/stop — stop execution */
  stop: (id: string) =>
    apiCall<{ success: boolean }>(`/api/agents/${id}/stop`, {
      method: 'POST',
    }),

  /** GET /api/agents/{id}/execute/status — check if execution is active */
  getExecutionStatus: (id: string) =>
    apiCall<{ active: boolean; done?: boolean; has_error?: boolean; session_id: string }>(
      `/api/agents/${id}/execute/status`,
    ),

  /**
   * Reconnect to a running execution's SSE stream.
   *
   * Used when the page reloads or the user returns after locking the phone.
   * If an execution is still active on the backend, this streams events
   * from where the backend currently is via GET /execute/events.
   */
  reconnectStream: (
    id: string,
    onEvent: (eventType: string, eventData: Record<string, unknown>) => void,
  ): { close: () => void } => {
    let evtSource: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;
    const RECONNECT_DELAY = 3_000;
    const MAX_RETRIES = 10;
    let retries = 0;

    const connect = () => {
      if (closed) return;
      const backendUrl = getBackendUrl();
      evtSource = new EventSource(`${backendUrl}/api/agents/${id}/execute/events`);

      evtSource.addEventListener('log', (e) => {
        retries = 0;
        try { onEvent('log', JSON.parse(e.data)); } catch { /* skip */ }
      });
      evtSource.addEventListener('status', (e) => {
        retries = 0;
        try { onEvent('status', JSON.parse(e.data)); } catch { /* skip */ }
      });
      evtSource.addEventListener('result', (e) => {
        retries = 0;
        try { onEvent('result', JSON.parse(e.data)); } catch { /* skip */ }
      });
      evtSource.addEventListener('heartbeat', () => { retries = 0; });
      evtSource.addEventListener('error', (e) => {
        if (e instanceof MessageEvent && e.data) {
          try { onEvent('error', JSON.parse(e.data)); } catch { /* skip */ }
        }
      });
      evtSource.addEventListener('done', () => {
        onEvent('done', {});
        closed = true;
        evtSource?.close();
        evtSource = null;
      });

      evtSource.onerror = () => {
        if (closed) return;
        evtSource?.close();
        evtSource = null;
        if (retries >= MAX_RETRIES) {
          closed = true;
          return;
        }
        retries++;
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY);
      };
    };

    connect();
    return {
      close: () => {
        closed = true;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        evtSource?.close();
        evtSource = null;
      },
    };
  },

  /** GET /api/agents/{id}/graph — graph structure */
  getGraph: (id: string) => apiCall<GraphStructure>(`/api/agents/${id}/graph`),

  /** GET /api/agents/{id}/workflow — workflow definition for the session */
  getWorkflow: (id: string) =>
    apiCall<import('@/types/workflow').WorkflowDefinition>(`/api/agents/${id}/workflow`),

  /** PUT /api/agents/{id}/system-prompt — update system prompt */
  updateSystemPrompt: (id: string, systemPrompt: string | null) =>
    apiCall<{ success: boolean; length: number }>(`/api/agents/${id}/system-prompt`, {
      method: 'PUT',
      body: JSON.stringify({ system_prompt: systemPrompt }),
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
    const res = await fetch(`/api/shared-folder/upload?${params}`, {
      method: 'POST',
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

  /** GET /api/chat/rooms/:id/messages — get room message history */
  getRoomMessages: (roomId: string) =>
    apiCall<ChatRoomMessageListResponse>(`/api/chat/rooms/${roomId}/messages`),

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

  /**
   * Subscribe to SSE events for a chat room.
   *
   * Connects directly to the backend to avoid Next.js proxy buffering.
   * Reconnects automatically with the latest message cursor on failure.
   */
  subscribeToRoom: (
    roomId: string,
    afterId: string | null,
    onEvent: (eventType: string, eventData: Record<string, unknown>) => void,
    getLatestMsgId?: () => string | null,
  ): { close: () => void } => {
    let evtSource: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const RECONNECT_DELAY = 3_000;

    const getUrl = () => {
      const currentAfter = getLatestMsgId?.() ?? afterId;
      const qs = currentAfter ? `?after=${encodeURIComponent(currentAfter)}` : '';
      return `${getBackendUrl()}/api/chat/rooms/${roomId}/events${qs}`;
    };

    const connect = () => {
      if (closed) return;

      const url = getUrl();
      evtSource = new EventSource(url);

      const handleEvent = (e: MessageEvent) => {
        try {
          onEvent(e.type, JSON.parse(e.data));
        } catch { /* skip malformed */ }
      };

      evtSource.addEventListener('message', handleEvent);
      evtSource.addEventListener('broadcast_status', handleEvent);
      evtSource.addEventListener('broadcast_done', handleEvent);
      evtSource.addEventListener('agent_progress', handleEvent);
      evtSource.addEventListener('heartbeat', handleEvent);

      evtSource.onerror = () => {
        if (closed) return;
        evtSource?.close();
        evtSource = null;
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (closed || reconnectTimer) return;
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, RECONNECT_DELAY);
    };

    connect();

    return {
      close: () => {
        closed = true;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        evtSource?.close();
        evtSource = null;
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
