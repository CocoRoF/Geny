'use client';

/**
 * Token / cost meter (G11.2).
 *
 * Aggregates token + cost from STAGE log entries that carry
 * ``token.usage`` data and renders a running totals strip + budget
 * gauge. Pure derivation off the existing logEntries array — no
 * extra WS subscription needed beyond what CommandTab already does.
 */

import { useMemo } from 'react';
import { useAppStore } from '@/store/useAppStore';
import type { LogEntry, LogEntryMetadata } from '@/types';
import { Coins, Zap, Activity } from 'lucide-react';

interface Totals {
  inputTokens: number;
  outputTokens: number;
  cacheCreation: number;
  cacheRead: number;
  costUsd: number;
}

function aggregate(entries: LogEntry[]): Totals {
  const out: Totals = {
    inputTokens: 0, outputTokens: 0,
    cacheCreation: 0, cacheRead: 0, costUsd: 0,
  };
  for (const entry of entries) {
    const meta = entry.metadata as LogEntryMetadata | undefined;
    const data = (meta?.data || {}) as Record<string, unknown>;
    const evt = meta?.event_type;
    if (evt !== 'token.usage' && evt !== 'token_usage') continue;
    out.inputTokens += Number(data.input_tokens || 0);
    out.outputTokens += Number(data.output_tokens || 0);
    out.cacheCreation += Number(data.cache_creation || data.cache_creation_tokens || 0);
    out.cacheRead += Number(data.cache_read || data.cache_read_tokens || 0);
    out.costUsd += Number(data.cost_usd || data.total_cost_usd || 0);
  }
  return out;
}

function fmt(n: number): string {
  if (n < 1000) return n.toString();
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}K`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

interface Props {
  sessionId: string;
  /** Optional cost ceiling. When set, the meter renders a percentage gauge. */
  costBudgetUsd?: number;
}

export default function TokenMeter({ sessionId, costBudgetUsd }: Props) {
  const cache = useAppStore((s) => s.sessionDataCache[sessionId]);
  const entries = useMemo(() => (cache?.logEntries || []) as LogEntry[], [cache?.logEntries]);
  const totals = useMemo(() => aggregate(entries), [entries]);

  const costPct = costBudgetUsd && costBudgetUsd > 0
    ? Math.min(100, (totals.costUsd / costBudgetUsd) * 100)
    : null;
  const costColor = costPct == null
    ? 'var(--text-secondary)'
    : costPct < 50
      ? 'var(--success-color)'
      : costPct < 80
        ? 'var(--warning-color)'
        : 'var(--danger-color)';

  return (
    <div className="flex items-stretch gap-2 px-3 py-2 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
      <div className="flex items-center gap-1.5 px-2 py-1 rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)]">
        <Activity size={11} className="text-[var(--primary-color)]" />
        <span className="text-[0.625rem] uppercase font-bold tracking-wider text-[var(--text-muted)]">in</span>
        <span className="text-[0.75rem] font-mono text-[var(--text-primary)]">{fmt(totals.inputTokens)}</span>
      </div>
      <div className="flex items-center gap-1.5 px-2 py-1 rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)]">
        <Activity size={11} className="text-[var(--primary-color)] rotate-180" />
        <span className="text-[0.625rem] uppercase font-bold tracking-wider text-[var(--text-muted)]">out</span>
        <span className="text-[0.75rem] font-mono text-[var(--text-primary)]">{fmt(totals.outputTokens)}</span>
      </div>
      <div className="flex items-center gap-1.5 px-2 py-1 rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)]">
        <Zap size={11} className="text-[var(--success-color)]" />
        <span className="text-[0.625rem] uppercase font-bold tracking-wider text-[var(--text-muted)]">cache</span>
        <span className="text-[0.75rem] font-mono text-[var(--text-primary)]">
          {fmt(totals.cacheRead)} / {fmt(totals.cacheCreation)}
        </span>
      </div>
      <div
        className="flex items-center gap-1.5 px-2 py-1 rounded-md border bg-[var(--bg-tertiary)]"
        style={{ borderColor: costColor }}
      >
        <Coins size={11} style={{ color: costColor }} />
        <span className="text-[0.625rem] uppercase font-bold tracking-wider text-[var(--text-muted)]">cost</span>
        <span className="text-[0.75rem] font-mono" style={{ color: costColor }}>
          ${totals.costUsd.toFixed(4)}
          {costPct != null && (
            <span className="ml-1 text-[0.5625rem] opacity-70">({costPct.toFixed(0)}%)</span>
          )}
        </span>
      </div>
    </div>
  );
}
