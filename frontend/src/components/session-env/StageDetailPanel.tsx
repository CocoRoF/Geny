'use client';

/**
 * StageDetailPanel — slide-in right panel showing static stage metadata
 * merged with the manifest's live config. Ported from geny-executor-web
 * but adapted for Geny's `StageManifestEntry` (strategies is a
 * Record<slot,impl>, not an array of introspections) and stripped of
 * any execution-state hooks.
 */

import { X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import type { StageManifestEntry } from '@/types/environment';
import {
  getCategoryColor,
  getStageMetaByOrder,
  inferCategoryFromOrder,
} from './stageMetadata';

interface StageDetailPanelProps {
  order: number;
  entry: StageManifestEntry | undefined;
  onClose: () => void;
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="px-5 py-4"
      style={{ borderBottom: '1px solid var(--pipe-border)' }}
    >
      <h4
        className="text-[10px] uppercase tracking-[0.18em] font-semibold mb-3"
        style={{ color: 'var(--pipe-text-muted)' }}
      >
        {title}
      </h4>
      {children}
    </div>
  );
}

function Badge({
  label,
  accent,
  bg,
}: {
  label: string;
  accent: string;
  bg: string;
}) {
  return (
    <span
      className="text-[10px] px-2.5 py-1 rounded-full font-medium tracking-wide"
      style={{ background: bg, color: accent }}
    >
      {label}
    </span>
  );
}

export default function StageDetailPanel({
  order,
  entry,
  onClose,
}: StageDetailPanelProps) {
  const { t, locale } = useI18n();
  const meta = getStageMetaByOrder(order, locale);
  const category = meta?.category ?? inferCategoryFromOrder(order);
  const catColor = getCategoryColor(category);

  const isActive = !!entry?.active;
  const isPresent = !!entry;
  const currentStrategies: Record<string, string> = entry?.strategies ?? {};

  return (
    <>
      {/* Backdrop — always a dark scrim so the slide-in panel has
          separation from the canvas even in light mode. */}
      <div
        className="fixed inset-0 z-40"
        style={{ background: 'rgba(0,0,0,0.4)' }}
        onClick={onClose}
      />

      {/* Panel */}
      <div
        className="fixed right-0 top-0 bottom-0 w-[420px] max-w-[100vw] overflow-y-auto z-50 pipe-slide-in"
        style={{
          background: 'var(--pipe-bg-secondary)',
          borderLeft: '1px solid var(--pipe-border)',
          boxShadow: 'var(--shadow-lg)',
        }}
      >
        {/* Header */}
        <div
          className="p-5"
          style={{ borderBottom: '1px solid var(--pipe-border)' }}
        >
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-4 min-w-0">
              <div
                className="w-12 h-12 rounded-full flex items-center justify-center text-base font-bold pipe-mono shrink-0"
                style={{
                  border: `2px solid ${catColor.accent}`,
                  color: catColor.accent,
                  background: catColor.bg,
                  boxShadow: `0 0 16px ${catColor.border}`,
                }}
              >
                {order}
              </div>
              <div className="min-w-0">
                <h3
                  className="pipe-serif text-xl font-bold leading-tight truncate"
                  style={{ color: 'var(--pipe-text-primary)' }}
                >
                  {meta?.displayName ?? entry?.name ?? `Stage ${order}`}
                </h3>
                <span
                  className="text-[10px] uppercase tracking-[0.2em] font-medium"
                  style={{ color: catColor.accent }}
                >
                  {meta?.categoryLabel ?? category.replace('_', ' ')}
                </span>
              </div>
            </div>
            <button
              onClick={onClose}
              aria-label={t('common.close')}
              className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 transition-colors cursor-pointer"
              style={{
                color: 'var(--pipe-text-muted)',
                background: 'var(--pipe-bg-tertiary)',
                border: '1px solid var(--pipe-border)',
              }}
            >
              <X size={14} />
            </button>
          </div>

          {/* Status badges */}
          <div className="mt-3 flex flex-wrap gap-2">
            <Badge
              label={
                isPresent
                  ? isActive
                    ? t('sessionEnvironmentTab.active')
                    : t('sessionEnvironmentTab.inactive')
                  : t('sessionEnvironmentTab.pipeline.notInManifest')
              }
              accent={
                isPresent
                  ? isActive
                    ? 'var(--pipe-green)'
                    : 'var(--pipe-text-muted)'
                  : 'var(--pipe-text-muted)'
              }
              bg={
                isPresent && isActive
                  ? 'color-mix(in srgb, var(--pipe-green) 14%, transparent)'
                  : 'var(--pipe-bg-tertiary)'
              }
            />
            {meta && (
              <>
                <Badge
                  label={`${t('sessionEnvironmentTab.pipeline.phase')} ${meta.phase}`}
                  accent="var(--pipe-accent)"
                  bg="var(--pipe-accent-dim)"
                />
                {meta.canBypass && (
                  <Badge
                    label={t('sessionEnvironmentTab.pipeline.bypassable')}
                    accent="var(--pipe-cyan)"
                    bg="color-mix(in srgb, var(--pipe-cyan) 12%, transparent)"
                  />
                )}
              </>
            )}
          </div>

          {/* Artifact line */}
          {entry?.artifact && (
            <div
              className="pipe-mono mt-3 text-[11px] flex items-center gap-2"
              style={{ color: 'var(--pipe-text-muted)' }}
            >
              <span
                className="uppercase tracking-wider text-[9px]"
                style={{ color: 'var(--pipe-text-muted)' }}
              >
                {t('sessionEnvironmentTab.pipeline.artifact')}
              </span>
              <span style={{ color: 'var(--pipe-text-secondary)' }}>
                {entry.artifact}
              </span>
            </div>
          )}
        </div>

        {/* Description */}
        {meta && (
          <Section title={t('sessionEnvironmentTab.pipeline.overview')}>
            <p
              className="text-[13px] leading-[1.7]"
              style={{ color: 'var(--pipe-text-primary)' }}
            >
              {meta.detailedDescription}
            </p>
            {meta.canBypass && meta.bypassCondition && (
              <div
                className="mt-3 rounded-lg px-3 py-2 text-[11px]"
                style={{
                  background:
                    'color-mix(in srgb, var(--pipe-cyan) 7%, transparent)',
                  border:
                    '1px solid color-mix(in srgb, var(--pipe-cyan) 18%, transparent)',
                  color: 'var(--pipe-cyan)',
                }}
              >
                <span className="font-semibold">
                  {t('sessionEnvironmentTab.pipeline.bypass')}:
                </span>{' '}
                {meta.bypassCondition}
              </div>
            )}
          </Section>
        )}

        {/* Technical Behavior */}
        {meta && meta.technicalBehavior.length > 0 && (
          <Section
            title={t('sessionEnvironmentTab.pipeline.technicalBehavior')}
          >
            <ul className="space-y-2">
              {meta.technicalBehavior.map((item, i) => (
                <li key={i} className="flex gap-2.5 text-[12px] leading-relaxed">
                  <span
                    className="mt-1.5 w-1 h-1 rounded-full shrink-0"
                    style={{ background: catColor.accent }}
                  />
                  <span style={{ color: 'var(--pipe-text-secondary)' }}>
                    {item}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {/* Strategy Slots (metadata catalog) — highlight the impl picked
            by the manifest, if any. */}
        {meta && meta.strategies.length > 0 && (
          <Section title={t('sessionEnvironmentTab.pipeline.strategySlots')}>
            <div className="space-y-4">
              {meta.strategies.map((slot) => {
                const currentImpl = findManifestImplForSlot(
                  slot.slot,
                  currentStrategies,
                );
                return (
                  <div key={slot.slot}>
                    <div
                      className="text-[11px] font-semibold uppercase tracking-wider mb-2"
                      style={{ color: catColor.accent }}
                    >
                      {slot.slot}
                    </div>
                    <div className="space-y-1.5">
                      {slot.options.map((opt) => {
                        const isCurrent = currentImpl === opt.name;
                        return (
                          <div
                            key={opt.name}
                            className="rounded-lg px-3 py-2.5 flex gap-3 items-start"
                            style={{
                              background: isCurrent
                                ? catColor.bg
                                : 'var(--pipe-bg-tertiary)',
                              border: `1px solid ${isCurrent ? catColor.border : 'var(--pipe-border)'}`,
                            }}
                          >
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span
                                  className="pipe-mono text-[11px] font-medium"
                                  style={{
                                    color: isCurrent
                                      ? catColor.accent
                                      : 'var(--pipe-text-primary)',
                                  }}
                                >
                                  {opt.name}
                                </span>
                                {isCurrent && (
                                  <span
                                    className="text-[8px] px-1.5 py-0.5 rounded-full font-bold uppercase tracking-wider"
                                    style={{
                                      background: catColor.accent,
                                      color: '#ffffff',
                                    }}
                                  >
                                    {t('sessionEnvironmentTab.pipeline.inUse')}
                                  </span>
                                )}
                              </div>
                              <p
                                className="mt-1 text-[11px] leading-relaxed"
                                style={{ color: 'var(--pipe-text-muted)' }}
                              >
                                {opt.description}
                              </p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </Section>
        )}

        {/* Live Configuration (from the manifest) */}
        {isPresent && hasLiveConfig(entry) && (
          <Section title={t('sessionEnvironmentTab.pipeline.currentConfig')}>
            <div className="space-y-3">
              {Object.keys(currentStrategies).length > 0 && (
                <div
                  className="rounded-lg p-3"
                  style={{
                    background: 'var(--pipe-bg-tertiary)',
                    border: '1px solid var(--pipe-border)',
                  }}
                >
                  <div
                    className="text-[10px] uppercase tracking-widest mb-2"
                    style={{ color: 'var(--pipe-text-muted)' }}
                  >
                    {t('sessionEnvironmentTab.strategies')}
                  </div>
                  <div className="flex flex-col gap-1.5">
                    {Object.entries(currentStrategies).map(([slot, impl]) => (
                      <div
                        key={slot}
                        className="flex items-center justify-between gap-2"
                      >
                        <span
                          className="pipe-mono text-[11px]"
                          style={{ color: 'var(--pipe-text-secondary)' }}
                        >
                          {slot}
                        </span>
                        <span
                          className="pipe-mono text-[11px] font-medium"
                          style={{ color: catColor.accent }}
                        >
                          {impl}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {Object.keys(entry.config ?? {}).length > 0 && (
                <JsonBlock
                  label={t('sessionEnvironmentTab.config')}
                  value={entry.config}
                />
              )}

              {Object.keys(entry.strategy_configs ?? {}).length > 0 && (
                <JsonBlock
                  label={t('sessionEnvironmentTab.pipeline.strategyConfigs')}
                  value={entry.strategy_configs}
                />
              )}

              {(() => {
                // Cycle 20260427_1 — StageToolBinding shape switched
                // from {mode, patterns} (placeholder) to the executor's
                // canonical {allowed, blocked, extra_context}. Render
                // both the mode (derived from which list is non-empty)
                // and the entries.
                const tb = entry.tool_binding;
                if (!tb) return null;
                const allowed = tb.allowed ?? [];
                const blocked = tb.blocked ?? [];
                const items: Array<{ key: string; tone: 'allow' | 'deny' }> = [
                  ...allowed.map((p) => ({ key: p, tone: 'allow' as const })),
                  ...blocked.map((p) => ({ key: p, tone: 'deny' as const })),
                ];
                if (items.length === 0) return null;
                const mode =
                  allowed.length > 0 && blocked.length === 0
                    ? 'allowlist'
                    : allowed.length === 0 && blocked.length > 0
                      ? 'blocklist'
                      : 'mixed';
                return (
                  <div
                    className="rounded-lg p-3"
                    style={{
                      background: 'var(--pipe-bg-tertiary)',
                      border: '1px solid var(--pipe-border)',
                    }}
                  >
                    <div
                      className="text-[10px] uppercase tracking-widest mb-2"
                      style={{ color: 'var(--pipe-text-muted)' }}
                    >
                      {t('sessionEnvironmentTab.toolBinding')}
                      <span
                        className="pipe-mono ml-2 normal-case"
                        style={{ color: 'var(--pipe-text-secondary)' }}
                      >
                        ({mode})
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {items.map((it) => (
                        <span
                          key={`${it.tone}_${it.key}`}
                          className="pipe-mono text-[10px] px-1.5 py-0.5 rounded border"
                          style={{
                            background:
                              it.tone === 'deny'
                                ? 'rgba(239, 68, 68, 0.08)'
                                : 'var(--pipe-bg-primary)',
                            color:
                              it.tone === 'deny'
                                ? 'rgb(220, 38, 38)'
                                : 'var(--pipe-text-secondary)',
                            borderColor:
                              it.tone === 'deny'
                                ? 'rgba(239, 68, 68, 0.3)'
                                : 'var(--pipe-border)',
                          }}
                        >
                          {it.tone === 'deny' ? '−' : '+'} {it.key}
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })()}

              {entry.model_override &&
                Object.keys(entry.model_override).length > 0 && (
                  <JsonBlock
                    label={t('sessionEnvironmentTab.modelOverride')}
                    value={entry.model_override}
                  />
                )}
            </div>
          </Section>
        )}

        {/* Architecture */}
        {meta?.architectureNotes && (
          <Section title={t('sessionEnvironmentTab.pipeline.architecture')}>
            <div
              className="rounded-lg p-3.5 text-[12px] leading-[1.7]"
              style={{
                background: 'var(--pipe-bg-primary)',
                border: '1px solid var(--pipe-border)',
                color: 'var(--pipe-text-secondary)',
              }}
            >
              {meta.architectureNotes}
            </div>
          </Section>
        )}

        <div className="h-8" />
      </div>
    </>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  let text: string;
  try {
    text = JSON.stringify(value ?? {}, null, 2);
  } catch {
    text = String(value);
  }
  return (
    <div
      className="rounded-lg p-3"
      style={{
        background: 'var(--pipe-bg-tertiary)',
        border: '1px solid var(--pipe-border)',
      }}
    >
      <div
        className="text-[10px] uppercase tracking-widest mb-2"
        style={{ color: 'var(--pipe-text-muted)' }}
      >
        {label}
      </div>
      <pre
        className="pipe-mono text-[11px] leading-[1.5] whitespace-pre overflow-auto max-h-[220px]"
        style={{ color: 'var(--pipe-text-secondary)' }}
      >
        {text}
      </pre>
    </div>
  );
}

function hasLiveConfig(entry: StageManifestEntry): boolean {
  const strat = Object.keys(entry.strategies ?? {}).length;
  const stratCfg = Object.keys(entry.strategy_configs ?? {}).length;
  const cfg = Object.keys(entry.config ?? {}).length;
  // Cycle 20260427_1 — tool_binding shape: {allowed, blocked} (canonical).
  const tbBinding = entry.tool_binding;
  const tb =
    !!tbBinding &&
    ((tbBinding.allowed?.length ?? 0) > 0 || (tbBinding.blocked?.length ?? 0) > 0);
  const mo = entry.model_override && Object.keys(entry.model_override).length > 0;
  return strat + stratCfg + cfg > 0 || !!tb || !!mo;
}

/**
 * Manifest strategy keys come in various casings (snake_case like
 * `memory_strategy`, `input_validator`). Metadata slot labels are
 * display strings ("Validator", "Normalizer", "Update Strategy").
 * We match leniently: exact → lowercased → alnum-prefix.
 */
function findManifestImplForSlot(
  slotLabel: string,
  manifestStrategies: Record<string, string>,
): string | undefined {
  const slots = Object.keys(manifestStrategies);
  if (slots.length === 0) return undefined;

  const normalize = (s: string) =>
    s.toLowerCase().replace(/[^a-z0-9]+/g, '');

  const target = normalize(slotLabel);

  // 1. Exact normalized match
  const exact = slots.find((k) => normalize(k) === target);
  if (exact) return manifestStrategies[exact];

  // 2. Contains-match in either direction
  const contains = slots.find((k) => {
    const kn = normalize(k);
    return kn.includes(target) || target.includes(kn);
  });
  if (contains) return manifestStrategies[contains];

  return undefined;
}
