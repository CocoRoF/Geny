'use client';

/**
 * Stage01InputEditor — curated editor for s01_input.
 *
 * The user's mental model: "what is the agent told to do at the start
 * of every turn?" In manifest terms that's mostly stage.config.system_
 * prompt (string), with optional persona starter chips loaded from
 * settings (PR-F polish).
 *
 * Surface:
 *   - Active toggle (stage 1 is required; users almost never turn it
 *     off — but we show the toggle so they CAN see its state)
 *   - System prompt textarea (large, autosize)
 *   - Quick-insert chips for common patterns ("Be concise.",
 *     "Use the available tools when relevant.", ...)
 *   - Advanced disclosure → StageGenericEditor
 */

import { useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  MessageSquare,
  Sparkles,
} from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type { StageManifestEntry } from '@/types/environment';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import StageGenericEditor from '../StageGenericEditor';

const STARTER_CHIPS = [
  { id: 'concise', textKey: 'envManagement.stage01.starters.concise' },
  { id: 'tools', textKey: 'envManagement.stage01.starters.tools' },
  { id: 'cite', textKey: 'envManagement.stage01.starters.cite' },
  { id: 'plan', textKey: 'envManagement.stage01.starters.plan' },
  { id: 'safety', textKey: 'envManagement.stage01.starters.safety' },
];

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function Stage01InputEditor({ order, entry }: Props) {
  const { t } = useI18n();
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);

  const [advancedOpen, setAdvancedOpen] = useState(false);

  const cfg = (entry.config as Record<string, unknown>) ?? {};
  const systemPrompt =
    typeof cfg.system_prompt === 'string' ? (cfg.system_prompt as string) : '';

  const setSystemPrompt = (next: string) => {
    patchStage(order, { config: { ...cfg, system_prompt: next } });
  };

  const insertChip = (text: string) => {
    if (!systemPrompt.trim()) {
      setSystemPrompt(text);
      return;
    }
    const sep = systemPrompt.endsWith('\n') ? '' : '\n';
    setSystemPrompt(systemPrompt + sep + text);
  };

  const charCount = systemPrompt.length;

  return (
    <div className="flex flex-col gap-4">
      {/* ── Active ── */}
      <section className="flex items-center justify-between gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div>
          <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage01.activeTitle')}
          </div>
          <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage01.activeDesc')}
          </div>
        </div>
        <Switch
          checked={!!entry.active}
          onCheckedChange={(checked) => patchStage(order, { active: checked })}
        />
      </section>

      {/* ── System prompt ── */}
      <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <header className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-[hsl(var(--primary))]" />
            <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
              {t('envManagement.stage01.systemPromptTitle')}
            </h4>
          </div>
          <span className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] tabular-nums">
            {t('envManagement.stage01.charCount', { n: String(charCount) })}
          </span>
        </header>
        <Textarea
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          placeholder={t('envManagement.stage01.systemPromptPlaceholder')}
          rows={10}
          className="font-mono text-[0.8125rem] leading-relaxed resize-y"
        />
        <p className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
          {t('envManagement.stage01.systemPromptHint')}
        </p>

        {/* Starter chips */}
        <div className="flex flex-col gap-1.5 pt-2 border-t border-[hsl(var(--border))]">
          <div className="flex items-center gap-1 text-[0.6875rem] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
            <Sparkles className="w-3 h-3" />
            {t('envManagement.stage01.startersTitle')}
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
          {t('envManagement.stage01.advancedTitle')}
          <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage01.advancedHint')}
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
