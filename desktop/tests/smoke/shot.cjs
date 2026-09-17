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

ipcMain.handle('config:get', () => ({ serverUrl: SERVER, theme: THEME, lang: 'ko' }))
ipcMain.handle('config:set', () => ({ serverUrl: SERVER }))
ipcMain.handle('secure:get', (_e, key) => (key === 'geny_auth_token' ? TOKEN : null))
ipcMain.handle('secure:set', () => true)
ipcMain.handle('secure:delete', () => true)
ipcMain.handle('i18n:default-lang', () => 'ko')
ipcMain.handle('app:version', () => '0.24.0')
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
    },
  })
  await win.loadFile(join(root, 'out/renderer/index.html'), { query: { window: WINDOW } })
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
  if (process.env.GENY_SHOT_PROBE) {
    const probe = await win.webContents.executeJavaScript(process.env.GENY_SHOT_PROBE)
    console.log('PROBE', JSON.stringify(probe))
  }
  const image = await win.webContents.capturePage()
  writeFileSync(OUT, image.toPNG())
  console.log('wrote', OUT)
  app.exit(0)
})
