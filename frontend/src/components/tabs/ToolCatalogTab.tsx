'use client';

/**
 * ToolCatalogTab — viewer for executor's BUILT_IN_TOOL_CLASSES (PR-E.1.2).
 *
 * Surfaces every framework tool (Read / Write / Bash / AgentTool /
 * TaskCreate / etc — 33 tools) so operators can browse what's
 * available before deciding which to enable per preset.
 *
 * Layout:
 *   [Sidebar: feature groups]  [Card grid: tools in active group]  [Detail panel: selected tool]
 */

import { useEffect, useMemo, useState } from 'react';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';
import { frameworkToolApi, FrameworkToolDetail } from '@/lib/api';
import { RefreshCw, X } from 'lucide-react';

function cn(...c: (string | boolean | undefined | null)[]) {
  return twMerge(c.filter(Boolean).join(' '));
}

const ALL = '__all__';

// Capability badges — short labels for the card view.
const CAPABILITY_BADGES: Array<[keyof FrameworkToolDetail['capabilities'], string, string]> = [
  ['read_only', 'read-only', 'bg-green-100 text-green-800'],
  ['destructive', 'destructive', 'bg-red-100 text-red-800'],
  ['concurrency_safe', 'parallel', 'bg-blue-100 text-blue-800'],
  ['idempotent', 'idempotent', 'bg-purple-100 text-purple-800'],
  ['network_egress', 'network', 'bg-amber-100 text-amber-800'],
];

export function ToolCatalogTab() {
  const { t } = useI18n();
  const [tools, setTools] = useState<FrameworkToolDetail[]>([]);
  const [groups, setGroups] = useState<string[]>([]);
  const [activeGroup, setActiveGroup] = useState<string>(ALL);
  const [selected, setSelected] = useState<FrameworkToolDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await frameworkToolApi.list();
      setTools(res.tools);
      setGroups(res.groups);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const visible = useMemo(() => {
    if (activeGroup === ALL) return tools;
    return tools.filter((tt) => tt.feature_group === activeGroup);
  }, [tools, activeGroup]);

  // Sidebar entries with per-group counts
  const groupCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const tt of tools) {
      counts[tt.feature_group] = (counts[tt.feature_group] || 0) + 1;
    }
    return counts;
  }, [tools]);

  return (
    <div className="flex h-full min-h-0">
      {/* ── Sidebar ── */}
      <aside className="w-44 shrink-0 border-r border-[var(--border-color)] overflow-y-auto p-2">
        <div className="text-[0.625rem] uppercase tracking-wider text-[var(--text-muted)] font-semibold px-2 py-1">
          Groups
        </div>
        <button
          type="button"
          onClick={() => setActiveGroup(ALL)}
          className={cn(
            'w-full text-left px-2 py-1.5 rounded text-[0.8125rem] hover:bg-[var(--bg-tertiary)]',
            activeGroup === ALL && 'bg-[var(--bg-tertiary)] font-semibold',
          )}
        >
          All <span className="text-[var(--text-muted)] text-[0.6875rem]">({tools.length})</span>
        </button>
        {groups.map((g) => (
          <button
            key={g}
            type="button"
            onClick={() => setActiveGroup(g)}
            className={cn(
              'w-full text-left px-2 py-1.5 rounded text-[0.8125rem] hover:bg-[var(--bg-tertiary)]',
              activeGroup === g && 'bg-[var(--bg-tertiary)] font-semibold',
            )}
          >
            {g}{' '}
            <span className="text-[var(--text-muted)] text-[0.6875rem]">
              ({groupCounts[g] ?? 0})
            </span>
          </button>
        ))}
      </aside>

      {/* ── Card grid ── */}
      <main className="flex-1 min-w-0 overflow-y-auto p-4">
        <header className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold">Framework tools</h2>
            <p className="text-[0.75rem] text-[var(--text-muted)]">
              Built-in tools shipped with geny-executor.{' '}
              {activeGroup !== ALL && <span>· filter: {activeGroup}</span>}
            </p>
          </div>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-1 text-xs border rounded px-2 py-1 disabled:opacity-50"
          >
            <RefreshCw className={cn('w-3 h-3', loading && 'animate-spin')} />
            Refresh
          </button>
        </header>

        {error && (
          <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2 mb-3">
            {error}
          </div>
        )}

        {visible.length === 0 ? (
          <div className="text-sm text-[var(--text-muted)] text-center py-8">
            {loading ? 'Loading…' : 'No tools.'}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {visible.map((tt) => (
              <button
                key={tt.name}
                type="button"
                onClick={() => setSelected(tt)}
                className={cn(
                  'text-left border border-[var(--border-color)] rounded-md p-3 hover:border-[var(--primary-color)] hover:shadow-sm transition-all',
                  selected?.name === tt.name &&
                    'border-[var(--primary-color)] shadow-sm',
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono font-semibold text-[0.875rem]">
                    {tt.name}
                  </span>
                  <span className="text-[0.625rem] text-[var(--text-muted)] uppercase">
                    {tt.feature_group}
                  </span>
                </div>
                <div className="text-[0.75rem] text-[var(--text-secondary)] mt-1 line-clamp-2">
                  {tt.description || '—'}
                </div>
                <div className="flex flex-wrap gap-1 mt-2">
                  {CAPABILITY_BADGES.map(([key, label, cls]) =>
                    tt.capabilities[key] ? (
                      <span
                        key={String(key)}
                        className={cn(
                          'inline-block text-[0.5625rem] px-1.5 py-0.5 rounded',
                          cls,
                        )}
                      >
                        {label}
                      </span>
                    ) : null,
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </main>

      {/* ── Detail panel ── */}
      {selected && (
        <aside className="w-96 shrink-0 border-l border-[var(--border-color)] overflow-y-auto p-4">
          <header className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold font-mono">{selected.name}</h3>
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            >
              <X className="w-4 h-4" />
            </button>
          </header>

          <div className="text-[0.6875rem] text-[var(--text-muted)] uppercase tracking-wider mb-1">
            Group
          </div>
          <div className="text-[0.8125rem] mb-3">{selected.feature_group}</div>

          <div className="text-[0.6875rem] text-[var(--text-muted)] uppercase tracking-wider mb-1">
            Description
          </div>
          <div className="text-[0.8125rem] mb-3 whitespace-pre-wrap">
            {selected.description || '—'}
          </div>

          <div className="text-[0.6875rem] text-[var(--text-muted)] uppercase tracking-wider mb-1">
            Capabilities
          </div>
          <div className="flex flex-wrap gap-1 mb-3">
            {Object.entries(selected.capabilities).map(([k, v]) => (
              <span
                key={k}
                className="text-[0.625rem] px-1.5 py-0.5 rounded bg-[var(--bg-tertiary)] font-mono"
              >
                {k}: {String(v)}
              </span>
            ))}
            {Object.keys(selected.capabilities).length === 0 && (
              <span className="text-[var(--text-muted)] text-[0.75rem]">—</span>
            )}
          </div>

          <div className="text-[0.6875rem] text-[var(--text-muted)] uppercase tracking-wider mb-1">
            Input schema
          </div>
          <pre className="text-[0.625rem] font-mono bg-[var(--bg-tertiary)] rounded p-2 overflow-x-auto">
            {JSON.stringify(selected.input_schema, null, 2)}
          </pre>
        </aside>
      )}
    </div>
  );
}

export default ToolCatalogTab;
