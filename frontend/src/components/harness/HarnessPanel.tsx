'use client';

/**
 * Settings › this agent › Harness — the 21 stages it actually runs.
 *
 * Everything on this page is read from the session's LIVE pipeline, not from
 * the environment it was built from. Geny declares placeholders in that
 * manifest and installs the real implementations at session build, so a page
 * rendered from the manifest shows `no_persist` on a stage that persists and
 * an empty guard chain on a session that guards. Each value therefore also
 * says where it came from, because what runs is only half of what a settings
 * page owes the reader; the other half is whether changing it will stick.
 *
 * Three screens, and which one a control lands on is a claim about the
 * reader rather than about the code:
 *
 *   기본   nine questions and three budgets. Someone tuning their agent.
 *   고급   everything else swappable, grouped the way a turn moves.
 *   잠김   what this product IS. Shown, because hiding them would make the
 *          page a lie of omission, and inert.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, CheckCircle2, ChevronRight, Loader2, Lock, RotateCcw } from 'lucide-react';

import { agentApi } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import type {
  HarnessBudgets,
  HarnessField,
  HarnessSlot,
  HarnessStage,
  HarnessView,
} from '@/types/harness';

type Tier = 'basic' | 'advanced' | 'locked';

/** Where a value came from, as a badge. `session` is the only one that also
 *  offers a way back. */
function SourceBadge({ source }: { source: string }) {
  const { t } = useI18n();
  const tone =
    source === 'session'
      ? 'text-[var(--primary-color)] border-[var(--primary-color)]'
      : 'text-[var(--text-muted)] border-[var(--border-color)]';
  return (
    <span className={`shrink-0 text-[0.65rem] px-1.5 py-0.5 rounded border ${tone}`}>
      {t(`harness.source.${source}`)}
    </span>
  );
}

/** One setting of the chosen implementation, committed when the reader
 *  leaves the field — the same rhythm as the budgets above. */
function ConfigField({
  field,
  value,
  busy,
  onCommit,
}: {
  field: HarnessField;
  value: unknown;
  busy: boolean;
  onCommit: (value: unknown) => void;
}) {
  const { t } = useI18n();
  const key = `harness.field.${field.name}`;
  const translated = t(key);
  const label = translated === key ? field.label : translated;
  const shown = value === undefined || value === null ? field.default : value;
  const asText = Array.isArray(shown) ? shown.join(', ') : shown == null ? '' : String(shown);
  const [draft, setDraft] = useState(asText);
  useEffect(() => setDraft(asText), [asText]);

  const commit = () => {
    if (draft === asText) return;
    if (field.type === 'integer' || field.type === 'number') {
      const next = Number(draft);
      if (draft.trim() !== '' && Number.isFinite(next)) onCommit(next);
      else setDraft(asText);
    } else if (field.type === 'array') {
      onCommit(
        draft
          .split(',')
          .map((part) => part.trim())
          .filter(Boolean),
      );
    } else {
      onCommit(draft);
    }
  };

  if (field.type === 'boolean') {
    return (
      <label className="flex items-center gap-2 text-[0.75rem]">
        <input
          type="checkbox"
          checked={Boolean(shown)}
          disabled={busy}
          onChange={(e) => onCommit(e.target.checked)}
        />
        <span>{label}</span>
      </label>
    );
  }
  const numeric = field.type === 'integer' || field.type === 'number';
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[0.75rem] text-[var(--text-secondary)]">{label}</span>
      <input
        type={numeric ? 'number' : 'text'}
        step={field.type === 'number' ? 0.01 : 1}
        min={field.minValue ?? undefined}
        max={field.maxValue ?? undefined}
        className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-1.5 text-[0.8125rem] font-mono disabled:opacity-60"
        value={draft}
        disabled={busy}
        title={field.description}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
      />
    </label>
  );
}

function SlotRow({
  stage,
  slot,
  busy,
  onChange,
  onReset,
  onConfigure,
}: {
  stage: HarnessStage;
  slot: HarnessSlot;
  busy: boolean;
  onChange: (key: string, value: string) => void;
  onReset: (key: string) => void;
  onConfigure: (key: string, config: Record<string, unknown>) => void;
}) {
  const { t } = useI18n();
  const key = `${stage.order}.${slot.slot}`;
  const locked = slot.tier === 'locked';
  const chosen = Array.isArray(slot.value) ? '' : String(slot.value ?? '');

  // A basic slot leads with the question it answers; everything else leads
  // with what it is, because at that depth the reader already knows.
  const title = slot.question
    ? t(`harness.question.${slot.question}`)
    : `${stage.order}. ${t(`harness.stage.${stage.name}`) ?? stage.name} · ${slot.slot}`;

  const note = locked
    ? t(`harness.locked.${slot.lockedBecause}`)
    : slot.installedBy
      ? t(`harness.installed.${slot.installedBy}`)
      : slot.description;

  return (
    <div className="flex flex-col gap-1.5 py-3 border-b border-[var(--border-color)] last:border-b-0">
      <div className="flex items-start gap-2">
        <span className="flex-1 text-[0.8125rem] font-medium">{title}</span>
        {locked && <Lock size={12} className="mt-1 text-[var(--text-muted)]" />}
        <SourceBadge source={slot.source} />
        {slot.source === 'session' && !locked && (
          <button
            type="button"
            className="shrink-0 text-[var(--text-muted)] hover:text-[var(--text-primary)] disabled:opacity-40"
            disabled={busy}
            title={t('harness.revert')}
            onClick={() => onReset(key)}
          >
            <RotateCcw size={12} />
          </button>
        )}
      </div>

      {note && <p className="text-[0.75rem] text-[var(--text-muted)] leading-relaxed">{note}</p>}

      {Array.isArray(slot.value) ? (
        // A chain is a list, and reordering it is not something this page
        // asks for yet — showing the order is what the reader needs to know
        // the guards are actually there.
        <p className="text-[0.75rem] font-mono text-[var(--text-secondary)]">
          {slot.value.length ? slot.value.join(' → ') : t('harness.emptyChain')}
        </p>
      ) : (
        <select
          className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem] disabled:opacity-60"
          value={chosen}
          disabled={locked || busy}
          onChange={(e) => onChange(key, e.target.value)}
        >
          {slot.options.map((o) => (
            <option key={o.name} value={o.name}>
              {o.name}
              {o.installed ? ` (${t('harness.installedOption')})` : ''}
              {o.description ? ` — ${o.description}` : ''}
            </option>
          ))}
        </select>
      )}

      {!locked && !Array.isArray(slot.value) && (() => {
        // The settings of what is chosen, not of every option: a form for
        // an implementation that is not running would edit nothing.
        const fields = slot.options.find((o) => o.name === chosen)?.schema?.fields ?? [];
        if (!fields.length) return null;
        return (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-1">
            {fields.map((field) => (
              <ConfigField
                key={field.name}
                field={field}
                value={slot.config[field.name]}
                busy={busy}
                onCommit={(v) => onConfigure(key, { ...slot.config, [field.name]: v })}
              />
            ))}
          </div>
        );
      })()}
    </div>
  );
}

function BudgetRow({
  label,
  hint,
  value,
  unit,
  source,
  busy,
  onCommit,
}: {
  label: string;
  hint: string;
  value: number | null;
  unit: string;
  /** Who decided this number — the owner, the route, or nobody. Shown
   *  because a budget derived from the route and one typed by hand behave
   *  differently on the next model switch, and the page would otherwise
   *  present them identically. */
  source?: string;
  busy: boolean;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState(value == null ? '' : String(value));
  useEffect(() => setDraft(value == null ? '' : String(value)), [value]);
  return (
    <div className="flex flex-col gap-1.5 py-3 border-b border-[var(--border-color)] last:border-b-0">
      <div className="flex items-start gap-2">
        <span className="flex-1 text-[0.8125rem] font-medium">{label}</span>
        {source && <SourceBadge source={source} />}
      </div>
      <p className="text-[0.75rem] text-[var(--text-muted)] leading-relaxed">{hint}</p>
      <div className="flex items-center gap-2">
        <input
          type="number"
          min={0}
          className="flex-1 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem] font-mono"
          value={draft}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            const next = Number(draft);
            if (Number.isFinite(next) && next >= 0 && String(value ?? '') !== draft) {
              onCommit(next);
            }
          }}
        />
        <span className="text-[0.75rem] text-[var(--text-muted)] w-14">{unit}</span>
      </div>
    </div>
  );
}

function Section({
  title,
  subtitle,
  defaultOpen = true,
  children,
}: {
  title: string;
  subtitle?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="mb-4">
      <button
        type="button"
        className="w-full flex items-center gap-1.5 text-left mb-1"
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronRight
          size={13}
          className={open ? 'rotate-90 transition-transform' : 'transition-transform'}
        />
        <span className="text-[0.75rem] font-semibold uppercase tracking-[0.06em] text-[var(--text-secondary)]">
          {title}
        </span>
      </button>
      {subtitle && (
        <p className="text-[0.75rem] text-[var(--text-muted)] mb-2 ml-5 leading-relaxed">
          {subtitle}
        </p>
      )}
      {open && <div className="ml-5">{children}</div>}
    </section>
  );
}

export default function HarnessPanel({ sessionId }: { sessionId: string }) {
  const { t } = useI18n();
  const [view, setView] = useState<HarnessView | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setView(await agentApi.getHarness(sessionId));
    } catch (e) {
      setMessage({ tone: 'bad', text: e instanceof Error ? e.message : String(e) });
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const patch = useCallback(
    async (body: Record<string, unknown>) => {
      setBusy(true);
      setMessage(null);
      try {
        await agentApi.patchHarness(sessionId, body);
        await load();
        setMessage({ tone: 'ok', text: t('harness.saved') });
      } catch (e) {
        setMessage({ tone: 'bad', text: e instanceof Error ? e.message : String(e) });
      } finally {
        setBusy(false);
      }
    },
    [sessionId, load, t],
  );

  const setSlot = useCallback(
    (key: string, value: string) => void patch({ slots: { [key]: value } }),
    [patch],
  );
  const resetSlot = useCallback(
    // Back to inherited means the implementation AND its settings.
    (key: string) => void patch({ slots: { [key]: null }, slotConfigs: { [key]: null } }),
    [patch],
  );
  const configureSlot = useCallback(
    (key: string, config: Record<string, unknown>) => void patch({ slotConfigs: { [key]: config } }),
    [patch],
  );

  const byTier = useMemo(() => {
    const out: Record<Tier, { stage: HarnessStage; slot: HarnessSlot }[]> = {
      basic: [],
      advanced: [],
      locked: [],
    };
    for (const stage of view?.stages ?? []) {
      for (const slot of stage.slots) out[slot.tier as Tier]?.push({ stage, slot });
    }
    return out;
  }, [view]);

  if (!view) {
    // A failed load used to spin here forever: the error was set but the
    // element that renders it sits below this early return, so the one thing
    // the reader needed was the one thing they could not see.
    return (
      <div className="flex flex-col gap-2 py-8 text-[0.8125rem]">
        {message?.tone === 'bad' ? (
          <>
            <p className="flex items-start gap-1.5 text-rose-300">
              <AlertCircle size={12} className="mt-0.5 shrink-0" />
              {message.text}
            </p>
            <button
              type="button"
              className="self-start px-3 py-1.5 rounded border border-[var(--border-color)] text-[0.8125rem] hover:bg-[var(--bg-hover)]"
              onClick={() => void load()}
            >
              {t('common.retry')}
            </button>
          </>
        ) : (
          <span className="flex items-center gap-2 text-[var(--text-muted)]">
            <Loader2 size={13} className="animate-spin" /> {t('common.loading')}
          </span>
        )}
      </div>
    );
  }

  const budgets: HarnessBudgets = view.budgets ?? {};
  const perHop = budgets.contextWindow?.perHop ?? [];

  return (
    <div className="flex flex-col">
      {message && (
        <p
          className={`flex items-start gap-1.5 text-[0.75rem] mb-3 ${
            message.tone === 'ok' ? 'text-emerald-400' : 'text-rose-300'
          }`}
        >
          {message.tone === 'ok' ? (
            <CheckCircle2 size={12} className="mt-0.5 shrink-0" />
          ) : (
            <AlertCircle size={12} className="mt-0.5 shrink-0" />
          )}
          {message.text}
        </p>
      )}

      <Section title={t('harness.section.budgets')} subtitle={t('harness.section.budgetsHint')}>
        <BudgetRow
          label={t('harness.budget.maxIterations')}
          hint={t('harness.budget.maxIterationsHint')}
          value={budgets.maxIterations?.value ?? null}
          source={budgets.maxIterations?.source}
          unit={t('harness.unit.turns')}
          busy={busy}
          onCommit={(v) => void patch({ budgets: { maxIterations: v } })}
        />
        <BudgetRow
          label={t('harness.budget.contextWindow')}
          hint={
            perHop.length
              ? t('harness.budget.contextWindowPerHop', {
                  hops: perHop
                    .map((h) => `${h.label}: ${h.window ? h.window.toLocaleString() : t('harness.unknown')}`)
                    .join(' · '),
                })
              : t('harness.budget.contextWindowHint')
          }
          value={budgets.contextWindow?.value ?? null}
          source={budgets.contextWindow?.source}
          unit={t('harness.unit.tokens')}
          busy={busy}
          onCommit={(v) => void patch({ budgets: { contextWindow: v } })}
        />
        <BudgetRow
          label={t('harness.budget.costCeiling')}
          hint={t('harness.budget.costCeilingHint')}
          value={budgets.costCeiling?.value ?? null}
          source={budgets.costCeiling?.source}
          unit={t('harness.unit.usd')}
          busy={busy}
          onCommit={(v) => void patch({ budgets: { costCeiling: v } })}
        />
      </Section>

      <Section title={t('harness.section.basic')} subtitle={t('harness.section.basicHint')}>
        {byTier.basic.map(({ stage, slot }) => (
          <SlotRow
            key={`${stage.order}.${slot.slot}`}
            stage={stage}
            slot={slot}
            busy={busy}
            onChange={setSlot}
            onReset={resetSlot}
            onConfigure={configureSlot}
          />
        ))}
      </Section>

      <Section
        title={t('harness.section.advanced')}
        subtitle={t('harness.section.advancedHint')}
        defaultOpen={false}
      >
        {byTier.advanced.map(({ stage, slot }) => (
          <SlotRow
            key={`${stage.order}.${slot.slot}`}
            stage={stage}
            slot={slot}
            busy={busy}
            onChange={setSlot}
            onReset={resetSlot}
            onConfigure={configureSlot}
          />
        ))}
      </Section>

      <Section
        title={t('harness.section.locked')}
        subtitle={t('harness.section.lockedHint')}
        defaultOpen={false}
      >
        {byTier.locked.map(({ stage, slot }) => (
          <SlotRow
            key={`${stage.order}.${slot.slot}`}
            stage={stage}
            slot={slot}
            busy={busy}
            onChange={setSlot}
            onReset={resetSlot}
            onConfigure={configureSlot}
          />
        ))}
      </Section>
    </div>
  );
}
