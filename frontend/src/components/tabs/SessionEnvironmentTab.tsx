'use client';

/**
 * SessionEnvironmentTab — per-session read-only view of the
 * EnvironmentManifest the session is bound to, rendered as the
 * 16-stage pipeline canvas (visually mirrors geny-executor-web's
 * pipeline page). Execution state is intentionally absent — this
 * tab answers "which environment is applied to this session?",
 * not "is it running right now?".
 *
 * Sessions that pre-date the environment migration have no env_id
 * and still run the legacy preset; they get a "bind an environment"
 * CTA instead of a faked pipeline.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Boxes,
  Code2,
  ExternalLink,
  Link2Off,
  Maximize2,
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
import PipelineCanvas from '@/components/session-env/PipelineCanvas';
import StageDetailPanel from '@/components/session-env/StageDetailPanel';
import CodeViewModal from '@/components/session-env/CodeViewModal';

export default function SessionEnvironmentTab() {
  const { selectedSessionId, sessions, setActiveTab } = useAppStore();
  const environments = useEnvironmentStore((s) => s.environments);
  const loadEnvironments = useEnvironmentStore((s) => s.loadEnvironments);
  const requestOpenEnvDrawer = useEnvironmentStore(
    (s) => s.requestOpenEnvDrawer,
  );
  const { t } = useI18n();

  const session = useMemo(
    () => sessions.find((s) => s.session_id === selectedSessionId),
    [sessions, selectedSessionId],
  );
  const sessionEnvId = session?.env_id ?? null;

  useEffect(() => {
    if (sessionEnvId && environments.length === 0) {
      void loadEnvironments();
    }
  }, [sessionEnvId, environments.length, loadEnvironments]);

  const envSummary = sessionEnvId
    ? environments.find((e) => e.id === sessionEnvId) ?? null
    : null;
  const envMissing =
    !!sessionEnvId && environments.length > 0 && envSummary === null;

  // Local manifest fetch — kept out of useEnvironmentStore.selectedEnvironment
  // so we don't clobber state other views (Builder, Drawer) rely on.
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
        setManifestError(
          e instanceof Error
            ? e.message
            : t('sessionEnvironmentTab.loadFailed'),
        );
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

  const stages = useMemo<StageManifestEntry[]>(() => {
    const list = manifestEnv?.manifest?.stages ?? [];
    return [...list].sort((a, b) => a.order - b.order);
  }, [manifestEnv]);

  const stageByOrder = useMemo(() => {
    const m = new Map<number, StageManifestEntry>();
    for (const s of stages) m.set(s.order, s);
    return m;
  }, [stages]);

  const activeCount = useMemo(
    () => stages.filter((s) => s.active).length,
    [stages],
  );

  // Selected stage (for detail panel)
  const [selectedOrder, setSelectedOrder] = useState<number | null>(null);
  useEffect(() => {
    // Clear selection whenever the session / env changes
    setSelectedOrder(null);
  }, [selectedSessionId, sessionEnvId]);

  // Code view
  const [codeOpen, setCodeOpen] = useState(false);

  // Canvas reset
  const resetViewRef = useRef<(() => void) | null>(null);
  const handleReset = () => {
    resetViewRef.current?.();
  };

  const openEnvInDrawer = () => {
    if (!sessionEnvId) return;
    requestOpenEnvDrawer(sessionEnvId);
    setActiveTab('environments');
  };

  const openEnvironmentsTab = () => {
    setActiveTab('environments');
  };

  if (!session) {
    return (
      <div className="flex items-center justify-center h-full text-[var(--text-muted)] text-[0.875rem]">
        {t('sessionEnvironmentTab.selectSession')}
      </div>
    );
  }

  const sessionDisplayName =
    session.session_name || session.session_id.slice(0, 8);
  const sourceLabel = envSummary?.name ?? sessionEnvId?.slice(0, 8) ?? '—';
  const hasPipeline = !!sessionEnvId && !envMissing && stages.length > 0;

  return (
    <div className="pipeline-scope h-full flex flex-col overflow-hidden">
      {/* ── Header ──────────────────────────────────────── */}
      <div
        className="px-6 py-3 flex items-center justify-between shrink-0 gap-3 flex-wrap"
        style={{ borderBottom: '1px solid var(--pipe-border)' }}
      >
        <div className="min-w-0">
          <span
            className="text-[10px] font-semibold uppercase tracking-[0.2em]"
            style={{ color: 'var(--pipe-accent)' }}
          >
            {t('sessionEnvironmentTab.pipeline.label')}
          </span>
          <div className="flex items-center gap-2 mt-0.5">
            <h2
              className="pipe-serif text-lg font-bold leading-tight"
              style={{ color: 'var(--pipe-text-primary)' }}
            >
              {t('sessionEnvironmentTab.pipeline.title')}
            </h2>
          </div>
          <div className="flex items-center gap-2 mt-1 text-[10px] flex-wrap">
            <span
              className="uppercase tracking-[0.15em]"
              style={{ color: 'var(--pipe-text-muted)' }}
            >
              {t('sessionEnvironmentTab.pipeline.sourceEnvironment')}
            </span>
            <span style={{ color: 'var(--pipe-border-hover)' }}>·</span>
            {sessionEnvId && !envMissing ? (
              <button
                onClick={openEnvInDrawer}
                title={sessionEnvId}
                className="pipe-mono font-semibold cursor-pointer hover:underline flex items-center gap-1"
                style={{ color: 'var(--pipe-accent)' }}
              >
                {sourceLabel}
                <ExternalLink size={10} className="opacity-60" />
              </button>
            ) : (
              <span
                className="pipe-mono font-semibold"
                style={{ color: 'var(--pipe-text-muted)' }}
              >
                {envMissing
                  ? t('sessionEnvironmentTab.envMissing')
                  : t('sessionEnvironmentTab.noEnvBound')}
              </span>
            )}
            {hasPipeline && (
              <>
                <span style={{ color: 'var(--pipe-border-hover)' }}>·</span>
                <span style={{ color: 'var(--pipe-text-muted)' }}>
                  {t('sessionEnvironmentTab.pipeline.activeRatio', {
                    active: String(activeCount),
                    total: String(stages.length),
                  })}
                </span>
              </>
            )}
            <span style={{ color: 'var(--pipe-border-hover)' }}>·</span>
            <span
              className="pipe-mono"
              style={{ color: 'var(--pipe-text-muted)' }}
              title={session.session_id}
            >
              {sessionDisplayName}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0 flex-wrap">
          <span
            className="text-[9px] tracking-wide hidden md:inline"
            style={{ color: 'var(--pipe-text-muted)' }}
          >
            {t('sessionEnvironmentTab.pipeline.hint')}
          </span>
          {hasPipeline && (
            <>
              <button
                onClick={() => setCodeOpen(true)}
                className="text-[10px] px-3 py-1 rounded-md cursor-pointer transition-colors hover:brightness-125 flex items-center gap-1.5"
                style={{
                  background: 'var(--pipe-bg-tertiary)',
                  color: 'var(--pipe-accent)',
                  border: '1px solid var(--pipe-border)',
                }}
              >
                <Code2 size={11} />
                {t('sessionEnvironmentTab.pipeline.code')}
              </button>
              <button
                onClick={handleReset}
                className="text-[10px] px-3 py-1 rounded-md cursor-pointer transition-colors hover:brightness-125 flex items-center gap-1.5"
                style={{
                  background: 'var(--pipe-bg-tertiary)',
                  color: 'var(--pipe-text-secondary)',
                  border: '1px solid var(--pipe-border)',
                }}
              >
                <Maximize2 size={11} />
                {t('sessionEnvironmentTab.pipeline.reset')}
              </button>
            </>
          )}
          {sessionEnvId && !envMissing && (
            <>
              <button
                onClick={() => sessionEnvId && void fetchManifest(sessionEnvId)}
                disabled={manifestLoading}
                title={t('sessionEnvironmentTab.reload')}
                aria-label={t('sessionEnvironmentTab.reload')}
                className="flex items-center justify-center w-7 h-7 rounded-md cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                style={{
                  background: 'var(--pipe-bg-tertiary)',
                  color: 'var(--pipe-text-muted)',
                  border: '1px solid var(--pipe-border)',
                }}
              >
                <RefreshCw
                  size={11}
                  className={manifestLoading ? 'animate-spin' : ''}
                />
              </button>
              <button
                onClick={openEnvInDrawer}
                className="flex items-center gap-1.5 py-1 px-3 rounded-md cursor-pointer text-[10px] font-semibold transition-colors hover:brightness-125"
                style={{
                  background: 'var(--pipe-accent)',
                  color: '#ffffff',
                  border: '1px solid var(--pipe-accent)',
                }}
              >
                <Settings2 size={11} />
                {t('sessionEnvironmentTab.openInEnvironments')}
              </button>
            </>
          )}
        </div>
      </div>

      {/* ── Body ────────────────────────────────────────── */}
      {!sessionEnvId ? (
        <UnboundState
          workflow={session.workflow_id || '—'}
          onGoToEnvironments={openEnvironmentsTab}
        />
      ) : envMissing ? (
        <EnvMissingState sessionEnvId={sessionEnvId} />
      ) : manifestLoading && !manifestEnv ? (
        <CenterMessage message={t('sessionEnvironmentTab.loading')} />
      ) : manifestError ? (
        <ErrorState
          message={manifestError}
          onRetry={() => sessionEnvId && void fetchManifest(sessionEnvId)}
        />
      ) : stages.length === 0 ? (
        <CenterMessage message={t('sessionEnvironmentTab.manifestEmpty')} />
      ) : (
        <PipelineCanvas
          stages={stages}
          selectedOrder={selectedOrder}
          onSelectStage={setSelectedOrder}
          onResetView={(fn) => {
            resetViewRef.current = fn;
          }}
        />
      )}

      {/* ── Detail panel ─────────────────────────────────── */}
      {selectedOrder !== null && hasPipeline && (
        <StageDetailPanel
          order={selectedOrder}
          entry={stageByOrder.get(selectedOrder)}
          onClose={() => setSelectedOrder(null)}
        />
      )}

      {/* ── Code view ────────────────────────────────────── */}
      {codeOpen && manifestEnv?.manifest && (
        <CodeViewModal
          manifest={manifestEnv.manifest}
          envName={envSummary?.name}
          onClose={() => setCodeOpen(false)}
        />
      )}
    </div>
  );
}

/* ═══ Empty / error states ═══ */

function UnboundState({
  workflow,
  onGoToEnvironments,
}: {
  workflow: string;
  onGoToEnvironments: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-6">
      <Link2Off
        size={28}
        style={{ color: 'var(--pipe-text-muted)', opacity: 0.6 }}
      />
      <p
        className="text-[0.875rem] max-w-[420px]"
        style={{ color: 'var(--pipe-text-secondary)' }}
      >
        {t('sessionEnvironmentTab.unboundHeadline')}
      </p>
      <p
        className="text-[0.75rem] max-w-[480px]"
        style={{ color: 'var(--pipe-text-muted)' }}
      >
        {t('sessionEnvironmentTab.unboundBody', { workflow })}
      </p>
      <button
        onClick={onGoToEnvironments}
        className="mt-1 flex items-center gap-1.5 py-1.5 px-3 rounded-md text-[0.75rem] font-semibold cursor-pointer transition-colors hover:brightness-125"
        style={{
          background: 'var(--pipe-accent)',
          color: '#ffffff',
          border: '1px solid var(--pipe-accent)',
        }}
      >
        <Boxes size={12} />
        {t('sessionEnvironmentTab.goToEnvironments')}
      </button>
    </div>
  );
}

function EnvMissingState({ sessionEnvId }: { sessionEnvId: string }) {
  const { t } = useI18n();
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-6">
      <AlertTriangle size={28} style={{ color: 'var(--pipe-red)', opacity: 0.8 }} />
      <p
        className="text-[0.875rem] max-w-[480px]"
        style={{ color: 'var(--pipe-text-secondary)' }}
      >
        {t('sessionEnvironmentTab.envMissingHeadline')}
      </p>
      <p
        className="pipe-mono text-[0.6875rem]"
        style={{ color: 'var(--pipe-text-muted)' }}
      >
        {sessionEnvId}
      </p>
      <p
        className="text-[0.75rem] max-w-[480px]"
        style={{ color: 'var(--pipe-text-muted)' }}
      >
        {t('sessionEnvironmentTab.envMissingBody')}
      </p>
    </div>
  );
}

function CenterMessage({ message }: { message: string }) {
  return (
    <div
      className="flex-1 flex items-center justify-center text-[0.875rem]"
      style={{ color: 'var(--pipe-text-muted)' }}
    >
      {message}
    </div>
  );
}

function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center px-6">
      <AlertTriangle size={24} style={{ color: 'var(--pipe-red)', opacity: 0.8 }} />
      <p
        className="text-[0.8125rem]"
        style={{ color: 'var(--pipe-red)' }}
      >
        {message}
      </p>
      <button
        onClick={onRetry}
        className="mt-1 flex items-center gap-1.5 py-1 px-3 rounded-md text-[0.75rem] cursor-pointer transition-colors"
        style={{
          background: 'var(--pipe-bg-tertiary)',
          color: 'var(--pipe-text-secondary)',
          border: '1px solid var(--pipe-border)',
        }}
      >
        <RefreshCw size={12} />
        {t('common.refresh')}
      </button>
    </div>
  );
}
