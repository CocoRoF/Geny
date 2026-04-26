'use client';

/**
 * CronTab — manage scheduled background jobs (PR-A.8.3 frontend).
 *
 * Wraps /api/cron/jobs/ from the cron controller. Polls every 30 s
 * (cron jobs change far less often than tasks). Create modal + per-row
 * Run-now + Delete.
 */

import { useState, useEffect, useCallback, FormEvent } from 'react';
import { cronApi, CronJobRecord, CronJobCreateRequest } from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import { RefreshCw, Plus, Trash2, Play } from 'lucide-react';

function cn(...c: (string | boolean | undefined | null)[]) {
  return twMerge(c.filter(Boolean).join(' '));
}

const POLL_INTERVAL_MS = 30_000;

export function CronTab() {
  const [rows, setRows] = useState<CronJobRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await cronApi.list();
      setRows(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const handleDelete = useCallback(
    async (name: string) => {
      if (!window.confirm(`Delete cron job "${name}"?`)) return;
      try {
        await cronApi.delete(name);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        refresh();
      }
    },
    [refresh],
  );

  const handleRunNow = useCallback(
    async (name: string) => {
      try {
        const res = await cronApi.runNow(name);
        alert(`Adhoc fired. task_id=${res.task_id}`);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        refresh();
      }
    },
    [refresh],
  );

  return (
    <div className="flex flex-col h-full p-4 gap-4">
      <header className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Cron Jobs</h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-1 text-sm border rounded px-2 py-1 disabled:opacity-50"
          >
            <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1 text-sm bg-blue-600 text-white rounded px-2 py-1"
          >
            <Plus className="w-4 h-4" /> Add Job
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
          No cron jobs. Add one to schedule recurring tasks.
        </div>
      ) : (
        <div className="overflow-auto border rounded">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-100 sticky top-0">
              <tr>
                <th className="text-left px-3 py-2">Name</th>
                <th className="text-left px-3 py-2">Cron</th>
                <th className="text-left px-3 py-2">Target</th>
                <th className="text-left px-3 py-2">Last Fired</th>
                <th className="text-left px-3 py-2">Status</th>
                <th className="text-right px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.name} className="border-t hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono text-xs">{row.name}</td>
                  <td className="px-3 py-2 font-mono text-xs">{row.cron_expr}</td>
                  <td className="px-3 py-2">{row.target_kind}</td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {row.last_fired_at
                      ? new Date(row.last_fired_at).toLocaleString()
                      : '—'}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={cn(
                        'inline-block rounded px-2 py-0.5 text-xs',
                        row.status === 'enabled'
                          ? 'bg-green-200 text-green-900'
                          : 'bg-slate-200 text-slate-800',
                      )}
                    >
                      {row.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => handleRunNow(row.name)}
                      className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline mr-3"
                    >
                      <Play className="w-3 h-3" /> Run now
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(row.name)}
                      className="inline-flex items-center gap-1 text-xs text-red-600 hover:underline"
                    >
                      <Trash2 className="w-3 h-3" /> Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <CreateModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            refresh();
          }}
          onError={setError}
        />
      )}
    </div>
  );
}

function CreateModal({
  onClose,
  onCreated,
  onError,
}: {
  onClose: () => void;
  onCreated: () => void;
  onError: (e: string) => void;
}) {
  const [name, setName] = useState('');
  const [cronExpr, setCronExpr] = useState('0 * * * *');
  const [targetKind, setTargetKind] = useState('local_bash');
  const [payloadJson, setPayloadJson] = useState('{"command":"echo hello"}');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    let payload: Record<string, unknown>;
    try {
      payload = payloadJson.trim() ? JSON.parse(payloadJson) : {};
    } catch (err) {
      onError(`payload is not valid JSON: ${err}`);
      setSubmitting(false);
      return;
    }
    const req: CronJobCreateRequest = {
      name: name.trim(),
      cron_expr: cronExpr.trim(),
      target_kind: targetKind,
      payload,
    };
    try {
      await cronApi.create(req);
      onCreated();
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-lg p-6 w-full max-w-md flex flex-col gap-3"
      >
        <h3 className="text-lg font-semibold">Add Cron Job</h3>
        <label className="flex flex-col text-sm">
          Name (alphanumeric / dash / underscore)
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            pattern="[a-zA-Z0-9_-]+"
            className="border rounded px-2 py-1 mt-1"
          />
        </label>
        <label className="flex flex-col text-sm">
          Cron expression (5 fields: m h dom mon dow)
          <input
            value={cronExpr}
            onChange={(e) => setCronExpr(e.target.value)}
            required
            className="border rounded px-2 py-1 mt-1 font-mono"
          />
        </label>
        <label className="flex flex-col text-sm">
          Target kind
          <select
            value={targetKind}
            onChange={(e) => setTargetKind(e.target.value)}
            className="border rounded px-2 py-1 mt-1"
          >
            <option value="local_bash">local_bash</option>
            <option value="local_agent">local_agent</option>
          </select>
        </label>
        <label className="flex flex-col text-sm">
          Payload (JSON)
          <textarea
            value={payloadJson}
            onChange={(e) => setPayloadJson(e.target.value)}
            rows={4}
            className="border rounded px-2 py-1 mt-1 font-mono text-xs"
          />
        </label>
        <div className="flex justify-end gap-2 mt-2">
          <button
            type="button"
            onClick={onClose}
            className="text-sm border rounded px-3 py-1"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="text-sm bg-blue-600 text-white rounded px-3 py-1 disabled:opacity-50"
          >
            {submitting ? 'Creating…' : 'Create'}
          </button>
        </div>
      </form>
    </div>
  );
}

export default CronTab;
