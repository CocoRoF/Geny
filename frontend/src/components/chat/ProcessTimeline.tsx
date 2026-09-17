'use client';

/**
 * What the agent did, on the web — the same timeline the desktop app draws.
 *
 * Both render from `shared/chat/tool-view`, so a tool call is described
 * identically in both places and neither recognises a vendor by name. Before
 * this, the web showed the raw log: `TOOL Bash 🔧 Bash` in a monospace dump
 * behind an "N steps" toggle, which is the log, not an account of the work.
 *
 * The shape is XGen Dex's: a pill while closed, and open, a rail of numbered
 * nodes — one per sentence the agent said before acting — each with its tool
 * rows beside it, colour-badged by kind, duration on the right, and the
 * result drawn in whatever shape it actually has.
 */

import { useState } from 'react';
import {
  Check, AlertTriangle, ChevronDown, ChevronRight,
  Terminal, Package, Search, FileText, PenLine, Globe, List, Wrench,
} from 'lucide-react';

import {
  describeTool, resultView, type ResultView, type ToolIcon,
} from '@/shared/chat/tool-view';

/** One call, as the web receives it in an agent's log. */
export interface TimelineCall {
  key: string;
  name: string;
  /** JSON string or object — the model parses either. */
  input?: unknown;
  result?: string;
  ok?: boolean | null;
  durationMs?: number;
  /** What the agent said it was doing when it called this. */
  step?: string;
}

const BADGE: Record<ToolIcon, React.ReactNode> = {
  terminal: <Terminal size={14} />,
  package: <Package size={14} />,
  search: <Search size={14} />,
  file: <FileText size={14} />,
  edit: <PenLine size={14} />,
  web: <Globe size={14} />,
  list: <List size={14} />,
  external: <Wrench size={14} />,
};

/** Tailwind is not available for these — the tints are the Dex ones. */
const BADGE_STYLE: Record<ToolIcon, React.CSSProperties> = {
  terminal: { color: '#334155', background: 'rgba(51, 65, 85, 0.1)' },
  package: { color: '#b45309', background: 'rgba(245, 158, 11, 0.14)' },
  search: { color: '#7c3aed', background: 'rgba(124, 58, 237, 0.11)' },
  file: { color: '#2563eb', background: 'rgba(37, 99, 235, 0.11)' },
  edit: { color: '#0f766e', background: 'rgba(13, 148, 136, 0.12)' },
  web: { color: '#0e7490', background: 'rgba(8, 145, 178, 0.12)' },
  list: { color: '#7c3aed', background: 'rgba(124, 58, 237, 0.11)' },
  external: { color: '#fff', background: 'linear-gradient(90deg, #305eeb 0%, #783ced 100%)' },
};

function seconds(ms?: number): string {
  if (typeof ms !== 'number' || ms <= 0) return '';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}초` : `${ms}ms`;
}

function Result({ view }: { view: ResultView }) {
  if (view.table) {
    return (
      <div className="overflow-x-auto">
        <table className="text-[0.6875rem] border-collapse">
          <thead>
            <tr>
              {view.table.columns.map((c) => (
                <th key={c} className="pr-3 py-0.5 text-left font-semibold text-[var(--text-muted)]">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.table.rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j} className="pr-3 py-0.5 text-[var(--text-secondary)] max-w-[220px] truncate">{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {view.table.more > 0 && (
          <div className="text-[0.625rem] text-[var(--text-muted)]">외 {view.table.more}건</div>
        )}
      </div>
    );
  }
  if (view.title || view.fields.length || view.flags.length) {
    return (
      <div className="flex flex-col gap-0.5">
        {view.title && (
          <div className="text-[0.75rem] font-semibold text-[var(--text-secondary)]">{view.title}</div>
        )}
        {(view.fields.length > 0 || view.flags.length > 0) && (
          <div className="flex flex-wrap gap-x-2.5 gap-y-1 text-[0.6875rem] text-[var(--text-muted)]">
            {view.fields.map(([k, v]) => (
              <span key={k}><i className="not-italic opacity-75">{k}</i> {v}</span>
            ))}
            {view.flags.map(([k, v]) => (
              <span key={k} className={v ? 'text-emerald-500' : 'text-rose-500'}>
                {v ? '✓' : '✗'} {k}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }
  return view.line ? (
    <div className="font-mono text-[0.6875rem] text-[var(--text-muted)] truncate">{view.line}</div>
  ) : null;
}

function ToolRow({ call }: { call: TimelineCall }) {
  const [open, setOpen] = useState(false);
  const { icon, text } = describeTool(call.name, call.input);
  const view = resultView(call.result);
  const failed = call.ok === false;
  const running = call.ok === null || call.ok === undefined;
  const dur = seconds(call.durationMs);
  const slow = (call.durationMs ?? 0) > 5000;
  const openable = Boolean(call.input || call.result);

  return (
    <div
      className="border-t border-[var(--border-color)] first:border-t-0"
      style={running ? { background: 'rgba(48, 94, 235, 0.06)' } : undefined}
    >
      <button
        type="button"
        disabled={!openable}
        onClick={() => setOpen((v) => !v)}
        className="flex items-start gap-2.5 w-full px-3 py-2 bg-transparent border-none text-left cursor-pointer disabled:cursor-default hover:bg-[var(--bg-hover)]"
      >
        <span
          className="shrink-0 w-[26px] h-[26px] rounded-lg grid place-items-center"
          style={BADGE_STYLE[icon]}
        >
          {BADGE[icon]}
        </span>
        <span className="flex-1 min-w-0 flex flex-col gap-0.5">
          <span className={`text-[0.8125rem] truncate ${failed ? 'text-rose-500' : 'text-[var(--text-primary)]'}`}>
            {text}
          </span>
          {view && <Result view={view} />}
        </span>
        {dur && (
          <span
            className={`shrink-0 font-mono text-[0.6875rem] leading-[18px] px-2 rounded-full ${
              failed ? 'text-rose-500 bg-rose-500/10'
                : slow ? 'text-amber-600 bg-amber-500/10'
                  : 'text-[var(--text-muted)] bg-[var(--bg-tertiary)]'
            }`}
          >
            {dur}
          </span>
        )}
      </button>
      {open && (
        <div className="px-3 pb-3 pl-[48px] flex flex-col gap-1">
          {call.input !== undefined && call.input !== null && (
            <>
              <div className="text-[0.625rem] font-bold tracking-wider uppercase text-[var(--text-muted)]">넣은 값</div>
              <pre className="m-0 max-h-[240px] overflow-auto p-2 rounded-md bg-[var(--bg-tertiary)] font-mono text-[0.6875rem] whitespace-pre-wrap break-words text-[var(--text-secondary)]">
                {typeof call.input === 'string' ? call.input : JSON.stringify(call.input, null, 2)}
              </pre>
            </>
          )}
          {call.result && (
            <>
              <div className="text-[0.625rem] font-bold tracking-wider uppercase text-[var(--text-muted)]">돌려받은 값</div>
              <pre className="m-0 max-h-[240px] overflow-auto p-2 rounded-md bg-[var(--bg-tertiary)] font-mono text-[0.6875rem] whitespace-pre-wrap break-words text-[var(--text-secondary)]">
                {call.result}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** Calls → steps: a call that arrived with a sentence in front of it opens a
 *  new step, and the calls after it belong to the same one. */
function intoSteps(calls: TimelineCall[]): { title?: string; rows: TimelineCall[] }[] {
  const steps: { title?: string; rows: TimelineCall[] }[] = [];
  for (const row of calls) {
    const last = steps[steps.length - 1];
    if (row.step || !last) steps.push({ title: row.step, rows: [row] });
    else last.rows.push(row);
  }
  return steps;
}

export function ProcessTimeline({ calls, live = false }: { calls: TimelineCall[]; live?: boolean }) {
  const [manual, setManual] = useState<boolean | null>(null);
  const open = manual ?? live;
  if (calls.length === 0) return null;

  const failed = calls.filter((c) => c.ok === false).length;
  const total = calls.reduce((sum, c) => sum + (c.durationMs ?? 0), 0);
  const summary = [
    `도구 ${calls.length}회`,
    failed ? `실패 ${failed}` : '',
    seconds(total),
  ].filter(Boolean).join(' · ');

  return (
    <div className="mt-1.5">
      <button
        type="button"
        onClick={() => setManual(!open)}
        aria-expanded={open}
        className="inline-flex items-center gap-2 pl-1.5 pr-3 py-1 rounded-full border border-[var(--border-color)] bg-[var(--bg-tertiary)] hover:border-[var(--primary-color)]/40 cursor-pointer text-[0.8125rem]"
      >
        <span
          className="w-[18px] h-[18px] rounded-full grid place-items-center shrink-0"
          style={failed
            ? { color: '#e03131', background: 'rgba(224, 49, 49, 0.14)' }
            : { color: '#2eb146', background: 'rgba(46, 177, 70, 0.14)' }}
        >
          {failed ? <AlertTriangle size={11} /> : <Check size={11} />}
        </span>
        <span className="font-semibold text-[var(--text-primary)]">작업 과정</span>
        <span className="text-[var(--text-muted)] tabular-nums">{summary}</span>
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>

      {open && (
        <div className="mt-3">
          {intoSteps(calls).map((step, index) => {
            const phase = step.rows.some((r) => r.ok === null || r.ok === undefined) ? 'run'
              : step.rows.some((r) => r.ok === false) ? 'err'
                : 'ok';
            return (
              <div key={step.rows[0].key} className="relative pl-8 pb-3.5">
                {index < intoSteps(calls).length - 1 && (
                  <span className="absolute left-[10px] top-6 bottom-0.5 w-0.5 rounded bg-[var(--border-color)]" />
                )}
                <span
                  className="absolute left-0 top-0 w-[22px] h-[22px] rounded-full grid place-items-center text-[0.6875rem] font-bold tabular-nums border-[1.5px]"
                  style={phase === 'ok'
                    ? { color: '#2eb146', background: 'rgba(46, 177, 70, 0.14)', borderColor: 'transparent' }
                    : phase === 'err'
                      ? { color: '#e03131', background: 'rgba(224, 49, 49, 0.08)', borderColor: 'rgba(224,49,49,0.35)' }
                      : { color: '#305eeb', background: 'rgba(48, 94, 235, 0.1)', borderColor: 'rgba(48,94,235,0.25)' }}
                >
                  {phase === 'ok' ? <Check size={12} /> : phase === 'err' ? '!' : index + 1}
                </span>
                {step.title && (
                  <div className="text-[0.84rem] leading-[22px] text-[var(--text-primary)]">{step.title}</div>
                )}
                <div className="mt-1.5 rounded-xl border border-[var(--border-color)] bg-[var(--bg-secondary)] overflow-hidden">
                  {step.rows.map((row) => <ToolRow key={row.key} call={row} />)}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default ProcessTimeline;
