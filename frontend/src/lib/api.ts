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
  // Fallback: same hostname as the browser page, backend port from env (local dev)
  const port = process.env.NEXT_PUBLIC_BACKEND_PORT || '8000';
  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:${port}`;
  }
  return `http://localhost:${port}`;
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

  /** POST /api/agents/{id}/pet — pet the agent (increases affection) */
  pet: (id: string) =>
    apiCall<{ success: boolean; session_id: string; affection: number; message: string }>(
      `/api/sessions/${id}/pet`,
      { method: 'POST' },
    ),

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
        evtSource.addEventListener('heartbeat', (e) => {
          reconnectAttempts = 0; // connection alive
          try { onEvent('heartbeat', JSON.parse((e as MessageEvent).data)); } catch { /* skip */ }
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
    apiCall<{ active: boolean; done?: boolean; has_error?: boolean; session_id: string; elapsed_ms?: number; last_activity_ms?: number; last_event_level?: string; last_tool_name?: string }>(
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
      evtSource.addEventListener('heartbeat', (e) => {
        retries = 0;
        try { onEvent('heartbeat', JSON.parse((e as MessageEvent).data)); } catch { /* skip */ }
      });
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
   * Subscribe to avatar state SSE events.
   * Connects directly to backend (bypasses Next.js proxy buffering).
   */
  subscribeToAvatarState: (
    sessionId: string,
    onState: (state: AvatarState) => void,
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
      evtSource = new EventSource(`${backendUrl}/api/vtuber/agents/${sessionId}/events`);

      evtSource.addEventListener('avatar_state', (e) => {
        retries = 0;
        try { onState(JSON.parse(e.data) as AvatarState); } catch { /* skip */ }
      });

      evtSource.addEventListener('heartbeat', () => {
        retries = 0;
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
};
