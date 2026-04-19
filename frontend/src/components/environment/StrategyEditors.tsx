'use client';

/**
 * Strategies + Chains editors used inside the Environment Builder.
 *
 * Strategies: each slot has a current implementation picked from
 * `available_impls`; when that impl has a `impl_schemas[impl]` we
 * render the JSON schema form so users can configure it without
 * leaving the tab.
 *
 * Chains: each chain has an ordered list of implementations. Users can
 * reorder (up/down), remove, or append from the remaining available
 * impls.
 */

import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react';

import JsonSchemaForm, {
  type JsonSchema,
} from '@/components/environment/JsonSchemaForm';
import { useI18n } from '@/lib/i18n';
import type {
  ChainIntrospection,
  SlotIntrospection,
} from '@/types/environment';

// ────────────────────────────────────────────────────────────────
// Strategies

interface StrategiesEditorProps {
  slots: Record<string, SlotIntrospection>;
  strategies: Record<string, string>;
  strategyConfigs: Record<string, Record<string, unknown>>;
  onChangeStrategies: (next: Record<string, string>) => void;
  onChangeStrategyConfigs: (next: Record<string, Record<string, unknown>>) => void;
}

export function StrategiesEditor({
  slots,
  strategies,
  strategyConfigs,
  onChangeStrategies,
  onChangeStrategyConfigs,
}: StrategiesEditorProps) {
  const { t } = useI18n();
  const slotNames = Object.keys(slots);
  if (slotNames.length === 0) {
    return (
      <p className="text-[0.75rem] text-[var(--text-muted)] italic">
        {t('builderTab.strategiesEmpty')}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {slotNames.map(slotName => {
        const slot = slots[slotName];
        const current = strategies[slotName] ?? slot.current_impl ?? '';
        const schema = (slot.impl_schemas?.[current] ?? null) as JsonSchema | null;
        const implDescription = slot.impl_descriptions?.[current] || '';
        const implConfig = strategyConfigs[slotName] || {};
        return (
          <div
            key={slotName}
            className="flex flex-col gap-1.5 p-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)]"
          >
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-[0.8125rem] font-medium text-[var(--text-primary)]">
                  {slotName}
                </span>
                {slot.required && (
                  <span className="text-[0.625rem] font-semibold text-[var(--danger-color)]">
                    required
                  </span>
                )}
              </div>
              <select
                value={current}
                onChange={e => {
                  const nextImpl = e.target.value;
                  onChangeStrategies({ ...strategies, [slotName]: nextImpl });
                }}
                className="py-1 px-2 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.75rem] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)] cursor-pointer"
              >
                {slot.available_impls.map(impl => (
                  <option key={impl} value={impl}>
                    {impl}
                    {slot.impl_descriptions?.[impl]
                      ? ` — ${slot.impl_descriptions[impl]}`
                      : ''}
                  </option>
                ))}
                {!slot.available_impls.includes(current) && current && (
                  <option value={current}>{current} (legacy)</option>
                )}
              </select>
            </div>
            {slot.description && (
              <small className="text-[0.6875rem] text-[var(--text-muted)]">
                {slot.description}
              </small>
            )}
            {implDescription && implDescription !== slot.description && (
              <small className="text-[0.6875rem] text-[var(--text-muted)] italic">
                {implDescription}
              </small>
            )}
            {schema && (
              <div className="mt-1 p-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)]">
                <JsonSchemaForm
                  schema={schema}
                  value={implConfig}
                  onChange={next =>
                    onChangeStrategyConfigs({
                      ...strategyConfigs,
                      [slotName]: next,
                    })
                  }
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Chains

interface ChainsEditorProps {
  chains: Record<string, ChainIntrospection>;
  chainOrder: Record<string, string[]>;
  onChangeChainOrder: (next: Record<string, string[]>) => void;
}

export function ChainsEditor({
  chains,
  chainOrder,
  onChangeChainOrder,
}: ChainsEditorProps) {
  const { t } = useI18n();
  const chainNames = Object.keys(chains);
  if (chainNames.length === 0) {
    return (
      <p className="text-[0.75rem] text-[var(--text-muted)] italic">
        {t('builderTab.chainsEmpty')}
      </p>
    );
  }

  const reorder = (chainName: string, from: number, to: number) => {
    const current = chainOrder[chainName] ?? chains[chainName].current_impls ?? [];
    if (to < 0 || to >= current.length) return;
    const next = [...current];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    onChangeChainOrder({ ...chainOrder, [chainName]: next });
  };

  const remove = (chainName: string, index: number) => {
    const current = chainOrder[chainName] ?? chains[chainName].current_impls ?? [];
    const next = current.filter((_, i) => i !== index);
    onChangeChainOrder({ ...chainOrder, [chainName]: next });
  };

  const append = (chainName: string, impl: string) => {
    if (!impl) return;
    const current = chainOrder[chainName] ?? chains[chainName].current_impls ?? [];
    onChangeChainOrder({ ...chainOrder, [chainName]: [...current, impl] });
  };

  return (
    <div className="flex flex-col gap-3">
      {chainNames.map(chainName => {
        const chain = chains[chainName];
        const order = chainOrder[chainName] ?? chain.current_impls ?? [];
        const remaining = chain.available_impls.filter(x => !order.includes(x));
        return (
          <div
            key={chainName}
            className="flex flex-col gap-2 p-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)]"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-[0.8125rem] font-medium text-[var(--text-primary)]">
                {chainName}
              </span>
              <span className="text-[0.625rem] text-[var(--text-muted)]">
                {order.length} / {chain.available_impls.length}
              </span>
            </div>
            {chain.description && (
              <small className="text-[0.6875rem] text-[var(--text-muted)]">
                {chain.description}
              </small>
            )}
            <ol className="flex flex-col gap-1">
              {order.length === 0 && (
                <li className="text-[0.6875rem] text-[var(--text-muted)] italic">
                  {t('builderTab.chainEmpty')}
                </li>
              )}
              {order.map((impl, index) => (
                <li
                  key={`${impl}-${index}`}
                  className="flex items-center gap-1.5 py-1 px-2 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)]"
                >
                  <span className="text-[0.625rem] font-mono text-[var(--text-muted)] w-4 shrink-0">
                    {index + 1}.
                  </span>
                  <span className="flex-1 min-w-0 text-[0.75rem] text-[var(--text-primary)] truncate">
                    {impl}
                  </span>
                  <button
                    onClick={() => reorder(chainName, index, index - 1)}
                    disabled={index === 0}
                    className="w-6 h-6 flex items-center justify-center rounded bg-transparent border-none text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                    aria-label="move up"
                  >
                    <ArrowUp size={12} />
                  </button>
                  <button
                    onClick={() => reorder(chainName, index, index + 1)}
                    disabled={index === order.length - 1}
                    className="w-6 h-6 flex items-center justify-center rounded bg-transparent border-none text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                    aria-label="move down"
                  >
                    <ArrowDown size={12} />
                  </button>
                  <button
                    onClick={() => remove(chainName, index)}
                    className="w-6 h-6 flex items-center justify-center rounded bg-transparent border-none text-[var(--text-muted)] hover:text-[var(--danger-color)] hover:bg-[rgba(239,68,68,0.1)] cursor-pointer transition-colors"
                    aria-label="remove"
                  >
                    <Trash2 size={12} />
                  </button>
                </li>
              ))}
            </ol>
            {remaining.length > 0 && (
              <div className="flex items-center gap-1.5">
                <select
                  value=""
                  onChange={e => {
                    append(chainName, e.target.value);
                    e.target.value = '';
                  }}
                  className="py-1 px-2 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.75rem] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)] cursor-pointer flex-1 min-w-0"
                >
                  <option value="">{t('builderTab.chainAddPick')}</option>
                  {remaining.map(impl => (
                    <option key={impl} value={impl}>
                      {impl}
                    </option>
                  ))}
                </select>
                <Plus
                  size={12}
                  className="text-[var(--text-muted)] shrink-0"
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
