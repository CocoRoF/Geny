/**
 * Take a picture of the window.
 *
 * A design cannot be reviewed by reading its stylesheet. This loads the built
 * renderer with the IPC surface stubbed (optionally against a real server) and
 * writes a PNG, so the thing being judged is the thing on screen.
 *
 * GENY_SHOT_OUT=/path/shot.png  [GENY_SMOKE_URL=… GENY_SMOKE_TOKEN=…]
 *   [GENY_SHOT_WINDOW=control|settings] [GENY_SHOT_THEME=dark|light]
 *   [GENY_SHOT_CLICK='<css selector>']   click it, then wait, then capture
 *   [GENY_SHOT_SCRIPT='await click(".ab-btn"); await sleep(2000)']  several steps
 *   [GENY_SHOT_SEND=quickchat:opened]   an IPC event main would send first
 *   [GENY_SHOT_SESSION=<id>]   the session the avatar shows (quick chat, chip)
 */
const { app, BrowserWindow, ipcMain } = require('electron')
const { join } = require('node:path')
const { writeFileSync } = require('node:fs')

const root = join(__dirname, '..', '..')
const OUT = process.env.GENY_SHOT_OUT || '/tmp/geny-shot.png'
const SERVER = process.env.GENY_SMOKE_URL || ''
const TOKEN = process.env.GENY_SMOKE_TOKEN || ''
const WINDOW = process.env.GENY_SHOT_WINDOW || 'control'
const THEME = process.env.GENY_SHOT_THEME || 'dark'
const WAIT = Number(process.env.GENY_SHOT_WAIT || 6000)

// The VTuber the avatar shows — what the quick-chat bar talks to.
const AVATAR_SESSION = process.env.GENY_SHOT_SESSION || ''
ipcMain.handle('config:get', () => ({
  serverUrl: SERVER, theme: THEME, lang: 'ko', overlaySession: AVATAR_SESSION || undefined,
}))
ipcMain.handle('avatar:get-state', () => (AVATAR_SESSION ? { sessionId: AVATAR_SESSION } : null))
ipcMain.handle('config:set', () => ({ serverUrl: SERVER }))
ipcMain.handle('secure:get', (_e, key) => (key === 'geny_auth_token' ? TOKEN : null))
ipcMain.handle('secure:set', () => true)
ipcMain.handle('secure:delete', () => true)
ipcMain.handle('i18n:default-lang', () => 'ko')
ipcMain.handle('app:version', () => require(join(root, 'package.json')).version)
ipcMain.handle('system:stats', () => ({
  cpu: 24, memUsed: 8.4 * 1024 ** 3, memTotal: 15.5 * 1024 ** 3,
  appMem: 212 * 1024 ** 2, cores: 8, load1: 1.12,
}))
ipcMain.on('debug:log', () => undefined)

app.on('ready', async () => {
  const win = new BrowserWindow({
    // Shown, on the virtual display. A hidden window stops compositing, so
    // capturePage returns the frame from before the last interaction — which
    // made every screenshot of an expanded panel show it collapsed.
    show: true,
    width: Number(process.env.GENY_SHOT_W || 1280),
    height: Number(process.env.GENY_SHOT_H || 840),
    webPreferences: {
      preload: join(root, 'out/preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      // Same as the shipped control window: Chromium's PDF viewer, which is
      // what renders a PDF in the file viewer. Without it a screenshot of one
      // is a blank rectangle that says nothing about the app.
      plugins: true,
    },
  })
  await win.loadFile(join(root, 'out/renderer/index.html'), { query: { window: WINDOW } })
  if (process.env.GENY_SHOT_SEND) {
    // An event main would send — 'quickchat:opened' is what summons the bar.
    await new Promise((r) => setTimeout(r, 1500))
    win.webContents.send(process.env.GENY_SHOT_SEND)
  }
  await new Promise((r) => setTimeout(r, WAIT))
  if (process.env.GENY_SHOT_SCROLL === 'top') {
    await win.webContents.executeJavaScript(
      `(() => { const el = document.querySelector('.gy-chat-scroll'); if (el) el.scrollTop = 0; return true })()`,
    )
    await new Promise((r) => setTimeout(r, 400))
  }
  if (process.env.GENY_SHOT_CLICK) {
    const sel = JSON.stringify(process.env.GENY_SHOT_CLICK)
    const hit = await win.webContents.executeJavaScript(
      `(() => { const el = document.querySelector(${sel}); if (!el) return false; el.click(); return true })()`,
    )
    if (!hit) console.error('nothing matched', process.env.GENY_SHOT_CLICK)
    await new Promise((r) => setTimeout(r, Number(process.env.GENY_SHOT_AFTER || 3000)))
  }
  if (process.env.GENY_SHOT_SCRIPT) {
    // Several steps in the page — open a panel, expand a folder, open a file.
    // The body runs as an async function with `sleep(ms)` and `click(sel)`.
    const body = process.env.GENY_SHOT_SCRIPT
    const ok = await win.webContents.executeJavaScript(`(async () => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
      const click = (sel, text) => {
        const els = [...document.querySelectorAll(sel)]
        const el = text ? els.find((e) => (e.innerText || '').includes(text)) : els[0]
        if (!el) return false
        el.click()
        return true
      }
      ${body}
      return true
    })()`).catch((e) => String(e))
    if (ok !== true) console.error('script:', ok)
    await new Promise((r) => setTimeout(r, Number(process.env.GENY_SHOT_AFTER || 1500)))
  }
  if (process.env.GENY_SHOT_PROBE) {
    const probe = await win.webContents.executeJavaScript(process.env.GENY_SHOT_PROBE)
    console.log('PROBE', JSON.stringify(probe))
  }
  const image = await win.webContents.capturePage()
  writeFileSync(OUT, image.toPNG())
  console.log('wrote', OUT)
  app.exit(0)
})
