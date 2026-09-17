/**
 * A server that answers like Geny, with a turn worth looking at.
 *
 * The states that decide whether this UI is any good — a run of tool calls, a
 * command that failed, an answer with code in it, a fallback account
 * answering instead of the one you picked — are rare in a live session and
 * impossible to summon on demand. So they live here, as one canned log, and
 * the window can be opened onto them at any time.
 *
 * It is a fixture, not a mock: the shapes are the server's real ones (the log
 * levels and metadata keys that `shared/chat/transcript` folds), so if the
 * contract moves, what renders here stops making sense too.
 *
 *   node tests/smoke/fixture-server.cjs [port]
 */
const { createServer } = require('node:http')

const PORT = Number(process.argv[2] || 58787)

const SESSIONS = [
  { session_id: 'fixture-1', session_name: '커넥터 리디자인', status: 'running', env_name: '일반 환경' },
  { session_id: 'fixture-2', session_name: '엘렌', status: 'stopped', env_name: 'VTuber 환경' },
]

let t = Date.parse('2026-09-17T21:30:00+09:00')
const at = (step = 4000) => new Date((t += step)).toISOString()

const LOG = [
  {
    level: 'COMMAND', timestamp: at(),
    message: 'PROMPT: 접속기 스타일시트에서 안 쓰는 토큰이 있는지 확인하고 정리해줘.',
  },
  {
    level: 'TOOL', timestamp: at(1200), message: '🔧 Bash',
    metadata: {
      tool_name: 'Bash', tool_id: 'c1',
      input_preview: '{"command": "grep -c \\"var(--\\" src/renderer/src/styles/*.css"}',
      command_data: { command: 'grep -c "var(--" src/renderer/src/styles/*.css' },
    },
  },
  {
    level: 'TOOL_RES', timestamp: at(900), message: 'TOOL_RESULT [OK]: Bash',
    metadata: {
      tool_name: 'Bash', tool_id: 'c1', is_error: false, duration_ms: 240,
      result_preview: 'tokens.css:2\nbase.css:21\ncomponents.css:96\nworkspace.css:142',
    },
  },
  {
    level: 'TOOL', timestamp: at(600), message: '🔧 Read',
    metadata: {
      tool_name: 'Read', tool_id: 'c2',
      input_preview: '{"file_path": "src/renderer/src/styles/tokens.css"}',
      file_read: { file_path: 'src/renderer/src/styles/tokens.css' },
    },
  },
  {
    level: 'TOOL_RES', timestamp: at(500), message: 'TOOL_RESULT [OK]: Read',
    metadata: { tool_name: 'Read', tool_id: 'c2', is_error: false, duration_ms: 90, result_preview: '134 lines' },
  },
  {
    level: 'TOOL', timestamp: at(500), message: '🔧 Bash',
    metadata: {
      tool_name: 'Bash', tool_id: 'c3',
      input_preview: '{"command": "npx stylelint src/renderer/src/styles"}',
      command_data: { command: 'npx stylelint src/renderer/src/styles' },
    },
  },
  {
    level: 'TOOL_RES', timestamp: at(2600), message: 'TOOL_RESULT [ERROR]: Bash',
    metadata: {
      tool_name: 'Bash', tool_id: 'c3', is_error: true, duration_ms: 2480,
      result_preview: 'sh: 1: stylelint: not found\nexit code 127',
    },
  },
  {
    level: 'TOOL', timestamp: at(400), message: '🔧 Edit',
    metadata: {
      tool_name: 'Edit', tool_id: 'c4',
      input_preview: '{"file_path": "src/renderer/src/styles/tokens.css", "old": "--surface-2", "new": ""}',
      file_changes: { file_path: 'src/renderer/src/styles/tokens.css', operation: 'edit', lines_added: 0, lines_removed: 2 },
    },
  },
  {
    level: 'TOOL_RES', timestamp: at(300), message: 'TOOL_RESULT [OK]: Edit',
    metadata: { tool_name: 'Edit', tool_id: 'c4', is_error: false, duration_ms: 40, result_preview: 'edited' },
  },
  {
    level: 'RESPONSE', timestamp: at(1500),
    message: `SUCCESS: 토큰은 전부 쓰이고 있었고, 안 쓰이는 건 \`--surface-2\` 하나였습니다.

확인한 방법:

1. 선언된 토큰 목록을 뽑고
2. 나머지 네 파일에서 \`var(--이름)\` 을 세어
3. 0 인 것만 남겼습니다.

\`\`\`bash
comm -23 <(declared) <(used)
# --surface-2
\`\`\`

지웠습니다. \`stylelint\` 는 이 저장소에 설치돼 있지 않아서 건너뛰었습니다 — 필요하면 devDependency 로 넣어둘까요?`,
    metadata: { success: true, duration_ms: 11200, cost_usd: 0.031 },
  },
  {
    level: 'COMMAND', timestamp: at(9000),
    message: 'PROMPT: [THINKING_TRIGGER:time_evening] [time_context: 목요일 저녁] The evening is here.',
  },
  {
    level: 'RESPONSE', timestamp: at(3000),
    message: "FAILED: CLI '/usr/bin/claude' exited with code 1:  [cli_version=2.1.220 (Claude Code)]",
    metadata: { success: false },
  },
]

// A stretch of autonomous turns that said nothing, which is what a VTuber
// session's log actually looks like between real exchanges.
LOG.push(
  {
    level: 'COMMAND', timestamp: at(60000),
    message: 'PROMPT: [THINKING_TRIGGER:screen_observation] look at the screen',
  },
  {
    level: 'RESPONSE', timestamp: at(2000), message: 'SUCCESS: [calm:0.3] [SILENT]',
    metadata: { success: true },
  },
  {
    level: 'COMMAND', timestamp: at(60000),
    message: 'PROMPT: [THINKING_TRIGGER:screen_observation] look at the screen',
  },
  {
    level: 'RESPONSE', timestamp: at(2000), message: 'SUCCESS: [calm:0.3] [SILENT]',
    metadata: { success: true },
  },
  {
    level: 'COMMAND', timestamp: at(60000),
    message: 'PROMPT: [THINKING_TRIGGER:screen_observation] look at the screen',
  },
  {
    level: 'RESPONSE', timestamp: at(2000),
    message: 'SUCCESS: [calm:0.4] release 0.26.0 빌드 다 초록불이네 — 데스크톱 3종에 APK 까지.',
    metadata: { success: true },
  },
)

const FILES = {
  '': [
    { name: 'src', path: 'workspace/src', is_dir: true },
    { name: 'docs', path: 'workspace/docs', is_dir: true },
    { name: 'README.md', path: 'workspace/README.md', is_dir: false, size: 1841 },
    { name: 'tokens.css', path: 'workspace/tokens.css', is_dir: false, size: 4096 },
    { name: 'notes.txt', path: 'workspace/notes.txt', is_dir: false, size: 220 },
  ],
  'workspace/src': [
    { name: 'index.ts', path: 'workspace/src/index.ts', is_dir: false, size: 980 },
    { name: 'styles.css', path: 'workspace/src/styles.css', is_dir: false, size: 12400 },
  ],
}

const FILE_TEXT = `/* tokens.css — written by the agent */
:root {
  --primary: #305eeb;
  --primary-end: #783ced;
  --panel: #ffffff;
}
`

const ACCOUNTS = {
  accounts: [
    {
      id: 'acc-claude', kind: 'claude_code', label: 'Claude Code', enabled: true, baseUrl: '', effort: '',
      identity: { email: 'you@example.com', plan: 'max' }, status: { ok: true },
      models: [], modelChoices: [{ id: 'sonnet', label: 'Sonnet (최신)' }, { id: 'opus', label: 'Opus (최신)' }],
      hasSecret: true, engineProvider: 'geny_claude_code',
    },
    {
      id: 'acc-openai', kind: 'openai', label: 'OpenAI', enabled: true, baseUrl: '', effort: '',
      identity: {}, status: { ok: true }, models: [],
      modelChoices: [{ id: 'gpt-5.6-terra', label: 'GPT-5.6 Terra' }],
      hasSecret: true, engineProvider: 'openai',
    },
  ],
  defaultRoute: { primary: { accountId: 'acc-claude' }, fallbacks: [{ accountId: 'acc-openai' }] },
}

const SUMMARY = {
  files: [
    { path: 'desktop/src/renderer/src/styles/tokens.css', operations: ['edit'], writes: 1, linesAdded: 0, linesRemoved: 2, failed: 0 },
    { path: 'desktop/src/renderer/src/styles/workspace.css', operations: ['write'], writes: 1, linesAdded: 142, linesRemoved: 0, failed: 0 },
  ],
  commands: [
    { seq: 2, command: 'grep -c "var(--" src/renderer/src/styles/*.css', ok: true, durationMs: 240 },
    { seq: 6, command: 'npx stylelint src/renderer/src/styles', ok: false, durationMs: 2480 },
  ],
  failures: [{ seq: 6, tool: 'Bash', error: 'stylelint: not found' }],
  toolCounts: { Bash: 2, Read: 1, Edit: 1 },
  turns: 2,
}

const ACTIVITY = {
  total: 6,
  entries: [
    { seq: 6, kind: 'command', command: 'npx stylelint src/renderer/src/styles', ok: false },
    { seq: 5, kind: 'file', path: 'styles/tokens.css', operation: 'edit', linesRemoved: 2 },
    { seq: 4, kind: 'turn', role: 'assistant', text: '토큰은 전부 쓰이고 있었고…' },
    { seq: 3, kind: 'turn', role: 'trigger', text: '[THINKING_TRIGGER:time_evening]' },
    { seq: 2, kind: 'read', path: 'styles/tokens.css' },
    { seq: 1, kind: 'turn', role: 'user', text: '접속기 스타일시트에서…' },
  ],
}

const ROUTES = {
  route: { primary: { accountId: 'acc-claude', model: 'sonnet' }, fallbacks: [{ accountId: 'acc-openai' }] },
  // The fallback answered — the one case the header exists to show.
  last_route: { accountId: 'acc-openai', label: 'OpenAI', model: 'gpt-5.6-terra', index: 1, failedOver: true },
  live: true,
}

const server = createServer((req, res) => {
  const url = new URL(req.url, 'http://x')
  const send = (body) => {
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify(body))
  }
  if (url.pathname === '/api/agents') return send(SESSIONS)
  if (url.pathname.startsWith('/api/command/logs/')) {
    // The endpoint answers newest-first; the window reverses it.
    return send({ entries: [...LOG].reverse(), total_entries: LOG.length })
  }
  if (url.pathname === '/api/llm-accounts') return send(ACCOUNTS)
  if (url.pathname === '/api/llm-accounts/kinds') return send({ kinds: {}, families: [], efforts: [] })
  if (url.pathname.endsWith('/route')) return send(ROUTES)
  if (url.pathname.endsWith('/workspace/summary')) return send(SUMMARY)
  if (url.pathname.includes('/workspace/activity')) return send(ACTIVITY)
  if (url.pathname === '/api/environments') return send({ environments: [] })
  if (url.pathname.endsWith('/storage')) {
    return send({ files: FILES[url.searchParams.get('path') || ''] ?? [] })
  }
  if (url.pathname.includes('/storage/')) {
    return send({ content: FILE_TEXT, size: FILE_TEXT.length, encoding: 'utf-8' })
  }
  res.writeHead(404, { 'Content-Type': 'application/json' })
  res.end('{}')
})

// The window opens an execute socket. Refusing the upgrade leaves it
// reconnecting, which is its own (correct) design state — so leave it.
server.listen(PORT, '127.0.0.1', () => {
  console.log(`fixture on http://127.0.0.1:${PORT}`)
})
