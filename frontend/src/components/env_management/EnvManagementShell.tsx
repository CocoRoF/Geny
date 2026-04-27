'use client';

/**
 * EnvManagementShell — visual 21-stage environment builder body.
 *
 * Hosted by /app/environments/page.tsx. The page wrapper owns the
 * route-level chrome (back link, page title, post-save navigation);
 * this shell owns the editor body itself.
 *
 * Cycle 20260427_2 PR-2 — canvas-first redesign:
 *
 *   ┌─ CompactMetaBar (52px) ─────────────────────────────┐
 *   │ name, tags, status, [⚙ Globals] [Discard] [Save]    │
 *   ├──────────────────────────────────────────────────────┤
 *   │ Mode A — overview:                                   │
 *   │   ┌──────────────────────────────────────────────┐   │
 *   │   │ Big PipelineCanvas (or StartFromPicker)      │   │
 *   │   └──────────────────────────────────────────────┘   │
 *   │                                                       │
 *   │ Mode B — stage detail:                               │
 *   │   StageProgressBar (68px, scrollable)                │
 *   │   ┌──────────────────────────────────────────────┐   │
 *   │   │ StageDetailView (curated/generic editor)     │   │
 *   │   └──────────────────────────────────────────────┘   │
 *   └──────────────────────────────────────────────────────┘
 *
 *   GlobalSettingsDrawer slides over from the right when ⚙ is clicked.
 *
 * Mode is internal state — overview ↔ stage detail. Clicking a stage
 * on the canvas opens its detail view; clicking back on the progress
 * bar returns to the canvas.
 */

import { useEffect, useMemo, useState } from 'react';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import CompactMetaBar from './CompactMetaBar';
import OverviewView from './OverviewView';
import StageProgressBar from './StageProgressBar';
import StageDetailView from './StageDetailView';
import GlobalSettingsDrawer from './GlobalSettingsDrawer';

export interface EnvManagementShellProps {
  /** Called after a successful Save with the new env id. The page
   *  wrapper decides where to send the user (back to /, into a
   *  detail drawer, etc.). */
  onSaved?: (newEnvId: string) => void;
}

type ViewMode = { mode: 'overview' } | { mode: 'stage'; order: number };

export default function EnvManagementShell({
  onSaved,
}: EnvManagementShellProps = {}) {
  const draft = useEnvironmentDraftStore((s) => s.draft);
  const isDirty = useEnvironmentDraftStore((s) => s.isDirty);
  const resetDraft = useEnvironmentDraftStore((s) => s.resetDraft);
  const stageDirty = useEnvironmentDraftStore((s) => s.stageDirty);

  const [view, setView] = useState<ViewMode>({ mode: 'overview' });
  const [globalsOpen, setGlobalsOpen] = useState(false);

  // beforeunload guard for browser tab close while dirty
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (isDirty()) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  // If the draft disappears (e.g. after save reset), bail back to
  // overview so we don't render stage view against null data.
  useEffect(() => {
    if (!draft && view.mode === 'stage') {
      setView({ mode: 'overview' });
    }
  }, [draft, view.mode]);

  const activeOrders = useMemo(() => {
    const set = new Set<number>();
    draft?.stages.forEach((s) => {
      if (s.active) set.add(s.order);
    });
    return set;
  }, [draft]);

  const handleSaved = (newEnvId: string) => {
    setView({ mode: 'overview' });
    setGlobalsOpen(false);
    resetDraft();
    onSaved?.(newEnvId);
  };

  return (
    <div className="flex flex-col h-full min-h-0 bg-[hsl(var(--background))]">
      <CompactMetaBar
        onSaved={handleSaved}
        onOpenGlobals={() => setGlobalsOpen(true)}
      />

      {view.mode === 'overview' && (
        <OverviewView
          onSelectStage={(order) => setView({ mode: 'stage', order })}
        />
      )}

      {view.mode === 'stage' && draft && (
        <>
          <StageProgressBar
            selectedOrder={view.order}
            onSelect={(order) => setView({ mode: 'stage', order })}
            onBack={() => setView({ mode: 'overview' })}
            dirtyOrders={stageDirty}
            activeOrders={activeOrders}
          />
          <StageDetailView order={view.order} />
        </>
      )}

      <GlobalSettingsDrawer
        open={globalsOpen}
        onClose={() => setGlobalsOpen(false)}
      />
    </div>
  );
}
