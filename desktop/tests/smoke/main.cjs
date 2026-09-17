/**
 * Does the main window actually come up?
 *
 * The connector's main window is a React app now, and the failure mode a
 * typecheck cannot see is the one that matters: it builds, it ships, and it
 * paints nothing because something threw on mount. Nobody notices until the
 * app is installed.
 *
 * So this loads the BUILT renderer in a real Electron window and asserts the
 * three things that have to be on screen before anything else can work — the
 * session rail, the header, the composer — and fails on any error the page
 * logs while mounting.
 *
 * It deliberately does NOT register the main process's IPC handlers. Every
 * `config:get` in here rejects, which is the point: the window has to survive
 * a backend that is not answering, because that is also what a signed-out
 * user, a stopped server and a laptop on a train all look like.
 *
 * Run: npm run smoke   (needs a display; CI uses xvfb-run)
 *
 * It is a directory with its own package.json because that is how Electron
 * is told "this is an app": handed a lone .cjs file it runs it as a plain
 * node script, where `require('electron')` has no `app` on it.
 */
const { app, BrowserWindow } = require('electron')
const { join } = require('node:path')

const root = join(__dirname, '..', '..')
const problems = []

/** Errors we cause by not being the real main process. */
const EXPECTED = /No handler registered for|Electron Security Warning/

app.on('ready', async () => {
  const win = new BrowserWindow({
    show: false,
    width: 1200,
    height: 800,
    webPreferences: {
      preload: join(root, 'out/preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  win.webContents.on('console-message', (_e, level, message) => {
    if (level >= 2 && !EXPECTED.test(message)) problems.push(message)
  })
  win.webContents.on('render-process-gone', (_e, details) => {
    problems.push(`renderer gone: ${details.reason}`)
  })

  try {
    await win.loadFile(join(root, 'out/renderer/index.html'), { query: { window: 'control' } })
  } catch (err) {
    console.error(`✗ the window would not load: ${err && err.message}`)
    app.exit(1)
    return
  }
  // React mounts, the first fetches reject, the error paths render.
  await new Promise((resolve) => setTimeout(resolve, 2500))

  const probe = await win.webContents.executeJavaScript(`(() => {
    const composer = document.querySelector('.composer-input')
    return {
      mounted: Boolean(document.querySelector('.workspace')),
      rail: Boolean(document.querySelector('.sidebar')),
      header: Boolean(document.querySelector('.chat-header')),
      footer: Boolean(document.querySelector('.system-monitor-footer')),
      composer: Boolean(composer),
      placeholder: composer ? composer.placeholder : '',
      // The window must not render its own key names at the user.
      untranslated: document.body.innerText.includes('chat.'),
    }
  })()`)

  const failures = []
  for (const part of ['mounted', 'rail', 'header', 'footer', 'composer']) {
    if (!probe[part]) failures.push(`no ${part}`)
  }
  if (!probe.placeholder) failures.push('the composer has no placeholder')
  if (probe.untranslated) failures.push('an i18n key reached the screen')
  for (const message of problems.slice(0, 5)) failures.push(`console: ${message}`)

  if (failures.length > 0) {
    console.error('✗ chat window smoke FAILED')
    for (const line of failures) console.error(`   · ${line}`)
    app.exit(1)
    return
  }
  console.log('✓ chat window smoke OK — rail, header and composer are on screen')
  app.exit(0)
})
