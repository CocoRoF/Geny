/**
 * Tool Preset & Catalog API
 */

import type {
  ToolPresetDefinition,
  ToolPresetListResponse,
  ToolCatalogResponse,
  ToolInfo,
  MCPServerInfo,
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
      const raw = json.detail || json.message || json.error;
      message = typeof raw === 'string' ? raw : raw ? JSON.stringify(raw) : `HTTP ${res.status}`;
    } catch {
      message = body || `HTTP ${res.status}`;
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

// ==================== Tool Preset API ====================

export const toolPresetApi = {
  list: () => apiCall<ToolPresetListResponse>('/api/tool-presets/'),

  listTemplates: () => apiCall<ToolPresetListResponse>('/api/tool-presets/templates'),

  get: (id: string) => apiCall<ToolPresetDefinition>(`/api/tool-presets/${id}`),

  create: (data: { name: string; description?: string; icon?: string; custom_tools?: string[]; mcp_servers?: string[] }) =>
    apiCall<ToolPresetDefinition>('/api/tool-presets/', { method: 'POST', body: JSON.stringify(data) }),

  update: (id: string, data: Partial<Pick<ToolPresetDefinition, 'name' | 'description' | 'icon' | 'custom_tools' | 'mcp_servers'>>) =>
    apiCall<ToolPresetDefinition>(`/api/tool-presets/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  delete: (id: string) =>
    apiCall<{ success: boolean }>(`/api/tool-presets/${id}`, { method: 'DELETE' }),

  clone: (id: string, newName: string) =>
    apiCall<ToolPresetDefinition>(`/api/tool-presets/${id}/clone`, { method: 'POST', body: JSON.stringify({ new_name: newName }) }),
};

// ==================== Tool Catalog API ====================

export const toolCatalogApi = {
  catalog: () => apiCall<ToolCatalogResponse>('/api/tools/catalog'),

  builtIn: () => apiCall<ToolInfo[]>('/api/tools/catalog/built-in'),

  custom: () => apiCall<ToolInfo[]>('/api/tools/catalog/custom'),

  mcpServers: () => apiCall<MCPServerInfo[]>('/api/tools/catalog/mcp-servers'),
};
