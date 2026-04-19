'use client';

/**
 * EnvironmentDiffModal — side-by-side comparison of two v2
 * EnvironmentManifests.
 *
 * Posts to `/api/environments/diff` (via `environmentApi.diff`) and
 * renders the three buckets the backend returns: `added`, `removed`,
 * `changed`. Paths are dot-segmented JSON pointers (e.g.
 * `stages[3].config.temperature`) — we render them verbatim since
 * the backend keeps them stable.
 */

import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeftRight, Minus, Pencil, Plus, X } from 'lucide-react';

import { environmentApi } from '@/lib/environmentApi';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { useI18n } from '@/lib/i18n';
import type { EnvironmentDiffResult } from '@/types/environment';

interface Props {
  onClose: () => void;
  initialLeft?: string;
  initialRight?: string;
}

function formatValue(v: unknown): string {
  if (v === null) return 'null';
  if (v === undefined) return '—';
  if (typeof v === 'string') return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

export default function EnvironmentDiffModal({ onClose, initialLeft, initialRight }: Props) {
  const { environments, loadEnvironments } = useEnvironmentStore();
  const { t } = useI18n();

  const [leftId, setLeftId] = useState(initialLeft || '');
  const [rightId, setRightId] = useState(initialRight || '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<EnvironmentDiffResult | null>(null);

  useEffect(() => {
    if (environments.length === 0) {
      loadEnvironments();
    }
  }, [environments.length, loadEnvironments]);

  const canRun = !!leftId && !!rightId && leftId !== rightId && !loading;

  const runDiff = async () => {
    if (!canRun) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await environmentApi.diff(leftId, rightId);
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('diff.failed'));
    } finally {
      setLoading(false);
    }
  };

  const swap = () => {
    setLeftId(rightId);
    setRightId(leftId);
  };

  const leftName = useMemo(
    () => environments.find(e => e.id === leftId)?.name || leftId,
    [environments, leftId],
  );
  const rightName = useMemo(
    () => environments.find(e => e.id === rightId)?.name || rightId,
    [environments, rightId],
  );

  if (typeof document === 'undefined') return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-xl shadow-[var(--shadow-lg)] w-full max-w-[880px] max-h-[88vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 py-3 px-5 border-b border-[var(--border-color)] shrink-0">
          <div className="flex flex-col gap-0.5">
            <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">
              {t('diff.title')}
            </h3>
            <p className="text-[0.75rem] text-[var(--text-muted)]">
              {t('diff.subtitle')}
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-md bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer shrink-0"
          >
            <X size={16} />
          </button>
        </div>

        {/* Picker row */}
        <div className="px-5 py-3 border-b border-[var(--border-color)] flex items-end gap-2">
          <div className="flex-1 min-w-0 flex flex-col gap-1">
            <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
              {t('diff.left')}
            </label>
            <select
              value={leftId}
              onChange={e => setLeftId(e.target.value)}
              className="py-1.5 px-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.8125rem] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)] cursor-pointer"
            >
              <option value="">{t('diff.pickEnv')}</option>
              {environments.map(env => (
                <option key={env.id} value={env.id}>
                  {env.name}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={swap}
            disabled={!leftId || !rightId}
            className="w-8 h-8 mb-0.5 flex items-center justify-center rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            aria-label="swap sides"
          >
            <ArrowLeftRight size={14} />
          </button>
          <div className="flex-1 min-w-0 flex flex-col gap-1">
            <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
              {t('diff.right')}
            </label>
            <select
              value={rightId}
              onChange={e => setRightId(e.target.value)}
              className="py-1.5 px-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.8125rem] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)] cursor-pointer"
            >
              <option value="">{t('diff.pickEnv')}</option>
              {environments.map(env => (
                <option key={env.id} value={env.id}>
                  {env.name}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={runDiff}
            disabled={!canRun}
            className="py-1.5 px-4 mb-0.5 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-semibold cursor-pointer border-none transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? t('diff.running') : t('diff.compare')}
          </button>
        </div>

        {/* Result body */}
        <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4">
          {error && (
            <div className="mb-3 px-3 py-2 rounded-md bg-[rgba(239,68,68,0.1)] border border-[rgba(239,68,68,0.3)] text-[0.8125rem] text-[var(--danger-color)]">
              {error}
            </div>
          )}

          {loading && (
            <div className="text-[0.875rem] text-[var(--text-muted)] italic py-8 text-center">
              {t('diff.running')}
            </div>
          )}

          {!loading && !result && !error && (
            <div className="text-[0.875rem] text-[var(--text-muted)] py-8 text-center">
              {t('diff.idle')}
            </div>
          )}

          {result && !loading && (
            <div className="flex flex-col gap-4">
              {/* Header row */}
              <div className="flex items-center gap-2 text-[0.75rem] text-[var(--text-muted)]">
                <span className="font-medium text-[var(--text-secondary)] truncate">
                  {leftName}
                </span>
                <ArrowLeftRight size={12} className="shrink-0" />
                <span className="font-medium text-[var(--text-secondary)] truncate">
                  {rightName}
                </span>
              </div>

              {/* Unchanged state */}
              {result.added.length === 0 &&
                result.removed.length === 0 &&
                result.changed.length === 0 && (
                  <div className="text-[0.8125rem] text-[var(--success-color)] py-6 text-center">
                    {t('diff.noChanges')}
                  </div>
                )}

              {/* Added */}
              {result.added.length > 0 && (
                <section className="flex flex-col gap-1.5">
                  <h4 className="flex items-center gap-1.5 text-[0.75rem] font-semibold text-[var(--success-color)] uppercase tracking-wide">
                    <Plus size={12} />
                    {t('diff.added')} ({result.added.length})
                  </h4>
                  <ul className="flex flex-col gap-0.5">
                    {result.added.map(path => (
                      <li
                        key={path}
                        className="px-2.5 py-1 rounded-md bg-[rgba(34,197,94,0.08)] border border-[rgba(34,197,94,0.2)] text-[0.75rem] font-mono text-[var(--text-primary)]"
                      >
                        {path}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {/* Removed */}
              {result.removed.length > 0 && (
                <section className="flex flex-col gap-1.5">
                  <h4 className="flex items-center gap-1.5 text-[0.75rem] font-semibold text-[var(--danger-color)] uppercase tracking-wide">
                    <Minus size={12} />
                    {t('diff.removed')} ({result.removed.length})
                  </h4>
                  <ul className="flex flex-col gap-0.5">
                    {result.removed.map(path => (
                      <li
                        key={path}
                        className="px-2.5 py-1 rounded-md bg-[rgba(239,68,68,0.08)] border border-[rgba(239,68,68,0.2)] text-[0.75rem] font-mono text-[var(--text-primary)]"
                      >
                        {path}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {/* Changed */}
              {result.changed.length > 0 && (
                <section className="flex flex-col gap-1.5">
                  <h4 className="flex items-center gap-1.5 text-[0.75rem] font-semibold text-[var(--primary-color)] uppercase tracking-wide">
                    <Pencil size={12} />
                    {t('diff.changed')} ({result.changed.length})
                  </h4>
                  <ul className="flex flex-col gap-2">
                    {result.changed.map((entry, idx) => (
                      <li
                        key={`${entry.path}-${idx}`}
                        className="p-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] flex flex-col gap-1.5"
                      >
                        <div className="text-[0.75rem] font-mono text-[var(--text-primary)] break-all">
                          {entry.path}
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          <div className="flex flex-col gap-0.5">
                            <span className="text-[0.625rem] text-[var(--text-muted)] uppercase">
                              {t('diff.before')}
                            </span>
                            <pre className="text-[0.6875rem] leading-[1.5] font-mono text-[var(--text-secondary)] bg-[rgba(239,68,68,0.06)] border border-[rgba(239,68,68,0.2)] rounded p-1.5 whitespace-pre-wrap break-all">
                              {formatValue(entry.before)}
                            </pre>
                          </div>
                          <div className="flex flex-col gap-0.5">
                            <span className="text-[0.625rem] text-[var(--text-muted)] uppercase">
                              {t('diff.after')}
                            </span>
                            <pre className="text-[0.6875rem] leading-[1.5] font-mono text-[var(--text-secondary)] bg-[rgba(34,197,94,0.06)] border border-[rgba(34,197,94,0.2)] rounded p-1.5 whitespace-pre-wrap break-all">
                              {formatValue(entry.after)}
                            </pre>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="py-2.5 px-5 border-t border-[var(--border-color)] shrink-0 flex justify-end">
          <button
            onClick={onClose}
            className="py-1.5 px-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
          >
            {t('common.close')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
