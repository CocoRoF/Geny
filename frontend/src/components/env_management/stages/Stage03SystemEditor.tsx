'use client';

/**
 * Stage03SystemEditor — curated editor for s03_system. THIS is where
 * the system prompt actually lives in the manifest (config.prompt
 * under the StaticPromptBuilder builder, or composable blocks under
 * ComposablePromptBuilder).
 *
 * The friendly textarea + starter-chip UX that originally landed in
 * Stage 1 belongs here — moved in cycle 20260427_3 once the
 * stage-1-vs-stage-3 contract was double-checked.
 */

import { useEffect, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  MessageSquare,
  Sparkles,
} from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { catalogApi } from '@/lib/environmentApi';
import { localizeIntrospection } from '../stage_locale';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type {
  StageIntrospection,
  StageManifestEntry,
} from '@/types/environment';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import StageGenericEditor from '../StageGenericEditor';

const STARTER_CHIPS = [
  { id: 'concise', textKey: 'envManagement.stage03.starters.concise' },
  { id: 'tools', textKey: 'envManagement.stage03.starters.tools' },
  { id: 'cite', textKey: 'envManagement.stage03.starters.cite' },
  { id: 'plan', textKey: 'envManagement.stage03.starters.plan' },
  { id: 'safety', textKey: 'envManagement.stage03.starters.safety' },
];

const BUILDER_OPTIONS = [
  {
    id: 'StaticPromptBuilder',
    titleKey: 'envManagement.stage03.builder.static.title',
    descKey: 'envManagement.stage03.builder.static.desc',
  },
  {
    id: 'ComposablePromptBuilder',
    titleKey: 'envManagement.stage03.builder.composable.title',
    descKey: 'envManagement.stage03.builder.composable.desc',
  },
];

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function Stage03SystemEditor({ order, entry }: Props) {
  const { t } = useI18n();
  const locale = useI18n((s) => s.locale);
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
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [order, locale]);

  const availableBuilder = new Set(
    intro?.strategy_slots?.['builder']?.available_impls ??
      BUILDER_OPTIONS.map((o) => o.id),
  );
  const currentBuilder =
    entry.strategies?.['builder'] ??
    intro?.strategy_slots?.['builder']?.current_impl ??
    'StaticPromptBuilder';

  const setBuilder = (id: string) =>
    patchStage(order, {
      strategies: { ...(entry.strategies ?? {}), builder: id },
    });

  const cfg = (entry.config as Record<string, unknown>) ?? {};
  const prompt =
    typeof cfg.prompt === 'string' ? (cfg.prompt as string) : '';
  const charCount = prompt.length;

  const setPrompt = (next: string) => {
    patchStage(order, { config: { ...cfg, prompt: next } });
  };

  const insertChip = (text: string) => {
    if (!prompt.trim()) {
      setPrompt(text);
      return;
    }
    const sep = prompt.endsWith('\n') ? '' : '\n';
    setPrompt(prompt + sep + text);
  };

  const isStatic = currentBuilder === 'StaticPromptBuilder';

  return (
    <div className="flex flex-col gap-4">
      {/* ── Active ── */}
      <section className="flex items-center justify-between gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div>
          <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage03.activeTitle')}
          </div>
          <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage03.activeDesc')}
          </div>
        </div>
        <Switch
          checked={!!entry.active}
          onCheckedChange={(checked) => patchStage(order, { active: checked })}
        />
      </section>

      {/* ── Builder picker ── */}
      <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <header className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-[hsl(var(--primary))]" />
          <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage03.builderTitle')}
          </h4>
        </header>
        <p className="text-[0.7rem] text-[hsl(var(--muted-foreground))] leading-relaxed">
          {t('envManagement.stage03.builderHint')}
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {BUILDER_OPTIONS.map((opt) => {
            const available = availableBuilder.has(opt.id);
            const active = currentBuilder === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                disabled={!available}
                onClick={() => setBuilder(opt.id)}
                className={`flex items-start gap-2 p-2.5 rounded-md border text-left transition-colors ${
                  active
                    ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)]'
                    : 'border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:bg-[hsl(var(--accent))]'
                } ${!available ? 'opacity-40 cursor-not-allowed' : ''}`}
                title={!available ? t('envManagement.stage03.unavailable') : undefined}
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

      {/* ── System prompt textarea (static builder only) ── */}
      {isStatic && (
        <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
          <header className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <MessageSquare className="w-4 h-4 text-[hsl(var(--primary))]" />
              <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
                {t('envManagement.stage03.systemPromptTitle')}
              </h4>
            </div>
            <span className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] tabular-nums">
              {t('envManagement.stage03.charCount', { n: String(charCount) })}
            </span>
          </header>
          <Textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={t('envManagement.stage03.systemPromptPlaceholder')}
            rows={10}
            className="font-mono text-[0.8125rem] leading-relaxed resize-y"
          />
          <p className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage03.systemPromptHint')}
          </p>

          <div className="flex flex-col gap-1.5 pt-2 border-t border-[hsl(var(--border))]">
            <div className="flex items-center gap-1 text-[0.6875rem] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
              <Sparkles className="w-3 h-3" />
              {t('envManagement.stage03.startersTitle')}
            </div>
            <div className="flex flex-wrap gap-1">
              {STARTER_CHIPS.map((chip) => {
                const text = t(chip.textKey);
                return (
                  <button
                    key={chip.id}
                    type="button"
                    onClick={() => insertChip(text)}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-full border border-dashed border-[hsl(var(--border))] text-[0.7rem] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))] hover:border-[hsl(var(--primary))] transition-colors"
                    title={text}
                  >
                    + {text.length > 32 ? text.slice(0, 32) + '…' : text}
                  </button>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {/* ── Composable note ── */}
      {!isStatic && (
        <div className="px-3 py-2 rounded-md bg-[hsl(var(--accent))] text-[0.7rem] text-[hsl(var(--muted-foreground))]">
          {t('envManagement.stage03.composableHint')}
        </div>
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
          {t('envManagement.stage03.advancedTitle')}
          <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage03.advancedHint')}
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
