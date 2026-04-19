'use client';

/**
 * EnvironmentDiffMatrixModal — pairwise diff summary across 3+
 * environments.
 *
 * Given a selection of N env ids, posts all (i < j) pairs in a single
 * `/api/environments/diff-bulk` round-trip and renders an N×N grid
 * where each upper-triangle cell shows the per-pair summary
 * (`+A / -R / ~C` or `=` for byte-identical manifests). Clicking a cell
 * hands the pair to the existing `EnvironmentDiffModal` for a full diff
 * view — the matrix stays in a "single pair opened" state underneath.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeftRight, Check, Clipboard, Download, Loader2, X } from 'lucide-react';

import { environmentApi } from '@/lib/environmentApi';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { useI18n } from '@/lib/i18n';
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

function cellKey(a: string, b: string): CellKey {
  return `${a}|${b}`;
}

export default function EnvironmentDiffMatrixModal({ envIds, onClose }: Props) {
  const { environments } = useEnvironmentStore();
  const { t } = useI18n();

  const [cells, setCells] = useState<Record<CellKey, CellState>>({});
  const [pair, setPair] = useState<{ left: string; right: string } | null>(null);
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle');
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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
    const pending: Record<CellKey, CellState> = {};
    for (const { a, b } of pairs) pending[cellKey(a, b)] = { status: 'pending' };
    setCells(pending);
    if (pairs.length === 0) return;
    (async () => {
      try {
        const res = await environmentApi.diffBulk({
          pairs: pairs.map(({ a, b }) => ({ env_id_a: a, env_id_b: b })),
        });
        if (cancelled) return;
        const next: Record<CellKey, CellState> = {};
        for (const r of res.results) {
          const key = cellKey(r.env_id_a, r.env_id_b);
          if (r.ok) {
            const s = r.summary ?? { added: 0, removed: 0, changed: 0 };
            next[key] = {
              status: 'ok',
              summary: { added: s.added, removed: s.removed, changed: s.changed },
            };
          } else {
            next[key] = { status: 'error', error: r.error ?? 'diff failed' };
          }
        }
        setCells(next);
      } catch (e: unknown) {
        if (cancelled) return;
        // Whole-request failure — mark every cell as errored so the UI
        // surfaces the reason rather than spinning forever.
        const next: Record<CellKey, CellState> = {};
        const msg = e instanceof Error ? e.message : 'diff-bulk failed';
        for (const { a, b } of pairs) {
          next[cellKey(a, b)] = { status: 'error', error: msg };
        }
        setCells(next);
      }
    })();
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

  const exportable = stats.pending === 0 && stats.total > 0;

  const downloadBlob = (body: BlobPart, mime: string, filename: string) => {
    const blob = new Blob([body], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const collectPairs = () =>
    pairs.map(({ a, b }) => {
      const cell = cells[cellKey(a, b)];
      if (cell?.status === 'ok') {
        const { added, removed, changed } = cell.summary;
        return {
          env_id_a: a,
          env_id_b: b,
          name_a: nameById.get(a) ?? null,
          name_b: nameById.get(b) ?? null,
          ok: true,
          identical: added === 0 && removed === 0 && changed === 0,
          summary: { added, removed, changed },
          error: null as string | null,
        };
      }
      return {
        env_id_a: a,
        env_id_b: b,
        name_a: nameById.get(a) ?? null,
        name_b: nameById.get(b) ?? null,
        ok: false,
        identical: false,
        summary: null,
        error: cell?.status === 'error' ? cell.error : 'pending',
      };
    });

  const exportMatrixJson = () => {
    if (!exportable) return;
    const stamp = new Date().toISOString();
    const payload = {
      version: '1',
      generated_at: stamp,
      envs: orderedIds.map(id => ({ id, name: nameById.get(id) ?? null })),
      summary: {
        pairs: pairs.length,
        ok: stats.done,
        failed: stats.failed,
      },
      pairs: collectPairs(),
    };
    const stampSlug = stamp.replace(/[:.]/g, '-');
    downloadBlob(
      JSON.stringify(payload, null, 2),
      'application/json',
      `env-diff-matrix-${orderedIds.length}-${stampSlug}.json`,
    );
  };

  const buildMatrixMarkdown = (stamp: string): string => {
    const lines: string[] = [];
    lines.push(`# Environment diff matrix`);
    lines.push('');
    lines.push(`- **Environments:** ${orderedIds.length}`);
    lines.push(`- **Pairs:** ${pairs.length} (ok ${stats.done} · failed ${stats.failed})`);
    lines.push(`- **Generated:** ${stamp}`);
    lines.push('');
    // Index table
    lines.push('## Environments');
    lines.push('');
    lines.push('| # | Name | Id |');
    lines.push('|---|------|----|');
    orderedIds.forEach((id, i) => {
      const name = nameById.get(id) ?? '—';
      lines.push(`| ${i + 1} | ${name} | \`${id}\` |`);
    });
    lines.push('');
    // Matrix table (symmetric, upper + lower filled with same data for
    // readability in GitHub). Cells = `+A/-R/~C` or `=` or `err`.
    lines.push('## Summary matrix');
    lines.push('');
    const header = ['', ...orderedIds.map((id, i) => `${i + 1}`)];
    lines.push(`| ${header.join(' | ')} |`);
    lines.push(`| ${header.map(() => '---').join(' | ')} |`);
    for (let i = 0; i < orderedIds.length; i += 1) {
      const row: string[] = [`${i + 1}`];
      for (let j = 0; j < orderedIds.length; j += 1) {
        if (i === j) {
          row.push('—');
          continue;
        }
        const [aIdx, bIdx] = i < j ? [i, j] : [j, i];
        const cell = cells[cellKey(orderedIds[aIdx], orderedIds[bIdx])];
        if (!cell || cell.status === 'pending') row.push('…');
        else if (cell.status === 'error') row.push('err');
        else {
          const { added, removed, changed } = cell.summary;
          row.push(
            added === 0 && removed === 0 && changed === 0
              ? '='
              : `+${added}/-${removed}/~${changed}`,
          );
        }
      }
      lines.push(`| ${row.join(' | ')} |`);
    }
    lines.push('');
    // Per-pair drill-down (upper triangle only, non-identical first).
    const nonIdentical = collectPairs().filter(
      p => p.ok && !p.identical,
    );
    if (nonIdentical.length > 0) {
      lines.push('## Non-identical pairs');
      lines.push('');
      for (const p of nonIdentical) {
        const s = p.summary!;
        lines.push(
          `- **${p.name_a ?? p.env_id_a}** ↔ **${p.name_b ?? p.env_id_b}** — +${s.added} / −${s.removed} / ~${s.changed}`,
        );
      }
      lines.push('');
    }
    const errored = collectPairs().filter(p => !p.ok);
    if (errored.length > 0) {
      lines.push('## Errored pairs');
      lines.push('');
      for (const p of errored) {
        lines.push(
          `- **${p.name_a ?? p.env_id_a}** ↔ **${p.name_b ?? p.env_id_b}** — \`${p.error ?? 'unknown'}\``,
        );
      }
      lines.push('');
    }
    return lines.join('\n');
  };

  const exportMatrixMarkdown = () => {
    if (!exportable) return;
    const stamp = new Date().toISOString();
    const body = buildMatrixMarkdown(stamp);
    const stampSlug = stamp.replace(/[:.]/g, '-');
    downloadBlob(
      body,
      'text/markdown',
      `env-diff-matrix-${orderedIds.length}-${stampSlug}.md`,
    );
  };

  const copyMatrixMarkdown = async () => {
    if (!exportable) return;
    const body = buildMatrixMarkdown(new Date().toISOString());
    try {
      if (!navigator?.clipboard?.writeText) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(body);
      setCopyStatus('copied');
    } catch {
      setCopyStatus('failed');
    }
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopyStatus('idle'), 1800);
  };

  useEffect(() => {
    return () => {
      if (copyTimer.current) clearTimeout(copyTimer.current);
    };
  }, []);

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
        <div className="py-2.5 px-5 border-t border-[var(--border-color)] shrink-0 flex items-center justify-between gap-2">
          <div className="text-[0.6875rem] text-[var(--text-muted)] flex-1 min-w-0 truncate">
            {t('diffMatrix.legend')}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {exportable && (
              <>
                <button
                  onClick={exportMatrixJson}
                  className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
                >
                  <Download size={12} />
                  {t('diffMatrix.exportJson')}
                </button>
                <button
                  onClick={exportMatrixMarkdown}
                  className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
                >
                  <Download size={12} />
                  {t('diffMatrix.exportMarkdown')}
                </button>
                <button
                  onClick={copyMatrixMarkdown}
                  className={`flex items-center gap-1.5 py-1.5 px-3 rounded-md border text-[0.75rem] font-medium cursor-pointer transition-colors ${
                    copyStatus === 'copied'
                      ? 'bg-[rgba(34,197,94,0.1)] border-[rgba(34,197,94,0.35)] text-[var(--success-color)]'
                      : copyStatus === 'failed'
                        ? 'bg-[rgba(239,68,68,0.1)] border-[rgba(239,68,68,0.35)] text-[var(--danger-color)]'
                        : 'bg-[var(--bg-primary)] border-[var(--border-color)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
                  }`}
                >
                  {copyStatus === 'copied' ? <Check size={12} /> : <Clipboard size={12} />}
                  {copyStatus === 'copied'
                    ? t('diffMatrix.copied')
                    : copyStatus === 'failed'
                      ? t('diffMatrix.copyFailed')
                      : t('diffMatrix.copyMarkdown')}
                </button>
              </>
            )}
            <button
              onClick={onClose}
              className="py-1.5 px-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
            >
              {t('common.close')}
            </button>
          </div>
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
