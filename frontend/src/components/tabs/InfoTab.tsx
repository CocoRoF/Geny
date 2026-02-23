'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import type { SessionInfo } from '@/types';

function formatTimestamp(ts: string) {
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

export default function InfoTab() {
  const { selectedSessionId, sessions, restoreSession, permanentDeleteSession } = useAppStore();
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
      <div className="no-session-selected">
        <div className="empty-state">
          <h3>Select a Session</h3>
          <p>Choose a session to view its details</p>
        </div>
      </div>
    );
  }

  if (loading) return <div className="flex items-center justify-center h-full text-[var(--text-muted)]">Loading...</div>;
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
    { label: 'Session ID', value: data.session_id },
    { label: 'Name', value: data.session_name || '(unnamed)' },
    { label: 'Status', value: isDeleted ? '🗑️ Deleted' : (data.status || 'unknown') },
    { label: 'Model', value: data.model || 'default' },
    { label: 'Role', value: data.role || 'worker' },
    { label: 'Autonomous', value: data.autonomous ? 'Yes' : 'No' },
    { label: 'Max Turns', value: data.max_turns ?? '—' },
    { label: 'Timeout', value: data.timeout ? `${data.timeout}s` : '—' },
    { label: 'Max Iterations', value: data.autonomous_max_iterations ?? '—' },
    { label: 'Storage Path', value: data.storage_path || '—' },
    { label: 'Created', value: data.created_at ? formatTimestamp(data.created_at) : '—' },
    { label: 'PID', value: data.pid || '—' },
    { label: 'Pod', value: data.pod_name || '—' },
    { label: 'Manager ID', value: data.manager_id ? data.manager_id.substring(0, 8) + '...' : '—' },
    ...(isDeleted ? [{ label: 'Deleted At', value: data.deleted_at ? formatTimestamp(data.deleted_at) : '—' }] : []),
  ];

  return (
    <div className="p-5 overflow-y-auto h-full bg-[var(--bg-primary)]">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h4 className="text-[16px] font-semibold text-[var(--text-primary)] m-0">{data.session_name || 'Session Details'}</h4>
        <span className="text-[11px] font-semibold py-[3px] px-2.5 rounded-[12px] uppercase tracking-[0.5px]"
              style={getStatusBadgeStyle()}>
          {isDeleted ? 'Deleted' : (data.status || 'unknown')}
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
          <button className="btn btn-primary btn-sm" onClick={() => restoreSession(data.session_id)}>↻ Restore Session</button>
          <button className="btn btn-danger btn-sm" onClick={() => permanentDeleteSession(data.session_id)}>🗑️ Permanently Delete</button>
        </div>
      )}
    </div>
  );
}
