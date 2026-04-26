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
import { RefreshCw, Square, Eye, Plus, Clock, ListChecks } from 'lucide-react';
import {
  TabShell,
  EditorModal,
  EmptyState,
  StatusBadge,
  ActionButton,
  type BadgeTone,
} from '@/components/layout';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

const POLL_INTERVAL_MS = 5_000;

const STATUS_TONE: Record<BackgroundTaskRecord['status'], BadgeTone> = {
  pending: 'neutral',
  running: 'info',
  done: 'success',
  failed: 'danger',
  cancelled: 'warning',
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
      <TabShell title="Background Tasks" icon={ListChecks}>
        <EmptyState
          title="No session selected"
          description="Select a session to view its background tasks."
        />
      </TabShell>
    );
  }

  return (
    <TabShell
      title="Background Tasks"
      icon={ListChecks}
      actions={
        <>
          {capacity && (capacity.in_flight !== null || capacity.max !== null) && (
            <StatusBadge
              tone="info"
              uppercase
              title="Process-wide BackgroundTaskRunner load"
            >
              {capacity.in_flight ?? '?'} / {capacity.max ?? '∞'}
            </StatusBadge>
          )}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-xs border rounded px-2 py-1 bg-[var(--bg-primary)]"
          >
            <option value="">All statuses</option>
            <option value="pending">Pending</option>
            <option value="running">Running</option>
            <option value="done">Done</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </select>
          <ActionButton variant="primary" icon={Plus} onClick={() => setCreateOpen(true)}>
            New task
          </ActionButton>
          <ActionButton icon={RefreshCw} spinIcon={loading} onClick={refresh} disabled={loading}>
            Refresh
          </ActionButton>
        </>
      }
      error={error}
      onDismissError={() => setError(null)}
    >
      <div className="h-full min-h-0 overflow-y-auto p-4">
      {rows.length === 0 ? (
        <EmptyState
          icon={ListChecks}
          title="No tasks"
          description="Tools that submit background work (TaskCreate / Cron-fired jobs) will appear here."
        />
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
                      <StatusBadge tone={STATUS_TONE[row.status]}>{row.status}</StatusBadge>
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
      </div>

      <EditorModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="New background task"
        saving={creating}
        width="lg"
        footer={
          <>
            <ActionButton onClick={() => setCreateOpen(false)} disabled={creating}>
              Cancel
            </ActionButton>
            <ActionButton
              variant="primary"
              onClick={handleCreate}
              disabled={creating || !newKind.trim()}
            >
              {creating ? 'Submitting…' : 'Create'}
            </ActionButton>
          </>
        }
      >
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="task-kind">Kind</Label>
            <Input
              id="task-kind"
              value={newKind}
              onChange={(e) => setNewKind(e.target.value)}
              placeholder="shell, agent, …"
            />
          </div>
          {subagentTypes.length > 0 && (
            <div className="grid gap-1.5">
              <Label>Subagent type <span className="opacity-60">(optional)</span></Label>
              <Select
                value={newSubagentType || '__none__'}
                onValueChange={(v) => setNewSubagentType(v === '__none__' ? '' : v)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="— none —" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">— none —</SelectItem>
                  {subagentTypes.map((t) => (
                    <SelectItem key={t.agent_type} value={t.agent_type}>
                      {t.agent_type} — {t.description.slice(0, 60)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="grid gap-1.5">
            <Label htmlFor="task-payload">Payload <span className="opacity-60">(JSON object)</span></Label>
            <Textarea
              id="task-payload"
              value={newPayload}
              onChange={(e) => setNewPayload(e.target.value)}
              rows={6}
              className="font-mono text-xs"
            />
          </div>
        </div>
      </EditorModal>
    </TabShell>
  );
}

export default TasksTab;
