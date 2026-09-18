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
    level: 'STREAM', timestamp: at(300), message: '스타일시트에서 선언된 토큰을 먼저 세어 보겠습니다.',
    metadata: { type: 'text_delta' },
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
    level: 'STREAM', timestamp: at(200), message: '세어 봤으니 이제 린터로 확인합니다.',
    metadata: { type: 'text_delta' },
  },
  {
    level: 'TOOL', timestamp: at(500), message: '🔧 Bash',
    metadata: {
      tool_name: 'Bash', tool_id: 'c3',
      input_preview: JSON.stringify({ command: 'python3 - <<EOF\nimport pdfplumber, json\nfrom re import sub\nprint(1)\nEOF' }),
      command_data: { command: 'python3 …' },
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
    metadata: {
      tool_name: 'Edit', tool_id: 'c4', is_error: false, duration_ms: 40,
      result_preview: JSON.stringify({ name: 'tokens.css', removed: 2, saved: true }),
    },
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

// RECURSIVE, and rooted at workspace/ — paths carry no `workspace/` prefix,
// exactly as `GET …/storage?scope=workspace` returns them. Two `docs`
// directories at different depths are deliberate: a flat render shows them
// twice, which is how the first explorer was found to be wrong.
const FILES = [
  { name: 'src', path: 'src', is_dir: true },
  { name: 'index.ts', path: 'src/index.ts', is_dir: false, size: 980 },
  { name: 'styles.css', path: 'src/styles.css', is_dir: false, size: 12400 },
  { name: 'docs', path: 'src/docs', is_dir: true },
  { name: 'api.md', path: 'src/docs/api.md', is_dir: false, size: 640 },
  { name: 'docs', path: 'docs', is_dir: true },
  { name: 'note.md', path: 'docs/note.md', is_dir: false, size: 16 },
  { name: 'README.md', path: 'README.md', is_dir: false, size: 1841 },
  { name: 'tokens.css', path: 'tokens.css', is_dir: false, size: 4096 },
  { name: 'rows.csv', path: 'rows.csv', is_dir: false, size: 220 },
]

const FILE_TEXT = `/* tokens.css — written by the agent */
:root {
  --primary: #305eeb;
  --primary-end: #783ced;
  --panel: #ffffff;
}
`

const MD_TEXT = `# 점검 결과

85개 문서 중 **5개**를 뽑아 확인했습니다.

- 제조국이 표기와 다른 것: 1건
- 판매 중단된 것: 2건

\`\`\`bash
python3 check.py --limit 5
\`\`\`
`

const CSV_TEXT = `상품명,제조국,판매여부
포켓몬 피카츄 어린이 운동화,중국,판매중
어린이 물놀이 튜브,베트남,중단
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

// ── the conversation ─────────────────────────────────────────────────
//
// The room, not the log. The window reads this now — the same store the web
// page and the phone read — so the fixture has to serve it or the screen is
// empty for a reason that has nothing to do with the design.

const ROOM = {
  id: 'room-1',
  name: '커넥터 리디자인 Chat',
  session_ids: ['fixture-1'],
  created_at: '2026-09-17T21:30:00+09:00',
  updated_at: '2026-09-17T21:41:00+09:00',
  message_count: 4,
}

const ROOM_MESSAGES = [
  {
    id: 'm1', type: 'user', session_id: 'fixture-1',
    timestamp: '2026-09-17T21:30:00+09:00',
    content: '접속기 스타일시트에서 안 쓰는 토큰이 있는지 확인하고 정리해줘.',
  },
  {
    id: 'm2', type: 'agent', session_id: 'fixture-1',
    timestamp: '2026-09-17T21:31:51+09:00', duration_ms: 11200,
    content: `토큰은 전부 쓰이고 있었고, 안 쓰이는 건 \`--surface-2\` 하나였습니다.

확인한 방법:

1. 선언된 토큰 목록을 뽑고
2. 나머지 네 파일에서 \`var(--이름)\` 을 세어
3. 0 인 것만 남겼습니다.

\`\`\`bash
comm -23 <(declared) <(used)
# --surface-2
\`\`\`

지웠습니다. \`stylelint\` 는 이 저장소에 설치돼 있지 않아서 건너뛰었습니다 — 필요하면 devDependency 로 넣어둘까요?`,
  },
  {
    id: 'm3', type: 'user', session_id: 'fixture-1',
    timestamp: '2026-09-17T21:38:00+09:00',
    content: '좋아. 그럼 하단 바에 CPU 도 같이 보여줘.',
  },
  {
    // A mood direction dropped mid-sentence. It is a direction to the avatar,
    // not something anybody said, and a screen that prints it is the bug.
    id: 'm4', type: 'agent', session_id: 'fixture-1',
    timestamp: '2026-09-17T21:41:00+09:00', duration_ms: 4300,
    content: '[calm:0.3] 넣었습니다. [curious:0.5] 메모리 옆에 같은 형식으로 붙였어요.',
  },
]

const server = createServer((req, res) => {
  const url = new URL(req.url, 'http://x')
  const send = (body) => {
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify(body))
  }
  if (url.pathname === '/api/agents') return send(SESSIONS)
  if (url.pathname === '/api/chat/rooms') return send({ rooms: [ROOM], total: 1 })
  if (url.pathname.startsWith('/api/chat/rooms/for-session/')) {
    const sid = decodeURIComponent(url.pathname.split('/for-session/')[1] || '')
    // The server makes a room for a session that has none; a session that is
    // not this fixture's simply has no conversation here.
    if (sid !== 'fixture-1') {
      res.writeHead(404, { 'Content-Type': 'application/json' })
      return res.end(JSON.stringify({ detail: `No chat room for session: ${sid}` }))
    }
    return send(ROOM)
  }
  if (url.pathname.endsWith('/messages') && url.pathname.includes('/api/chat/rooms/')) {
    return send({ room_id: ROOM.id, messages: ROOM_MESSAGES, total: ROOM_MESSAGES.length, has_more: false })
  }
  if (url.pathname.endsWith('/message') && req.method === 'POST') {
    let body = ''
    req.on('data', (chunk) => { body += chunk })
    req.on('end', () => {
      let text = ''
      try { text = JSON.parse(body).message } catch { /* the window sends JSON */ }
      const message = {
        id: `m${ROOM_MESSAGES.length + 1}`, type: 'user', session_id: 'fixture-1',
        timestamp: new Date().toISOString(), content: text,
      }
      ROOM_MESSAGES.push(message)
      send({ message })
    })
    return undefined
  }
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
    // The second agent has written nothing yet — the explorer has to say so
    // per agent, not hide the agent.
    const sid = decodeURIComponent(url.pathname.split('/api/agents/')[1] || '').split('/')[0]
    return send({ files: sid === 'fixture-2' ? [] : FILES })
  }
  if (url.pathname.includes('/storage/')) {
    // Not scoped: the path arrives with `workspace/` in front of it, and a
    // reader that forgets the prefix gets this 404 — which is the bug this
    // fixture exists to keep fixed.
    const rel = decodeURIComponent(url.pathname.split('/storage/')[1] || '')
    if (!rel.startsWith('workspace/')) {
      res.writeHead(404, { 'Content-Type': 'application/json' })
      return res.end(JSON.stringify({ detail: `File not found: ${rel}` }))
    }
    const body = rel.endsWith('.csv') ? CSV_TEXT : rel.endsWith('.md') ? MD_TEXT : FILE_TEXT
    return send({ content: body, size: body.length, encoding: 'utf-8' })
  }
  res.writeHead(404, { 'Content-Type': 'application/json' })
  res.end('{}')
})

// The window opens the room socket. Refusing the upgrade leaves it
// reconnecting, which is its own (correct) design state and is what the unit
// tests cover in detail — so leave it. The history above is what paints.
server.listen(PORT, '127.0.0.1', () => {
  console.log(`fixture on http://127.0.0.1:${PORT}`)
})
