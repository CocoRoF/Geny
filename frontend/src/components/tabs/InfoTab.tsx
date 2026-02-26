'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';
import type { SessionInfo } from '@/types';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

function formatTimestamp(ts: string) {
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

export default function InfoTab() {
  const { selectedSessionId, sessions, restoreSession, permanentDeleteSession } = useAppStore();
  const { t } = useI18n();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchDetail = useCallback(async () => {
    if (!selectedSessionId) { setData(null); return; }
    setLoading(true);
    setError('');
    try {
      let result: any;
      try {
        result = await agentApi.get(selectedSessionId);
        result._source = 'live';
      } catch {
        result = await agentApi.getStore(selectedSessionId);
        result._source = 'store';
      }
      setData(result);
    } catch (e: any) {
      setError(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [selectedSessionId]);

  useEffect(() => { fetchDetail(); }, [fetchDetail]);

  if (!selectedSessionId) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center justify-center py-12 px-4">
          <h3 className="text-[1rem] font-medium text-[var(--text-secondary)] mb-2">{t('info.selectSession')}</h3>
          <p className="text-[0.8125rem] text-[var(--text-muted)]">{t('info.selectSessionDesc')}</p>
        </div>
      </div>
    );
  }

  if (loading) return <div className="flex items-center justify-center h-full text-[var(--text-muted)]">{t('common.loading')}</div>;
  if (error) return <div className="flex items-center justify-center h-full text-[var(--danger-color)] text-[0.875rem]">{error}</div>;
  if (!data) return null;

  const isDeleted = data.is_deleted === true;

  const getStatusBadgeStyle = (): React.CSSProperties => {
    if (isDeleted) return { background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444' };
    if (data.status === 'running') return { background: 'rgba(16, 185, 129, 0.15)', color: '#10b981' };
    if (data.status === 'error') return { background: 'rgba(239, 68, 68, 0.15)', color: '#ef4444' };
    if (data.status === 'starting') return { background: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' };
    return { background: 'rgba(107, 114, 128, 0.15)', color: '#9ca3af' };
  };

  const fields = [
    { label: t('info.fields.sessionId'), value: data.session_id },
    { label: t('info.fields.name'), value: data.session_name || t('info.unnamed') },
    { label: t('info.fields.status'), value: isDeleted ? `🗑️ ${t('info.deleted')}` : (data.status || t('info.unknown')) },
    { label: t('info.fields.model'), value: data.model || t('info.default') },
    { label: t('info.fields.role'), value: data.role || t('info.worker') },
    { label: t('info.fields.graphName'), value: data.graph_name || '—' },
    { label: t('info.fields.workflowId'), value: data.workflow_id || '—' },
    { label: t('info.fields.maxTurns'), value: data.max_turns ?? '—' },
    { label: t('info.fields.timeout'), value: data.timeout ? `${data.timeout}s` : '—' },
    { label: t('info.fields.maxIterations'), value: data.max_iterations ?? '—' },
    { label: t('info.fields.storagePath'), value: data.storage_path || '—' },
    { label: t('info.fields.created'), value: data.created_at ? formatTimestamp(data.created_at) : '—' },
    { label: t('info.fields.pid'), value: data.pid || '—' },
    { label: t('info.fields.pod'), value: data.pod_name || '—' },
    { label: t('info.fields.managerId'), value: data.manager_id ? data.manager_id.substring(0, 8) + '...' : '—' },
    ...(isDeleted ? [{ label: t('info.fields.deletedAt'), value: data.deleted_at ? formatTimestamp(data.deleted_at) : '—' }] : []),
  ];

  return (
    <div className="p-5 overflow-y-auto h-full bg-[var(--bg-primary)]">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h4 className="text-[16px] font-semibold text-[var(--text-primary)] m-0">{data.session_name || t('info.sessionDetails')}</h4>
        <span className="text-[11px] font-semibold py-[3px] px-2.5 rounded-[12px] uppercase tracking-[0.5px]"
              style={getStatusBadgeStyle()}>
          {isDeleted ? t('info.deleted') : (data.status || t('info.unknown'))}
        </span>
      </div>

      {/* Fields Grid */}
      <div className="grid grid-cols-2 gap-1.5">
        {fields.map(f => (
          <div key={f.label} className="flex flex-col gap-0.5 py-2 px-3 bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)]">
            <span className="text-[10px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">{f.label}</span>
            <span className="text-[13px] text-[var(--text-primary)] break-all" style={{ fontFamily: "'SF Mono', 'Fira Code', monospace" }}>{String(f.value)}</span>
          </div>
        ))}
      </div>

      {/* Actions for deleted */}
      {isDeleted && (
        <div className="flex gap-2 mt-4 pt-4 border-t border-[var(--border-color)]">
          <button className={cn("py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed", "!py-1.5 !px-3 text-[0.75rem]")} onClick={() => restoreSession(data.session_id)}>↻ {t('info.restoreSession')}</button>
          <button className={cn("py-2 px-4 bg-[var(--danger-color)] hover:brightness-110 text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed", "!py-1.5 !px-3 text-[0.75rem]")} onClick={() => permanentDeleteSession(data.session_id)}>🗑️ {t('info.permanentDelete')}</button>
        </div>
      )}
    </div>
  );
}
