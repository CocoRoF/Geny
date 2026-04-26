'use client';

/**
 * HooksTab — view & edit the executor's HookConfig (PR-E.3.3).
 *
 * Three sections:
 *   1. Header: enabled gate + env-opt-in (GENY_ALLOW_HOOKS) + audit path.
 *   2. Entries: per-event grouped table + Add/Edit modal.
 *   3. Recent fires: tail of audit_log_path JSONL (PR-E.3.2).
 *
 * Both gates (config-side enabled + env opt-in) must be open for hooks
 * to actually fire. The header surfaces both so an operator can see at
 * a glance why an entry isn't firing.
 */

import { useEffect, useMemo, useState } from 'react';
import { twMerge } from 'tailwind-merge';
import {
  hookApi,
  HOOK_EVENTS,
  HookEvent,
  HookEntryPayload,
  HookEntryRow,
  HookEntriesResponse,
  HookListResponse,
  HookFiresResponse,
} from '@/lib/api';
import { RefreshCw, Plus, Pencil, Trash2, X, Power } from 'lucide-react';

function cn(...c: (string | boolean | undefined | null)[]) {
  return twMerge(c.filter(Boolean).join(' '));
}

interface EntryFormState {
  event: HookEvent;
  command: string;       // free-text shell-split
  timeout_ms: string;    // free-text → parseInt
  tool_filter: string;   // CSV
}

const EMPTY_FORM: EntryFormState = {
  event: 'PRE_TOOL_USE',
  command: '',
  timeout_ms: '',
  tool_filter: '',
};

function splitShell(s: string): string[] {
  // Naive split — good enough for the common case (one command + a
  // few args). Operators with complex pipelines should pass a single
  // sh -c ... entry.
  return s
    .trim()
    .split(/\s+/)
    .filter((p) => p.length > 0);
}

function formToPayload(f: EntryFormState): HookEntryPayload {
  const ms = f.timeout_ms.trim() ? Number.parseInt(f.timeout_ms.trim(), 10) : null;
  return {
    event: f.event,
    command: splitShell(f.command),
    timeout_ms: ms !== null && !Number.isNaN(ms) ? ms : null,
    tool_filter: f.tool_filter
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0),
  };
}

export function HooksTab() {
  const [editable, setEditable] = useState<HookEntriesResponse | null>(null);
  const [inspect, setInspect] = useState<HookListResponse | null>(null);
  const [fires, setFires] = useState<HookFiresResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingTarget, setEditingTarget] = useState<{ event: string; idx: number } | null>(null);
  const [form, setForm] = useState<EntryFormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [edit, ins, recent] = await Promise.all([
        hookApi.listEditable(),
        hookApi.inspect(),
        hookApi.recentFires(50),
      ]);
      setEditable(edit);
      setInspect(ins);
      setFires(recent);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const grouped = useMemo(() => {
    const map = new Map<string, HookEntryRow[]>();
    (editable?.entries ?? []).forEach((row) => {
      if (!map.has(row.event)) map.set(row.event, []);
      map.get(row.event)!.push(row);
    });
    return map;
  }, [editable]);

  const openCreate = () => {
    setEditingTarget(null);
    setForm(EMPTY_FORM);
    setEditorOpen(true);
  };

  const openEdit = (row: HookEntryRow) => {
    setEditingTarget({ event: row.event, idx: row.idx });
    setForm({
      event: row.event as HookEvent,
      command: row.command.join(' '),
      timeout_ms: row.timeout_ms != null ? String(row.timeout_ms) : '',
      tool_filter: (row.tool_filter ?? []).join(', '),
    });
    setEditorOpen(true);
  };

  const submitForm = async () => {
    const payload = formToPayload(form);
    if (payload.command.length === 0) {
      setError('command is required');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = editingTarget
        ? await hookApi.replace(editingTarget.event, editingTarget.idx, payload)
        : await hookApi.append(payload);
      setEditable(res);
      try {
        const ins = await hookApi.inspect();
        setInspect(ins);
      } catch {/* ignore */}
      setEditorOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const deleteEntry = async (row: HookEntryRow) => {
    const confirmed = window.confirm(
      `Delete hook ${row.event}#${row.idx} (${row.command.join(' ')})?`,
    );
    if (!confirmed) return;
    setError(null);
    try {
      const res = await hookApi.remove(row.event, row.idx);
      setEditable(res);
      try {
        const ins = await hookApi.inspect();
        setInspect(ins);
      } catch {/* ignore */}
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const toggleEnabled = async () => {
    if (!editable) return;
    setError(null);
    try {
      const res = await hookApi.setEnabled(!editable.enabled);
      setEditable(res);
      try {
        const ins = await hookApi.inspect();
        setInspect(ins);
      } catch {/* ignore */}
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const totalEditable = editable?.entries.length ?? 0;
  const totalLoaded = inspect?.entries.length ?? 0;
  const fileEnabled = editable?.enabled ?? false;
  const envOptIn = inspect?.env_opt_in ?? false;
  const willFire = fileEnabled && envOptIn;

  return (
    <div className="flex flex-col h-full min-h-0">
      <header className="px-4 py-3 border-b border-[var(--border-color)] flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold flex items-center gap-2">
            Hooks
            <span
              className={cn(
                'text-[0.625rem] font-mono uppercase px-1.5 py-0.5 rounded border',
                willFire
                  ? 'bg-green-100 text-green-800 border-green-300'
                  : 'bg-amber-100 text-amber-800 border-amber-300',
              )}
              title={
                willFire
                  ? 'Both file flag and GENY_ALLOW_HOOKS are set — hooks will fire.'
                  : 'Hooks will NOT fire — both file flag AND GENY_ALLOW_HOOKS env var must be set.'
              }
            >
              {willFire ? 'live' : 'gated'}
            </span>
          </h2>
          <p className="text-[0.75rem] text-[var(--text-muted)]">
            File: <button
              type="button"
              onClick={toggleEnabled}
              className={cn(
                'inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[0.625rem]',
                fileEnabled
                  ? 'bg-green-100 text-green-800 border-green-300'
                  : 'bg-gray-100 text-gray-800 border-gray-300',
              )}
            >
              <Power className="w-3 h-3" />
              {fileEnabled ? 'enabled' : 'disabled'}
            </button>
            {' · '}
            Env <span className="font-mono">GENY_ALLOW_HOOKS</span>:{' '}
            <span className={cn('font-mono', envOptIn ? 'text-green-700' : 'text-red-600')}>
              {envOptIn ? 'set' : 'unset'}
            </span>
            {' · '}
            {totalEditable} editable / {totalLoaded} loaded
            {editable && (
              <> · <span className="font-mono">{editable.settings_path}</span></>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={openCreate}
            className="flex items-center gap-1 text-xs bg-[var(--primary-color)] text-white rounded px-2 py-1"
          >
            <Plus className="w-3 h-3" />
            Add hook
          </button>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-1 text-xs border rounded px-2 py-1 disabled:opacity-50"
          >
            <RefreshCw className={cn('w-3 h-3', loading && 'animate-spin')} />
            Refresh
          </button>
        </div>
      </header>

      {error && (
        <div className="m-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2">
          {error}
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-4">
        {/* ── Entries grouped by event ── */}
        <section>
          <h3 className="text-[0.6875rem] uppercase tracking-wider text-[var(--text-muted)] font-semibold mb-2">
            Entries
          </h3>
          {totalEditable === 0 && !loading ? (
            <div className="text-sm text-[var(--text-muted)] text-center py-4">
              No entries. Click <span className="font-mono">Add hook</span> to create one.
            </div>
          ) : (
            <div className="space-y-3">
              {Array.from(grouped.entries()).map(([event, rows]) => (
                <div key={event} className="border border-[var(--border-color)] rounded">
                  <div className="px-2 py-1 bg-[var(--bg-tertiary)] font-mono text-[0.75rem] font-semibold border-b border-[var(--border-color)]">
                    {event} <span className="text-[var(--text-muted)] font-normal">({rows.length})</span>
                  </div>
                  <table className="w-full text-[0.8125rem]">
                    <thead>
                      <tr className="text-[0.6875rem] uppercase tracking-wider text-[var(--text-muted)]">
                        <th className="text-left py-1 px-2 w-8">#</th>
                        <th className="text-left py-1 px-2">Command</th>
                        <th className="text-left py-1 px-2 w-20">Timeout</th>
                        <th className="text-left py-1 px-2 w-40">Tool filter</th>
                        <th className="text-right py-1 px-2 w-20">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={`${row.event}-${row.idx}`} className="border-t border-[var(--border-color)] hover:bg-[var(--bg-tertiary)]">
                          <td className="py-1 px-2 text-[var(--text-muted)] font-mono text-[0.75rem]">{row.idx}</td>
                          <td className="py-1 px-2 font-mono text-[0.75rem]">{row.command.join(' ') || '—'}</td>
                          <td className="py-1 px-2 text-[0.75rem]">{row.timeout_ms != null ? `${row.timeout_ms}ms` : '—'}</td>
                          <td className="py-1 px-2 text-[0.75rem] font-mono text-[var(--text-secondary)]">
                            {(row.tool_filter ?? []).join(', ') || '*'}
                          </td>
                          <td className="py-1 px-2 text-right">
                            <div className="flex items-center justify-end gap-1">
                              <button
                                type="button"
                                onClick={() => openEdit(row)}
                                className="text-[var(--text-muted)] hover:text-[var(--primary-color)]"
                                title="Edit"
                              >
                                <Pencil className="w-3.5 h-3.5" />
                              </button>
                              <button
                                type="button"
                                onClick={() => deleteEntry(row)}
                                className="text-[var(--text-muted)] hover:text-red-600"
                                title="Delete"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ── Recent fires ── */}
        <section>
          <h3 className="text-[0.6875rem] uppercase tracking-wider text-[var(--text-muted)] font-semibold mb-2">
            Recent fires
            {fires?.audit_path && (
              <span className="ml-2 text-[var(--text-muted)] font-normal font-mono normal-case">
                {fires.audit_path}
              </span>
            )}
          </h3>
          {!fires?.audit_path ? (
            <div className="text-[0.75rem] text-[var(--text-muted)]">
              No <span className="font-mono">audit_log_path</span> configured. Add one to <span className="font-mono">hooks</span> in settings.json to see fires here.
            </div>
          ) : !fires.exists ? (
            <div className="text-[0.75rem] text-[var(--text-muted)]">
              Audit log file not yet created — fires will appear here once a hook runs.
            </div>
          ) : fires.fires.length === 0 ? (
            <div className="text-[0.75rem] text-[var(--text-muted)]">No fires yet.</div>
          ) : (
            <div className="border border-[var(--border-color)] rounded overflow-hidden">
              {fires.truncated && (
                <div className="px-2 py-1 text-[0.6875rem] text-amber-800 bg-amber-50 border-b border-amber-200">
                  Truncated — older fires omitted.
                </div>
              )}
              <ul className="max-h-72 overflow-y-auto divide-y divide-[var(--border-color)]">
                {fires.fires.slice().reverse().map((row, i) => (
                  <li key={i} className="px-2 py-1.5 text-[0.75rem] font-mono">
                    <details>
                      <summary className="cursor-pointer truncate">
                        {String(row.record.event ?? row.record.hook_event ?? 'fire')}
                        {' · '}
                        {String(row.record.tool_name ?? row.record.payload_tool_name ?? '')}
                        {' · '}
                        <span className="text-[var(--text-muted)]">
                          {String(row.record.ts ?? row.record.timestamp ?? '')}
                        </span>
                      </summary>
                      <pre className="mt-1 text-[0.6875rem] text-[var(--text-secondary)] whitespace-pre-wrap">
                        {JSON.stringify(row.record, null, 2)}
                      </pre>
                    </details>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </div>

      {editorOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={() => !saving && setEditorOpen(false)}
        >
          <div
            className="bg-[var(--bg-primary)] rounded-lg border border-[var(--border-color)] w-full max-w-md p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold">
                {editingTarget ? `Edit ${editingTarget.event}#${editingTarget.idx}` : 'Add hook'}
              </h3>
              <button
                type="button"
                onClick={() => setEditorOpen(false)}
                disabled={saving}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              >
                <X className="w-4 h-4" />
              </button>
            </header>
            <div className="grid gap-2">
              <label className="text-[0.75rem]">
                <div className="text-[var(--text-muted)] mb-0.5">Event</div>
                <select
                  value={form.event}
                  onChange={(e) => setForm({ ...form, event: e.target.value as HookEvent })}
                  disabled={!!editingTarget}
                  className="w-full border rounded px-2 py-1 text-[0.8125rem] disabled:opacity-50"
                  title={editingTarget ? 'Change event by deleting and re-adding' : ''}
                >
                  {HOOK_EVENTS.map((ev) => (
                    <option key={ev} value={ev}>{ev}</option>
                  ))}
                </select>
              </label>
              <label className="text-[0.75rem]">
                <div className="text-[var(--text-muted)] mb-0.5">Command (space-separated argv)</div>
                <input
                  value={form.command}
                  onChange={(e) => setForm({ ...form, command: e.target.value })}
                  placeholder="./scripts/log-hook.sh"
                  className="w-full border rounded px-2 py-1 text-[0.8125rem] font-mono"
                />
              </label>
              <label className="text-[0.75rem]">
                <div className="text-[var(--text-muted)] mb-0.5">Timeout (ms, optional)</div>
                <input
                  value={form.timeout_ms}
                  onChange={(e) => setForm({ ...form, timeout_ms: e.target.value })}
                  placeholder="1000"
                  inputMode="numeric"
                  className="w-full border rounded px-2 py-1 text-[0.8125rem]"
                />
              </label>
              <label className="text-[0.75rem]">
                <div className="text-[var(--text-muted)] mb-0.5">Tool filter (CSV; empty = match any)</div>
                <input
                  value={form.tool_filter}
                  onChange={(e) => setForm({ ...form, tool_filter: e.target.value })}
                  placeholder="Bash, Read"
                  className="w-full border rounded px-2 py-1 text-[0.8125rem] font-mono"
                />
              </label>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditorOpen(false)}
                disabled={saving}
                className="text-xs border rounded px-3 py-1"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submitForm}
                disabled={saving || !form.command.trim()}
                className="text-xs bg-[var(--primary-color)] text-white rounded px-3 py-1 disabled:opacity-50"
              >
                {saving ? 'Saving…' : editingTarget ? 'Save' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default HooksTab;
