'use client';

/**
 * CronTab — manage scheduled background jobs (PR-A.8.3 frontend).
 *
 * Wraps /api/cron/jobs/ from the cron controller. Polls every 30 s
 * (cron jobs change far less often than tasks). Create modal + per-row
 * Run-now + Delete.
 */

import { useState, useEffect, useCallback, FormEvent, Fragment } from 'react';
import { cronApi, CronJobRecord, CronJobCreateRequest, CronJobHistoryEntry, CronStatusResponse } from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import { RefreshCw, Plus, Trash2, Play, Power, ChevronDown, ChevronRight } from 'lucide-react';

// PR-F.4.2 — show a friendly description of a cron expression next to
// the raw form. cronstrue is consulted at runtime only; the indirect
// module name keeps Next.js / TS from trying to statically resolve it
// so installs without the package still build cleanly.
async function describeCron(expr: string): Promise<string | null> {
  try {
    const moduleName = 'cronstrue';
    const dynamicImport = new Function('m', 'return import(m);') as (m: string) => Promise<unknown>;
    const mod = await dynamicImport(moduleName);
    const fn = (mod as { default?: { toString?: (s: string) => string }; toString?: (s: string) => string });
    if (fn.default && typeof fn.default.toString === 'function') {
      return fn.default.toString(expr);
    }
    if (typeof fn.toString === 'function') {
      return fn.toString(expr);
    }
    return null;
  } catch {
    return null;
  }
}

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const target = new Date(iso).getTime();
    const diff = target - Date.now();
    const abs = Math.abs(diff);
    const sec = Math.round(abs / 1000);
    if (sec < 60) return diff >= 0 ? `in ${sec}s` : `${sec}s ago`;
    const min = Math.round(sec / 60);
    if (min < 60) return diff >= 0 ? `in ${min}m` : `${min}m ago`;
    const hr = Math.round(min / 60);
    if (hr < 24) return diff >= 0 ? `in ${hr}h` : `${hr}h ago`;
    const day = Math.round(hr / 24);
    return diff >= 0 ? `in ${day}d` : `${day}d ago`;
  } catch {
    return iso;
  }
}

function cn(...c: (string | boolean | undefined | null)[]) {
  return twMerge(c.filter(Boolean).join(' '));
}

const POLL_INTERVAL_MS = 30_000;

export function CronTab() {
  const [rows, setRows] = useState<CronJobRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  // PR-F.4.3 — per-row expansion + cached history.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [histories, setHistories] = useState<Record<string, CronJobHistoryEntry[]>>({});
  // PR-F.6.4 — runner status badge in the header.
  const [status, setStatus] = useState<CronStatusResponse | null>(null);

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

  useEffect(() => {
    const load = () => {
      cronApi.status().then(setStatus).catch(() => {});
    };
    load();
    const id = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

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

  const handleToggleStatus = useCallback(
    async (row: CronJobRecord) => {
      const target = row.status === 'enabled' ? 'disabled' : 'enabled';
      try {
        await cronApi.setStatus(row.name, target);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        refresh();
      }
    },
    [refresh],
  );

  const toggleExpand = useCallback(async (name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
    if (!histories[name]) {
      try {
        const h = await cronApi.history(name, 30);
        setHistories((m) => ({ ...m, [name]: h.fires }));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }
  }, [histories]);

  return (
    <div className="flex flex-col h-full p-4 gap-4">
      <header className="flex items-center justify-between">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          Cron Jobs
          {status && (
            <span
              className={cn(
                'text-[0.625rem] px-1.5 py-0.5 rounded border font-mono uppercase tracking-wider',
                status.running
                  ? 'bg-green-100 text-green-800 border-green-300'
                  : 'bg-red-100 text-red-800 border-red-300',
              )}
              title={`cycle ${status.cycle_seconds ?? '?'}s · ${status.jobs_enabled}/${status.jobs_total} enabled`}
            >
              {status.running ? 'live' : 'down'} · {status.jobs_enabled}/{status.jobs_total}
            </span>
          )}
        </h2>
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
              {rows.map((row) => {
                const isExpanded = expanded.has(row.name);
                return (
                  <Fragment key={row.name}>
                    <tr className="border-t hover:bg-slate-50">
                      <td className="px-3 py-2 font-mono text-xs">
                        <button
                          type="button"
                          onClick={() => toggleExpand(row.name)}
                          className="inline-flex items-center gap-1 hover:text-blue-600"
                        >
                          {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                          {row.name}
                        </button>
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">{row.cron_expr}</td>
                      <td className="px-3 py-2">{row.target_kind}</td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {row.last_fired_at
                          ? new Date(row.last_fired_at).toLocaleString()
                          : '—'}
                      </td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => handleToggleStatus(row)}
                          className={cn(
                            'inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs',
                            row.status === 'enabled'
                              ? 'bg-green-200 text-green-900 hover:bg-green-300'
                              : 'bg-slate-200 text-slate-800 hover:bg-slate-300',
                          )}
                          title="Click to toggle"
                        >
                          <Power className="w-3 h-3" />
                          {row.status}
                        </button>
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
                    {isExpanded && (
                      <tr className="bg-slate-50/50">
                        <td colSpan={6} className="px-4 py-2 text-xs">
                          <div className="grid grid-cols-2 gap-2 mb-2">
                            <div>
                              <span className="text-slate-500">Next fire:</span>{' '}
                              <span className="font-mono">
                                {row.next_fire_at ? new Date(row.next_fire_at).toLocaleString() : '—'}
                              </span>
                              {row.next_fire_at && (
                                <span className="ml-1 text-slate-500">({formatRelative(row.next_fire_at)})</span>
                              )}
                            </div>
                            <div>
                              <span className="text-slate-500">Created:</span>{' '}
                              <span className="font-mono">
                                {row.created_at ? new Date(row.created_at).toLocaleString() : '—'}
                              </span>
                            </div>
                            <div className="col-span-2">
                              <span className="text-slate-500">Payload:</span>{' '}
                              <code className="font-mono">{JSON.stringify(row.payload)}</code>
                            </div>
                          </div>
                          <div className="font-semibold mt-2 mb-1 text-slate-600">Recent fires</div>
                          {histories[row.name] === undefined ? (
                            <div className="text-slate-500">Loading…</div>
                          ) : histories[row.name].length === 0 ? (
                            <div className="text-slate-500">No fires recorded yet.</div>
                          ) : (
                            <ul className="space-y-0.5 font-mono">
                              {histories[row.name].slice().reverse().map((f, i) => (
                                <li key={i}>
                                  <span>{new Date(f.fired_at).toLocaleString()}</span>
                                  {f.task_id && <span className="ml-2 text-slate-500">task: {f.task_id.slice(0, 12)}</span>}
                                  {f.status && <span className="ml-2">[{f.status}]</span>}
                                  {f.error && <span className="ml-2 text-red-600">{f.error}</span>}
                                </li>
                              ))}
                            </ul>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
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
  // PR-F.4.2 — friendly cron description.
  const [cronDescription, setCronDescription] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    describeCron(cronExpr).then((desc) => {
      if (!cancelled) setCronDescription(desc);
    });
    return () => {
      cancelled = true;
    };
  }, [cronExpr]);

  // PR-F.4.2 — kind-aware payload presets so the operator doesn't
  // have to remember the right keys.
  useEffect(() => {
    if (targetKind === 'local_bash' && payloadJson.trim() === '{}') {
      setPayloadJson('{"command":"echo hello"}');
    } else if (targetKind === 'local_agent' && !payloadJson.includes('input_text')) {
      setPayloadJson('{"input_text":"What\'s the time?"}');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetKind]);

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
          {cronDescription && (
            <span className="text-xs text-slate-500 mt-1 italic">
              ⏱ {cronDescription}
            </span>
          )}
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
