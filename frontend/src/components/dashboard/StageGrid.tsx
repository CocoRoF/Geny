'use client';

/**
 * Live stage execution grid (G11.1).
 *
 * Renders the 21-stage layout as a grid; each cell shows whether the
 * stage entered/exited in the current iteration plus the duration of
 * the last execution. Subscribes to the session's logEntries (filtered
 * to STAGE level) so the grid updates as events stream in via WS.
 *
 * Read-only snapshot per render — the parent decides which session id
 * to feed.
 */

import { useMemo } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { getStageMetaByOrder } from '@/components/session-env/stageMetadata';
import { useI18n } from '@/lib/i18n';
import type { LogEntry, LogEntryMetadata } from '@/types';

interface StageState {
  order: number;
  status: 'idle' | 'running' | 'done' | 'error';
  lastDurationMs: number | null;
  iteration: number;
}

function buildStageStates(entries: LogEntry[]): Map<number, StageState> {
  const out = new Map<number, StageState>();
  for (let i = 1; i <= 21; i++) {
    out.set(i, { order: i, status: 'idle', lastDurationMs: null, iteration: 0 });
  }
  let lastEnterAt: Map<number, number> = new Map();
  for (const entry of entries) {
    if (entry.level !== 'STAGE') continue;
    const meta = entry.metadata as LogEntryMetadata | undefined;
    const order = meta?.stage_order;
    if (typeof order !== 'number') continue;
    const cell = out.get(order);
    if (!cell) continue;
    const ts = new Date(entry.timestamp).getTime();
    const evt = meta?.event_type;
    if (evt === 'stage_enter') {
      cell.status = 'running';
      lastEnterAt.set(order, ts);
      if (typeof meta?.iteration === 'number') cell.iteration = meta.iteration;
    } else if (evt === 'stage_exit') {
      cell.status = 'done';
      const enterTs = lastEnterAt.get(order);
      if (enterTs != null) cell.lastDurationMs = ts - enterTs;
    } else if (evt === 'stage_error') {
      cell.status = 'error';
    }
  }
  return out;
}

function formatDur(ms: number | null): string {
  if (ms == null) return '—';
  if (ms < 100) return `${ms}ms`;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

const STATUS_COLOR: Record<string, string> = {
  idle: 'rgba(148,163,184,0.10)',
  running: 'rgba(59,130,246,0.22)',
  done: 'rgba(16,185,129,0.18)',
  error: 'rgba(239,68,68,0.22)',
};

const STATUS_BORDER: Record<string, string> = {
  idle: 'var(--border-color)',
  running: 'var(--primary-color)',
  done: 'var(--success-color)',
  error: 'var(--danger-color)',
};

interface Props {
  sessionId: string;
}

export default function StageGrid({ sessionId }: Props) {
  const locale = useI18n((s) => s.locale);
  const cache = useAppStore((s) => s.sessionDataCache[sessionId]);
  const entries = useMemo(() => (cache?.logEntries || []) as LogEntry[], [cache?.logEntries]);
  const states = useMemo(() => buildStageStates(entries), [entries]);

  return (
    <div className="grid grid-cols-7 gap-1.5 p-3">
      {Array.from(states.values()).map((cell) => {
        const meta = getStageMetaByOrder(cell.order, locale);
        return (
          <div
            key={cell.order}
            className="rounded-md border px-2 py-1.5 flex flex-col gap-0.5"
            style={{
              backgroundColor: STATUS_COLOR[cell.status],
              borderColor: STATUS_BORDER[cell.status],
            }}
            title={`${meta?.displayName ?? `Stage ${cell.order}`} — ${cell.status}${cell.iteration ? ` · iter ${cell.iteration}` : ''}`}
          >
            <div className="flex items-center justify-between text-[0.5625rem] font-mono opacity-70">
              <span>{cell.order.toString().padStart(2, '0')}</span>
              <span>{formatDur(cell.lastDurationMs)}</span>
            </div>
            <div
              className="text-[0.625rem] font-medium truncate"
              style={{ color: 'var(--text-primary)' }}
            >
              {meta?.displayName ?? '—'}
            </div>
          </div>
        );
      })}
    </div>
  );
}
