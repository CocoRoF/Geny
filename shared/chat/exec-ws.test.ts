/**
 * The connection rules a phone lives by.
 *
 * Every test here is a behaviour that, missing, turns into the same visible
 * bug: a spinner over a conversation that already finished, or an error over
 * a turn that is still running perfectly well on the server.
 */
import { strict as assert } from 'node:assert';
import { test } from 'node:test';

import { connectExecWs, WS_UNAUTHORIZED_CODE, type ConnState } from './exec-ws';

/** A socket a test can open, feed, and kill. */
class FakeSocket {
  static last: FakeSocket | null = null;
  static created = 0;
  readyState = 0;
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;

  constructor(readonly url: string, readonly protocols?: string[]) {
    FakeSocket.last = this;
    FakeSocket.created += 1;
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.();
  }

  send(raw: string): void {
    this.sent.push(JSON.parse(raw));
  }

  emit(payload: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  kill(code = 1006): void {
    this.readyState = 3;
    this.onclose?.({ code });
  }

  close(): void {
    this.readyState = 3;
  }

  types(): string[] {
    return this.sent.map((m) => String(m.type));
  }
}

/** A clock the test drives. */
function harness(extra: Record<string, unknown> = {}) {
  FakeSocket.last = null;
  FakeSocket.created = 0;
  const timers: { fn: () => void; at: number; id: number }[] = [];
  let clock = 0;
  let nextId = 1;
  const states: ConnState[] = [];
  const errors: string[] = [];
  const running: boolean[] = [];

  const handle = connectExecWs({
    wsBase: 'wss://geny.example',
    sessionId: 's1',
    token: 'jwt-token',
    wsFactory: (url, protocols) => new FakeSocket(url, protocols) as unknown as WebSocket,
    setTimeoutFn: (fn, ms) => {
      const id = nextId++;
      timers.push({ fn, at: clock + ms, id });
      return id;
    },
    clearTimeoutFn: (h) => {
      const index = timers.findIndex((t) => t.id === h);
      if (index >= 0) timers.splice(index, 1);
    },
    now: () => clock,
    onState: (s) => states.push(s),
    onError: (e) => errors.push(e),
    onRunning: (r) => running.push(r),
    ...extra,
  });

  const advance = (ms: number): void => {
    clock += ms;
    for (;;) {
      const due = timers.filter((t) => t.at <= clock).sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      timers.splice(timers.indexOf(due), 1);
      due.fn();
    }
  };

  return { handle, advance, states, errors, running, socket: () => FakeSocket.last! };
}

// ── the handshake ────────────────────────────────────────────────────

test('the token rides in the subprotocol, never the URL', () => {
  const h = harness();
  assert.equal(h.socket().url, 'wss://geny.example/ws/execute/s1');
  assert.deepEqual(h.socket().protocols, ['geny-auth', 'jwt-token']);
  assert.ok(!h.socket().url.includes('jwt-token'), 'a token in the URL lands in proxy logs');
});

test('every connect asks whether a turn is already running', () => {
  const h = harness();
  h.socket().open();
  assert.deepEqual(h.socket().types(), ['reconnect']);
});

test('a turn found in flight is reported as running', () => {
  const h = harness();
  h.socket().open();
  h.socket().emit({ type: 'status', data: { status: 'running' } });
  assert.deepEqual(h.running, [true]);
});

test('an idle session is reported as idle, not as an error', () => {
  const h = harness();
  h.socket().open();
  h.socket().emit({ type: 'status', data: { status: 'idle', message: 'No active execution' } });
  assert.deepEqual(h.errors, []);
  assert.equal(h.handle.running(), false);
});

// ── a drop is not a failure ──────────────────────────────────────────

test('losing the socket does not report an error', () => {
  const h = harness();
  h.socket().open();
  h.socket().kill();
  assert.deepEqual(h.errors, [], 'the turn is still running on the server');
  assert.equal(h.handle.state(), 'reconnecting');
});

test('it reconnects with a growing backoff', () => {
  const h = harness();
  h.socket().open();
  h.socket().kill();
  const before = FakeSocket.created;
  h.advance(1_000);
  assert.equal(FakeSocket.created, before + 1);

  h.socket().kill();
  h.advance(1_000);
  assert.equal(FakeSocket.created, before + 1, 'second wait is longer than the first');
  h.advance(1_000);
  assert.equal(FakeSocket.created, before + 2);
});

test('the replay after a reconnect is asked for again', () => {
  const h = harness();
  h.socket().open();
  h.socket().kill();
  h.advance(1_000);
  h.socket().open();
  assert.deepEqual(h.socket().types(), ['reconnect']);
});

// ── the socket that lies ─────────────────────────────────────────────

test('an idle socket is kept alive with a ping', () => {
  const h = harness();
  h.socket().open();
  h.advance(25_000);
  assert.deepEqual(h.socket().types(), ['reconnect', 'ping']);
});

test('silence past the limit forces a reconnect even while the socket says open', () => {
  const h = harness();
  const first = h.socket();
  first.open();
  const created = FakeSocket.created;
  // Pings go out and nothing ever comes back — a carrier NAT dropped the flow
  // an hour ago and neither end noticed.
  h.advance(25_000);
  h.advance(25_000);
  h.advance(25_000);
  assert.equal(h.handle.state(), 'reconnecting');
  h.advance(1_000);
  assert.ok(FakeSocket.created > created, 'a new socket was opened');
});

test('a pong resets the silence clock', () => {
  const h = harness();
  h.socket().open();
  h.advance(25_000);
  h.socket().emit({ type: 'pong', data: { ts: 1, running: false } });
  h.advance(25_000);
  h.socket().emit({ type: 'pong', data: { ts: 2, running: false } });
  h.advance(25_000);
  assert.equal(h.handle.state(), 'connected');
});

test('a pong carries whether a turn is running', () => {
  const h = harness();
  h.socket().open();
  h.socket().emit({ type: 'pong', data: { running: true } });
  assert.equal(h.handle.running(), true);
});

// ── waking up ────────────────────────────────────────────────────────

test('resuming skips the backoff', () => {
  const h = harness();
  h.socket().open();
  h.socket().kill();
  h.advance(500);            // still waiting
  const created = FakeSocket.created;
  h.handle.resume();
  assert.equal(FakeSocket.created, created + 1, 'foreground is not "the server is down"');
});

test('resuming on a socket that looks fine makes it prove it', () => {
  const h = harness();
  h.socket().open();
  h.handle.resume();
  assert.deepEqual(h.socket().types(), ['reconnect', 'ping']);
});

test('a connection that works resets the budget', () => {
  // A socket that opened is not a failure — a phone on a flaky train should
  // not exhaust its retries over an afternoon of brief drops.
  const h = harness();
  for (let i = 0; i < 20; i += 1) {
    h.socket().open();
    h.socket().kill();
    h.advance(30_000);
  }
  assert.notEqual(h.handle.state(), 'offline');
});

test('a server that never answers is eventually given up on', () => {
  const h = harness();
  // Every attempt dies before the socket ever opens — the server is gone.
  for (let i = 0; i < 20 && h.handle.state() !== 'offline'; i += 1) {
    h.socket().kill();
    h.advance(30_000);
  }
  assert.equal(h.handle.state(), 'offline');
});

test('giving up is about us, not about the turn — resume still recovers', () => {
  const h = harness();
  for (let i = 0; i < 20 && h.handle.state() !== 'offline'; i += 1) {
    h.socket().kill();
    h.advance(30_000);
  }
  assert.equal(h.handle.state(), 'offline');
  const created = FakeSocket.created;
  h.handle.resume();
  assert.equal(FakeSocket.created, created + 1);
  assert.notEqual(h.handle.state(), 'offline');
});

// ── sending ──────────────────────────────────────────────────────────

test('a prompt typed while reconnecting is held, not refused', () => {
  const h = harness();
  h.socket().open();
  h.socket().kill();
  h.handle.execute('한 줄 정리해줘');
  h.advance(1_000);
  h.socket().open();
  const execs = h.socket().sent.filter((m) => m.type === 'execute');
  assert.equal(execs.length, 1);
  assert.equal(execs[0].prompt, '한 줄 정리해줘');
});

test('an empty prompt is not sent', () => {
  const h = harness();
  h.socket().open();
  h.handle.execute('   ');
  assert.deepEqual(h.socket().types(), ['reconnect']);
});

test('done clears the running flag', () => {
  const h = harness();
  h.socket().open();
  h.socket().emit({ type: 'status', data: { status: 'running' } });
  h.socket().emit({ type: 'done', data: {} });
  assert.equal(h.handle.running(), false);
});

// ── the one failure that is ours ─────────────────────────────────────

test('a rejected token stops the retry loop and says to sign in', () => {
  const h = harness();
  h.socket().open();
  const created = FakeSocket.created;
  h.socket().kill(WS_UNAUTHORIZED_CODE);
  h.advance(60_000);
  assert.equal(FakeSocket.created, created, 'retrying a dead token forever helps nobody');
  assert.equal(h.handle.state(), 'unauthorized');
  assert.match(h.errors.join(' '), /로그인/);
});

test('closing is final', () => {
  const h = harness();
  h.socket().open();
  h.handle.close();
  const created = FakeSocket.created;
  h.advance(60_000);
  assert.equal(FakeSocket.created, created);
  assert.equal(h.handle.state(), 'closed');
});
