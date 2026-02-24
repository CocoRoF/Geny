'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import type { ManagerDashboard, WorkerInfo, ManagerEvent } from '@/types';

const EVENT_ICONS: Record<string, string> = {
  task_delegated: '📤', worker_started: '▶️', worker_completed: '✅',
  worker_error: '❌', worker_progress: '🔄', plan_created: '📋',
  plan_updated: '📝', user_message: '💬', manager_response: '🤖',
};

const EVENT_LABELS: Record<string, string> = {
  task_delegated: 'Task Delegated', worker_started: 'Worker Started',
  worker_completed: 'Worker Completed', worker_error: 'Worker Error',
  worker_progress: 'Progress Update', plan_created: 'Plan Created',
  plan_updated: 'Plan Updated', user_message: 'User Message',
  manager_response: 'Manager Response',
};

const EVENT_COLORS: Record<string, string> = {
  task_delegated: 'text-[var(--primary-color)]', worker_started: 'text-[var(--primary-color)]',
  worker_completed: 'text-[var(--success-color)]', worker_error: 'text-[var(--danger-color)]',
  worker_progress: 'text-[var(--warning-color)]',
};

export default function DashboardTab() {
  const { selectedSessionId, sessions } = useAppStore();
  const [dashboard, setDashboard] = useState<ManagerDashboard | null>(null);
  const [error, setError] = useState('');

  const session = sessions.find(s => s.session_id === selectedSessionId);
  const isManager = session?.role === 'manager';

  const fetchDashboard = useCallback(async () => {
    if (!selectedSessionId || !isManager) return;
    try {
      const data = await agentApi.getDashboard(selectedSessionId);
      setDashboard(data);
      setError('');
    } catch (e: any) {
      setError(e.message);
    }
  }, [selectedSessionId, isManager]);

  useEffect(() => {
    fetchDashboard();
    const interval = setInterval(fetchDashboard, 5000);
    return () => clearInterval(interval);
  }, [fetchDashboard]);

  if (!selectedSessionId) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center justify-center py-12 px-4">
          <h3 className="text-[1rem] font-medium text-[var(--text-secondary)] mb-2">Select a Session</h3>
          <p className="text-[0.8125rem] text-[var(--text-muted)]">Choose a session to view its dashboard</p>
        </div>
      </div>
    );
  }

  if (!isManager) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center justify-center py-12 px-4">
          <h3 className="text-[1rem] font-medium text-[var(--text-secondary)] mb-2">Manager Only</h3>
          <p className="text-[0.8125rem] text-[var(--text-muted)]">Dashboard is only available for manager sessions</p>
        </div>
      </div>
    );
  }

  if (error) {
    return <div className="flex items-center justify-center h-full text-[var(--danger-color)] text-[0.875rem]">{error}</div>;
  }

  const getEventBorderColor = (eventType: string) => {
    if (['worker_completed'].includes(eventType)) return 'var(--success-color)';
    if (['worker_error'].includes(eventType)) return 'var(--danger-color)';
    if (['task_delegated', 'worker_started', 'plan_created', 'plan_updated'].includes(eventType)) return 'var(--primary-color)';
    if (['worker_progress'].includes(eventType)) return 'var(--warning-color)';
    return 'var(--border-color)';
  };

  return (
    <div className="h-full flex flex-col bg-[var(--bg-secondary)]">
      {/* Header */}
      <div className="flex justify-between items-center py-4 px-5 border-b border-[var(--border-color)] bg-[var(--bg-primary)] shrink-0">
        <h3 className="text-[16px] font-semibold text-[var(--text-primary)]">Manager Dashboard</h3>
        <div className="flex items-center gap-3">
          <span className="text-[13px] text-[var(--text-muted)] py-1 px-2.5 bg-[var(--bg-tertiary)] rounded-[var(--border-radius)]">
            {session?.session_name || selectedSessionId.substring(0, 8)}
          </span>
          <span className="text-[12px] font-semibold text-[var(--text-muted)] bg-[var(--bg-tertiary)] py-[2px] px-2 rounded-[10px]">
            {dashboard?.workers.length || 0} workers
          </span>
        </div>
      </div>

      {/* Content Grid */}
      <div className="flex-1 grid overflow-hidden" style={{ gridTemplateColumns: '350px 1fr', gap: '1px', background: 'var(--border-color)' }}>
        {/* Workers Section */}
        <div className="bg-[var(--bg-secondary)] flex flex-col overflow-hidden">
          <div className="flex justify-between items-center py-3 px-4 border-b border-[var(--border-color)]">
            <h4 className="text-[13px] font-semibold text-[var(--text-primary)] uppercase tracking-[0.5px]">Workers</h4>
          </div>
          <div className="flex-1 p-3 flex flex-col gap-2 overflow-y-auto">
            {!dashboard?.workers.length ? (
              <div className="flex flex-col items-center justify-center py-12 px-4"><p className="text-[0.8125rem] text-[var(--text-muted)]">No workers assigned</p></div>
            ) : (
              dashboard.workers.map((w: WorkerInfo) => (
                <div key={w.worker_id}
                     className="flex items-center gap-3 py-3 px-3.5 bg-[var(--bg-tertiary)] rounded-lg transition-colors hover:bg-[var(--bg-hover)]"
                     style={{ borderLeft: `3px solid ${w.is_busy ? 'var(--warning-color)' : 'var(--success-color)'}` }}>
                  <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${w.status === 'running' ? 'bg-[var(--success-color)]' : w.status === 'error' ? 'bg-[var(--danger-color)]' : 'bg-[var(--text-muted)]'}`}
                       style={w.status === 'running' ? { boxShadow: '0 0 6px var(--success-color)' } : {}} />
                  <div className="flex-1 min-w-0">
                    <div className="text-[14px] font-medium text-[var(--text-primary)] mb-[2px]">{w.worker_name || w.worker_id.substring(0, 8)}</div>
                    <div className="text-[11px] text-[var(--text-muted)] capitalize">{w.status}</div>
                  </div>
                  {w.is_busy ? (
                    <span className="text-[10px] font-semibold text-[var(--warning-color)] py-[2px] px-2 rounded-[10px] animate-pulse"
                          style={{ background: 'rgba(245, 158, 11, 0.15)' }}>
                      Working
                    </span>
                  ) : (
                    <span className="text-[10px] font-semibold text-[var(--success-color)] py-[2px] px-2 rounded-[10px]"
                          style={{ background: 'rgba(16, 185, 129, 0.15)' }}>
                      Idle
                    </span>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Activity Timeline Section */}
        <div className="bg-[var(--bg-secondary)] flex flex-col overflow-hidden">
          <div className="flex justify-between items-center py-3 px-4 border-b border-[var(--border-color)]">
            <h4 className="text-[13px] font-semibold text-[var(--text-primary)] uppercase tracking-[0.5px]">Activity Timeline</h4>
          </div>
          <div className="flex-1 py-3 px-4 overflow-y-auto flex flex-col gap-3">
            {!dashboard?.recent_events.length ? (
              <div className="flex flex-col items-center justify-center py-12 px-4"><p className="text-[0.8125rem] text-[var(--text-muted)]">No activity yet</p></div>
            ) : (
              dashboard.recent_events.map((ev: ManagerEvent, idx: number) => (
                <div key={idx}
                     className="flex gap-3 py-3 px-3.5 bg-[var(--bg-tertiary)] rounded-lg"
                     style={{ borderLeft: `3px solid ${getEventBorderColor(ev.event_type)}` }}>
                  <span className="text-[18px] shrink-0">{EVENT_ICONS[ev.event_type] || '📌'}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-[12px] font-semibold text-[var(--text-primary)]">
                        {EVENT_LABELS[ev.event_type] || ev.event_type}
                      </span>
                      <span className="text-[11px] text-[var(--text-muted)]">
                        {new Date(ev.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <p className="text-[13px] text-[var(--text-secondary)] leading-[1.4]">{ev.message}</p>
                    {ev.worker_id && <p className="text-[11px] text-[var(--text-muted)] mt-1">Worker: {ev.worker_id.substring(0, 8)}</p>}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
