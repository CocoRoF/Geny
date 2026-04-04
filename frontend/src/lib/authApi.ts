/**
 * Auth API — communicates with backend /api/auth/* endpoints.
 */

// ==================== Types ====================

export interface AuthStatus {
  has_users: boolean;
  is_authenticated: boolean;
  username: string | null;
  display_name: string | null;
}

export interface AuthTokenResponse {
  token: string;
  username: string;
  display_name: string;
}

export interface AuthMessageResponse {
  message: string;
}

// ==================== Token Management ====================

const TOKEN_KEY = 'geny_auth_token';

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function removeToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

// ==================== Fetch Helper ====================

async function authCall<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(endpoint, { ...options, headers });
  if (!res.ok) {
    const body = await res.text();
    let message: string;
    try {
      const json = JSON.parse(body);
      message = json.detail || json.message || json.error || `HTTP ${res.status}`;
    } catch {
      message = body || `HTTP ${res.status}`;
    }
    const err: Error & { status?: number } = new Error(message);
    err.status = res.status;
    throw err;
  }
  return res.json() as Promise<T>;
}

// ==================== Auth API ====================

export const authApi = {
  /** Check auth status (has_users, is_authenticated, etc.) */
  status: () => authCall<AuthStatus>('/api/auth/status'),

  /** First-time setup — create admin account */
  setup: (data: { username: string; password: string; display_name?: string }) =>
    authCall<AuthTokenResponse>('/api/auth/setup', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** Login with existing credentials */
  login: (data: { username: string; password: string }) =>
    authCall<AuthTokenResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** Logout (server-side cookie clear) */
  logout: () =>
    authCall<AuthMessageResponse>('/api/auth/logout', { method: 'POST' }),

  /** Get current user info */
  me: () => authCall<{ username: string; display_name: string }>('/api/auth/me'),
};
