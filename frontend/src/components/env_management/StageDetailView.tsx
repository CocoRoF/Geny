'use client';

/**
 * StageDetailView — full-width body for the "stage detail" view mode
 * (cycle 20260427_2 PR-2).
 *
 * Replaces the old StageEditorPanel side panel. Same routing table
 * (curated editor per order, generic fallback) but rendered as the
 * primary body content with a roomier reading column instead of a
 * cramped 440px-wide drawer.
 *
 * Header here is intentionally minimal (just the stage's category +
 * description) because the StageProgressBar above already shows which
 * stage is selected.
 */

import { useState } from 'react';
import { Info } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useTheme } from '@/lib/theme';
import { getStageMetaByOrder } from '@/components/session-env/stageMetadata';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import StageGenericEditor from './StageGenericEditor';
import StageInfoModal from './stage_info/StageInfoModal';
import Stage01InputEditor from './stages/Stage01InputEditor';
import Stage06ApiEditor from './stages/Stage06ApiEditor';
import Stage10ToolsEditor from './stages/Stage10ToolsEditor';
import Stage11ToolReviewEditor from './stages/Stage11ToolReviewEditor';
import Stage14EvaluateEditor from './stages/Stage14EvaluateEditor';
import Stage15HitlEditor from './stages/Stage15HitlEditor';
import Stage18MemoryEditor from './stages/Stage18MemoryEditor';

// Theme-aware palette mirroring StageProgressBar so the detail-view
// header circle reads the same as the navigator circle for the same
// stage. Active = subtle emerald, idle = neutral outline.
const HEADER_PALETTE = {
  light: {
    activeBg: 'rgb(220 252 231)', // emerald-100
    activeFg: 'rgb(4 120 87)', // emerald-700
    activeBorder: 'rgb(16 185 129)', // emerald-500
    badgeBg: 'rgb(220 252 231)',
    badgeFg: 'rgb(4 120 87)',
  },
  dark: {
    activeBg: 'rgb(6 78 59 / 0.45)', // emerald-900 @ 45%
    activeFg: 'rgb(110 231 183)', // emerald-300
    activeBorder: 'rgb(52 211 153)', // emerald-400
    badgeBg: 'rgb(6 78 59 / 0.4)',
    badgeFg: 'rgb(110 231 183)',
  },
} as const;

const CURATED_EDITORS: Record<
  number,
  React.ComponentType<{ order: number; entry: import('@/types/environment').StageManifestEntry }>
> = {
  1: Stage01InputEditor,
  6: Stage06ApiEditor,
  10: Stage10ToolsEditor,
  11: Stage11ToolReviewEditor,
  14: Stage14EvaluateEditor,
  15: Stage15HitlEditor,
  18: Stage18MemoryEditor,
};

export interface StageDetailViewProps {
  order: number;
}

export default function StageDetailView({ order }: StageDetailViewProps) {
  const locale = useI18n((s) => s.locale);
  const { t } = useI18n();
  const { theme } = useTheme();
  const palette = HEADER_PALETTE[theme === 'dark' ? 'dark' : 'light'];
  const draft = useEnvironmentDraftStore((s) => s.draft);
  const [infoOpen, setInfoOpen] = useState(false);

  if (!draft) return null;

  const meta = getStageMetaByOrder(order, locale);
  const entry = draft.stages.find((s) => s.order === order);

  if (!entry) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-[0.875rem] text-[hsl(var(--muted-foreground))]">
        {t('envManagement.stageMissing')}
      </div>
    );
  }

  const Curated = CURATED_EDITORS[order];
  const Editor = Curated ?? StageGenericEditor;
  const isActive = !!entry.active;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-[hsl(var(--background))]">
      <div className="max-w-[840px] mx-auto p-6 flex flex-col gap-6">
        {/* ── Stage header ── */}
        <header className="flex items-center gap-3">
          {/* Stage number circle — outlined, matches StageProgressBar
              circle style. Active stages get the emerald palette;
              inactive stages stay neutral so the user can tell at a
              glance whether the stage is enabled in the manifest. */}
          <span
            className="inline-flex items-center justify-center w-12 h-12 rounded-full text-[1rem] font-bold tabular-nums shrink-0"
            style={
              isActive
                ? {
                    background: palette.activeBg,
                    color: palette.activeFg,
                    border: `2px solid ${palette.activeBorder}`,
                    boxShadow:
                      '0 1px 4px -1px rgb(16 185 129 / 0.18)',
                  }
                : {
                    background: 'hsl(var(--background))',
                    color: 'hsl(var(--muted-foreground))',
                    border: '2px solid hsl(var(--border))',
                  }
            }
          >
            {order}
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-[1.125rem] font-semibold text-[hsl(var(--foreground))]">
                {meta?.displayName ?? entry.name}
              </h2>
              {meta?.categoryLabel && (
                <span
                  className="text-[0.625rem] uppercase tracking-wider px-1.5 py-0.5 rounded font-medium"
                  style={{
                    background: isActive ? palette.badgeBg : 'hsl(var(--accent))',
                    color: isActive ? palette.badgeFg : 'hsl(var(--muted-foreground))',
                  }}
                >
                  {meta.categoryLabel}
                </span>
              )}
              <code className="text-[0.6875rem] font-mono text-[hsl(var(--muted-foreground))] opacity-70">
                {entry.name}
              </code>
            </div>
            {meta?.description && (
              <p className="text-[0.8125rem] text-[hsl(var(--muted-foreground))] mt-1 leading-relaxed">
                {meta.description}
              </p>
            )}
          </div>

          {/* Detail button — opens the rich info modal. */}
          <button
            type="button"
            onClick={() => setInfoOpen(true)}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[0.75rem] font-medium text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--primary))] hover:border-[hsl(var(--primary)/0.4)] hover:bg-[hsl(var(--accent))] transition-colors shrink-0 self-start"
            title={t('envManagement.info.openTip')}
          >
            <Info className="w-3.5 h-3.5" />
            {t('envManagement.info.openLabel')}
          </button>
        </header>

        {/* ── Editor body ── */}
        <Editor order={order} entry={entry} />

        {/* The old inline "About this stage" <details> was moved into
            the StageInfoModal which the Detail button (header right)
            opens. Keeps the editor body focused on configuration. */}
      </div>

      <StageInfoModal
        open={infoOpen}
        onClose={() => setInfoOpen(false)}
        order={order}
      />
    </div>
  );
}
