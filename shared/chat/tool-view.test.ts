/**
 * The rules that decide what a tool call says it did.
 *
 * The one that matters most is what is NOT here: no test asserts a label for
 * a named MCP server or a named agent, because the model must not recognise
 * one. A tool nobody has heard of has to come out readable too.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { describeTool, resultView, summarizeArgs, summarizeCommand } from './tool-view';

test('a one-line command is the command', () => {
  assert.equal(summarizeCommand('npm test -- --watch'), 'npm test -- --watch');
});

test('a script is its language, its length and what it imported', () => {
  // Never what it was FOR: that is the model's to say and not ours to guess.
  const script = [
    'python3 - <<EOF',
    'import pdfplumber, json',
    'from re import sub',
    'print(1)',
    'EOF',
  ].join('\n');
  assert.equal(summarizeCommand(script), '파이썬 스크립트 5줄 · pdfplumber, json, re');
});

test('the built-in tools speak plain language', () => {
  assert.deepEqual(describeTool('Glob', { pattern: '**/*.pdf' }),
    { icon: 'search', text: '파일 찾기 · **/*.pdf' });
  assert.deepEqual(describeTool('WebSearch', { query: '삼성전자 주가' }),
    { icon: 'web', text: '웹 검색 · 삼성전자 주가' });
  assert.deepEqual(describeTool('Read', { file_path: '/data/agents/a/workspace/src/a.ts' }),
    { icon: 'file', text: '파일 읽기 · src/a.ts' });
});

test('a tool nobody knows still reads', () => {
  // Its registered description if there is one, else its name and two args.
  assert.deepEqual(
    describeTool('mcp__vendor__table_export', { filename: 'out/report', format: 'xlsx', pretty: true }),
    { icon: 'external', text: 'table_export · filename out/report, format xlsx' },
  );
  assert.deepEqual(
    describeTool('mcp__vendor__table_export', { filename: 'out/report' }, 'Saves a table to a file. Supports xlsx and csv.'),
    { icon: 'external', text: 'Saves a table to a file · filename out/report' },
  );
});

test('switches and structures are not argument summary material', () => {
  assert.equal(summarizeArgs({ deep: true, opts: { a: 1 }, name: 'x' }), 'name x');
});

test('a text result is its first line and how many there were', () => {
  const view = resultView('uploads/위해상품_공표문_85개.pdf\nb.pdf\nc.pdf');
  assert.equal(view?.line, 'uploads/위해상품_공표문_85개.pdf · 3줄');
});

test('a list of objects becomes a small table', () => {
  const view = resultView(JSON.stringify([
    { name: '가', price: 1000 }, { name: '나', price: 2000 },
  ]));
  assert.deepEqual(view?.table?.columns, ['name', 'price']);
  assert.deepEqual(view?.table?.rows[0], ['가', '1000']);
});

test('an object with a name becomes a card', () => {
  const view = resultView(JSON.stringify({ name: '피카츄 운동화', price: 29000, found: true }));
  assert.equal(view?.title, '피카츄 운동화');
  assert.deepEqual(view?.fields, [['price', '29000']]);
  assert.deepEqual(view?.flags, [['found', true]]);
});

test('JSON the server truncated is treated as text, not dropped', () => {
  const view = resultView('{"rows": [{"a": 1}, {"a": 2}');
  assert.ok(view?.line?.startsWith('{"rows"'));
});

test('no result draws nothing', () => {
  assert.equal(resultView(''), null);
  assert.equal(resultView(undefined), null);
});
