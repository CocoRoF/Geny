'use client';

/**
 * Stage06ApiEditor — curated editor for s06_api (the LLM caller).
 *
 * The single most-edited stage: pick the model + sampling. Hides the
 * raw artifact / strategy / config controls behind a "고급 설정"
 * disclosure since 99% of users only touch model_override.
 *
 * model_override semantics:
 *   - null → use pipeline.model (the default)
 *   - object → ModelConfig for THIS stage only; nullable per-key (any
 *     unset key falls back to pipeline.model for that key)
 *
 * Save flow: edits go straight to draft.stages[6].model_override via
 * patchStage(6, { model_override: ... }).
 */

import { useState } from 'react';
import { Cpu, ChevronDown, ChevronRight, Sparkles } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type { StageManifestEntry, StageModelOverride } from '@/types/environment';
import { ModelConfigEditor } from '@/components/builder/ModelConfigEditor';
import { Switch } from '@/components/ui/switch';
import StageGenericEditor from '../StageGenericEditor';

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function Stage06ApiEditor({ order, entry }: Props) {
  const { t } = useI18n();
  const draft = useEnvironmentDraftStore((s) => s.draft);
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);

  const [advancedOpen, setAdvancedOpen] = useState(false);

  const overrideOn = entry.model_override !== null && entry.model_override !== undefined;
  const pipelineModel = (draft?.model ?? {}) as Record<string, unknown>;

  const toggleOverride = (next: boolean) => {
    if (next) {
      // Seed with the pipeline defaults so the user starts from
      // something that works rather than an empty form. They can
      // override any subset.
      patchStage(order, {
        model_override: { ...pipelineModel } as unknown as StageModelOverride,
      });
    } else {
      patchStage(order, { model_override: null });
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* ── Active ── */}
      <section className="flex items-center justify-between gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div>
          <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage06.activeTitle')}
          </div>
          <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage06.activeDesc')}
          </div>
        </div>
        <Switch
          checked={!!entry.active}
          onCheckedChange={(checked) => patchStage(order, { active: checked })}
        />
      </section>

      {/* ── Model override ── */}
      <section className="flex flex-col gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Cpu className="w-4 h-4 text-[hsl(var(--primary))]" />
            <div>
              <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
                {t('envManagement.stage06.modelTitle')}
              </div>
              <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
                {overrideOn
                  ? t('envManagement.stage06.overrideOnDesc')
                  : t('envManagement.stage06.overrideOffDesc', {
                      model:
                        (pipelineModel.model as string | undefined) ??
                        '(default)',
                    })}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
              {overrideOn
                ? t('envManagement.stage06.overrideToggleOn')
                : t('envManagement.stage06.overrideToggleOff')}
            </span>
            <Switch checked={overrideOn} onCheckedChange={toggleOverride} />
          </div>
        </div>

        {overrideOn && (
          <div className="border-t border-[hsl(var(--border))] pt-3">
            <ModelConfigEditor
              initial={(entry.model_override as Record<string, unknown>) ?? {}}
              saving={false}
              error={null}
              onSave={(changes) => {
                const next = {
                  ...((entry.model_override as Record<string, unknown>) ?? {}),
                  ...changes,
                };
                // StageModelOverride has explicit fields (model: string?,
                // ...) plus a [key: string]: unknown index signature.
                // Record<string, unknown> only provides the index-sig view
                // of properties so TS can't prove e.g. `model` is a string.
                // Cast through unknown — the runtime shape matches the
                // executor's Dict[str, Any] contract.
                patchStage(order, {
                  model_override: next as unknown as StageModelOverride,
                });
              }}
              onClearError={() => {}}
            />
          </div>
        )}

        {!overrideOn && (
          <div className="border-t border-[hsl(var(--border))] pt-3 flex items-start gap-2 text-[0.7rem] text-[hsl(var(--muted-foreground))]">
            <Sparkles className="w-3.5 h-3.5 mt-0.5 text-[hsl(var(--primary))] shrink-0" />
            <span>{t('envManagement.stage06.useDefaultHint')}</span>
          </div>
        )}
      </section>

      {/* ── Advanced (artifact / strategies / chains / config) ── */}
      <section className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          className="w-full flex items-center gap-2 px-3 py-2 text-[0.8125rem] font-semibold text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors text-left"
        >
          {advancedOpen ? (
            <ChevronDown className="w-3.5 h-3.5" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5" />
          )}
          {t('envManagement.stage06.advancedTitle')}
          <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage06.advancedHint')}
          </span>
        </button>
        {advancedOpen && (
          <div className="px-3 pb-3 border-t border-[hsl(var(--border))] pt-3">
            <StageGenericEditor order={order} entry={entry} />
          </div>
        )}
      </section>
    </div>
  );
}
