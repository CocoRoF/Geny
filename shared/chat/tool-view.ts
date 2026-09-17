/**
 * What a tool call should SAY it did, and what its result looks like.
 *
 * Ported from XGen Dex (`apps/desktop/src/renderer/src/views/
 * process-timeline-model.ts`) so both products describe a tool call the same
 * way, and so Geny's app and Geny's web page cannot drift from each other —
 * they import this, not their own copy.
 *
 * The rule that makes it work everywhere: **no agent, tool or service is
 * recognised by name beyond the built-ins.**
 *
 *  · Labels: the standard tools (shell, files, search, web) become plain
 *    language. Everything else — MCP, connector, API tools — gets the first
 *    clause of its registered description, or its name plus two arguments.
 *  · Shell: the command's PURPOSE is never guessed from its content. Language,
 *    line count, imported modules — no further.
 *  · Results: JSON is drawn by its shape (a list of objects → a small table,
 *    an object with a name → a card, otherwise key/value). Anything else is
 *    its first line and how many lines there were.
 *
 * Pure, and tested under `node:test`.
 */

export type ToolIcon =
  | 'terminal' | 'package' | 'search' | 'file' | 'edit' | 'web' | 'list' | 'external';

const clip = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** `/data/agents/x/workspace/src/a.ts` → `src/a.ts`. */
const workspaceTail = (p: string): string => p.split('/workspace/').pop() ?? p;

/** `mcp__geny__memory_pin` → `memory_pin`; `Bash` → `Bash`. */
export function shortToolName(name: string): string {
  const parts = (name ?? '').split('__');
  return parts[parts.length - 1] || name || 'tool';
}

export function parseToolInput(input: unknown): Record<string, unknown> {
  if (input && typeof input === 'object' && !Array.isArray(input)) {
    return input as Record<string, unknown>;
  }
  if (typeof input === 'string') {
    try {
      const v = JSON.parse(input);
      return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
    } catch {
      return {};
    }
  }
  return {};
}

/**
 * A shell command, summarised. One line is the command itself; a script is
 * its language, its length and what it imported — never a guess at what it
 * was FOR, which is the model's job to say and not ours to invent.
 */
export function summarizeCommand(command: string): string {
  const cmd = (command ?? '').trim();
  if (!cmd) return '명령 실행';
  const lines = cmd.split('\n');
  if (lines.length === 1) return clip(cmd, 100);
  const head = lines[0];
  const lang = /\bpython3?\b/.test(head) ? '파이썬'
    : /\b(node|deno|bun)\b/.test(head) ? '자바스크립트'
      : '셸';
  const mods: string[] = [];
  if (lang === '파이썬') {
    for (const line of lines) {
      const imp = line.match(/^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)/);
      const from = line.match(/^\s*from\s+([\w.]+)\s+import\b/);
      const names = imp ? imp[1].split(',') : from ? [from[1]] : [];
      for (const n of names) {
        const top = n.trim().split('.')[0];
        if (top && !mods.includes(top)) mods.push(top);
      }
    }
  }
  const modText = mods.length
    ? ` · ${mods.slice(0, 4).join(', ')}${mods.length > 4 ? ' 외' : ''}`
    : '';
  return `${lang} 스크립트 ${lines.length}줄${modText}`;
}

/** Up to `max` short arguments as `key value`. Objects, arrays and switches
 *  are skipped — they say nothing at a glance. */
export function summarizeArgs(input: Record<string, unknown>, max = 2): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(input)) {
    if (v === null || v === undefined || typeof v === 'object' || typeof v === 'boolean') continue;
    const s = String(v).replace(/\s+/g, ' ').trim();
    if (!s) continue;
    parts.push(`${k} ${clip(s, 40)}`);
    if (parts.length >= max) break;
  }
  return parts.join(', ');
}

/** The first clause of a registered tool description, short enough for a row. */
export function descriptionHeadline(description?: string): string {
  const d = (description ?? '').replace(/\s+/g, ' ').trim();
  if (!d) return '';
  const first = d.split(/(?<=[.!?。])\s/)[0] ?? d;
  return clip(first.replace(/[.。]$/, ''), 48);
}

/** One tool row: which badge it wears, and what it says. */
export function describeTool(
  name: string,
  rawInput: unknown,
  description?: string,
): { icon: ToolIcon; text: string } {
  const input = parseToolInput(rawInput);
  const short = shortToolName(name);
  const str = (...keys: string[]): string => {
    for (const k of keys) {
      const v = input[k];
      if (typeof v === 'string' && v.trim()) return v;
    }
    return '';
  };
  switch (short) {
    case 'Bash':
    case 'Shell':
      return { icon: 'terminal', text: summarizeCommand(str('command', 'cmd')) };
    case 'PythonEnv': {
      const pkgs = Array.isArray(input.packages) ? (input.packages as unknown[]).join(', ') : '';
      return { icon: 'package', text: `파이썬 패키지 준비${pkgs ? ` · ${clip(pkgs, 60)}` : ''}` };
    }
    case 'Glob':
      return { icon: 'search', text: `파일 찾기 · ${str('pattern')}` };
    case 'Grep':
      return { icon: 'search', text: `내용 찾기 · ${str('pattern')}` };
    case 'ToolSearch':
      return { icon: 'search', text: `사용할 도구 찾기 · ${str('query')}` };
    case 'Read':
      return { icon: 'file', text: `파일 읽기 · ${workspaceTail(str('file_path', 'path', 'file'))}` };
    case 'Write':
      return { icon: 'edit', text: `파일 쓰기 · ${workspaceTail(str('file_path', 'path', 'file'))}` };
    case 'Edit':
    case 'MultiEdit':
      return { icon: 'edit', text: `파일 수정 · ${workspaceTail(str('file_path', 'path', 'file'))}` };
    case 'WebFetch':
      return { icon: 'web', text: `웹 페이지 열기 · ${clip(str('url'), 60)}` };
    case 'WebSearch':
      return { icon: 'web', text: `웹 검색 · ${str('query')}` };
    case 'TodoWrite':
      return { icon: 'list', text: '할 일 목록 갱신' };
    default: {
      const label = descriptionHeadline(description) || short;
      const args = summarizeArgs(input);
      return { icon: 'external', text: args ? `${label} · ${args}` : label };
    }
  }
}

// ── results ──────────────────────────────────────────────────────────

/** How to draw a result. Empty parts are not drawn. */
export interface ResultView {
  /** An object that carries a name → the card's title. */
  title?: string;
  /** Short scalars as `[key, value]`. */
  fields: Array<[string, string]>;
  /** Booleans as `[key, value]`. */
  flags: Array<[string, boolean]>;
  /** A list of objects → a small table (first rows). */
  table?: { columns: string[]; rows: string[][]; more: number };
  /** Not JSON → the first line, and how many there were. */
  line?: string;
}

const TITLE_KEYS = ['title', 'name', 'display_name', 'displayName', 'label', 'subject', 'headline'];
const TABLE_ROWS = 5;

const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === 'object' && !Array.isArray(v);

const scalarText = (v: unknown): string | null =>
  typeof v === 'string' ? clip(v.replace(/\s+/g, ' ').trim(), 60)
    : typeof v === 'number' ? String(v)
      : null;

function titleOf(o: Record<string, unknown>): [string, string] | null {
  for (const k of TITLE_KEYS) {
    const v = o[k];
    if (typeof v === 'string' && v.trim()) return [k, v.trim()];
  }
  return null;
}

function collect(
  o: Record<string, unknown>,
  skip: ReadonlySet<string>,
  view: ResultView,
  maxFields: number,
): void {
  for (const [k, v] of Object.entries(o)) {
    if (skip.has(k)) continue;
    if (typeof v === 'boolean') {
      if (view.flags.length < 4) view.flags.push([k, v]);
      continue;
    }
    const s = scalarText(v);
    if (s && view.fields.length < maxFields) view.fields.push([k, s]);
  }
}

function tableOf(items: Record<string, unknown>[]): NonNullable<ResultView['table']> {
  const first = items[0];
  const keys = Object.keys(first)
    .filter((k) => typeof first[k] === 'string' || typeof first[k] === 'number');
  const t = titleOf(first)?.[0];
  const columns = (t ? [t, ...keys.filter((k) => k !== t)] : keys).slice(0, 4);
  return {
    columns,
    rows: items.slice(0, TABLE_ROWS).map((r) => columns.map((c) => scalarText(r[c]) ?? '')),
    more: Math.max(0, items.length - TABLE_ROWS),
  };
}

function jsonView(v: unknown): ResultView {
  const view: ResultView = { fields: [], flags: [] };
  if (Array.isArray(v)) {
    const objs = v.filter(isPlainObject);
    if (objs.length) view.table = tableOf(objs);
    else view.line = clip(JSON.stringify(v), 160);
    return view;
  }
  if (!isPlainObject(v)) {
    view.line = clip(String(v), 160);
    return view;
  }
  const keys = Object.keys(v);
  const listKey = keys.find((k) => Array.isArray(v[k]) && (v[k] as unknown[]).some(isPlainObject));
  const own = titleOf(v);
  const entityKey = own
    ? undefined
    : keys.find((k) => isPlainObject(v[k]) && titleOf(v[k] as Record<string, unknown>));
  if (own) {
    view.title = own[1];
    collect(v, new Set([own[0], ...(listKey ? [listKey] : [])]), view, 3);
  } else if (entityKey) {
    const entity = v[entityKey] as Record<string, unknown>;
    const t = titleOf(entity) as [string, string];
    view.title = t[1];
    collect(entity, new Set([t[0]]), view, 3);
    // The outer booleans ("found", "ok") belong beside the card.
    collect(v, new Set([entityKey, ...(listKey ? [listKey] : [])]), view, view.fields.length);
  } else {
    collect(v, new Set(listKey ? [listKey] : []), view, listKey ? 3 : 6);
  }
  if (listKey) view.table = tableOf((v[listKey] as unknown[]).filter(isPlainObject));
  if (!view.title && !view.table && !view.fields.length && !view.flags.length) {
    view.line = clip(JSON.stringify(v), 160);
  }
  return view;
}

/** A tool's result text → the shape to draw. `null` when there is none. */
export function resultView(result: string | undefined): ResultView | null {
  const raw = (result ?? '').trim();
  if (!raw) return null;
  if (raw.startsWith('{') || raw.startsWith('[')) {
    try {
      return jsonView(JSON.parse(raw));
    } catch {
      // JSON the server truncated at its preview limit — fall through to text.
    }
  }
  const lines = raw.split('\n')
    .map((l) => l.trim().replace(/^\d+\s+/, ''))
    .filter((l) => l.length >= 2);
  const first = lines[0] ?? raw.split('\n')[0].trim();
  const count = raw.split('\n').length;
  return { fields: [], flags: [], line: `${clip(first, 140)}${count > 1 ? ` · ${count}줄` : ''}` };
}
