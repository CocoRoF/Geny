'use client';

/**
 * Stage15HitlEditor — curated editor for s15_hitl (human-in-the-loop).
 *
 * Two strategy slots that almost everyone touches:
 *   - requester: null (always-approve passthrough) / callback (host
 *     callback) / pipeline_resume (pause + external decision API)
 *   - timeout: indefinite (wait forever) / auto_approve / auto_reject
 *     (the latter two read timeout_seconds from strategy_configs)
 *
 * Tile-pickers + a single conditional timeout_seconds field. Everything
 * else lives under "고급".
 */

import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Timer } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { catalogApi } from '@/lib/environmentApi';
import { localizeIntrospection } from '../stage_locale';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type {
  StageIntrospection,
  StageManifestEntry,
} from '@/types/environment';
import { Input } from '@/components/ui/input';
import StageGenericEditor from '../StageGenericEditor';

const REQUESTER_OPTIONS = [
  {
    id: 'null',
    titleKey: 'envManagement.stage15.requester.null.title',
    descKey: 'envManagement.stage15.requester.null.desc',
  },
  {
    id: 'callback',
    titleKey: 'envManagement.stage15.requester.callback.title',
    descKey: 'envManagement.stage15.requester.callback.desc',
  },
  {
    id: 'pipeline_resume',
    titleKey: 'envManagement.stage15.requester.pipeline_resume.title',
    descKey: 'envManagement.stage15.requester.pipeline_resume.desc',
  },
];

const TIMEOUT_OPTIONS = [
  {
    id: 'indefinite',
    titleKey: 'envManagement.stage15.timeout.indefinite.title',
    descKey: 'envManagement.stage15.timeout.indefinite.desc',
  },
  {
    id: 'auto_approve',
    titleKey: 'envManagement.stage15.timeout.auto_approve.title',
    descKey: 'envManagement.stage15.timeout.auto_approve.desc',
  },
  {
    id: 'auto_reject',
    titleKey: 'envManagement.stage15.timeout.auto_reject.title',
    descKey: 'envManagement.stage15.timeout.auto_reject.desc',
  },
];

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function Stage15HitlEditor({ order, entry }: Props) {
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

  const availableRequester = new Set(
    intro?.strategy_slots?.['requester']?.available_impls ?? [],
  );
  const availableTimeout = new Set(
    intro?.strategy_slots?.['timeout']?.available_impls ?? [],
  );

  const currentRequester =
    entry.strategies?.['requester'] ??
    intro?.strategy_slots?.['requester']?.current_impl ??
    'null';
  const currentTimeout =
    entry.strategies?.['timeout'] ??
    intro?.strategy_slots?.['timeout']?.current_impl ??
    'indefinite';

  const setRequester = (next: string) =>
    patchStage(order, {
      strategies: { ...(entry.strategies ?? {}), requester: next },
    });
  const setTimeoutStrategy = (next: string) =>
    patchStage(order, {
      strategies: { ...(entry.strategies ?? {}), timeout: next },
    });

  const timeoutCfg =
    (entry.strategy_configs?.[currentTimeout] as Record<string, unknown>) ?? {};
  const timeoutSeconds =
    typeof timeoutCfg.timeout_seconds === 'number'
      ? (timeoutCfg.timeout_seconds as number)
      : '';

  const setTimeoutSeconds = (raw: string) => {
    const n = raw === '' ? null : Number(raw);
    if (raw !== '' && (isNaN(n as number) || (n as number) < 0)) return;
    const nextCfg = { ...(entry.strategy_configs ?? {}) };
    nextCfg[currentTimeout] = {
      ...(nextCfg[currentTimeout] ?? {}),
      timeout_seconds: n,
    };
    patchStage(order, { strategy_configs: nextCfg });
  };

  const showTimeoutField =
    currentTimeout === 'auto_approve' || currentTimeout === 'auto_reject';

  return (
    <div className="flex flex-col gap-4">
      {/* ── Requester ── */}
      <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <header className="flex items-center gap-2">
          <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage15.requesterTitle')}
          </h4>
        </header>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          {REQUESTER_OPTIONS.map((opt) => {
            const available = availableRequester.has(opt.id);
            const active = currentRequester === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                disabled={!available && availableRequester.size > 0}
                onClick={() => setRequester(opt.id)}
                className={`flex items-start gap-2 p-2.5 rounded-md border text-left transition-colors ${
                  active
                    ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)]'
                    : 'border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:bg-[hsl(var(--accent))]'
                } ${
                  !available && availableRequester.size > 0
                    ? 'opacity-40 cursor-not-allowed'
                    : ''
                }`}
                title={!available ? t('envManagement.stage15.unavailable') : undefined}
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

      {/* ── Timeout ── */}
      <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <header className="flex items-center gap-2">
          <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage15.timeoutTitle')}
          </h4>
        </header>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          {TIMEOUT_OPTIONS.map((opt) => {
            const available = availableTimeout.has(opt.id);
            const active = currentTimeout === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                disabled={!available && availableTimeout.size > 0}
                onClick={() => setTimeoutStrategy(opt.id)}
                className={`flex items-start gap-2 p-2.5 rounded-md border text-left transition-colors ${
                  active
                    ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)]'
                    : 'border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:bg-[hsl(var(--accent))]'
                } ${
                  !available && availableTimeout.size > 0
                    ? 'opacity-40 cursor-not-allowed'
                    : ''
                }`}
                title={!available ? t('envManagement.stage15.unavailable') : undefined}
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

        {showTimeoutField && (
          <div className="flex flex-col gap-1 pt-2 border-t border-[hsl(var(--border))]">
            <label className="flex items-center gap-1.5 text-[0.75rem] font-medium text-[hsl(var(--foreground))]">
              <Timer className="w-3 h-3" />
              {t('envManagement.stage15.timeoutSecondsLabel')}
            </label>
            <Input
              type="number"
              min={0}
              value={timeoutSeconds === '' ? '' : String(timeoutSeconds)}
              onChange={(e) => setTimeoutSeconds(e.target.value)}
              placeholder="60"
              className="h-7 w-32 font-mono text-[0.75rem]"
            />
            <p className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
              {t('envManagement.stage15.timeoutSecondsHint')}
            </p>
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
          {t('envManagement.stage15.advancedTitle')}
          <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage15.advancedHint')}
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
