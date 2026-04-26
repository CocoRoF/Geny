'use client';

/**
 * Observability dashboard (G11 + G15). Composes:
 * - TokenMeter (G11.2): running input / output / cache / cost
 * - StageGrid (G11.1): live 21-stage status + per-stage durations
 * - MutationLog (G11.3): scrollable PipelineMutator audit feed
 *   (clickable rows open MutationDiffViewer modal — G15)
 * - StageStrategyHeatmap (G15): per-stage strategy override map
 *
 * TokenMeter / StageGrid / MutationLog derive from the session's
 * logEntries (live WS stream). StageStrategyHeatmap pulls from
 * /api/agents/{id}/pipeline/introspect on mount.
 */

import { useAppStore } from '@/store/useAppStore';
import StageGrid from '@/components/dashboard/StageGrid';
import TokenMeter from '@/components/dashboard/TokenMeter';
import MutationLog from '@/components/dashboard/MutationLog';
import StageStrategyHeatmap from '@/components/dashboard/StageStrategyHeatmap';
import { LayoutDashboard } from 'lucide-react';
import { TabShell, EmptyState } from '@/components/layout';

export default function DashboardTab() {
  const selectedSessionId = useAppStore((s) => s.selectedSessionId);

  if (!selectedSessionId) {
    return (
      <TabShell title="Dashboard" icon={LayoutDashboard} subtitle="Per-session observability">
        <EmptyState
          icon={LayoutDashboard}
          title="No session selected"
          description="Select a session to view its observability dashboard."
        />
      </TabShell>
    );
  }

  return (
    <TabShell title="Dashboard" icon={LayoutDashboard} subtitle="Per-session observability">
      <div className="flex flex-col h-full overflow-hidden">
        <TokenMeter sessionId={selectedSessionId} />

        <div className="flex-1 overflow-auto">
          <section>
            <h3 className="text-[0.625rem] font-semibold text-[var(--text-muted)] uppercase tracking-wider px-3 pt-3">
              Stage execution
            </h3>
            <StageGrid sessionId={selectedSessionId} />
          </section>

          <section className="border-t border-[var(--border-color)] pt-2">
            <StageStrategyHeatmap sessionId={selectedSessionId} />
          </section>

          <section className="border-t border-[var(--border-color)]">
            <h3 className="text-[0.625rem] font-semibold text-[var(--text-muted)] uppercase tracking-wider px-3 pt-3">
              Pipeline mutations
            </h3>
            <MutationLog sessionId={selectedSessionId} />
          </section>
        </div>
      </div>
    </TabShell>
  );
}
