/**
 * Model accounts, and the route a session runs on.
 *
 * An ACCOUNT is one way this server can reach a model: a Claude Code login,
 * a second Claude Code login, a ChatGPT (Codex) login, an API key, a local
 * server. There is no limit per kind.
 *
 * A ROUTE is what a session uses — a primary `(account, model)` and ordered
 * fallbacks. The pipeline always names one provider, so switching the route
 * mid-conversation keeps the conversation: same tools, same memory, same
 * hooks, same permission policy.
 *
 * Both subscription logins are STREAMED, not returned. Neither can finish
 * inside a request — Claude Code prints a URL and waits for a code, Codex
 * hands out a device code and waits for approval — and the browser that
 * completes them is this one, not the server. `loginEvents` carries the flow
 * out; `sendLoginInput` carries the answer back.
 */

import { handleAuthFailure } from '@/lib/api';
import { getToken } from '@/lib/authApi';

// ── shapes ───────────────────────────────────────────────────────────

export type AccountKind =
  | 'claude_code' | 'codex' | 'anthropic' | 'openai' | 'google'
  | 'openrouter' | 'ollama' | 'vllm' | 'openai_compatible';

/** How a Claude Code account authenticates the CLI.
 *  login = `claude auth login` into this account's own config dir
 *  token = a long-lived `claude setup-token`
 *  api_key = an Anthropic Console key
 *  system = whatever the server's own `claude` is logged into */
export type ClaudeAuthMethod = 'login' | 'token' | 'api_key' | 'system';

/** token = the CLI only generates tokens and Geny runs the tools (default).
 *  agent = the CLI runs its own loop — Geny then sees only the announcement. */

export interface ModelChoice {
  id: string;
  label: string;
  hint?: string;
}

/** Which conversation a kind is: one you sign into, one you paste a key
 *  into, or one you point at a machine you run. */
export type KindFamily = 'subscription' | 'api' | 'self_hosted';

export interface KindInfo {
  label: string;
  short: string;
  engineProvider: string;
  family: KindFamily;
  /** api_key | optional_key | none | oauth */
  secret: string;
  hint: string;
  models: ModelChoice[];
  defaultBaseUrl: string;
  needsBaseUrl: boolean;
  ownsConfigDir: boolean;
}

export interface AccountIdentity {
  email?: string | null;
  plan?: string | null;
  organization?: string | null;
  subscription?: string | null;
  accountId?: string | null;
}

export interface AccountStatus {
  ok?: boolean;
  checkedAt?: number;
  detail?: string;
}

export interface LlmAccount {
  id: string;
  kind: AccountKind;
  label: string;
  enabled: boolean;
  baseUrl: string;
  effort: string;
  identity: AccountIdentity;
  status: AccountStatus;
  models: string[];
  modelChoices: ModelChoice[];
  hasSecret: boolean;
  engineProvider: string;
  createdAt?: string | null;
  claude?: { authMethod: ClaudeAuthMethod };
  configDir?: string;
}

export interface RouteRef {
  accountId: string;
  model?: string;
  effort?: string;
}

export interface AgentRoute {
  primary: RouteRef | null;
  fallbacks: RouteRef[];
}

/** Who actually answered the last turn. Differs from the route exactly when
 *  a hop failed over — which is the moment it is worth seeing. */
export interface LastRoute {
  accountId?: string;
  label?: string;
  kind?: AccountKind;
  model?: string;
  index?: number;
  failedOver?: boolean;
}

export interface AccountTestResult {
  ok: boolean;
  latencyMs: number;
  model?: string;
  reply?: string;
  error?: string;
}

export interface ClaudeStatus {
  loggedIn: boolean;
  method?: string | null;
  email?: string | null;
  organization?: string | null;
  subscription?: string | null;
  error?: string | null;
  cli?: CliInfo;
}

export interface CliInfo {
  found: boolean;
  path: string;
  version: string;
}

export type LoginEvent =
  | { ts: number; jobId: string; accountId: string; type: 'line'; stream: 'stdout' | 'stderr'; text: string }
  | { ts: number; jobId: string; accountId: string; type: 'url'; url: string }
  | { ts: number; jobId: string; accountId: string; type: 'device'; userCode: string; verificationUrl: string; expiresAt: number }
  | { ts: number; jobId: string; accountId: string; type: 'done'; ok: boolean; error?: string | null };

export interface NewAccountInput {
  kind: AccountKind;
  label?: string;
  baseUrl?: string;
  secret?: string;
  effort?: string;
  claude?: { authMethod?: ClaudeAuthMethod };
}

export interface AccountPatch {
  label?: string;
  enabled?: boolean;
  baseUrl?: string;
  effort?: string;
  secret?: string;
  claude?: { authMethod?: ClaudeAuthMethod };
}

// ── transport ────────────────────────────────────────────────────────

async function call<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
    ...options,
  });
  if (res.status === 401) handleAuthFailure();
  if (!res.ok) {
    const body = await res.text();
    let message = `HTTP ${res.status}`;
    try {
      const json = JSON.parse(body);
      message = typeof json.detail === 'string' ? json.detail : message;
    } catch {
      if (body && !body.trimStart().startsWith('<')) message = body.slice(0, 300);
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const BASE = '/api/llm-accounts';

export const llmAccountsApi = {
  /** Every kind of account, what it needs, and the models it offers. */
  kinds: () => call<{
    kinds: Record<AccountKind, KindInfo>;
    families: { id: KindFamily; label: string }[];
    efforts: string[];
  }>(`${BASE}/kinds`),

  list: () => call<{ accounts: LlmAccount[]; defaultRoute: AgentRoute }>(BASE),

  create: (input: NewAccountInput) =>
    call<{ account: LlmAccount }>(BASE, { method: 'POST', body: JSON.stringify(input) }),

  update: (id: string, patch: AccountPatch) =>
    call<{ account: LlmAccount }>(`${BASE}/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),

  remove: (id: string) => call<{ ok: boolean }>(`${BASE}/${id}`, { method: 'DELETE' }),

  reorder: (order: string[]) =>
    call<{ accounts: LlmAccount[] }>(`${BASE}/reorder`, {
      method: 'POST', body: JSON.stringify({ order }),
    }),

  /** Is a `claude` binary reachable from the server, and which version. */
  cli: (refresh = false) => call<CliInfo>(`${BASE}/cli${refresh ? '?refresh=true' : ''}`),

  /** One real generation. `auth status` reports a lapsed plan as fine and a
   *  rotated key as present, so this is the only honest check. */
  test: (id: string, model?: string) =>
    call<AccountTestResult>(`${BASE}/${id}/test`, {
      method: 'POST', body: JSON.stringify({ model: model ?? null }),
    }),

  discoverModels: (id: string) =>
    call<{ models: string[] }>(`${BASE}/${id}/discover-models`, { method: 'POST' }),

  claudeStatus: (id: string) => call<ClaudeStatus>(`${BASE}/${id}/claude/status`),

  claudeLogin: (id: string, console_ = false) =>
    call<{ jobId: string }>(`${BASE}/${id}/claude/login`, {
      method: 'POST', body: JSON.stringify({ console: console_ }),
    }),

  claudeLogout: (id: string) =>
    call<{ ok: boolean }>(`${BASE}/${id}/claude/logout`, { method: 'POST' }),

  codexLogin: (id: string) =>
    call<{ jobId: string; userCode: string; verificationUrl: string; expiresAt: number }>(
      `${BASE}/${id}/codex/login`, { method: 'POST' },
    ),

  /** Adopt an existing `~/.codex/auth.json` on the server — a copy, not a
   *  share: that refresh token is single-use. */
  codexImport: (id: string) =>
    call<{ ok: boolean; account: LlmAccount }>(`${BASE}/${id}/codex/import-cli`, { method: 'POST' }),

  /** The code the user read in the browser on their own machine. */
  sendLoginInput: (jobId: string, text: string) =>
    call<{ ok: boolean }>(`${BASE}/login/input`, {
      method: 'POST', body: JSON.stringify({ jobId, text }),
    }),

  cancelLogin: (jobId: string) =>
    call<{ ok: boolean }>(`${BASE}/login/${jobId}/cancel`, { method: 'POST' }),

  /**
   * Subscribe to a login's events. Replays what the job already emitted
   * before going live, so opening a moment late does not lose the URL the
   * whole flow hangs on. Returns an unsubscribe.
   *
   * EventSource cannot carry an Authorization header, so this reads the
   * stream with fetch and parses the SSE frames itself.
   */
  loginEvents: (jobId: string | null, onEvent: (event: LoginEvent) => void): (() => void) => {
    const controller = new AbortController();
    const token = getToken();
    const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : '';

    void (async () => {
      try {
        const res = await fetch(`${BASE}/events${query}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: controller.signal,
        });
        if (!res.ok || !res.body) return;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        for (;;) {
          const { done, value } = await reader.read();
          if (done) return;
          buffer += decoder.decode(value, { stream: true });
          let cut = buffer.indexOf('\n\n');
          while (cut >= 0) {
            const frame = buffer.slice(0, cut);
            buffer = buffer.slice(cut + 2);
            for (const line of frame.split('\n')) {
              if (!line.startsWith('data:')) continue;
              try {
                onEvent(JSON.parse(line.slice(5).trim()) as LoginEvent);
              } catch {
                /* a keepalive or a partial frame — the next one carries it */
              }
            }
            cut = buffer.indexOf('\n\n');
          }
        }
      } catch {
        /* aborted, or the connection dropped; the caller re-subscribes */
      }
    })();

    return () => controller.abort();
  },
};

// ── a session's route ────────────────────────────────────────────────

export interface SessionRouteState {
  session_id: string;
  route: AgentRoute | null;
  last_route: LastRoute | null;
  live: boolean;
}

export interface RouteChangeResult {
  success: boolean;
  session_id: string;
  route: AgentRoute;
  previous_route: AgentRoute | null;
  targets: { accountId: string; label: string; kind: AccountKind; model: string }[];
  live: boolean;
  /** "immediately" for a live session — the swap happens in place, with no
   *  pipeline rebuild, so the conversation continues. */
  applies: 'immediately' | 'next_turn';
}

export const sessionRouteApi = {
  get: (sessionId: string) => call<SessionRouteState>(`/api/agents/${sessionId}/route`),

  set: (sessionId: string, route: AgentRoute) =>
    call<RouteChangeResult>(`/api/agents/${sessionId}/route`, {
      method: 'PUT',
      body: JSON.stringify({ primary: route.primary, fallbacks: route.fallbacks }),
    }),
};

// ── helpers ──────────────────────────────────────────────────────────

/** Everything an account can be asked for: its kind's catalogue first, then
 *  anything discovery found that the catalogue misses. */
export function modelChoicesFor(account: LlmAccount, kinds?: Record<string, KindInfo>): ModelChoice[] {
  if (account.modelChoices?.length) return account.modelChoices;
  const known = kinds?.[account.kind]?.models ?? [];
  const seen = new Set(known.map((m) => m.id));
  return [...known, ...account.models.filter((id) => !seen.has(id)).map((id) => ({ id, label: id }))];
}

export function modelLabel(account: LlmAccount | undefined, id: string): string {
  if (!account) return id;
  return modelChoicesFor(account).find((m) => m.id === id)?.label ?? id;
}

export function describeAccount(account: LlmAccount): string {
  const identity = account.identity ?? {};
  return identity.email || identity.plan || identity.organization || account.label;
}
