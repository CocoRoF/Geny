'use client';

/**
 * Stage11ToolReviewEditor — curated editor for s11_tool_review.
 *
 * Tool review is a chain of independent reviewers that look at each
 * pending tool call and can flag it (the executor lets stage 14
 * decide what to do with the flags). The chain is configurable in
 * two ways:
 *   - WHICH reviewers are in the chain (subset of available_impls)
 *   - the ORDER they fire in (some reviewers short-circuit on flag)
 *
 * Both live under stage.chain_order[chain_name]: List[str] in the
 * manifest. Per-reviewer config (e.g. SensitivePatternReviewer's
 * pattern list) lives under stage.strategy_configs[reviewer_name].
 */

import { useEffect, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  ChevronUp,
  GripVertical,
  ShieldAlert,
} from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { catalogApi } from '@/lib/environmentApi';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type {
  ChainIntrospection,
  StageIntrospection,
  StageManifestEntry,
} from '@/types/environment';
import JsonSchemaForm, {
  type JsonSchema,
} from '@/components/environment/JsonSchemaForm';
import { Switch } from '@/components/ui/switch';
import StageGenericEditor from '../StageGenericEditor';

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function Stage11ToolReviewEditor({ order, entry }: Props) {
  const { t } = useI18n();
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);

  const [intro, setIntro] = useState<StageIntrospection | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [expandedConfig, setExpandedConfig] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    catalogApi
      .stage(order)
      .then((res) => {
        if (!cancelled) setIntro(res);
      })
      .catch(() => {
        /* fall back to generic */
      });
    return () => {
      cancelled = true;
    };
  }, [order]);

  // Pick the first chain slot — stage 11 only has one in the default
  // artifact, but the data model supports multiple.
  const chainName = intro ? Object.keys(intro.strategy_chains)[0] : null;
  const chain: ChainIntrospection | null = chainName
    ? intro!.strategy_chains[chainName]
    : null;

  // Narrow explicitly — `chainName && X` collapses to "" when chainName is
  // an empty string, which would leak `""` through the `??` chain (the
  // empty string isn't nullish so `??` doesn't substitute it).
  const currentChain: string[] = (chainName
    ? (entry.chain_order?.[chainName] as string[] | undefined)
    : undefined) ?? chain?.current_impls ?? [];
  const available = chain?.available_impls ?? [];
  const inChain = new Set(currentChain);
  const remaining = available.filter((n) => !inChain.has(n));

  const writeChain = (next: string[]) => {
    if (!chainName) return;
    patchStage(order, {
      chain_order: { ...(entry.chain_order ?? {}), [chainName]: next },
    });
  };

  const moveUp = (idx: number) => {
    if (idx === 0) return;
    const next = [...currentChain];
    [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
    writeChain(next);
  };
  const moveDown = (idx: number) => {
    if (idx >= currentChain.length - 1) return;
    const next = [...currentChain];
    [next[idx + 1], next[idx]] = [next[idx], next[idx + 1]];
    writeChain(next);
  };
  const removeAt = (idx: number) => {
    const next = currentChain.filter((_, i) => i !== idx);
    writeChain(next);
  };
  const append = (name: string) => writeChain([...currentChain, name]);

  const setReviewerConfig = (name: string, next: Record<string, unknown>) => {
    patchStage(order, {
      strategy_configs: { ...(entry.strategy_configs ?? {}), [name]: next },
    });
  };

  return (
    <div className="flex flex-col gap-4">
      {/* ── Active ── */}
      <section className="flex items-center justify-between gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div>
          <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage11.activeTitle')}
          </div>
          <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage11.activeDesc')}
          </div>
        </div>
        <Switch
          checked={!!entry.active}
          onCheckedChange={(checked) => patchStage(order, { active: checked })}
        />
      </section>

      {/* ── Chain ── */}
      <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <header className="flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-[hsl(var(--primary))]" />
          <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage11.chainTitle')}
          </h4>
          {chainName && (
            <code className="text-[0.625rem] font-mono text-[hsl(var(--muted-foreground))]">
              {chainName}
            </code>
          )}
        </header>
        <p className="text-[0.7rem] text-[hsl(var(--muted-foreground))] leading-relaxed">
          {t('envManagement.stage11.chainHint')}
        </p>

        {!chain && (
          <p className="text-[0.75rem] text-[hsl(var(--muted-foreground))] italic">
            {t('envManagement.stage11.noChain')}
          </p>
        )}

        {chain && currentChain.length === 0 && (
          <div className="px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/30 text-[0.75rem] text-amber-700 dark:text-amber-300">
            {t('envManagement.stage11.emptyChainWarning')}
          </div>
        )}

        {chain && currentChain.length > 0 && (
          <ol className="flex flex-col gap-1.5 mt-1">
            {currentChain.map((name, idx) => {
              const desc = chain.impl_descriptions[name] || '';
              const schema = (chain.impl_schemas?.[name] ?? null) as
                | JsonSchema
                | null;
              const cfgValue =
                (entry.strategy_configs?.[name] as Record<string, unknown>) ?? {};
              const cfgOpen = !!expandedConfig[name];
              return (
                <li
                  key={`${name}_${idx}`}
                  className="flex flex-col gap-1 p-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))]"
                >
                  <div className="flex items-center gap-2">
                    <GripVertical className="w-3.5 h-3.5 text-[hsl(var(--muted-foreground))]" />
                    <span className="text-[0.625rem] font-mono text-[hsl(var(--muted-foreground))] w-4 text-center">
                      {idx + 1}
                    </span>
                    <code className="font-mono text-[0.75rem] text-[hsl(var(--foreground))] flex-1 truncate">
                      {name}
                    </code>
                    <div className="flex items-center gap-0.5">
                      <button
                        type="button"
                        onClick={() => moveUp(idx)}
                        disabled={idx === 0}
                        className="p-1 rounded hover:bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] disabled:opacity-30 disabled:cursor-not-allowed"
                        aria-label="move up"
                      >
                        <ChevronUp className="w-3 h-3" />
                      </button>
                      <button
                        type="button"
                        onClick={() => moveDown(idx)}
                        disabled={idx === currentChain.length - 1}
                        className="p-1 rounded hover:bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] disabled:opacity-30 disabled:cursor-not-allowed"
                        aria-label="move down"
                      >
                        <ChevronDown className="w-3 h-3" />
                      </button>
                      <button
                        type="button"
                        onClick={() => removeAt(idx)}
                        className="p-1 rounded hover:bg-red-500/10 text-[hsl(var(--muted-foreground))] hover:text-red-500"
                        aria-label="remove"
                      >
                        ×
                      </button>
                    </div>
                  </div>
                  {desc && (
                    <p className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] pl-7 leading-relaxed">
                      {desc}
                    </p>
                  )}
                  {schema && (
                    <div className="pl-7 pt-1">
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedConfig((p) => ({ ...p, [name]: !p[name] }))
                        }
                        className="inline-flex items-center gap-1 text-[0.6875rem] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
                      >
                        {cfgOpen ? (
                          <ChevronDown className="w-3 h-3" />
                        ) : (
                          <ChevronRight className="w-3 h-3" />
                        )}
                        {t('envManagement.stage11.configure')}
                      </button>
                      {cfgOpen && (
                        <div className="mt-1.5 p-2 rounded border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
                          <JsonSchemaForm
                            schema={schema}
                            value={cfgValue}
                            onChange={(next) => setReviewerConfig(name, next)}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        )}

        {/* Add reviewer */}
        {chain && remaining.length > 0 && (
          <div className="mt-2 pt-2 border-t border-[hsl(var(--border))]">
            <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] mb-1.5">
              {t('envManagement.stage11.addReviewer')}
            </div>
            <div className="flex flex-wrap gap-1">
              {remaining.map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => append(name)}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-full border border-dashed border-[hsl(var(--border))] text-[0.6875rem] font-mono text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] hover:border-[hsl(var(--primary))]"
                  title={chain.impl_descriptions[name] || name}
                >
                  + {name}
                </button>
              ))}
            </div>
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
          {t('envManagement.stage11.advancedTitle')}
          <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage11.advancedHint')}
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
