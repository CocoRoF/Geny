/**
 * Environment & Catalog API client.
 *
 * Wraps the Geny backend's `/api/environments/*` (Phase 3 controller)
 * and `/api/catalog/*` (Phase 3 catalog) endpoints. Mirrors the
 * `geny-executor-web` client shape so Builder/Environment-tab
 * components can be ported with minimal call-site churn.
 */

import { getToken } from '@/lib/authApi';
import type {
  CatalogResponse,
  CreateEnvironmentPayload,
  EnvironmentDetail,
  EnvironmentDiffResult,
  EnvironmentManifest,
  EnvironmentSessionCountsResponse,
  EnvironmentSessionsResponse,
  EnvironmentSummary,
  StageArtifactList,
  StageIntrospection,
  StageSummary,
  UpdateEnvironmentPayload,
  UpdateStageTemplatePayload,
} from '@/types/environment';

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
  // 204 / empty body → return undefined as T
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

// ==================== Environments ====================

export const environmentApi = {
  list: async (): Promise<EnvironmentSummary[]> => {
    const res = await apiCall<{ environments: EnvironmentSummary[] }>('/api/environments');
    return res.environments;
  },

  get: (envId: string) => apiCall<EnvironmentDetail>(`/api/environments/${envId}`),

  create: (payload: CreateEnvironmentPayload) =>
    apiCall<{ id: string }>('/api/environments', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  update: (envId: string, changes: UpdateEnvironmentPayload) =>
    apiCall<EnvironmentDetail>(`/api/environments/${envId}`, {
      method: 'PUT',
      body: JSON.stringify(changes),
    }),

  delete: (envId: string) =>
    apiCall<void>(`/api/environments/${envId}`, { method: 'DELETE' }),

  duplicate: (envId: string, newName: string) =>
    apiCall<{ id: string }>(`/api/environments/${envId}/duplicate`, {
      method: 'POST',
      body: JSON.stringify({ new_name: newName }),
    }),

  replaceManifest: (envId: string, manifest: EnvironmentManifest) =>
    apiCall<EnvironmentDetail>(`/api/environments/${envId}/manifest`, {
      method: 'PUT',
      body: JSON.stringify({ manifest }),
    }),

  updateStage: (envId: string, order: number, payload: UpdateStageTemplatePayload) =>
    apiCall<EnvironmentDetail>(
      `/api/environments/${envId}/stages/${order}`,
      { method: 'PATCH', body: JSON.stringify(payload) },
    ),

  exportEnv: (envId: string) => apiCall<string>(`/api/environments/${envId}/export`),

  importEnv: (data: Record<string, unknown>) =>
    apiCall<{ id: string }>('/api/environments/import', {
      method: 'POST',
      body: JSON.stringify({ data }),
    }),

  diff: (envIdA: string, envIdB: string) =>
    apiCall<EnvironmentDiffResult>('/api/environments/diff', {
      method: 'POST',
      body: JSON.stringify({ env_id_a: envIdA, env_id_b: envIdB }),
    }),

  markPreset: (envId: string) =>
    apiCall<void>(`/api/environments/${envId}/preset`, { method: 'POST' }),

  unmarkPreset: (envId: string) =>
    apiCall<void>(`/api/environments/${envId}/preset`, { method: 'DELETE' }),

  linkedSessions: (envId: string, includeDeleted = false) =>
    apiCall<EnvironmentSessionsResponse>(
      `/api/environments/${envId}/sessions?include_deleted=${includeDeleted ? 'true' : 'false'}`,
    ),

  sessionCounts: () =>
    apiCall<EnvironmentSessionCountsResponse>('/api/environments/session-counts'),
};

// ==================== Catalog ====================
//
// Endpoints mirror `backend/controller/catalog_controller.py` exactly:
//   GET /api/catalog/full
//   GET /api/catalog/stages
//   GET /api/catalog/stages/{order}                 — StageIntrospection
//   GET /api/catalog/stages/{order}/artifacts       — StageArtifactList
//   GET /api/catalog/stages/{order}/artifacts/{name} — StageIntrospection

export const catalogApi = {
  full: () => apiCall<CatalogResponse>('/api/catalog/full'),

  stages: async (): Promise<StageSummary[]> => {
    const res = await apiCall<{ stages: StageSummary[] }>('/api/catalog/stages');
    return res.stages;
  },

  stage: (order: number) =>
    apiCall<StageIntrospection>(`/api/catalog/stages/${order}`),

  listArtifacts: (order: number) =>
    apiCall<StageArtifactList>(`/api/catalog/stages/${order}/artifacts`),

  artifactByStage: (order: number, name: string) =>
    apiCall<StageIntrospection>(
      `/api/catalog/stages/${order}/artifacts/${encodeURIComponent(name)}`,
    ),
};
