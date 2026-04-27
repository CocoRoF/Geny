'use client';

/**
 * EnvironmentsTab — Library/Environments view (system-wide manifests).
 *
 * Refactored onto the shared layout primitives (PR-Layout) so the tab
 * body owns only the result grid + modals; chrome (header / toolbar /
 * bulk bar / footer) lives in <TabShell>.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Archive,
  ArrowLeftRight,
  Boxes,
  Check,
  Download,
  FilterX,
  Plus,
  RefreshCw,
  SquareCheck,
  Tag,
  Trash2,
  Upload,
  Users,
} from 'lucide-react';
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
import BuilderTab from '@/components/tabs/BuilderTab';
import {
  TabShell,
  TabToolbar,
  SearchInput,
  FilterPills,
  SortMenu,
  BulkActionBar,
  ResultsGrid,
  TabFooter,
  CountSummary,
  ActionButton,
  EmptyState,
  type FilterPillDef,
  type SortOptionDef,
  type SortDirection,
} from '@/components/layout';

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

type SortKeyBase =
  | 'updated'
  | 'name'
  | 'sessions'
  | 'errors';

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
    builderEnvId,
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
  const [sortKey, setSortKey] = useState<SortKeyBase>('updated');
  const [sortDir, setSortDir] = useState<SortDirection>('desc');
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

  const consumePendingDrawerEnvId = useEnvironmentStore(s => s.consumePendingDrawerEnvId);
  const pendingDrawerEnvId = useEnvironmentStore(s => s.pendingDrawerEnvId);
  useEffect(() => {
    if (pendingDrawerEnvId) {
      const id = consumePendingDrawerEnvId();
      if (id) setOpenEnvId(id);
    }
  }, [pendingDrawerEnvId, consumePendingDrawerEnvId]);

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
        for (const tg of tagFilter) if (!envTags.has(tg)) return false;
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
    const flip = sortDir === 'asc' ? -1 : 1;
    switch (sortKey) {
      case 'updated':
        sorted.sort((a, b) => updatedCmp(a, b) * flip);
        break;
      case 'name':
        sorted.sort((a, b) => nameCmp(a, b) * (sortDir === 'asc' ? 1 : -1));
        break;
      case 'sessions':
        sorted.sort(
          (a, b) =>
            (countOf(b, 'active') - countOf(a, 'active')) * flip ||
            updatedCmp(a, b),
        );
        break;
      case 'errors':
        sorted.sort(
          (a, b) =>
            (countOf(b, 'error') - countOf(a, 'error')) * flip ||
            updatedCmp(a, b),
        );
        break;
    }
    return sorted;
  }, [environments, countsPerEnv, searchQuery, statusFilter, selectedTags, sortKey, sortDir]);

  const filtersActive =
    searchQuery.trim().length > 0 ||
    selectedTags.size > 0 ||
    statusFilter !== 'all' ||
    sortKey !== 'updated' ||
    sortDir !== 'desc';

  const clearFilters = () => {
    setSearchQuery('');
    setSelectedTags(new Set());
    setStatusFilter('all');
    setSortKey('updated');
    setSortDir('desc');
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

  const toggleSelectAllInView = () => {
    if (selectedIds.size >= filteredEnvs.length && filteredEnvs.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredEnvs.map(e => e.id)));
    }
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

  if (builderEnvId) {
    return <BuilderTab />;
  }

  // ── Filter pill defs (with bucket counts where useful) ──
  const statusPills: FilterPillDef[] = (
    [
      'all',
      'has_errors',
      'has_sessions',
      'has_deleted',
      'idle',
      'has_preset',
      'has_tags',
    ] as StatusFilter[]
  ).map<FilterPillDef>(id => {
    const tone: FilterPillDef['tone'] =
      id === 'has_errors'
        ? 'danger'
        : id === 'has_sessions'
          ? 'success'
          : id === 'idle'
            ? 'info'
            : 'default';
    return {
      id,
      label: t(`environmentsTab.filterStatus.${id}`),
      tone,
    };
  });

  const sortOptions: SortOptionDef[] = [
    { id: 'updated', label: t('environmentsTab.sort.updated') },
    { id: 'name', label: t('environmentsTab.sort.name') },
    { id: 'sessions', label: t('environmentsTab.sort.sessions') },
    { id: 'errors', label: t('environmentsTab.sort.errors') },
  ];

  const headerActions = (
    <>
      <ActionButton
        icon={RefreshCw}
        spinIcon={isLoading}
        disabled={isLoading}
        onClick={() => {
          loadEnvironments();
          refreshSessionCounts();
        }}
      >
        {t('common.refresh')}
      </ActionButton>
      <ActionButton
        icon={ArrowLeftRight}
        disabled={environments.length < 2}
        onClick={() => setShowDiff({})}
      >
        {t('environmentsTab.compare')}
      </ActionButton>
      <ActionButton
        icon={SquareCheck}
        variant={selectMode ? 'primary' : 'secondary'}
        disabled={environments.length === 0}
        onClick={selectMode ? exitSelectMode : enterSelectMode}
      >
        {selectMode ? t('environmentsTab.cancelSelect') : t('environmentsTab.select')}
      </ActionButton>
      <ActionButton icon={Upload} onClick={() => setShowImport(true)}>
        {t('environmentsTab.importEnvironment')}
      </ActionButton>
      <ActionButton icon={Plus} variant="primary" onClick={() => setShowCreate(true)}>
        {t('environmentsTab.newEnvironment')}
      </ActionButton>
    </>
  );

  const tagFilterControl = allTags.length > 0 ? (
    <div className="relative" ref={tagMenuRef}>
      <button
        type="button"
        onClick={() => setTagMenuOpen(v => !v)}
        className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-[0.75rem] font-medium transition-colors ${
          selectedTags.size > 0
            ? 'bg-[rgba(99,102,241,0.15)] border-[rgba(99,102,241,0.4)] text-[#a5b4fc]'
            : 'border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]'
        }`}
      >
        <Tag className="w-3 h-3" />
        {selectedTags.size > 0
          ? t('environmentsTab.tagFilterActive', { n: String(selectedTags.size) })
          : t('environmentsTab.tagFilterAll')}
      </button>
      {tagMenuOpen && (
        <div className="absolute left-0 top-full mt-1 z-20 w-[220px] max-h-[280px] overflow-auto rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-md p-1.5 flex flex-col gap-0.5">
          {allTags.map(tag => {
            const on = selectedTags.has(tag);
            return (
              <button
                key={tag}
                onClick={() => toggleTag(tag)}
                className="flex items-center justify-between gap-2 py-1 px-2 rounded-md text-[0.75rem] text-left bg-transparent border-none cursor-pointer hover:bg-[hsl(var(--accent))]"
              >
                <span className="text-[hsl(var(--foreground))] truncate">{tag}</span>
                {on && <Check className="w-3 h-3 text-[hsl(var(--primary))]" />}
              </button>
            );
          })}
          {selectedTags.size > 0 && (
            <button
              onClick={() => setSelectedTags(new Set())}
              className="mt-1 py-1 px-2 rounded-md text-[0.6875rem] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] bg-transparent border border-[hsl(var(--border))] cursor-pointer"
            >
              {t('environmentsTab.tagFilterClear')}
            </button>
          )}
        </div>
      )}
    </div>
  ) : null;

  const toolbar = environments.length > 0 ? (
    <TabToolbar
      search={
        <SearchInput
          value={searchQuery}
          onChange={setSearchQuery}
          placeholder={t('environmentsTab.searchPlaceholder')}
        />
      }
      filters={
        <div className="flex items-center gap-2 flex-wrap">
          <FilterPills
            mode="single"
            pills={statusPills}
            active={statusFilter}
            onSelect={(v) => setStatusFilter(v as StatusFilter)}
          />
          {tagFilterControl}
        </div>
      }
      sort={
        <div className="flex items-center gap-1.5">
          <SortMenu
            options={sortOptions}
            value={sortKey}
            direction={sortDir}
            onChange={(k, d) => {
              setSortKey(k as SortKeyBase);
              setSortDir(d);
            }}
          />
          {filtersActive && (
            <button
              onClick={clearFilters}
              className="inline-flex items-center gap-1 py-1 px-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[0.6875rem] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
            >
              <FilterX className="w-3 h-3" />
              {t('environmentsTab.clearFilters')}
            </button>
          )}
        </div>
      }
    />
  ) : undefined;

  const bulkBar = selectMode ? (
    <BulkActionBar
      count={selectedIds.size}
      total={filteredEnvs.length}
      onSelectAll={toggleSelectAllInView}
      onClear={exitSelectMode}
      label={(n) => t('environmentsTab.bulkSelected', { n: String(n) })}
      actions={
        <>
          {selectedIds.size === 2 && (
            <ActionButton
              icon={ArrowLeftRight}
              disabled={bulkBusy}
              onClick={() => {
                const [left, right] = Array.from(selectedIds);
                setShowDiff({ left, right });
              }}
            >
              {t('environmentsTab.bulkCompare')}
            </ActionButton>
          )}
          {selectedIds.size >= 3 && (
            <ActionButton
              icon={ArrowLeftRight}
              disabled={bulkBusy}
              onClick={() => setMatrixIds(Array.from(selectedIds))}
            >
              {t('environmentsTab.bulkCompareMatrix', { n: String(selectedIds.size) })}
            </ActionButton>
          )}
          <ActionButton
            icon={Download}
            disabled={selectedIds.size === 0 || bulkBusy}
            onClick={runBulkExport}
          >
            {t('environmentsTab.bulkExport', { n: String(selectedIds.size) })}
          </ActionButton>
          <ActionButton
            icon={Trash2}
            variant="danger"
            disabled={selectedIds.size === 0 || bulkBusy}
            onClick={() => setShowBulkDeleteConfirm(true)}
          >
            {t('environmentsTab.bulkDelete', { n: String(selectedIds.size) })}
          </ActionButton>
        </>
      }
    />
  ) : undefined;

  const footer = (
    <TabFooter
      left={
        <CountSummary
          total={environments.length}
          shown={filteredEnvs.length}
          selected={selectMode ? selectedIds.size : undefined}
        />
      }
      right={bulkError ? (
        <span className="text-red-600 dark:text-red-400">
          {bulkError}
        </span>
      ) : null}
    />
  );

  // Body (only the result grid + empty/no-match states)
  const body = environments.length === 0 && !isLoading ? (
    <EmptyState
      icon={Boxes}
      title={t('environmentsTab.empty')}
      description={t('environmentsTab.emptyHint')}
      action={
        <div className="flex items-center gap-2">
          <ActionButton icon={Plus} variant="primary" onClick={() => setShowCreate(true)}>
            {t('environmentsTab.createFirst')}
          </ActionButton>
          <ActionButton icon={Upload} onClick={() => setShowImport(true)}>
            {t('environmentsTab.importFirst')}
          </ActionButton>
        </div>
      }
    />
  ) : (
    <ResultsGrid
      items={filteredEnvs}
      loading={isLoading && environments.length === 0}
      keyOf={(env) => env.id}
      empty={
        <EmptyState
          icon={FilterX}
          title={t('environmentsTab.noFilterMatch', { n: String(environments.length) })}
          action={
            <ActionButton onClick={clearFilters}>
              {t('environmentsTab.clearFilters')}
            </ActionButton>
          }
        />
      }
      renderItem={(env) => {
        const b = countsPerEnv[env.id] ?? { active: 0, deleted: 0, error: 0 };
        return (
          <EnvironmentCard
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
              selectMode ? undefined : (id) => prefetchDrawerSessions(id, false)
            }
          />
        );
      }}
    />
  );

  return (
    <>
      <TabShell
        title={t('environmentsTab.title')}
        subtitle={t('environmentsTab.subtitle')}
        icon={Boxes}
        actions={headerActions}
        toolbar={toolbar}
        bulkBar={bulkBar}
        loading={isLoading && environments.length > 0}
        error={error}
        bodyPadding="md"
        bodyScroll="auto"
        footer={footer}
      >
        {body}
      </TabShell>

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
    </>
  );
}
