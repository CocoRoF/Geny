/**
 * Tool Preset API Client
 */

import type {
  ToolPreset,
  ToolPresetListResponse,
  AvailableToolsResponse,
} from '@/types';

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
      message = json.detail || json.message || json.error || `HTTP ${res.status}`;
    } catch {
      message = body || `HTTP ${res.status}`;
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export const toolPresetApi = {
  /** GET /api/tool-presets — list all tool presets */
  list: () =>
    apiCall<ToolPresetListResponse>('/api/tool-presets'),

  /** GET /api/tool-presets/templates — list only templates */
  listTemplates: () =>
    apiCall<{ templates: ToolPreset[]; total: number }>('/api/tool-presets/templates'),

  /** POST /api/tool-presets — create a new tool preset */
  create: (data: { name: string; description?: string; allowed_servers?: string[]; allowed_tools?: string[] }) =>
    apiCall<ToolPreset>('/api/tool-presets', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** GET /api/tool-presets/:id — get a tool preset */
  get: (id: string) =>
    apiCall<ToolPreset>(`/api/tool-presets/${id}`),

  /** PUT /api/tool-presets/:id — update a tool preset */
  update: (id: string, data: { name?: string; description?: string; allowed_servers?: string[]; allowed_tools?: string[] }) =>
    apiCall<ToolPreset>(`/api/tool-presets/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  /** DELETE /api/tool-presets/:id */
  delete: (id: string) =>
    apiCall<{ success: boolean }>(`/api/tool-presets/${id}`, { method: 'DELETE' }),

  /** POST /api/tool-presets/:id/clone */
  clone: (id: string) =>
    apiCall<ToolPreset>(`/api/tool-presets/${id}/clone`, { method: 'POST' }),

  /** GET /api/tools/available — list available MCP servers and tools */
  listAvailable: () =>
    apiCall<AvailableToolsResponse>('/api/tools/available'),

  /** GET /api/tools/session/:id — get tools for a specific session */
  getSessionTools: (sessionId: string) =>
    apiCall<{ session_id: string; tool_preset_id: string | null; tool_preset_name: string | null; active_servers: string[] }>(
      `/api/tools/session/${sessionId}`,
    ),
};
