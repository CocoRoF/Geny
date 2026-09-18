'use client';

/**
 * When this agent speaks on its own.
 *
 * The runtime model is two-tier and weighted: situations (categories) carry
 * conditions and a weight, they reference prompts from a shared library with
 * their own weights, and firing is two rounds of weighted roulette. All of
 * that is right, and none of it is what someone wants to think about when the
 * question is "stop talking at night" or "say something else when I share my
 * screen".
 *
 * So this shows the two things that are actually decisions:
 *
 *   · how long the silence has to be before it says anything
 *   · for each situation: how often, and what it might say
 *
 * and expresses every condition in a sentence instead of a number. The
 * weights are levels relative to what the situation ships with, so "보통"
 * keeps the balance the ladder was designed with — the companion's "I'm
 * working" line stays dominant over small talk without anyone tuning 1000
 * against 5.
 *
 * Everything else in the manifest (tick interval, adaptive scaling, the
 * signal payload, per-reference weights) is left exactly as it was found.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { Plus, Trash2, X } from 'lucide-react';

import { agentApi } from '@/lib/api';
import { triggerPresetApi } from '@/lib/triggerPresetApi';
import { useI18n } from '@/lib/i18n';
import type {
  TriggerCategory,
  TriggerPresetManifest,
  TriggerPrompt,
} from '@/types/triggerPreset';

/** How often a situation comes up, as a share of what it ships with. */
const LEVELS = [
  { id: 'off', factor: 0 },
  { id: 'rare', factor: 0.2 },
  { id: 'normal', factor: 1 },
  { id: 'often', factor: 4 },
] as const;
type LevelId = (typeof LEVELS)[number]['id'];

const WAITS = [30, 60, 120, 300, 600];

function levelOf(weight: number, base: number): LevelId {
  if (weight <= 0) return 'off';
  const ratio = base > 0 ? weight / base : 1;
  // Nearest level in log space — 0.2 / 1 / 4 are multiplicative steps.
  let best: LevelId = 'normal';
  let bestGap = Infinity;
  for (const level of LEVELS) {
    if (level.factor === 0) continue;
    const gap = Math.abs(Math.log(ratio) - Math.log(level.factor));
    if (gap < bestGap) { bestGap = gap; best = level.id; }
  }
  return best;
}

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

export default function TriggerStudioModal({
  sessionId, onClose,
}: { sessionId: string; onClose: () => void }) {
  const { t, locale } = useI18n();
  const lang = (locale || 'ko').startsWith('en') ? 'en' : 'ko';

  const [presetId, setPresetId] = useState<string | null>(null);
  const [manifest, setManifest] = useState<TriggerPresetManifest | null>(null);
  /** The shipped weights, so "보통" means "as designed" for each situation. */
  const [baseWeights, setBaseWeights] = useState<Record<string, number>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Its own ladder, or a private copy of what it is already running.
        const own = await agentApi.makeOwnTriggerPreset(sessionId);
        if (cancelled) return;
        setPresetId(own.trigger_preset_id);
        setManifest(own.manifest as TriggerPresetManifest);
        try {
          const shipped = await triggerPresetApi.defaults();
          if (!cancelled) {
            setBaseWeights(Object.fromEntries(
              (shipped.manifest.categories || []).map((c) => [c.id, c.weight]),
            ));
          }
        } catch {
          /* levels fall back to the situation's own weight */
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => { cancelled = true; };
  }, [sessionId]);

  const promptsById = useMemo(() => {
    const map: Record<string, TriggerPrompt> = {};
    for (const p of manifest?.prompts ?? []) map[p.id] = p;
    return map;
  }, [manifest]);

  const patch = useCallback((fn: (m: TriggerPresetManifest) => void) => {
    setManifest((prev) => {
      if (!prev) return prev;
      const next = clone(prev);
      fn(next);
      return next;
    });
  }, []);

  /** One sentence describing when a situation applies. */
  const whenText = (c: TriggerCategory): string => {
    const parts: string[] = [];
    if (c.requires_screen_active) parts.push(t('triggerStudio.when.screen') ?? '화면을 공유하는 동안');
    if (c.requires_sub_worker_busy) parts.push(t('triggerStudio.when.helperBusy') ?? '동료가 일하는 중일 때');
    if (c.requires_sub_worker_idle) parts.push(t('triggerStudio.when.helperIdle') ?? '동료가 쉬고 있을 때');
    if (c.time_window) {
      // The hours it actually means, from this ladder's own boundaries — the
      // bare word repeats the situation's name and says nothing.
      const b = manifest?.time_boundaries;
      const from = b?.[`${c.time_window}_start` as keyof typeof b] as number | undefined;
      const order = ['morning', 'afternoon', 'evening', 'night'] as const;
      const nextKey = order[(order.indexOf(c.time_window) + 1) % order.length];
      const to = b?.[`${nextKey}_start` as keyof typeof b] as number | undefined;
      parts.push(
        from != null && to != null
          ? (t('triggerStudio.when.hours') ?? '{a}시~{b}시')
            .replace('{a}', String(from)).replace('{b}', String(to))
          : (t(`triggerStudio.when.${c.time_window}`) ?? c.time_window),
      );
    }
    if (c.consec_max === 0) parts.push(t('triggerStudio.when.first') ?? '대화가 끊긴 직후');
    else if (c.consec_min > 0 && c.consec_max) {
      parts.push((t('triggerStudio.when.between') ?? '혼잣말이 {a}~{b}번 이어졌을 때')
        .replace('{a}', String(c.consec_min)).replace('{b}', String(c.consec_max)));
    } else if (c.consec_min > 0) {
      parts.push((t('triggerStudio.when.after') ?? '혼잣말이 {a}번 넘게 이어졌을 때')
        .replace('{a}', String(c.consec_min)));
    }
    if (parts.length === 0) parts.push(t('triggerStudio.when.any') ?? '조용할 때 언제든');
    if (c.cooldown_seconds > 0) {
      parts.push((t('triggerStudio.when.cooldown') ?? '{n}초에 한 번까지')
        .replace('{n}', String(Math.round(c.cooldown_seconds))));
    }
    return parts.join(' · ');
  };

  const setLevel = (cat: TriggerCategory, level: LevelId) => {
    const base = baseWeights[cat.id] ?? (cat.weight > 0 ? cat.weight : 55);
    const factor = LEVELS.find((l) => l.id === level)!.factor;
    patch((m) => {
      const target = m.categories.find((c) => c.id === cat.id);
      if (target) target.weight = Math.round(base * factor * 100) / 100;
    });
  };

  const sentencesOf = (cat: TriggerCategory): { promptId: string; text: string }[] =>
    cat.prompt_refs.map((ref) => ({
      promptId: ref.prompt_id,
      text: promptsById[ref.prompt_id]?.content?.[lang]
        ?? Object.values(promptsById[ref.prompt_id]?.content ?? {})[0]
        ?? '',
    }));

  const editSentence = (promptId: string, text: string) => {
    patch((m) => {
      const prompt = m.prompts.find((p) => p.id === promptId);
      if (prompt) prompt.content = { ...prompt.content, [lang]: text };
    });
  };

  const addSentence = (cat: TriggerCategory) => {
    patch((m) => {
      const id = `${cat.id}-${Date.now().toString(36)}`;
      m.prompts.push({ id, label: '', content: { [lang]: '' }, tags: [] });
      const target = m.categories.find((c) => c.id === cat.id);
      if (target) target.prompt_refs.push({ prompt_id: id, weight: 1 });
    });
  };

  const removeSentence = (cat: TriggerCategory, promptId: string) => {
    patch((m) => {
      const target = m.categories.find((c) => c.id === cat.id);
      if (target) target.prompt_refs = target.prompt_refs.filter((r) => r.prompt_id !== promptId);
      // Drop the prompt itself only when nothing else points at it.
      const stillUsed = m.categories.some((c) => c.prompt_refs.some((r) => r.prompt_id === promptId));
      if (!stillUsed) m.prompts = m.prompts.filter((p) => p.id !== promptId);
    });
  };

  const save = async () => {
    if (!presetId || !manifest) return;
    setSaving(true);
    setError('');
    try {
      await triggerPresetApi.replaceManifest(presetId, manifest);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  if (typeof document === 'undefined') return null;

  const wait = manifest?.timing.base_idle_seconds ?? 60;

  return createPortal(
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 p-3 md:p-6"
      role="dialog"
      aria-modal="true"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="flex flex-col w-full max-w-[860px] h-[min(88vh,900px)] rounded-[var(--border-radius)] border border-[var(--border-color)] bg-[var(--bg-primary)] shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between shrink-0 py-3 px-4 md:px-5 border-b border-[var(--border-color)]">
          <div className="flex flex-col">
            <span className="text-[0.9375rem] font-semibold text-[var(--text-primary)]">
              {t('triggerStudio.title') ?? '먼저 말 걸기'}
            </span>
            <span className="text-[11.5px] text-[var(--text-muted)]">
              {t('triggerStudio.subtitle') ?? '조용할 때 이 에이전트가 스스로 꺼내는 말입니다.'}
            </span>
          </div>
          <button
            type="button" onClick={onClose} aria-label={t('common.close') ?? '닫기'}
            className="flex items-center justify-center w-7 h-7 rounded-md bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] border-none cursor-pointer transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-auto p-4 md:p-5">
          {busy && <div className="text-[12.5px] text-[var(--text-muted)]">{t('common.loading') ?? '읽는 중…'}</div>}
          {error && <div className="mb-3 text-[12px] text-[var(--danger-color)]">{error}</div>}

          {manifest && (
            <>
              {/* ── how long the silence has to be ── */}
              <section className="mb-5">
                <div className="text-[12px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)] mb-2">
                  {t('triggerStudio.waitTitle') ?? '얼마나 기다렸다가'}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {WAITS.map((seconds) => (
                    <button
                      key={seconds}
                      type="button"
                      onClick={() => patch((m) => {
                        m.timing.base_idle_seconds = seconds;
                        if (m.timing.max_idle_seconds < seconds) m.timing.max_idle_seconds = seconds;
                      })}
                      className={`py-1.5 px-3 text-[12.5px] rounded-md border cursor-pointer transition-colors ${
                        wait === seconds
                          ? 'border-[var(--primary-color)] bg-[var(--primary-subtle)] text-[var(--primary-color)]'
                          : 'border-[var(--border-color)] bg-[var(--bg-secondary)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
                      }`}
                    >
                      {seconds < 60
                        ? (t('triggerStudio.seconds') ?? '{n}초').replace('{n}', String(seconds))
                        : (t('triggerStudio.minutes') ?? '{n}분').replace('{n}', String(seconds / 60))}
                    </button>
                  ))}
                </div>
                <p className="mt-1.5 text-[11.5px] text-[var(--text-muted)] leading-relaxed">
                  {t('triggerStudio.waitHelp')
                    ?? '이만큼 말이 없으면 먼저 말을 겁니다. 혼잣말이 이어지면 간격은 스스로 늘어납니다.'}
                </p>
              </section>

              {/* ── the situations ── */}
              <section>
                <div className="text-[12px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)] mb-2">
                  {t('triggerStudio.situations') ?? '어떤 때 무슨 말을'}
                </div>
                <div className="flex flex-col gap-2">
                  {manifest.categories.map((cat) => {
                    const base = baseWeights[cat.id] ?? (cat.weight > 0 ? cat.weight : 55);
                    const level = levelOf(cat.weight, base);
                    const expanded = open === cat.id;
                    return (
                      <div
                        key={cat.id}
                        className={`rounded-md border ${level === 'off' ? 'border-[var(--border-color)] opacity-60' : 'border-[var(--border-color)]'} bg-[var(--bg-secondary)]`}
                      >
                        <div className="flex items-center gap-2 p-2.5">
                          <button
                            type="button"
                            onClick={() => setOpen(expanded ? null : cat.id)}
                            className="flex-1 min-w-0 text-left bg-transparent border-none cursor-pointer p-0"
                          >
                            <div className="flex items-center gap-1.5">
                              <span className="text-[13px] font-medium text-[var(--text-primary)]">
                                {cat.label || cat.id}
                              </span>
                              {cat.kind === 'activity' && (
                                <span className="px-1.5 py-0.5 rounded text-[10px] bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
                                  {t('triggerStudio.kindActivity') ?? '행동'}
                                </span>
                              )}
                            </div>
                            <div className="text-[11.5px] text-[var(--text-muted)] mt-0.5">{whenText(cat)}</div>
                          </button>
                          <div className="flex shrink-0 rounded-md border border-[var(--border-color)] overflow-hidden">
                            {LEVELS.map((l) => (
                              <button
                                key={l.id}
                                type="button"
                                onClick={() => setLevel(cat, l.id)}
                                className={`py-1 px-2 text-[11.5px] border-none cursor-pointer transition-colors ${
                                  level === l.id
                                    ? 'bg-[var(--primary-color)] text-white'
                                    : 'bg-[var(--bg-primary)] text-[var(--text-muted)] hover:bg-[var(--bg-hover)]'
                                }`}
                              >
                                {t(`triggerStudio.level.${l.id}`) ?? l.id}
                              </button>
                            ))}
                          </div>
                        </div>

                        {expanded && (
                          <div className="px-2.5 pb-2.5 flex flex-col gap-1.5">
                            {sentencesOf(cat).map(({ promptId, text }) => (
                              <div key={promptId} className="flex items-start gap-1.5">
                                <textarea
                                  value={text}
                                  onChange={(e) => editSentence(promptId, e.target.value)}
                                  rows={2}
                                  placeholder={t('triggerStudio.sentencePlaceholder') ?? '이 상황에서 할 말'}
                                  className="flex-1 min-w-0 py-1.5 px-2 rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] text-[12px] text-[var(--text-primary)] resize-y"
                                />
                                <button
                                  type="button"
                                  onClick={() => removeSentence(cat, promptId)}
                                  aria-label={t('common.delete') ?? '삭제'}
                                  className="flex items-center justify-center w-7 h-7 shrink-0 rounded-md bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--danger-color)] border-none cursor-pointer"
                                >
                                  <Trash2 size={13} />
                                </button>
                              </div>
                            ))}
                            <button
                              type="button"
                              onClick={() => addSentence(cat)}
                              className="self-start inline-flex items-center gap-1 py-1 px-2 text-[11.5px] rounded-md border border-dashed border-[var(--border-color)] bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer"
                            >
                              <Plus size={12} />
                              {t('triggerStudio.addSentence') ?? '할 말 추가'}
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            </>
          )}
        </div>

        <div className="flex justify-end items-center gap-2 shrink-0 py-3 px-4 md:px-5 border-t border-[var(--border-color)]">
          <button
            type="button" onClick={onClose}
            className="py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer border border-[var(--border-color)]"
          >
            {t('common.cancel') ?? '취소'}
          </button>
          <button
            type="button" onClick={save} disabled={saving || busy || !manifest}
            className="py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer border-none disabled:opacity-50"
          >
            {saving ? (t('common.saving') ?? '저장 중…') : (t('common.save') ?? '저장')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
