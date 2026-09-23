import { contextBridge, ipcRenderer } from 'electron'

// ─────────────────────────────────────────────────────────────────────────────
// connectorBridge — the ONLY surface the renderer uses to reach native power.
//
// The renderer never imports `electron` directly (PLAN §2.1 hedge): everything
// native goes through this typed bridge, so a future Tauri backend can supply
// the same shape without touching renderer code. Phase 0 implements the subset
// needed for the floating overlay; screenCapture / mic / hotkeys / actuation are
// declared as the surface grows (Phases 3–6) but only wired when implemented.
// ─────────────────────────────────────────────────────────────────────────────

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
  /** TTS output device, chosen by LABEL ('' = system default). deviceId isn't
   *  portable across windows/origins, so the overlay resolves the label to a
   *  current device (and re-resolves when devices change — VoiceMeeter race). */
  audioOutputLabel?: string
  /** Mic input device, chosen by LABEL ('' = system default). */
  audioInputLabel?: string
}

/** What the avatar window is doing (see main/avatar-bridge.ts). */
export interface AvatarState {
  sessionId: string | null
  tts: boolean
  stt: boolean
  realtime: boolean
  captions: boolean
  screen: boolean
  ptt: boolean
  speaking: boolean
  listening: boolean
}

export type AvatarSwitch = 'tts' | 'stt' | 'realtime' | 'captions' | 'screen' | 'ptt'

export type AvatarCommand =
  | { type: 'set'; key: AvatarSwitch; value: boolean }
  | { type: 'speak'; text: string }
  | { type: 'hush' }

/** Consent posture for an actuation capability group. */
export type ConsentMode = 'ask' | 'session' | 'auto'
/** Local Computer Use — per-capability consent (local bridge). */
export interface ComputerUseConfig {
  enabled?: boolean
  screen?: boolean
  input?: boolean
  apps?: boolean
  clipboard?: boolean
  /** Structured browser control (dedicated Chrome/Edge automation instance). */
  browser?: boolean
  browserEngine?: 'auto' | 'chrome' | 'edge'
  consentMode?: ConsentMode
}

/** A local MCP server the connector hosts + proxies to the Geny agent. */
export interface MCPServerConfig {
  name: string
  transport: 'stdio' | 'http'
  command?: string
  env?: Record<string, string>
  url?: string
  headers?: Record<string, string>
  enabled?: boolean
}
export interface MCPToolSchema {
  name: string
  description?: string
  inputSchema?: Record<string, unknown>
}
export interface MCPServerAdvert {
  name: string
  connected: boolean
  error?: string
  tools: MCPToolSchema[]
}

export interface ConnectorConfig {
  serverUrl: string
  theme?: 'system' | 'dark' | 'light'
  /** UI language for the settings window. Unset → resolved from the OS locale. */
  lang?: 'ko' | 'en'
  overlay?: { x: number; y: number; width: number; height: number; displayId?: number }
  overlayTuning?: OverlayTuning
  computerUse?: ComputerUseConfig
  mcpServers?: MCPServerConfig[]
}

export interface SystemStats {
  /** 0-100, all cores, over the last sample interval. */
  cpu: number
  /** Bytes. */
  memUsed: number
  memTotal: number
  /** The connector's own resident memory, in bytes. */
  appMem: number
  cores: number
  /** 1-minute load average; 0 on Windows, which keeps none. */
  load1: number
}

export interface ConnectorBridge {
  /** Which window this renderer is: 'overlay' (avatar), 'settings'/'control', or
   *  'quickchat' (the floating Spotlight-style input bar). */
  windowKind: 'overlay' | 'control' | 'settings' | 'quickchat' | 'chip'

  /** Connector app version (package.json), for the settings window. */
  appVersion(): Promise<string>

  /** In-app debug log — renderers append flow steps, settings reads the
   *  merged main-process buffer for copyable bug reports. */
  debug: {
    log(line: string): void
    get(): Promise<string>
  }

  /** OS-derived default UI language ('ko' if the OS locale starts with "ko",
   *  else 'en'). The settings window uses this when config.lang is unset. */
  appDefaultLang(): Promise<'ko' | 'en'>

  /** This machine, for the status bar. `get()` is the first reading (so a
   *  fresh window shows numbers immediately); `onChange` is the 2s push. */
  system: {
    get(): Promise<SystemStats>
    onChange(cb: (stats: SystemStats) => void): () => void
  }

  serverConfig: {
    get(): Promise<ConnectorConfig>
    set(patch: Partial<ConnectorConfig>): Promise<ConnectorConfig>
    /** Subscribe to live config changes (main broadcasts after every set);
     *  used by the overlay to apply overlayTuning without a reload. */
    onChange(cb: (cfg: ConnectorConfig) => void): () => void
  }

  /** Encrypted secret store (Electron safeStorage) — the account JWT, not the password. */
  secureStore: {
    get(key: string): Promise<string | null>
    set(key: string, value: string): Promise<boolean>
    delete(key: string): Promise<boolean>
  }

  windowControl: {
    /** true = clicks pass through to the app behind; false = overlay captures. */
    setClickThrough(ignore: boolean): void
    setInteractiveRects(rects: Array<{ x: number; y: number; w: number; h: number }>): void
    /** Chip window reports its rendered size (main sizes/places the window). */
    chipSize(w: number, h: number): void
    /** Lock/unlock from either window — main owns the state. */
    setLocked(locked: boolean): void
    onSetLocked(cb: (locked: boolean) => void): () => void
    /** Avatar page only: how many pixels of the window's BOTTOM the chip
     *  window is currently covering. The chip is a separate always-on-top
     *  window, so the page cannot see it; anything anchored to the bottom
     *  (subtitle, hands-free caption) must lift by this much or the two
     *  draw on top of each other. 0 while the chip is hidden. */
    requestChipInset(): void
    onChipInset(cb: (px: number) => void): () => void
    /** Move the overlay by a pixel delta (dock-handle drag). */
    moveBy(dx: number, dy: number): void
    /** Signal the end of a drag so main drops its authoritative drag rect
     *  immediately (it also auto-expires ~300ms after the last moveBy). */
    moveEnd(): void
    /** Resize the overlay from an edge/corner handle by a pixel delta (unlocked).
     *  `edge` is a combo of n/s/e/w (e.g. 'se', 'n'). */
    resizeOverlayBy(edge: string, dx: number, dy: number): void
    /** Show/hide the control (chat/settings) window. */
    toggleControl(): void
    /** Always show + focus the control window (chat/settings); never hides. */
    openControl(): void
    /** Re-load BOTH windows after login/logout (token changed in keychain). */
    refresh(): void
    /** Set which session the floating overlay renders, and reload it. */
    setOverlaySession(sessionId: string): void
    /** Open the settings window (server URL / account / auto-update). */
    openSettings(): void
    /** Restart the whole connector app (reloads overlay/panel + native code). */
    restart(): void
    /** Open a URL in the user's default browser (e.g. the Geny web app). */
    openExternal(url: string): void
    /** Reload only the chat/control panel (e.g. after a theme change). */
    reloadPanel(): void
    /** Reset every window's position/size + the avatar view to defaults. */
    resetPositions(): void
    /** Overlay page only: fired when the user resets positions — clear the saved
     *  pan/zoom + reload so the avatar returns to its default framing. */
    onResetView(cb: () => void): () => void
  }

  /** The avatar's switches, from any window. The avatar window publishes and
   *  obeys; every other window reads and asks. */
  avatar: {
    /** Avatar window only: report the current state. */
    publish(state: AvatarState): void
    /** Avatar window only: receive a command another window sent. */
    onCommand(cb: (command: AvatarCommand) => void): () => void
    /** The last state the avatar reported, or null when none is up. */
    getState(): Promise<AvatarState | null>
    onState(cb: (state: AvatarState | null) => void): () => void
    command(command: AvatarCommand): void
  }

  /** A JPEG of the screen (raw base64), for the chat to attach. */
  screenGrab(): Promise<{ data: string; mime_type: string; width: number; height: number } | null>

  /** Global hotkeys (push-to-talk + quick-chat). */
  hotkeys: {
    getPushToTalk(): Promise<string | null>
    setPushToTalk(accelerator: string): Promise<boolean>
    /** Subscribe to global push-to-talk presses; returns a disposer. */
    onPushToTalk(cb: () => void): () => void
    /** Global quick-chat accelerator (summons the floating input bar). */
    getQuickChat(): Promise<string | null>
    setQuickChat(accelerator: string): Promise<boolean>
    /** Suspend / restore all global shortcuts while a settings field records a
     *  new combo (so a registered key isn't intercepted during capture). */
    pause(): void
    resume(): void
  }

  /** Quick-chat input bar (the 'quickchat' window) → relay to the VTuber chat. */
  quickChat: {
    /** Send the typed text (+ pasted images as data URLs) to the current
     *  VTuber; main closes the bar on ok. */
    submit(payload: {
      text: string
      images?: Array<{ name: string; type: string; dataUrl: string }>
    }): Promise<{ ok: boolean; error?: string }>
    /** Dismiss the bar (Esc / blur). */
    close(): void
    /** Content height changed (multi-line text / thumbnails) — main grows the
     *  window to fit so the page never scrolls. */
    resize(contentHeight: number): void
    /** Fired each time the bar is summoned (paint the card, reset + focus). */
    onOpened(cb: () => void): () => void
    /** Fired when main dismisses the bar (blur/submit/Esc) — stop painting. */
    onDismissed(cb: () => void): () => void
  }

  /** Inbound messaging from the connector → the /connector chat page reuses its
   *  own send path when a quick-chat message arrives. */
  messaging: {
    /** Subscribe to quick-chat relays; returns a disposer. Payload is the
     *  structured `{ text, images? }` form (legacy bars sent a bare string —
     *  consumers should accept both). */
    onQuickSend(
      cb: (
        payload:
          | string
          | { text: string; images?: Array<{ name: string; type: string; dataUrl: string }> },
      ) => void,
    ): () => void
  }

  /** GitHub Releases auto-update controls. */
  updater: {
    /** Is auto-update enabled? (default true) */
    getEnabled(): Promise<boolean>
    /** Toggle auto-update; when re-enabled, an immediate check runs. */
    setEnabled(enabled: boolean): Promise<boolean>
    /** Manually check now (downloads + prompts if an update exists). */
    check(): void
  }

  /** Launch-on-login (start when the user signs into the OS). `set` returns
   *  the EFFECTIVE state — enabling can be refused (e.g. AppImage running
   *  from an ephemeral /tmp mount), in which case it returns false. */
  autostart: {
    get(): Promise<boolean>
    set(enabled: boolean): Promise<boolean>
  }

  /** Phase 4 — desktop awareness (read-only). */
  capture: {
    listSources(): Promise<Array<{ id: string; name: string; display_id: string }>>
    /** The primary display's id (string) — so desktop_screenshot captures the
     *  PRIMARY, whose pixel space matches nut.js mouse coordinates. */
    primaryDisplayId(): Promise<string>
    /** Report the last full-res screenshot's pixel size so main can map the
     *  model's image-space click coords back to screen coords. */
    noteCaptureDims(w: number, h: number): void
  }

  /** Phase 6 — guarded actuation. Each call is gated by the master switch + a
   *  native confirm in main; returns {ok, result?, denied?, error?}. */
  actuate: {
    openApp(target: string): Promise<ActuationResult>
    clipboardWrite(text: string): Promise<ActuationResult>
    type(text: string): Promise<ActuationResult>
    key(keys: string): Promise<ActuationResult>
    click(x: number, y: number, button?: string): Promise<ActuationResult>
    /** Scroll the wheel: positive = down, negative = up (wheel steps). */
    scroll(amount: number): Promise<ActuationResult>
  }

  /** Phase 7 — structured browser control (CDP on a dedicated Chrome/Edge
   *  automation instance). Ops: tabs|open|snapshot|act|read|screenshot|eval|close.
   *  Read ops are toggle-gated; act ops prompt-once like other actuation. */
  browser: {
    call(op: string, args: Record<string, unknown>): Promise<GatedCallResult>
  }

  /** Phase 7 — structured Windows app control (UIA) + live Office documents
   *  (COM), hosted in a persistent PowerShell STA process. Windows-only.
   *  Ops: windows|win_snapshot|el_act|win_focus|win_read|office_status|office_read|office_act. */
  winauto?: {
    call(op: string, args: Record<string, unknown>): Promise<GatedCallResult>
  }

  /** Local MCP proxy (Phase 3) — hosts MCP clients to the user's local servers. */
  mcp: {
    /** Configured servers (from config; no connection). */
    listServers(): Promise<MCPServerConfig[]>
    /** Connect all enabled servers + return their tool catalogs. */
    advertise(): Promise<MCPServerAdvert[]>
    /** Call a tool on a server. Returns the raw MCP CallToolResult (or error). */
    callTool(server: string, tool: string, args: unknown): Promise<{ ok: boolean; result?: unknown; error?: string }>
    /** One-shot connect → list tools → disconnect (settings "테스트"). */
    testServer(cfg: MCPServerConfig): Promise<{ ok: boolean; tools?: MCPToolSchema[]; error?: string }>
    /** Add/replace a server (persisted). Returns the new list. */
    addServer(cfg: MCPServerConfig): Promise<MCPServerConfig[]>
    /** Edit a server (handles rename via originalName). Returns the new list. */
    updateServer(originalName: string, cfg: MCPServerConfig): Promise<MCPServerConfig[]>
    /** Remove a server by name (persisted). Returns the new list. */
    removeServer(name: string): Promise<MCPServerConfig[]>
    /** Local MCP master switch (default on). */
    getEnabled(): Promise<boolean>
    setEnabled(enabled: boolean): Promise<boolean>
    /** Live status snapshot: connected/error/tool counts per server. */
    status(): Promise<MCPServerStatus[]>
    /** Deduped status push — fires on connect/disconnect/tool-list/config
     *  changes. The overlay bridge re-advertises the catalog on this. */
    onStatus(cb: (status: MCPServerStatus[]) => void): () => void
  }

  /** Workspace sync — Drive-style replication between a local folder and an
   *  agent's server workspace (settings → Workspace tab). */
  sync: {
    list(): Promise<{
      pairs: SyncPairConfig[]
      /** Drive links (config of record): one row per binding. */
      links: Array<{ name: string; localPath: string; paused?: boolean }>
      statuses: SyncPairStatus[]
    }>
    pickFolder(): Promise<string | null>
    /** Link a folder to the DRIVE (no agent — every connected agent
     *  shares it as workspace/<name>/). */
    addPair(pair: { localPath: string }): Promise<{ ok?: boolean; name?: string; error?: string; conflictWith?: string }>
    /** Unlink by link NAME (the whole binding, all agents). */
    removePair(name: string): Promise<{ ok: boolean }>
    /** Pause/resume the whole link across all agents. */
    setPaused(name: string, paused: boolean): Promise<{ ok: boolean }>
    syncNow(id: string): Promise<void>
    /** Answer the mass-delete safety valve. Refusing pauses the pair. */
    confirmMassDelete(id: string, accept: boolean): Promise<void>
    openFolder(id: string): Promise<void>
    /** Sessions on the server for the pairing picker. */
    listAgents(): Promise<Array<{ id: string; name: string }>>
    onStatus(cb: (statuses: SyncPairStatus[]) => void): () => void
  }

  /** Geny Drive — one local root, one folder per connected agent. The user
   *  chooses WHICH agents live on the drive (and where the root is); every
   *  folder placement is derived. */
  drive: {
    get(): Promise<{
      root: string
      agents: Record<string, { enabled: boolean; folder: string; label?: string }>
      statuses: SyncPairStatus[]
      /** Install-time (or in-app) "use Geny Cloud" choice; default true. */
      cloudOptIn: boolean
      /** Probed per-OS readiness — mirror always works; streaming needs FUSE
       *  (Linux) / Windows 10 1709+ (CfAPI) / mount_webdav (macOS). */
      capabilities: {
        mirror: true
        streaming: boolean
        mechanism: 'fuse' | 'cfapi' | 'webdav' | 'none'
        missing: string
        code: string
      }
    }>
    /** Native virtual drive (Linux FUSE sidecar): mount/unmount + status. */
    nativeMount(enable: boolean): Promise<{ mounted?: boolean; mountpoint?: string; error?: string }>
    nativeStatus(): Promise<{ running: boolean; mountpoint: string; supported: boolean }>
    /** Master switch: off parks the whole drive (membership is remembered). */
    setCloud(enabled: boolean): Promise<{ cloudOptIn: boolean }>
    /** Per-agent used/quota bytes in one round trip. */
    usage(): Promise<Record<string, { used: number | null; quota: number }>>
    /** Native folder picker for the drive root (returns null on cancel). */
    pickRoot(): Promise<string | null>
    /** Relocate the drive: MOVES every managed folder, keeps sync indexes. */
    setRoot(root: string): Promise<{ ok: boolean; root?: string; moved?: number; error?: string }>
  }
}

export interface SyncPairConfig {
  id: string
  sessionId: string
  sessionLabel?: string
  localPath: string
  paused?: boolean
}

export interface SyncPairStatus {
  id: string
  sessionId: string
  sessionLabel?: string
  localPath: string
  state: 'idle' | 'syncing' | 'paused' | 'offline' | 'error' | 'awaiting_confirmation'
  connected: boolean
  lastSyncAt: number | null
  lastError: string | null
  counts: { downloaded: number; uploaded: number; conflicts: number; skippedLarge: number }
  pendingMassDelete: { count: number; total: number } | null
}

export interface MCPServerStatus {
  name: string
  transport: 'stdio' | 'http'
  enabled: boolean
  connected: boolean
  error?: string
  toolCount: number
  toolNames: string[]
}

export interface ActuationResult {
  ok: boolean
  result?: string
  denied?: boolean
  error?: string
}

/** Result of a gated structured-control call (browser/winauto) — same envelope
 *  as ActuationResult but the result may be any JSON value. */
export interface GatedCallResult {
  ok: boolean
  result?: unknown
  denied?: boolean
  error?: string
}

const _wk = new URLSearchParams(location.search).get('window')

const api: ConnectorBridge = {
  // Unknown values fall back to 'overlay', so a route added in main but
  // NOT listed here silently renders the avatar placeholder instead —
  // which is exactly what happened to the chip window (a full placeholder
  // squeezed into 104x40). Keep this list in step with loadRoute().
  windowKind:
    _wk === 'settings' ? 'settings'
    : _wk === 'control' ? 'control'
    : _wk === 'quickchat' ? 'quickchat'
    : _wk === 'chip' ? 'chip'
    : 'overlay',
  appVersion: () => ipcRenderer.invoke('app:version'),
  debug: {
    log: (line) => ipcRenderer.send('debug:log', line),
    get: () => ipcRenderer.invoke('debug:get'),
  },
  appDefaultLang: () => ipcRenderer.invoke('i18n:default-lang'),
  system: {
    get: () => ipcRenderer.invoke('system:stats'),
    onChange: (cb) => {
      const h = (_e: unknown, stats: SystemStats) => cb(stats)
      ipcRenderer.on('system:stats', h)
      return () => ipcRenderer.removeListener('system:stats', h)
    },
  },
  serverConfig: {
    get: () => ipcRenderer.invoke('config:get'),
    set: (patch) => ipcRenderer.invoke('config:set', patch),
    onChange: (cb) => {
      const h = (_e: unknown, cfg: ConnectorConfig) => cb(cfg)
      ipcRenderer.on('config:changed', h)
      return () => ipcRenderer.removeListener('config:changed', h)
    },
  },
  secureStore: {
    get: (key) => ipcRenderer.invoke('secure:get', key),
    set: (key, value) => ipcRenderer.invoke('secure:set', key, value),
    delete: (key) => ipcRenderer.invoke('secure:delete', key),
  },
  windowControl: {
    setClickThrough: (ignore) => ipcRenderer.send('overlay:set-ignore-mouse', ignore),
    /** Window-relative rects that must stay clickable while click-through
     *  is on. Linux has no event forwarding, so main hit-tests the cursor
     *  against these — without them the lock would swallow its own bar. */
    setInteractiveRects: (rects) => ipcRenderer.send('overlay:set-interactive-rects', rects),
    chipSize: (w, h) => ipcRenderer.send('overlay:chip-size', w, h),
    setLocked: (locked) => ipcRenderer.send('overlay:set-locked', locked),
    onSetLocked: (cb) => {
      const h = (_e: unknown, v: boolean): void => cb(v)
      ipcRenderer.on('overlay:locked', h)
      return () => ipcRenderer.removeListener('overlay:locked', h)
    },
    requestChipInset: () => ipcRenderer.send('overlay:request-chip-inset'),
    onChipInset: (cb) => {
      const h = (_e: unknown, v: number): void => cb(v)
      ipcRenderer.on('overlay:chip-inset', h)
      return () => ipcRenderer.removeListener('overlay:chip-inset', h)
    },
    moveBy: (dx, dy) => ipcRenderer.send('overlay:move-by', dx, dy),
    moveEnd: () => ipcRenderer.send('overlay:move-end'),
    resizeOverlayBy: (edge, dx, dy) => ipcRenderer.send('overlay:resize-by', edge, dx, dy),
    toggleControl: () => ipcRenderer.send('control:toggle'),
    openControl: () => ipcRenderer.send('control:open'),
    refresh: () => ipcRenderer.send('app:refresh'),
    setOverlaySession: (sessionId) => ipcRenderer.send('overlay:set-session', sessionId),
    openSettings: () => ipcRenderer.send('settings:open'),
    restart: () => ipcRenderer.send('app:restart'),
    openExternal: (url) => ipcRenderer.send('app:open-external', url),
    reloadPanel: () => ipcRenderer.send('app:reload-control'),
    resetPositions: () => ipcRenderer.send('windows:reset-positions'),
    onResetView: (cb) => {
      const h = () => cb()
      ipcRenderer.on('overlay:reset-view', h)
      return () => ipcRenderer.removeListener('overlay:reset-view', h)
    },
  },
  updater: {
    getEnabled: () => ipcRenderer.invoke('updater:get-enabled'),
    setEnabled: (enabled) => ipcRenderer.invoke('updater:set-enabled', enabled),
    check: () => ipcRenderer.send('updater:check'),
  },
  autostart: {
    get: () => ipcRenderer.invoke('autostart:get'),
    set: (enabled) => ipcRenderer.invoke('autostart:set', enabled),
  },
  capture: {
    listSources: () => ipcRenderer.invoke('capture:list-sources'),
    primaryDisplayId: () => ipcRenderer.invoke('capture:primary-display-id'),
    noteCaptureDims: (w, h) => ipcRenderer.send('capture:note-dims', w, h),
  },
  actuate: {
    openApp: (target) => ipcRenderer.invoke('actuate:open-app', target),
    clipboardWrite: (text) => ipcRenderer.invoke('actuate:clipboard-write', text),
    type: (text) => ipcRenderer.invoke('actuate:type', text),
    key: (keys) => ipcRenderer.invoke('actuate:key', keys),
    click: (x, y, button) => ipcRenderer.invoke('actuate:click', x, y, button),
    scroll: (amount) => ipcRenderer.invoke('actuate:scroll', amount),
  },
  browser: {
    call: (op, args) => ipcRenderer.invoke('browser:call', op, args),
  },
  // Windows-only UIA/COM control: expose the surface ONLY on win32 — the
  // server advertises app_*/office_* tools purely on this key's presence,
  // and a Linux/mac connector must not promise tools that can only error.
  ...(process.platform === 'win32'
    ? {
        winauto: {
          call: (op: string, args?: unknown) => ipcRenderer.invoke('winauto:call', op, args),
        },
      }
    : {}),
  mcp: {
    listServers: () => ipcRenderer.invoke('mcp:list-servers'),
    advertise: () => ipcRenderer.invoke('mcp:advertise'),
    callTool: (server, tool, args) => ipcRenderer.invoke('mcp:call-tool', server, tool, args),
    testServer: (cfg) => ipcRenderer.invoke('mcp:test-server', cfg),
    addServer: (cfg) => ipcRenderer.invoke('mcp:add-server', cfg),
    updateServer: (originalName, cfg) => ipcRenderer.invoke('mcp:update-server', originalName, cfg),
    removeServer: (name) => ipcRenderer.invoke('mcp:remove-server', name),
    getEnabled: () => ipcRenderer.invoke('mcp:get-enabled'),
    setEnabled: (enabled) => ipcRenderer.invoke('mcp:set-enabled', enabled),
    status: () => ipcRenderer.invoke('mcp:status'),
    onStatus: (cb) => {
      const h = (_e: unknown, status: MCPServerStatus[]) => cb(status)
      ipcRenderer.on('mcp:status-event', h)
      return () => ipcRenderer.removeListener('mcp:status-event', h)
    },
  },
  sync: {
    list: () => ipcRenderer.invoke('sync:list'),
    pickFolder: () => ipcRenderer.invoke('sync:pick-folder'),
    addPair: (pair) => ipcRenderer.invoke('sync:add-pair', pair),
    removePair: (id) => ipcRenderer.invoke('sync:remove-pair', id),
    setPaused: (id, paused) => ipcRenderer.invoke('sync:set-paused', id, paused),
    syncNow: (id) => ipcRenderer.invoke('sync:sync-now', id),
    confirmMassDelete: (id, accept) => ipcRenderer.invoke('sync:confirm-mass-delete', id, accept),
    openFolder: (id) => ipcRenderer.invoke('sync:open-folder', id),
    listAgents: () => ipcRenderer.invoke('sync:list-agents'),
    onStatus: (cb) => {
      const h = (_e: unknown, statuses: SyncPairStatus[]) => cb(statuses)
      ipcRenderer.on('sync:status-event', h)
      return () => ipcRenderer.removeListener('sync:status-event', h)
    },
  },
  drive: {
    get: () => ipcRenderer.invoke('drive:get'),
    nativeMount: (enable) => ipcRenderer.invoke('drive:native-mount', enable),
    nativeStatus: () => ipcRenderer.invoke('drive:native-status'),
    setCloud: (enabled) => ipcRenderer.invoke('drive:set-cloud', enabled),
    usage: () => ipcRenderer.invoke('drive:usage'),
    pickRoot: () => ipcRenderer.invoke('drive:pick-root'),
    setRoot: (root) => ipcRenderer.invoke('drive:set-root', root),
  },
  avatar: {
    publish: (state) => ipcRenderer.send('avatar:publish', state),
    onCommand: (cb) => {
      const h = (_e: unknown, command: AvatarCommand) => cb(command)
      ipcRenderer.on('avatar:command', h)
      return () => ipcRenderer.removeListener('avatar:command', h)
    },
    getState: () => ipcRenderer.invoke('avatar:get-state'),
    onState: (cb) => {
      const h = (_e: unknown, state: AvatarState | null) => cb(state)
      ipcRenderer.on('avatar:state', h)
      return () => ipcRenderer.removeListener('avatar:state', h)
    },
    command: (command) => ipcRenderer.send('avatar:command', command),
  },
  screenGrab: () => ipcRenderer.invoke('screen:grab'),
  hotkeys: {
    getPushToTalk: () => ipcRenderer.invoke('hotkey:get-ptt'),
    setPushToTalk: (acc) => ipcRenderer.invoke('hotkey:set-ptt', acc),
    onPushToTalk: (cb) => {
      const h = () => cb()
      ipcRenderer.on('connector:ptt-toggle', h)
      return () => ipcRenderer.removeListener('connector:ptt-toggle', h)
    },
    getQuickChat: () => ipcRenderer.invoke('hotkey:get-quickchat'),
    setQuickChat: (acc) => ipcRenderer.invoke('hotkey:set-quickchat', acc),
    pause: () => ipcRenderer.send('hotkey:pause'),
    resume: () => ipcRenderer.send('hotkey:resume'),
  },
  quickChat: {
    submit: (payload) => ipcRenderer.invoke('quickchat:submit', payload),
    close: () => ipcRenderer.send('quickchat:close'),
    resize: (h) => ipcRenderer.send('quickchat:resize', h),
    onOpened: (cb) => {
      const h = () => cb()
      ipcRenderer.on('quickchat:opened', h)
      return () => ipcRenderer.removeListener('quickchat:opened', h)
    },
    onDismissed: (cb) => {
      const h = () => cb()
      ipcRenderer.on('quickchat:dismissed', h)
      return () => ipcRenderer.removeListener('quickchat:dismissed', h)
    },
  },
  messaging: {
    onQuickSend: (cb) => {
      const h = (
        _e: unknown,
        payload:
          | string
          | { text: string; images?: Array<{ name: string; type: string; dataUrl: string }> },
      ) => cb(payload)
      ipcRenderer.on('connector:quick-send', h)
      return () => ipcRenderer.removeListener('connector:quick-send', h)
    },
  },
}

contextBridge.exposeInMainWorld('connector', api)
