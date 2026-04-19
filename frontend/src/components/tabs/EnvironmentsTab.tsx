'use client';

/**
 * EnvironmentsTab — read-only list view for v2 EnvironmentManifests.
 *
 * Phase 6c scope: render what the backend already returns (list GET) and
 * expose empty / loading / error states. Create/edit/duplicate/delete
 * land in follow-up PRs so this file stays small and easy to diff.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Archive, ArrowLeftRight, Boxes, Plus, RefreshCw, Tag, Upload, Users } from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { useI18n } from '@/lib/i18n';
import { environmentApi } from '@/lib/environmentApi';
import type { EnvironmentSummary } from '@/types/environment';
import CreateEnvironmentModal from '@/components/modals/CreateEnvironmentModal';
import EnvironmentDetailDrawer from '@/components/EnvironmentDetailDrawer';
import EnvironmentDiffModal from '@/components/modals/EnvironmentDiffModal';
import ImportEnvironmentModal from '@/components/modals/ImportEnvironmentModal';

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function EnvironmentCard({
  env,
  sessionCount,
  errorCount,
  deletedCount,
  onClick,
}: {
  env: EnvironmentSummary;
  sessionCount: number;
  errorCount: number;
  deletedCount: number;
  onClick: () => void;
}) {
  const { t } = useI18n();
  return (
    <div
      onClick={onClick}
      className="group relative flex flex-col gap-2 p-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] hover:border-[var(--text-muted)] hover:bg-[var(--bg-tertiary)] transition-all duration-150 cursor-pointer"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-6 h-6 rounded-md bg-gradient-to-br from-[#6366f1] to-[#8b5cf6] flex items-center justify-center shrink-0">
            <Boxes size={12} className="text-white" />
          </div>
          <h4 className="text-[0.875rem] font-semibold text-[var(--text-primary)] truncate">
            {env.name}
          </h4>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {errorCount > 0 && (
            <span
              className="inline-flex items-center gap-1 py-0.5 px-1.5 rounded-md bg-[rgba(239,68,68,0.12)] text-[10px] font-semibold text-[var(--danger-color)] border border-[rgba(239,68,68,0.25)]"
              title={t('environmentsTab.errorCountTooltip', { n: String(errorCount) })}
            >
              <AlertTriangle size={9} />
              {errorCount}
            </span>
          )}
          {sessionCount > 0 && (
            <span
              className="inline-flex items-center gap-1 py-0.5 px-1.5 rounded-md bg-[rgba(34,197,94,0.1)] text-[10px] font-semibold text-[var(--success-color)] border border-[rgba(34,197,94,0.25)]"
              title={t('environmentsTab.sessionCountTooltip', { n: String(sessionCount) })}
            >
              <Users size={9} />
              {sessionCount}
            </span>
          )}
          {deletedCount > 0 && (
            <span
              className="inline-flex items-center gap-1 py-0.5 px-1.5 rounded-md bg-[rgba(148,163,184,0.12)] text-[10px] font-semibold text-[var(--text-muted)] border border-[rgba(148,163,184,0.25)]"
              title={t('environmentsTab.deletedCountTooltip', { n: String(deletedCount) })}
            >
              <Archive size={9} />
              {deletedCount}
            </span>
          )}
        </div>
      </div>

      <p className="text-[0.75rem] text-[var(--text-muted)] line-clamp-2 leading-[1.5]">
        {env.description || t('environmentsTab.noDescription')}
      </p>

      {env.tags.length > 0 && (
        <div className="flex items-center flex-wrap gap-1">
          {env.tags.slice(0, 4).map(tag => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 py-0.5 px-1.5 rounded-md bg-[rgba(99,102,241,0.1)] text-[10px] font-medium text-[#a5b4fc] border border-[rgba(99,102,241,0.2)]"
            >
              <Tag size={9} />
              {tag}
            </span>
          ))}
          {env.tags.length > 4 && (
            <span className="text-[10px] text-[var(--text-muted)]">
              +{env.tags.length - 4}
            </span>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 text-[0.6875rem] text-[var(--text-muted)] mt-auto pt-1">
        <span>{t('environmentsTab.updated', { date: formatDate(env.updated_at) })}</span>
      </div>
    </div>
  );
}

type CountBucket = { active: number; deleted: number; error: number };

export default function EnvironmentsTab() {
  const { environments, isLoading, error, loadEnvironments } = useEnvironmentStore();
  const sessions = useAppStore(s => s.sessions);
  const { t } = useI18n();
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [showDiff, setShowDiff] = useState<{ left?: string; right?: string } | null>(null);
  const [openEnvId, setOpenEnvId] = useState<string | null>(null);
  const [serverCounts, setServerCounts] = useState<Record<string, CountBucket> | null>(null);

  const refreshCounts = useCallback(async () => {
    try {
      const res = await environmentApi.sessionCounts();
      const map: Record<string, CountBucket> = {};
      for (const c of res.counts) {
        map[c.env_id] = {
          active: c.active_count,
          deleted: c.deleted_count,
          error: c.error_count,
        };
      }
      setServerCounts(map);
    } catch {
      // Leave serverCounts null → client aggregation keeps the card grid usable.
    }
  }, []);

  useEffect(() => {
    loadEnvironments();
  }, [loadEnvironments]);

  useEffect(() => {
    refreshCounts();
  }, [refreshCounts]);

  const clientCountsPerEnv = useMemo(() => {
    const counts: Record<string, CountBucket> = {};
    for (const s of sessions) {
      const envId = (s as { env_id?: string | null }).env_id;
      if (!envId) continue;
      const b = (counts[envId] ??= { active: 0, deleted: 0, error: 0 });
      b.active += 1;
      if (s.status === 'error') b.error += 1;
    }
    return counts;
  }, [sessions]);

  const countsPerEnv = useMemo<Record<string, CountBucket>>(() => {
    return serverCounts ?? clientCountsPerEnv;
  }, [serverCounts, clientCountsPerEnv]);

  return (
    <div className="flex-1 min-h-0 overflow-auto bg-[var(--bg-primary)]">
      <div className="max-w-[1200px] mx-auto p-6 flex flex-col gap-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex flex-col gap-1 min-w-0">
            <h2 className="text-[1.25rem] font-semibold text-[var(--text-primary)]">
              {t('environmentsTab.title')}
            </h2>
            <p className="text-[0.8125rem] text-[var(--text-muted)] max-w-[720px]">
              {t('environmentsTab.subtitle')}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                loadEnvironments();
                refreshCounts();
              }}
              disabled={isLoading}
              className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <RefreshCw size={12} className={isLoading ? 'animate-spin' : ''} />
              {t('common.refresh')}
            </button>
            <button
              onClick={() => setShowDiff({})}
              disabled={environments.length < 2}
              className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ArrowLeftRight size={12} />
              {t('environmentsTab.compare')}
            </button>
            <button
              onClick={() => setShowImport(true)}
              className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
            >
              <Upload size={12} />
              {t('environmentsTab.importEnvironment')}
            </button>
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-semibold cursor-pointer border-none transition-colors"
            >
              <Plus size={12} />
              {t('environmentsTab.newEnvironment')}
            </button>
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="px-3 py-2 rounded-md bg-[rgba(239,68,68,0.1)] border border-[rgba(239,68,68,0.3)] text-[0.8125rem] text-[var(--danger-color)]">
            {error}
          </div>
        )}

        {/* Content */}
        {isLoading && environments.length === 0 ? (
          <div className="flex items-center justify-center py-16 text-[0.875rem] text-[var(--text-muted)]">
            {t('environmentsTab.loading')}
          </div>
        ) : environments.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 gap-2 text-center">
            <Boxes size={32} className="text-[var(--text-muted)] opacity-60" />
            <p className="text-[0.875rem] text-[var(--text-secondary)]">
              {t('environmentsTab.empty')}
            </p>
            <p className="text-[0.75rem] text-[var(--text-muted)] max-w-[420px]">
              {t('environmentsTab.emptyHint')}
            </p>
            <div className="mt-3 flex items-center gap-2">
              <button
                onClick={() => setShowCreate(true)}
                className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-semibold cursor-pointer border-none transition-colors"
              >
                <Plus size={12} />
                {t('environmentsTab.createFirst')}
              </button>
              <button
                onClick={() => setShowImport(true)}
                className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
              >
                <Upload size={12} />
                {t('environmentsTab.importFirst')}
              </button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3">
            {environments.map(env => {
              const b = countsPerEnv[env.id] ?? { active: 0, deleted: 0, error: 0 };
              return (
                <EnvironmentCard
                  key={env.id}
                  env={env}
                  sessionCount={b.active}
                  errorCount={b.error}
                  deletedCount={b.deleted}
                  onClick={() => setOpenEnvId(env.id)}
                />
              );
            })}
          </div>
        )}
      </div>

      {showCreate && (
        <CreateEnvironmentModal
          onClose={() => setShowCreate(false)}
          onCreated={id => setOpenEnvId(id)}
        />
      )}

      {showImport && (
        <ImportEnvironmentModal
          onClose={() => setShowImport(false)}
          onImported={id => setOpenEnvId(id)}
        />
      )}

      {openEnvId && (
        <EnvironmentDetailDrawer
          envId={openEnvId}
          onClose={() => setOpenEnvId(null)}
          onCompare={() => {
            setShowDiff({ left: openEnvId });
            setOpenEnvId(null);
          }}
        />
      )}

      {showDiff && (
        <EnvironmentDiffModal
          initialLeft={showDiff.left}
          initialRight={showDiff.right}
          onClose={() => setShowDiff(null)}
        />
      )}
    </div>
  );
}
