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
  /** Called once when the stream ends by itself (server restart, network) —
   *  not when the caller stopped it. Lets a follower reconnect only when it
   *  has to, instead of on a timer. */
  onEnd?: () => void,
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
    } finally {
      if (!controller.signal.aborted) onEnd?.()
    }
  })()
  return () => controller.abort()
}

/** An absolute URL on the configured server — for an <img> that cannot
 *  carry the Authorization header (`/static/...` is served without one). */
export async function serverUrl(path: string): Promise<string> {
  return `${await base()}${path}`
}

// ── the avatar ───────────────────────────────────────────────────────
//
// Which puppet a VTuber session wears. The avatar window renders whatever is
// assigned here and follows every change the moment it happens (the server
// streams assignments), so changing it from this window is the whole job.

export interface AvatarModel {
  name: string
  display_name: string
  /** live2d | mmd | spine */
  runtime?: string
  thumbnail?: string | null
  description?: string
}

export const avatars = {
  list: () => serverFetch<{ models: AvatarModel[] }>('/api/vtuber/models'),
  of: (sessionId: string) =>
    serverFetch<{ session_id: string; model: AvatarModel | null }>(
      `/api/vtuber/agents/${encodeURIComponent(sessionId)}/model`),
  assign: (sessionId: string, modelName: string) =>
    serverFetch<{ status: string; model_name: string }>(
      `/api/vtuber/agents/${encodeURIComponent(sessionId)}/model`,
      { method: 'PUT', body: JSON.stringify({ model_name: modelName }) }),
  clear: (sessionId: string) =>
    serverFetch<{ status: string }>(
      `/api/vtuber/agents/${encodeURIComponent(sessionId)}/model`, { method: 'DELETE' }),
  /** Every (un)assignment, from any screen, as it happens. Returns a stop. */
  follow: (
    onChange: (sessionId: string, modelName: string | null) => void,
    onEnd?: () => void,
  ): (() => void) =>
    serverStream('/api/vtuber/assignments/stream', (event) => {
      if (event.event === 'assignment_changed' && typeof event.session_id === 'string') {
        onChange(event.session_id, typeof event.model_name === 'string' ? event.model_name : null)
      }
    }, onEnd),
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
  /** `trigger` = the agent woke on a schedule; nobody asked. */
  role?: 'user' | 'assistant' | 'trigger'
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

// ── the conversation ─────────────────────────────────────────────────
//
// The room, not the session log. A room holds ONE agent, and every surface —
// this app, the web page, the phone — reads and writes the same one, which is
// the only way the three can show the same conversation. Which room a session
// talks in is the server's answer, never ours. See `shared/chat/room.ts`.

export interface ChatRoom {
  id: string
  name: string
  session_ids: string[]
  updated_at: string
  message_count: number
}

export const rooms = {
  messages: (roomId: string, limit = 200) =>
    serverFetch<{ messages: RoomMessageDTO[] }>(
      `/api/chat/rooms/${encodeURIComponent(roomId)}/messages?limit=${limit}`),

  /** Says it to the room's agent — the same door the web page and the phone
   *  use, so a message typed here lands where one typed there does. */
  send: (roomId: string, message: string) =>
    serverFetch<{ message?: RoomMessageDTO }>(
      `/api/chat/rooms/${encodeURIComponent(roomId)}/message`,
      { method: 'POST', body: JSON.stringify({ message }) }),

  /**
   * Where this session's conversation lives — the SERVER's answer, not ours.
   *
   * Picking it here meant picking it differently from the web page and from
   * the agent's own autonomous deliveries, which is how one session came to
   * have three conversations. The server creates the room when the session
   * has never spoken, so this always answers.
   */
  forSession: (sessionId: string) =>
    serverFetch<ChatRoom>(
      `/api/chat/rooms/for-session/${encodeURIComponent(sessionId)}`),
}

export interface RoomMessageDTO {
  id: string
  type?: string
  content?: string
  timestamp?: string
  session_id?: string | null
  duration_ms?: number | null
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

// ── the agent's own workspace ────────────────────────────────────────
//
// What the agent is working ON, as opposed to what it said about it. The
// listing is rooted at `workspace/` (scope=workspace) rather than the whole
// session directory: the rest of that directory is the engine's own state —
// the memory vault, transcripts, the database — and it is neither the
// agent's work nor anyone's business here.

export interface StorageEntry {
  name: string
  path: string
  is_dir: boolean
  size?: number | null
  modified_at?: string | null
}

/** `a/b.md` → `workspace/a/b.md`, encoded segment by segment.
 *  The file endpoints resolve from the SESSION root, so a path that came from
 *  the workspace listing needs the prefix put back. */
const scoped = (workspacePath: string): string =>
  ['workspace', ...workspacePath.split('/')].map(encodeURIComponent).join('/')

export interface StorageFile {
  content: string
  /** The whole file's size, even when only its head came back. */
  size: number
  encoding: string
  /** Not text: a PNG, a PDF, a zip. Fetch `raw()` and render it as what it is. */
  binary?: boolean
  /** Only the head of a large file. The rest is on the server. */
  truncated?: boolean
}

export interface DocPreview {
  /** 'svg' for slides, 'png' for pages, 'unsupported' for anything else. */
  kind: string
  count: number
  /** Storage-root-relative paths; load each through `rawUrl`. */
  pages: string[]
}

export const workspace = {
  /** Recursive: one call returns every file at every depth, each path
   *  relative to `workspace/`. The caller builds the tree. */
  list: (sessionId: string) =>
    serverFetch<{ files: StorageEntry[] }>(
      `/api/agents/${encodeURIComponent(sessionId)}/storage?scope=workspace`),

  read: (sessionId: string, workspacePath: string) =>
    serverFetch<StorageFile>(
      `/api/agents/${encodeURIComponent(sessionId)}/storage/${scoped(workspacePath)}`),

  /**
   * The bytes, as a blob URL the page can point an <img>/<video>/<embed> at.
   *
   * It has to be fetched rather than linked: the endpoint wants an
   * Authorization header, and an <img src> cannot carry one. The caller owns
   * the URL and must revoke it.
   */
  raw: async (sessionId: string, storagePath: string): Promise<{ url: string; type: string }> => {
    const [root, token] = await Promise.all([base(), window.connector?.secureStore.get(TOKEN_KEY)])
    const res = await fetch(
      `${root}/api/agents/${encodeURIComponent(sessionId)}/storage-raw/`
      + storagePath.split('/').map(encodeURIComponent).join('/'),
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    )
    if (!res.ok) throw new ServerError(`HTTP ${res.status}`, res.status)
    const blob = await res.blob()
    return { url: URL.createObjectURL(blob), type: blob.type }
  },

  /** Same, for a file addressed inside the agent's workspace. */
  rawWorkspace: (sessionId: string, workspacePath: string) =>
    workspace.raw(sessionId, `workspace/${workspacePath}`),

  /**
   * Office documents and PDFs, rendered to pages by the server (pptx → one
   * SVG a slide, docx/xlsx/pdf → a PNG a page). Cached on the source's mtime,
   * so asking again is instant and an edited document re-renders itself.
   */
  docPreview: (sessionId: string, workspacePath: string) =>
    serverFetch<DocPreview>(
      `/api/agents/${encodeURIComponent(sessionId)}/doc-preview`
      + `?path=${encodeURIComponent(`workspace/${workspacePath}`)}`),
}
