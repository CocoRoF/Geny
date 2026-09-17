/**
 * The turn stream: what a session is DOING right now.
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

import { openSocket, WS_AUTH_SUBPROTOCOL, WS_UNAUTHORIZED_CODE, type ConnState, type SocketHandle }
  from './socket';

export { WS_AUTH_SUBPROTOCOL, WS_UNAUTHORIZED_CODE };
export type { ConnState };

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

export interface ExecWsHandle {
  /** Start a turn. */
  execute(prompt: string): void;
  stop(): void;
  /** The app came back to the foreground, or the network returned. */
  resume(): void;
  close(): void;
  state(): ConnState;
  running(): boolean;
}

export function connectExecWs(opts: ExecWsOptions): ExecWsHandle {
  const url = `${opts.wsBase.replace(/\/+$/, '')}/ws/execute/${encodeURIComponent(opts.sessionId)}`;
  let running = false;

  const setRunning = (next: boolean): void => {
    if (running === next) return;
    running = next;
    opts.onRunning?.(next);
  };

  const socket: SocketHandle = openSocket({
    url,
    token: opts.token,
    wsFactory: opts.wsFactory,
    setTimeoutFn: opts.setTimeoutFn,
    clearTimeoutFn: opts.clearTimeoutFn,
    now: opts.now,
    log: opts.log,
    onState: opts.onState,
    onError: opts.onError,
    // Always ask. The answer is either "here is the turn you missed, from the
    // beginning" or "nothing is running" — and not asking is how a phone ends
    // up showing a spinner over a conversation that finished while it slept.
    greeting: () => ({ type: 'reconnect' }),
    onFrame(type, data) {
      switch (type) {
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
      }
    },
  });

  return {
    execute(prompt: string): void {
      const text = prompt.trim();
      if (!text) return;
      socket.sendOrQueue({ type: 'execute', prompt: text });
    },
    stop(): void {
      socket.send({ type: 'stop' });
    },
    resume: socket.resume,
    close: socket.close,
    state: socket.state,
    running: () => running,
  };
}
