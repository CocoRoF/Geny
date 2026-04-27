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

import { useI18n } from '@/lib/i18n';
import {
  getStageMetaByOrder,
  getCategoryColor,
} from '@/components/session-env/stageMetadata';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import StageGenericEditor from './StageGenericEditor';
import Stage01InputEditor from './stages/Stage01InputEditor';
import Stage06ApiEditor from './stages/Stage06ApiEditor';
import Stage10ToolsEditor from './stages/Stage10ToolsEditor';
import Stage11ToolReviewEditor from './stages/Stage11ToolReviewEditor';
import Stage14EvaluateEditor from './stages/Stage14EvaluateEditor';
import Stage15HitlEditor from './stages/Stage15HitlEditor';
import Stage18MemoryEditor from './stages/Stage18MemoryEditor';

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
  const draft = useEnvironmentDraftStore((s) => s.draft);

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

  const categoryColor = meta ? getCategoryColor(meta.category) : null;
  const Curated = CURATED_EDITORS[order];
  const Editor = Curated ?? StageGenericEditor;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-[hsl(var(--background))]">
      <div className="max-w-[840px] mx-auto p-6 flex flex-col gap-6">
        {/* ── Stage header ── */}
        <header className="flex items-start gap-3">
          <span
            className="inline-flex items-center justify-center w-12 h-12 rounded-2xl text-[0.9375rem] font-bold tabular-nums shrink-0"
            style={{
              background: categoryColor?.bg ?? 'hsl(var(--accent))',
              color: categoryColor?.accent ?? 'hsl(var(--foreground))',
              border: `2px solid ${categoryColor?.accent ?? 'hsl(var(--border))'}`,
            }}
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
                    background: categoryColor?.bg ?? 'transparent',
                    color: categoryColor?.accent ?? 'hsl(var(--muted-foreground))',
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
        </header>

        {/* ── Editor body ── */}
        <Editor order={order} entry={entry} />

        {/* ── About this stage (collapsed) ── */}
        {meta?.detailedDescription && (
          <details className="text-[0.8125rem] text-[hsl(var(--muted-foreground))] border border-[hsl(var(--border))] rounded-lg p-3 bg-[hsl(var(--card))]">
            <summary className="cursor-pointer font-medium text-[hsl(var(--foreground))]">
              {t('envManagement.aboutThisStage')}
            </summary>
            <p className="mt-2 leading-relaxed whitespace-pre-wrap">
              {meta.detailedDescription}
            </p>
            {meta.technicalBehavior && meta.technicalBehavior.length > 0 && (
              <ul className="mt-3 ml-4 list-disc space-y-1">
                {meta.technicalBehavior.map((tb, i) => (
                  <li key={i}>{tb}</li>
                ))}
              </ul>
            )}
          </details>
        )}
      </div>
    </div>
  );
}
