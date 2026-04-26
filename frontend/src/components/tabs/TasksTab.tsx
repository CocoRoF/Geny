'use client';

/**
 * TasksTab — view + manage background tasks (PR-A.5.5).
 *
 * Wraps the /api/agents/{sid}/tasks/ endpoints from PR-A.5.4.
 * Polls every 5 s while mounted so a long-running shell job updates
 * status without manual refresh. Stop button cancels in-flight tasks
 * via DELETE; the runner marks them CANCELLED.
 */

import { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import {
  backgroundTaskApi,
  BackgroundTaskRecord,
  cronApi,
  subagentTypeApi,
  SubagentTypeRow,
  adminTelemetryApi,
} from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import { RefreshCw, Square, Eye, Plus, X, Clock } from 'lucide-react';

function cn(...c: (string | boolean | undefined | null)[]) {
  return twMerge(c.filter(Boolean).join(' '));
}

const POLL_INTERVAL_MS = 5_000;

const STATUS_COLORS: Record<BackgroundTaskRecord['status'], string> = {
  pending: 'bg-slate-200 text-slate-800',
  running: 'bg-blue-200 text-blue-900',
  done: 'bg-green-200 text-green-900',
  failed: 'bg-red-200 text-red-900',
  cancelled: 'bg-amber-200 text-amber-900',
};

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return '—';
  const a = new Date(start).getTime();
  const b = end ? new Date(end).getTime() : Date.now();
  const sec = Math.max(0, Math.round((b - a) / 1000));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  return `${min}m ${sec % 60}s`;
}

export function TasksTab() {
  const sessionId = useAppStore((s) => s.selectedSessionId) || '';
  const [rows, setRows] = useState<BackgroundTaskRecord[]>([]);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  // PR-F.3.2 — New Task modal.
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newKind, setNewKind] = useState('shell');
  const [newPayload, setNewPayload] = useState('{}');
  const [newSubagentType, setNewSubagentType] = useState<string>('');
  const [subagentTypes, setSubagentTypes] = useState<SubagentTypeRow[]>([]);
  // PR-F.6.6 — runner capacity meter.
  const [capacity, setCapacity] = useState<{ in_flight: number | null; max: number | null } | null>(null);

  useEffect(() => {
    subagentTypeApi.list()
      .then((r) => setSubagentTypes(r.types))
      .catch(() => {/* viewer is optional */});
    const loadStatus = () => {
      adminTelemetryApi.systemStatus()
        .then((r) => {
          if (r.task_runner) {
            setCapacity({
              in_flight: r.task_runner.in_flight ?? null,
              max: r.task_runner.max_concurrency ?? null,
            });
          }
        })
        .catch(() => {});
    };
    loadStatus();
    const id = setInterval(loadStatus, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await backgroundTaskApi.list(sessionId, {
        status: statusFilter || undefined,
        limit: 50,
      });
      setRows(resp.tasks);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [sessionId, statusFilter]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const handleStop = useCallback(
    async (taskId: string) => {
      if (!sessionId) return;
      try {
        await backgroundTaskApi.stop(sessionId, taskId);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        refresh();
      }
    },
    [sessionId, refresh],
  );

  // PR-F.3.2 — submit a new background task.
  const handleCreate = async () => {
    if (!sessionId) return;
    let payload: Record<string, unknown> = {};
    try {
      const parsed = JSON.parse(newPayload);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('payload must be a JSON object');
      }
      payload = parsed as Record<string, unknown>;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    }
    if (newSubagentType) {
      payload.subagent_type = newSubagentType;
    }
    setCreating(true);
    setError(null);
    try {
      await backgroundTaskApi.create(sessionId, newKind.trim() || 'shell', payload);
      setCreateOpen(false);
      setNewPayload('{}');
      setNewSubagentType('');
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  };

  // PR-F.3.3 — schedule a row as a recurring cron job. Convention:
  // jobs land with name `task-<task_id_prefix>` so the operator can
  // see the link in CronTab.
  const handleSchedule = async (row: BackgroundTaskRecord) => {
    if (!sessionId) return;
    const cronExpr = window.prompt(
      'Cron expression (e.g. "*/30 * * * *" for every 30 minutes):',
      '0 * * * *',
    );
    if (!cronExpr) return;
    try {
      await cronApi.create({
        name: `task-${row.task_id.slice(0, 12)}`,
        cron_expr: cronExpr,
        target_kind: row.kind,
        payload: { ...row.payload, scheduled_from_task: row.task_id },
        description: `Cloned from background task ${row.task_id}`,
      });
      window.alert(
        `Scheduled. View it in the Cron tab as task-${row.task_id.slice(0, 12)}.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (!sessionId) {
    return (
      <div className="p-6 text-sm text-slate-500">
        Select a session to view its background tasks.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full p-4 gap-4">
      <header className="flex items-center justify-between gap-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          Background Tasks
          {capacity && (capacity.in_flight !== null || capacity.max !== null) && (
            <span
              className="text-[0.625rem] px-1.5 py-0.5 rounded border font-mono uppercase tracking-wider bg-blue-100 text-blue-800 border-blue-300"
              title="Process-wide BackgroundTaskRunner load"
            >
              {capacity.in_flight ?? '?'} / {capacity.max ?? '∞'}
            </span>
          )}
        </h2>
        <div className="flex items-center gap-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-sm border rounded px-2 py-1"
          >
            <option value="">All statuses</option>
            <option value="pending">Pending</option>
            <option value="running">Running</option>
            <option value="done">Done</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </select>
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="flex items-center gap-1 text-sm bg-[var(--primary-color)] text-white rounded px-2 py-1"
          >
            <Plus className="w-4 h-4" />
            New task
          </button>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-1 text-sm border rounded px-2 py-1 disabled:opacity-50"
          >
            <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
            Refresh
          </button>
        </div>
      </header>

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
          {error}
        </div>
      )}

      {rows.length === 0 ? (
        <div className="text-sm text-slate-500 p-4 border rounded text-center">
          No tasks. Tools that submit background work (TaskCreate / Cron-fired
          jobs) will appear here.
        </div>
      ) : (
        <div className="overflow-auto border rounded">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-100 sticky top-0">
              <tr>
                <th className="text-left px-3 py-2">Task ID</th>
                <th className="text-left px-3 py-2">Kind</th>
                <th className="text-left px-3 py-2">Status</th>
                <th className="text-left px-3 py-2">Duration</th>
                <th className="text-right px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const isTerminal =
                  row.status === 'done' ||
                  row.status === 'failed' ||
                  row.status === 'cancelled';
                return (
                  <tr key={row.task_id} className="border-t hover:bg-slate-50">
                    <td className="px-3 py-2 font-mono text-xs">{row.task_id.slice(0, 12)}…</td>
                    <td className="px-3 py-2">{row.kind}</td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          'inline-block rounded px-2 py-0.5 text-xs font-medium',
                          STATUS_COLORS[row.status],
                        )}
                      >
                        {row.status}
                      </span>
                      {row.error && (
                        <span className="ml-2 text-xs text-red-600 truncate inline-block max-w-xs align-middle">
                          {row.error}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {formatDuration(row.started_at, row.completed_at)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <a
                        href={backgroundTaskApi.outputUrl(sessionId, row.task_id)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline mr-3"
                      >
                        <Eye className="w-3 h-3" /> Output
                      </a>
                      <button
                        type="button"
                        onClick={() => handleSchedule(row)}
                        className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline mr-3"
                        title="Schedule a recurring cron job with the same payload"
                      >
                        <Clock className="w-3 h-3" /> Schedule
                      </button>
                      <button
                        type="button"
                        disabled={isTerminal}
                        onClick={() => handleStop(row.task_id)}
                        className="inline-flex items-center gap-1 text-xs text-red-600 hover:underline disabled:text-slate-400 disabled:hover:no-underline"
                      >
                        <Square className="w-3 h-3" /> Stop
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* PR-F.3.2 — New Task modal */}
      {createOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={() => !creating && setCreateOpen(false)}
        >
          <div
            className="bg-[var(--bg-primary)] rounded-lg border border-[var(--border-color)] w-full max-w-lg p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold">New background task</h3>
              <button
                type="button"
                onClick={() => setCreateOpen(false)}
                disabled={creating}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              >
                <X className="w-4 h-4" />
              </button>
            </header>
            <div className="grid gap-2 text-[0.75rem]">
              <label>
                <div className="text-[var(--text-muted)] mb-0.5">Kind</div>
                <input
                  value={newKind}
                  onChange={(e) => setNewKind(e.target.value)}
                  placeholder="shell, agent, …"
                  className="w-full border rounded px-2 py-1 text-[0.8125rem]"
                />
              </label>
              {subagentTypes.length > 0 && (
                <label>
                  <div className="text-[var(--text-muted)] mb-0.5">Subagent type (optional)</div>
                  <select
                    value={newSubagentType}
                    onChange={(e) => setNewSubagentType(e.target.value)}
                    className="w-full border rounded px-2 py-1 text-[0.8125rem]"
                  >
                    <option value="">— none —</option>
                    {subagentTypes.map((t) => (
                      <option key={t.agent_type} value={t.agent_type}>
                        {t.agent_type} — {t.description.slice(0, 60)}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label>
                <div className="text-[var(--text-muted)] mb-0.5">Payload (JSON object)</div>
                <textarea
                  value={newPayload}
                  onChange={(e) => setNewPayload(e.target.value)}
                  rows={6}
                  className="w-full border rounded px-2 py-1 text-[0.75rem] font-mono"
                />
              </label>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCreateOpen(false)}
                disabled={creating}
                className="text-xs border rounded px-3 py-1"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleCreate}
                disabled={creating || !newKind.trim()}
                className="text-xs bg-[var(--primary-color)] text-white rounded px-3 py-1 disabled:opacity-50"
              >
                {creating ? 'Submitting…' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default TasksTab;
