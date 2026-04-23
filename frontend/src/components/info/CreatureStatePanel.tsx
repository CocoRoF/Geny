'use client';

/**
 * CreatureStatePanel — renders a session's Tamagotchi snapshot.
 *
 * Shipped in cycle 20260422_5 (X7) alongside backend changes that
 * expose `CreatureStateSnapshot` through the `/api/agents/{id}`
 * response. The component is a pure presentational layer: it takes
 * the snapshot + a translator and draws three groups of bars
 * (vitals / bond / mood) plus a life-stage / dominant-mood header.
 *
 * Design notes:
 * - Intentionally lightweight — inline divs, no external chart
 *   library. Matches the existing InfoTab aesthetic (bg-secondary
 *   cards, muted labels, monospace values).
 * - Vitals axes go 0–100 with a semantic direction. "hunger" and
 *   "stress" are *bad* at high values, so we invert the color to
 *   red as they grow. Energy / cleanliness use green for high.
 * - Bond axes are unbounded in backend ([0, ∞)); we soft-clamp at
 *   100 for the visual bar and show the raw number beside it, so
 *   long-running sessions still render sanely.
 * - Mood axes are [0, 1]; rendered as percent.
 */

import type { CreatureStateSnapshot } from '@/types';
import { Heart, Battery, Brain, Sparkles } from 'lucide-react';

export interface CreatureStatePanelProps {
  snapshot: CreatureStateSnapshot;
  t: (key: string, params?: Record<string, string>) => string;
  /**
   * Compact "game UI" rendering for the VTuberTab status badge
   * hover overlay. Uses a darker translucent backdrop, neon
   * accents and tighter spacing while preserving the same
   * three-section layout (vitals / bond / mood).
   */
  compact?: boolean;
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

function clamp100(v: number): number {
  return Math.max(0, Math.min(100, v));
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

/** Bar with percentage fill. `tone` drives the color gradient. */
function StatBar({
  label,
  value,
  max,
  tone,
  valueLabel,
}: {
  label: string;
  value: number;   // in same units as `max`
  max: number;
  tone: 'good' | 'warn' | 'neutral' | 'info';
  valueLabel?: string;
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const toneColor =
    tone === 'good'
      ? 'var(--success-color, #10b981)'
      : tone === 'warn'
        ? 'var(--danger-color, #ef4444)'
        : tone === 'info'
          ? 'var(--primary-color, #3b82f6)'
          : 'var(--text-muted, #6b7280)';
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">
          {label}
        </span>
        <span
          className="text-[11px] text-[var(--text-primary)]"
          style={{ fontFamily: "'SF Mono', 'Fira Code', monospace" }}
        >
          {valueLabel ?? `${pct.toFixed(0)}%`}
        </span>
      </div>
      <div
        className="h-1.5 w-full rounded-full overflow-hidden"
        style={{ background: 'var(--bg-tertiary, rgba(0,0,0,0.08))' }}
      >
        <div
          className="h-full rounded-full transition-[width] duration-300"
          style={{ width: `${pct}%`, background: toneColor }}
        />
      </div>
    </div>
  );
}

export default function CreatureStatePanel({
  snapshot,
  t,
  compact = false,
}: CreatureStatePanelProps) {
  const { mood, bond, vitals, progression, mood_dominant, last_interaction_at } =
    snapshot;

  // Mood axis ordering — keep in lockstep with backend MoodVector.keys()
  const moodAxes: Array<[keyof typeof mood, string]> = [
    ['joy', t('info.creatureState.moodAxes.joy')],
    ['sadness', t('info.creatureState.moodAxes.sadness')],
    ['anger', t('info.creatureState.moodAxes.anger')],
    ['fear', t('info.creatureState.moodAxes.fear')],
    ['calm', t('info.creatureState.moodAxes.calm')],
    ['excitement', t('info.creatureState.moodAxes.excitement')],
  ];

  // Plan/Phase01 — dominant-mood string returned by the backend is
  // an English key ("calm", "joy", ...). Look it up in the i18n
  // moodDominant map so the UI shows a localized label; fall back to
  // the raw key when the translation table doesn't cover it (forward
  // compat for new emotions).
  const dominantLabel = mood_dominant
    ? (t(`info.creatureState.moodDominant.${mood_dominant}`) || mood_dominant)
    : '—';

  const bondAxes: Array<[keyof typeof bond, string]> = [
    ['affection', t('info.creatureState.bondAxes.affection')],
    ['trust', t('info.creatureState.bondAxes.trust')],
    ['familiarity', t('info.creatureState.bondAxes.familiarity')],
    ['dependency', t('info.creatureState.bondAxes.dependency')],
  ];

  // Vitals — semantic direction: hunger/stress are bad when high.
  type VitalAxis = readonly [keyof typeof vitals, string, 'good' | 'warn'];
  const vitalAxes: readonly VitalAxis[] = [
    ['hunger', t('info.creatureState.vitalsAxes.hunger'), 'warn'],
    ['energy', t('info.creatureState.vitalsAxes.energy'), 'good'],
    ['stress', t('info.creatureState.vitalsAxes.stress'), 'warn'],
    ['cleanliness', t('info.creatureState.vitalsAxes.cleanliness'), 'good'],
  ];

  // ─── Compact "game UI" rendering for the VTuberTab hover overlay ─
  if (compact) {
    return (
      <div
        className="rounded-xl border border-[rgba(99,102,241,0.45)] shadow-[0_0_30px_rgba(99,102,241,0.25),inset_0_0_20px_rgba(0,0,0,0.6)] backdrop-blur-md p-3.5 w-[360px] text-[var(--text-primary)]"
        style={{
          background:
            'linear-gradient(160deg, rgba(15,18,38,0.92) 0%, rgba(28,16,46,0.92) 100%)',
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-2.5 pb-2 border-b border-[rgba(99,102,241,0.25)]">
          <div className="flex items-center gap-1.5">
            <Sparkles size={13} className="text-[#a5b4fc]" />
            <span className="text-[11px] font-bold uppercase tracking-[1px] text-[#c7d2fe]">
              {t('info.creatureState.title')}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-[10px]">
            <span className="px-1.5 py-0.5 rounded bg-[rgba(99,102,241,0.2)] text-[#e0e7ff] uppercase tracking-[0.8px] border border-[rgba(99,102,241,0.4)]">
              {progression.life_stage || '—'}
            </span>
            <span className="text-[#a5b4fc]">
              {t('info.creatureState.ageDays', { days: String(progression.age_days) })}
            </span>
          </div>
        </div>

        {/* Dominant mood pill */}
        <div className="mb-3 flex items-center justify-between text-[10px]">
          <span className="uppercase tracking-[0.8px] text-[#a5b4fc]">
            {t('info.creatureState.dominantMood')}
          </span>
          <span className="font-mono text-[#fde68a] uppercase">{dominantLabel}</span>
        </div>

        {/* Vitals */}
        <div className="mb-2.5">
          <div className="flex items-center gap-1 mb-1">
            <Battery size={11} className="text-[#a5b4fc]" />
            <span className="text-[10px] font-bold uppercase tracking-[1px] text-[#c7d2fe]">
              {t('info.creatureState.vitals')}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
            {vitalAxes.map(([key, label, tone]) => (
              <StatBar
                key={key}
                label={label}
                value={clamp100(vitals[key])}
                max={100}
                tone={tone}
                valueLabel={vitals[key].toFixed(0)}
              />
            ))}
          </div>
        </div>

        {/* Bond */}
        <div className="mb-2.5">
          <div className="flex items-center gap-1 mb-1">
            <Heart size={11} className="text-[#a5b4fc]" />
            <span className="text-[10px] font-bold uppercase tracking-[1px] text-[#c7d2fe]">
              {t('info.creatureState.bond')}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
            {bondAxes.map(([key, label]) => (
              <StatBar
                key={key}
                label={label}
                value={Math.max(-100, Math.min(100, bond[key]))}
                max={100}
                tone="info"
                valueLabel={bond[key].toFixed(1)}
              />
            ))}
          </div>
        </div>

        {/* Mood */}
        <div>
          <div className="flex items-center gap-1 mb-1">
            <Brain size={11} className="text-[#a5b4fc]" />
            <span className="text-[10px] font-bold uppercase tracking-[1px] text-[#c7d2fe]">
              {t('info.creatureState.mood')}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
            {moodAxes.map(([key, label]) => (
              <StatBar
                key={key}
                label={label}
                value={clamp01(mood[key]) * 100}
                max={100}
                tone="neutral"
                valueLabel={`${(clamp01(mood[key]) * 100).toFixed(0)}%`}
              />
            ))}
          </div>
        </div>

        {/* Footer: last interaction */}
        <div className="mt-2.5 pt-2 border-t border-[rgba(99,102,241,0.25)] flex items-center justify-between text-[9px] text-[#a5b4fc]">
          <span className="uppercase tracking-[0.8px]">
            {t('info.creatureState.lastInteraction')}
          </span>
          <span className="font-mono">{formatTimestamp(last_interaction_at)}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="mb-4 pb-4 border-b border-[var(--border-color)]">
      {/* Header: title + life-stage / dominant mood summary */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <Sparkles size={14} className="text-[var(--text-muted)]" />
          <span className="text-[12px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">
            {t('info.creatureState.title')}
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
          <span className="px-1.5 py-0.5 rounded bg-[var(--bg-tertiary)] text-[var(--text-primary)] uppercase tracking-[0.5px]">
            {progression.life_stage || '—'}
          </span>
          <span>
            {t('info.creatureState.ageDays', {
              days: String(progression.age_days),
            })}
          </span>
        </div>
      </div>

      {/* Top line: dominant mood + last interaction */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 mb-3">
        <div className="flex flex-col gap-0.5 py-2 px-3 bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)]">
          <span className="text-[10px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">
            {t('info.creatureState.dominantMood')}
          </span>
          <span
            className="text-[13px] text-[var(--text-primary)]"
            style={{ fontFamily: "'SF Mono', 'Fira Code', monospace" }}
          >
            {dominantLabel}
          </span>
        </div>
        <div className="flex flex-col gap-0.5 py-2 px-3 bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)]">
          <span className="text-[10px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">
            {t('info.creatureState.lastInteraction')}
          </span>
          <span
            className="text-[12px] text-[var(--text-primary)] break-all"
            style={{ fontFamily: "'SF Mono', 'Fira Code', monospace" }}
          >
            {formatTimestamp(last_interaction_at)}
          </span>
        </div>
      </div>

      {/* Vitals group */}
      <div className="mb-3">
        <div className="flex items-center gap-1.5 mb-1.5">
          <Battery size={12} className="text-[var(--text-muted)]" />
          <span className="text-[11px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">
            {t('info.creatureState.vitals')}
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {vitalAxes.map(([key, label, tone]) => (
            <StatBar
              key={key}
              label={label}
              value={clamp100(vitals[key])}
              max={100}
              tone={tone}
              valueLabel={vitals[key].toFixed(1)}
            />
          ))}
        </div>
      </div>

      {/* Bond group */}
      <div className="mb-3">
        <div className="flex items-center gap-1.5 mb-1.5">
          <Heart size={12} className="text-[var(--text-muted)]" />
          <span className="text-[11px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">
            {t('info.creatureState.bond')}
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {bondAxes.map(([key, label]) => (
            <StatBar
              key={key}
              label={label}
              // Bond axes are unbounded in the backend; clamp to 100
              // for visual stability while still showing the raw
              // value in the label.
              value={Math.max(-100, Math.min(100, bond[key]))}
              max={100}
              tone="info"
              valueLabel={bond[key].toFixed(2)}
            />
          ))}
        </div>
      </div>

      {/* Mood group */}
      <div>
        <div className="flex items-center gap-1.5 mb-1.5">
          <Brain size={12} className="text-[var(--text-muted)]" />
          <span className="text-[11px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">
            {t('info.creatureState.mood')}
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {moodAxes.map(([key, label]) => (
            <StatBar
              key={key}
              label={label}
              value={clamp01(mood[key]) * 100}
              max={100}
              tone="neutral"
              valueLabel={`${(clamp01(mood[key]) * 100).toFixed(0)}%`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
