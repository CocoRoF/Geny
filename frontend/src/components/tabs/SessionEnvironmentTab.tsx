'use client';

/**
 * SessionEnvironmentTab — per-session read-only view of the
 * EnvironmentManifest the session is bound to. Renamed from the
 * legacy "Graph" tab on 2026-04-20 when the product pivoted to the
 * environment-centric model: every session now runs through an
 * EnvironmentManifest, so showing a static 16-stage diagram no
 * longer reflects reality. This tab pulls the session's actual
 * manifest and renders the real stage list (active/inactive,
 * artifact, config, strategies, tool binding).
 *
 * Sessions that pre-date the environment migration have no env_id
 * bound — they still run the legacy preset. We detect that and
 * show a "bind an environment" CTA instead of faking stages.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Boxes,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Layers,
  Link2Off,
  RefreshCw,
  Settings2,
} from 'lucide-react';

import { useAppStore } from '@/store/useAppStore';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { useI18n } from '@/lib/i18n';
import { environmentApi } from '@/lib/environmentApi';
import type {
  EnvironmentDetail,
  StageManifestEntry,
} from '@/types/environment';

type CategoryKey = 'ingress' | 'preflight' | 'execution' | 'decision' | 'egress';

const CATEGORY_RANGES: { key: CategoryKey; min: number; max: number }[] = [
  { key: 'ingress', min: 1, max: 3 },
  { key: 'preflight', min: 4, max: 5 },
  { key: 'execution', min: 6, max: 11 },
  { key: 'decision', min: 12, max: 13 },
  { key: 'egress', min: 14, max: 16 },
];

const CATEGORY_CLASS: Record<CategoryKey, string> = {
  ingress: 'border-blue-500/30 bg-blue-500/5',
  preflight: 'border-yellow-500/30 bg-yellow-500/5',
  execution: 'border-green-500/30 bg-green-500/5',
  decision: 'border-purple-500/30 bg-purple-500/5',
  egress: 'border-orange-500/30 bg-orange-500/5',
};

function categoryOfOrder(order: number): CategoryKey {
  for (const r of CATEGORY_RANGES) {
    if (order >= r.min && order <= r.max) return r.key;
  }
  return 'execution';
}

function jsonPreview(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return String(value);
  }
}

function hasMeaningfulConfig(entry: StageManifestEntry): boolean {
  const cfgKeys = Object.keys(entry.config ?? {});
  const stratKeys = Object.keys(entry.strategies ?? {});
  const stratCfgKeys = Object.keys(entry.strategy_configs ?? {});
  const toolBinding = entry.tool_binding && entry.tool_binding.patterns.length > 0;
  const modelOverride = entry.model_override && Object.keys(entry.model_override).length > 0;
  return (
    cfgKeys.length > 0 ||
    stratKeys.length > 0 ||
    stratCfgKeys.length > 0 ||
    !!toolBinding ||
    !!modelOverride
  );
}

function StageCard({ entry }: { entry: StageManifestEntry }) {
  const { t } = useI18n();
  const cat = categoryOfOrder(entry.order);
  const catClass = CATEGORY_CLASS[cat];
  const [expanded, setExpanded] = useState(false);
  const meaningful = hasMeaningfulConfig(entry);

  return (
    <div
      className={`rounded-lg border ${catClass} ${entry.active ? '' : 'opacity-50'}`}
    >
      <button
        onClick={() => setExpanded(v => !v)}
        disabled={!meaningful}
        className="w-full flex items-center gap-3 py-2 px-3 bg-transparent border-none text-left cursor-pointer disabled:cursor-default"
      >
        <span className="text-[0.6875rem] font-mono text-[var(--text-muted)] w-7 shrink-0">
          {String(entry.order).padStart(2, '0')}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)] truncate">
              {entry.name}
            </span>
            <span className="text-[0.625rem] uppercase tracking-wide py-0.5 px-1.5 rounded-md border border-[var(--border-color)] text-[var(--text-muted)]">
              {t(`sessionEnvironmentTab.category.${cat}`)}
            </span>
            {entry.active ? (
              <span className="text-[0.625rem] font-semibold py-0.5 px-1.5 rounded-md bg-[rgba(34,197,94,0.15)] text-[#4ade80] border border-[rgba(34,197,94,0.35)]">
                {t('sessionEnvironmentTab.active')}
              </span>
            ) : (
              <span className="text-[0.625rem] font-semibold py-0.5 px-1.5 rounded-md bg-[var(--bg-tertiary)] text-[var(--text-muted)] border border-[var(--border-color)]">
                {t('sessionEnvironmentTab.inactive')}
              </span>
            )}
          </div>
          <div className="text-[0.6875rem] text-[var(--text-muted)] font-mono truncate mt-0.5">
            {entry.artifact}
          </div>
        </div>
        {meaningful && (
          <span className="shrink-0 text-[var(--text-muted)]">
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
        )}
      </button>
      {expanded && meaningful && (
        <div className="border-t border-[var(--border-color)] px-3 py-2 flex flex-col gap-2">
          {Object.keys(entry.config ?? {}).length > 0 && (
            <div className="flex flex-col gap-1">
              <div className="text-[0.625rem] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                {t('sessionEnvironmentTab.config')}
              </div>
              <pre className="text-[0.6875rem] leading-[1.5] font-mono text-[var(--text-secondary)] bg-[var(--bg-primary)] rounded-md border border-[var(--border-color)] px-2 py-1.5 overflow-auto max-h-[220px] whitespace-pre">
                {jsonPreview(entry.config)}
              </pre>
            </div>
          )}
          {Object.keys(entry.strategies ?? {}).length > 0 && (
            <div className="flex flex-col gap-1">
              <div className="text-[0.625rem] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                {t('sessionEnvironmentTab.strategies')}
              </div>
              <div className="flex flex-wrap gap-1">
                {Object.entries(entry.strategies).map(([slot, impl]) => (
                  <span
                    key={slot}
                    className="text-[0.6875rem] font-mono py-0.5 px-1.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[var(--text-secondary)]"
                    title={`${slot} = ${impl}`}
                  >
                    {slot}: <span className="text-[var(--text-primary)]">{impl}</span>
                  </span>
                ))}
              </div>
            </div>
          )}
          {entry.tool_binding && entry.tool_binding.patterns.length > 0 && (
            <div className="flex flex-col gap-1">
              <div className="text-[0.625rem] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                {t('sessionEnvironmentTab.toolBinding')}
                <span className="ml-1 font-mono text-[var(--text-secondary)] normal-case">
                  ({entry.tool_binding.mode})
                </span>
              </div>
              <div className="flex flex-wrap gap-1">
                {entry.tool_binding.patterns.map(p => (
                  <span
                    key={p}
                    className="text-[0.6875rem] font-mono py-0.5 px-1.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[var(--text-secondary)]"
                  >
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}
          {entry.model_override && Object.keys(entry.model_override).length > 0 && (
            <div className="flex flex-col gap-1">
              <div className="text-[0.625rem] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                {t('sessionEnvironmentTab.modelOverride')}
              </div>
              <pre className="text-[0.6875rem] leading-[1.5] font-mono text-[var(--text-secondary)] bg-[var(--bg-primary)] rounded-md border border-[var(--border-color)] px-2 py-1.5 overflow-auto max-h-[160px] whitespace-pre">
                {jsonPreview(entry.model_override)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function SessionEnvironmentTab() {
  const { selectedSessionId, sessions, setActiveTab } = useAppStore();
  const environments = useEnvironmentStore(s => s.environments);
  const loadEnvironments = useEnvironmentStore(s => s.loadEnvironments);
  const requestOpenEnvDrawer = useEnvironmentStore(s => s.requestOpenEnvDrawer);
  const { t } = useI18n();

  const session = useMemo(
    () => sessions.find(s => s.session_id === selectedSessionId),
    [sessions, selectedSessionId],
  );
  const sessionEnvId = session?.env_id ?? null;

  useEffect(() => {
    if (sessionEnvId && environments.length === 0) {
      void loadEnvironments();
    }
  }, [sessionEnvId, environments.length, loadEnvironments]);

  const envSummary = sessionEnvId
    ? environments.find(e => e.id === sessionEnvId) ?? null
    : null;
  const envMissing = !!sessionEnvId && environments.length > 0 && envSummary === null;

  // Local fetch of the full manifest — keeping it out of
  // `useEnvironmentStore.selectedEnvironment` avoids clobbering state
  // that EnvironmentDetailDrawer / BuilderTab may be relying on.
  const [manifestEnv, setManifestEnv] = useState<EnvironmentDetail | null>(null);
  const [manifestLoading, setManifestLoading] = useState(false);
  const [manifestError, setManifestError] = useState('');

  const fetchManifest = useCallback(
    async (envId: string) => {
      setManifestLoading(true);
      setManifestError('');
      try {
        const env = await environmentApi.get(envId);
        setManifestEnv(env);
      } catch (e) {
        setManifestError(e instanceof Error ? e.message : t('sessionEnvironmentTab.loadFailed'));
      } finally {
        setManifestLoading(false);
      }
    },
    [t],
  );

  useEffect(() => {
    if (!sessionEnvId) {
      setManifestEnv(null);
      setManifestError('');
      return;
    }
    if (manifestEnv?.id === sessionEnvId) return;
    void fetchManifest(sessionEnvId);
  }, [sessionEnvId, manifestEnv?.id, fetchManifest]);

  const openEnvInDrawer = () => {
    if (!sessionEnvId) return;
    requestOpenEnvDrawer(sessionEnvId);
    setActiveTab('environments');
  };

  const openEnvironmentsTab = () => {
    setActiveTab('environments');
  };

  const stages = useMemo<StageManifestEntry[]>(() => {
    const list = manifestEnv?.manifest?.stages ?? [];
    return [...list].sort((a, b) => a.order - b.order);
  }, [manifestEnv]);

  const stagesByCategory = useMemo(() => {
    const grouped: Record<CategoryKey, StageManifestEntry[]> = {
      ingress: [],
      preflight: [],
      execution: [],
      decision: [],
      egress: [],
    };
    for (const stage of stages) grouped[categoryOfOrder(stage.order)].push(stage);
    return grouped;
  }, [stages]);

  const activeCount = useMemo(() => stages.filter(s => s.active).length, [stages]);

  if (!session) {
    return (
      <div className="flex items-center justify-center h-full text-[var(--text-muted)] text-[0.875rem]">
        {t('sessionEnvironmentTab.selectSession')}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-auto">
      {/* Header */}
      <div className="shrink-0 px-5 py-4 border-b border-[var(--border-color)] flex flex-col gap-2">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex flex-col gap-0.5 min-w-0">
            <h2 className="text-[1rem] font-semibold text-[var(--text-primary)] flex items-center gap-2">
              <Boxes size={16} />
              {t('sessionEnvironmentTab.title')}
            </h2>
            <p className="text-[0.75rem] text-[var(--text-muted)] truncate">
              {t('sessionEnvironmentTab.sessionLine', {
                name: session.session_name || session.session_id.slice(0, 8),
                model: session.model || '—',
              })}
            </p>
          </div>
          {sessionEnvId && !envMissing && (
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                onClick={() => sessionEnvId && void fetchManifest(sessionEnvId)}
                disabled={manifestLoading}
                title={t('sessionEnvironmentTab.reload')}
                aria-label={t('sessionEnvironmentTab.reload')}
                className="flex items-center justify-center w-8 h-8 rounded-md bg-transparent border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <RefreshCw size={12} className={manifestLoading ? 'animate-spin' : ''} />
              </button>
              <button
                onClick={openEnvInDrawer}
                className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-semibold cursor-pointer border-none transition-colors"
              >
                <Settings2 size={12} />
                {t('sessionEnvironmentTab.openInEnvironments')}
              </button>
            </div>
          )}
        </div>

        {/* Env badge + stage count */}
        <div className="flex items-center flex-wrap gap-2">
          {sessionEnvId ? (
            envMissing ? (
              <span className="inline-flex items-center gap-1.5 py-1 px-2 rounded-md border border-red-500/40 bg-red-500/10 text-red-300 text-[0.6875rem] font-medium">
                <AlertTriangle size={11} />
                {t('sessionEnvironmentTab.envMissing')}
                <span className="font-mono opacity-70">{sessionEnvId.slice(0, 8)}</span>
              </span>
            ) : (
              <button
                onClick={openEnvInDrawer}
                title={sessionEnvId}
                className="inline-flex items-center gap-1.5 py-1 px-2 rounded-md border border-indigo-500/40 bg-indigo-500/10 text-indigo-300 text-[0.6875rem] font-medium hover:bg-indigo-500/20 hover:border-indigo-500/60 cursor-pointer transition-colors"
              >
                <Boxes size={11} />
                <span className="opacity-70">{t('sessionEnvironmentTab.environmentLabel')}:</span>
                <span>{envSummary?.name ?? t('sessionEnvironmentTab.envLoading')}</span>
                <ExternalLink size={11} className="opacity-60" />
              </button>
            )
          ) : (
            <span className="inline-flex items-center gap-1.5 py-1 px-2 rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-muted)] text-[0.6875rem] font-medium">
              <Link2Off size={11} />
              {t('sessionEnvironmentTab.noEnvBound')}
            </span>
          )}
          {stages.length > 0 && (
            <span className="inline-flex items-center gap-1 text-[0.6875rem] text-[var(--text-muted)]">
              <Layers size={11} />
              {t('sessionEnvironmentTab.stageCount', {
                active: String(activeCount),
                total: String(stages.length),
              })}
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 px-5 py-4">
        {!sessionEnvId ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
            <Link2Off size={28} className="text-[var(--text-muted)] opacity-60" />
            <p className="text-[0.875rem] text-[var(--text-secondary)] max-w-[420px]">
              {t('sessionEnvironmentTab.unboundHeadline')}
            </p>
            <p className="text-[0.75rem] text-[var(--text-muted)] max-w-[480px]">
              {t('sessionEnvironmentTab.unboundBody', {
                workflow: session.workflow_id || '—',
              })}
            </p>
            <button
              onClick={openEnvironmentsTab}
              className="mt-1 flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-semibold cursor-pointer border-none transition-colors"
            >
              <Boxes size={12} />
              {t('sessionEnvironmentTab.goToEnvironments')}
            </button>
          </div>
        ) : envMissing ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3 text-center">
            <AlertTriangle size={28} className="text-red-400 opacity-80" />
            <p className="text-[0.875rem] text-[var(--text-secondary)] max-w-[480px]">
              {t('sessionEnvironmentTab.envMissingHeadline')}
            </p>
            <p className="text-[0.75rem] text-[var(--text-muted)] max-w-[480px]">
              {t('sessionEnvironmentTab.envMissingBody')}
            </p>
          </div>
        ) : manifestLoading && !manifestEnv ? (
          <div className="flex items-center justify-center py-16 text-[0.875rem] text-[var(--text-muted)]">
            {t('sessionEnvironmentTab.loading')}
          </div>
        ) : manifestError ? (
          <div className="flex flex-col items-center justify-center py-10 gap-2 text-center">
            <AlertTriangle size={24} className="text-red-400 opacity-80" />
            <p className="text-[0.8125rem] text-[var(--danger-color)]">{manifestError}</p>
            <button
              onClick={() => sessionEnvId && void fetchManifest(sessionEnvId)}
              className="mt-1 flex items-center gap-1.5 py-1 px-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.75rem] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
            >
              <RefreshCw size={12} />
              {t('common.retry')}
            </button>
          </div>
        ) : stages.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 gap-2 text-center">
            <Layers size={24} className="text-[var(--text-muted)] opacity-60" />
            <p className="text-[0.8125rem] text-[var(--text-muted)]">
              {t('sessionEnvironmentTab.manifestEmpty')}
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            {CATEGORY_RANGES.map(({ key }) => {
              const entries = stagesByCategory[key];
              if (entries.length === 0) return null;
              return (
                <section key={key} className="flex flex-col gap-2">
                  <h3 className="text-[0.6875rem] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                    {t(`sessionEnvironmentTab.category.${key}`)}
                  </h3>
                  <div className="flex flex-col gap-2">
                    {entries.map(entry => (
                      <StageCard key={entry.order} entry={entry} />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
