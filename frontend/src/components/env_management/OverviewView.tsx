'use client';

/**
 * OverviewView — the canvas-first first-page view (cycle 20260427_2 PR-2).
 *
 * Two states:
 *   - draft === null  → centered StartFromPicker card
 *   - draft !== null  → big PipelineCanvas + a "click any stage to
 *                       configure it" hint pill at the bottom
 *
 * Picking a stage on the canvas hands off to the parent's onSelectStage,
 * which switches the shell to the "stage" view mode.
 */

import { MousePointerClick, Sparkles } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import PipelineCanvas from '@/components/session-env/PipelineCanvas';
import StartFromPicker from './StartFromPicker';

export interface OverviewViewProps {
  onSelectStage: (order: number) => void;
}

export default function OverviewView({ onSelectStage }: OverviewViewProps) {
  const { t } = useI18n();
  const draft = useEnvironmentDraftStore((s) => s.draft);
  const stageDirty = useEnvironmentDraftStore((s) => s.stageDirty);

  // ── Empty state — no draft yet
  if (!draft) {
    return (
      <div className="flex-1 min-h-0 overflow-y-auto bg-[hsl(var(--background))]">
        <div className="max-w-[920px] mx-auto px-6 py-12 flex flex-col gap-6">
          <div className="text-center">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-[hsl(var(--primary)/0.1)] mb-4">
              <Sparkles className="w-7 h-7 text-[hsl(var(--primary))]" />
            </div>
            <h2 className="text-[1.5rem] font-semibold text-[hsl(var(--foreground))]">
              {t('envManagement.welcomeTitle')}
            </h2>
            <p className="text-[0.875rem] text-[hsl(var(--muted-foreground))] mt-2 max-w-[640px] mx-auto leading-relaxed">
              {t('envManagement.welcomeDescription')}
            </p>
          </div>
          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-5">
            <StartFromPicker />
          </div>
        </div>
      </div>
    );
  }

  // ── Draft active — big canvas
  // The .stage-circle class + --pipe-* CSS variables are scoped under
  // .pipeline-scope in globals.css; without that wrapper the stage
  // nodes render as bare numbers + labels (no circles, no colour, no
  // grid). Mirror the wrapper used by SessionEnvironmentTab.
  return (
    <div className="pipeline-scope flex-1 min-h-0 flex flex-col bg-[hsl(var(--background))] relative">
      <PipelineCanvas
        stages={draft.stages}
        selectedOrder={null}
        onSelectStage={(order) => {
          if (order != null) onSelectStage(order);
        }}
        dirtyOrders={stageDirty}
      />
      {/* Bottom hint pill — gentle nudge that stages are clickable */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-[hsl(var(--card))]/95 backdrop-blur border border-[hsl(var(--border))] shadow-md text-[0.7rem] text-[hsl(var(--muted-foreground))] pointer-events-none">
        <MousePointerClick className="w-3 h-3 text-[hsl(var(--primary))]" />
        {t('envManagement.canvasHint')}
      </div>
    </div>
  );
}
