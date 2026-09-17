/**
 * The turn stream, made to survive a phone.
 *
 * A turn belongs to the SESSION, not to this socket. The server starts it in
 * the background and keeps going whether or not anyone is listening — so on a
 * phone, where the socket dies every time the screen locks, the connection is
 * not the conversation. Losing it is not losing the turn.
 *
 * Everything here follows from that one fact:
 *
 * · A drop is not a failure. The UI keeps showing the turn as running, because
 *   it IS running. Painting an error there teaches the user to distrust a
 *   screen that was right.
 * · On every (re)connect the client asks `reconnect`. The server replays the
 *   turn from its start — the holder's cursor is fixed at execution start —
 *   so a phone that was in a tunnel for a minute comes back with the whole
 *   answer, not the tail of it.
 * · A socket can die without saying so. Carrier NAT drops the flow, the OS
 *   suspends the app, a proxy times out — and the socket object stays
 *   "open" forever, with a spinner above it. So: heartbeats while a turn runs,
 *   `ping` while idle, and a watchdog that forces a reconnect when neither
 *   has been heard.
 * · Waking up should not wait. Backoff is for a server that is down; a phone
 *   returning to the foreground with the network back is a different event,
 *   and `resume()` skips the wait.
 *
 * Deliberately free of React and of `expo-*` imports so the whole thing runs
 * under `node:test` with a fake socket.
 */

export type ConnState =
  | 'connecting'
  | 'connected'
  /** The socket is gone and the turn (if any) is still running on the server. */
  | 'reconnecting'
  /** Out of attempts. The turn may STILL be running — this is about us. */
  | 'offline'
  | 'unauthorized'
  | 'closed';

export interface LogEntry {
  timestamp?: string;
  level?: string;
  message?: string;
  metadata?: Record<string, unknown> | string;
}

export interface ExecEvents {
  onState?(state: ConnState): void;
  /** A turn is running on the server, or is not. Reported on every connect. */
  onRunning?(running: boolean): void;
  onLog?(entry: LogEntry): void;
  onResult?(result: Record<string, unknown>): void;
  /** The turn ended. */
  onDone?(): void;
  onError?(message: string): void;
}

export interface ExecWsOptions extends ExecEvents {
  /** `wss://host` — no trailing slash needed. */
  wsBase: string;
  sessionId: string;
  token: string | null;
  /** Injected in tests; defaults to the platform WebSocket. */
  wsFactory?: (url: string, protocols?: string[]) => WebSocket;
  /** Injected in tests. */
  setTimeoutFn?: (fn: () => void, ms: number) => unknown;
  clearTimeoutFn?: (handle: unknown) => void;
  now?: () => number;
  log?(line: string): void;
}

export const WS_AUTH_SUBPROTOCOL = 'geny-auth';
/** The server's "your token is no good" close code. */
export const WS_UNAUTHORIZED_CODE = 4401;

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 20_000;
const RECONNECT_MAX_ATTEMPTS = 12;
/** Idle keepalive. Comfortably under the ~60s a carrier NAT usually allows. */
const PING_INTERVAL_MS = 25_000;
/**
 * Nothing heard for this long → the socket is dead even if it says otherwise.
 * Longer than the server's 15s heartbeat and our own ping, with room for a
 * slow mobile round trip.
 */
const SILENCE_LIMIT_MS = 70_000;

export interface ExecWsHandle {
  /** Start a turn. Rejects only if the socket is not usable right now. */
  execute(prompt: string): void;
  stop(): void;
  /** The app came back to the foreground, or the network returned. */
  resume(): void;
  close(): void;
  state(): ConnState;
  running(): boolean;
}

export function connectExecWs(opts: ExecWsOptions): ExecWsHandle {
  const factory = opts.wsFactory ?? ((url, protocols) =>
    (protocols ? new WebSocket(url, protocols) : new WebSocket(url)));
  const setTimer = opts.setTimeoutFn ?? ((fn, ms) => setTimeout(fn, ms));
  const clearTimer = opts.clearTimeoutFn ?? ((h) => clearTimeout(h as ReturnType<typeof setTimeout>));
  const now = opts.now ?? (() => Date.now());
  const log = opts.log ?? (() => undefined);

  const url = `${opts.wsBase.replace(/\/+$/, '')}/ws/execute/${encodeURIComponent(opts.sessionId)}`;

  let ws: WebSocket | null = null;
  let state: ConnState = 'connecting';
  let running = false;
  let closedByUser = false;
  let attempts = 0;
  let reconnectTimer: unknown = null;
  let pingTimer: unknown = null;
  let lastHeard = now();
  /** Sent the moment the socket opens, if the user typed while it was down. */
  let queuedPrompt: string | null = null;

  const setState = (next: ConnState): void => {
    if (state === next) return;
    state = next;
    opts.onState?.(next);
  };

  const setRunning = (next: boolean): void => {
    if (running === next) return;
    running = next;
    opts.onRunning?.(next);
  };

  const clearTimers = (): void => {
    if (reconnectTimer !== null) { clearTimer(reconnectTimer); reconnectTimer = null; }
    if (pingTimer !== null) { clearTimer(pingTimer); pingTimer = null; }
  };

  const send = (payload: Record<string, unknown>): boolean => {
    if (!ws || ws.readyState !== 1 /* OPEN */) return false;
    try {
      ws.send(JSON.stringify(payload));
      return true;
    } catch {
      return false;
    }
  };

  /** One timer does both jobs: keep the flow alive, and notice when it died. */
  const scheduleHousekeeping = (): void => {
    if (pingTimer !== null) clearTimer(pingTimer);
    pingTimer = setTimer(() => {
      if (closedByUser) return;
      if (now() - lastHeard > SILENCE_LIMIT_MS) {
        // The socket believes it is open. Nothing has arrived for over a
        // minute, through a heartbeat AND a ping. It is not open.
        log('silence limit passed — forcing a reconnect');
        dropAndRetry('silent');
        return;
      }
      send({ type: 'ping' });
      scheduleHousekeeping();
    }, PING_INTERVAL_MS);
  };

  const scheduleReconnect = (immediate = false): void => {
    if (closedByUser || reconnectTimer !== null) return;
    if (attempts >= RECONNECT_MAX_ATTEMPTS) {
      // Out of attempts is about US, not about the turn: it may well still be
      // running, and `resume()` will find it.
      setState('offline');
      return;
    }
    const delay = immediate
      ? 0
      : Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** attempts);
    attempts += 1;
    setState('reconnecting');
    reconnectTimer = setTimer(() => {
      reconnectTimer = null;
      open();
    }, delay);
  };

  const dropAndRetry = (why: string): void => {
    log(`connection lost (${why})`);
    if (ws) {
      try { ws.onclose = null; ws.onerror = null; ws.onmessage = null; ws.close(); } catch { /* already gone */ }
      ws = null;
    }
    clearTimers();
    scheduleReconnect();
  };

  const handle = (raw: string): void => {
    lastHeard = now();
    let event: { type?: string; data?: Record<string, unknown> };
    try {
      event = JSON.parse(raw);
    } catch {
      return;
    }
    const data = event.data ?? {};
    switch (event.type) {
      case 'log':
        setRunning(true);
        opts.onLog?.(data as LogEntry);
        return;
      case 'status': {
        const status = String(data.status ?? '');
        if (status === 'running') setRunning(true);
        if (status === 'idle' || status === 'stopped' || status === 'completed') setRunning(false);
        return;
      }
      case 'result':
        opts.onResult?.(data);
        return;
      case 'done':
        setRunning(false);
        opts.onDone?.();
        return;
      case 'pong':
        setRunning(Boolean(data.running));
        return;
      case 'heartbeat':
        setRunning(true);
        return;
      case 'error':
        opts.onError?.(String(data.error ?? 'unknown error'));
        return;
      default:
        return;
    }
  };

  const open = (): void => {
    if (closedByUser) return;
    setState(attempts > 0 ? 'reconnecting' : 'connecting');
    let socket: WebSocket;
    try {
      socket = opts.token
        ? factory(url, [WS_AUTH_SUBPROTOCOL, opts.token])
        : factory(url);
    } catch (err) {
      log(`could not create socket: ${String(err)}`);
      scheduleReconnect();
      return;
    }
    ws = socket;

    socket.onopen = (): void => {
      attempts = 0;
      lastHeard = now();
      setState('connected');
      // Always ask. The answer is either "here is the turn you missed, from
      // the beginning" or "nothing is running" — and not asking is how a
      // phone ends up showing a spinner over a conversation that finished
      // while it was asleep.
      send({ type: 'reconnect' });
      if (queuedPrompt !== null) {
        const prompt = queuedPrompt;
        queuedPrompt = null;
        send({ type: 'execute', prompt });
      }
      scheduleHousekeeping();
    };

    socket.onmessage = (event: MessageEvent): void => {
      handle(typeof event.data === 'string' ? event.data : String(event.data));
    };

    socket.onerror = (): void => {
      // `onclose` always follows; reconnecting from both would double the rate.
      log('socket error');
    };

    socket.onclose = (event: CloseEvent): void => {
      ws = null;
      clearTimers();
      if (closedByUser) { setState('closed'); return; }
      if (event?.code === WS_UNAUTHORIZED_CODE) {
        // Retrying with the same dead token forever would hammer the server
        // and never recover. The app has to sign in again.
        setState('unauthorized');
        opts.onError?.('로그인이 만료됐습니다 — 설정에서 다시 로그인하세요');
        return;
      }
      scheduleReconnect();
    };
  };

  open();

  return {
    execute(prompt: string): void {
      const text = prompt.trim();
      if (!text) return;
      if (!send({ type: 'execute', prompt: text })) {
        // Hold it rather than refuse it: the socket is usually back within a
        // second, and asking the user to retype into a reconnecting app is
        // the kind of small insult that makes a phone app feel broken.
        queuedPrompt = text;
        scheduleReconnect(true);
      }
    },
    stop(): void {
      send({ type: 'stop' });
    },
    resume(): void {
      if (closedByUser) return;
      if (state === 'connected') {
        // Looks fine — but a socket that slept through a suspend looks fine
        // too. Make it prove it.
        lastHeard = now();
        send({ type: 'ping' });
        return;
      }
      // Coming back to the foreground is not "the server is down": drop the
      // backoff and go now.
      attempts = 0;
      if (reconnectTimer !== null) { clearTimer(reconnectTimer); reconnectTimer = null; }
      open();
    },
    close(): void {
      closedByUser = true;
      clearTimers();
      if (ws) {
        try { ws.close(); } catch { /* already gone */ }
        ws = null;
      }
      setState('closed');
    },
    state: () => state,
    running: () => running,
  };
}
