'use client';

/**
 * Stage14EvaluateEditor — curated editor for s14_evaluate (loop
 * termination + budget enforcement).
 *
 * Stage 14 is special — its termination ceilings actually live on
 * pipeline.* (max_iterations, cost_budget_usd, context_window_budget),
 * NOT on stage.config. So this editor reaches into draft.pipeline via
 * patchPipeline(), with a clear explanation that these are pipeline-
 * level fields (so the user understands changes affect the whole
 * pipeline, not just stage 14).
 *
 * Strategy slots and stage-specific config (e.g. retry policy) still
 * live on the stage and are surfaced via the standard layout.
 */

import { useEffect, useState } from 'react';
import {
  AlertOctagon,
  ChevronDown,
  ChevronRight,
  Coins,
  Hash,
  Layers,
} from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { catalogApi } from '@/lib/environmentApi';
import { localizeIntrospection } from '../stage_locale';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type {
  StageIntrospection,
  StageManifestEntry,
} from '@/types/environment';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import {
  StrategiesEditor,
} from '@/components/environment/StrategyEditors';
import StageGenericEditor from '../StageGenericEditor';

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function Stage14EvaluateEditor({ order, entry }: Props) {
  const { t } = useI18n();
  const locale = useI18n((s) => s.locale);
  const draft = useEnvironmentDraftStore((s) => s.draft);
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);
  const patchPipeline = useEnvironmentDraftStore((s) => s.patchPipeline);

  const [intro, setIntro] = useState<StageIntrospection | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    catalogApi
      .stage(order)
      .then((res) => {
        if (!cancelled) setIntro(localizeIntrospection(res, locale));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [order, locale]);

  const pipeline = (draft?.pipeline ?? {}) as Record<string, unknown>;

  const maxIterations =
    typeof pipeline.max_iterations === 'number'
      ? (pipeline.max_iterations as number)
      : '';
  const costBudget =
    pipeline.cost_budget_usd === null || pipeline.cost_budget_usd === undefined
      ? ''
      : typeof pipeline.cost_budget_usd === 'number'
        ? (pipeline.cost_budget_usd as number)
        : '';
  const ctxWindow =
    typeof pipeline.context_window_budget === 'number'
      ? (pipeline.context_window_budget as number)
      : '';

  const setMaxIterations = (raw: string) => {
    if (raw === '') {
      const next = { ...pipeline };
      delete next.max_iterations;
      patchPipeline(next);
      return;
    }
    const n = Number(raw);
    if (isNaN(n) || n < 1) return;
    patchPipeline({ ...pipeline, max_iterations: n });
  };

  const setCostBudget = (raw: string) => {
    if (raw === '') {
      patchPipeline({ ...pipeline, cost_budget_usd: null });
      return;
    }
    const n = Number(raw);
    if (isNaN(n) || n < 0) return;
    patchPipeline({ ...pipeline, cost_budget_usd: n });
  };

  const setCtxWindow = (raw: string) => {
    if (raw === '') {
      const next = { ...pipeline };
      delete next.context_window_budget;
      patchPipeline(next);
      return;
    }
    const n = Number(raw);
    if (isNaN(n) || n < 1024) return;
    patchPipeline({ ...pipeline, context_window_budget: n });
  };

  return (
    <div className="flex flex-col gap-4">
      {/* ── Active ── */}
      <section className="flex items-center justify-between gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div>
          <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage14.activeTitle')}
          </div>
          <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage14.activeDesc')}
          </div>
        </div>
        <Switch
          checked={!!entry.active}
          onCheckedChange={(checked) => patchStage(order, { active: checked })}
        />
      </section>

      {/* ── Pipeline-level ceilings ── */}
      <section className="flex flex-col gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <header className="flex items-center gap-2">
          <AlertOctagon className="w-4 h-4 text-[hsl(var(--primary))]" />
          <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage14.budgetsTitle')}
          </h4>
          <span className="text-[0.625rem] uppercase tracking-wider px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-700 dark:text-amber-300">
            {t('envManagement.stage14.pipelineLevelBadge')}
          </span>
        </header>
        <p className="text-[0.7rem] text-[hsl(var(--muted-foreground))] leading-relaxed">
          {t('envManagement.stage14.budgetsHint')}
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* max_iterations */}
          <div className="flex flex-col gap-1">
            <label className="flex items-center gap-1 text-[0.75rem] font-medium text-[hsl(var(--foreground))]">
              <Hash className="w-3 h-3" />
              {t('envManagement.stage14.maxIterationsLabel')}
            </label>
            <Input
              type="number"
              min={1}
              value={maxIterations === '' ? '' : String(maxIterations)}
              onChange={(e) => setMaxIterations(e.target.value)}
              placeholder="50"
              className="h-7 font-mono text-[0.75rem]"
            />
            <p className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
              {t('envManagement.stage14.maxIterationsHint')}
            </p>
          </div>

          {/* cost_budget_usd */}
          <div className="flex flex-col gap-1">
            <label className="flex items-center gap-1 text-[0.75rem] font-medium text-[hsl(var(--foreground))]">
              <Coins className="w-3 h-3" />
              {t('envManagement.stage14.costBudgetLabel')}
            </label>
            <Input
              type="number"
              min={0}
              step={0.01}
              value={costBudget === '' ? '' : String(costBudget)}
              onChange={(e) => setCostBudget(e.target.value)}
              placeholder={t('envManagement.stage14.costBudgetPlaceholder')}
              className="h-7 font-mono text-[0.75rem]"
            />
            <p className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
              {t('envManagement.stage14.costBudgetHint')}
            </p>
          </div>

          {/* context_window_budget */}
          <div className="flex flex-col gap-1">
            <label className="flex items-center gap-1 text-[0.75rem] font-medium text-[hsl(var(--foreground))]">
              <Layers className="w-3 h-3" />
              {t('envManagement.stage14.ctxWindowLabel')}
            </label>
            <Input
              type="number"
              min={1024}
              value={ctxWindow === '' ? '' : String(ctxWindow)}
              onChange={(e) => setCtxWindow(e.target.value)}
              placeholder="200000"
              className="h-7 font-mono text-[0.75rem]"
            />
            <p className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
              {t('envManagement.stage14.ctxWindowHint')}
            </p>
          </div>
        </div>
      </section>

      {/* ── Strategy picker (convergence / retry) ── */}
      {intro && Object.keys(intro.strategy_slots).length > 0 && (
        <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
          <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage14.strategiesTitle')}
          </h4>
          <p className="text-[0.7rem] text-[hsl(var(--muted-foreground))] leading-relaxed">
            {t('envManagement.stage14.strategiesHint')}
          </p>
          <StrategiesEditor
            slots={intro.strategy_slots}
            strategies={entry.strategies || {}}
            strategyConfigs={entry.strategy_configs || {}}
            onChangeStrategies={(next) => patchStage(order, { strategies: next })}
            onChangeStrategyConfigs={(next) =>
              patchStage(order, { strategy_configs: next })
            }
          />
        </section>
      )}

      {/* ── Advanced ── */}
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
          {t('envManagement.stage14.advancedTitle')}
          <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage14.advancedHint')}
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
