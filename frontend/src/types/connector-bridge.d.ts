/**
 * Ambient type for the desktop connector's preload bridge.
 *
 * When a page is loaded inside the Geny desktop connector (Electron), the
 * preload exposes `window.connector`. In a normal browser it is undefined, so
 * every access is optional-chained. This declaration only covers what the web
 * routes (e.g. /connector) call; the full surface lives in desktop/src/preload.
 */
interface OverlayTuning {
  ttsVolume?: number
  sttSensitivity?: number
  sttSilenceMs?: number
  sttEchoCancellation?: boolean
  sttNoiseSuppression?: boolean
  sttAutoGain?: boolean
  screenIntervalMs?: number
  screenSourceId?: string | null
}
interface ConnectorConfig {
  serverUrl: string
  theme?: 'system' | 'dark' | 'light'
  overlayTuning?: OverlayTuning
}

interface ConnectorAvatarState {
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
type ConnectorAvatarCommand =
  | { type: 'set'; key: 'tts' | 'stt' | 'realtime' | 'captions' | 'screen' | 'ptt'; value: boolean }
  | { type: 'speak'; text: string }
  | { type: 'hush' }

declare global {
  interface Window {
    connector?: {
      serverConfig: {
        get(): Promise<ConnectorConfig>
        set(patch: Partial<ConnectorConfig>): Promise<ConnectorConfig>
        onChange(cb: (cfg: ConnectorConfig) => void): () => void
      }
      /** OS keychain — used to drop the stale JWT on token expiry. */
      secureStore?: {
        get(key: string): Promise<string | null>
        set(key: string, value: string): Promise<boolean>
        delete(key: string): Promise<boolean>
      }
      windowControl: {
        setOverlaySession(sessionId: string): void
        refresh(): void
        openSettings(): void
        toggleControl(): void
        openControl(): void
        setClickThrough(ignore: boolean): void
        /** Rects (window-relative CSS px) that must stay clickable while
         *  click-through is on. Optional: older connectors lack it, and
         *  the page must not break on them. */
        setInteractiveRects?(rects: Array<{ x: number; y: number; w: number; h: number }>): void
        /** Chip window: report its rendered size so the connector can size
         *  and place the window around it. */
        chipSize?(w: number, h: number): void
        /** Set the lock from EITHER window; main owns the state and applies
         *  it to the avatar window, then relays it to the avatar page. */
        setLocked?(locked: boolean): void
        onSetLocked?(cb: (locked: boolean) => void): () => void
        /** Avatar page (connector ≥0.19.8): how many pixels of this
         *  window's BOTTOM the chip window currently covers. The chip is a
         *  separate always-on-top window, so the page cannot see it —
         *  without this the subtitle and the caption are drawn underneath
         *  its buttons. 0 while the chip is hidden. Optional: older
         *  connectors simply never send it, and the inset stays 0. */
        requestChipInset?(): void
        onChipInset?(cb: (px: number) => void): () => void
        moveBy(dx: number, dy: number): void
        /** Optional (connector ≥0.17.1): end-of-drag signal. */
        moveEnd?(): void
        resizeOverlayBy?(edge: string, dx: number, dy: number): void
        restart(): void
        openExternal(url: string): void
        resetPositions?(): void
        onResetView?(cb: () => void): () => void
      }
      /** The avatar's switches, from any window (connector ≥0.30). The avatar
       *  page publishes its state and obeys commands; the chat window and the
       *  locked chip read and ask. Optional: older connectors lack it. */
      avatar?: {
        publish(state: ConnectorAvatarState): void
        onCommand(cb: (command: ConnectorAvatarCommand) => void): () => void
        getState(): Promise<ConnectorAvatarState | null>
        onState(cb: (state: ConnectorAvatarState | null) => void): () => void
        command(command: ConnectorAvatarCommand): void
      }
      hotkeys?: {
        getPushToTalk(): Promise<string | null>
        setPushToTalk(accelerator: string): Promise<boolean>
        /** Subscribe to global push-to-talk presses; returns a disposer. */
        onPushToTalk(cb: () => void): () => void
        getQuickChat?(): Promise<string | null>
        setQuickChat?(accelerator: string): Promise<boolean>
      }
      /** Quick-chat relay: the floating bar's message arrives here so the
       *  /connector chat can reuse its own send path. */
      messaging?: {
        onQuickSend(
          cb: (
            payload:
              | string
              | { text: string; images?: Array<{ name: string; type: string; dataUrl: string }> },
          ) => void,
        ): () => void
      }
      capture: {
        listSources(): Promise<Array<{ id: string; name: string; display_id: string }>>
        primaryDisplayId?(): Promise<string>
        noteCaptureDims?(w: number, h: number): void
      }
      actuate: {
        openApp(target: string): Promise<{ ok: boolean; result?: string; denied?: boolean; error?: string }>
        clipboardWrite(text: string): Promise<{ ok: boolean; result?: string; denied?: boolean; error?: string }>
        type(text: string): Promise<{ ok: boolean; result?: string; denied?: boolean; error?: string }>
        key(keys: string): Promise<{ ok: boolean; result?: string; denied?: boolean; error?: string }>
        click(x: number, y: number, button?: string): Promise<{ ok: boolean; result?: string; denied?: boolean; error?: string }>
        scroll(amount: number): Promise<{ ok: boolean; result?: string; denied?: boolean; error?: string }>
      }
      /** Structured browser control (Phase 7, connector ≥0.17) — CDP on a
       *  dedicated Chrome/Edge automation instance. */
      browser?: {
        call(op: string, args: Record<string, unknown>): Promise<{ ok: boolean; result?: unknown; denied?: boolean; error?: string }>
      }
      /** Structured Windows app + Office control (Phase 7, connector ≥0.17). */
      winauto?: {
        call(op: string, args: Record<string, unknown>): Promise<{ ok: boolean; result?: unknown; denied?: boolean; error?: string }>
      }
      /** Local MCP proxy (Phase 3) — present only in the desktop connector. */
      mcp?: {
        advertise(): Promise<Array<{ name: string; connected: boolean; error?: string; tools: Array<{ name: string; description?: string; inputSchema?: Record<string, unknown> }> }>>
        callTool(server: string, tool: string, args: unknown): Promise<{ ok: boolean; result?: unknown; error?: string }>
        /** Status push (newer connectors): fired on server connect/disconnect
         *  or tool-list changes — the bridge re-advertises the catalog. */
        onStatus?(cb: () => void): () => void
      }
    }
  }
}

export {}
