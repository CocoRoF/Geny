/**
 * The conversation is the room, and every surface must fold it the same way.
 *
 * These exist because the app and the web showed different conversations for
 * a week: the web rendered the room, the app rendered the execute log, and
 * both looked plausible on their own.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { foldCalls, foldRoom, foldRoomMessage, lastRoomId } from './room';
import { pendingUserMessage } from './transcript';

test('a room message folds by id, and a replay lands on itself', () => {
  const one = foldRoomMessage([], { id: 'm1', type: 'agent', content: '응, 사장님.', timestamp: 't1' });
  const again = foldRoomMessage(one, { id: 'm1', type: 'agent', content: '응, 사장님.', timestamp: 't1' });
  assert.equal(again.length, 1, 'a reconnect replays; it must not duplicate');
  assert.equal(again[0].text, '응, 사장님.');
});

test('the server copy adopts the bubble already on screen', () => {
  const pending = pendingUserMessage('뭐야');
  const after = foldRoomMessage([pending], { id: 'm2', type: 'user', content: '뭐야', timestamp: 't2' });
  assert.equal(after.length, 1);
  assert.equal(after[0].pending, undefined);
  assert.equal(after[0].key, 'room:m2');
});

test('the same words typed twice are two messages', () => {
  let m = foldRoomMessage([], { id: 'a', type: 'user', content: '뭐야', timestamp: 't1' });
  m = foldRoomMessage(m, { id: 'b', type: 'user', content: '뭐야', timestamp: 't2' });
  assert.equal(m.length, 2);
});

test('a silent agent message puts nothing in the room', () => {
  const m = foldRoomMessage([], { id: 'm3', type: 'agent', content: '[calm:0.3] [SILENT]' });
  assert.equal(m.length, 0);
});

test('the mood tag comes off, and the duration rides along', () => {
  const m = foldRoomMessage([], {
    id: 'm4', type: 'agent', content: '[curious:0.5] 빌드 끝났어.', duration_ms: 19500,
  });
  assert.equal(m[0].text, '빌드 끝났어.');
  assert.equal(m[0].mood, 'curious');
  assert.equal(m[0].durationMs, 19500);
});

test('the resume cursor is the newest room message', () => {
  const m = foldRoom([
    { id: 'a', type: 'user', content: '하나' },
    { id: 'b', type: 'agent', content: '둘' },
  ]);
  assert.equal(lastRoomId(m), 'b');
  // A pending bubble is not a cursor: the server has never heard of it.
  assert.equal(lastRoomId([...m, pendingUserMessage('셋')]), 'b');
});

test('nothing to resume from is null, not undefined', () => {
  assert.equal(lastRoomId([]), null);
});

// ── the progress feed ────────────────────────────────────────────────

test('tool calls pair by id', () => {
  const calls = foldCalls([
    { level: 'TOOL', tool_name: 'Bash', tool_id: 'a', input_preview: '{"command":"ls"}' },
    { level: 'TOOL', tool_name: 'Read', tool_id: 'b' },
    { level: 'TOOL_RES', tool_name: 'Read', tool_id: 'b', is_error: true, result_preview: 'nope', duration_ms: 12 },
  ]);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].ok, null, 'the first is still running');
  assert.equal(calls[1].ok, false);
  assert.equal(calls[1].result, 'nope');
});

test('a result with no id falls back to the open call of that name', () => {
  // Production sends both shapes; a batch summary arrives with neither.
  const calls = foldCalls([
    { level: 'TOOL', tool_name: 'Bash' },
    { level: 'TOOL_RES', tool_name: 'Bash', is_error: false, duration_ms: 40 },
  ]);
  assert.equal(calls[0].ok, true);
  assert.equal(calls[0].durationMs, 40);
});

test('a result for a call nobody announced is dropped, not invented', () => {
  assert.deepEqual(foldCalls([{ level: 'TOOL_RES', tool_name: 'Ghost' }]), []);
});

test("the room's own bookkeeping is a status line, not a failed turn", () => {
  // "1/1 sessions responded" arrives as a system message after EVERY
  // broadcast, successful ones included. Folding it as a notice drew a red
  // 실패 box under every answer the agent got right.
  const folded = foldRoomMessage([], {
    id: 'm9', type: 'system', content: '1/1 sessions responded (7.1s)', timestamp: 't9',
  });
  assert.equal(folded[0].role, 'system');
  assert.equal(folded[0].text, '1/1 sessions responded (7.1s)');
});
