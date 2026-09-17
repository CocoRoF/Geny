/**
 * The two things a phone gets wrong about a server address, and the one thing
 * it must do with a dead token.
 */
import { strict as assert } from 'node:assert';
import { test } from 'node:test';

import {
  normalizeBaseUrl, request, rooms, setUnauthorizedHandler, ServerError, toWsBase,
} from '../src/lib/server';

test('a bare host becomes https, not http', () => {
  // Downgrading silently would send the password over the air in the clear.
  assert.equal(normalizeBaseUrl('geny.example.com'), 'https://geny.example.com');
});

test('an explicit scheme is respected', () => {
  assert.equal(normalizeBaseUrl('http://192.168.0.9:8000'), 'http://192.168.0.9:8000');
});

test('trailing slashes do not double up in paths', () => {
  assert.equal(normalizeBaseUrl('https://geny.example.com///'), 'https://geny.example.com');
});

test('the websocket base follows the http scheme', () => {
  assert.equal(toWsBase('https://geny.example.com'), 'wss://geny.example.com');
  assert.equal(toWsBase('http://10.0.0.2:8000'), 'ws://10.0.0.2:8000');
});

test('a missing address is refused before a request is made', async () => {
  await assert.rejects(
    () => request({ baseUrl: '', token: null }, '/api/agents'),
    (e: ServerError) => e.status === 0,
  );
});

test('a 401 clears the session exactly once and says so', async () => {
  let cleared = 0;
  setUnauthorizedHandler(() => { cleared += 1; });
  const original = globalThis.fetch;
  globalThis.fetch = (async () => new Response('{}', { status: 401 })) as typeof fetch;
  try {
    await assert.rejects(
      () => request({ baseUrl: 'https://geny.example', token: 'stale' }, '/api/agents'),
      (e: ServerError) => e.status === 401,
    );
  } finally {
    globalThis.fetch = original;
    setUnauthorizedHandler(() => undefined);
  }
  assert.equal(cleared, 1);
});

test("the server's own reason survives to the screen", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ detail: '그 라우트에는 쓸 수 있는 계정이 없습니다' }), { status: 400 })) as typeof fetch;
  try {
    await assert.rejects(
      () => request({ baseUrl: 'https://geny.example', token: 't' }, '/api/agents/x/route'),
      (e: ServerError) => e.message.includes('계정이 없습니다'),
    );
  } finally {
    globalThis.fetch = original;
  }
});

test('an HTML error page is not dumped onto the screen', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response('<html><body>502 Bad Gateway</body></html>', { status: 502 })) as typeof fetch;
  try {
    await assert.rejects(
      () => request({ baseUrl: 'https://geny.example', token: 't' }, '/api/agents'),
      (e: ServerError) => e.message === 'HTTP 502',
    );
  } finally {
    globalThis.fetch = original;
  }
});

test("the room for a session is asked of the server, not worked out here", async () => {
  // Three surfaces each applying their own rule is what made one session show
  // three conversations. The phone asks; the server answers.
  const seen: string[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (url: string) => {
    seen.push(String(url));
    return new Response(JSON.stringify({ id: 'r1', name: 'x', session_ids: ['s 1'] }),
      { status: 200, headers: { 'Content-Type': 'application/json' } });
  }) as unknown as typeof fetch;
  try {
    const creds = { baseUrl: 'https://g.example', token: 't' };
    const room = await rooms.forSession(creds, 's 1');
    assert.equal(room.id, 'r1');
    await rooms.send(creds, 'r1', '안녕');
    assert.deepEqual(seen, [
      'https://g.example/api/chat/rooms/for-session/s%201',
      // One agent in the room, so the door is "message" — not "broadcast",
      // which is what it was called when a room held several.
      'https://g.example/api/chat/rooms/r1/message',
    ]);
  } finally {
    globalThis.fetch = original;
  }
});
