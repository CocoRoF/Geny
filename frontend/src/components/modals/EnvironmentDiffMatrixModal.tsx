'use client';

/**
 * EnvironmentDiffMatrixModal — pairwise diff summary across 3+
 * environments.
 *
 * Given a selection of N env ids, runs `environmentApi.diff(a, b)` for
 * every (i < j) pair with bounded concurrency and renders an N×N grid
 * where each upper-triangle cell shows the per-pair summary
 * (`+A / -R / ~C` or `—` for identical). Clicking a cell hands the pair
 * to the existing `EnvironmentDiffModal` for a full diff view — the
 * matrix stays in a "single pair opened" state underneath.
 *
 * Backend work is one `/api/environments/diff` call per pair. With N
 * envs that is N·(N-1)/2 calls, capped by `CONCURRENCY` = 4 in-flight
 * so a 10-env matrix (45 pairs) settles in a handful of batches without
 * clobbering the server.
 */

import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeftRight, Loader2, X } from 'lucide-react';

import { environmentApi } from '@/lib/environmentApi';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { useI18n } from '@/lib/i18n';
import type { EnvironmentDiffResult } from '@/types/environment';
import EnvironmentDiffModal from '@/components/modals/EnvironmentDiffModal';

interface Props {
  envIds: string[];
  onClose: () => void;
}

type CellKey = string; // `${leftId}|${rightId}`

type CellState =
  | { status: 'pending' }
  | { status: 'ok'; summary: { added: number; removed: number; changed: number } }
  | { status: 'error'; error: string };

const CONCURRENCY = 4;

function cellKey(a: string, b: string): CellKey {
  return `${a}|${b}`;
}

async function runWithConcurrency<T>(
  tasks: Array<() => Promise<T>>,
  limit: number,
): Promise<void> {
  let cursor = 0;
  const workers = Array.from({ length: Math.min(limit, tasks.length) }, async () => {
    while (cursor < tasks.length) {
      const idx = cursor;
      cursor += 1;
      const task = tasks[idx];
      if (!task) return;
      try {
        await task();
      } catch {
        // Per-task handlers own their own errors — this catch is just to
        // keep the worker alive for remaining tasks.
      }
    }
  });
  await Promise.all(workers);
}

function summarize(r: EnvironmentDiffResult) {
  return {
    added: r.added.length,
    removed: r.removed.length,
    changed: r.changed.length,
  };
}

export default function EnvironmentDiffMatrixModal({ envIds, onClose }: Props) {
  const { environments } = useEnvironmentStore();
  const { t } = useI18n();

  const [cells, setCells] = useState<Record<CellKey, CellState>>({});
  const [pair, setPair] = useState<{ left: string; right: string } | null>(null);

  const orderedIds = useMemo(() => envIds.filter(Boolean), [envIds]);
  const nameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const env of environments) map.set(env.id, env.name);
    return map;
  }, [environments]);

  const pairs = useMemo(() => {
    const out: Array<{ a: string; b: string }> = [];
    for (let i = 0; i < orderedIds.length; i += 1) {
      for (let j = i + 1; j < orderedIds.length; j += 1) {
        out.push({ a: orderedIds[i], b: orderedIds[j] });
      }
    }
    return out;
  }, [orderedIds]);

  useEffect(() => {
    let cancelled = false;
    setCells(() => {
      const next: Record<CellKey, CellState> = {};
      for (const { a, b } of pairs) next[cellKey(a, b)] = { status: 'pending' };
      return next;
    });
    const tasks = pairs.map(({ a, b }) => async () => {
      try {
        const res = await environmentApi.diff(a, b);
        if (cancelled) return;
        setCells(prev => ({
          ...prev,
          [cellKey(a, b)]: { status: 'ok', summary: summarize(res) },
        }));
      } catch (e: unknown) {
        if (cancelled) return;
        setCells(prev => ({
          ...prev,
          [cellKey(a, b)]: {
            status: 'error',
            error: e instanceof Error ? e.message : 'diff failed',
          },
        }));
      }
    });
    void runWithConcurrency(tasks, CONCURRENCY);
    return () => {
      cancelled = true;
    };
  }, [pairs]);

  const stats = useMemo(() => {
    let pending = 0;
    let done = 0;
    let failed = 0;
    for (const cell of Object.values(cells)) {
      if (cell.status === 'pending') pending += 1;
      else if (cell.status === 'ok') done += 1;
      else failed += 1;
    }
    return { pending, done, failed, total: pending + done + failed };
  }, [cells]);

  const renderCell = (rowIdx: number, colIdx: number) => {
    if (rowIdx === colIdx) {
      return (
        <div className="w-full h-full flex items-center justify-center text-[var(--text-muted)] text-[0.75rem]">
          —
        </div>
      );
    }
    const [aIdx, bIdx] = rowIdx < colIdx ? [rowIdx, colIdx] : [colIdx, rowIdx];
    const a = orderedIds[aIdx];
    const b = orderedIds[bIdx];
    const cell = cells[cellKey(a, b)];
    const upperTriangle = rowIdx < colIdx;

    if (!cell || cell.status === 'pending') {
      return (
        <div className="w-full h-full flex items-center justify-center text-[var(--text-muted)]">
          <Loader2 size={12} className="animate-spin" />
        </div>
      );
    }
    if (cell.status === 'error') {
      return (
        <div
          title={cell.error}
          className="w-full h-full flex items-center justify-center text-[var(--danger-color)] text-[0.6875rem] font-mono"
        >
          err
        </div>
      );
    }
    const { added, removed, changed } = cell.summary;
    const identical = added === 0 && removed === 0 && changed === 0;
    if (!upperTriangle) {
      // Lower-triangle is a visual mirror with softer color so the eye
      // understands it's the same pair and not new data.
      return (
        <div className="w-full h-full flex items-center justify-center text-[var(--text-muted)] text-[0.6875rem] font-mono opacity-60">
          {identical ? '=' : `+${added}/-${removed}/~${changed}`}
        </div>
      );
    }
    return (
      <button
        type="button"
        onClick={() => setPair({ left: a, right: b })}
        title={t('diffMatrix.cellTooltip', {
          left: nameById.get(a) ?? a,
          right: nameById.get(b) ?? b,
        })}
        className={`w-full h-full flex items-center justify-center text-[0.6875rem] font-mono cursor-pointer bg-transparent border-none transition-colors ${
          identical
            ? 'text-[var(--success-color)] hover:bg-[rgba(34,197,94,0.08)]'
            : 'text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
        }`}
      >
        {identical ? '=' : `+${added}/-${removed}/~${changed}`}
      </button>
    );
  };

  if (typeof document === 'undefined') return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-xl shadow-[var(--shadow-lg)] w-full max-w-[960px] max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 py-3 px-5 border-b border-[var(--border-color)] shrink-0">
          <div className="flex flex-col gap-0.5">
            <h3 className="flex items-center gap-2 text-[1rem] font-semibold text-[var(--text-primary)]">
              <ArrowLeftRight size={14} />
              {t('diffMatrix.title', { n: String(orderedIds.length) })}
            </h3>
            <p className="text-[0.75rem] text-[var(--text-muted)]">
              {t('diffMatrix.subtitle', {
                pairs: String(pairs.length),
                done: String(stats.done),
                failed: String(stats.failed),
              })}
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-md bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer shrink-0"
          >
            <X size={16} />
          </button>
        </div>

        {/* Matrix body */}
        <div className="flex-1 min-h-0 overflow-auto px-5 py-4">
          {orderedIds.length < 2 ? (
            <div className="text-[0.8125rem] text-[var(--text-muted)] italic py-6 text-center">
              {t('diffMatrix.tooFew')}
            </div>
          ) : (
            <div
              className="inline-grid gap-px bg-[var(--border-color)] rounded-md overflow-hidden"
              style={{
                gridTemplateColumns: `minmax(120px, 200px) repeat(${orderedIds.length}, minmax(72px, 110px))`,
              }}
            >
              {/* Top-left empty corner */}
              <div className="bg-[var(--bg-primary)] px-2 py-1.5 text-[0.625rem] text-[var(--text-muted)] uppercase tracking-wide">
                {t('diffMatrix.cornerLabel')}
              </div>
              {/* Column headers */}
              {orderedIds.map(id => (
                <div
                  key={`col-${id}`}
                  title={id}
                  className="bg-[var(--bg-primary)] px-2 py-1.5 text-[0.6875rem] font-medium text-[var(--text-secondary)] truncate"
                >
                  {nameById.get(id) ?? id}
                </div>
              ))}
              {/* Rows */}
              {orderedIds.map((rowId, rowIdx) => (
                <RowFragment
                  key={`row-${rowId}`}
                  rowLabel={nameById.get(rowId) ?? rowId}
                  rowId={rowId}
                  rowIdx={rowIdx}
                  cols={orderedIds.length}
                  renderCell={renderCell}
                />
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="py-2.5 px-5 border-t border-[var(--border-color)] shrink-0 flex items-center justify-between">
          <div className="text-[0.6875rem] text-[var(--text-muted)]">
            {t('diffMatrix.legend')}
          </div>
          <button
            onClick={onClose}
            className="py-1.5 px-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
          >
            {t('common.close')}
          </button>
        </div>
      </div>

      {pair && (
        <EnvironmentDiffModal
          initialLeft={pair.left}
          initialRight={pair.right}
          onClose={() => setPair(null)}
        />
      )}
    </div>,
    document.body,
  );
}

function RowFragment({
  rowLabel,
  rowId,
  rowIdx,
  cols,
  renderCell,
}: {
  rowLabel: string;
  rowId: string;
  rowIdx: number;
  cols: number;
  renderCell: (rowIdx: number, colIdx: number) => React.ReactNode;
}) {
  return (
    <>
      <div
        title={rowId}
        className="bg-[var(--bg-primary)] px-2 py-1.5 text-[0.6875rem] font-medium text-[var(--text-secondary)] truncate sticky left-0"
      >
        {rowLabel}
      </div>
      {Array.from({ length: cols }).map((_, colIdx) => (
        <div
          key={`cell-${rowIdx}-${colIdx}`}
          className="bg-[var(--bg-secondary)] h-8 flex items-center justify-center"
        >
          {renderCell(rowIdx, colIdx)}
        </div>
      ))}
    </>
  );
}
