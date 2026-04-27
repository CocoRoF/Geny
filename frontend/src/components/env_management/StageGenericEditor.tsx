'use client';

/**
 * StageGenericEditor — schema-driven fallback for any stage that
 * doesn't (yet) have a curated editor.
 *
 * The Active toggle and the Artifact picker are rendered by
 * StageDetailView (header chrome + first card under the header) so
 * they're consistent across every stage, curated or generic. This
 * editor only owns the body sections:
 *   - StrategiesEditor (per-slot strategy + per-strategy config)
 *   - ChainsEditor (where the stage exposes chains)
 *   - JsonSchemaForm (artifact's own ConfigSchema → stage.config)
 */

import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { catalogApi } from '@/lib/environmentApi';
import { useI18n } from '@/lib/i18n';
import type {
  StageIntrospection,
  StageManifestEntry,
} from '@/types/environment';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import { localizeIntrospection } from './stage_locale';
import {
  StrategiesEditor,
  ChainsEditor,
} from '@/components/environment/StrategyEditors';
import JsonSchemaForm, {
  type JsonSchema,
} from '@/components/environment/JsonSchemaForm';

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function StageGenericEditor({ order, entry }: Props) {
  const { t } = useI18n();
  const locale = useI18n((s) => s.locale);
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);

  const [intro, setIntro] = useState<StageIntrospection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch introspection for the chosen artifact (or default artifact if
  // none is set yet). Re-fetch when the artifact changes so schemas
  // match the new artifact's ConfigSchema. Run the response through
  // the locale layer so KO users see translated slot/impl/config
  // descriptions without touching the executor.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const fetcher =
      entry.artifact && entry.artifact !== 'default'
        ? catalogApi.artifactByStage(order, entry.artifact)
        : catalogApi.stage(order);
    fetcher
      .then((res) => {
        if (cancelled) return;
        setIntro(localizeIntrospection(res, locale));
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [order, entry.artifact, locale]);

  const configSchema: JsonSchema | null = (intro?.config_schema as
    | JsonSchema
    | null
    | undefined) ?? null;

  return (
    <div className="flex flex-col gap-4">
      {loading && (
        <div className="flex items-center gap-2 text-[0.75rem] text-[hsl(var(--muted-foreground))] p-3">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          {t('envManagement.loadingSchema')}
        </div>
      )}

      {error && (
        <div className="px-3 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-[0.75rem] text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {/* ── Strategies (per-slot) ── */}
      {intro && Object.keys(intro.strategy_slots).length > 0 && (
        <section className="flex flex-col gap-2">
          <h4 className="text-[0.75rem] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stageStrategies')}
          </h4>
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

      {/* ── Chains (where supported) ── */}
      {intro && Object.keys(intro.strategy_chains).length > 0 && (
        <section className="flex flex-col gap-2">
          <h4 className="text-[0.75rem] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stageChains')}
          </h4>
          <ChainsEditor
            chains={intro.strategy_chains}
            chainOrder={entry.chain_order || {}}
            onChangeChainOrder={(next) =>
              patchStage(order, { chain_order: next })
            }
          />
        </section>
      )}

      {/* ── Stage config (artifact's ConfigSchema) ── */}
      {intro && configSchema && (
        <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
          <h4 className="text-[0.75rem] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stageConfig')}
          </h4>
          <JsonSchemaForm
            schema={configSchema}
            value={entry.config || {}}
            onChange={(next) => patchStage(order, { config: next })}
          />
        </section>
      )}

      {/* ── model_override / tool_binding hints (hidden until PR-B/PR-C) ── */}
      {intro?.model_override_supported && !entry.model_override && (
        <div className="px-3 py-2 rounded-md bg-[hsl(var(--accent))] text-[0.7rem] text-[hsl(var(--muted-foreground))]">
          {t('envManagement.modelOverrideHint')}
        </div>
      )}
      {intro?.tool_binding_supported && !entry.tool_binding && (
        <div className="px-3 py-2 rounded-md bg-[hsl(var(--accent))] text-[0.7rem] text-[hsl(var(--muted-foreground))]">
          {t('envManagement.toolBindingHint')}
        </div>
      )}
    </div>
  );
}
