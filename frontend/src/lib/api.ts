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

// ==================== Agent API ====================

import type {
  SessionInfo,
  CreateAgentRequest,
  ExecuteRequest,
  ExecuteResponse,
  GraphStructure,
  ManagerDashboard,
  StorageListResponse,
  StorageFileContent,
  ChatBroadcastRequest,
  ChatBroadcastResponse,
} from '@/types';

export const agentApi = {
  /** GET /api/agents — list all sessions */
  list: () => apiCall<SessionInfo[]>('/api/agents'),

  /** GET /api/agents/store/deleted — list deleted sessions */
  listDeleted: () => apiCall<SessionInfo[]>('/api/agents/store/deleted'),

  /** GET /api/agents/managers — list manager sessions */
  listManagers: () => apiCall<SessionInfo[]>('/api/agents/managers'),

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

  /** POST /api/agents/{id}/stop — stop execution */
  stop: (id: string) =>
    apiCall<{ success: boolean }>(`/api/agents/${id}/stop`, {
      method: 'POST',
    }),

  /** GET /api/agents/{id}/dashboard — manager dashboard */
  getDashboard: (id: string) => apiCall<ManagerDashboard>(`/api/agents/${id}/dashboard`),

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
  getLogs: (id: string, limit = 200, level?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
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
  /** POST /api/chat/broadcast — broadcast message to all sessions */
  broadcast: (data: ChatBroadcastRequest) =>
    apiCall<ChatBroadcastResponse>('/api/chat/broadcast', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};
