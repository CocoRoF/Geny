'use client';

/**
 * Stage strategy heatmap (G15).
 *
 * 21-cell grid (mirrors StageGrid). Each cell shows whether the stage's
 * strategy slots are bound to non-default impls. The legend:
 *   - solid green tint  → at least one slot has a non-default override
 *   - faded base tone   → all slots are on their default strategies
 *   - hatched red       → introspection couldn't reach the stage (FAIL)
 *
 * Tooltip on hover: per-slot active impl name.
 */

import { useEffect, useState } from 'react';
import { agentApi } from '@/lib/api';
import { getStageMetaByOrder } from '@/components/session-env/stageMetadata';
import { useI18n } from '@/lib/i18n';
import { Layers } from 'lucide-react';

interface StageRow {
  order: number;
  name: string;
  artifact: string;
  strategy_slots: Record<string, { active: string | null; registered: string[] }>;
  strategy_chains: Record<string, { items: string[]; registered: string[] }>;
}

const DEFAULT_IMPL_NAMES = new Set([
  'default', 'null', 'no_persist', 'no_summary', 'no_scorer', 'standard',
  'passthrough', 'append_only', 'static', 'sequential',
]);

function isOverridden(row: StageRow): boolean {
  for (const [, slot] of Object.entries(row.strategy_slots)) {
    if (!slot.active) continue;
    if (!DEFAULT_IMPL_NAMES.has(slot.active)) return true;
  }
  for (const [, chain] of Object.entries(row.strategy_chains)) {
    if (chain.items.length > 0) return true;
  }
  return false;
}

interface Props {
  sessionId: string;
}

export default function StageStrategyHeatmap({ sessionId }: Props) {
  const locale = useI18n((s) => s.locale);
  const [rows, setRows] = useState<StageRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    agentApi.pipelineIntrospect(sessionId)
      .then((resp) => { if (!cancelled) setRows(resp.stages); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)); });
    return () => { cancelled = true; };
  }, [sessionId]);

  const byOrder = new Map(rows.map((r) => [r.order, r]));

  return (
    <div className="px-3 pb-3">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-[0.625rem] uppercase tracking-wider font-semibold text-[var(--text-muted)] flex items-center gap-1.5">
          <Layers size={11} className="text-[var(--primary-color)]" />
          Strategy overrides
        </h4>
        <div className="flex items-center gap-2 text-[0.5625rem] text-[var(--text-muted)]">
          <span className="inline-flex items-center gap-1">
            <span className="w-2 h-2 rounded bg-[rgba(16,185,129,0.45)]" /> override
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="w-2 h-2 rounded bg-[rgba(148,163,184,0.18)]" /> default
          </span>
        </div>
      </div>

      {error && (
        <div className="text-[0.6875rem] text-[var(--danger-color)] py-2">{error}</div>
      )}

      <div className="grid grid-cols-7 gap-1">
        {Array.from({ length: 21 }).map((_, idx) => {
          const order = idx + 1;
          const row = byOrder.get(order);
          const meta = getStageMetaByOrder(order, locale);
          const overridden = row ? isOverridden(row) : false;
          const tooltip = row
            ? Object.entries(row.strategy_slots)
                .map(([name, slot]) => `${name}: ${slot.active ?? '—'}`)
                .join('\n')
            : 'not registered';
          return (
            <div
              key={order}
              className="rounded-md border px-1.5 py-1 text-center"
              style={{
                backgroundColor: row
                  ? overridden
                    ? 'rgba(16,185,129,0.45)'
                    : 'rgba(148,163,184,0.18)'
                  : 'rgba(239,68,68,0.10)',
                borderColor: 'var(--border-color)',
              }}
              title={tooltip}
            >
              <div className="text-[0.5625rem] font-mono opacity-70">{order.toString().padStart(2, '0')}</div>
              <div className="text-[0.625rem] font-medium truncate" style={{ color: 'var(--text-primary)' }}>
                {meta?.displayName ?? '—'}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
