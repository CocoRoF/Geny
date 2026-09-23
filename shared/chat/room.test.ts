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

test('a turn that failed does not read as the agent talking', () => {
  // Stored before the server could tell the difference. Three of these sat in
  // a row in ellen_new's room, as ordinary bubbles, the agent calmly saying
  // it had hit its session limit.
  const folded = foldRoomMessage([], {
    id: 'm10', type: 'agent', timestamp: 't1',
    content: "Error: CLI '/usr/bin/claude' exited with code 1: [cli_version=2.1.220]",
  });
  assert.equal(folded[0].role, 'notice');
  assert.ok(!folded[0].text.startsWith('Error:'), 'the label is the renderer\'s job');
  assert.match(folded[0].text, /exited with code 1/);
});

test('an answer that merely talks about an error is still an answer', () => {
  const folded = foldRoomMessage([], {
    id: 'm11', type: 'agent', timestamp: 't1',
    content: 'Error: 이 메시지로 시작했지만\n\n실제로는 설명이 이어지는 답변입니다.',
  });
  assert.equal(folded[0].role, 'assistant');
});

test('files on a message come with it', () => {
  const [user] = foldRoom([{
    id: 'u1', type: 'user', content: '이거 봐줘', timestamp: 't',
    attachments: [{ kind: 'image', name: 'a.png', url: '/static/uploads/ab/a.png' }],
  }]);
  assert.equal(user.attachments?.[0].url, '/static/uploads/ab/a.png');
});

test('an agent message that is only a file is not silence', () => {
  const [msg] = foldRoom([{
    id: 'a1', type: 'agent', content: '', timestamp: 't',
    attachments: [{ kind: 'file', name: 'report.pdf', url: '/api/agents/s/storage-raw/report.pdf' }],
  }]);
  assert.ok(msg, 'a delivered file was dropped for having no sentence around it');
  assert.equal(msg.attachments?.[0].name, 'report.pdf');
});

test('an attachment with no way to reach it is not drawn', () => {
  const [msg] = foldRoom([{
    id: 'u2', type: 'user', content: 'hi', timestamp: 't', attachments: [{ kind: 'image', name: 'x' }],
  }]);
  assert.equal(msg.attachments, undefined);
});

test('the voice text rides along with the answer', () => {
  const [msg] = foldRoom([{
    id: 'a2', type: 'agent', content: '좋아!', spoken: '[joy:0.6] 좋아!', timestamp: 't',
  }]);
  assert.equal(msg.text, '좋아!');
  assert.equal(msg.spoken, '[joy:0.6] 좋아!');
});

test('a pending message shows its files before the server has them', () => {
  const pending = pendingUserMessage('봐줘', [{ kind: 'image', url: '/static/uploads/x.png' }]);
  const folded = foldRoomMessage([pending], {
    id: 'u3', type: 'user', content: '봐줘', timestamp: 't',
    attachments: [{ kind: 'image', url: '/static/uploads/x.png' }],
  });
  assert.equal(folded.length, 1);
  assert.equal(folded[0].attachments?.length, 1);
});
