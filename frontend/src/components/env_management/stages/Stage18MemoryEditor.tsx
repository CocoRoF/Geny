'use client';

/**
 * Stage18MemoryEditor — curated editor for s18_memory.
 *
 * Memory is two orthogonal slot picks (strategy + persistence) plus an
 * optional model_override (only meaningful for reflective strategies).
 * The catalog backend tells us the exact strategy names + per-strategy
 * config schemas, but the *names themselves* deserve human-friendly
 * labels — we map the four canonical strategies + three persistence
 * options here so the user gets sentences, not enum slugs.
 *
 * Anything outside the curated subset (e.g. a custom strategy registered
 * by a downstream artifact) falls back to the generic editor under
 * "고급 설정".
 */

import { useEffect, useMemo, useState } from 'react';
import {
  Brain,
  Database,
  ChevronDown,
  ChevronRight,
  HardDrive,
  Cpu,
} from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { catalogApi } from '@/lib/environmentApi';
import { localizeIntrospection } from '../stage_locale';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type {
  StageIntrospection,
  StageManifestEntry,
  StageModelOverride,
} from '@/types/environment';
import { ModelConfigEditor } from '@/components/builder/ModelConfigEditor';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import StageGenericEditor from '../StageGenericEditor';

const STRATEGY_OPTIONS = [
  {
    id: 'append_only',
    titleKey: 'envManagement.stage18.strategy.append_only.title',
    descKey: 'envManagement.stage18.strategy.append_only.desc',
  },
  {
    id: 'no_memory',
    titleKey: 'envManagement.stage18.strategy.no_memory.title',
    descKey: 'envManagement.stage18.strategy.no_memory.desc',
  },
  {
    id: 'reflective',
    titleKey: 'envManagement.stage18.strategy.reflective.title',
    descKey: 'envManagement.stage18.strategy.reflective.desc',
  },
  {
    id: 'structured_reflective',
    titleKey: 'envManagement.stage18.strategy.structured_reflective.title',
    descKey: 'envManagement.stage18.strategy.structured_reflective.desc',
  },
];

const PERSISTENCE_OPTIONS = [
  {
    id: 'null',
    titleKey: 'envManagement.stage18.persist.null.title',
    descKey: 'envManagement.stage18.persist.null.desc',
  },
  {
    id: 'in_memory',
    titleKey: 'envManagement.stage18.persist.in_memory.title',
    descKey: 'envManagement.stage18.persist.in_memory.desc',
  },
  {
    id: 'file',
    titleKey: 'envManagement.stage18.persist.file.title',
    descKey: 'envManagement.stage18.persist.file.desc',
  },
];

const REFLECTIVE_STRATEGIES = new Set(['reflective', 'structured_reflective']);

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function Stage18MemoryEditor({ order, entry }: Props) {
  const { t } = useI18n();
  const locale = useI18n((s) => s.locale);
  const draft = useEnvironmentDraftStore((s) => s.draft);
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);

  const [intro, setIntro] = useState<StageIntrospection | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    catalogApi
      .stage(order)
      .then((res) => {
        if (!cancelled) setIntro(localizeIntrospection(res, locale));
      })
      .catch(() => {
        /* generic editor falls back gracefully */
      });
    return () => {
      cancelled = true;
    };
  }, [order, locale]);

  // Available strategy/persistence names from the catalog (so we can
  // disable curated tiles that the executor build doesn't actually
  // ship).
  const availableStrategies = useMemo(() => {
    const slot = intro?.strategy_slots?.['strategy'];
    return new Set(slot?.available_impls ?? []);
  }, [intro]);
  const availablePersistence = useMemo(() => {
    const slot = intro?.strategy_slots?.['persistence'];
    return new Set(slot?.available_impls ?? []);
  }, [intro]);

  const currentStrategy =
    entry.strategies?.['strategy'] ??
    intro?.strategy_slots?.['strategy']?.current_impl ??
    'append_only';
  const currentPersistence =
    entry.strategies?.['persistence'] ??
    intro?.strategy_slots?.['persistence']?.current_impl ??
    'null';

  const persistenceConfig =
    (entry.strategy_configs?.[currentPersistence] as Record<string, unknown>) ?? {};
  const fileBaseDir =
    typeof persistenceConfig.base_dir === 'string'
      ? (persistenceConfig.base_dir as string)
      : '';

  const setStrategy = (s: string) => {
    patchStage(order, {
      strategies: { ...(entry.strategies ?? {}), strategy: s },
    });
  };

  const setPersistence = (p: string) => {
    patchStage(order, {
      strategies: { ...(entry.strategies ?? {}), persistence: p },
    });
  };

  const setFileBaseDir = (path: string) => {
    const nextConfigs = { ...(entry.strategy_configs ?? {}) };
    nextConfigs['file'] = { ...(nextConfigs['file'] ?? {}), base_dir: path };
    patchStage(order, { strategy_configs: nextConfigs });
  };

  const overrideOn =
    entry.model_override !== null && entry.model_override !== undefined;
  const pipelineModel = (draft?.model ?? {}) as Record<string, unknown>;

  const toggleOverride = (next: boolean) => {
    if (next) {
      patchStage(order, {
        model_override: { ...pipelineModel } as unknown as StageModelOverride,
      });
    } else {
      patchStage(order, { model_override: null });
    }
  };

  const reflectiveActive = REFLECTIVE_STRATEGIES.has(currentStrategy);

  return (
    <div className="flex flex-col gap-4">
      {/* ── Active ── */}
      <section className="flex items-center justify-between gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div>
          <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage18.activeTitle')}
          </div>
          <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage18.activeDesc')}
          </div>
        </div>
        <Switch
          checked={!!entry.active}
          onCheckedChange={(checked) => patchStage(order, { active: checked })}
        />
      </section>

      {/* ── Strategy ── */}
      <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <header className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-[hsl(var(--primary))]" />
          <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage18.strategyTitle')}
          </h4>
        </header>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {STRATEGY_OPTIONS.map((opt) => {
            const available = availableStrategies.has(opt.id);
            const active = currentStrategy === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                disabled={!available && availableStrategies.size > 0}
                onClick={() => setStrategy(opt.id)}
                className={`flex items-start gap-2 p-2.5 rounded-md border text-left transition-colors ${
                  active
                    ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)]'
                    : 'border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:bg-[hsl(var(--accent))]'
                } ${
                  !available && availableStrategies.size > 0
                    ? 'opacity-40 cursor-not-allowed'
                    : ''
                }`}
                title={!available ? t('envManagement.stage18.unavailable') : undefined}
              >
                <div className="min-w-0">
                  <div className="text-[0.8125rem] font-medium text-[hsl(var(--foreground))]">
                    {t(opt.titleKey)}
                  </div>
                  <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] mt-0.5">
                    {t(opt.descKey)}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* ── Persistence ── */}
      <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <header className="flex items-center gap-2">
          <Database className="w-4 h-4 text-[hsl(var(--primary))]" />
          <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage18.persistTitle')}
          </h4>
        </header>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          {PERSISTENCE_OPTIONS.map((opt) => {
            const available = availablePersistence.has(opt.id);
            const active = currentPersistence === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                disabled={!available && availablePersistence.size > 0}
                onClick={() => setPersistence(opt.id)}
                className={`flex items-start gap-2 p-2.5 rounded-md border text-left transition-colors ${
                  active
                    ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)]'
                    : 'border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:bg-[hsl(var(--accent))]'
                } ${
                  !available && availablePersistence.size > 0
                    ? 'opacity-40 cursor-not-allowed'
                    : ''
                }`}
                title={!available ? t('envManagement.stage18.unavailable') : undefined}
              >
                <div className="min-w-0">
                  <div className="text-[0.8125rem] font-medium text-[hsl(var(--foreground))]">
                    {t(opt.titleKey)}
                  </div>
                  <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] mt-0.5">
                    {t(opt.descKey)}
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {currentPersistence === 'file' && (
          <div className="flex flex-col gap-1 pt-2 border-t border-[hsl(var(--border))]">
            <label className="flex items-center gap-1.5 text-[0.75rem] font-medium text-[hsl(var(--foreground))]">
              <HardDrive className="w-3 h-3" />
              {t('envManagement.stage18.fileBaseDirLabel')}
            </label>
            <Input
              value={fileBaseDir}
              onChange={(e) => setFileBaseDir(e.target.value)}
              placeholder=".geny/memory"
              className="h-7 font-mono text-[0.75rem]"
            />
            <p className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
              {t('envManagement.stage18.fileBaseDirHint')}
            </p>
          </div>
        )}
      </section>

      {/* ── Memory model override (only meaningful for reflective) ── */}
      <section
        className={`flex flex-col gap-3 p-3 rounded-md border bg-[hsl(var(--card))] ${
          reflectiveActive
            ? 'border-[hsl(var(--border))]'
            : 'border-dashed border-[hsl(var(--border))] opacity-60'
        }`}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Cpu className="w-4 h-4 text-[hsl(var(--primary))]" />
            <div>
              <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
                {t('envManagement.stage18.modelTitle')}
              </div>
              <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
                {reflectiveActive
                  ? overrideOn
                    ? t('envManagement.stage18.modelOnDesc')
                    : t('envManagement.stage18.modelOffDesc', {
                        model:
                          (pipelineModel.model as string | undefined) ??
                          '(default)',
                      })
                  : t('envManagement.stage18.modelDisabledDesc')}
              </div>
            </div>
          </div>
          <Switch
            checked={overrideOn}
            onCheckedChange={toggleOverride}
            disabled={!reflectiveActive}
          />
        </div>

        {overrideOn && reflectiveActive && (
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
                patchStage(order, {
                  model_override: next as unknown as StageModelOverride,
                });
              }}
              onClearError={() => {}}
            />
          </div>
        )}
      </section>

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
          {t('envManagement.stage18.advancedTitle')}
          <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage18.advancedHint')}
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
