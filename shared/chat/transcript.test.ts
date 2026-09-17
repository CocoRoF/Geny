/**
 * Folding the session log into something a phone can read.
 *
 * The replay case is the one that matters: a reconnect sends the turn again
 * from its start, and a fold that is not idempotent turns "the phone caught
 * up" into "the phone said everything twice".
 */
import { strict as assert } from 'node:assert';
import { test } from 'node:test';

import {
  describeTool, foldAll, foldEntry, latestAssistantText, pendingUserMessage, type Message,
} from './transcript';

const user = { timestamp: '2026-09-17T10:00:00', level: 'COMMAND', message: '테스트 돌려줘' };
const answer = { timestamp: '2026-09-17T10:00:30', level: 'RESPONSE', message: '전부 통과했습니다.' };
const wrote = {
  timestamp: '2026-09-17T10:00:10',
  level: 'TOOL',
  message: '🔧 Write',
  metadata: {
    type: 'tool_use', tool_name: 'Write', tool_id: 't1',
    file_changes: { file_path: '/w/app.py', operation: 'write', lines_added: 12, lines_removed: 0 },
  },
};
const ran = {
  timestamp: '2026-09-17T10:00:12',
  level: 'TOOL',
  message: '🔧 Bash',
  metadata: { type: 'tool_use', tool_name: 'Bash', tool_id: 't2', command_data: { command: 'pytest -q' } },
};
const ok = (toolName: string, toolId: string) => ({
  timestamp: '2026-09-17T10:00:13',
  level: 'TOOL_RES',
  message: `TOOL_RESULT: ${toolName}`,
  metadata: { type: 'tool_result', tool_name: toolName, tool_id: toolId, is_error: false, result_preview: 'ok' },
});
const failed = (toolName: string, toolId: string) => ({
  timestamp: '2026-09-17T10:00:14',
  level: 'TOOL_RES',
  message: `TOOL_RESULT: ${toolName}`,
  metadata: { type: 'tool_result', tool_name: toolName, tool_id: toolId, is_error: true, result_preview: 'exit 1' },
});

test('a turn becomes a question and an answer', () => {
  const messages = foldAll([user, answer]);
  assert.deepEqual(messages.map((m) => m.role), ['user', 'assistant']);
  assert.equal(messages[1].text, '전부 통과했습니다.');
});

test('a tool call is one line, not a wall', () => {
  const messages = foldAll([user, wrote, ok('Write', 't1'), answer]);
  assert.deepEqual(messages.map((m) => m.role), ['user', 'activity', 'assistant']);
  assert.equal(messages[1].text, 'write /w/app.py  +12');
  assert.equal(messages[1].ok, true);
});

test('a command shows what was run', () => {
  assert.equal(describeTool(ran).text, '$ pytest -q');
});

test('a result marks the call it belongs to rather than adding a line', () => {
  const messages = foldAll([ran, ok('Bash', 't2')]);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].ok, true);
});

test('a failure interrupts, because it is worth interrupting for', () => {
  const messages = foldAll([ran, failed('Bash', 't2')]);
  assert.deepEqual(messages.map((m) => m.role), ['activity', 'notice']);
  assert.equal(messages[0].ok, false);
  assert.equal(messages[1].text, 'exit 1');
});

test('a replayed turn does not say everything twice', () => {
  const entries = [user, wrote, ok('Write', 't1'), answer];
  const once = foldAll(entries);
  const twice = entries.reduce<Message[]>((acc, entry, i) => foldEntry(acc, entry, i), once);
  assert.deepEqual(twice.map((m) => m.key), once.map((m) => m.key));
});

test('engine detail stays out of the conversation', () => {
  const messages = foldAll([
    user,
    { level: 'STAGE', message: 'stage.enter s06_api' },
    { level: 'INFO', message: 'MemoryProvider ready' },
    answer,
  ]);
  assert.deepEqual(messages.map((m) => m.role), ['user', 'assistant']);
});

test('an error reaches the screen', () => {
  const messages = foldAll([{ level: 'ERROR', message: '세션이 죽었습니다' }]);
  assert.deepEqual(messages.map((m) => m.role), ['notice']);
});

test('metadata that arrived as JSON text is still read', () => {
  const asText = { ...wrote, metadata: JSON.stringify(wrote.metadata) };
  assert.equal(foldAll([asText])[0].text, 'write /w/app.py  +12');
});

test('the streaming answer is the last assistant message', () => {
  assert.equal(latestAssistantText(foldAll([user, answer])), '전부 통과했습니다.');
  assert.equal(latestAssistantText(foldAll([user])), '');
});

test("the server's echo replaces the message already on screen", () => {
  // Otherwise every single turn shows the question twice — once optimistically
  // and once when the server logs it a moment later with its own timestamp.
  const optimistic = [pendingUserMessage('테스트 돌려줘')];
  const folded = foldEntry(optimistic, user, 1);
  assert.equal(folded.length, 1);
  assert.equal(folded[0].pending, undefined);
  assert.equal(folded[0].ts, user.timestamp);
});

test('the same line genuinely sent twice stays two messages', () => {
  const first = foldEntry([pendingUserMessage('다시')], { level: 'COMMAND', message: '다시', timestamp: 'a' }, 1);
  const second = foldEntry([...first, pendingUserMessage('다시')], { level: 'COMMAND', message: '다시', timestamp: 'b' }, 2);
  assert.equal(second.filter((m) => m.role === 'user').length, 2);
});

// ── what the desktop opens ───────────────────────────────────────────
// The phone shows a tool call as one line. A desktop row expands, and what it
// expands into has to come from the same fold — a second folder written for
// the bigger screen is how the two surfaces start disagreeing about what the
// agent did.

test('a tool call carries its arguments and its result', () => {
  const start = foldEntry([], {
    level: 'TOOL',
    timestamp: 't1',
    message: 'TOOL_USE: Bash',
    metadata: {
      tool_name: 'Bash',
      tool_id: 'call_1',
      input_preview: '{"command": "npm test"}',
      command_data: { command: 'npm test' },
    },
  });
  const done = foldEntry(start, {
    level: 'TOOL_RES',
    timestamp: 't2',
    message: 'TOOL_RESULT [OK]: Bash',
    metadata: {
      tool_name: 'Bash',
      tool_id: 'call_1',
      result_preview: '41 passing',
      duration_ms: 3200,
    },
  });
  assert.equal(done.length, 1);
  assert.equal(done[0].args, '{"command": "npm test"}');
  assert.equal(done[0].result, '41 passing');
  assert.equal(done[0].durationMs, 3200);
  assert.equal(done[0].ok, true);
});

test('the result lands on the call with the same id, not the nearest one', () => {
  // Two calls to the same tool in flight. Name matching would close the first
  // one with the second one's verdict.
  let messages = foldEntry([], {
    level: 'TOOL', timestamp: 't1', message: 'TOOL_USE: Read',
    metadata: { tool_name: 'Read', tool_id: 'a', file_read: { file_path: '/a' } },
  });
  messages = foldEntry(messages, {
    level: 'TOOL', timestamp: 't2', message: 'TOOL_USE: Read',
    metadata: { tool_name: 'Read', tool_id: 'b', file_read: { file_path: '/b' } },
  });
  messages = foldEntry(messages, {
    level: 'TOOL_RES', timestamp: 't3', message: 'TOOL_RESULT [ERROR]: Read',
    metadata: { tool_name: 'Read', tool_id: 'b', is_error: true, result_preview: 'no such file' },
  });

  const rows = messages.filter((m) => m.role === 'activity');
  assert.equal(rows.length, 2);
  assert.equal(rows[0].ok, null, 'the first call is still open');
  assert.equal(rows[1].ok, false);
  assert.equal(rows[1].result, 'no such file');
});
