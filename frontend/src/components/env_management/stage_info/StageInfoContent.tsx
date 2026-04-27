'use client';

/**
 * StageInfoContent — renders the body of the stage info modal by
 * combining:
 *
 *   1. Base metadata from stageMetadata.ts (every stage has this — 21
 *      pre-localised entries with description / detailedDescription /
 *      technicalBehavior bullets / strategies / architectureNotes).
 *   2. Optional extras from stage_info/extras/Stage<NN>*Extras.ts —
 *      curated stages add useCases / configurations / pitfalls /
 *      codeReferences / relatedStages.
 *
 * Sections are rendered in a fixed order so every stage feels like the
 * same document, and absent sections are simply skipped.
 */

import {
  AlertTriangle,
  Boxes,
  CheckSquare,
  Code,
  ListTree,
  Sparkles,
  Wrench,
} from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { getStageMetaByOrder } from '@/components/session-env/stageMetadata';
import { STAGE_EXTRAS } from './extras';

export interface StageInfoContentProps {
  order: number;
}

export default function StageInfoContent({ order }: StageInfoContentProps) {
  const { t } = useI18n();
  const locale = useI18n((s) => s.locale);

  const meta = getStageMetaByOrder(order, locale);
  const extrasFactory = STAGE_EXTRAS[order];
  const extras = extrasFactory ? extrasFactory(locale) : null;

  if (!meta) {
    return (
      <div className="p-5 text-[0.875rem] text-[hsl(var(--muted-foreground))]">
        {t('envManagement.info.unknownStage', { n: String(order) })}
      </div>
    );
  }

  return (
    <div className="px-5 py-5 flex flex-col gap-6 text-[0.875rem] leading-relaxed text-[hsl(var(--foreground))]">
      {/* ── Overview / detailed description ── */}
      <Section
        icon={Sparkles}
        title={t('envManagement.info.overview')}
        accent="primary"
      >
        <p className="whitespace-pre-wrap">{meta.detailedDescription}</p>
      </Section>

      {/* ── Bypass condition (only when canBypass) ── */}
      {meta.canBypass && meta.bypassCondition && (
        <Callout
          tone="info"
          title={t('envManagement.info.canBypass')}
          body={meta.bypassCondition}
        />
      )}

      {/* ── Technical behaviour ── */}
      {meta.technicalBehavior.length > 0 && (
        <Section
          icon={ListTree}
          title={t('envManagement.info.technicalBehavior')}
          accent="primary"
        >
          <ul className="list-disc pl-5 space-y-1.5">
            {meta.technicalBehavior.map((tb, i) => (
              <li key={i}>{tb}</li>
            ))}
          </ul>
        </Section>
      )}

      {/* ── Strategies (per-slot) ── */}
      {meta.strategies.length > 0 && (
        <Section
          icon={Wrench}
          title={t('envManagement.info.strategies')}
          accent="primary"
        >
          <div className="flex flex-col gap-3">
            {meta.strategies.map((slot) => (
              <div key={slot.slot}>
                <div className="text-[0.75rem] uppercase tracking-wider font-semibold text-[hsl(var(--muted-foreground))] mb-1">
                  {slot.slot}
                </div>
                <ul className="flex flex-col gap-1">
                  {slot.options.map((opt) => (
                    <li
                      key={opt.name}
                      className="flex items-start gap-2 px-2 py-1.5 rounded bg-[hsl(var(--accent))]/40"
                    >
                      <code className="text-[0.6875rem] font-mono text-[hsl(var(--primary))] shrink-0">
                        {opt.name}
                      </code>
                      <span className="text-[0.8125rem] text-[hsl(var(--muted-foreground))]">
                        {opt.description}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── Architecture notes ── */}
      {meta.architectureNotes && (
        <Callout
          tone="neutral"
          title={t('envManagement.info.architectureNotes')}
          body={meta.architectureNotes}
        />
      )}

      {/* ── Extras (only for curated stages) ── */}
      {extras?.useCases && extras.useCases.length > 0 && (
        <Section
          icon={CheckSquare}
          title={t('envManagement.info.useCases')}
          accent="emerald"
        >
          <div className="flex flex-col gap-3">
            {extras.useCases.map((uc, i) => (
              <div
                key={i}
                className="border-l-2 border-emerald-500/50 pl-3"
              >
                <div className="text-[0.875rem] font-semibold mb-1">
                  {uc.title}
                </div>
                <p className="text-[0.8125rem] text-[hsl(var(--muted-foreground))] whitespace-pre-wrap">
                  {uc.body}
                </p>
              </div>
            ))}
          </div>
        </Section>
      )}

      {extras?.configurations && extras.configurations.length > 0 && (
        <Section
          icon={Boxes}
          title={t('envManagement.info.configurations')}
          accent="primary"
        >
          <div className="grid gap-2 grid-cols-1 md:grid-cols-2">
            {extras.configurations.map((cfg, i) => (
              <div
                key={i}
                className="border border-[hsl(var(--border))] rounded-md p-3 bg-[hsl(var(--card))]"
              >
                <div className="text-[0.875rem] font-semibold mb-0.5">
                  {cfg.name}
                </div>
                <p className="text-[0.75rem] text-[hsl(var(--muted-foreground))] mb-2">
                  {cfg.summary}
                </p>
                {cfg.highlights && cfg.highlights.length > 0 && (
                  <ul className="text-[0.75rem] space-y-0.5">
                    {cfg.highlights.map((h, j) => (
                      <li key={j} className="flex items-start gap-1.5">
                        <span className="w-1 h-1 rounded-full bg-[hsl(var(--primary))] mt-1.5 shrink-0" />
                        <code className="font-mono text-[0.7rem] text-[hsl(var(--foreground))]">
                          {h}
                        </code>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {extras?.pitfalls && extras.pitfalls.length > 0 && (
        <Section
          icon={AlertTriangle}
          title={t('envManagement.info.pitfalls')}
          accent="amber"
        >
          <div className="flex flex-col gap-3">
            {extras.pitfalls.map((p, i) => (
              <div
                key={i}
                className="rounded-md border border-amber-500/30 bg-amber-500/[0.06] p-3"
              >
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
                  <div className="flex-1 min-w-0">
                    <div className="text-[0.8125rem] font-semibold text-amber-700 dark:text-amber-300 mb-0.5">
                      {p.title}
                    </div>
                    <p className="text-[0.8125rem] text-[hsl(var(--muted-foreground))]">
                      {p.body}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {extras?.relatedStages && extras.relatedStages.length > 0 && (
        <Section
          icon={ListTree}
          title={t('envManagement.info.relatedStages')}
          accent="primary"
        >
          <ul className="flex flex-col gap-1.5">
            {extras.relatedStages.map((r) => (
              <li
                key={r.order}
                className="flex items-start gap-2 text-[0.8125rem]"
              >
                <span className="inline-flex items-center justify-center w-6 h-6 rounded-full text-[0.6875rem] font-bold tabular-nums bg-[hsl(var(--accent))] text-[hsl(var(--foreground))] shrink-0">
                  {r.order}
                </span>
                <span className="flex-1 min-w-0 text-[hsl(var(--muted-foreground))]">
                  {r.reason}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {extras?.codeReferences && extras.codeReferences.length > 0 && (
        <Section
          icon={Code}
          title={t('envManagement.info.codeReferences')}
          accent="primary"
        >
          <ul className="flex flex-col gap-1.5">
            {extras.codeReferences.map((ref, i) => (
              <li
                key={i}
                className="flex flex-col gap-0.5 px-2 py-1.5 rounded bg-[hsl(var(--accent))]/40"
              >
                <code className="text-[0.7rem] font-mono text-[hsl(var(--primary))]">
                  {ref.label}
                </code>
                {ref.description && (
                  <span className="text-[0.75rem] text-[hsl(var(--muted-foreground))]">
                    {ref.description}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* ── Footer hint when no extras yet (placeholder for future PRs) ── */}
      {!extras && (
        <p className="text-[0.75rem] italic text-[hsl(var(--muted-foreground))] border-t border-[hsl(var(--border))] pt-3">
          {t('envManagement.info.extrasPending')}
        </p>
      )}
    </div>
  );
}

// ── Helper components ─────────────────────────────────────

interface SectionProps {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  accent: 'primary' | 'emerald' | 'amber';
  children: React.ReactNode;
}

function Section({ icon: Icon, title, accent, children }: SectionProps) {
  const accentClass =
    accent === 'emerald'
      ? 'text-emerald-500'
      : accent === 'amber'
        ? 'text-amber-500'
        : 'text-[hsl(var(--primary))]';
  return (
    <section className="flex flex-col gap-2.5">
      <h3 className="flex items-center gap-1.5 text-[0.8125rem] font-semibold uppercase tracking-wider text-[hsl(var(--foreground))]">
        <Icon className={`w-3.5 h-3.5 ${accentClass}`} />
        {title}
      </h3>
      {children}
    </section>
  );
}

interface CalloutProps {
  tone: 'info' | 'neutral';
  title: string;
  body: string;
}

function Callout({ tone, title, body }: CalloutProps) {
  const styles =
    tone === 'info'
      ? 'border-blue-500/30 bg-blue-500/[0.06]'
      : 'border-[hsl(var(--border))] bg-[hsl(var(--card))]';
  return (
    <div className={`rounded-md border p-3 ${styles}`}>
      <div className="text-[0.75rem] uppercase tracking-wider font-semibold text-[hsl(var(--muted-foreground))] mb-1">
        {title}
      </div>
      <p className="text-[0.8125rem] text-[hsl(var(--foreground))] whitespace-pre-wrap">
        {body}
      </p>
    </div>
  );
}
