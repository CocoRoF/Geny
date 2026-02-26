/**
 * Workflow API Client
 */

import type {
  WfNodeCatalog,
  WorkflowDefinition,
  WorkflowListResponse,
  WorkflowValidateResponse,
  WorkflowExecuteResponse,
  CompileViewResponse,
} from '@/types/workflow';

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

export const workflowApi = {
  /** GET /api/workflows/nodes — node type catalog */
  getNodeCatalog: () =>
    apiCall<WfNodeCatalog>('/api/workflows/nodes'),

  /** GET /api/workflows — list all workflows */
  list: () =>
    apiCall<WorkflowListResponse>('/api/workflows'),

  /** POST /api/workflows — create workflow */
  create: (data: { name: string; description?: string; nodes?: unknown[]; edges?: unknown[] }) =>
    apiCall<WorkflowDefinition>('/api/workflows', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** GET /api/workflows/:id — get workflow */
  get: (id: string) =>
    apiCall<WorkflowDefinition>(`/api/workflows/${id}`),

  /** PUT /api/workflows/:id — update workflow */
  update: (id: string, data: Record<string, unknown>) =>
    apiCall<WorkflowDefinition>(`/api/workflows/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  /** DELETE /api/workflows/:id */
  delete: (id: string) =>
    apiCall<{ success: boolean }>(`/api/workflows/${id}`, { method: 'DELETE' }),

  /** POST /api/workflows/:id/clone */
  clone: (id: string) =>
    apiCall<WorkflowDefinition>(`/api/workflows/${id}/clone`, { method: 'POST' }),

  /** GET /api/workflows/templates */
  listTemplates: () =>
    apiCall<{ templates: WorkflowDefinition[]; total: number }>('/api/workflows/templates'),

  /** POST /api/workflows/:id/validate */
  validate: (id: string) =>
    apiCall<WorkflowValidateResponse>(`/api/workflows/${id}/validate`, { method: 'POST' }),

  /** POST /api/workflows/:id/compile-view */
  compileView: (id: string) =>
    apiCall<CompileViewResponse>(`/api/workflows/${id}/compile-view`, { method: 'POST' }),

  /** POST /api/workflows/:id/execute */
  execute: (id: string, data: { session_id: string; input_text: string; max_iterations?: number }) =>
    apiCall<WorkflowExecuteResponse>(`/api/workflows/${id}/execute`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};
