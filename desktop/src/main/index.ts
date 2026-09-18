import { app, BrowserWindow, clipboard, desktopCapturer, dialog, globalShortcut, ipcMain, Menu, nativeImage, powerMonitor, safeStorage, screen, session, shell, Tray } from 'electron'
import { spawn } from 'child_process'
import { hostname } from 'os'
import { basename, join, sep } from 'path'
import { readFileSync, writeFileSync, mkdirSync, existsSync, unlinkSync, renameSync, cpSync, rmSync, readdirSync, lstatSync, readlinkSync, symlinkSync } from 'fs'
import { initAutoUpdate, checkForUpdatesManually, triggerBackgroundCheck } from './updater'
import { getMcpManager, type MCPServerConfig } from './mcp-manager'
import { getSyncManager, initSyncManager, type SyncPairConfig } from './sync-manager'
import { driveCapabilities } from './drive-preflight'
import { randomUUID } from 'crypto'
import { browserCall, getBrowserControl } from './browser-control'
import { getWinAutoHost, disposeWinAutoHost } from './winauto-host'
import { currentSystemStats, startSystemStats, stopSystemStats } from './system-stats'

// Tray icon (32px), embedded so it works regardless of packaging layout.
// Generated from img/Geny_Charactor_small.png (the Geny mascot).
const TRAY_ICON_B64 =
  'iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAG8UlEQVR4nL1Xe1BU1xn/zrl37967D3aX3UV2EQQWRF5RgZhCUlmmZLQ+gpZiO9VOg1Zt0qk6k3Y6Y2eyS8dpm5l2BifTpGlMqNNM0rhSi1Od6KiAiKAIGiK6vJQ3K49l2WXZ191z+ofS9o+yC9T299eZe8853+985/t+5/sA/itQBBaKAQDAQvE/x/8XVFBmYZh/6APJSrdBK5hPASgCQDT/g/Oyx46iXL/L/aoqjY9XZAd+32tOefg/IvDUKADFgBCBw8NHeModDQRJKp2Y9IFByWo369tjGfFo715128KiaLsu484QzX3j1xpKzRj/2P4m7us/6b/0eeob9DfilcON/M6kYTJzdTrO+2B4vPKzS1t3f3ihFACAUhrxkGxUuxYLhgdWVFb0l0RVvKGsvG5rJ9gf/5TcbyO6BEac1uawvxwqEZ1JakliusBIYzRbZu3d/ZR6R4FShBCK6IUlX8Frp04pY+UJG1p7dSn2uoGPtDEBFI5fi1yBWASpOuCS5VS/lsXpGoDeYd8XRbpHb8XHZ/e/mw5BiEAiCgGKoGZAijvRITI6dQPOFHTAgb5KtrfnY5XCH5ge90lYnRYkchUE00woLkdGJN5giE3V8AplqKbzFW5/BaWMDaHw8gkU17PQWCLCvo4DoNC+B5VJa+QOoPOn71xB965kETEQRopYhvoJgGY1QIwaICaGvrjdQHw+ih/Pyp5sLyM7z6yP6wBK0WJeiB4DSn6GDYY49KH9jnfEiWXiE4Ou/OWwc8gF80Oz1FhegNbmqCFOkIBpDQ/JSXJ8q208bL9MjPfH9FsAoAMagAEAcXkEGkvCABTBJrgoPJmoo098W0MMJw2ODIouZxLRaQVOUHJ0o6wnrHdSXFq5DeSsBK5fbaeuMQJm9ayzIkVz7jAAWBqAVC1iJpIHKFBAYG0QPVzOSdDqvWwyyRS9ebnFXBdXytRea2C/V/STF77Ou2Kw6Bjy44BCpBsCHNKP9XKZik8/N3VKtgKA3QxmXAVA/pORyDqAEK3IBt6y/tbDYv7qUaxkWyE9awok6M9lxq96sqQN79cYjB1fZcQzs3KBDIUYPFGYy6D16e/MdXfdb+8YuQgAYLY2riAIAWAheL5/uilJUAqSP57lnIXF/rQNG40q9fBd9c3OHX+7/uW1P8SlrDqgSNSFtHoy59Ipf7TT4Bp8RFaTc3mojUbRgiXrwJHmvhy1jGb6KV8+SeQmRHxtTT2xgdCM95ju/Hsh/EohrsyfoKF4072mcPZnmezU9vZbN7994c29MyvOAgul+IHNhhKMBTtYKVdKeWHQ5WcZRhLa/cnGhJGCWvfPFfla8rXMXcTY/C6TMR6idv26Ajkv5CAqaVGm5QkAMGOxWlHVIu/C4h54puE/a+1PCyFmR4iPSeRo6KGbcltqb7HDrm7GrQ5Pl2dt1mXpkgWi9/kQN2KnKRmyYAfKEHgy+4s/Fah/FU2IFg1CixUQIEQ9/qA0yPB5DMd5A0jyTbUUpR8sVR7btVP2dpxKmv3Y1kFbLg2iriAHo6pVcPbUbXyzXyTN3XgKAMBmjXzNkX4ioBT219UplCmFljDicqUCpxc9cyMG6rqrWaXb62cU2vbbHmXTpx0wMTGFvE6/COokDtLijoN7rhqgMAi2xU8fjQBY6utZhz9+tRDLygNszPEgwxq8flbOIirIZDITRxHHCCxMjgbR+U9GEBuvCQWIQuoLOH7429cdl89eFqda3yryRbIRMQirSkpEABgorqnns17Kr533wg9EIpS4/Cx4RueJm+VgbCwMeQmUGjbFweQjEYfZIDEkhn2esxdGW8EaaXsAWEJBYrFYcOPr5oCj+u0W6p6LeThCJ+9cd83f+esoeC48oLwYgKY2AhwH4PIhnLVGgr/7on/fDalOA1WYQJSCZMk6UFZTr9almta23JN8o/uRUMVMOSA4MYN5o5r6NQmsJoEJFySw6OUM593BQfuxmm+V3IgmQssisFCPJr0zeWlogH0V5pzBWJZI07PVsHoNHs3LUegR9oyde796R1v1ia5I4vPviP4cP0Ox5RprBjNpMs56JmaVKD2V4sxMhVMjHz+RtAp2eRAW712/eaSt+kRXtNxfEQEzmInVCvTgRXRc+8K8aU6hWX+mxXvyd/tGr/S5TWJg+Mv7Xxx8rf6Z25dkHGAZVXFVFSJ7bDZ8aruqZ9M2z95hNyBewC8NzOLB0LTjHL8ubzNCCKzL7DWW1UrZ9uwJV5yhzO0hZ1+yynPatE7YVtubN9jNZ/x9ygcOSshyG51ld0YLaygGgN3NMxvH5vginUws4ZnwIVuhaubpjOjB9xzwr/ze1Tyx/zstM8lPP0fO++cKi4XitJM9UliZJ58zVnjyfwCpDwefILK43gAAAABJRU5ErkJggg=='

// ─────────────────────────────────────────────────────────────────────────────
// Geny connector — main process.
//
// Two windows, one renderer process (so the zustand module-scope TTS-turn state
// is shared — see PLAN §4.1):
//   (A) overlay  — transparent, frameless, always-on-top, click-through. The
//                  floating avatar that sits at the bottom of the desktop.
//   (B) control  — a normal framed window (chat / settings / login), hidden by
//                  default, toggled from the tray (tray lands in Phase 2).
//
// The renderer talks to a running Geny server over the existing WS + REST
// contract ("Connector API v1"); this process only owns native concerns:
// window placement, click-through, secure token storage, server-URL config.
// ─────────────────────────────────────────────────────────────────────────────

const isDev = !app.isPackaged

// ── in-app debug log ─────────────────────────────────────────────────────────
// Ring buffer surfaced in the settings window (앱 탭 → 디버그 로그) so field
// failures are copyable by the user instead of dying in an invisible console.
// Never log secrets — use redactTok() for tokens.
const debugLines: string[] = []
function dlog(tag: string, ...parts: unknown[]): void {
  const line = `${new Date().toISOString()} [${tag}] ${parts
    .map((p) => (typeof p === 'string' ? p : JSON.stringify(p)))
    .join(' ')}`
  debugLines.push(line)
  if (debugLines.length > 600) debugLines.splice(0, debugLines.length - 600)
  console.log('[dbg]', line)
}
function redactTok(t: string | null | undefined): string {
  if (!t) return '(none)'
  return `tok(len=${t.length},head=${t.slice(0, 8)}…)`
}

// ── Windows screen-capture fix ───────────────────────────────────────────────
// The legacy desktop capturer (DXGI/GDI) renders hardware-accelerated app
// windows — Chrome, Edge, VS Code, Teams, video players, … — as BLACK,
// especially on hybrid-GPU laptops where DXGI duplication runs on a different
// adapter than the desktop and silently falls back to GDI. The agent then
// "sees" only the wallpaper + taskbar (reported: 바탕화면만 캡처됨). Forcing the
// Windows Graphics Capture (WGC) backend captures the fully-composited desktop
// — including GPU windows — on Windows 10 2004+ (build 19041) and Windows 11.
// Command-line switches must be set at module load, before app `ready`.
// (Zero-Hz WGC is intentionally NOT enabled: it suppresses frames when the
// screen is static, which would starve our on-demand single-frame grabs.)
// Linux/Wayland: desktopCapturer needs the PipeWire portal capturer —
// without it a Wayland session captures a black/empty XWayland root.
// Harmless on X11 (feature simply unused).
// (Ubuntu 24.04 sandbox handling — userns restriction vs SUID helper — lives
// in the launcher shim written by build/afterPack.cjs: the zygote's sandbox
// check runs before any app JS, so it cannot be handled here.)
// ONE CONNECTOR PER MACHINE.
//
// Without this lock a second launch — updating while the app is running,
// clicking the launcher again because the avatar is "hidden", a desktop
// autostart racing a manual start — brings up a COMPLETE second instance:
// a second avatar window, a second set of sync engines, a second tray.
// Reported as "the avatar exists twice, one of them broken", and it is
// invisible in the logs because each process writes its own.
//
// The second launch instead surfaces the windows of the one already
// running, which is what the user wanted by launching it.
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    try {
      if (overlay && !overlay.isDestroyed()) {
        if (!overlay.isVisible()) overlay.show()
        overlay.moveTop()
      }
      showControl()
    } catch {
      /* windows not built yet — the first instance is still starting */
    }
  })
}

if (process.platform === 'linux') {
  app.commandLine.appendSwitch('enable-features', 'WebRTCPipeWireCapturer')
  // Let Chromium fall back to software compositing instead of taking the
  // renderer down with the GPU process. The avatar is a small canvas; a
  // slower path is vastly better than a crash loop, and a crash loop here
  // has been observed to take the whole desktop with it.
  app.commandLine.appendSwitch('disable-gpu-watchdog')
  // FORCE X11 (XWayland when the session is Wayland).
  //
  // A Wayland client CANNOT position its own toplevel windows — the
  // protocol has no such request. Running natively on Wayland therefore
  // makes the avatar impossible to move: every setBounds/setPosition,
  // including the drag handler, is silently ignored, and always-on-top
  // is equally unavailable. The user sees an avatar that simply will not
  // respond, which is exactly the reported symptom.
  //
  // Some environments switch Electron to Wayland behind our back via
  // ELECTRON_OZONE_PLATFORM_HINT, so the switch is set explicitly AND the
  // hint is cleared. Under XWayland everything (positioning, stacking,
  // input regions) behaves like X11.
  // WebGL MUST have a software path.
  //
  // The avatar is drawn with WebGL. Recent Chromium REFUSES to fall back
  // to SwiftShader unless this switch is present — so on a machine where
  // GPU acceleration is unavailable (which forcing X11 below can cause on
  // a Wayland session), the canvas silently renders NOTHING and the
  // renderer can die outright: an empty avatar window that reloads
  // forever, exactly as reported. Slow beats absent.
  app.commandLine.appendSwitch('enable-unsafe-swiftshader')

  // FORCE X11 (XWayland when the session is Wayland) — unless the user
  // opts out with GENY_OZONE_PLATFORM=wayland.
  //
  // A Wayland client CANNOT position its own toplevel windows — the
  // protocol has no such request. Running natively on Wayland therefore
  // makes the avatar impossible to move: every setBounds/setPosition,
  // including the drag handler, is silently ignored, and always-on-top
  // is equally unavailable.
  //
  // Some environments switch Electron to Wayland behind our back via
  // ELECTRON_OZONE_PLATFORM_HINT, so the switch is set explicitly AND the
  // hint is cleared. The escape hatch exists because this trade (movable
  // window vs native-Wayland GPU path) can go the other way on some
  // machines, and a user must not be stuck with our choice.
  const ozone = process.env.GENY_OZONE_PLATFORM || 'x11'
  delete process.env.ELECTRON_OZONE_PLATFORM_HINT
  app.commandLine.appendSwitch('ozone-platform', ozone)
  app.commandLine.appendSwitch('ozone-platform-hint', ozone)
}

if (process.platform === 'win32') {
  app.commandLine.appendSwitch(
    'enable-features',
    'AllowWgcScreenCapturer,AllowWgcWindowCapturer',
  )
}

let overlay: BrowserWindow | null = null
let control: BrowserWindow | null = null
let quickchat: BrowserWindow | null = null

// ── tiny JSON config (server URL, last geometry) in userData ────────────────
interface ConnectorConfig {
  serverUrl: string
  /** UI theme for the settings + chat windows. 'system' follows the OS. */
  theme?: 'system' | 'dark' | 'light'
  /** UI language for the settings window + native chrome (tray/menu/dialogs).
   *  Unset → resolved from the OS locale (see resolvedLang). */
  lang?: 'ko' | 'en'
  /** Auto-update toggle (default true). When false, updates only notify. */
  autoUpdate?: boolean
  /** Launch the connector automatically when the user logs into the OS
   *  (default false). Applied via app.setLoginItemSettings on win/mac and a
   *  ~/.config/autostart .desktop file on Linux. */
  autoLaunch?: boolean
  /** Global push-to-talk accelerator (Electron format). */
  pttHotkey?: string
  /** Global quick-chat accelerator (Electron format) — pops the floating input
   *  bar that sends a message to the current VTuber (Spotlight-style). */
  quickChatHotkey?: string
  /** Last position of the draggable quick-chat bar (remembered between summons).
   *  Absent → it opens centered near the top of the active display. */
  quickChatBar?: { x: number; y: number }
  /** Linux-only: avatar overlay click-through opt-in (tray toggle). Persisted
   *  so the user's choice survives restarts — {forward:true} hover-unlock does
   *  not exist on Linux, so this is a deliberate all-or-nothing switch. */
  linuxClickThrough?: boolean
  /** Geny Drive — Google-Drive-style single root: every connected agent gets
   *  `<driveRoot>/<folder>/` synced with its server workspace. Absent →
   *  defaults to ~/GenyDrive on first use. */
  driveRoot?: string
  /** Install-time "Geny 클라우드 사용" choice (NSIS option / deb default).
   *  Undefined is treated as TRUE — the drive is the intended default and a
   *  config written before this field existed must not silently opt out. */
  cloudOptIn?: boolean
  /** Native virtual drive (FUSE sidecar) enabled by the user. */
  nativeMount?: boolean
  /** Folders linked INTO GenyDrive — bound to the DRIVE, not to any one
   *  agent: [폴더-GenyDrive]에 바인드되고, 드라이브에 연결된 에이전트들이
   *  [GenyDrive-에이전트] 바인딩을 통해 전부 공유한다. Each link appears
   *  as workspace/<name>/ in EVERY connected agent's workspace (web:
   *  subdirectory) and as a shortcut at the GenyDrive ROOT (local). */
  driveLinks?: Array<{ name: string; localPath: string; paused?: boolean }>
  /** Per-agent Drive membership. `folder` is allocated once (safe name from
   *  the session label) and kept stable across session renames so local
   *  paths never churn. Disabling keeps the local folder on disk. */
  /** Allow the agent to capture the screen (Phase 4). Default true.
   *  Legacy — superseded by computerUse.screen when computerUse is present. */
  captureArmed?: boolean
  /** Allow the agent to actuate the desktop — type/click/open (Phase 6). Default false.
   *  Legacy — superseded by computerUse.{input,apps,clipboard} when present. */
  automationEnabled?: boolean
  /** Local Computer Use — per-capability consent (local bridge Phase 1). When
   *  present it supersedes the legacy captureArmed/automationEnabled toggles;
   *  when absent those remain the fallback so existing installs keep working. */
  computerUse?: ComputerUseConfig
  /** Which session the floating overlay renders (chosen in the control panel). */
  overlaySession?: string
  overlay?: WinBounds & { displayId?: number }
  /** Avatar overlay geometry remembered PER MONITOR (key = display signature).
   *  Each monitor keeps its own position + size, so moving the avatar between a
   *  150% and a 100% screen restores that screen's chosen size instead of the
   *  DPI-rescaled one. */
  overlayByDisplay?: Record<string, WinBounds>
  /** Remembered window geometry (position + size) — restored across restarts,
   *  multi-monitor aware (see restoreWinBounds). */
  control?: WinBounds
  settings?: WinBounds
  /** Avatar capability tuning (set in the 음성/앱 settings tabs, applied live to
   *  the overlay's TTS/STT/screen drivers via the config:changed broadcast). */
  overlayTuning?: OverlayTuning
  /** Local MCP servers the connector hosts + proxies to the Geny agent
   *  (local bridge Phase 3). Configured in settings → MCP. */
  mcpServers?: MCPServerConfig[]
  /** Local MCP master switch — off hides every server from the agent without
   *  deleting the configs. Default true. */
  mcpEnabled?: boolean
  /** Workspace sync pairings: agent session ↔ local folder (Drive-style
   *  bidirectional replication). Managed in settings → Workspace. */
  /** Stable replica identity for the sync protocol — generated once. */
  deviceId?: string
}
interface WinBounds { x: number; y: number; width: number; height: number }
/** Consent posture for an actuation capability group. */
type ConsentMode = 'ask' | 'session' | 'auto'
/** Per-capability local-control consent. Read-only "screen" needs no prompt;
 *  the actuation groups (input/apps/clipboard) obey consentMode. */
interface ComputerUseConfig {
  /** Master — all local control is off unless this is true. Default false. */
  enabled?: boolean
  /** Read-only: screen capture + window list. Default true (when enabled). */
  screen?: boolean
  /** Input synthesis: type / key / click (+ future scroll/drag). Default true. */
  input?: boolean
  /** Open an app / URL / path + structured app control (UIA / Office COM).
   *  Default true. */
  apps?: boolean
  /** Write the clipboard. Default true. */
  clipboard?: boolean
  /** Structured browser control — a dedicated Chrome/Edge automation instance
   *  driven over CDP (browser_* tools). Default true (when enabled). */
  browser?: boolean
  /** Which engine the automation browser uses. Default 'auto' (Chrome → Edge). */
  browserEngine?: 'auto' | 'chrome' | 'edge'
  /** Consent for the actuation groups: ask every time / allow for this run /
   *  auto (no prompt). Default 'ask'. */
  consentMode?: ConsentMode
}
export interface OverlayTuning {
  ttsVolume?: number
  sttSensitivity?: number
  sttSilenceMs?: number
  sttEchoCancellation?: boolean
  sttNoiseSuppression?: boolean
  sttAutoGain?: boolean
  screenIntervalMs?: number
  screenSourceId?: string | null
  /** Show the bottom dialogue-box subtitle on the avatar overlay (default true). */
  subtitlesEnabled?: boolean
  /** Subtitle typewriter pace — ms per character (default 100 = 0.1s/char). */
  subtitleCharMs?: number
  /** TTS output device by LABEL ('' = system default; resolved in the overlay). */
  audioOutputLabel?: string
  /** Mic input device by LABEL ('' = system default). */
  audioInputLabel?: string
}
function configPath(): string {
  const dir = app.getPath('userData')
  mkdirSync(dir, { recursive: true })
  return join(dir, 'connector.json')
}
// Canonicalize a user-typed server address ONCE, at the config boundary:
// every consumer (fetch bases, overlay loadURL, sync transport, quick-chat)
// assumes a scheme-qualified URL with no trailing slash. Users type bare
// hosts ("geny.example.com") — default them to https, except obviously-local
// targets where a dev Geny runs plain http.
function normalizeServerUrl(raw: string | undefined): string {
  let s = (raw ?? '').trim()
  if (!s) return ''
  if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(s)) {
    const host = s.split('/')[0].split(':')[0]
    const local =
      host === 'localhost' || /^\d{1,3}(\.\d{1,3}){3}$/.test(host) || host.endsWith('.local')
    s = (local ? 'http://' : 'https://') + s
  }
  return s.replace(/\/+$/, '')
}
function loadConfig(): ConnectorConfig {
  try {
    const cfg = JSON.parse(readFileSync(configPath(), 'utf-8')) as ConnectorConfig
    // Migrate configs written before write-time normalization existed.
    if (cfg.serverUrl) cfg.serverUrl = normalizeServerUrl(cfg.serverUrl)
    return cfg
  } catch {
    // No personal default — the user enters their own Geny server on first run.
    // GENY_SERVER_URL lets a deployment pre-seed it without editing code.
    return { serverUrl: normalizeServerUrl(process.env.GENY_SERVER_URL) }
  }
}
/** Write the config verbatim — the only way to REMOVE a key, since
 *  saveConfig merges a patch and can therefore only add or overwrite. */
function writeConfigRaw(cfg: Record<string, unknown>): void {
  writeFileSync(configPath(), JSON.stringify(cfg, null, 2))
}

function saveConfig(patch: Partial<ConnectorConfig>): ConnectorConfig {
  if ('serverUrl' in patch) patch = { ...patch, serverUrl: normalizeServerUrl(patch.serverUrl) }
  const prevLang = loadConfig().lang
  const next = { ...loadConfig(), ...patch }
  writeFileSync(configPath(), JSON.stringify(next, null, 2))
  // Reconcile the live MCP client set when the server list changed.
  if ('mcpServers' in patch) {
    try { getMcpManager().configure(next.mcpServers) } catch { /* SDK missing */ }
  }
  // Re-localize the native chrome (tray + app menu) when the language changed —
  // the renderer persists lang via config:set, so this catches it there too.
  if ('lang' in patch && next.lang !== prevLang) {
    try { rebuildTrayMenu() } catch { /* tray not yet created */ }
    try { buildAppMenu() } catch { /* menu not yet built */ }
    // Native window title is set at creation time — refresh it live too.
    try { settings?.setTitle(nt('window.settingsTitle')) } catch { /* not created */ }
  }
  return next
}

// ── launch-on-login (system startup) ────────────────────────────────────────
// win/mac use the OS login-item API; Linux uses a ~/.config/autostart .desktop
// file (setLoginItemSettings is a no-op on Linux). Best-effort — autostart
// wiring must never crash the app.
function autostartDesktopPath(): string {
  return join(app.getPath('home'), '.config', 'autostart', 'geny-connector.desktop')
}
// Returns whether the requested state was actually applied — a refusal (e.g.
// ephemeral AppImage mount) must reach the settings UI, not just the console:
// a toggle that shows "on" while nothing was written is a silent lie.
function applyAutoLaunch(enabled: boolean): boolean {
  try {
    if (process.platform === 'linux') {
      const p = autostartDesktopPath()
      if (enabled) {
        mkdirSync(join(app.getPath('home'), '.config', 'autostart'), { recursive: true })
        // AppImage relaunches via $APPIMAGE; packaged builds via the exe path.
        // process.execPath is the REAL binary (<name>.bin behind the sandbox
        // shim, see build/afterPack.cjs) — autostart must go through the shim
        // so the sandbox decision is re-made on every boot.
        const exec = process.env.APPIMAGE || process.execPath.replace(/\.bin$/, '')
        // extract-and-run / FUSE-less launches leave APPIMAGE unset and
        // execPath inside an EPHEMERAL /tmp mount — an autostart entry
        // pointing there is dead at next boot. Refuse rather than break.
        if (/\/tmp\/(\.mount_|appimage_extracted)/.test(exec)) {
          console.warn('autoLaunch skipped: ephemeral AppImage mount path', exec)
          return false
        }
        // Desktop Entry field codes: literal % must be doubled.
        const execEsc = exec.replace(/%/g, '%%')
        writeFileSync(
          p,
          `[Desktop Entry]\nType=Application\nName=Geny\nExec="${execEsc}" --hidden\nX-GNOME-Autostart-enabled=true\nTerminal=false\nNoDisplay=false\n`,
        )
      } else if (existsSync(p)) {
        unlinkSync(p)
      }
    } else {
      // openAsHidden is honored on macOS; args flag the autostart launch.
      app.setLoginItemSettings({ openAtLogin: enabled, openAsHidden: enabled, args: ['--hidden'] })
    }
    return true
  } catch (e) {
    console.warn('autoLaunch apply failed:', (e as Error).message)
    return false
  }
}

// ── native-chrome i18n (tray / app menu / actuation dialogs) ────────────────
// The renderer settings UI has its own catalog (renderer/src/i18n.ts); this is
// the small ko/en map for the strings shown by the OS chrome. resolvedLang()
// reads config.lang, falling back to the OS locale (ko if it starts with "ko").
type Lang = 'ko' | 'en'
function osDefaultLang(): Lang {
  return app.getLocale().toLowerCase().startsWith('ko') ? 'ko' : 'en'
}
function resolvedLang(): Lang {
  return loadConfig().lang ?? osDefaultLang()
}
const NATIVE_MESSAGES: Record<string, { ko: string; en: string }> = {
  // tray menu
  'tray.openControl': { ko: '제어판 / 채팅 열기', en: 'Open control panel / chat' },
  'tray.quickChat': { ko: '빠른 채팅 (VTuber에게 보내기)', en: 'Quick chat (send to VTuber)' },
  'tray.openSettings': { ko: '설정 열기', en: 'Open settings' },
  'tray.hideAvatar': { ko: '아바타 숨기기', en: 'Hide avatar' },
  'tray.showAvatar': { ko: '아바타 보이기', en: 'Show avatar' },
  'tray.allowComputerUse': { ko: '로컬 컴퓨터 제어 허용 (화면·입력 — 세부는 설정에서)', en: 'Allow Local Computer Use (screen · input — details in settings)' },
  'tray.restoreInput': { ko: '아바타 조작 복구 (클릭이 안 될 때)', en: 'Restore avatar input (if clicks stop working)' },
  'tray.autoUpdate': { ko: '자동 업데이트', en: 'Auto-update' },
  'tray.checkUpdate': { ko: '최신버전 다운로드 (자동 설치·재시작)', en: 'Download latest version (installs & restarts)' },
  'tray.version': { ko: '버전 v{version}', en: 'Version v{version}' },
  'tray.logout': { ko: '로그아웃', en: 'Sign out' },
  'tray.restart': { ko: '재시작', en: 'Restart' },
  'tray.quit': { ko: '종료', en: 'Quit' },
  // app menu
  'menu.settings': { ko: '설정', en: 'Settings' },
  'menu.control': { ko: '제어판 / 채팅', en: 'Control panel / chat' },
  'menu.checkUpdate': { ko: '최신버전 다운로드', en: 'Download latest version' },
  'menu.restart': { ko: '재시작', en: 'Restart' },
  'menu.logout': { ko: '로그아웃', en: 'Sign out' },
  'menu.quit': { ko: '종료', en: 'Quit' },
  'menu.edit': { ko: '편집', en: 'Edit' },
  'menu.undo': { ko: '실행 취소', en: 'Undo' },
  'menu.redo': { ko: '다시 실행', en: 'Redo' },
  'menu.cut': { ko: '잘라내기', en: 'Cut' },
  'menu.copy': { ko: '복사', en: 'Copy' },
  'menu.paste': { ko: '붙여넣기', en: 'Paste' },
  'menu.selectAll': { ko: '전체 선택', en: 'Select All' },
  'menu.view': { ko: '보기', en: 'View' },
  'menu.reload': { ko: '새로고침', en: 'Reload' },
  'menu.devTools': { ko: '개발자 도구', en: 'Developer Tools' },
  'menu.resetZoom': { ko: '기본 배율', en: 'Actual Size' },
  'menu.zoomIn': { ko: '확대', en: 'Zoom In' },
  'menu.zoomOut': { ko: '축소', en: 'Zoom Out' },
  // actuation dialog
  'act.allow': { ko: '허용', en: 'Allow' },
  'act.allowSession': { ko: '이 세션 동안 허용', en: 'Allow for this session' },
  'act.deny': { ko: '거부', en: 'Deny' },
  'act.dialogTitle': { ko: 'Geny 데스크톱 제어', en: 'Geny Desktop Control' },
  'act.dialogMessage': { ko: 'Geny 가 실행하려고 합니다: {label}', en: 'Geny wants to perform: {label}' },
  'act.capOpenApp': { ko: '앱/링크 열기', en: 'Open app/link' },
  'act.capType': { ko: '타이핑', en: 'Type' },
  'act.capKey': { ko: '키 입력', en: 'Press keys' },
  'act.capClick': { ko: '마우스 클릭', en: 'Mouse click' },
  'act.capScroll': { ko: '스크롤', en: 'Scroll' },
  'act.capClipboard': { ko: '클립보드 쓰기', en: 'Write clipboard' },
  'act.detailTarget': { ko: '대상: {target}', en: 'Target: {target}' },
  'act.scrollDown': { ko: '아래', en: 'down' },
  'act.scrollUp': { ko: '위', en: 'up' },
  'act.capBrowser': { ko: '브라우저 조작', en: 'Browser control' },
  'act.capBrowserOpen': { ko: '브라우저에서 페이지 열기', en: 'Open a page in the browser' },
  'act.capBrowserEval': { ko: '브라우저에서 스크립트 실행', en: 'Run a script in the browser' },
  'act.capAppControl': { ko: '프로그램 제어', en: 'Application control' },
  'act.capOfficeControl': { ko: 'Office 문서 조작', en: 'Office document control' },
  'act.deniedByUser': { ko: '사용자가 거부함', en: 'Denied by the user' },
  'act.capDisabled': { ko: '이 동작이 꺼져 있습니다 (설정 → 로컬 컴퓨터 제어)', en: 'This action is disabled (Settings → Local Computer Use)' },
  // quick-chat delivery errors
  'qc.emptyMessage': { ko: '빈 메시지', en: 'Empty message' },
  'qc.loginRequired': { ko: '로그인이 필요합니다', en: 'Sign-in required' },
  // window titles
  'window.settingsTitle': { ko: 'Geny 설정', en: 'Geny Settings' },
}
function nt(key: string, vars?: Record<string, string | number>): string {
  const entry = NATIVE_MESSAGES[key]
  let s = entry ? entry[resolvedLang()] : key
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v))
  return s
}

// ── window geometry persistence (multi-monitor aware) ───────────────────────
// Resolve saved bounds onto a CONNECTED display. getDisplayMatching returns the
// display the saved rect overlaps most (else the nearest), so a window saved on a
// secondary monitor restores THERE — not snapped back to the primary — and a
// window whose monitor was unplugged lands visibly on the nearest one instead of
// off-screen. The rect is clamped to fit that display's work area.
function restoreWinBounds(saved: WinBounds | undefined, defaults: WinBounds): WinBounds {
  if (!saved || ![saved.x, saved.y, saved.width, saved.height].every(Number.isFinite)) return defaults
  const wa = screen.getDisplayMatching(saved).workArea
  const width = Math.max(200, Math.min(Math.round(saved.width), wa.width))
  const height = Math.max(150, Math.min(Math.round(saved.height), wa.height))
  const x = Math.round(Math.min(Math.max(saved.x, wa.x), wa.x + wa.width - width))
  const y = Math.round(Math.min(Math.max(saved.y, wa.y), wa.y + wa.height - height))
  return { x, y, width, height }
}

// While a monitor DPI change is settling, Windows RESCALES the window (WM_DPICHANGED)
// and getBounds() reports transient/rescaled values — persisting those is exactly
// how the position ends up "wrong" after a 150%↔100% move. Suppress saves until
// this timestamp (set on display-metrics-changed) so we only persist SETTLED bounds.
let dpiSettleUntil = 0

// Persist a window's geometry on move/resize (debounced). Skips minimized /
// maximized / fullscreen states, and waits out an in-flight DPI transition so the
// SETTLED bounds are saved, not the mid-rescale ones.
function attachBoundsPersistence(win: BrowserWindow, key: 'overlay' | 'control' | 'settings'): void {
  let timer: ReturnType<typeof setTimeout> | null = null
  const run = () => {
    if (win.isDestroyed() || win.isMinimized() || win.isMaximized() || win.isFullScreen()) return
    const wait = dpiSettleUntil - Date.now()
    if (wait > 0) { timer = setTimeout(run, wait + 100); return } // let the DPI rescale finish first
    const b = win.getBounds()
    saveConfig({ [key]: { x: b.x, y: b.y, width: b.width, height: b.height } } as Partial<ConnectorConfig>)
  }
  const save = () => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(run, 450)
  }
  win.on('moved', save)
  win.on('resized', save)
  win.on('closed', () => { if (timer) clearTimeout(timer) })
}

// ── avatar overlay geometry, remembered PER MONITOR ─────────────────────────
// Each display keeps its own overlay position + size, keyed by a stable-ish
// display signature. This is what stops the width/height getting distorted by a
// DPI rescale: when the overlay settles on another monitor we re-apply THAT
// monitor's remembered size instead of trusting the WM_DPICHANGED rect.
type Display = ReturnType<typeof screen.getPrimaryDisplay>
function displayKey(d: Display): string {
  return `${d.bounds.x},${d.bounds.y}:${d.size.width}x${d.size.height}@${d.scaleFactor}`
}
function overlayCurrentDisplay(): Display | null {
  if (!overlay || overlay.isDestroyed()) return null
  return screen.getDisplayMatching(overlay.getBounds())
}
let lastOverlayDisplayKey = ''
let overlayGeomTimer: ReturnType<typeof setTimeout> | null = null
function saveOverlayGeometry(): void {
  if (overlayGeomTimer) clearTimeout(overlayGeomTimer)
  const run = () => {
    if (!overlay || overlay.isDestroyed() || overlay.isMinimized()) return
    const wait = dpiSettleUntil - Date.now()
    if (wait > 0) { overlayGeomTimer = setTimeout(run, wait + 100); return }
    const d = overlayCurrentDisplay(); if (!d) return
    const b = overlay.getBounds()
    const bounds: WinBounds = { x: b.x, y: b.y, width: b.width, height: b.height }
    const cfg = loadConfig()
    saveConfig({ overlayByDisplay: { ...(cfg.overlayByDisplay || {}), [displayKey(d)]: bounds }, overlay: bounds })
  }
  overlayGeomTimer = setTimeout(run, 450)
}
// On launch: apply the geometry remembered for whichever display the overlay is on.
function restoreOverlayGeometry(): void {
  if (!overlay || overlay.isDestroyed()) return
  const d = overlayCurrentDisplay(); if (!d) return
  lastOverlayDisplayKey = displayKey(d)
  const saved = loadConfig().overlayByDisplay?.[displayKey(d)] ?? loadConfig().overlay
  if (saved) overlay.setBounds(restoreWinBounds(saved, saved))
}
// After a move settles on a DIFFERENT monitor, snap to that monitor's remembered
// SIZE (keeping the dropped position). Fixes the DPI-move size distortion.
function applyOverlaySizeOnCross(): void {
  if (!overlay || overlay.isDestroyed()) return
  const d = overlayCurrentDisplay(); if (!d) return
  const key = displayKey(d)
  if (key === lastOverlayDisplayKey) return
  lastOverlayDisplayKey = key
  const saved = loadConfig().overlayByDisplay?.[key]
  if (!saved) { saveOverlayGeometry(); return } // first time on this monitor → remember it
  const wa = d.workArea
  const width = Math.min(saved.width, wa.width)
  const height = Math.min(saved.height, wa.height)
  const b = overlay.getBounds()
  const x = Math.round(Math.min(Math.max(b.x, wa.x), wa.x + wa.width - width))
  const y = Math.round(Math.min(Math.max(b.y, wa.y), wa.y + wa.height - height))
  overlay.setBounds({ x, y, width, height })
}
// Authoritative drag rect: during a dock-handle drag we track the overlay's
// intended bounds in JS and re-assert a CONSTANT size each frame, instead of
// reading getBounds() (which drifts + grows the window on fractional DPI). See
// the 'overlay:move-by' handler for the full rationale.
let overlayMoveRect: { x: number; y: number; w: number; h: number } | null = null
let overlayMoveIdle: ReturnType<typeof setTimeout> | null = null
function endOverlayMove(): void {
  if (overlayMoveIdle) { clearTimeout(overlayMoveIdle); overlayMoveIdle = null }
  overlayMoveRect = null
  onOverlayMoved() // reconcile size-on-cross + persist the settled bounds
}

// 'moved' fires during a drag + on the DPI cross; debounce, wait out the DPI
// rescale, THEN reconcile size-on-cross and persist.
let overlayMovedTimer: ReturnType<typeof setTimeout> | null = null
function onOverlayMoved(): void {
  if (overlayMovedTimer) clearTimeout(overlayMovedTimer)
  const run = () => {
    const wait = dpiSettleUntil - Date.now()
    if (wait > 0) { overlayMovedTimer = setTimeout(run, wait + 100); return }
    applyOverlaySizeOnCross()
    saveOverlayGeometry()
  }
  overlayMovedTimer = setTimeout(run, 350)
}

// Any overlap with a work area = still (at least partly) visible.
function isVisibleOnSomeDisplay(b: WinBounds): boolean {
  return screen.getAllDisplays().some((d) => {
    const wa = d.workArea
    const ix = Math.min(b.x + b.width, wa.x + wa.width) - Math.max(b.x, wa.x)
    const iy = Math.min(b.y + b.height, wa.y + wa.height) - Math.max(b.y, wa.y)
    return ix > 0 && iy > 0
  })
}

// When a monitor is unplugged / rearranged, a window that was on it can end up
// entirely off-screen (invisible, "lost"). Pull only those windows back onto the
// nearest display — leave still-visible windows exactly where the user put them.
function ensureWindowsOnScreen(): void {
  for (const win of [overlay, control, settings, quickchat]) {
    if (!win || win.isDestroyed()) continue
    const b = win.getBounds()
    if (isVisibleOnSomeDisplay(b)) continue
    win.setBounds(restoreWinBounds(b, b))
  }
}

// Reset every window to its default position/size on the primary display, clear
// the remembered geometry, and reset the avatar's in-canvas pan/zoom. The escape
// hatch when a multi-monitor / DPI mess leaves things off-screen or broken.
function resetWindowPositions(): void {
  saveConfig({ overlay: undefined, overlayByDisplay: undefined, control: undefined, settings: undefined, quickChatBar: undefined } as Partial<ConnectorConfig>)
  lastOverlayDisplayKey = ''
  const wa = screen.getPrimaryDisplay().workArea
  const centered = (w: number, h: number) => ({
    x: Math.round(wa.x + (wa.width - w) / 2),
    y: Math.round(wa.y + (wa.height - h) / 2),
    width: w,
    height: h,
  })
  if (overlay && !overlay.isDestroyed()) {
    const w = 420
    const h = Math.round(wa.height * 0.45)
    overlay.setBounds({ x: wa.x + wa.width - w - 24, y: wa.y + wa.height - h, width: w, height: h })
    overlay.show()
    overlay.webContents.send('overlay:reset-view') // reset avatar pan/zoom (localStorage view)
  }
  if (control && !control.isDestroyed()) control.setBounds(centered(640, 760))
  if (settings && !settings.isDestroyed()) settings.setBounds(centered(640, 720))
  // quick-chat re-centers on its next summon now that quickChatBar is cleared.
}

// Keep a window in the 'screen-saver' top band even as OTHER processes churn
// the z-order. A one-shot setAlwaysOnTop decays on Windows — but only through
// OBSERVABLE transitions, so this is purely event-driven (zero idle cost, no
// polling):
//   · An ordinary window — even maximized — can NEVER cover a TOPMOST one, so
//     "opened another app and the avatar sank" always means a fullscreen /
//     borderless transition or a stripped TOPMOST bit was involved.
//   · Fullscreen & borderless toggles hide the taskbar / change the work area
//     → `display-metrics-changed` fires. DPI moves fire it too.
//   · The OS stripping the bit surfaces as `always-on-top-changed(false)`.
//   · Our own focus churn (user clicks our windows then away) → blur/show/
//     restore.
// Each trigger asserts twice: immediately, and once more shortly after via a
// ONE-SHOT timer (transitions finish after the event; the second pass lands
// on the settled z-order). setAlwaysOnTop/moveTop are cheap SetWindowPos
// calls — no-ops when already top, never steal focus, no flicker.
function armAlwaysOnTop(win: BrowserWindow, after?: () => void): void {
  let settle: ReturnType<typeof setTimeout> | null = null
  const assertNow = (): void => {
    if (win.isDestroyed() || !win.isVisible() || win.isMinimized()) return
    try {
      win.setAlwaysOnTop(true, 'screen-saver')
      if (process.platform === 'darwin') {
        win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
      }
      win.moveTop() // top of the topmost band — above later-created topmost peers
    } catch {
      /* window mid-teardown */
    }
    // Anything that must sit ABOVE this window has to be raised again
    // right after — moveTop() just put this one on top of its whole band.
    after?.()
  }
  const assert = (): void => {
    assertNow()
    if (settle) clearTimeout(settle)
    settle = setTimeout(() => {
      settle = null
      assertNow()
    }, 900)
  }
  assertNow()
  win.on('show', assert)
  win.on('restore', assert)
  // Focus moved elsewhere — exactly when another window may have claimed the
  // top of the topmost band.
  win.on('blur', assert)
  // The OS actively stripped the bit (fullscreen/DPI transitions do this).
  win.on('always-on-top-changed', (_e, isOnTop) => {
    if (!isOnTop) assert()
  })
  // Display topology / fullscreen-driven metric changes (taskbar hide, work-
  // area, DPI) — the signal that fires when another app goes fullscreen.
  const onMetrics = (): void => assert()
  screen.on('display-metrics-changed', onMetrics)
  win.on('closed', () => {
    if (settle) clearTimeout(settle)
    screen.removeListener('display-metrics-changed', onMetrics)
  })
}

// ── overlay window: the floating avatar ─────────────────────────────────────
function createOverlay(): void {
  const wa = screen.getPrimaryDisplay().workArea
  const defW = 420
  const defH = Math.round(wa.height * 0.45)
  // Restore the remembered geometry onto whichever monitor it was on (multi-
  // monitor aware); default to the bottom-right of the primary work area.
  const b = restoreWinBounds(loadConfig().overlay, {
    width: defW,
    height: defH,
    x: wa.x + wa.width - defW - 24,
    y: wa.y + wa.height - defH,
  })

  overlay = new BrowserWindow({
    width: b.width,
    height: b.height,
    x: b.x,
    y: b.y,
    transparent: true,
    frame: false,
    resizable: true,
    movable: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: join(__dirname, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      // Keep the avatar ticking at full FPS even when occluded/unfocused —
      // presence (blink/idle/saccade) must not stutter. RAM is bounded by the
      // renderer's own FPS cap.
      backgroundThrottling: false,
    },
  })

  // Float above full-screen apps and STAY there — one-shot always-on-top
  // decays on Windows as other processes churn the z-order (see
  // armAlwaysOnTop); this asserts now and keeps re-asserting for the
  // window's lifetime.
  // The chip carries the ONLY controls a locked avatar has, so it must
  // never end up behind it. The avatar re-asserts always-on-top for its
  // lifetime (moveTop puts it above its whole band, chip included), so
  // every assert re-raises the chip immediately afterwards.
  armAlwaysOnTop(overlay, raiseChip)

  // The chip is a separate window, so it has to be told to follow. Move and
  // resize fire continuously during a drag; setBounds on an unchanged rect
  // is cheap, and syncing every frame is what keeps the chip from lagging
  // behind the avatar it belongs to.
  overlay.on('move', syncChipBounds)
  overlay.on('resize', syncChipBounds)
  overlay.on('show', applyChipVisibility)
  overlay.on('hide', applyChipVisibility)
  overlay.on('closed', () => {
    try {
      overlayChip?.destroy()
    } catch { /* already gone */ }
    overlayChip = null
  })

  // External links open in the OS browser, never inside the overlay.
  overlay.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // Content depends on login state: the remote transparent /overlay avatar page
  // once a token exists, otherwise a local "log in first" placeholder.
  attachContentResilience(
    overlay,
    () => void applyOverlayContent(),
    () => {
      // Repeated renderer death (a GPU/WebGL failure, typically): stop
      // reloading the avatar page and show the local placeholder instead.
      // A visible, working window beats an invisible loop that eats the
      // machine.
      overlayFellBack = true
      overlayLocked = false
      applyOverlayInput()
      applyChipVisibility()
      if (overlay && !overlay.isDestroyed()) loadRoute(overlay, 'overlay')
    },
  )
  // Per-monitor geometry: restore this display's remembered bounds, and on every
  // move/resize reconcile size-on-cross + persist per display.
  restoreOverlayGeometry()
  overlay.on('moved', onOverlayMoved)
  overlay.on('resized', saveOverlayGeometry)
  applyOverlayContent()

  overlay.on('closed', () => {
    overlay = null
  })
}

// ── control window: chat / settings / login (hidden until toggled) ──────────
function createControl(): void {
  const wa = screen.getPrimaryDisplay().workArea
  const b = restoreWinBounds(loadConfig().control, {
    width: 1120, height: 780,
    x: Math.round(wa.x + (wa.width - 1120) / 2),
    y: Math.round(wa.y + (wa.height - 780) / 2),
  })
  control = new BrowserWindow({
    width: b.width,
    height: b.height,
    x: b.x,
    y: b.y,
    minWidth: 760,
    minHeight: 520,
    show: false,
    title: 'Geny',
    webPreferences: {
      preload: join(__dirname, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      // Chromium's own PDF viewer, which is what renders a PDF the agent
      // wrote when you open it from the explorer. It is off by default and
      // an <embed> of a PDF is then a blank rectangle. Nothing else is
      // enabled by this, and the window still has no node and no shared
      // context with the page.
      plugins: true,
    },
  })
  control.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })
  attachContentResilience(control, () => void applyControlContent())
  attachBoundsPersistence(control, 'control')
  applyControlContent()
  control.on('close', (e) => {
    // Hide instead of destroy so the single renderer process persists.
    // If the tray failed to appear there is no way to re-open a hidden
    // window (and no single-instance lock to piggyback on) — closing the
    // LAST visible UI surface must quit instead of stranding a zombie app.
    if (!appQuitting) {
      if (!tray && !settings?.isVisible()) {
        app.quit()
        return
      }
      e.preventDefault()
      control?.hide()
    }
  })
}

// Control window content: the connector's OWN chat workspace.
//
// This used to load the server's /connector web page — the app was a browser
// pointed at the app. Everything a user comes to this window for (which model
// answered, what the agent just ran, what it changed on disk) lives in the
// renderer now, over the same execute socket the phone uses. The window keeps
// its identity, its bounds and its tray entry; only what is inside changed.
//
// The content is local, so it loads whether or not there is a token — there
// is nothing to fetch and nothing to fail. Which window the user actually
// SEES is still decided by refreshAll(): signed out, this one stays hidden
// and Settings takes the screen.
async function applyControlContent(): Promise<void> {
  if (!control) return
  const token = await getStoredToken()
  dlog('control', `chat workspace (token=${token ? 'yes' : 'no'})`)
  loadRoute(control, 'control')
}

// ── settings window: server URL / account / auto-update (local, always open) ─
let settings: BrowserWindow | null = null
function createSettings(): void {
  const wa = screen.getPrimaryDisplay().workArea
  const b = restoreWinBounds(loadConfig().settings, {
    width: 640, height: 720,
    x: Math.round(wa.x + (wa.width - 640) / 2),
    y: Math.round(wa.y + (wa.height - 720) / 2),
  })
  settings = new BrowserWindow({
    width: b.width,
    height: b.height,
    x: b.x,
    y: b.y,
    minWidth: 560,
    minHeight: 600,
    show: false,
    title: nt('window.settingsTitle'),
    webPreferences: {
      preload: join(__dirname, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  attachContentResilience(settings, () => settings && loadRoute(settings, 'settings'))
  attachBoundsPersistence(settings, 'settings')
  loadRoute(settings, 'settings')
  settings.on('close', (e) => {
    // Same tray-less rule as the control window: closing the last visible
    // UI surface with no tray to summon it back means quit, not zombie.
    if (!appQuitting) {
      if (!tray && !control?.isVisible()) {
        app.quit()
        return
      }
      e.preventDefault()
      settings?.hide()
    }
  })
}
function showSettings(): void {
  if (!settings) createSettings()
  settings?.show()
  settings?.focus()
}

// ── quick-chat window: Spotlight-style floating input ───────────────────────
// A small, frameless, transparent, always-on-top input bar summoned by a global
// hotkey from anywhere. Typing + Enter sends the message to the CURRENT VTuber
// (the overlaySession) by relaying it to the already-loaded /connector chat —
// reusing its proven send/auth/TTS pipeline (no duplicate transport).
const QUICKCHAT_W = 640
const QUICKCHAT_H = 188
// Content-driven growth cap (multi-line text + image thumbnails).
const QUICKCHAT_MAX_H = 480
// When the bar was last summoned — used to swallow the spurious `blur` that a
// focused full-screen game fires immediately after we show (so the bar doesn't
// vanish before the user can type).
let quickChatShownAt = 0
// The bar is a PERMANENTLY-shown top-most window (like the avatar overlay) — we
// only toggle its visibility via opacity + click-through, never hide()/show().
// This is the load-bearing fix for surfacing over a borderless full-screen game:
// re-showing a hidden window won't place it above a game that's already full-
// screen, but a window that claimed the top band BEFORE the game did stays above
// it. `quickChatOpen` tracks the summoned/dismissed state (isVisible() is always
// true now).
let quickChatOpen = false
function createQuickChat(): void {
  quickchat = new BrowserWindow({
    width: QUICKCHAT_W,
    height: QUICKCHAT_H,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    movable: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: join(__dirname, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      // Match the avatar overlay exactly (it surfaces over Skyrim): keep the
      // renderer ticking even while unfocused/occluded.
      backgroundThrottling: false,
    },
  })
  // Float above full-screen apps — same armed recipe as the avatar overlay
  // ('screen-saver' band + lifetime re-assertion; visibleOnFullScreen is
  // macOS-only inside armAlwaysOnTop). One caveat handled there: assert is a
  // no-op while hidden, and the 'show' hook re-asserts on every open.
  armAlwaysOnTop(quickchat)
  attachContentResilience(quickchat, () => quickchat && loadRoute(quickchat, 'quickchat'))
  loadRoute(quickchat, 'quickchat')
  // Dismiss on focus loss (click elsewhere) — Spotlight behaviour. But ignore the
  // spurious blur a focused full-screen game fires right after we show (we may
  // not win focus on the first frame); real click-away dismissal still works
  // once the short grace window elapses.
  quickchat.on('blur', () => {
    if (!quickChatOpen) return
    if (Date.now() - quickChatShownAt < 450) return
    dismissQuickChat()
  })
  // Remember where the user drags the bar. 'move' streams during the drag
  // (Win/Linux) and 'moved' lands once it settles (macOS); debounce both so we
  // persist the final spot without hammering the config file mid-drag.
  quickchat.on('move', persistQuickChatPos)
  quickchat.on('moved', persistQuickChatPos)
  quickchat.on('close', (e) => {
    if (!appQuitting) {
      e.preventDefault()
      dismissQuickChat()
    }
  })
  // Establish the window ON-SCREEN, shown, top-most and click-through at launch —
  // exactly like the avatar overlay (which surfaces over borderless full-screen
  // games). It claims the 'screen-saver' top band BEFORE any game goes full-screen
  // and then stays put; the renderer paints nothing until summoned. showInactive()
  // so we don't steal focus from whatever the user is doing at launch.
  positionQuickChat()
  // Dismissed = click-through on EVERY platform. Unlike the avatar overlay,
  // quick-chat needs no hover unlock — the hotkey summon path flips it
  // interactive explicitly — so Linux can stay click-through too (an
  // interactive invisible bar would silently eat a 640×188 hole of clicks).
  quickchat.setIgnoreMouseEvents(true, IS_LINUX ? undefined : { forward: true })
  quickchat.showInactive()
}

// Hide the bar WITHOUT touching the window: the window stays shown, on-screen and
// top-most (so it keeps its z-order above a full-screen game); the RENDERER just
// stops painting the card, and we make the window click-through. This mirrors the
// avatar overlay exactly — a persistent transparent top-most window whose content
// is what appears/disappears, never the window itself. (Hiding / moving off-screen
// / opacity all failed to layer above a game that went full-screen after launch.)
function dismissQuickChat(): void {
  if (!quickchat) return
  quickChatOpen = false
  // Click-through on Linux as well — see createQuickChat.
  quickchat.setIgnoreMouseEvents(true, IS_LINUX ? undefined : { forward: true })
  quickchat.webContents.send('quickchat:dismissed')
}

let quickChatPosTimer: ReturnType<typeof setTimeout> | null = null
let suppressQuickChatPosSave = false
function persistQuickChatPos(): void {
  // Ignore the programmatic setBounds in positionQuickChat — only user drags.
  if (suppressQuickChatPosSave) return
  if (quickChatPosTimer) clearTimeout(quickChatPosTimer)
  quickChatPosTimer = setTimeout(() => {
    if (!quickchat || !quickChatOpen) return
    const b = quickchat.getBounds()
    saveConfig({ quickChatBar: { x: b.x, y: b.y } })
  }, 350)
}

// Place the bar: restore the user's remembered spot (clamped onto a visible
// display in case monitors changed), else center it near the top of the display
// under the cursor (classic launcher placement).
function positionQuickChat(): void {
  if (!quickchat) return
  suppressQuickChatPosSave = true
  const saved = loadConfig().quickChatBar
  if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
    // Multi-monitor aware: restore onto whichever display the bar was on, clamped
    // to fit (guards a closed/moved monitor). Size is fixed (QUICKCHAT_W/H).
    const rect = { x: saved.x, y: saved.y, width: QUICKCHAT_W, height: QUICKCHAT_H }
    const b = restoreWinBounds(rect, rect)
    quickchat.setBounds({ x: b.x, y: b.y, width: QUICKCHAT_W, height: QUICKCHAT_H })
  } else {
    const pt = screen.getCursorScreenPoint()
    const wa = screen.getDisplayNearestPoint(pt).workArea
    const x = Math.round(wa.x + (wa.width - QUICKCHAT_W) / 2)
    const y = Math.round(wa.y + wa.height * 0.22)
    quickchat.setBounds({ x, y, width: QUICKCHAT_W, height: QUICKCHAT_H })
  }
  // Re-arm persistence after the programmatic move settles.
  setTimeout(() => { suppressQuickChatPosSave = false }, 120)
}

// Summon the bar: the window is ALREADY shown + top-most on-screen, so we only
// re-assert the top band, make it interactive, raise + focus it, and tell the
// renderer to paint the card. No hide()/show(), no move, no opacity — the window
// claimed the top band at launch (before any game went full-screen) and never
// left, exactly like the avatar overlay, so it stays above the game. Focus works
// because we're triggered by a global hotkey (user input). (True EXCLUSIVE-
// fullscreen DirectX bypasses the compositor and needs injection; borderless /
// windowed-fullscreen works.)
function showQuickChatOnTop(): void {
  if (!quickchat) return
  quickChatOpen = true
  quickChatShownAt = Date.now()
  quickchat.setAlwaysOnTop(true, 'screen-saver')
  if (process.platform === 'darwin') {
    quickchat.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  }
  quickchat.setIgnoreMouseEvents(false)
  quickchat.moveTop()
  // Paint the bar FIRST so it's visible immediately (grabbing OS focus up-front
  // makes a borderless game reclaim the foreground and repaint over us — that's
  // what kept the bar from showing in earlier builds).
  quickchat.webContents.send('quickchat:opened')
  // THEN, a tick later, take keyboard focus so the user can type without clicking,
  // and re-raise right after in case the focus transfer let the game repaint for a
  // frame. The bar is already established/visible by now, so this no longer hides
  // it. The renderer re-focuses its input on the window 'focus' event.
  setTimeout(() => {
    if (!quickchat || !quickChatOpen) return
    quickchat.focus()
    quickchat.moveTop()
  }, 110)
}

async function toggleQuickChat(): Promise<void> {
  if (!quickchat) createQuickChat()
  if (quickChatOpen) {
    dismissQuickChat()
    return
  }
  // Logged-out → there's no VTuber to message; route the user to login instead.
  const token = await getStoredToken()
  if (!token || !loadConfig().serverUrl) {
    showSettings()
    return
  }
  positionQuickChat()
  showQuickChatOnTop()
}

// Relay a quick-chat message to the current VTuber via the /connector page's
// existing chat send. Returns whether it was delivered (false → not logged in /
// panel not ready, so the bar can surface a hint).
interface QuickChatPayload {
  text: string
  images?: Array<{ name: string; type: string; dataUrl: string }>
}

const QC_MAX_IMAGES = 4
// data URL overhead ≈ 4/3 of raw bytes; 14 MiB string ≈ 10 MiB image.
const QC_MAX_DATAURL_CHARS = 14 * 1024 * 1024

function sanitizeQuickImages(images: unknown): QuickChatPayload['images'] {
  if (!Array.isArray(images)) return undefined
  const out: NonNullable<QuickChatPayload['images']> = []
  for (const img of images.slice(0, QC_MAX_IMAGES)) {
    if (!img || typeof img !== 'object') continue
    const { name, type, dataUrl } = img as Record<string, unknown>
    if (typeof dataUrl !== 'string' || !dataUrl.startsWith('data:image/')) continue
    if (dataUrl.length > QC_MAX_DATAURL_CHARS) continue
    out.push({
      name: typeof name === 'string' && name ? name.slice(0, 200) : 'pasted.png',
      type: typeof type === 'string' && type.startsWith('image/') ? type : 'image/png',
      dataUrl,
    })
  }
  return out.length ? out : undefined
}

async function deliverQuickChat(
  payload: string | QuickChatPayload,
): Promise<{ ok: boolean; error?: string }> {
  // Accept both the structured form and the legacy bare string.
  const raw = typeof payload === 'string' ? { text: payload } : payload ?? { text: '' }
  const body = (raw.text ?? '').trim()
  const images = sanitizeQuickImages(raw.images)
  if (!body && !images) return { ok: false, error: nt('qc.emptyMessage') }
  const token = await getStoredToken()
  if (!token || !loadConfig().serverUrl) return { ok: false, error: nt('qc.loginRequired') }
  const fresh = !control
  if (!control) createControl()
  // A window created a moment ago has not mounted its listener yet, and an
  // early send is dropped with no sign that it was.
  if (fresh) await new Promise((r) => setTimeout(r, 450))
  control!.webContents.send('connector:quick-send', { text: body, images })
  return { ok: true }
}

// Re-evaluate everything after login/logout/url-change: window content + which
// window is visible.
// Autostart launches pass --hidden (written by applyAutoLaunch /
// setLoginItemSettings): start in the tray without popping any window.
// Consumed once — later explicit refreshes behave normally.
let startHidden = process.argv.includes('--hidden')

async function refreshAll(): Promise<void> {
  dlog('refresh', `begin serverUrl=${loadConfig().serverUrl || '(empty)'}`)
  await applyOverlayContent()
  await applyControlContent()
  if (startHidden) {
    startHidden = false
    dlog('refresh', 'startHidden → staying in tray')
    return
  }
  const token = await getStoredToken()
  dlog('refresh', `windows: token=${token ? 'yes' : 'no'} → ${token ? 'control' : 'settings'}`)
  if (token) {
    settings?.hide()
    control?.show()
  } else {
    control?.hide()
    showSettings()
  }
}

function loadRoute(win: BrowserWindow, route: 'overlay' | 'control' | 'settings' | 'quickchat' | 'chip'): void {
  if (isDev && process.env.ELECTRON_RENDERER_URL) {
    win.loadURL(`${process.env.ELECTRON_RENDERER_URL}/index.html?window=${route}`)
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'), { query: { window: route } })
  }
  // External links open in the OS browser, never inside the overlay.
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })
}

// ── Self-healing window content ─────────────────────────────────────────────
// A window must NEVER be left dead requiring a manual app restart. This recovers
// a window's content from the two ways it can break without us noticing:
//   • did-fail-load — the server/page was unreachable (server restart, network
//     blip, sleep/wake, the brief window right after an auto-update relaunch).
//     Retry `reload` with capped exponential backoff until it loads (a transient
//     outage self-heals the moment the server returns — no restart needed).
//   • render-process-gone — the renderer crashed / was OOM-killed. Rebuild it.
// `reload` rebuilds the RIGHT content (applyOverlayContent / applyControlContent
// re-evaluate login state; loadRoute reloads a local route).
function attachContentResilience(
  win: BrowserWindow,
  reload: () => void,
  onCrashLoop?: () => void,
): void {
  const wc = win.webContents
  let retries = 0
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  const clearRetry = () => {
    if (retryTimer) { clearTimeout(retryTimer); retryTimer = null }
  }
  wc.on('did-finish-load', () => {
    retries = 0
    clearRetry()
    dlog('load', `${win.getTitle() || 'win'} finished ${wc.getURL().replace(/token=[^&]+/, 'token=…')}`)
  })
  wc.on('did-fail-load', (_e, errorCode, errorDesc, url, isMainFrame) => {
    if (!isMainFrame) return        // ignore subresource failures
    if (errorCode === -3) return    // ERR_ABORTED — a superseding navigation, not a failure
    clearRetry()
    const delay = Math.min(2000 * Math.pow(1.6, retries), 20000) // 2s → cap 20s
    retries = Math.min(retries + 1, 10)
    dlog('load', `${win.getTitle() || 'win'} FAILED ${errorCode} ${errorDesc} url=${url.replace(/token=[^&]+/, 'token=…')} retry in ${Math.round(delay)}ms`)
    retryTimer = setTimeout(() => { if (!win.isDestroyed()) reload() }, delay)
  })
  // CRASH-LOOP BREAKER.
  //
  // This used to reload IMMEDIATELY, with no delay and with the retry
  // counter reset — so a page that dies on load (a GPU/WebGL failure is
  // the usual cause for the avatar) came straight back, died again, and
  // span forever. Every turn of that loop spawns a fresh renderer and a
  // fresh batch of GPU work, which is how an app bug turns into a frozen
  // MACHINE. Reported from the field exactly that way.
  //
  // So: back off like any other failure, and after a few crashes in a
  // short window STOP retrying the remote page and fall back to the local
  // placeholder — which needs no GPU and lets the user reach the tray,
  // settings and logs instead of watching a dead loop.
  let crashes = 0
  let crashWindowStart = 0
  wc.on('render-process-gone', (_e, details) => {
    if (details.reason === 'clean-exit') return
    clearRetry()
    const now = Date.now()
    if (now - crashWindowStart > 60_000) {
      crashWindowStart = now
      crashes = 0
    }
    crashes += 1
    if (crashes > 3) {
      dlog('load', `renderer gone (${details.reason}) x${crashes} — giving up on the remote page`)
      onCrashLoop?.()
      return
    }
    const delay = Math.min(1500 * Math.pow(2, crashes - 1), 15000)
    dlog('load', `renderer gone (${details.reason}); reload in ${delay}ms (${crashes}/3)`)
    retryTimer = setTimeout(() => { if (!win.isDestroyed()) reload() }, delay)
  })
  wc.on('destroyed', clearRetry)
}

// ── secure secret store (Electron safeStorage; replaces keytar) ─────────────
// keytar was a native-ABI landmine: a wrong-platform keytar.node, a missing
// Secret Service, or a locked keyring made set/getPassword fail — and login
// could then never persist (observed in the field: "login succeeds, nothing
// happens / logged out after restart"). safeStorage is built into Electron
// (win32 DPAPI · macOS Keychain · Linux kwallet/gnome-keyring with a
// basic_text fallback): no native module, no ABI, and it ALWAYS has a
// working backend. Secrets live encrypted in userData/secure-store.json
// (0600); a value the OS can no longer decrypt just reads as null → re-login.
const TOKEN_KEY = 'geny_auth_token'
function secretsPath(): string {
  return join(app.getPath('userData'), 'secure-store.json')
}
function readSecretsFile(): Record<string, string> {
  try {
    return JSON.parse(readFileSync(secretsPath(), 'utf-8'))
  } catch {
    return {}
  }
}
function secureSet(key: string, value: string): boolean {
  try {
    const enc = safeStorage.isEncryptionAvailable()
    const payload = enc
      ? `enc:${safeStorage.encryptString(value).toString('base64')}`
      : // Never brick login over missing encryption (exotic Linux setups):
        // an obfuscated-plaintext token beats a connector nobody can log into.
        `raw:${Buffer.from(value, 'utf-8').toString('base64')}`
    const all = readSecretsFile()
    all[key] = payload
    writeFileSync(secretsPath(), JSON.stringify(all), { mode: 0o600 })
    dlog('secure', `set ${key} ok (backend=${enc ? 'safeStorage' : 'raw-fallback'})`)
    return true
  } catch (e) {
    dlog('secure', `set ${key} FAILED: ${(e as Error)?.message}`)
    return false
  }
}
// Log reads only when the outcome CHANGES (sync polls this often).
const lastGetOutcome = new Map<string, boolean>()
function secureGet(key: string): string | null {
  let out: string | null = null
  try {
    const v = readSecretsFile()[key]
    if (v?.startsWith('enc:')) out = safeStorage.decryptString(Buffer.from(v.slice(4), 'base64'))
    else if (v?.startsWith('raw:')) out = Buffer.from(v.slice(4), 'base64').toString('utf-8')
  } catch (e) {
    dlog('secure', `get ${key} FAILED: ${(e as Error)?.message}`)
    return null
  }
  if (lastGetOutcome.get(key) !== !!out) {
    lastGetOutcome.set(key, !!out)
    dlog('secure', `get ${key} → ${redactTok(out)}`)
  }
  return out
}
function secureDelete(key: string): boolean {
  try {
    const all = readSecretsFile()
    delete all[key]
    writeFileSync(secretsPath(), JSON.stringify(all), { mode: 0o600 })
    return true
  } catch {
    return false
  }
}

// Read the account JWT the control window stored.
async function getStoredToken(): Promise<string | null> {
  return secureGet(TOKEN_KEY)
}
async function storeToken(token: string): Promise<void> {
  secureSet(TOKEN_KEY, token)
}
async function clearStoredToken(): Promise<void> {
  secureDelete(TOKEN_KEY)
}

// Keep the connector logged in across restarts. The stored JWT is reused on
// every launch; this validates it and — crucially — mints a FRESH-expiry token
// (so the clock resets each launch and a regularly-used connector never logs
// out). /api/auth/refresh requires a still-valid token, so:
//   • 200 → token was valid; persist the new one (extended expiry).
//   • 401 → token genuinely expired/revoked; drop it so the UI shows a clean
//           "login needed" instead of the confusing "saved but not working".
//   • network/other → keep the token (don't nuke a good token over a blip).
// Returns true if we end up with a usable token.
async function validateAndRefreshAuth(): Promise<boolean> {
  const token = await getStoredToken()
  const { serverUrl } = loadConfig()
  if (!token || !serverUrl) {
    dlog('auth', `refresh skipped (token=${token ? 'yes' : 'no'} serverUrl=${serverUrl || '(empty)'})`)
    return false
  }
  const base = serverUrl.replace(/\/+$/, '')
  try {
    const r = await fetch(`${base}/api/auth/refresh`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (r.ok) {
      const j = await r.json().catch(() => null)
      if (j?.access_token) await storeToken(j.access_token)
      dlog('auth', `refresh ok (rotated=${j?.access_token ? 'yes' : 'no'})`)
      return true
    }
    if (r.status === 401 || r.status === 403) {
      dlog('auth', `refresh ${r.status} → clearing stored token (server rejected it)`)
      await clearStoredToken()
      return false
    }
    dlog('auth', `refresh HTTP ${r.status} → keeping token (transient)`)
    return true // transient server error — assume still logged in
  } catch (e) {
    dlog('auth', `refresh unreachable (${(e as Error)?.message}) → keeping token`)
    return true // offline / unreachable — keep the token, retry later
  }
}

let authRefreshTimer: ReturnType<typeof setInterval> | null = null

// Point the overlay at the server's transparent /overlay avatar page when logged
// in (reusing the proven browser Live2D+TTS+WS stack), else a local placeholder.
// Called on launch and again after login/logout (overlay:refresh).
//: Set when the avatar page has crashed too many times to keep retrying.
//: The overlay then shows the LOCAL placeholder, which needs no GPU.
let overlayFellBack = false
//: Serializes content application. Concurrent callers (login, resume,
//: session change, config change) each started a loadURL that aborted the
//: previous one — an ERR_ABORTED storm that could leave the window with
//: nothing loaded at all, which is what "the avatar never appears" looked
//: like in the field.
let overlayContentInFlight: Promise<void> | null = null

function applyOverlayContent(): Promise<void> {
  if (overlayContentInFlight) return overlayContentInFlight
  const run = applyOverlayContentInner().finally(() => {
    overlayContentInFlight = null
  })
  overlayContentInFlight = run
  return run
}

async function applyOverlayContentInner(): Promise<void> {
  if (!overlay) return
  if (overlayFellBack) {
    // A crash loop was broken earlier; do not walk back into it. The user
    // gets the placeholder until they explicitly retry (tray → 재시작 /
    // 아바타 조작 복구) or the app restarts.
    loadRoute(overlay, 'overlay')
    return
  }
  const token = await getStoredToken()
  const { serverUrl } = loadConfig()
  if (token && serverUrl) {
    const base = serverUrl.replace(/\/+$/, '')
    const sess = loadConfig().overlaySession
    const sessQ = sess ? `&session=${encodeURIComponent(sess)}` : ''
    // Locked by default: the avatar is click-through (clicks reach the desktop),
    // and only the /overlay control bar re-enables input on hover via
    // windowControl.setClickThrough. The page owns -webkit-app-region (drag).
    // A freshly loaded avatar starts locked (clicks reach the desktop);
    // its controls live in the chip window, so nothing is unreachable.
    overlayLocked = true
    applyOverlayInput()
    void createOverlayChip().then(() => {
      void applyChipContent()
      applyChipVisibility()
    })
    try {
      dlog('overlay', `loadURL ${base}/overlay ${redactTok(token)}`)
      await overlay.loadURL(`${base}/overlay?token=${encodeURIComponent(token)}${sessQ}`)
      overlay.webContents.insertCSS('html,body{background:transparent !important;}')
      dlog('overlay', 'loadURL ok')
    } catch (e) {
      // Load failed (server/network) — attachContentResilience retries with backoff.
      dlog('overlay', `loadURL FAILED: ${(e as Error)?.message}`)
    }
  } else {
    // Logged-out placeholder needs its dock handle clickable.
    dlog('overlay', `placeholder (token=${token ? 'yes' : 'no'} serverUrl=${serverUrl || '(empty)'})`)
    // Logged out: the placeholder needs its own dock handle clickable and
    // there is no server page to host a chip.
    overlayLocked = false
    applyOverlayInput()
    applyChipVisibility()
    loadRoute(overlay, 'overlay')
  }
}


// ── Linux overlay input ───────────────────────────────────────────────
//
// `setIgnoreMouseEvents(true, {forward:true})` is darwin/win32-only. On
// Linux a click-through window receives NO events at all, so the overlay
// page's hover-to-unlock can never fire — which made the LOCKED avatar
// swallow its own control bar: the user could see the unlock button and
// could not press it, and the only way out was a tray menu.
//
// Main does the hit-testing instead. The page reports the rectangles that
// must stay clickable (its control bar); while click-through is wanted we
// poll the cursor and drop the ignore flag whenever it is over one of
// them. That reproduces `forward:true` behaviour without forwarded
// events, and the lock does what it says on every platform.
//
// FAIL TOWARDS CONTROL: with no rectangles reported (an older server page)
// click-through is simply not applied. A window the user cannot click is
// worse than an avatar that catches a stray click.
const IS_LINUX = process.platform === 'linux'


// ── the locked-state chip window ──────────────────────────────────────
//
// A locked avatar must pass clicks to the desktop on EVERY platform,
// which means the avatar window is input-transparent — and an
// input-transparent window cannot host its own unlock button. So the
// chip lives in its own small, always-interactive window that follows
// the avatar. Uniform behaviour, no platform-specific compromise.
let overlayChip: BrowserWindow | null = null
let overlayLocked = true
let chipSize = { w: 104, h: 40 }

/** Gap between the chip's bottom edge and the avatar window's. */
const CHIP_MARGIN = 6

function chipBoundsFor(b: Electron.Rectangle): Electron.Rectangle {
  return {
    x: Math.round(b.x + (b.width - chipSize.w) / 2),
    y: Math.round(b.y + b.height - chipSize.h - CHIP_MARGIN),
    width: chipSize.w,
    height: chipSize.h,
  }
}

/**
 * How much of the avatar window's bottom the chip is sitting on.
 *
 * The chip is a SEPARATE always-on-top window parked over the bottom
 * centre of the avatar — which is exactly where the subtitle bubble and
 * the hands-free caption render. Nothing in the avatar page could know
 * that, so the two drew straight through each other: the buttons landed
 * on top of the last line of speech.
 *
 * Main is the only side that knows both rectangles, so it publishes the
 * reserved height and the page lifts its bottom-anchored overlays clear
 * of it. Zero while the chip is hidden (unlocked), so the unlocked
 * layout is untouched.
 */
function chipInsetPx(): number {
  const visible =
    !!overlayChip && !overlayChip.isDestroyed() && overlayChip.isVisible()
  return visible ? chipSize.h + CHIP_MARGIN * 2 : 0
}

function publishChipInset(): void {
  try {
    overlay?.webContents.send('overlay:chip-inset', chipInsetPx())
  } catch { /* window gone */ }
}

/** Put the chip back on top of the avatar. Cheap and idempotent. */
function raiseChip(): void {
  if (!overlayChip || overlayChip.isDestroyed() || !overlayChip.isVisible()) return
  try {
    overlayChip.setAlwaysOnTop(true, 'screen-saver')
    overlayChip.moveTop()
  } catch {
    /* mid-teardown */
  }
}

function syncChipBounds(): void {
  if (!overlayChip || overlayChip.isDestroyed() || !overlay || overlay.isDestroyed()) return
  try {
    overlayChip.setBounds(chipBoundsFor(overlay.getBounds()))
    raiseChip()
  } catch { /* mid-teardown */ }
}

function applyChipVisibility(): void {
  if (!overlayChip || overlayChip.isDestroyed()) return
  const shouldShow = overlayLocked && !!overlay && !overlay.isDestroyed() && overlay.isVisible()
  if (shouldShow) {
    syncChipBounds()
    // showInactive: taking focus would pull the user out of whatever they
    // are doing every time the avatar re-locks.
    if (!overlayChip.isVisible()) overlayChip.showInactive()
    raiseChip()
  } else if (overlayChip.isVisible()) {
    overlayChip.hide()
  }
  // After the show/hide above, so the page is told what is actually on
  // screen rather than what was about to be.
  publishChipInset()
}

async function createOverlayChip(): Promise<void> {
  if (overlayChip && !overlayChip.isDestroyed()) return
  overlayChip = new BrowserWindow({
    width: chipSize.w,
    height: chipSize.h,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    movable: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: join(__dirname, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  // NOT armAlwaysOnTop: that arms blur/show hooks and a re-assert timer.
  // Running it on a SECOND always-on-top window next to the avatar adds
  // restack traffic for no gain — the chip is small, short-lived and
  // recreated with the avatar. alwaysOnTop at creation is enough.
  overlayChip.on('closed', () => {
    overlayChip = null
  })
  await applyChipContent()
}

async function applyChipContent(): Promise<void> {
  if (!overlayChip || overlayChip.isDestroyed()) return
  // LOCAL page, deliberately. Loading the server's overlay page into this
  // window crashed the app outright — measured: creating the window is
  // harmless, loading that bundle into it is fatal (a second avatar
  // runtime + WebGL context for three buttons). A local chip also works
  // before login and costs no network.
  loadRoute(overlayChip, 'chip')
}

/** Lock state is owned HERE: it decides window input, and two windows
 *  (avatar + chip) must never disagree about it. */
function setOverlayLocked(locked: boolean): void {
  overlayLocked = locked
  applyOverlayInput()
  applyChipVisibility()
  try {
    overlay?.webContents.send('overlay:locked', locked)
  } catch { /* window gone */ }
}

/** Single place that decides the overlay's input state. */
function applyOverlayInput(): void {
  if (!overlay || overlay.isDestroyed()) return
  // SAME RULE ON EVERY PLATFORM: locked → the avatar passes clicks to
  // whatever is behind it; unlocked → it captures them for pan/zoom and
  // the resize frame. The controls are never affected either way, because
  // they live in their own window.
  overlay.setIgnoreMouseEvents(overlayLocked, IS_LINUX ? undefined : { forward: true })
  dlog('overlay', `input: ${overlayLocked ? 'click-through' : 'interactive'}`)
}


/** Panic button (tray): whatever state the overlay got into, give it back
 *  to the user. Costs one stray click on the avatar; never costs control. */
function forceOverlayInteractive(): void {
  // Also the "try the avatar again" button: clearing the crash-loop latch
  // is the only in-app way back to the remote page without a restart.
  if (overlayFellBack) {
    overlayFellBack = false
    void applyOverlayContent()
  }
  overlayLocked = false
  try {
    overlay?.setIgnoreMouseEvents(false)
    overlay?.showInactive()
  } catch { /* ignore */ }
  dlog('overlay', 'input force-restored (tray)')
}

let appQuitting = false
app.on('before-quit', () => {
  appQuitting = true
  stopSystemStats()
})

// ── Geny Drive helpers ───────────────────────────────────────────────────
// The drive is a single local root whose immediate children are agent
// folders. Membership (which agent) is the only user decision; placement is
// derived. Drive-owned sync pairs are marked managed:'drive' so the classic
// hand-paired workflow keeps working side by side.

/** Consume the installer's one-shot choice file, if present.
 *
 * The Windows installer (build/installer.nsh) records the "Geny 클라우드 사용"
 * answer as %APPDATA%\geny-connector\install-flags.json. We fold it into the
 * config ONCE and delete it, so a later change made in the app is never
 * re-overwritten by a stale install artifact. Absent file = keep whatever the
 * config already says (and the config's own default is opt-IN).
 */
function consumeInstallFlags(): void {
  const flagPath = join(app.getPath('appData'), 'geny-connector', 'install-flags.json')
  try {
    if (!existsSync(flagPath)) return
    const flags = JSON.parse(readFileSync(flagPath, 'utf-8'))
    if (typeof flags?.cloudOptIn === 'boolean') {
      saveConfig({ cloudOptIn: flags.cloudOptIn })
      dlog('drive', `install flag consumed: cloudOptIn=${flags.cloudOptIn}`)
    }
  } catch (e) {
    dlog('drive', `install flag read failed: ${(e as Error)?.message}`)
  } finally {
    try { unlinkSync(flagPath) } catch { /* already gone */ }
  }
}

/** Storage scope addressing the user's cloud (server-side constant). */
const CLOUD_SCOPE = '_cloud'

/** The local mirror of the server cloud. A folder INSIDE the drive root
 *  rather than the root itself: existing installs already keep per-agent
 *  folders at the root, and moving those would risk user data for a
 *  cosmetic gain. */
function cloudFolder(): string {
  return join(driveRoot(), 'Cloud')
}

/** Set once the IPC layer is wired; used by the boot-time restore. */
let startNativeMount: () => Promise<{ mounted?: boolean; mountpoint?: string; error?: string }> =
  async () => ({ error: 'not ready' })

function driveRoot(): string {
  return loadConfig().driveRoot || join(app.getPath('home'), 'GenyDrive')
}

/** Reconcile sync pairs with the drive config: one managed pair per enabled
 *  agent at `<root>/<folder>`, none for disabled ones. Idempotent — safe to
 *  call after any config change. */
/** Safe subtree name for a linked folder — same constraints as drive
 *  folder names (portable across every OS the drive mounts on). */
function allocateLinkName(desired: string, taken: Set<string>): string {
  let name = (desired || 'folder').normalize('NFC').trim()
  name = name.replace(/[<>:"/\\|?*]/g, '_').replace(/[. ]+$/g, '')
  name = name.slice(0, 80) || 'folder'
  let candidate = name
  let i = 2
  const lower = new Set([...taken].map((t) => t.toLowerCase()))
  while (lower.has(candidate.toLowerCase())) candidate = `${name}-${i++}`
  return candidate
}

/** Represent a linked folder INSIDE the local GenyDrive agent folder as a
 *  symlink (junction on Windows — no admin needed). The drive engine
 *  ignores it (scan skips symlinks + the subtree is in excludePrefixes),
 *  so the link engine is the single owner of that subtree. */
function ensureLinkShortcut(
  parentDir: string,
  linkName: string,
  targetDir: string,
): void {
  const at = join(parentDir, linkName)
  try {
    const st = lstatSync(at, { throwIfNoEntry: false } as never) as ReturnType<typeof lstatSync> | undefined
    if (st?.isSymbolicLink()) {
      if (readlinkSync(at) === targetDir) return
      unlinkSync(at) // stale target → recreate below
    } else if (st) {
      // A REAL directory or file already occupies the path. Never touch it:
      // whatever it is, it is the user's. The "reclaim" branch that used to
      // move it aside as `<name>.pre-link-<ts>` existed only to take the
      // path back from a per-agent mirror, and there are no agent mirrors.
      dlog('drive', `link shortcut skipped (occupied): ${at}`)
      return
    }
    symlinkSync(targetDir, at, process.platform === 'win32' ? 'junction' : 'dir')
  } catch (e) {
    dlog('drive', `link shortcut failed at ${at}: ${(e as Error)?.message}`)
  }
}

function removeLinkShortcut(agentDir: string, linkName: string, targetDir: string): void {
  const at = join(agentDir, linkName)
  try {
    const st = lstatSync(at, { throwIfNoEntry: false } as never) as ReturnType<typeof lstatSync> | undefined
    if (st?.isSymbolicLink() && readlinkSync(at) === targetDir) unlinkSync(at)
  } catch { /* best effort */ }
}

/** Persist a pause for a DERIVED pair.
 *
 *  Engines are computed from `driveLinks` plus the cloud switch, so the
 *  pause has to land on the thing that survives a restart. The legacy model
 *  stored pairs in the config and edited them in place; doing that now wrote
 *  to an empty list and then reconfigured the manager with it — which
 *  stopped every engine on the machine, not just the paused one.
 *
 *  The cloud pair has nowhere to record a pause, so it is not pausable: the
 *  switch that turns it off is "use Geny Cloud". */
function pauseLink(pairId: string, reason: string): void {
  const name = pairId.startsWith('link:') ? pairId.slice('link:'.length) : null
  if (!name) {
    dlog('drive', `pause requested for non-link pair ${pairId} — ignored (${reason})`)
    return
  }
  const cfg = loadConfig()
  const links = (cfg.driveLinks ?? []).map((l) =>
    l.name === name ? { ...l, paused: true } : l,
  )
  saveConfig({ driveLinks: links })
  dlog('drive', `link '${name}' paused: ${reason}`)
  applyDriveConfig()
}

/** One-time removal of config from the per-agent / manual-pairing era.
 *
 *  `syncPairs` was the store for hand-made folder pairings and, later, the
 *  derived drive pairs; `driveAgents` named a local mirror folder per agent.
 *  Neither model exists — the drive is one cloud folder plus linked folders,
 *  and its engines are derived. Leaving the keys behind would preserve state
 *  that nothing reads and that describes a structure the app no longer has. */
function dropLegacyDriveState(): void {
  const cfg = loadConfig() as unknown as Record<string, unknown>
  if (!('syncPairs' in cfg) && !('driveAgents' in cfg)) return
  delete cfg.syncPairs
  delete cfg.driveAgents
  writeConfigRaw(cfg)
  dlog('drive', 'legacy syncPairs/driveAgents config dropped')
  sweepPreLinkCopies()
}

/** Remove the `<name>.pre-link-<ts>` copies the old link flow left behind.
 *
 *  Creating a link used to rename an agent mirror's copy of the subtree aside
 *  under that suffix, so the shortcut could take the path. The copy was
 *  redundant the moment the link started syncing — the same bytes live in the
 *  linked folder and in the cloud — but it stayed on disk forever, showing up
 *  as a stray directory beside the real one.
 *
 *  Only the exact `.pre-link-<base36>` shape this code produced is matched, so
 *  a folder a user happened to name similarly is never touched. */
function sweepPreLinkCopies(): void {
  const root = driveRoot()
  if (!existsSync(root)) return
  const suffix = /\.pre-link-[0-9a-z]+$/
  const sweep = (dir: string): void => {
    let names: string[]
    try { names = readdirSync(dir) } catch { return }
    for (const name of names) {
      const at = join(dir, name)
      if (!suffix.test(name)) continue
      try {
        // lstat, not stat: a SYMLINK that happens to match the pattern must
        // not be followed and its target destroyed.
        if (!lstatSync(at).isDirectory()) continue
        rmSync(at, { recursive: true, force: true })
        dlog('drive', `removed stale pre-link copy: ${at}`)
      } catch { /* locked or already gone — next launch retries */ }
    }
  }
  sweep(root)
  sweep(cloudFolder())
}

function applyDriveConfig(): void {
  const cfg = loadConfig()
  const root = driveRoot()
  const links = cfg.driveLinks ?? []
  // Opting out of Geny Cloud (installer answer or the in-app switch) parks
  // the whole drive: no managed pairs run. Per-agent membership is kept so
  // opting back in restores exactly the previous set — and, because folders
  // and pair ids are stable, without re-downloading anything.
  const cloudOn = cfg.cloudOptIn !== false
  // Mirror the current choice as a sentinel the WINDOWS INSTALLER can read
  // (NSIS can't parse JSON): a manual reinstall pre-sets its checkbox from
  // this, so rerunning the installer never silently re-enables the cloud a
  // user turned off in the app. Harmless bookkeeping on Linux/macOS.
  const optOutMarker = join(app.getPath('appData'), 'geny-connector', 'cloud-opt-out')
  try {
    if (!cloudOn && !existsSync(optOutMarker)) writeFileSync(optOutMarker, '')
    else if (cloudOn && existsSync(optOutMarker)) unlinkSync(optOutMarker)
  } catch { /* cosmetic — never block the drive on marker IO */ }
  // ── THE CLOUD ─────────────────────────────────────────────────────
  // One pair, not one per agent. The server cloud is the hub every agent
  // connects to, so a shared folder crosses the network ONCE no matter
  // how many agents use it — the old model uploaded the same folder into
  // every agent's workspace and ran an engine per copy.
  const cloudLocal = cloudFolder()
  if (cloudOn) {
    try {
      mkdirSync(cloudLocal, { recursive: true })
    } catch { /* surfaced by the engine's own error state */ }
  }
  const cloudPair = cloudOn
    ? [{
        id: 'cloud',
        sessionId: CLOUD_SCOPE,
        sessionLabel: 'GenyCloud',
        localPath: cloudLocal,
        managed: 'drive' as const,
        // Linked subtrees belong to their own engines; the cloud mirror
        // must not also materialise them as real folders here.
        excludePrefixes: links.map((l) => l.name),
      }]
    : []

  // NO agent mirrors. The cloud is the only connection point, so this
  // machine has exactly one edge: [computer] ── [cloud]. An agent reaches
  // the same bytes through its own edge to the cloud.
  //
  // There used to be a mirror per agent here — a direct [computer] ── [agent]
  // edge that made one shared folder into N copies with N engines, and put a
  // "syncing with 1 PC" badge on an agent's private workspace describing a
  // connection that is not part of the model.
  //
  // Removing the PAIR stops the syncing; it does not touch the bytes. Any
  // `<root>/<agent>` folder already on disk stays exactly where it is, as an
  // ordinary local folder. Those workspaces remain reachable on the web
  // (클라우드 → 에이전트) and through the virtual drive mount.
  // A linked folder binds to the CLOUD — one engine each, whatever the agent
  // count. Ids drop the session dimension entirely.
  const linkPairs = cloudOn
    ? links.map((l) => ({
        id: `link:${l.name}`,
        sessionId: CLOUD_SCOPE,
        sessionLabel: l.name,
        localPath: l.localPath,
        managed: 'link' as const,
        remotePrefix: l.name,
        paused: l.paused,
      }))
    : []
  // The pair set is DERIVED, never stored: it is the cloud mirror plus one
  // engine per linked folder, both computed from `driveLinks` and the cloud
  // switch. Persisting it was the legacy manual-pairing model, where a pair
  // was a thing a user created by hand and the config was its home.
  const next = [...cloudPair, ...linkPairs]
  getSyncManager()?.configure(next)
  ensureAllLinkShortcuts()
  publishLinkLedger()
  // A shortcut ensured at (re)configure time can lose a race with the
  // drive engine's own first round — e.g. a link created over a subtree
  // the drive previously mirrored: the engine clears its stale real-dir
  // copy AFTER we looked and found the path "occupied". One delayed
  // re-ensure closes that window; drive:get re-ensures on every UI
  // refresh as a backstop (idempotent either way).
  setTimeout(() => ensureAllLinkShortcuts(), 20_000).unref?.()
}

/** Publish this device's linked-folder set to the CLOUD.
 *
 * The binding graph lives here, in the connector — without publishing it
 * the web explorer cannot tell a linked folder from a folder something
 * else created, and neither can a second device. Names and this device's
 * label only: which folder on which machine is the user's business.
 * Best-effort by design — a failed publish costs a badge, never data. */
function publishLinkLedger(): void {
  const cfg = loadConfig()
  const cloudOn = cfg.cloudOptIn !== false
  const links = cloudOn
    ? (cfg.driveLinks ?? []).map((l) => ({ name: l.name, device: hostname() }))
    : []
  // ONE publish: linked folders live in the cloud now, so the ledger
  // belongs to the cloud too. Agents see them through their connection,
  // not as per-agent copies with per-agent ledgers.
  void (async () => {
    const token = await getStoredToken()
    if (!cfg.serverUrl || !token) return
    try {
      await fetch(
        `${cfg.serverUrl.replace(/\/$/, '')}/api/agents/${CLOUD_SCOPE}/storage/links`,
        {
          method: 'PUT',
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ links }),
        },
      )
    } catch {
      /* badge-only metadata — never surface, never retry-storm */
    }
  })()
}

/** Idempotent: the GenyDrive ROOT carries one shortcut per drive link —
 *  the [폴더-GenyDrive] binding made visible, next to the agent folders.
 *  Safe to call any time (skips occupied paths, repairs stale targets,
 *  no-ops when already correct). Also sweeps 0.19.17-era per-agent
 *  shortcuts, which the drive-level model superseded. */
function ensureAllLinkShortcuts(): void {
  const cfg = loadConfig()
  if (cfg.cloudOptIn === false) return
  const root = driveRoot()
  if (!existsSync(root)) return
  const cloudLocal = cloudFolder()
  try { mkdirSync(cloudLocal, { recursive: true }) } catch { /* engine reports */ }
  for (const l of cfg.driveLinks ?? []) {
    // A linked folder belongs to the cloud, so its shortcut lives INSIDE
    // the local cloud folder — browsing GenyCloud shows it in place.
    ensureLinkShortcut(cloudLocal, l.name, l.localPath)
    // Sweep the shortcut the drive-root model left behind (0.19.18).
    removeLinkShortcut(root, l.name, l.localPath)
  }
}

// Relaunch via the sandbox shim / AppImage runtime. process.execPath is the
// REAL binary (<name>.bin behind the shim, build/afterPack.cjs) — relaunching
// it directly would skip the sandbox decision, and an AppImage's FUSE mount
// dies with this process, so the relaunch must go through $APPIMAGE.
//
// Linux does NOT use app.relaunch(): it relays through a '--type=relauncher'
// helper whose content-sandbox init sets NoNewPrivs, which the relaunched
// browser inherits (NNP is irreversible across fork/exec). Under NNP the SUID
// chrome-sandbox cannot elevate, and on userns-restricted kernels (Ubuntu
// 23.10+/24.04) that leaves NO working sandbox → zygote dies → SIGTRAP at
// boot (verified via /proc/<pid>/status NoNewPrivs=1 on the relaunched main).
// This process has NNP=0, so spawn the successor ourselves.
function relaunchSelf(): void {
  appQuitting = true
  const exe = process.env.APPIMAGE || process.execPath.replace(/\.bin$/, '')
  if (process.platform === 'linux') {
    // Strip a shim-injected --no-sandbox so the new shim run re-decides.
    const args = process.argv.slice(1).filter((a) => a !== '--no-sandbox')
    // sh sleeps past our exit (old instance fully gone: tray, shortcuts,
    // FUSE mount), then execs the shim/AppImage. detached + unref → survives.
    const child = spawn('/bin/sh', ['-c', 'sleep 1; exec "$@"', 'geny-relaunch', exe, ...args], {
      detached: true,
      stdio: 'ignore',
    })
    child.unref()
    app.quit()
    return
  }
  app.relaunch({ execPath: exe })
  app.quit()
}
app.on('will-quit', () => {
  globalShortcut.unregisterAll()
  try { getSyncManager()?.stopAll() } catch { /* ignore */ }
  try { void getMcpManager().closeAll() } catch { /* ignore */ }
  // Structured-control teardown: drop CDP sockets (the visible automation
  // browser stays — it's the user's), kill the PowerShell UIA/COM host.
  try { getBrowserControl().dispose() } catch { /* ignore */ }
  try { disposeWinAutoHost() } catch { /* ignore */ }
  if (authRefreshTimer) clearInterval(authRefreshTimer)
})

// ── system tray: the always-available way to open settings / quit ───────────
let tray: Tray | null = null
// (Re)build the tray context menu. Hoisted so a language change (saveConfig) or
// a state change (avatar hide/show) can re-localize / refresh it in place.
function rebuildTrayMenu(): void {
  if (!tray) return
  const menu = Menu.buildFromTemplate([
    { label: nt('tray.openControl'), click: () => showControl() },
    { label: nt('tray.quickChat'), click: () => void toggleQuickChat() },
    { label: nt('tray.openSettings'), click: () => showSettings() },
    {
      label: overlay?.isVisible() ? nt('tray.hideAvatar') : nt('tray.showAvatar'),
      click: () => {
        if (!overlay) return
        overlay.isVisible() ? overlay.hide() : overlay.show()
        rebuildTrayMenu()
      },
    },
    { type: 'separator' },
    // The old Linux checkbox turned the overlay OFF for the mouse with no
    // way back from the overlay itself — main now hit-tests instead, so
    // what is left is a panic button: if anything ever leaves the avatar
    // unclickable, this hands control back.
    ...(IS_LINUX
      ? [{
          label: nt('tray.restoreInput'),
          click: () => {
            forceOverlayInteractive()
            rebuildTrayMenu()
          },
        }]
      : []),
    {
      label: nt('tray.allowComputerUse'),
      type: 'checkbox',
      checked: loadConfig().computerUse?.enabled === true,
      click: (item) => { patchComputerUse({ enabled: item.checked }); rebuildTrayMenu() },
    },
    { type: 'separator' },
    {
      label: nt('tray.autoUpdate'),
      type: 'checkbox',
      checked: loadConfig().autoUpdate !== false,
      click: (item) => {
        saveConfig({ autoUpdate: item.checked })
        if (item.checked) triggerBackgroundCheck()
      },
    },
    { label: nt('tray.checkUpdate'), click: () => void checkForUpdatesManually() },
    { label: nt('tray.version', { version: app.getVersion() }), enabled: false },
    { type: 'separator' },
    { label: nt('tray.logout'), click: () => void logout() },
    {
      label: nt('tray.restart'),
      click: () => relaunchSelf(),
    },
    {
      label: nt('tray.quit'),
      click: () => {
        appQuitting = true
        app.quit()
      },
    },
  ])
  tray.setContextMenu(menu)
}
function createTray(): void {
  try {
    const icon = nativeImage.createFromDataURL(`data:image/png;base64,${TRAY_ICON_B64}`)
    tray = new Tray(icon)
    tray.setToolTip('Geny')
    rebuildTrayMenu()
    // Left-click the tray toggles the control window (Windows/Linux convention).
    // Note: many Linux StatusNotifier hosts never emit 'click' — the context
    // menu is the reliable path there.
    tray.on('click', () => showControl())
  } catch (e) {
    // No StatusNotifier host (e.g. plain GNOME without the AppIndicator
    // extension). Without a tray the control window is the only remaining
    // UI surface, so make sure one actually appears: cancel a pending
    // --hidden start (refreshAll runs after createTray and would otherwise
    // leave the app running with no reachable UI at all).
    console.error('[tray] unavailable:', (e as Error)?.message)
    tray = null
    startHidden = false
  }
}

function showControl(): void {
  if (!control) createControl()
  control?.show()
  control?.focus()
}

// Clear the stored JWT and send both windows back to their logged-out state.
async function logout(): Promise<void> {
  await clearStoredToken()
  await refreshAll() // logged out → hides panel, shows settings/login
}

// ── global hotkeys (push-to-talk + quick-chat) ──────────────────────────────
const DEFAULT_PTT = 'CommandOrControl+Shift+Space'
// A deliberately uncommon default (rarely claimed system-wide) yet mnemonic —
// Enter = "send". Reconfigurable in the settings window.
const DEFAULT_QUICKCHAT = 'CommandOrControl+Shift+Enter'

// Both global accelerators are (re)registered together: globalShortcut has no
// race-free per-accelerator rebind, so we unregister all and re-add each from
// the current config. Returns which ones actually bound (false → conflict).
function registerHotkeys(): { ptt: boolean; quickChat: boolean } {
  globalShortcut.unregisterAll()
  const cfg = loadConfig()
  const result = { ptt: true, quickChat: true }

  const ptt = cfg.pttHotkey ?? DEFAULT_PTT
  if (ptt) {
    try {
      // press-only (globalShortcut has no key-up) → the overlay treats it as a
      // tap-to-toggle for the mic. Target the overlay: it owns the WS + audio.
      result.ptt = globalShortcut.register(ptt, () =>
        overlay?.webContents.send('connector:ptt-toggle'),
      )
    } catch {
      result.ptt = false
    }
  }

  const qc = cfg.quickChatHotkey ?? DEFAULT_QUICKCHAT
  if (qc) {
    try {
      result.quickChat = globalShortcut.register(qc, () => void toggleQuickChat())
    } catch {
      result.quickChat = false
    }
  }
  return result
}

// ── Local Computer Use gate: per-capability consent (local bridge Phase 1) ───
// Effective gate = master AND the capability toggle. When `computerUse` is
// absent we fall back to the legacy captureArmed/automationEnabled toggles so
// existing installs behave exactly as before.
type ActuationCap = 'input' | 'apps' | 'clipboard' | 'browser'
interface ComputerUseGate { screen: boolean; input: boolean; apps: boolean; clipboard: boolean; browser: boolean; mode: ConsentMode }
function computerUseGate(): ComputerUseGate {
  const c = loadConfig()
  const cu = c.computerUse
  if (!cu) {
    // Legacy fallback: screen defaults ON, actuation defaults OFF, always ASK.
    const act = c.automationEnabled === true
    return { screen: c.captureArmed !== false, input: act, apps: act, clipboard: act, browser: act, mode: 'ask' }
  }
  const on = cu.enabled === true
  return {
    screen: on && cu.screen !== false,
    input: on && cu.input !== false,
    apps: on && cu.apps !== false,
    clipboard: on && cu.clipboard !== false,
    browser: on && cu.browser !== false,
    mode: cu.consentMode ?? 'ask',
  }
}
function patchComputerUse(patch: Partial<ComputerUseConfig>): void {
  const cur = loadConfig().computerUse ?? {}
  saveConfig({ computerUse: { ...cur, ...patch } })
}

// "이 세션 동안 허용" — per-capability session grants, cleared on app restart.
const sessionAllow = new Set<ActuationCap>()

type ActuationResult = { ok: boolean; result?: unknown; denied?: boolean; error?: string }
async function runActuation(
  cap: ActuationCap,
  label: string,
  detail: string,
  fn: () => Promise<unknown>,
): Promise<ActuationResult> {
  const gate = computerUseGate()
  const allowed =
    cap === 'apps' ? gate.apps : cap === 'clipboard' ? gate.clipboard : cap === 'browser' ? gate.browser : gate.input
  if (!allowed) {
    return { ok: false, denied: true, error: nt('act.capDisabled') }
  }
  // Consent: auto or an active session-grant → run without a prompt; otherwise
  // ask, offering a "이 세션 동안 허용" that promotes to a session-grant.
  if (gate.mode !== 'auto' && !sessionAllow.has(cap)) {
    const { response } = await dialog.showMessageBox({
      type: 'warning',
      buttons: [nt('act.allow'), nt('act.allowSession'), nt('act.deny')],
      defaultId: 2,
      cancelId: 2,
      title: nt('act.dialogTitle'),
      message: nt('act.dialogMessage', { label }),
      detail,
    })
    if (response === 2) return { ok: false, denied: true, error: nt('act.deniedByUser') }
    if (response === 1) sessionAllow.add(cap) // grant for the rest of this run
  }
  try {
    return { ok: true, result: await fn() }
  } catch (e) {
    return { ok: false, error: String((e as Error).message) }
  }
}

// Native input synthesis (nut.js) — lazy + graceful: if the addon is missing
// on this build/platform, the import throws and runActuation reports it cleanly.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let _nut: any = null
// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function loadNut(): Promise<any> {
  if (_nut) return _nut
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const m: any = await import('@nut-tree-fork/nut-js')
  const K = m.Key
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const keyMap: Record<string, any> = {
    ctrl: K.LeftControl, control: K.LeftControl, alt: K.LeftAlt, shift: K.LeftShift,
    cmd: K.LeftCmd, meta: K.LeftSuper, win: K.LeftSuper, super: K.LeftSuper,
    enter: K.Enter, return: K.Return, tab: K.Tab, esc: K.Escape, escape: K.Escape,
    space: K.Space, backspace: K.Backspace, delete: K.Delete, del: K.Delete,
    up: K.Up, down: K.Down, left: K.Left, right: K.Right, home: K.Home, end: K.End,
    a: K.A, b: K.B, c: K.C, d: K.D, e: K.E, f: K.F, g: K.G, h: K.H, i: K.I, j: K.J, k: K.K, l: K.L, m: K.M,
    n: K.N, o: K.O, p: K.P, q: K.Q, r: K.R, s: K.S, t: K.T, u: K.U, v: K.V, w: K.W, x: K.X, y: K.Y, z: K.Z,
    '0': K.Num0, '1': K.Num1, '2': K.Num2, '3': K.Num3, '4': K.Num4,
    '5': K.Num5, '6': K.Num6, '7': K.Num7, '8': K.Num8, '9': K.Num9,
  }
  _nut = { keyboard: m.keyboard, mouse: m.mouse, screen: m.screen, Button: m.Button, Point: m.Point, Key: K, keyMap }
  return _nut
}

// ── Computer-use coordinate mapping ─────────────────────────────────────────
// The model clicks in the SCREENSHOT's pixel space. desktop_screenshot captures
// the PRIMARY display; nut.js mouse/screen operate in the primary's PHYSICAL
// pixels. So we scale image coords → nut coords by the ratio nut.screen / image,
// which is correct at ANY DPI and regardless of how the capture was scaled or
// capped (both spaces cover the same primary screen). Multi-monitor secondary
// displays are out of nut.js's (primary-only) mouse space — best-effort only.
let lastCaptureDims: { w: number; h: number } | null = null
// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function mapImageToScreen(nut: any, x: number, y: number): Promise<{ x: number; y: number }> {
  const dims = lastCaptureDims
  if (!dims || !dims.w || !dims.h) return { x, y } // no screenshot reference → assume 1:1
  try {
    const sw = await nut.screen.width()
    const sh = await nut.screen.height()
    if (!sw || !sh) return { x, y }
    return { x: Math.round((x * sw) / dims.w), y: Math.round((y * sh) / dims.h) }
  } catch {
    return { x, y }
  }
}

// ── IPC: the connectorBridge surface (preload calls these) ──────────────────
function registerIpc(): void {
  // The status bar's first reading — a window that just opened should not
  // show blanks for two seconds waiting for the first push.
  ipcMain.handle('system:stats', () => currentSystemStats())

  ipcMain.handle('config:get', () => loadConfig())
  ipcMain.handle('config:set', (_e, patch: Partial<ConnectorConfig>) => {
    const prevServer = loadConfig().serverUrl
    const next = saveConfig(patch)
    // Push the merged config to the avatar overlay so its capability drivers
    // (TTS/STT/screen) apply overlayTuning changes live — no reload.
    overlay?.webContents.send('config:changed', next)
    control?.webContents.send('config:changed', next)
    // Server address changed → re-derive every window's content NOW. Before
    // this, a URL saved via 연결확인 only took effect at the next login or
    // restart — the overlay sat on the logged-out placeholder forever.
    if ('serverUrl' in patch && next.serverUrl !== prevServer) void refreshAll()
    return next
  })

  // Click-through toggle from the renderer's hit-test loop.
  // The avatar page still reports its lock; main owns the state so both
  // windows can never disagree.
  ipcMain.on('overlay:set-ignore-mouse', (_e, ignore: boolean) => {
    setOverlayLocked(!!ignore)
  })

  ipcMain.on('overlay:set-locked', (_e, locked: boolean) => {
    setOverlayLocked(!!locked)
  })

  // Registered ONCE. It was registered twice, so every report ran the
  // body twice; the second pass fell out on the "changed by <2px" guard,
  // which is why it never showed — a duplicate that happened to be
  // idempotent is still a duplicate.
  ipcMain.on('overlay:chip-size', (_e, w: number, h: number) => {
    if (!Number.isFinite(w) || !Number.isFinite(h) || w < 20 || h < 12) return
    if (Math.abs(w - chipSize.w) < 2 && Math.abs(h - chipSize.h) < 2) return
    chipSize = { w: Math.min(600, Math.round(w)), h: Math.min(200, Math.round(h)) }
    syncChipBounds()
    // The chip just changed height — the page's reserved space is stale.
    publishChipInset()
  })

  // The avatar page mounts (and remounts, on every reload) long after the
  // chip's last visibility change, so it would otherwise sit at inset 0
  // until something happened to move the chip. It asks; main answers.
  ipcMain.on('overlay:request-chip-inset', () => publishChipInset())

  // Accepted and ignored: older avatar pages report interactive rects for
  // the cursor hit-test this build replaced with the chip window. Dropping
  // the channel would throw in those pages.
  ipcMain.on('overlay:set-interactive-rects', () => {})

  // Move the overlay by a pointer delta (dock-handle drag).
  //
  // The naive `setPosition(getPosition() + delta)` GROWS the window on Windows
  // fractional-DPI monitors (150%): Electron's setPosition internally does
  // `SetBounds(newOrigin, getBounds().size())`, and getBounds() reports the
  // DIP-rounded size — each frame reads a slightly larger rounded size and
  // writes it back, so over a drag's hundreds of frames the window balloons.
  // (setBounds has the exact same read-back-and-grow problem.)
  //
  // Fix: keep an AUTHORITATIVE rect in JS. Capture the real bounds once at the
  // start of a drag, then apply deltas to the tracked position and re-assert a
  // CONSTANT captured size every frame — never reading getBounds() mid-drag. A
  // constant DIP size converts to the same physical size each call, so it can't
  // drift; the DIP size also stays put when crossing to a different-scale
  // monitor (physical size adapts), and the post-drag 'moved' handler snaps to
  // that monitor's remembered size. The drag rect auto-expires shortly after
  // the last delta (or on the explicit move-end below).
  ipcMain.on('overlay:move-by', (_e, dx: number, dy: number) => {
    if (!overlay || overlay.isDestroyed()) return
    if (!overlayMoveRect) {
      const b = overlay.getBounds()
      overlayMoveRect = { x: b.x, y: b.y, w: b.width, h: b.height }
    }
    overlayMoveRect.x += dx
    overlayMoveRect.y += dy
    overlay.setBounds({
      x: Math.round(overlayMoveRect.x),
      y: Math.round(overlayMoveRect.y),
      width: overlayMoveRect.w,
      height: overlayMoveRect.h,
    })
    if (overlayMoveIdle) clearTimeout(overlayMoveIdle)
    overlayMoveIdle = setTimeout(endOverlayMove, 300) // fallback drag-end
  })
  // Explicit drag-end (mouseup) — drop the authoritative rect immediately so the
  // next natural window event reads real bounds again.
  ipcMain.on('overlay:move-end', endOverlayMove)

  // Resize the overlay from an edge/corner handle (unlocked). `edge` is any of
  // n/s/e/w combined (e.g. 'se','n'); dx/dy are pointer deltas. West/north edges
  // move the origin while resizing. Clamped to a sane minimum. The 'resized'
  // event persists the new size for the current monitor.
  ipcMain.on('overlay:resize-by', (_e, edge: string, dx: number, dy: number) => {
    if (!overlay) return
    const MIN = 160
    const b = overlay.getBounds()
    let { x, y, width, height } = b
    if (edge.includes('e')) width = Math.max(MIN, width + Math.round(dx))
    if (edge.includes('s')) height = Math.max(MIN, height + Math.round(dy))
    if (edge.includes('w')) { const nw = Math.max(MIN, width - Math.round(dx)); x += width - nw; width = nw }
    if (edge.includes('n')) { const nh = Math.max(MIN, height - Math.round(dy)); y += height - nh; height = nh }
    overlay.setBounds({ x, y, width, height })
  })

  ipcMain.on('control:toggle', () => {
    if (!control) return
    control.isVisible() ? control.hide() : control.show()
  })

  // Always show + focus the control window (never hides). The overlay's
  // chat/options buttons use this; the desired view (chat|settings) is
  // signalled via same-origin localStorage so the panel switches tabs.
  ipcMain.on('control:open', () => {
    if (!control) createControl()
    control?.show()
    control?.focus()
  })

  // Re-evaluate everything after login/logout (token changed in keychain).
  ipcMain.on('app:refresh', () => void refreshAll())

  // Open the settings window (from the panel's gear button or app menu).
  ipcMain.on('settings:open', () => showSettings())

  // Reset all window positions/sizes + the avatar view (settings → 위치 초기화).
  ipcMain.on('windows:reset-positions', () => resetWindowPositions())

  // App version (settings window "앱" tab).
  ipcMain.handle('app:version', () => app.getVersion())

  // OS-derived default UI language — the settings window uses this when the
  // config has no explicit `lang` yet.
  ipcMain.handle('i18n:default-lang', () => osDefaultLang())

  // Open a URL in the user's default browser (e.g. "Geny 서버 열기").
  ipcMain.on('app:open-external', (_e, url: string) => {
    if (typeof url === 'string' && /^https?:\/\//i.test(url)) shell.openExternal(url)
  })

  // Reload ONLY the chat/control panel (e.g. after a theme change) — leaves the
  // avatar overlay untouched so it doesn't flicker.
  ipcMain.on('app:reload-control', () => { void applyControlContent() })

  // Restart the whole connector (reloads the remote overlay/panel + native code).
  ipcMain.on('app:restart', () => relaunchSelf())

  // Global push-to-talk hotkey config. Persist the candidate, re-bind both
  // hotkeys, and roll back if it failed to register (conflict with another app).
  ipcMain.handle('hotkey:get-ptt', () => loadConfig().pttHotkey ?? DEFAULT_PTT)
  ipcMain.handle('hotkey:set-ptt', (_e, acc: string) => {
    const prev = loadConfig().pttHotkey
    saveConfig({ pttHotkey: acc })
    const ok = registerHotkeys().ptt
    if (!ok) {
      saveConfig({ pttHotkey: prev ?? DEFAULT_PTT })
      registerHotkeys()
    }
    return ok
  })

  // Global quick-chat hotkey config (same rollback contract as PTT).
  ipcMain.handle('hotkey:get-quickchat', () => loadConfig().quickChatHotkey ?? DEFAULT_QUICKCHAT)
  ipcMain.handle('hotkey:set-quickchat', (_e, acc: string) => {
    const prev = loadConfig().quickChatHotkey
    saveConfig({ quickChatHotkey: acc })
    const ok = registerHotkeys().quickChat
    if (!ok) {
      saveConfig({ quickChatHotkey: prev ?? DEFAULT_QUICKCHAT })
      registerHotkeys()
    }
    return ok
  })

  // While a settings field is RECORDING a new hotkey, suspend the global
  // shortcuts so an already-registered combo (e.g. the current PTT key) isn't
  // swallowed system-wide and can be re-captured by the renderer's keydown.
  ipcMain.on('hotkey:pause', () => globalShortcut.unregisterAll())
  ipcMain.on('hotkey:resume', () => registerHotkeys())

  // Quick-chat bar → send to the current VTuber, then close. Returns {ok,error}
  // so the bar can show a brief result (전송됨 / 로그인 필요).
  // Grow/shrink the bar window to fit its content (multi-line text, pasted
  // image thumbnails) so the page NEVER scrolls — Spotlight-style. Top edge
  // stays anchored; only height changes, clamped to a sane band. resizable is
  // false for the USER; programmatic resize toggles it around setBounds
  // (macOS blocks setBounds on non-resizable windows).
  ipcMain.on('quickchat:resize', (_e, contentH: number) => {
    if (!quickchat || quickchat.isDestroyed() || !quickChatOpen) return
    if (!Number.isFinite(contentH)) return
    const h = Math.max(QUICKCHAT_H, Math.min(QUICKCHAT_MAX_H, Math.round(contentH)))
    const b = quickchat.getBounds()
    if (Math.abs(b.height - h) < 2) return
    suppressQuickChatPosSave = true
    quickchat.setResizable(true)
    quickchat.setBounds({ x: b.x, y: b.y, width: QUICKCHAT_W, height: h })
    quickchat.setResizable(false)
    setTimeout(() => { suppressQuickChatPosSave = false }, 120)
  })

  ipcMain.handle('quickchat:submit', async (_e, payload: string | QuickChatPayload) => {
    const r = await deliverQuickChat(payload)
    if (r.ok) dismissQuickChat()
    return r
  })
  // Esc / cancel from the bar.
  ipcMain.on('quickchat:close', () => dismissQuickChat())

  // ── Phase 4: desktop awareness (read-only capture) ──
  ipcMain.handle('capture:list-sources', async () => {
    if (!computerUseGate().screen) return [] // screen capture disabled
    const sources = await desktopCapturer.getSources({
      types: ['screen', 'window'],
      thumbnailSize: { width: 1, height: 1 },
    })
    return sources.map((s) => ({ id: s.id, name: s.name, display_id: s.display_id }))
  })

  // ── Phase 6: guarded actuation. Master switch (default OFF) + native confirm
  //    are the load-bearing local gate, independent of the server's decision. ──
  ipcMain.handle('actuate:open-app', (_e, target: string) =>
    runActuation('apps', nt('act.capOpenApp'), nt('act.detailTarget', { target }), async () => {
      if (/^https?:\/\//i.test(target)) await shell.openExternal(target)
      else await shell.openPath(target)
      return `opened ${target}`
    }),
  )
  ipcMain.handle('actuate:clipboard-write', (_e, text: string) =>
    runActuation('clipboard', nt('act.capClipboard'), text.slice(0, 80), async () => {
      clipboard.writeText(text)
      return 'clipboard written'
    }),
  )
  ipcMain.handle('actuate:type', (_e, text: string) =>
    runActuation('input', nt('act.capType'), text.slice(0, 80), async () => {
      const nut = await loadNut()
      await nut.keyboard.type(text)
      return `typed ${text.length} chars`
    }),
  )
  ipcMain.handle('actuate:key', (_e, keys: string) =>
    runActuation('input', nt('act.capKey'), keys, async () => {
      const nut = await loadNut()
      const parts = keys.toLowerCase().split('+').map((p) => p.trim())
      const mapped = parts.map((p) => nut.keyMap[p]).filter((k: unknown) => k !== undefined)
      if (mapped.length === 0) throw new Error(`unknown keys: ${keys}`)
      await nut.keyboard.pressKey(...mapped)
      await nut.keyboard.releaseKey(...mapped)
      return `pressed ${keys}`
    }),
  )
  ipcMain.handle('actuate:click', (_e, x: number, y: number, button?: string) =>
    runActuation('input', nt('act.capClick'), `(${x}, ${y})${lastCaptureDims ? ' [image px]' : ''} ${button ?? 'left'}`, async () => {
      const nut = await loadNut()
      const p = await mapImageToScreen(nut, x, y)
      await nut.mouse.setPosition(new nut.Point(p.x, p.y))
      await nut.mouse.click(nut.Button[(button ?? 'left').toUpperCase() as 'LEFT' | 'RIGHT' | 'MIDDLE'])
      return `clicked image(${x},${y}) → screen(${p.x},${p.y})`
    }),
  )
  // Launch-on-login toggle. Returns the EFFECTIVE state: enabling can be
  // refused (ephemeral AppImage mount, write failure) — then the config is
  // rolled back and the renderer shows why instead of a lying "on" toggle.
  ipcMain.handle('autostart:get', () => loadConfig().autoLaunch === true)
  ipcMain.handle('autostart:set', (_e, enabled: boolean) => {
    const effective = applyAutoLaunch(!!enabled) && !!enabled
    saveConfig({ autoLaunch: effective })
    return effective
  })

  // desktop_screenshot geometry: the primary display id (so the renderer captures
  // the PRIMARY), and the last screenshot's pixel size (so clicks map back).
  ipcMain.handle('capture:primary-display-id', () => String(screen.getPrimaryDisplay().id))
  ipcMain.on('capture:note-dims', (_e, w: number, h: number) => {
    if (w > 0 && h > 0) lastCaptureDims = { w, h }
  })
  ipcMain.handle('actuate:scroll', (_e, amount: number) =>
    runActuation('input', nt('act.capScroll'), `${amount > 0 ? nt('act.scrollDown') : nt('act.scrollUp')} ${Math.abs(amount)}`, async () => {
      const nut = await loadNut()
      if (amount >= 0) await nut.mouse.scrollDown(amount)
      else await nut.mouse.scrollUp(-amount)
      return `scrolled ${amount}`
    }),
  )

  // ── Phase 7: structured local control — browser (CDP) + apps (UIA) + Office
  //    (COM). Read ops need only the capability toggle (like screen capture);
  //    act ops ride the same prompt-once consent as the other actuation groups. ──
  const BROWSER_READ_OPS = new Set(['tabs', 'snapshot', 'read', 'screenshot'])
  const browserOpLabel = (op: string): string =>
    op === 'open' ? nt('act.capBrowserOpen') : op === 'eval' ? nt('act.capBrowserEval') : nt('act.capBrowser')
  ipcMain.handle('browser:call', async (_e, op: string, args: Record<string, unknown>) => {
    const gate = computerUseGate()
    if (!gate.browser) return { ok: false, denied: true, error: nt('act.capDisabled') }
    const a: Record<string, unknown> = { ...(args ?? {}) }
    if (op === 'open' && !a.engine) a.engine = loadConfig().computerUse?.browserEngine ?? 'auto'
    if (BROWSER_READ_OPS.has(op)) {
      try {
        return { ok: true, result: await browserCall(op, a) }
      } catch (e) {
        return { ok: false, error: String((e as Error).message) }
      }
    }
    const detail = op === 'open' ? String(a.url ?? '') : op === 'act' ? `${a.action} ${a.element ?? ''}` : op
    return runActuation('browser', browserOpLabel(op), detail.slice(0, 120), () => browserCall(op, a))
  })

  const WINAUTO_READ_OPS = new Set(['windows', 'win_snapshot', 'win_read', 'office_status', 'office_read'])
  ipcMain.handle('winauto:call', async (_e, op: string, args: Record<string, unknown>) => {
    const gate = computerUseGate()
    if (!gate.apps) return { ok: false, denied: true, error: nt('act.capDisabled') }
    const host = getWinAutoHost()
    const a: Record<string, unknown> = args ?? {}
    if (WINAUTO_READ_OPS.has(op)) {
      try {
        return { ok: true, result: await host.call(op, a, 40000) }
      } catch (e) {
        return { ok: false, error: String((e as Error).message) }
      }
    }
    const label = op.startsWith('office') ? nt('act.capOfficeControl') : nt('act.capAppControl')
    const detail = op === 'el_act' ? `${a.action} ${a.element ?? ''}` : op === 'office_act' ? `${a.app}: ${a.action}` : op
    return runActuation('apps', label, String(detail).slice(0, 120), async () => {
      const r = (await host.call(op, a, 40000)) as Record<string, unknown> | null
      // Pattern-less control → fall back to a REAL click at its UIA center
      // (UIA bounds are physical desktop px — nut.js's coordinate space).
      if (r && r['no_pattern'] && Array.isArray(r['bounds'])) {
        const [bx, by, bw, bh] = r['bounds'] as number[]
        const nut = await loadNut()
        await nut.mouse.setPosition(new nut.Point(Math.round(bx + bw / 2), Math.round(by + bh / 2)))
        await nut.mouse.click(nut.Button.LEFT)
        return { done: `clicked the control center (no automation pattern) at (${Math.round(bx + bw / 2)},${Math.round(by + bh / 2)})`, fallback: 'click' }
      }
      return r
    })
  })

  // ── Local MCP proxy (Phase 3): the connector hosts MCP clients to the user's
  //    local MCP servers; the renderer bridge + server reach them via these. ──
  const broadcastMcpStatus = (): void => {
    let status: unknown = []
    try { status = getMcpManager().status() } catch { /* SDK missing */ }
    for (const w of BrowserWindow.getAllWindows()) {
      try { w.webContents.send('mcp:status-event', status) } catch { /* window gone */ }
    }
  }
  ipcMain.handle('mcp:list-servers', () => loadConfig().mcpServers ?? [])
  ipcMain.handle('mcp:advertise', async () => {
    // Master off → advertise nothing (server unregisters the tools). A total
    // failure is an EMPTY catalog, never a phantom server entry.
    if (loadConfig().mcpEnabled === false) return []
    try { return await getMcpManager().advertise() } catch { return [] }
  })
  ipcMain.handle('mcp:call-tool', async (_e, server: string, tool: string, args: unknown) => {
    if (loadConfig().mcpEnabled === false) return { ok: false, error: 'local MCP is disabled in the connector settings' }
    try { return { ok: true, result: await getMcpManager().callTool(server, tool, args) } }
    catch (e) { return { ok: false, error: String((e as Error).message) } }
  })
  ipcMain.handle('mcp:test-server', async (_e, cfg: MCPServerConfig) => getMcpManager().test(cfg))
  ipcMain.handle('mcp:add-server', (_e, cfg: MCPServerConfig) => {
    const list = (loadConfig().mcpServers ?? []).filter((s) => s.name !== cfg.name)
    return (saveConfig({ mcpServers: [...list, cfg] }).mcpServers) ?? []
  })
  // Edit in place; renaming replaces the original entry (originalName ≠ cfg.name).
  ipcMain.handle('mcp:update-server', (_e, originalName: string, cfg: MCPServerConfig) => {
    const list = (loadConfig().mcpServers ?? []).filter((s) => s.name !== originalName && s.name !== cfg.name)
    return (saveConfig({ mcpServers: [...list, cfg] }).mcpServers) ?? []
  })
  ipcMain.handle('mcp:remove-server', (_e, name: string) => {
    const list = (loadConfig().mcpServers ?? []).filter((s) => s.name !== name)
    return (saveConfig({ mcpServers: list }).mcpServers) ?? []
  })
  ipcMain.handle('mcp:get-enabled', () => loadConfig().mcpEnabled !== false)
  ipcMain.handle('mcp:set-enabled', (_e, enabled: boolean) => {
    saveConfig({ mcpEnabled: !!enabled })
    broadcastMcpStatus() // windows repaint + the bridge re-advertises
    return !!enabled
  })
  ipcMain.handle('mcp:status', () => getMcpManager().status())
  // Status push → every window (settings UI repaints; the overlay's
  // ConnectorBridgeClient re-advertises the catalog to the backend).
  try {
    getMcpManager().onStatusChange(() => broadcastMcpStatus())
  } catch { /* SDK missing */ }

  // ── Workspace sync (Drive-style local↔agent-workspace replication) ──
  const broadcastSyncStatus = (statuses: unknown): void => {
    for (const w of BrowserWindow.getAllWindows()) {
      try { w.webContents.send('sync:status-event', statuses) } catch { /* window gone */ }
    }
  }
  const reconfigureSync = (): void => {
    // Single source of truth: the drive orchestrator computes the ACTIVE
    // pair set (cloud gate, link exclusions, shortcuts). Configuring from
    // raw saved pairs here would resurrect parked engines.
    applyDriveConfig()
  }

  // ── Geny Drive ────────────────────────────────────────────────────────
  // One root, one folder per connected agent — the user picks WHICH agents
  // live on the drive, never where each one goes. Drive-owned pairs carry
  // managed:'drive'; classic hand-made pairs are untouched and keep working.

  // Drive mutations are serialized: drive:set-root quiesces engines and then
  // moves directories (seconds of awaited work), and the main process keeps
  // servicing IPC during those awaits — a cloud/agent toggle landing in that
  // window would applyDriveConfig() against the OLD root and start engines
  // watching the very directories the move is about to rename. One chain,
  // every mutation queues behind the previous one.
  let driveOpChain: Promise<unknown> = Promise.resolve()
  const driveExclusive = <T>(fn: () => Promise<T>): Promise<T> => {
    const run = driveOpChain.then(fn, fn)
    driveOpChain = run.then(
      () => undefined,
      () => undefined,
    )
    return run
  }

  ipcMain.handle('drive:get', async () => {
    ensureAllLinkShortcuts() // cheap, idempotent — repairs a lost race
    const cfg = loadConfig()
    return {
      root: driveRoot(),
      statuses: getSyncManager()?.statuses() ?? [],
      // Whether the install-time "Geny Cloud" option was accepted, and what
      // this machine can actually do (probed, never assumed).
      cloudOptIn: cfg.cloudOptIn !== false,
      capabilities: driveCapabilities(),
    }
  })

  // Per-agent usage/quota in ONE round trip (the Drive list would otherwise
  // issue a /storage/changes per agent just to read used_bytes).
  ipcMain.handle('drive:usage', async () => {
    const cfg = loadConfig()
    const token = await getStoredToken()
    if (!cfg.serverUrl || !token) return {}
    try {
      const res = await fetch(`${cfg.serverUrl.replace(/\/$/, '')}/api/agents/storage/summary`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) return {}
      const data = (await res.json()) as {
        agents?: Array<{ session_id: string; used_bytes: number | null; quota_bytes: number }>
      }
      return Object.fromEntries(
        (data.agents ?? []).map((a) => [a.session_id, { used: a.used_bytes, quota: a.quota_bytes }]),
      )
    } catch {
      return {}
    }
  })

  ipcMain.handle('drive:set-cloud', (_e, enabled: boolean) =>
    driveExclusive(async () => {
      saveConfig({ cloudOptIn: !!enabled })
      applyDriveConfig()
      return { cloudOptIn: !!enabled }
    }),
  )

  // ── Native virtual drive (Linux/FUSE sidecar — D4) ──────────────
  // FUSE cannot run inside Electron (V8 memory cage corrupts external
  // buffers — proven by spike), so a Go sidecar mounts the drive and
  // speaks the same storage REST as the mirror engine. The connector
  // owns lifecycle + token freshness (the daemon re-reads the token
  // file on 401).
  let daemonProc: ReturnType<typeof spawn> | null = null
  let daemonTokenTimer: NodeJS.Timeout | null = null
  const daemonTokenFile = (): string => join(app.getPath('userData'), 'drive-daemon.token')
  const daemonBinary = (): string => {
    const exe = process.platform === 'win32' ? 'geny-drive-daemon.exe' : 'geny-drive-daemon'
    const cand = [
      join(process.resourcesPath ?? '', exe),
      join(app.getAppPath(), '..', exe),
    ]
    return cand.find((p) => existsSync(p)) ?? ''
  }
  const writeDaemonToken = async (): Promise<boolean> => {
    const tok = await getStoredToken()
    if (!tok) return false
    writeFileSync(daemonTokenFile(), tok, { mode: 0o600 })
    return true
  }
  const nativeMountpoint = (): string =>
    join(app.getPath('home'), process.platform === 'win32' ? 'GenyDrive-Cloud' : 'GenyDrive-Live')

  const stopNativeMount = (opts: { unregister?: boolean } = {}): void => {
    if (daemonTokenTimer) { clearInterval(daemonTokenTimer); daemonTokenTimer = null }
    if (daemonProc) { try { daemonProc.kill() } catch { /* gone */ } daemonProc = null }
    try { unlinkSync(daemonTokenFile()) } catch { /* absent */ }
    // A FUSE mount dies with its process; a Windows SYNC ROOT does not —
    // it is registered state that survives reboots (that is what makes
    // Explorer remember the drive). Turning the drive OFF must therefore
    // unregister it explicitly, or the placeholders linger with nothing
    // able to hydrate them.
    if (opts.unregister && process.platform === 'win32') {
      const bin = daemonBinary()
      if (bin) {
        try {
          spawn(bin, ['--unregister', '--mountpoint', nativeMountpoint()], { stdio: 'ignore' })
        } catch { /* best effort */ }
      }
    }
  }
  // Quitting stops the daemon but must NOT unregister the Windows sync
  // root: the drive should still be there next launch (that is the whole
  // point of registered state). Only the user's own toggle unregisters.
  app.on('will-quit', () => stopNativeMount())

  startNativeMount = async (): Promise<{ mounted?: boolean; mountpoint?: string; error?: string }> => {
    const bin = daemonBinary()
    if (!bin) return { error: 'daemon binary not bundled for this platform' }
    const cfg = loadConfig()
    if (!cfg.serverUrl) return { error: 'not signed in' }
    if (!(await writeDaemonToken())) return { error: 'no auth token' }
    const mnt = nativeMountpoint()
    try { mkdirSync(mnt, { recursive: true }) } catch { /* exists */ }
    stopNativeMount() // idempotent restart
    await writeDaemonToken()
    // Force-clear a stale FUSE mount before taking the path (a previous
    // run killed with SIGKILL can leave one; mounting over it would
    // stack). Windows re-registers with UPDATE instead — no clearing.
    if (process.platform !== 'win32') {
      try {
        spawn('fusermount3', ['-u', mnt], { stdio: 'ignore' })
      } catch { /* not mounted / no fusermount — mount will tell us */ }
    }
    daemonProc = spawn(bin, [
      '--server', cfg.serverUrl.replace(/\/$/, ''),
      '--token-file', daemonTokenFile(),
      '--mountpoint', mnt,
      // The daemon unmounts itself if we vanish — a mount outliving the
      // app would keep answering with nothing behind it.
      '--parent-pid', String(process.pid),
    ], { stdio: 'ignore', detached: false })
    daemonProc.on('exit', (code) => {
      dlog('drive', `native mount daemon exited (${code})`)
      daemonProc = null
    })
    // Keep the token file fresh so a long-lived mount survives rotation.
    daemonTokenTimer = setInterval(() => { void writeDaemonToken() }, 10 * 60 * 1000)
    daemonTokenTimer.unref?.()
    saveConfig({ nativeMount: true })
    return { mounted: true, mountpoint: mnt }
  }

  ipcMain.handle('drive:native-mount', async (_e, enable: boolean) => {
    if (!enable) {
      stopNativeMount({ unregister: true })
      saveConfig({ nativeMount: false })
      return { mounted: false }
    }
    return startNativeMount()
  })

  ipcMain.handle('drive:native-status', () => ({
    running: !!daemonProc,
    mountpoint: nativeMountpoint(),
    // Linux needs a working FUSE stack; Windows needs Cloud Files API
    // (build 16299+). Both are what the preflight probe reports. macOS is
    // excluded on purpose — its FUSE needs a kext the user must install.
    supported:
      (process.platform === 'linux' || process.platform === 'win32') &&
      driveCapabilities().streaming &&
      !!daemonBinary(),
  }))

  ipcMain.handle('drive:pick-root', async () => {
    const res = await dialog.showOpenDialog({
      properties: ['openDirectory', 'createDirectory'],
      defaultPath: driveRoot(),
    })
    if (res.canceled || !res.filePaths[0]) return null
    return res.filePaths[0]
  })

  // Relocate the whole drive: MOVE every managed folder to the new root, then
  // re-point the pairs. Sync engines are stopped first so nothing writes into
  // a directory being moved, and per-pair indexes are preserved (they are
  // keyed by pair id, not path) so a relocation costs zero re-download.
  ipcMain.handle('drive:set-root', (_e, newRoot: string) =>
    driveExclusive(async () => {
    const target = String(newRoot || '').trim()
    if (!target) return { ok: false, error: 'empty path' }
    const current = driveRoot()
    if (target === current) return { ok: true, root: current, moved: 0 }
    // Stop engines and WAIT for in-flight rounds — `configure([])` would also
    // delete the per-pair indexes (forcing a full re-bootstrap), and a live
    // watcher would recreate the very directory we are moving.
    await getSyncManager()?.quiesce()
    let moved = 0
    try {
      mkdirSync(target, { recursive: true })
      // The drive is ONE folder now. This used to iterate per-agent mirrors
      // and, once those were removed, moved nothing at all — relocating the
      // drive silently left the whole cloud mirror at the old path and made
      // the engine re-download it into the new one.
      for (const folder of ['Cloud']) {
        const from = join(current, folder)
        const to = join(target, folder)
        if (!existsSync(from) || existsSync(to)) continue
        try {
          renameSync(from, to) // same volume: instant
        } catch {
          // Cross-volume (EXDEV) or locked: copy then remove the source.
          cpSync(from, to, { recursive: true })
          rmSync(from, { recursive: true, force: true })
        }
        moved++
        // A late watcher event can leave an EMPTY husk behind; never remove a
        // source that still holds data.
        try {
          if (existsSync(from) && readdirSync(from).length === 0) rmSync(from, { recursive: true })
        } catch {
          /* leftover husk is harmless */
        }
      }
    } catch (e) {
      applyDriveConfig() // restart engines on the OLD root — never leave them dead
      return { ok: false, error: (e as Error)?.message ?? String(e) }
    }
    saveConfig({ driveRoot: target })
    applyDriveConfig()
    dlog('drive', `root moved ${current} → ${target} (${moved} folder(s))`)
    return { ok: true, root: target, moved }
    }),
  )
  ipcMain.handle('sync:list', () => {
    const cfg = loadConfig()
    return {
      // Links are the config of record; the engines are derived from them,
      // so a link is listed even before its engine exists.
      links: cfg.driveLinks ?? [],
      statuses: getSyncManager()?.statuses() ?? [],
    }
  })
  ipcMain.handle('sync:pick-folder', async () => {
    const res = await dialog.showOpenDialog({
      properties: ['openDirectory', 'createDirectory'],
      title: 'Workspace 폴더 선택',
    })
    return res.canceled ? null : res.filePaths[0]
  })
  ipcMain.handle('sync:add-pair', (_e, pair: { localPath: string }) =>
    driveExclusive(async () => {
      const localPath = String(pair?.localPath || '').replace(/[\\/]+$/, '')
      if (!localPath) return { error: 'empty path' }
      const cfg = loadConfig()
      const links = [...(cfg.driveLinks ?? [])]
      // One binding per folder; nested folders would make two engines walk
      // the same files through the shared disk.
      for (const l of links) {
        const ex = l.localPath.replace(/[\\/]+$/, '')
        if (ex === localPath || ex.startsWith(localPath + sep) || localPath.startsWith(ex + sep)) {
          return { error: 'overlap', conflictWith: l.name }
        }
      }
      const root = driveRoot()
      // The shortcut lives at the DRIVE ROOT next to agent folders — the
      // name must not collide with links, agent folders, or anything the
      // user already keeps there.
      const taken = new Set<string>([
        // The cloud owns `agents/` and `gapt/`: an agent's space and the
        // user's GAPT workspaces live there. A linked folder taking one of
        // those names would be mirrored straight on top of the structure.
        'agents',
        'gapt',
        ...links.map((l) => l.name),
        ...(existsSync(root) ? readdirSync(root) : []),
      ])
      const name = allocateLinkName(basename(localPath), taken)
      links.push({ name, localPath })
      saveConfig({ driveLinks: links })
      // Quiesce before reconfiguring: starting an engine on a path while
      // another round is mid-flight reads its churn as user edits.
      await getSyncManager()?.quiesce()
      applyDriveConfig()
      return { ok: true, name }
    }),
  )
  ipcMain.handle('sync:remove-pair', (_e, name: string) =>
    driveExclusive(async () => {
      const cfg = loadConfig()
      const gone = (cfg.driveLinks ?? []).find((l) => l.name === name)
      if (!gone) return { ok: true }
      // Unlinking ends the binding between the user's folder and the
      // cloud. It does NOT delete the cloud copy: the cloud is the hub,
      // and what reached it is cloud content now — the same stance every
      // consumer drive takes. The user's own folder is untouched too.
      saveConfig({ driveLinks: (cfg.driveLinks ?? []).filter((l) => l.name !== name) })
      await getSyncManager()?.quiesce()
      removeLinkShortcut(cloudFolder(), gone.name, gone.localPath)
      removeLinkShortcut(driveRoot(), gone.name, gone.localPath) // legacy spot
      // The cloud mirror stops excluding that subtree, so it now syncs
      // down as ordinary cloud content.
      getSyncManager()?.dropIndex(`link:${name}`)
      applyDriveConfig()
      return { ok: true }
    }),
  )

  ipcMain.handle('sync:set-paused', (_e, name: string, paused: boolean) => {
    // Pausing a LINK pauses it on every agent — it is one binding.
    const links = (loadConfig().driveLinks ?? []).map((l) =>
      l.name === name ? { ...l, paused: !!paused } : l,
    )
    saveConfig({ driveLinks: links })
    reconfigureSync()
    return { ok: true }
  })
  ipcMain.handle('sync:sync-now', (_e, id: string) => getSyncManager()?.syncNow(id))
  ipcMain.handle('sync:confirm-mass-delete', (_e, id: string, accept: boolean) => {
    getSyncManager()?.confirmMassDelete(id, !!accept)
    if (!accept) {
      // refusal pauses the pair — persist that
      pauseLink(id, 'user refused a mass delete')
    }
  })
  ipcMain.handle('sync:open-folder', (_e, id: string) => {
    // Resolve against the LIVE engines. Pairs are derived, so looking them
    // up in the config found nothing and the button quietly did nothing.
    const st = getSyncManager()?.statuses().find((x) => x.id === id)
    if (st?.localPath) void shell.openPath(st.localPath)
  })
  // Agent list for the pairing picker (main process owns the token).
  ipcMain.handle('sync:list-agents', async () => {
    const cfg = loadConfig()
    const token = await getStoredToken()
    if (!cfg.serverUrl || !token) return []
    try {
      const res = await fetch(`${cfg.serverUrl.replace(/\/$/, '')}/api/agents`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) return []
      const data = await res.json()
      const sessions = Array.isArray(data) ? data : (data?.sessions ?? data?.agents ?? [])
      return (sessions as Array<Record<string, unknown>>).map((s) => ({
        id: String(s.session_id ?? s.id ?? ''),
        // Geny's SessionInfo carries the human label as `session_name`.
        name: String(s.session_name ?? s.name ?? s.display_name ?? s.session_id ?? s.id ?? ''),
      })).filter((s) => s.id)
    } catch {
      return []
    }
  })

  // Control panel picked a session → point the overlay at it.
  ipcMain.on('overlay:set-session', (_e, sessionId: string) => {
    saveConfig({ overlaySession: sessionId })
    applyOverlayContent()
  })

  // Auto-update toggle (default ON) + manual check.
  ipcMain.handle('updater:get-enabled', () => loadConfig().autoUpdate !== false)
  ipcMain.handle('updater:set-enabled', (_e, enabled: boolean) => {
    saveConfig({ autoUpdate: enabled })
    if (enabled) triggerBackgroundCheck() // re-enabled → check right away
    return enabled
  })
  ipcMain.on('updater:check', () => checkForUpdatesManually())

  // Secure token storage via Electron safeStorage (see secureSet/secureGet —
  // the keytar native module it replaced could silently fail and strand login).
  ipcMain.handle('secure:get', async (_e, key: string) => secureGet(key))
  ipcMain.handle('secure:set', async (_e, key: string, value: string) => secureSet(key, value))
  ipcMain.handle('secure:delete', async (_e, key: string) => secureDelete(key))

  // In-app debug log: renderers append their side of a flow (login steps),
  // the settings window reads the merged buffer for copy-paste bug reports.
  ipcMain.on('debug:log', (_e, line: string) => {
    if (typeof line === 'string') dlog('ui', line.slice(0, 500))
  })
  ipcMain.handle('debug:get', () => debugLines.join('\n'))
}

// Native application menu — keeps copy/paste accelerators (chat input) and
// surfaces 설정 / 업데이트 / 로그아웃 so options are always reachable.
function buildAppMenu(): void {
  const menu = Menu.buildFromTemplate([
    {
      label: 'Geny',
      submenu: [
        { label: nt('menu.settings'), accelerator: 'CmdOrCtrl+,', click: () => showSettings() },
        { label: nt('menu.control'), click: () => showControl() },
        { label: nt('menu.checkUpdate'), click: () => void checkForUpdatesManually() },
        { type: 'separator' },
        { label: nt('menu.restart'), click: () => relaunchSelf() },
        { label: nt('menu.logout'), click: () => void logout() },
        { role: 'quit', label: nt('menu.quit') },
      ],
    },
    {
      label: nt('menu.edit'),
      submenu: [
        { role: 'undo', label: nt('menu.undo') },
        { role: 'redo', label: nt('menu.redo') },
        { type: 'separator' },
        { role: 'cut', label: nt('menu.cut') },
        { role: 'copy', label: nt('menu.copy') },
        { role: 'paste', label: nt('menu.paste') },
        { role: 'selectAll', label: nt('menu.selectAll') },
      ],
    },
    {
      label: nt('menu.view'),
      submenu: [
        { role: 'reload', label: nt('menu.reload') },
        { role: 'toggleDevTools', label: nt('menu.devTools') },
        { type: 'separator' },
        { role: 'resetZoom', label: nt('menu.resetZoom') },
        { role: 'zoomIn', label: nt('menu.zoomIn') },
        { role: 'zoomOut', label: nt('menu.zoomOut') },
      ],
    },
  ])
  Menu.setApplicationMenu(menu)
}

app.whenReady().then(() => {
  // Environment fingerprint, logged once at boot. "The avatar is blank /
  // keeps reloading" is almost always one of these lines, and without
  // them every report costs a round trip to ask.
  try {
    const info = app.getGPUFeatureStatus?.() as unknown as Record<string, string> | undefined
    dlog(
      'env',
      `platform=${process.platform} ozone=${process.env.GENY_OZONE_PLATFORM || (IS_LINUX ? 'x11' : 'default')} ` +
        `session=${process.env.XDG_SESSION_TYPE || '?'} wayland=${process.env.WAYLAND_DISPLAY ? 'yes' : 'no'}`,
    )
    if (info) {
      dlog('env', `gpu webgl=${info.webgl ?? '?'} compositing=${info.gpu_compositing ?? '?'}`)
    }
  } catch { /* diagnostics only */ }

  dlog(
    'boot',
    `v${app.getVersion()} ${process.platform}/${process.arch} exec=${process.execPath}` +
      `${process.env.APPIMAGE ? ` appimage=${process.env.APPIMAGE}` : ''}` +
      ` argv=[${process.argv.slice(1).join(' ')}]` +
      ` encAvail=${safeStorage.isEncryptionAvailable()}` +
      (process.platform === 'linux' ? ` encBackend=${safeStorage.getSelectedStorageBackend()}` : ''),
  )
  // Screen-observation uses getDisplayMedia, which in Electron needs the app to
  // satisfy the display-media request (unlike a browser's built-in picker).
  // Prefer the OS picker where available; fall back to the primary screen.
  session.defaultSession.setDisplayMediaRequestHandler(
    (_request, callback) => {
      desktopCapturer
        .getSources({ types: ['screen', 'window'] })
        .then((sources) => callback(sources[0] ? { video: sources[0] } : {}))
        .catch(() => callback({}))
    },
    { useSystemPicker: true },
  )

  // Grant mic (STT) + screen (observation) + clipboard to our own pages.
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(['media', 'display-capture', 'clipboard-read', 'clipboard-sanitized-write'].includes(permission))
  })

  registerIpc()
  startSystemStats()
  // Load the user's local MCP servers into the manager (lazy-connects on use).
  try { getMcpManager().configure(loadConfig().mcpServers) } catch { /* SDK missing */ }

  // Workspace sync engine: one stable device id per install, engines per
  // configured pairing. Started AFTER auth validation below (engines read
  // the token lazily per request, so early start is also safe).
  try {
    if (!loadConfig().deviceId) saveConfig({ deviceId: randomUUID() })
    const manager = initSyncManager({
      indexDir: join(app.getPath('userData'), 'sync-index'),
      serverUrl: () => loadConfig().serverUrl ?? '',
      token: () => getStoredToken(),
      deviceId: () => loadConfig().deviceId as string,
      onStatus: (statuses) => {
        for (const w of BrowserWindow.getAllWindows()) {
          try { w.webContents.send('sync:status-event', statuses) } catch { /* window gone */ }
        }
      },
      log: (msg) => dlog('sync', msg),
      onAutoPause: (id, reason) => {
        // persist the auto-pause (WITH its reason, so the explanation
        // survives the engine teardown) AND tear the engine down
        // (watcher/WS must not keep running on an inert pair)
        pauseLink(id, reason)
      },
    })
    // Reconcile Geny Drive first (creates/moves managed pairs), which also
    // configures the manager; falls back to raw pairs if the drive is unset.
    try {
      consumeInstallFlags()
      dropLegacyDriveState()
      applyDriveConfig()
      // Restore the native mount the user left enabled. Delayed so the
      // token store is ready; a missing token simply skips it (the toggle
      // still works once signed in).
      if (loadConfig().nativeMount) {
        setTimeout(() => {
          void startNativeMount().catch((e) =>
            dlog('drive', `native mount restore failed: ${(e as Error)?.message}`),
          )
        }, 4000).unref?.()
      }
    } catch (e) {
      // applyDriveConfig is the ONLY way to build the pair set (cloud gate,
      // link exclusions, shortcuts). The old fallback replayed stored pairs,
      // which no longer exist — leaving the drive dead is worse than a
      // logged failure, so surface it and let the next config change retry.
      dlog('drive', `drive init failed: ${(e as Error)?.message ?? e}`)
    }
  } catch (e) {
    console.error('[sync] init failed', e)
  }
  // Reconcile the OS login item with the saved preference (default off) — keeps
  // the autostart entry in sync if the app moved or the setting changed offline.
  applyAutoLaunch(loadConfig().autoLaunch === true)
  // Restore the Linux click-through opt-in BEFORE the overlay first applies
  // its mouse policy (applyOverlayContent reads this flag).
  // (legacy `linuxClickThrough` opt-in retired — main hit-tests now)
  buildAppMenu()
  createOverlay()
  createControl()
  createSettings()
  createQuickChat()
  createTray()

  // Re-establish the session BEFORE deciding which window to show: validate the
  // stored JWT and mint a fresh-expiry one (or drop it if truly dead), so a
  // restart re-logs-in cleanly instead of showing "saved but not working". Then
  // show the right window: logged in → the /connector panel; logged out → the
  // settings/login window. (The avatar overlay always runs.)
  void (async () => {
    await validateAndRefreshAuth()
    await refreshAll()
  })()

  // Keep a long-running connector authenticated: re-mint the token well within
  // its lifetime so it never silently expires mid-session, and fall back to the
  // login window if it ever becomes invalid.
  authRefreshTimer = setInterval(() => {
    void validateAndRefreshAuth().then((ok) => { if (!ok) void refreshAll() })
  }, 12 * 60 * 60 * 1000)

  // GitHub Releases auto-update. Default ON; the toggle is read fresh on every
  // check, so changes take effect immediately.
  initAutoUpdate(() => loadConfig().autoUpdate !== false, () => resolvedLang())

  // Register the global hotkeys (push-to-talk + quick-chat).
  registerHotkeys()

  // After the machine wakes from sleep, the loaded pages' WS / network state can
  // be stale (the avatar freezes, chat stops) and previously needed an app
  // restart. Reload the remote pages so they reconnect cleanly. Debounced — some
  // platforms fire resume more than once.
  let resumeTimer: ReturnType<typeof setTimeout> | null = null
  powerMonitor.on('resume', () => {
    if (resumeTimer) clearTimeout(resumeTimer)
    resumeTimer = setTimeout(() => {
      void applyOverlayContent()
      void applyControlContent()
    }, 1500)
  })

  // Monitor plug/unplug/rearrange → rescue any window that ended up off-screen
  // (so windows are never lost on the disconnected monitor). Debounced.
  let displayTimer: ReturnType<typeof setTimeout> | null = null
  const onDisplayChange = () => {
    // Mark a DPI-settle window so bounds saves hold off on transient rescale
    // values (see attachBoundsPersistence), then rescue off-screen windows.
    dpiSettleUntil = Date.now() + 1800
    if (displayTimer) clearTimeout(displayTimer)
    displayTimer = setTimeout(ensureWindowsOnScreen, 900)
  }
  screen.on('display-removed', onDisplayChange)
  screen.on('display-added', onDisplayChange)
  screen.on('display-metrics-changed', onDisplayChange)

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createOverlay()
  })
})

// The overlay is always-on-top with no taskbar entry; closing the control window
// must NOT quit the app (it hides to tray). Quit is via the tray menu. So we do
// NOT auto-quit on window-all-closed except as a safety net when the tray is gone.
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
