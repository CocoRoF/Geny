/**
 * Talking to the Geny server from the connector.
 *
 * The settings window already fetches the server directly for login; this is
 * that, factored out, so every new surface resolves the base URL and the
 * stored token the same way instead of each one re-deriving them.
 *
 * A 401 clears the stored token. Leaving a dead token in the keychain is how
 * the connector ends up rendering empty lists forever with no visible reason
 * — the user sees "signed in" and no data.
 */

export const TOKEN_KEY = 'geny_auth_token'

export class ServerError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ServerError'
  }
}

async function base(): Promise<string> {
  const config = await window.connector?.serverConfig.get()
  const url = (config?.serverUrl ?? '').trim().replace(/\/+$/, '')
  if (!url) throw new ServerError('서버 주소가 설정되지 않았습니다', 0)
  return url
}

/** The server's WebSocket origin, derived from the configured HTTP one. */
export async function wsBase(): Promise<string> {
  const root = await base()
  return root.replace(/^http/, 'ws')
}

export async function authToken(): Promise<string | null> {
  return (await window.connector?.secureStore.get(TOKEN_KEY)) ?? null
}

export async function serverFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const [root, token] = await Promise.all([base(), window.connector?.secureStore.get(TOKEN_KEY)])
  const res = await fetch(`${root}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  })
  if (res.status === 401) {
    await window.connector?.secureStore.delete(TOKEN_KEY)
    throw new ServerError('로그인이 만료됐습니다 — 계정 탭에서 다시 로그인하세요', 401)
  }
  if (!res.ok) {
    const body = await res.text()
    let message = `HTTP ${res.status}`
    try {
      const parsed = JSON.parse(body)
      if (typeof parsed?.detail === 'string') message = parsed.detail
    } catch {
      if (body && !body.trimStart().startsWith('<')) message = body.slice(0, 300)
    }
    throw new ServerError(message, res.status)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/**
 * Follow a server-sent event stream. `EventSource` cannot carry an
 * Authorization header, so this reads the body and splits the frames itself.
 * Returns a stop function.
 */
export function serverStream(
  path: string,
  onEvent: (event: Record<string, unknown>) => void,
): () => void {
  const controller = new AbortController()
  void (async () => {
    try {
      const [root, token] = await Promise.all([base(), window.connector?.secureStore.get(TOKEN_KEY)])
      const res = await fetch(`${root}${path}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      })
      if (!res.ok || !res.body) return
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) return
        buffer += decoder.decode(value, { stream: true })
        let cut = buffer.indexOf('\n\n')
        while (cut >= 0) {
          const frame = buffer.slice(0, cut)
          buffer = buffer.slice(cut + 2)
          for (const line of frame.split('\n')) {
            if (!line.startsWith('data:')) continue
            try {
              onEvent(JSON.parse(line.slice(5).trim()))
            } catch {
              /* a keepalive, or a partial frame the next one completes */
            }
          }
          cut = buffer.indexOf('\n\n')
        }
      }
    } catch {
      /* aborted, or the connection dropped — the caller re-subscribes */
    }
  })()
  return () => controller.abort()
}

// ── model accounts ───────────────────────────────────────────────────

export type AccountKind =
  | 'claude_code' | 'codex' | 'anthropic' | 'openai' | 'google'
  | 'openrouter' | 'ollama' | 'vllm' | 'openai_compatible'

export interface ModelChoice { id: string; label: string; hint?: string }

export interface KindInfo {
  label: string
  short: string
  engineProvider: string
  /** subscription | api | self_hosted — how the settings page groups it. */
  family: string
  secret: string
  hint: string
  models: ModelChoice[]
  defaultBaseUrl: string
  needsBaseUrl: boolean
  ownsConfigDir: boolean
}

export interface LlmAccount {
  id: string
  kind: AccountKind
  label: string
  enabled: boolean
  baseUrl: string
  effort: string
  identity: { email?: string | null; plan?: string | null; organization?: string | null }
  status: { ok?: boolean; checkedAt?: number; detail?: string }
  models: string[]
  modelChoices: ModelChoice[]
  hasSecret: boolean
  engineProvider: string
  claude?: { authMethod: string; mode: string }
}

export interface RouteRef { accountId: string; model?: string; effort?: string }
export interface AgentRoute { primary: RouteRef | null; fallbacks: RouteRef[] }
export interface LastRoute {
  accountId?: string; label?: string; model?: string; failedOver?: boolean
}

export const accounts = {
  kinds: () => serverFetch<{
    kinds: Record<string, KindInfo>
    families: { id: string; label: string }[]
    efforts: string[]
  }>('/api/llm-accounts/kinds'),
  list: () => serverFetch<{ accounts: LlmAccount[]; defaultRoute: AgentRoute }>('/api/llm-accounts'),
  create: (input: Record<string, unknown>) =>
    serverFetch<{ account: LlmAccount }>('/api/llm-accounts', { method: 'POST', body: JSON.stringify(input) }),
  update: (id: string, patch: Record<string, unknown>) =>
    serverFetch<{ account: LlmAccount }>(`/api/llm-accounts/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  remove: (id: string) => serverFetch<{ ok: boolean }>(`/api/llm-accounts/${id}`, { method: 'DELETE' }),
  reorder: (order: string[]) =>
    serverFetch<{ accounts: LlmAccount[] }>('/api/llm-accounts/reorder', { method: 'POST', body: JSON.stringify({ order }) }),
  test: (id: string) =>
    serverFetch<{ ok: boolean; latencyMs: number; error?: string; reply?: string }>(
      `/api/llm-accounts/${id}/test`, { method: 'POST', body: JSON.stringify({ model: null }) }),
  cli: () => serverFetch<{ found: boolean; path: string; version: string }>('/api/llm-accounts/cli'),
  claudeLogin: (id: string) =>
    serverFetch<{ jobId: string }>(`/api/llm-accounts/${id}/claude/login`, {
      method: 'POST', body: JSON.stringify({ console: false }),
    }),
  claudeLogout: (id: string) =>
    serverFetch<{ ok: boolean }>(`/api/llm-accounts/${id}/claude/logout`, { method: 'POST' }),
  codexLogin: (id: string) =>
    serverFetch<{ jobId: string; userCode: string; verificationUrl: string; expiresAt: number }>(
      `/api/llm-accounts/${id}/codex/login`, { method: 'POST' }),
  sendLoginInput: (jobId: string, text: string) =>
    serverFetch<{ ok: boolean }>('/api/llm-accounts/login/input', {
      method: 'POST', body: JSON.stringify({ jobId, text }),
    }),
  cancelLogin: (jobId: string) =>
    serverFetch<{ ok: boolean }>(`/api/llm-accounts/login/${jobId}/cancel`, { method: 'POST' }),
  events: (jobId: string, onEvent: (event: Record<string, unknown>) => void) =>
    serverStream(`/api/llm-accounts/events?job_id=${encodeURIComponent(jobId)}`, onEvent),
}

// ── agents, their route, and what they did ───────────────────────────

export interface AgentSummary {
  session_id: string
  session_name?: string | null
  status: string
  role?: string
  model?: string | null
  env_name?: string | null
  route?: AgentRoute | null
  last_route?: LastRoute | null
}

export interface ActivityEntry {
  seq: number
  ts?: string
  kind: 'file' | 'command' | 'read' | 'tool' | 'turn' | 'route' | 'error'
  tool?: string
  path?: string
  operation?: string
  linesAdded?: number
  linesRemoved?: number
  command?: string
  cwd?: string
  output?: string
  ok?: boolean | null
  durationMs?: number | null
  error?: string | null
  role?: 'user' | 'assistant'
  text?: string
  label?: string
  model?: string
  failedOver?: boolean
  failedKind?: string
  detail?: string
}

export interface WorkspaceSummary {
  files: { path: string; operations: string[]; writes: number; linesAdded: number; linesRemoved: number; failed: number }[]
  commands: { seq: number; command: string; cwd?: string; ok?: boolean | null; durationMs?: number | null }[]
  failures: { seq: number; tool?: string; error?: string | null }[]
  toolCounts: Record<string, number>
  turns: number
}

export const agents = {
  list: () => serverFetch<AgentSummary[]>('/api/agents'),
  route: (id: string) =>
    serverFetch<{ route: AgentRoute | null; last_route: LastRoute | null; live: boolean }>(`/api/agents/${id}/route`),
  setRoute: (id: string, route: AgentRoute) =>
    serverFetch<{ applies: string; targets: { label: string; model: string }[] }>(`/api/agents/${id}/route`, {
      method: 'PUT', body: JSON.stringify({ primary: route.primary, fallbacks: route.fallbacks }),
    }),
  activity: (id: string, kind?: string, limit = 120) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (kind) params.set('kind', kind)
    return serverFetch<{ entries: ActivityEntry[]; total: number }>(
      `/api/agents/${id}/workspace/activity?${params.toString()}`)
  },
  summary: (id: string) => serverFetch<WorkspaceSummary>(`/api/agents/${id}/workspace/summary`),
  execute: (id: string, prompt: string) =>
    serverFetch<{ session_id: string }>(`/api/agents/${id}/execute`, {
      method: 'POST', body: JSON.stringify({ prompt }),
    }),
  stop: (id: string) => serverFetch<{ success: boolean }>(`/api/agents/${id}/stop`, { method: 'POST' }),
}

// ── the session's own record ─────────────────────────────────────────
//
// The log is what the server actually wrote, and the conversation is folded
// out of it (`shared/chat/transcript`). Opening a session reads its log;
// staying on it follows the execute socket. Both produce the same entries, so
// the same fold turns them into the same conversation.

export interface SessionLogEntry {
  timestamp?: string
  level?: string
  message?: string
  metadata?: Record<string, unknown> | string
}

export const sessions = {
  /** Newest first, as the endpoint returns them. */
  logs: (id: string, limit = 400) =>
    serverFetch<{ entries: SessionLogEntry[]; total_entries: number }>(
      `/api/command/logs/${encodeURIComponent(id)}?limit=${limit}`),
  create: (body: Record<string, unknown>) =>
    serverFetch<{ session_id: string; session_name?: string }>('/api/agents', {
      method: 'POST', body: JSON.stringify(body),
    }),
  remove: (id: string) =>
    serverFetch<{ success?: boolean }>(`/api/agents/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

export interface EnvironmentSummary {
  id: string
  name: string
  description?: string
  is_template?: boolean
}

export const environments = {
  list: () => serverFetch<{ environments: EnvironmentSummary[] }>('/api/environments'),
}
