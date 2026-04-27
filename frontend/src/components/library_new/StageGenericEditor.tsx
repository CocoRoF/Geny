'use client';

/**
 * StageGenericEditor — schema-driven fallback for any stage that
 * doesn't (yet) have a curated editor.
 *
 * Pulls the per-stage introspection from /api/catalog/stages/{order}
 * and composes the existing reusable editors:
 *   - artifact picker (dropdown of available artifacts)
 *   - active toggle
 *   - StrategiesEditor (per-slot strategy + per-strategy config)
 *   - JsonSchemaForm (artifact's own ConfigSchema → stage.config)
 *
 * model_override + tool_binding + chain_order surface only when the
 * introspection says the stage supports them; otherwise hidden.
 */

import { useEffect, useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { catalogApi } from '@/lib/environmentApi';
import { useI18n } from '@/lib/i18n';
import type {
  StageIntrospection,
  StageManifestEntry,
} from '@/types/environment';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import {
  StrategiesEditor,
  ChainsEditor,
} from '@/components/environment/StrategyEditors';
import JsonSchemaForm, {
  type JsonSchema,
} from '@/components/environment/JsonSchemaForm';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function StageGenericEditor({ order, entry }: Props) {
  const { t } = useI18n();
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);

  const [intro, setIntro] = useState<StageIntrospection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch introspection for the chosen artifact (or default artifact if
  // none is set yet). Re-fetch when the artifact changes so schemas
  // match the new artifact's ConfigSchema.
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
        setIntro(res);
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
  }, [order, entry.artifact]);

  const artifactOptions = useMemo(() => {
    // We don't have the per-stage artifact list pre-loaded; fall back to
    // showing only the current + the introspected default. PR-F will
    // hydrate the full list via catalogApi.listArtifacts(order).
    const current = entry.artifact || intro?.artifact || 'default';
    const set = new Set<string>([current]);
    if (intro?.artifact) set.add(intro.artifact);
    return Array.from(set);
  }, [entry.artifact, intro]);

  const configSchema: JsonSchema | null = (intro?.config_schema as
    | JsonSchema
    | null
    | undefined) ?? null;

  return (
    <div className="flex flex-col gap-4">
      {/* ── Active + artifact ── */}
      <section className="flex flex-col gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
              {t('libraryNewTab.stageActive')}
            </div>
            <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
              {t('libraryNewTab.stageActiveDesc')}
            </div>
          </div>
          <Switch
            checked={!!entry.active}
            onCheckedChange={(checked) => patchStage(order, { active: checked })}
          />
        </div>

        <div className="flex items-center gap-3">
          <label className="text-[0.75rem] font-medium text-[hsl(var(--foreground))] min-w-[64px]">
            {t('libraryNewTab.stageArtifact')}
          </label>
          <Select
            value={entry.artifact || 'default'}
            onValueChange={(v) => patchStage(order, { artifact: v })}
          >
            <SelectTrigger className="h-8 flex-1 text-[0.75rem]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {artifactOptions.map((a) => (
                <SelectItem key={a} value={a} className="text-[0.75rem]">
                  {a}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </section>

      {loading && (
        <div className="flex items-center gap-2 text-[0.75rem] text-[hsl(var(--muted-foreground))] p-3">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          {t('libraryNewTab.loadingSchema')}
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
            {t('libraryNewTab.stageStrategies')}
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
            {t('libraryNewTab.stageChains')}
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
            {t('libraryNewTab.stageConfig')}
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
          {t('libraryNewTab.modelOverrideHint')}
        </div>
      )}
      {intro?.tool_binding_supported && !entry.tool_binding && (
        <div className="px-3 py-2 rounded-md bg-[hsl(var(--accent))] text-[0.7rem] text-[hsl(var(--muted-foreground))]">
          {t('libraryNewTab.toolBindingHint')}
        </div>
      )}
    </div>
  );
}
