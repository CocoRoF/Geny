'use client';

/**
 * HooksTab — view & edit the executor's HookConfig.
 *
 * H.2 (cycle 20260426_2) — full schema rewrite to match the executor's
 * ``HookConfigEntry`` after H.1 fixed the backend. Inputs:
 *   - event picker (16 lowercase HookEvent values)
 *   - command (single executable) + args (one per line)
 *   - match dict editor (key/value rows; today's only meaningful key is "tool")
 *   - env table (key/value rows)
 *   - working_dir (optional)
 *   - timeout_ms (optional)
 *   - top-level audit_log_path
 *
 * Header still surfaces the dual gate (file-side ``enabled`` + env opt-in
 * ``GENY_ALLOW_HOOKS``) so the operator sees at a glance why an entry
 * isn't firing.
 */

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
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
import { RefreshCw, Plus, Pencil, Trash2, Power, Plug, X } from 'lucide-react';
import {
  TabShell,
  EditorModal,
  EmptyState,
  StatusBadge,
  ActionButton,
} from '@/components/layout';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface KvRow {
  key: string;
  value: string;
}

interface EntryFormState {
  event: HookEvent;
  command: string;        // single executable
  argsText: string;       // one per line
  timeout_ms: string;     // free-text → parseInt
  match: KvRow[];         // dict rows
  env: KvRow[];           // dict rows
  working_dir: string;
}

const EMPTY_FORM: EntryFormState = {
  event: 'pre_tool_use',
  command: '',
  argsText: '',
  timeout_ms: '',
  match: [],
  env: [],
  working_dir: '',
};

function rowsToDict(rows: KvRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rows) {
    const k = r.key.trim();
    if (!k) continue;
    out[k] = r.value;
  }
  return out;
}

function dictToRows(d: Record<string, unknown> | null | undefined): KvRow[] {
  if (!d || typeof d !== 'object') return [];
  return Object.entries(d).map(([k, v]) => ({ key: k, value: String(v ?? '') }));
}

function formToPayload(f: EntryFormState): HookEntryPayload {
  const ms = f.timeout_ms.trim() ? Number.parseInt(f.timeout_ms.trim(), 10) : null;
  const args = f.argsText
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  const wd = f.working_dir.trim();
  return {
    event: f.event,
    command: f.command.trim(),
    args: args.length ? args : undefined,
    timeout_ms: ms !== null && !Number.isNaN(ms) ? ms : null,
    match: f.match.length ? rowsToDict(f.match) : undefined,
    env: f.env.length ? rowsToDict(f.env) : undefined,
    working_dir: wd.length ? wd : null,
  };
}

function rowToForm(row: HookEntryRow): EntryFormState {
  return {
    event: row.event as HookEvent,
    command: row.command,
    argsText: (row.args ?? []).join('\n'),
    timeout_ms: row.timeout_ms != null ? String(row.timeout_ms) : '',
    match: dictToRows(row.match),
    env: dictToRows(row.env),
    working_dir: row.working_dir ?? '',
  };
}

function summarizeMatch(m: Record<string, unknown> | undefined): string {
  if (!m) return '*';
  const entries = Object.entries(m);
  if (entries.length === 0) return '*';
  return entries.map(([k, v]) => `${k}=${String(v)}`).join(', ');
}

function KvEditor({
  rows,
  onChange,
  keyPlaceholder = 'key',
  valuePlaceholder = 'value',
  emptyHint,
}: {
  rows: KvRow[];
  onChange: (rows: KvRow[]) => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  emptyHint?: string;
}) {
  return (
    <div className="grid gap-1.5">
      {rows.length === 0 && emptyHint && (
        <div className="text-[0.6875rem] text-[var(--text-muted)] italic">{emptyHint}</div>
      )}
      {rows.map((row, i) => (
        <div key={i} className="flex gap-1.5 items-center">
          <Input
            value={row.key}
            placeholder={keyPlaceholder}
            onChange={(e) => {
              const next = [...rows];
              next[i] = { ...next[i], key: e.target.value };
              onChange(next);
            }}
            className="font-mono text-[0.75rem] flex-1"
          />
          <Input
            value={row.value}
            placeholder={valuePlaceholder}
            onChange={(e) => {
              const next = [...rows];
              next[i] = { ...next[i], value: e.target.value };
              onChange(next);
            }}
            className="font-mono text-[0.75rem] flex-1"
          />
          <button
            type="button"
            onClick={() => onChange(rows.filter((_, j) => j !== i))}
            className="text-[var(--text-muted)] hover:text-red-600 p-1"
            title="Remove"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...rows, { key: '', value: '' }])}
        className="text-[0.75rem] text-[var(--primary-color)] hover:underline self-start"
      >
        + Add row
      </button>
    </div>
  );
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

  const [auditDraft, setAuditDraft] = useState('');
  const [savingAudit, setSavingAudit] = useState(false);

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
      setAuditDraft(edit.audit_log_path ?? '');
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
    setForm(rowToForm(row));
    setEditorOpen(true);
  };

  const submitForm = async () => {
    const payload = formToPayload(form);
    if (!payload.command) {
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
      setAuditDraft(res.audit_log_path ?? '');
      try {
        const ins = await hookApi.inspect();
        setInspect(ins);
      } catch {/* ignore */}
      toast.success(editingTarget ? 'Hook updated' : 'Hook added');
      setEditorOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const deleteEntry = async (row: HookEntryRow) => {
    const confirmed = window.confirm(
      `Delete hook ${row.event}#${row.idx} (${row.command})?`,
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
      toast.success(`Removed hook ${row.event}#${row.idx}`);
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

  const saveAuditLog = async () => {
    setSavingAudit(true);
    setError(null);
    try {
      const trimmed = auditDraft.trim();
      const res = await hookApi.setAuditLog(trimmed.length ? trimmed : null);
      setEditable(res);
      setAuditDraft(res.audit_log_path ?? '');
      toast.success(trimmed ? 'Audit log path saved' : 'Audit log path cleared');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingAudit(false);
    }
  };

  const totalEditable = editable?.entries.length ?? 0;
  const totalLoaded = inspect?.entries.length ?? 0;
  const fileEnabled = editable?.enabled ?? false;
  const envOptIn = inspect?.env_opt_in ?? false;
  const willFire = fileEnabled && envOptIn;

  return (
    <TabShell
      title="Hooks"
      icon={Plug}
      subtitle={
        <>
          File:{' '}
          <StatusBadge
            tone={fileEnabled ? 'success' : 'neutral'}
            icon={Power}
            onClick={toggleEnabled}
          >
            {fileEnabled ? 'enabled' : 'disabled'}
          </StatusBadge>
          {' · Env '}
          <span className="font-mono">GENY_ALLOW_HOOKS</span>:{' '}
          <span className={'font-mono ' + (envOptIn ? 'text-green-700' : 'text-red-600')}>
            {envOptIn ? 'set' : 'unset'}
          </span>
          {' · '}
          {totalEditable} editable / {totalLoaded} loaded
          {editable && <> · <span className="font-mono">{editable.settings_path}</span></>}
        </>
      }
      actions={
        <>
          <StatusBadge
            tone={willFire ? 'success' : 'warning'}
            uppercase
            title={
              willFire
                ? 'Both file flag and GENY_ALLOW_HOOKS are set — hooks will fire.'
                : 'Hooks will NOT fire — both file flag AND GENY_ALLOW_HOOKS env var must be set.'
            }
          >
            {willFire ? 'live' : 'gated'}
          </StatusBadge>
          <ActionButton variant="primary" icon={Plus} onClick={openCreate}>
            Add hook
          </ActionButton>
          <ActionButton icon={RefreshCw} spinIcon={loading} onClick={refresh} disabled={loading}>
            Refresh
          </ActionButton>
        </>
      }
      error={error}
      onDismissError={() => setError(null)}
    >
      <div className="h-full min-h-0 overflow-y-auto p-3 space-y-4">
        {/* ── Audit log path ── */}
        <section className="border border-[var(--border-color)] rounded p-3">
          <h3 className="text-[0.6875rem] uppercase tracking-wider text-[var(--text-muted)] font-semibold mb-2">
            Audit log
          </h3>
          <div className="flex gap-1.5 items-center">
            <Input
              value={auditDraft}
              onChange={(e) => setAuditDraft(e.target.value)}
              placeholder="/var/log/geny/hooks.jsonl"
              className="font-mono text-[0.75rem]"
            />
            <ActionButton
              onClick={saveAuditLog}
              disabled={savingAudit || (auditDraft.trim() === (editable?.audit_log_path ?? ''))}
            >
              {savingAudit ? 'Saving…' : 'Save'}
            </ActionButton>
          </div>
          <div className="mt-1 text-[0.6875rem] text-[var(--text-muted)]">
            Empty = no audit log. Recommended for production so each fire is traceable.
          </div>
        </section>

        {/* ── Entries grouped by event ── */}
        <section>
          <h3 className="text-[0.6875rem] uppercase tracking-wider text-[var(--text-muted)] font-semibold mb-2">
            Entries
          </h3>
          {totalEditable === 0 && !loading ? (
            <EmptyState
              compact
              title="No entries"
              description={<>Click <span className="font-mono">Add hook</span> to create one.</>}
            />
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
                        <th className="text-left py-1 px-2">Args</th>
                        <th className="text-left py-1 px-2 w-20">Timeout</th>
                        <th className="text-left py-1 px-2 w-40">Match</th>
                        <th className="text-right py-1 px-2 w-20">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={`${row.event}-${row.idx}`} className="border-t border-[var(--border-color)] hover:bg-[var(--bg-tertiary)]">
                          <td className="py-1 px-2 text-[var(--text-muted)] font-mono text-[0.75rem]">{row.idx}</td>
                          <td className="py-1 px-2 font-mono text-[0.75rem] truncate max-w-[200px]">{row.command || '—'}</td>
                          <td className="py-1 px-2 font-mono text-[0.75rem] text-[var(--text-secondary)] truncate max-w-[200px]">
                            {(row.args ?? []).join(' ') || '—'}
                          </td>
                          <td className="py-1 px-2 text-[0.75rem]">{row.timeout_ms != null ? `${row.timeout_ms}ms` : '—'}</td>
                          <td className="py-1 px-2 text-[0.75rem] font-mono text-[var(--text-secondary)] truncate">
                            {summarizeMatch(row.match)}
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
              No <span className="font-mono">audit_log_path</span> configured. Set one above to capture fires.
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

      <EditorModal
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        title={editingTarget ? `Edit ${editingTarget.event}#${editingTarget.idx}` : 'Add hook'}
        saving={saving}
        footer={
          <>
            <ActionButton onClick={() => setEditorOpen(false)} disabled={saving}>
              Cancel
            </ActionButton>
            <ActionButton
              variant="primary"
              onClick={submitForm}
              disabled={saving || !form.command.trim()}
            >
              {saving ? 'Saving…' : editingTarget ? 'Save' : 'Create'}
            </ActionButton>
          </>
        }
      >
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label>Event</Label>
            <Select
              value={form.event}
              onValueChange={(v) => setForm({ ...form, event: v as HookEvent })}
              disabled={!!editingTarget}
            >
              <SelectTrigger title={editingTarget ? 'Change event by deleting and re-adding' : ''}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {HOOK_EVENTS.map((ev) => (
                  <SelectItem key={ev} value={ev}>{ev}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="hook-cmd">Command <span className="opacity-60">(single executable path)</span></Label>
            <Input
              id="hook-cmd"
              value={form.command}
              onChange={(e) => setForm({ ...form, command: e.target.value })}
              placeholder="/usr/local/bin/audit-hook"
              className="font-mono"
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="hook-args">Args <span className="opacity-60">(one per line; no shell interpolation)</span></Label>
            <Textarea
              id="hook-args"
              value={form.argsText}
              onChange={(e) => setForm({ ...form, argsText: e.target.value })}
              placeholder={'--session\n${session_id}'}
              className="font-mono text-[0.75rem]"
              rows={3}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="hook-timeout">Timeout <span className="opacity-60">(ms)</span></Label>
              <Input
                id="hook-timeout"
                value={form.timeout_ms}
                onChange={(e) => setForm({ ...form, timeout_ms: e.target.value })}
                placeholder="5000"
                inputMode="numeric"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="hook-wd">Working dir <span className="opacity-60">(optional)</span></Label>
              <Input
                id="hook-wd"
                value={form.working_dir}
                onChange={(e) => setForm({ ...form, working_dir: e.target.value })}
                placeholder="/tmp"
                className="font-mono"
              />
            </div>
          </div>

          <div className="grid gap-1.5">
            <Label>Match <span className="opacity-60">(empty = match every event of this kind; today only the &quot;tool&quot; key is honored)</span></Label>
            <KvEditor
              rows={form.match}
              onChange={(rows) => setForm({ ...form, match: rows })}
              keyPlaceholder="tool"
              valuePlaceholder="Bash"
              emptyHint='No match filter — fires for every event. Add e.g. tool=Bash to limit.'
            />
          </div>

          <div className="grid gap-1.5">
            <Label>Env <span className="opacity-60">(extra environment variables for the subprocess)</span></Label>
            <KvEditor
              rows={form.env}
              onChange={(rows) => setForm({ ...form, env: rows })}
              keyPlaceholder="DEBUG"
              valuePlaceholder="1"
              emptyHint="No extra env. Parent env is inherited."
            />
          </div>
        </div>
      </EditorModal>
    </TabShell>
  );
}

export default HooksTab;
