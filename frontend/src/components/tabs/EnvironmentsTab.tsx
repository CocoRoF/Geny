'use client';

/**
 * EnvironmentsTab — read-only list view for v2 EnvironmentManifests.
 *
 * Phase 6c scope: render what the backend already returns (list GET) and
 * expose empty / loading / error states. Create/edit/duplicate/delete
 * land in follow-up PRs so this file stays small and easy to diff.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Archive, ArrowDownNarrowWide, ArrowLeftRight, Boxes, Check, Download, FilterX, Plus, RefreshCw, Search, SquareCheck, Tag, Trash2, Upload, Users, X } from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { useI18n } from '@/lib/i18n';
import { environmentApi } from '@/lib/environmentApi';
import type { EnvironmentSummary } from '@/types/environment';
import CreateEnvironmentModal from '@/components/modals/CreateEnvironmentModal';
import EnvironmentDetailDrawer from '@/components/EnvironmentDetailDrawer';
import EnvironmentDiffModal from '@/components/modals/EnvironmentDiffModal';
import EnvironmentDiffMatrixModal from '@/components/modals/EnvironmentDiffMatrixModal';
import ImportEnvironmentModal from '@/components/modals/ImportEnvironmentModal';
import ConfirmModal from '@/components/modals/ConfirmModal';

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
  selectable,
  selected,
  onClick,
  onHoverPrefetch,
}: {
  env: EnvironmentSummary;
  sessionCount: number;
  errorCount: number;
  deletedCount: number;
  selectable: boolean;
  selected: boolean;
  onClick: () => void;
  onHoverPrefetch?: (envId: string) => void;
}) {
  const { t } = useI18n();
  const borderOverride = selected
    ? 'border-[var(--primary-color)] bg-[rgba(99,102,241,0.08)] hover:border-[var(--primary-color)]'
    : 'border-[var(--border-color)] bg-[var(--bg-secondary)] hover:border-[var(--text-muted)] hover:bg-[var(--bg-tertiary)]';
  return (
    <div
      onClick={onClick}
      onMouseEnter={onHoverPrefetch ? () => onHoverPrefetch(env.id) : undefined}
      onFocus={onHoverPrefetch ? () => onHoverPrefetch(env.id) : undefined}
      className={`group relative flex flex-col gap-2 p-4 rounded-lg border transition-all duration-150 cursor-pointer ${borderOverride}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {selectable ? (
            <div
              className={`w-6 h-6 rounded-md border-2 flex items-center justify-center shrink-0 transition-colors ${
                selected
                  ? 'bg-[var(--primary-color)] border-[var(--primary-color)] text-white'
                  : 'bg-[var(--bg-primary)] border-[var(--border-color)] text-transparent'
              }`}
              aria-hidden
            >
              <Check size={12} />
            </div>
          ) : (
            <div className="w-6 h-6 rounded-md bg-gradient-to-br from-[#6366f1] to-[#8b5cf6] flex items-center justify-center shrink-0">
              <Boxes size={12} className="text-white" />
            </div>
          )}
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

type StatusFilter =
  | 'all'
  | 'has_errors'
  | 'has_sessions'
  | 'has_deleted'
  | 'idle'
  | 'has_preset'
  | 'has_tags';
type SortKey =
  | 'updated_desc'
  | 'updated_asc'
  | 'name_asc'
  | 'name_desc'
  | 'sessions_desc'
  | 'errors_desc';

function triggerBulkDownload(filename: string, content: string) {
  const blob = new Blob([content], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function EnvironmentsTab() {
  const {
    environments,
    isLoading,
    error,
    loadEnvironments,
    deleteEnvironment,
    sessionCounts: storeCounts,
    refreshSessionCounts,
    refreshSessionCountsIfStale,
    prefetchDrawerSessions,
  } = useEnvironmentStore();
  const sessions = useAppStore(s => s.sessions);
  const { t } = useI18n();
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [showDiff, setShowDiff] = useState<{ left?: string; right?: string } | null>(null);
  const [matrixIds, setMatrixIds] = useState<string[] | null>(null);
  const [openEnvId, setOpenEnvId] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [selectedTags, setSelectedTags] = useState<Set<string>>(() => new Set());
  const [sortKey, setSortKey] = useState<SortKey>('updated_desc');
  const [tagMenuOpen, setTagMenuOpen] = useState(false);
  const tagMenuRef = useRef<HTMLDivElement | null>(null);

  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState('');
  const [showBulkDeleteConfirm, setShowBulkDeleteConfirm] = useState(false);

  useEffect(() => {
    if (!tagMenuOpen) return;
    const handler = (e: MouseEvent) => {
      if (!tagMenuRef.current) return;
      if (!tagMenuRef.current.contains(e.target as Node)) setTagMenuOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [tagMenuOpen]);

  useEffect(() => {
    loadEnvironments();
  }, [loadEnvironments]);

  useEffect(() => {
    refreshSessionCounts();
  }, [refreshSessionCounts]);

  useEffect(() => {
    const STALE_MS = 10_000;
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        refreshSessionCountsIfStale(STALE_MS);
      }
    };
    const onFocus = () => refreshSessionCountsIfStale(STALE_MS);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('focus', onFocus);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('focus', onFocus);
    };
  }, [refreshSessionCountsIfStale]);

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
    return storeCounts ?? clientCountsPerEnv;
  }, [storeCounts, clientCountsPerEnv]);

  const allTags = useMemo(() => {
    const set = new Set<string>();
    for (const env of environments) for (const tag of env.tags) set.add(tag);
    return Array.from(set).sort();
  }, [environments]);

  const filteredEnvs = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    const tagFilter = selectedTags;
    const haystacks: EnvironmentSummary[] = environments.filter(env => {
      if (query) {
        const hit =
          env.name.toLowerCase().includes(query) ||
          (env.description || '').toLowerCase().includes(query) ||
          env.id.toLowerCase().includes(query);
        if (!hit) return false;
      }
      if (tagFilter.size > 0) {
        const envTags = new Set(env.tags);
        for (const t of tagFilter) if (!envTags.has(t)) return false;
      }
      if (statusFilter !== 'all') {
        const b = countsPerEnv[env.id] ?? { active: 0, deleted: 0, error: 0 };
        if (statusFilter === 'has_errors' && b.error === 0) return false;
        if (statusFilter === 'has_sessions' && b.active === 0) return false;
        if (statusFilter === 'has_deleted' && b.deleted === 0) return false;
        if (statusFilter === 'idle' && b.active > 0) return false;
        if (statusFilter === 'has_preset' && !(env.base_preset && env.base_preset.length > 0))
          return false;
        if (statusFilter === 'has_tags' && env.tags.length === 0) return false;
      }
      return true;
    });

    const sorted = [...haystacks];
    const nameCmp = (a: EnvironmentSummary, b: EnvironmentSummary) =>
      a.name.localeCompare(b.name);
    const updatedCmp = (a: EnvironmentSummary, b: EnvironmentSummary) =>
      (b.updated_at || '').localeCompare(a.updated_at || '');
    const countOf = (env: EnvironmentSummary, k: keyof CountBucket) =>
      (countsPerEnv[env.id] ?? { active: 0, deleted: 0, error: 0 })[k];
    switch (sortKey) {
      case 'updated_desc':
        sorted.sort(updatedCmp);
        break;
      case 'updated_asc':
        sorted.sort((a, b) => -updatedCmp(a, b));
        break;
      case 'name_asc':
        sorted.sort(nameCmp);
        break;
      case 'name_desc':
        sorted.sort((a, b) => -nameCmp(a, b));
        break;
      case 'sessions_desc':
        sorted.sort((a, b) => countOf(b, 'active') - countOf(a, 'active') || updatedCmp(a, b));
        break;
      case 'errors_desc':
        sorted.sort((a, b) => countOf(b, 'error') - countOf(a, 'error') || updatedCmp(a, b));
        break;
    }
    return sorted;
  }, [environments, countsPerEnv, searchQuery, statusFilter, selectedTags, sortKey]);

  const filtersActive =
    searchQuery.trim().length > 0 ||
    selectedTags.size > 0 ||
    statusFilter !== 'all' ||
    sortKey !== 'updated_desc';

  const clearFilters = () => {
    setSearchQuery('');
    setSelectedTags(new Set());
    setStatusFilter('all');
    setSortKey('updated_desc');
  };

  const toggleTag = (tag: string) => {
    setSelectedTags(prev => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  };

  const enterSelectMode = () => {
    setSelectMode(true);
    setBulkError('');
  };

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelectedIds(new Set());
    setBulkError('');
  };

  const toggleSelection = (envId: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(envId)) next.delete(envId);
      else next.add(envId);
      return next;
    });
  };

  const selectAllInView = () => {
    setSelectedIds(new Set(filteredEnvs.map(e => e.id)));
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
  };

  const runBulkDelete = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    setBulkBusy(true);
    setBulkError('');
    const failures: { id: string; msg: string }[] = [];
    for (const id of ids) {
      try {
        await deleteEnvironment(id);
      } catch (e) {
        failures.push({ id, msg: e instanceof Error ? e.message : 'delete failed' });
      }
    }
    setBulkBusy(false);
    if (failures.length > 0) {
      setBulkError(
        t('environmentsTab.bulkDeleteFailed', {
          n: String(failures.length),
          total: String(ids.length),
        }),
      );
      setSelectedIds(new Set(failures.map(f => f.id)));
    } else {
      exitSelectMode();
    }
  };

  const runBulkExport = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    setBulkBusy(true);
    setBulkError('');
    const bundle: { env_id: string; data: unknown }[] = [];
    const failures: string[] = [];
    for (const id of ids) {
      try {
        const payload = await environmentApi.exportEnv(id);
        const parsed = typeof payload === 'string' ? JSON.parse(payload) : payload;
        bundle.push({ env_id: id, data: parsed });
      } catch {
        failures.push(id);
      }
    }
    setBulkBusy(false);
    if (bundle.length > 0) {
      const now = new Date().toISOString().replace(/[:.]/g, '-');
      const body = {
        version: '1',
        generated_at: new Date().toISOString(),
        exports: bundle,
      };
      triggerBulkDownload(
        `envs-bulk-${now}.json`,
        JSON.stringify(body, null, 2),
      );
    }
    if (failures.length > 0) {
      setBulkError(
        t('environmentsTab.bulkExportFailed', {
          n: String(failures.length),
          total: String(ids.length),
        }),
      );
    }
  };

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
                refreshSessionCounts();
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
              onClick={selectMode ? exitSelectMode : enterSelectMode}
              disabled={environments.length === 0}
              className={`flex items-center gap-1.5 py-1.5 px-3 rounded-md text-[0.75rem] font-medium cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                selectMode
                  ? 'bg-[rgba(99,102,241,0.15)] border border-[rgba(99,102,241,0.4)] text-[#a5b4fc]'
                  : 'bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
              }`}
            >
              <SquareCheck size={12} />
              {selectMode ? t('environmentsTab.cancelSelect') : t('environmentsTab.select')}
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

        {/* Bulk selection bar */}
        {selectMode && (
          <div className="flex flex-wrap items-center gap-2 px-3 py-2 rounded-md border border-[rgba(99,102,241,0.4)] bg-[rgba(99,102,241,0.08)]">
            <span className="text-[0.8125rem] font-medium text-[var(--text-primary)]">
              {t('environmentsTab.bulkSelected', { n: String(selectedIds.size) })}
            </span>
            <button
              onClick={selectAllInView}
              disabled={filteredEnvs.length === 0 || selectedIds.size === filteredEnvs.length}
              className="py-1 px-2 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {t('environmentsTab.bulkSelectAll', { n: String(filteredEnvs.length) })}
            </button>
            {selectedIds.size > 0 && (
              <button
                onClick={clearSelection}
                className="py-1 px-2 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
              >
                {t('environmentsTab.bulkClear')}
              </button>
            )}
            <div className="ml-auto flex items-center gap-2">
              {selectedIds.size === 2 && (
                <button
                  onClick={() => {
                    const [left, right] = Array.from(selectedIds);
                    setShowDiff({ left, right });
                  }}
                  disabled={bulkBusy}
                  className="flex items-center gap-1.5 py-1 px-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ArrowLeftRight size={12} />
                  {t('environmentsTab.bulkCompare')}
                </button>
              )}
              {selectedIds.size >= 3 && (
                <button
                  onClick={() => setMatrixIds(Array.from(selectedIds))}
                  disabled={bulkBusy}
                  className="flex items-center gap-1.5 py-1 px-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ArrowLeftRight size={12} />
                  {t('environmentsTab.bulkCompareMatrix', { n: String(selectedIds.size) })}
                </button>
              )}
              <button
                onClick={runBulkExport}
                disabled={selectedIds.size === 0 || bulkBusy}
                className="flex items-center gap-1.5 py-1 px-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Download size={12} />
                {t('environmentsTab.bulkExport', { n: String(selectedIds.size) })}
              </button>
              <button
                onClick={() => setShowBulkDeleteConfirm(true)}
                disabled={selectedIds.size === 0 || bulkBusy}
                className="flex items-center gap-1.5 py-1 px-3 rounded-md bg-transparent border border-[rgba(239,68,68,0.3)] text-[0.75rem] font-medium text-[var(--danger-color)] hover:bg-[rgba(239,68,68,0.08)] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Trash2 size={12} />
                {t('environmentsTab.bulkDelete', { n: String(selectedIds.size) })}
              </button>
            </div>
            {bulkError && (
              <div className="w-full text-[0.6875rem] text-[var(--danger-color)]">
                {bulkError}
              </div>
            )}
          </div>
        )}

        {/* Filter toolbar */}
        {environments.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[220px] max-w-[360px]">
              <Search
                size={12}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none"
              />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder={t('environmentsTab.searchPlaceholder')}
                className="w-full pl-7 pr-7 py-1.5 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.8125rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)]"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  aria-label={t('environmentsTab.clearSearch')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] bg-transparent border-none cursor-pointer"
                >
                  <X size={12} />
                </button>
              )}
            </div>

            <div className="flex items-center gap-1 text-[0.75rem]">
              {(
                [
                  'all',
                  'has_errors',
                  'has_sessions',
                  'has_deleted',
                  'idle',
                  'has_preset',
                  'has_tags',
                ] as StatusFilter[]
              ).map(v => (
                <button
                  key={v}
                  onClick={() => setStatusFilter(v)}
                  className={`py-1 px-2 rounded-md border text-[0.6875rem] font-medium transition-colors cursor-pointer ${
                    statusFilter === v
                      ? 'bg-[var(--primary-color)] text-white border-[var(--primary-color)]'
                      : 'bg-[var(--bg-secondary)] text-[var(--text-secondary)] border-[var(--border-color)] hover:bg-[var(--bg-tertiary)]'
                  }`}
                >
                  {t(`environmentsTab.filterStatus.${v}`)}
                </button>
              ))}
            </div>

            {allTags.length > 0 && (
              <div className="relative" ref={tagMenuRef}>
                <button
                  onClick={() => setTagMenuOpen(v => !v)}
                  className={`flex items-center gap-1 py-1 px-2 rounded-md text-[0.6875rem] font-medium transition-colors cursor-pointer ${
                    selectedTags.size > 0
                      ? 'bg-[rgba(99,102,241,0.15)] border border-[rgba(99,102,241,0.4)] text-[#a5b4fc]'
                      : 'bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]'
                  }`}
                >
                  <Tag size={10} />
                  {selectedTags.size > 0
                    ? t('environmentsTab.tagFilterActive', { n: String(selectedTags.size) })
                    : t('environmentsTab.tagFilterAll')}
                </button>
                {tagMenuOpen && (
                  <div className="absolute left-0 top-full mt-1 z-20 w-[220px] max-h-[280px] overflow-auto rounded-md border border-[var(--border-color)] bg-[var(--bg-secondary)] shadow-[var(--shadow-md)] p-1.5 flex flex-col gap-0.5">
                    {allTags.map(tag => {
                      const on = selectedTags.has(tag);
                      return (
                        <button
                          key={tag}
                          onClick={() => toggleTag(tag)}
                          className="flex items-center justify-between gap-2 py-1 px-2 rounded-md text-[0.75rem] text-left bg-transparent border-none cursor-pointer hover:bg-[var(--bg-tertiary)]"
                        >
                          <span className="text-[var(--text-primary)] truncate">{tag}</span>
                          {on && <Check size={12} className="text-[var(--primary-color)]" />}
                        </button>
                      );
                    })}
                    {selectedTags.size > 0 && (
                      <button
                        onClick={() => setSelectedTags(new Set())}
                        className="mt-1 py-1 px-2 rounded-md text-[0.6875rem] text-[var(--text-muted)] hover:text-[var(--text-primary)] bg-transparent border border-[var(--border-color)] cursor-pointer"
                      >
                        {t('environmentsTab.tagFilterClear')}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="ml-auto flex items-center gap-1">
              <ArrowDownNarrowWide size={12} className="text-[var(--text-muted)]" />
              <select
                value={sortKey}
                onChange={e => setSortKey(e.target.value as SortKey)}
                className="py-1 px-2 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-secondary)] cursor-pointer focus:outline-none focus:border-[var(--primary-color)]"
              >
                <option value="updated_desc">{t('environmentsTab.sort.updated_desc')}</option>
                <option value="updated_asc">{t('environmentsTab.sort.updated_asc')}</option>
                <option value="name_asc">{t('environmentsTab.sort.name_asc')}</option>
                <option value="name_desc">{t('environmentsTab.sort.name_desc')}</option>
                <option value="sessions_desc">{t('environmentsTab.sort.sessions_desc')}</option>
                <option value="errors_desc">{t('environmentsTab.sort.errors_desc')}</option>
              </select>
              {filtersActive && (
                <button
                  onClick={clearFilters}
                  className="flex items-center gap-1 py-1 px-2 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
                >
                  <FilterX size={11} />
                  {t('environmentsTab.clearFilters')}
                </button>
              )}
            </div>
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
        ) : filteredEnvs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 gap-2 text-center">
            <FilterX size={24} className="text-[var(--text-muted)] opacity-60" />
            <p className="text-[0.8125rem] text-[var(--text-secondary)]">
              {t('environmentsTab.noFilterMatch', { n: String(environments.length) })}
            </p>
            <button
              onClick={clearFilters}
              className="mt-1 py-1 px-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
            >
              {t('environmentsTab.clearFilters')}
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3">
            {filteredEnvs.map(env => {
              const b = countsPerEnv[env.id] ?? { active: 0, deleted: 0, error: 0 };
              return (
                <EnvironmentCard
                  key={env.id}
                  env={env}
                  sessionCount={b.active}
                  errorCount={b.error}
                  deletedCount={b.deleted}
                  selectable={selectMode}
                  selected={selectedIds.has(env.id)}
                  onClick={() =>
                    selectMode ? toggleSelection(env.id) : setOpenEnvId(env.id)
                  }
                  onHoverPrefetch={
                    selectMode ? undefined : id => prefetchDrawerSessions(id, false)
                  }
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

      {matrixIds && (
        <EnvironmentDiffMatrixModal
          envIds={matrixIds}
          onClose={() => setMatrixIds(null)}
        />
      )}

      {showBulkDeleteConfirm && (
        <ConfirmModal
          title={t('environmentsTab.bulkDeleteTitle')}
          message={(() => {
            const ids = Array.from(selectedIds);
            let activeSum = 0;
            let errorSum = 0;
            const envsWithSessions: { id: string; name: string; active: number; error: number }[] = [];
            for (const id of ids) {
              const b = countsPerEnv[id] ?? { active: 0, deleted: 0, error: 0 };
              activeSum += b.active;
              errorSum += b.error;
              if (b.active > 0 || b.error > 0) {
                const env = environments.find(e => e.id === id);
                envsWithSessions.push({ id, name: env?.name ?? id, active: b.active, error: b.error });
              }
            }
            return (
              <div className="flex flex-col gap-2">
                <div>{t('environmentsTab.bulkDeleteMessage', { n: String(selectedIds.size) })}</div>
                {(activeSum > 0 || errorSum > 0) && (
                  <div className="rounded-md border border-[rgba(239,68,68,0.3)] bg-[rgba(239,68,68,0.06)] px-3 py-2 text-[0.75rem] text-[var(--text-secondary)] flex flex-col gap-1.5">
                    <div className="flex items-center gap-1.5 font-semibold text-[var(--danger-color)]">
                      <AlertTriangle size={12} />
                      {t('environmentsTab.bulkDeleteSessionsSummary', {
                        envs: String(envsWithSessions.length),
                        active: String(activeSum),
                        error: String(errorSum),
                      })}
                    </div>
                    <ul className="list-disc pl-5 text-[0.6875rem] max-h-[120px] overflow-auto">
                      {envsWithSessions.slice(0, 6).map(e => (
                        <li key={e.id} className="truncate">
                          <button
                            type="button"
                            onClick={() => {
                              setShowBulkDeleteConfirm(false);
                              setOpenEnvId(e.id);
                            }}
                            title={t('environmentsTab.bulkDeleteDrillTooltip', { name: e.name })}
                            className="bg-transparent border-none p-0 text-[0.6875rem] font-medium text-[var(--primary-color)] hover:underline cursor-pointer"
                          >
                            {e.name}
                          </button>
                          <span className="text-[var(--text-muted)]">
                            {' · '}
                            {t('environmentsTab.bulkDeleteSessionsLine', {
                              active: String(e.active),
                              error: String(e.error),
                            })}
                          </span>
                        </li>
                      ))}
                      {envsWithSessions.length > 6 && (
                        <li className="text-[var(--text-muted)] list-none">
                          {t('environmentsTab.bulkDeleteSessionsMore', {
                            n: String(envsWithSessions.length - 6),
                          })}
                        </li>
                      )}
                    </ul>
                  </div>
                )}
              </div>
            );
          })()}
          note={t('environmentsTab.bulkDeleteNote')}
          confirmLabel={t('environmentsTab.bulkDeleteConfirm')}
          confirmingLabel={t('environmentsTab.bulkDeleting')}
          onConfirm={runBulkDelete}
          onClose={() => setShowBulkDeleteConfirm(false)}
        />
      )}
    </div>
  );
}
