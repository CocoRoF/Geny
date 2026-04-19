'use client';

/**
 * EnvironmentDetailDrawer — slide-over panel for inspecting a single
 * EnvironmentManifest. Shows metadata, a read-only manifest JSON
 * preview, and the destructive/utility actions (duplicate, export,
 * delete) that the v2 environment REST surface exposes.
 *
 * Editing the manifest lands in Phase 6d (Builder tab) — this drawer
 * is intentionally read-only for the body so the delete/duplicate
 * flows can ship without waiting on the stage editor UX.
 */

import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeftRight, Check, Copy, Download, Link2, RefreshCw, Settings2, Tag, Trash2, Upload, X } from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { useI18n } from '@/lib/i18n';
import { environmentApi } from '@/lib/environmentApi';
import type { EnvironmentSessionSummary } from '@/types/environment';
import ConfirmModal from '@/components/modals/ConfirmModal';
import ImportManifestModal from '@/components/modals/ImportManifestModal';

interface Props {
  envId: string;
  onClose: () => void;
  onCompare?: () => void;
}

function triggerDownload(filename: string, content: string) {
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

function formatDate(iso: string | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function EnvironmentDetailDrawer({ envId, onClose, onCompare }: Props) {
  const {
    selectedEnvironment,
    loadEnvironment,
    clearSelection,
    deleteEnvironment,
    duplicateEnvironment,
    exportEnvironment,
    openInBuilder,
  } = useEnvironmentStore();
  const setActiveTab = useAppStore(s => s.setActiveTab);
  const sessions = useAppStore(s => s.sessions);
  const selectSession = useAppStore(s => s.selectSession);
  const { t } = useI18n();

  const clientLinkedSessions = useMemo(
    () =>
      sessions
        .filter(s => (s as { env_id?: string | null }).env_id === envId)
        .map<EnvironmentSessionSummary>(s => ({
          session_id: s.session_id,
          session_name: s.session_name ?? null,
          status: s.status ?? null,
          role: (s as { role?: string | null }).role ?? null,
          env_id: envId,
          created_at: (s as { created_at?: string | null }).created_at ?? null,
          is_deleted: false,
          deleted_at: null,
          error_message: null,
        })),
    [sessions, envId],
  );

  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showImportManifest, setShowImportManifest] = useState(false);
  const [duplicating, setDuplicating] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [copiedId, setCopiedId] = useState(false);
  const [showDeleted, setShowDeleted] = useState(false);
  const [serverSessions, setServerSessions] = useState<EnvironmentSessionSummary[] | null>(null);
  const [sessionsFetching, setSessionsFetching] = useState(false);
  const [sessionsError, setSessionsError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setSessionsFetching(true);
    setSessionsError('');
    environmentApi
      .linkedSessions(envId, showDeleted)
      .then(res => {
        if (cancelled) return;
        setServerSessions(res.sessions);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setSessionsError(e instanceof Error ? e.message : 'fetch failed');
      })
      .finally(() => {
        if (!cancelled) setSessionsFetching(false);
      });
    return () => {
      cancelled = true;
    };
  }, [envId, showDeleted]);

  const linkedSessions = useMemo<EnvironmentSessionSummary[]>(() => {
    if (serverSessions !== null) return serverSessions;
    return clientLinkedSessions;
  }, [serverSessions, clientLinkedSessions]);

  const linkedBreakdown = useMemo(() => {
    const counts = { running: 0, error: 0, other: 0, deleted: 0 };
    for (const s of linkedSessions) {
      if (s.is_deleted) counts.deleted += 1;
      else if (s.status === 'running') counts.running += 1;
      else if (s.status === 'error') counts.error += 1;
      else counts.other += 1;
    }
    return counts;
  }, [linkedSessions]);

  const handleCopyId = async () => {
    try {
      await navigator.clipboard.writeText(envId);
      setCopiedId(true);
      setTimeout(() => setCopiedId(false), 1200);
    } catch {
      // Clipboard API denied — swallow silently; user can still select the id
    }
  };

  useEffect(() => {
    setLoading(true);
    setLoadError('');
    loadEnvironment(envId)
      .catch((e: unknown) => {
        setLoadError(e instanceof Error ? e.message : t('environmentDetail.loadFailed'));
      })
      .finally(() => setLoading(false));
    return () => {
      clearSelection();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [envId]);

  const env = selectedEnvironment && selectedEnvironment.id === envId ? selectedEnvironment : null;
  const manifestJson = env?.manifest
    ? JSON.stringify(env.manifest, null, 2)
    : '';

  const handleDelete = async () => {
    setActionError('');
    await deleteEnvironment(envId);
    onClose();
  };

  const handleDuplicate = async () => {
    const suggested = env ? `${env.name} (copy)` : '';
    const newName = window.prompt(t('environmentDetail.duplicatePrompt'), suggested);
    if (!newName || !newName.trim()) return;
    setDuplicating(true);
    setActionError('');
    try {
      await duplicateEnvironment(envId, newName.trim());
      onClose();
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : t('environmentDetail.duplicateFailed'));
    } finally {
      setDuplicating(false);
    }
  };

  const handleExport = async () => {
    setExporting(true);
    setActionError('');
    try {
      const payload = await exportEnvironment(envId);
      const serialized = typeof payload === 'string' ? payload : JSON.stringify(payload, null, 2);
      const safeName = (env?.name || envId).replace(/[^a-zA-Z0-9_-]+/g, '_');
      triggerDownload(`env-${safeName}.json`, serialized);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : t('environmentDetail.exportFailed'));
    } finally {
      setExporting(false);
    }
  };

  if (typeof document === 'undefined') return null;

  return createPortal(
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Drawer */}
      <aside
        className="fixed top-0 right-0 bottom-0 z-50 w-full sm:w-[520px] bg-[var(--bg-secondary)] border-l border-[var(--border-color)] shadow-[var(--shadow-lg)] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 py-3 px-5 border-b border-[var(--border-color)] shrink-0">
          <div className="flex flex-col gap-0.5 min-w-0">
            <h3 className="text-[1rem] font-semibold text-[var(--text-primary)] truncate">
              {env?.name || t('environmentDetail.title')}
            </h3>
            <button
              onClick={handleCopyId}
              title={copiedId ? t('environmentDetail.idCopied') : t('environmentDetail.copyId')}
              className="flex items-center gap-1 text-[0.6875rem] text-[var(--text-muted)] font-mono truncate bg-transparent border-none p-0 cursor-pointer hover:text-[var(--text-primary)] text-left"
            >
              <span className="truncate">{envId}</span>
              {copiedId ? (
                <Check size={10} className="shrink-0 text-[var(--success-color)]" />
              ) : (
                <Copy size={10} className="shrink-0 opacity-60" />
              )}
            </button>
          </div>
          <button
            className="flex items-center justify-center w-8 h-8 rounded-md bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer shrink-0"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4">
          {loading && (
            <div className="text-[0.8125rem] text-[var(--text-muted)]">
              {t('environmentDetail.loading')}
            </div>
          )}

          {loadError && (
            <div className="text-[0.8125rem] text-[var(--danger-color)] bg-[rgba(239,68,68,0.1)] p-2.5 rounded-md">
              {loadError}
            </div>
          )}

          {actionError && (
            <div className="text-[0.8125rem] text-[var(--danger-color)] bg-[rgba(239,68,68,0.1)] p-2.5 rounded-md">
              {actionError}
            </div>
          )}

          {env && (
            <>
              {/* Description */}
              <section className="flex flex-col gap-1.5">
                <h4 className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                  {t('environmentDetail.description')}
                </h4>
                <p className="text-[0.8125rem] text-[var(--text-secondary)] whitespace-pre-wrap">
                  {env.description || t('environmentsTab.noDescription')}
                </p>
              </section>

              {/* Tags */}
              {env.tags.length > 0 && (
                <section className="flex flex-col gap-1.5">
                  <h4 className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                    {t('environmentDetail.tags')}
                  </h4>
                  <div className="flex flex-wrap gap-1">
                    {env.tags.map(tag => (
                      <span
                        key={tag}
                        className="inline-flex items-center gap-1 py-0.5 px-1.5 rounded-md bg-[rgba(99,102,241,0.1)] text-[10px] font-medium text-[#a5b4fc] border border-[rgba(99,102,241,0.2)]"
                      >
                        <Tag size={9} />
                        {tag}
                      </span>
                    ))}
                  </div>
                </section>
              )}

              {/* Timestamps */}
              <section className="grid grid-cols-2 gap-3 text-[0.75rem]">
                <div>
                  <div className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide mb-0.5">
                    {t('environmentDetail.created')}
                  </div>
                  <div className="text-[var(--text-secondary)]">{formatDate(env.created_at)}</div>
                </div>
                <div>
                  <div className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide mb-0.5">
                    {t('environmentDetail.updated')}
                  </div>
                  <div className="text-[var(--text-secondary)]">{formatDate(env.updated_at)}</div>
                </div>
              </section>

              {/* Linked sessions */}
              <section className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between gap-2">
                  <h4 className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide flex items-center gap-1.5">
                    <Link2 size={11} />
                    {t('environmentDetail.linkedSessions', { n: linkedSessions.length })}
                    {sessionsFetching && (
                      <RefreshCw size={10} className="animate-spin opacity-60" />
                    )}
                  </h4>
                  {linkedSessions.length > 0 && (
                    <div className="flex items-center gap-1 text-[0.625rem]">
                      {linkedBreakdown.running > 0 && (
                        <span
                          className="inline-flex items-center gap-0.5 py-0.5 px-1.5 rounded-md bg-[rgba(34,197,94,0.12)] text-[#4ade80] border border-[rgba(34,197,94,0.25)]"
                          title={t('environmentDetail.breakdownRunning', { n: linkedBreakdown.running })}
                        >
                          {linkedBreakdown.running} {t('environmentDetail.statusRunning')}
                        </span>
                      )}
                      {linkedBreakdown.error > 0 && (
                        <span
                          className="inline-flex items-center gap-0.5 py-0.5 px-1.5 rounded-md bg-[rgba(239,68,68,0.12)] text-[var(--danger-color)] border border-[rgba(239,68,68,0.25)]"
                          title={t('environmentDetail.breakdownError', { n: linkedBreakdown.error })}
                        >
                          {linkedBreakdown.error} {t('environmentDetail.statusError')}
                        </span>
                      )}
                      {linkedBreakdown.other > 0 && (
                        <span
                          className="inline-flex items-center gap-0.5 py-0.5 px-1.5 rounded-md bg-[var(--bg-tertiary)] text-[var(--text-muted)] border border-[var(--border-color)]"
                          title={t('environmentDetail.breakdownOther', { n: linkedBreakdown.other })}
                        >
                          {linkedBreakdown.other} {t('environmentDetail.statusOther')}
                        </span>
                      )}
                      {linkedBreakdown.deleted > 0 && (
                        <span
                          className="inline-flex items-center gap-0.5 py-0.5 px-1.5 rounded-md bg-[rgba(148,163,184,0.12)] text-[var(--text-muted)] border border-[rgba(148,163,184,0.25)]"
                          title={t('environmentDetail.breakdownDeleted', { n: linkedBreakdown.deleted })}
                        >
                          {linkedBreakdown.deleted} {t('environmentDetail.statusDeleted')}
                        </span>
                      )}
                    </div>
                  )}
                </div>
                <label className="flex items-center gap-1.5 text-[0.6875rem] text-[var(--text-muted)] cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={showDeleted}
                    onChange={e => setShowDeleted(e.target.checked)}
                    className="accent-[var(--primary-color)] w-3 h-3"
                  />
                  {t('environmentDetail.showDeleted')}
                </label>
                {sessionsError && (
                  <p className="text-[0.6875rem] text-[var(--danger-color)]">
                    {t('environmentDetail.linkedSessionsFallback')}
                  </p>
                )}
                {linkedSessions.length === 0 ? (
                  <p className="text-[0.75rem] text-[var(--text-muted)] italic">
                    {t('environmentDetail.linkedSessionsEmpty')}
                  </p>
                ) : (
                  <div className="flex flex-col gap-1">
                    {linkedSessions.map(s => (
                      <button
                        key={s.session_id}
                        onClick={() => {
                          if (s.is_deleted) return;
                          selectSession(s.session_id);
                          onClose();
                        }}
                        disabled={s.is_deleted}
                        title={s.is_deleted ? t('environmentDetail.sessionDeletedHint') : undefined}
                        className={`flex items-center justify-between gap-2 py-1.5 px-2 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-left transition-colors ${
                          s.is_deleted
                            ? 'opacity-60 cursor-not-allowed'
                            : 'hover:bg-[var(--bg-tertiary)] hover:border-[var(--primary-color)] cursor-pointer'
                        }`}
                      >
                        <div className="flex flex-col min-w-0 flex-1">
                          <span className={`text-[0.8125rem] font-medium truncate ${
                            s.is_deleted
                              ? 'text-[var(--text-muted)] line-through'
                              : 'text-[var(--text-primary)]'
                          }`}>
                            {s.session_name || s.session_id.slice(0, 8)}
                          </span>
                          <span className="text-[0.6875rem] text-[var(--text-muted)] font-mono truncate">
                            {s.session_id}
                          </span>
                        </div>
                        <span
                          className={`shrink-0 text-[0.625rem] font-semibold uppercase py-0.5 px-1.5 rounded-md ${
                            s.is_deleted
                              ? 'bg-[rgba(148,163,184,0.12)] text-[var(--text-muted)] border border-[rgba(148,163,184,0.25)]'
                              : s.status === 'running'
                                ? 'bg-[rgba(34,197,94,0.12)] text-[#4ade80] border border-[rgba(34,197,94,0.25)]'
                                : s.status === 'error'
                                  ? 'bg-[rgba(239,68,68,0.12)] text-[var(--danger-color)] border border-[rgba(239,68,68,0.25)]'
                                  : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)] border border-[var(--border-color)]'
                          }`}
                        >
                          {s.is_deleted ? t('environmentDetail.statusDeleted') : (s.status ?? '—')}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </section>

              {/* Manifest preview */}
              <section className="flex flex-col gap-1.5">
                <h4 className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                  {t('environmentDetail.manifest')}
                </h4>
                {manifestJson ? (
                  <pre className="text-[0.6875rem] leading-[1.5] bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-md p-3 overflow-auto max-h-[360px] text-[var(--text-secondary)] font-mono">
                    {manifestJson}
                  </pre>
                ) : (
                  <p className="text-[0.75rem] text-[var(--text-muted)] italic">
                    {t('environmentDetail.manifestEmpty')}
                  </p>
                )}
              </section>
            </>
          )}
        </div>

        {/* Footer actions */}
        <div className="flex items-center justify-between gap-2 py-3 px-5 border-t border-[var(--border-color)] shrink-0">
          <button
            onClick={() => setShowDeleteConfirm(true)}
            className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-transparent border border-[rgba(239,68,68,0.3)] text-[0.75rem] font-medium text-[var(--danger-color)] hover:bg-[rgba(239,68,68,0.08)] cursor-pointer transition-colors"
            disabled={!env}
          >
            <Trash2 size={12} />
            {t('common.delete')}
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                openInBuilder(envId);
                setActiveTab('builder');
                onClose();
              }}
              disabled={!env}
              className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-semibold cursor-pointer border-none transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Settings2 size={12} />
              {t('environmentDetail.openInBuilder')}
            </button>
            {onCompare && (
              <button
                onClick={onCompare}
                disabled={!env}
                className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ArrowLeftRight size={12} />
                {t('environmentDetail.compareWith')}
              </button>
            )}
            <button
              onClick={handleDuplicate}
              disabled={!env || duplicating}
              className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Copy size={12} />
              {duplicating ? t('environmentDetail.duplicating') : t('common.clone')}
            </button>
            <button
              onClick={handleExport}
              disabled={!env || exporting}
              className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download size={12} />
              {exporting ? t('environmentDetail.exporting') : t('common.export')}
            </button>
            <button
              onClick={() => setShowImportManifest(true)}
              disabled={!env}
              className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Upload size={12} />
              {t('environmentDetail.importManifest')}
            </button>
          </div>
        </div>
      </aside>

      {showDeleteConfirm && (
        <ConfirmModal
          title={t('environmentDetail.deleteTitle')}
          message={t('environmentDetail.deleteConfirm', { name: env?.name || envId })}
          note={t('environmentDetail.deleteNote')}
          onConfirm={handleDelete}
          onClose={() => setShowDeleteConfirm(false)}
        />
      )}

      {showImportManifest && (
        <ImportManifestModal
          envId={envId}
          envName={env?.name || envId}
          onClose={() => setShowImportManifest(false)}
          onImported={() => loadEnvironment(envId).catch(() => {})}
        />
      )}
    </>,
    document.body,
  );
}
