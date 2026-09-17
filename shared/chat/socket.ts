/**
 * A socket that survives a phone, a laptop lid, and a carrier NAT.
 *
 * Two of Geny's streams need exactly the same discipline — the room's
 * conversation and a session's execute log — and the discipline is the hard
 * part, not the protocol. It is written once here so the two cannot drift
 * into having different ideas about what a dropped connection means.
 *
 * What it is:
 *
 * · A drop is not a failure. Whatever is happening on the server keeps
 *   happening. The UI is told the connection state, never that the work
 *   stopped, because that would be a claim we cannot make.
 * · Every (re)connect sends a GREETING that asks to be caught up — with a
 *   cursor evaluated at that moment, so it asks from where this client
 *   actually got to and not from where it started.
 * · A socket can die without saying so: carrier NAT drops the flow, the OS
 *   suspends the app, a proxy times out, and the socket object stays "open"
 *   forever. So: ping on a timer, and a watchdog that forces a reconnect
 *   when nothing has been heard for longer than any legitimate silence.
 * · Waking up is not the same event as a server being down. `resume()` skips
 *   the backoff, because a user who just unlocked their phone should not wait
 *   out a timer that was counting for an outage.
 * · 4401 means the token is dead. Retrying it forever hammers the server and
 *   never recovers, so that one stops.
 *
 * Free of React and of any platform import, so the whole thing runs under
 * `node:test` with a fake socket.
 */

export type ConnState =
  | 'connecting'
  | 'connected'
  /** The socket is gone; whatever was happening on the server still is. */
  | 'reconnecting'
  /** Out of attempts. This is about us, not about the work. */
  | 'offline'
  | 'unauthorized'
  | 'closed';

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

export interface SocketOptions {
  /** `wss://host/ws/…` — complete, including the path. */
  url: string;
  token: string | null;
  /**
   * Sent the moment the socket opens. Evaluated per connect, so a cursor in
   * it is the one this client has actually reached.
   */
  greeting?(): Record<string, unknown> | null;
  /** One parsed frame. `data` is `{}` when the frame carried none. */
  onFrame(type: string, data: Record<string, unknown>): void;
  onState?(state: ConnState): void;
  onError?(message: string): void;
  /** Injected in tests; default to the platform's. */
  wsFactory?: (url: string, protocols?: string[]) => WebSocket;
  setTimeoutFn?: (fn: () => void, ms: number) => unknown;
  clearTimeoutFn?: (handle: unknown) => void;
  now?: () => number;
  log?(line: string): void;
}

export interface SocketHandle {
  /** `false` when the socket is not usable right now. */
  send(payload: Record<string, unknown>): boolean;
  /**
   * Send it, or hold it until the socket is back and send it then. For
   * anything a person typed: asking them to retype into a reconnecting app
   * is the small insult that makes an app feel broken.
   */
  sendOrQueue(payload: Record<string, unknown>): void;
  /** The app came back to the foreground, or the network returned. */
  resume(): void;
  close(): void;
  state(): ConnState;
}

export function openSocket(opts: SocketOptions): SocketHandle {
  const factory = opts.wsFactory ?? ((url, protocols) =>
    (protocols ? new WebSocket(url, protocols) : new WebSocket(url)));
  const setTimer = opts.setTimeoutFn ?? ((fn, ms) => setTimeout(fn, ms));
  const clearTimer = opts.clearTimeoutFn
    ?? ((h) => clearTimeout(h as ReturnType<typeof setTimeout>));
  const now = opts.now ?? (() => Date.now());
  const log = opts.log ?? (() => undefined);

  let ws: WebSocket | null = null;
  let state: ConnState = 'connecting';
  let closedByUser = false;
  let attempts = 0;
  let reconnectTimer: unknown = null;
  let pingTimer: unknown = null;
  let lastHeard = now();
  const queued: Record<string, unknown>[] = [];

  const setState = (next: ConnState): void => {
    if (state === next) return;
    state = next;
    opts.onState?.(next);
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

  function dropAndRetry(why: string): void {
    log(`connection lost (${why})`);
    if (ws) {
      try {
        ws.onclose = null;
        ws.onerror = null;
        ws.onmessage = null;
        ws.close();
      } catch { /* already gone */ }
      ws = null;
    }
    clearTimers();
    scheduleReconnect();
  }

  function open(): void {
    if (closedByUser) return;
    setState(attempts > 0 ? 'reconnecting' : 'connecting');
    let socket: WebSocket;
    try {
      socket = opts.token
        ? factory(opts.url, [WS_AUTH_SUBPROTOCOL, opts.token])
        : factory(opts.url);
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
      const greeting = opts.greeting?.();
      if (greeting) send(greeting);
      while (queued.length > 0) {
        const payload = queued.shift() as Record<string, unknown>;
        if (!send(payload)) { queued.unshift(payload); break; }
      }
      scheduleHousekeeping();
    };

    socket.onmessage = (event: MessageEvent): void => {
      lastHeard = now();
      const raw = typeof event.data === 'string' ? event.data : String(event.data);
      let frame: { type?: string; data?: Record<string, unknown> };
      try {
        frame = JSON.parse(raw);
      } catch {
        return;
      }
      opts.onFrame(String(frame.type ?? ''), frame.data ?? {});
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
        setState('unauthorized');
        opts.onError?.('로그인이 만료됐습니다 — 설정에서 다시 로그인하세요');
        return;
      }
      scheduleReconnect();
    };
  }

  open();

  return {
    send,
    sendOrQueue(payload: Record<string, unknown>): void {
      if (send(payload)) return;
      queued.push(payload);
      scheduleReconnect(true);
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
  };
}
