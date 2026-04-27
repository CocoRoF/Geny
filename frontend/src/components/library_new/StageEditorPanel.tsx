'use client';

/**
 * StageEditorPanel — slide-in side panel that hosts the per-stage
 * editor for the currently-selected stage.
 *
 * Routes to a curated editor when one exists for the stage order;
 * otherwise falls back to StageGenericEditor. PR-A ships only the
 * generic editor — curated editors land in PR-B…PR-E.
 *
 * The panel is always rendered (not animated in/out) when a stage is
 * selected so React state inside the editor survives re-clicks.
 */

import { X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { getStageMetaByOrder, getCategoryColor } from '@/components/session-env/stageMetadata';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import StageGenericEditor from './StageGenericEditor';
import Stage06ApiEditor from './stages/Stage06ApiEditor';
import Stage18MemoryEditor from './stages/Stage18MemoryEditor';

// Routing table — order → curated editor component. Anything not in
// this map falls back to StageGenericEditor.
const CURATED_EDITORS: Record<
  number,
  React.ComponentType<{ order: number; entry: import('@/types/environment').StageManifestEntry }>
> = {
  6: Stage06ApiEditor,
  18: Stage18MemoryEditor,
};

interface Props {
  order: number | null;
  onClose: () => void;
}

export default function StageEditorPanel({ order, onClose }: Props) {
  const locale = useI18n((s) => s.locale);
  const { t } = useI18n();
  const draft = useEnvironmentDraftStore((s) => s.draft);

  if (order == null || !draft) return null;

  const meta = getStageMetaByOrder(order, locale);
  const entry = draft.stages.find((s) => s.order === order);

  if (!entry) {
    // Should not happen — newDraft seeds all 21 stages — but guard.
    return (
      <aside className="w-[440px] shrink-0 border-l border-[hsl(var(--border))] bg-[hsl(var(--background))] flex flex-col">
        <header className="flex items-center justify-between px-4 py-3 border-b border-[hsl(var(--border))]">
          <h3 className="text-[0.875rem] font-semibold">
            Stage {order}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
            aria-label="close"
          >
            <X className="w-4 h-4" />
          </button>
        </header>
        <div className="p-4 text-[0.8125rem] text-[hsl(var(--muted-foreground))]">
          {t('libraryNewTab.stageMissing')}
        </div>
      </aside>
    );
  }

  const categoryColor = meta ? getCategoryColor(meta.category) : null;

  return (
    <aside className="w-[440px] shrink-0 border-l border-[hsl(var(--border))] bg-[hsl(var(--background))] flex flex-col h-full min-h-0">
      <header className="px-4 py-3 border-b border-[hsl(var(--border))] shrink-0 bg-[hsl(var(--card))]">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span
                className="inline-flex items-center justify-center w-7 h-7 rounded-full text-[0.6875rem] font-bold tabular-nums shrink-0"
                style={{
                  background: categoryColor?.bg ?? 'hsl(var(--accent))',
                  color: categoryColor?.accent ?? 'hsl(var(--foreground))',
                  border: `1px solid ${categoryColor?.border ?? 'hsl(var(--border))'}`,
                }}
              >
                {order}
              </span>
              <h3 className="text-[0.9375rem] font-semibold text-[hsl(var(--foreground))] truncate">
                {meta?.displayName ?? entry.name}
              </h3>
              {meta?.categoryLabel && (
                <span
                  className="text-[0.625rem] uppercase tracking-wider px-1.5 py-0.5 rounded shrink-0"
                  style={{
                    background: categoryColor?.bg ?? 'transparent',
                    color: categoryColor?.accent ?? 'hsl(var(--muted-foreground))',
                  }}
                >
                  {meta.categoryLabel}
                </span>
              )}
            </div>
            {meta?.description && (
              <p className="text-[0.75rem] text-[hsl(var(--muted-foreground))] mt-1 leading-relaxed">
                {meta.description}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] p-1 -m-1"
            aria-label="close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {(() => {
          const Curated = CURATED_EDITORS[order];
          if (Curated) return <Curated order={order} entry={entry} />;
          return <StageGenericEditor order={order} entry={entry} />;
        })()}

        {meta?.detailedDescription && (
          <details className="mt-6 text-[0.75rem] text-[hsl(var(--muted-foreground))]">
            <summary className="cursor-pointer font-medium">
              {t('libraryNewTab.aboutThisStage')}
            </summary>
            <p className="mt-2 leading-relaxed whitespace-pre-wrap">
              {meta.detailedDescription}
            </p>
            {meta.technicalBehavior && meta.technicalBehavior.length > 0 && (
              <ul className="mt-2 ml-4 list-disc space-y-1">
                {meta.technicalBehavior.map((tb, i) => (
                  <li key={i}>{tb}</li>
                ))}
              </ul>
            )}
          </details>
        )}
      </div>
    </aside>
  );
}
