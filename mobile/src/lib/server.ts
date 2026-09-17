/**
 * Talking to a Geny server from a phone.
 *
 * Native fetch, so there is no CORS to negotiate — the app is not a browser
 * page and the server does not have to know it exists. The base URL and the
 * token are the only state; both live in secure storage.
 *
 * A 401 clears the token and tells the app, once. A phone that keeps a dead
 * token renders empty lists forever and says "signed in" above them.
 */

export class ServerError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'ServerError';
  }
}

export interface Credentials {
  baseUrl: string;
  token: string | null;
}

export type OnUnauthorized = () => void;

let onUnauthorized: OnUnauthorized = () => undefined;

export function setUnauthorizedHandler(handler: OnUnauthorized): void {
  onUnauthorized = handler;
}

export function normalizeBaseUrl(raw: string): string {
  const trimmed = (raw || '').trim().replace(/\/+$/, '');
  if (!trimmed) return '';
  // A bare host is what people type. Assume https — a server reachable from a
  // phone is on the internet, and downgrading silently would be worse than a
  // connection error the user can read.
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

export function toWsBase(httpBase: string): string {
  return normalizeBaseUrl(httpBase).replace(/^http/i, 'ws');
}

export async function request<T>(
  creds: Credentials,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const base = normalizeBaseUrl(creds.baseUrl);
  if (!base) throw new ServerError('서버 주소를 먼저 입력하세요', 0);
  const res = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(creds.token ? { Authorization: `Bearer ${creds.token}` } : {}),
      ...(init.headers as Record<string, string> | undefined),
    },
  });
  if (res.status === 401) {
    onUnauthorized();
    throw new ServerError('로그인이 만료됐습니다 — 다시 로그인하세요', 401);
  }
  if (!res.ok) {
    const body = await res.text();
    let message = `HTTP ${res.status}`;
    try {
      const parsed = JSON.parse(body);
      if (typeof parsed?.detail === 'string') message = parsed.detail;
    } catch {
      if (body && !body.trimStart().startsWith('<')) message = body.slice(0, 300);
    }
    throw new ServerError(message, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ── auth ─────────────────────────────────────────────────────────────

export interface AuthStatus {
  has_users: boolean;
  is_authenticated: boolean;
  username?: string | null;
  display_name?: string | null;
}

export interface TokenResponse {
  access_token: string;
  username: string;
  display_name: string;
}

export const auth = {
  status: (creds: Credentials) => request<AuthStatus>(creds, '/api/auth/status'),
  login: (creds: Credentials, username: string, password: string) =>
    request<TokenResponse>(creds, '/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  /**
   * Extend the session without asking for the password again. Called on
   * launch: the token lasts 30 days, and a phone that is opened weekly should
   * never meet a login screen.
   */
  refresh: (creds: Credentials) =>
    request<TokenResponse>(creds, '/api/auth/refresh', { method: 'POST' }),
  changePassword: (creds: Credentials, current: string, next: string) =>
    request<TokenResponse>(creds, '/api/auth/password', {
      method: 'POST',
      body: JSON.stringify({ current_password: current, new_password: next }),
    }),
};

// ── sessions ─────────────────────────────────────────────────────────

export interface AgentSummary {
  session_id: string;
  session_name?: string | null;
  status: string;
  role?: string | null;
  model?: string | null;
  env_name?: string | null;
  last_route?: { label?: string; model?: string; failedOver?: boolean } | null;
}

export const agents = {
  list: (creds: Credentials) => request<AgentSummary[]>(creds, '/api/agents'),
  create: (creds: Credentials, name: string) =>
    request<AgentSummary>(creds, '/api/agents', {
      method: 'POST',
      body: JSON.stringify({ session_name: name, role: 'worker' }),
    }),
  remove: (creds: Credentials, id: string) =>
    request<{ success: boolean }>(creds, `/api/agents/${id}`, { method: 'DELETE' }),
  logs: (creds: Credentials, id: string, limit = 120) =>
    request<{ entries: unknown[] }>(creds, `/api/logs/${id}?limit=${limit}`),
  stop: (creds: Credentials, id: string) =>
    request<{ success: boolean }>(creds, `/api/agents/${id}/stop`, { method: 'POST' }),
};

// ── model accounts + the session's route ─────────────────────────────

export interface ModelChoice { id: string; label: string; hint?: string }

export interface LlmAccount {
  id: string;
  kind: string;
  label: string;
  enabled: boolean;
  modelChoices: ModelChoice[];
  status?: { ok?: boolean; detail?: string };
  identity?: { email?: string | null; plan?: string | null };
  hasSecret: boolean;
}

export interface RouteRef { accountId: string; model?: string }
export interface AgentRoute { primary: RouteRef | null; fallbacks: RouteRef[] }

export const models = {
  list: (creds: Credentials) =>
    request<{ accounts: LlmAccount[]; defaultRoute: AgentRoute }>(creds, '/api/llm-accounts'),
  test: (creds: Credentials, id: string) =>
    request<{ ok: boolean; latencyMs: number; error?: string }>(creds, `/api/llm-accounts/${id}/test`, {
      method: 'POST',
      body: JSON.stringify({ model: null }),
    }),
  route: (creds: Credentials, sessionId: string) =>
    request<{ route: AgentRoute | null; last_route: { label?: string; model?: string; failedOver?: boolean } | null }>(
      creds, `/api/agents/${sessionId}/route`),
  setRoute: (creds: Credentials, sessionId: string, route: AgentRoute) =>
    request<{ applies: string }>(creds, `/api/agents/${sessionId}/route`, {
      method: 'PUT',
      body: JSON.stringify({ primary: route.primary, fallbacks: route.fallbacks }),
    }),
};
