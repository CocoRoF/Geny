/**
 * The chat window against a REAL server.
 *
 * The headless smoke next door proves the window comes up with nothing
 * behind it. This proves the other half: that what it asks for is what the
 * server actually serves. Those are different failures — a renamed field, a
 * changed route, a response shape the fold does not recognise — and none of
 * them show up in a build.
 *
 * Manual, like `sync-prod-e2e.ts`: it needs a server and a token, so it is
 * never in CI and never in `npm test`.
 *
 *   GENY_SMOKE_URL=http://127.0.0.1:58999 \
 *   GENY_SMOKE_TOKEN=... \
 *   node tests/smoke/run.mjs --live
 *
 * It only READS unless you pass --send, because the session it would post
 * into is a real one with a real history.
 */
const { app, BrowserWindow, ipcMain } = require('electron')
const { join } = require('node:path')

const root = join(__dirname, '..', '..')
const SERVER = process.env.GENY_SMOKE_URL || ''
const TOKEN = process.env.GENY_SMOKE_TOKEN || ''
const SEND = process.argv.includes('--send')

if (!SERVER || !TOKEN) {
  console.error('✗ set GENY_SMOKE_URL and GENY_SMOKE_TOKEN')
  process.exit(2)
}

// Stand in for the main process, with just the two answers the renderer needs
// to reach a server: where it is, and who we are.
ipcMain.handle('config:get', () => ({ serverUrl: SERVER, theme: 'dark', lang: 'ko' }))
ipcMain.handle('config:set', () => ({ serverUrl: SERVER }))
ipcMain.handle('secure:get', (_e, key) => (key === 'geny_auth_token' ? TOKEN : null))
ipcMain.handle('secure:set', () => true)
ipcMain.handle('secure:delete', () => true)
ipcMain.handle('i18n:default-lang', () => 'ko')
ipcMain.handle('app:version', () => '0.0.0-smoke')
ipcMain.on('debug:log', () => undefined)

const problems = []
const EXPECTED = /Electron Security Warning/

app.on('ready', async () => {
  const win = new BrowserWindow({
    show: false,
    width: 1280,
    height: 860,
    webPreferences: {
      preload: join(root, 'out/preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  win.webContents.on('console-message', (_e, level, message) => {
    if (level >= 2 && !EXPECTED.test(message)) problems.push(message)
  })

  await win.loadFile(join(root, 'out/renderer/index.html'), { query: { window: 'control' } })
  // The window loads the session list, then its log, then opens the socket.
  await new Promise((resolve) => setTimeout(resolve, 6000))

  const probe = await win.webContents.executeJavaScript(`(() => {
    const rail = [...document.querySelectorAll('.gy-rail-item')].map((el) => el.innerText.trim())
    return {
      sessions: rail,
      railError: document.querySelector('.gy-rail-err')?.innerText ?? '',
      title: document.querySelector('.gy-chat-title')?.innerText ?? '',
      lamp: document.querySelector('.gy-lamp')?.innerText ?? '',
      route: document.querySelector('.gy-route-label')?.innerText ?? '',
      answered: document.querySelector('.gy-route-answered')?.innerText ?? '',
      turns: document.querySelectorAll('.gy-turn').length,
      tools: document.querySelectorAll('.gy-tool').length,
      composerEnabled: !document.querySelector('.gy-composer-input')?.disabled,
    }
  })()`)

  console.log('sessions      :', probe.sessions.length, probe.sessions.slice(0, 4))
  console.log('open session  :', probe.title)
  console.log('connection    :', probe.lamp)
  console.log('route         :', probe.route, probe.answered ? `(${probe.answered})` : '')
  console.log('transcript    :', probe.turns, 'turns,', probe.tools, 'tool rows')
  console.log('composer      :', probe.composerEnabled ? 'ready' : 'disabled')
  if (probe.railError) console.log('rail error    :', probe.railError)

  const failures = []
  if (probe.sessions.length === 0) failures.push('the server returned no sessions')
  if (probe.railError) failures.push(`the session list failed: ${probe.railError}`)
  if (!probe.lamp.includes('연결') && !probe.lamp.includes('실행')) {
    failures.push(`the socket never connected (lamp: ${probe.lamp})`)
  }
  if (!probe.route) failures.push('the header shows no route')
  if (probe.turns === 0) failures.push('the session log folded into no turns')
  if (!probe.composerEnabled) failures.push('the composer is disabled')

  if (SEND && failures.length === 0) {
    console.log('\nsending a message…')
    await win.webContents.executeJavaScript(`(() => {
      const box = document.querySelector('.gy-composer-input')
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set
      setter.call(box, '한 단어로만 답해: 커넥터?')
      box.dispatchEvent(new Event('input', { bubbles: true }))
      box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
      return true
    })()`)
    await new Promise((resolve) => setTimeout(resolve, 45000))
    const after = await win.webContents.executeJavaScript(`(() => ({
      turns: document.querySelectorAll('.gy-turn').length,
      last: [...document.querySelectorAll('.gy-turn--agent')].pop()?.innerText.slice(0, 160) ?? '',
      pending: document.querySelectorAll('.gy-turn--user.is-pending').length,
    }))()`)
    console.log('after send    :', after.turns, 'turns; last answer:', JSON.stringify(after.last))
    if (after.turns <= probe.turns) failures.push('the message produced no new turn')
    if (after.pending > 0) failures.push('the sent message never got adopted by the server echo')
  }

  for (const message of problems.slice(0, 5)) failures.push(`console: ${message}`)

  if (failures.length > 0) {
    console.error('\n✗ live smoke FAILED')
    for (const line of failures) console.error(`   · ${line}`)
    app.exit(1)
    return
  }
  console.log('\n✓ live smoke OK')
  app.exit(0)
})
