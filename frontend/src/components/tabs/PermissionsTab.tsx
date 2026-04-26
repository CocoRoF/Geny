'use client';

/**
 * PermissionsTab — view & edit the executor's permission rules
 * (PR-E.2.2). Lives behind the dev-only "Permissions" global tab.
 *
 * Layout:
 *   [Header: mode + sources consulted]
 *   [Rules table: tool / behavior / pattern / source / reason / actions]
 *   [Add modal: same fields, behavior+source dropdown]
 *
 * Read state comes from /api/permissions/list (cascade-merged) so the
 * operator sees what the matrix actually loaded — including yaml-only
 * rules that aren't editable here. Writes go through /api/permissions/rules
 * which mutates user-scope settings.json. Rules from non-user sources
 * surface in the table read-only with a hint pointing at the file.
 */

import { useEffect, useMemo, useState } from 'react';
import { twMerge } from 'tailwind-merge';
import {
  permissionApi,
  PermissionRulePayload,
  PermissionBehavior,
  PermissionSource,
  PermissionListResponse,
  PermissionRulesResponse,
} from '@/lib/api';
import { RefreshCw, Plus, Pencil, Trash2, X } from 'lucide-react';

function cn(...c: (string | boolean | undefined | null)[]) {
  return twMerge(c.filter(Boolean).join(' '));
}

const BEHAVIOR_OPTIONS: PermissionBehavior[] = ['allow', 'deny', 'ask'];
const SOURCE_OPTIONS: PermissionSource[] = ['user', 'project', 'local', 'cli', 'preset'];

const BEHAVIOR_BADGE: Record<string, string> = {
  allow: 'bg-green-100 text-green-800 border-green-300',
  deny: 'bg-red-100 text-red-800 border-red-300',
  ask: 'bg-amber-100 text-amber-800 border-amber-300',
};

interface RuleFormState {
  tool_name: string;
  behavior: PermissionBehavior;
  pattern: string;
  source: PermissionSource;
  reason: string;
}

const EMPTY_FORM: RuleFormState = {
  tool_name: '',
  behavior: 'ask',
  pattern: '',
  source: 'user',
  reason: '',
};

function formToPayload(f: RuleFormState): PermissionRulePayload {
  return {
    tool_name: f.tool_name.trim(),
    behavior: f.behavior,
    pattern: f.pattern.trim() ? f.pattern.trim() : null,
    source: f.source,
    reason: f.reason.trim() ? f.reason.trim() : null,
  };
}

export function PermissionsTab() {
  const [editable, setEditable] = useState<PermissionRulesResponse | null>(null);
  const [inspect, setInspect] = useState<PermissionListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [form, setForm] = useState<RuleFormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [edit, ins] = await Promise.all([
        permissionApi.listEditable(),
        permissionApi.inspect(),
      ]);
      setEditable(edit);
      setInspect(ins);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const editableCount = editable?.rules.length ?? 0;
  const inspectCount = inspect?.rules.length ?? 0;

  // Map index in editable.rules to ensure delete/replace target the
  // user-scope file. Non-user-scope rules from inspect are read-only
  // here (their PUT target index doesn't exist in editable).
  const editableIdxByKey = useMemo(() => {
    const map = new Map<string, number>();
    editable?.rules.forEach((r, idx) => {
      const key = `${r.tool_name}::${r.pattern ?? ''}::${r.behavior}::${r.source}`;
      map.set(key, idx);
    });
    return map;
  }, [editable]);

  const openCreate = () => {
    setEditingIdx(null);
    setForm(EMPTY_FORM);
    setEditorOpen(true);
  };

  const openEdit = (idx: number) => {
    const r = editable?.rules[idx];
    if (!r) return;
    setEditingIdx(idx);
    setForm({
      tool_name: r.tool_name,
      behavior: r.behavior,
      pattern: r.pattern ?? '',
      source: r.source ?? 'user',
      reason: r.reason ?? '',
    });
    setEditorOpen(true);
  };

  const submitForm = async () => {
    if (!form.tool_name.trim()) {
      setError('tool_name is required');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = formToPayload(form);
      const res = editingIdx === null
        ? await permissionApi.append(payload)
        : await permissionApi.replace(editingIdx, payload);
      setEditable(res);
      // Inspect view will go stale until next refresh; trigger one.
      try {
        const ins = await permissionApi.inspect();
        setInspect(ins);
      } catch {/* keep stale inspect — no harm */}
      setEditorOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const deleteRule = async (idx: number) => {
    const target = editable?.rules[idx];
    if (!target) return;
    const confirmed = window.confirm(
      `Delete permission rule for ${target.tool_name} (${target.behavior})?`,
    );
    if (!confirmed) return;
    setError(null);
    try {
      const res = await permissionApi.remove(idx);
      setEditable(res);
      try {
        const ins = await permissionApi.inspect();
        setInspect(ins);
      } catch {/* keep stale inspect */}
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <header className="px-4 py-3 border-b border-[var(--border-color)] flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Permissions</h2>
          <p className="text-[0.75rem] text-[var(--text-muted)]">
            Mode:{' '}
            <span className="font-mono uppercase">
              {inspect?.mode ?? '—'}
            </span>{' '}
            · {inspectCount} rule{inspectCount === 1 ? '' : 's'} loaded
            {editable && (
              <span> · {editableCount} editable in <span className="font-mono">{editable.settings_path}</span></span>
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
            Add rule
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

      <div className="flex-1 min-h-0 overflow-y-auto p-3">
        <table className="w-full text-[0.8125rem]">
          <thead>
            <tr className="text-[0.6875rem] uppercase tracking-wider text-[var(--text-muted)] border-b border-[var(--border-color)]">
              <th className="text-left py-1.5 px-2">Tool</th>
              <th className="text-left py-1.5 px-2">Behavior</th>
              <th className="text-left py-1.5 px-2">Pattern</th>
              <th className="text-left py-1.5 px-2">Source</th>
              <th className="text-left py-1.5 px-2">Reason</th>
              <th className="text-right py-1.5 px-2 w-20">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(inspect?.rules ?? []).map((r, viewIdx) => {
              const key = `${r.tool_name}::${r.pattern ?? ''}::${r.behavior}::${r.source}`;
              const editIdx = editableIdxByKey.get(key);
              const editable_ = editIdx !== undefined;
              return (
                <tr
                  key={`${key}-${viewIdx}`}
                  className="border-b border-[var(--border-color)] hover:bg-[var(--bg-tertiary)]"
                >
                  <td className="py-1.5 px-2 font-mono">{r.tool_name}</td>
                  <td className="py-1.5 px-2">
                    <span
                      className={cn(
                        'inline-block text-[0.6875rem] px-1.5 py-0.5 rounded border',
                        BEHAVIOR_BADGE[r.behavior] ?? 'bg-gray-100 text-gray-800 border-gray-300',
                      )}
                    >
                      {r.behavior}
                    </span>
                  </td>
                  <td className="py-1.5 px-2 font-mono text-[0.75rem]">{r.pattern ?? '—'}</td>
                  <td className="py-1.5 px-2 text-[0.75rem]">{r.source}</td>
                  <td className="py-1.5 px-2 text-[0.75rem] text-[var(--text-secondary)]">
                    {r.reason ?? ''}
                  </td>
                  <td className="py-1.5 px-2 text-right">
                    {editable_ ? (
                      <div className="flex items-center justify-end gap-1">
                        <button
                          type="button"
                          onClick={() => openEdit(editIdx!)}
                          className="text-[var(--text-muted)] hover:text-[var(--primary-color)]"
                          title="Edit"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteRule(editIdx!)}
                          className="text-[var(--text-muted)] hover:text-red-600"
                          title="Delete"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    ) : (
                      <span
                        className="text-[0.625rem] text-[var(--text-muted)] italic"
                        title="Read-only — defined outside user-scope settings.json"
                      >
                        external
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
            {(inspect?.rules ?? []).length === 0 && !loading && (
              <tr>
                <td colSpan={6} className="text-center py-6 text-[var(--text-muted)]">
                  No rules. Click <span className="font-mono">Add rule</span> to create one.
                </td>
              </tr>
            )}
          </tbody>
        </table>

        {inspect?.sources_consulted && inspect.sources_consulted.length > 0 && (
          <details className="mt-4 text-[0.75rem] text-[var(--text-muted)]">
            <summary className="cursor-pointer">Sources consulted ({inspect.sources_consulted.length})</summary>
            <ul className="mt-1 ml-4 list-disc">
              {inspect.sources_consulted.map((p) => (
                <li key={p} className="font-mono">{p}</li>
              ))}
            </ul>
          </details>
        )}
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
                {editingIdx === null ? 'Add rule' : `Edit rule #${editingIdx}`}
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
                <div className="text-[var(--text-muted)] mb-0.5">Tool name *</div>
                <input
                  value={form.tool_name}
                  onChange={(e) => setForm({ ...form, tool_name: e.target.value })}
                  placeholder="Bash, Read, * (any), ..."
                  className="w-full border rounded px-2 py-1 text-[0.8125rem] font-mono"
                />
              </label>
              <label className="text-[0.75rem]">
                <div className="text-[var(--text-muted)] mb-0.5">Behavior</div>
                <select
                  value={form.behavior}
                  onChange={(e) => setForm({ ...form, behavior: e.target.value as PermissionBehavior })}
                  className="w-full border rounded px-2 py-1 text-[0.8125rem]"
                >
                  {BEHAVIOR_OPTIONS.map((b) => (
                    <option key={b} value={b}>{b}</option>
                  ))}
                </select>
              </label>
              <label className="text-[0.75rem]">
                <div className="text-[var(--text-muted)] mb-0.5">Pattern (optional, glob/regex per executor)</div>
                <input
                  value={form.pattern}
                  onChange={(e) => setForm({ ...form, pattern: e.target.value })}
                  placeholder="git push *"
                  className="w-full border rounded px-2 py-1 text-[0.8125rem] font-mono"
                />
              </label>
              <label className="text-[0.75rem]">
                <div className="text-[var(--text-muted)] mb-0.5">Source</div>
                <select
                  value={form.source}
                  onChange={(e) => setForm({ ...form, source: e.target.value as PermissionSource })}
                  className="w-full border rounded px-2 py-1 text-[0.8125rem]"
                >
                  {SOURCE_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label className="text-[0.75rem]">
                <div className="text-[var(--text-muted)] mb-0.5">Reason (optional, surfaced in UI)</div>
                <textarea
                  value={form.reason}
                  onChange={(e) => setForm({ ...form, reason: e.target.value })}
                  rows={2}
                  className="w-full border rounded px-2 py-1 text-[0.8125rem]"
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
                disabled={saving || !form.tool_name.trim()}
                className="text-xs bg-[var(--primary-color)] text-white rounded px-3 py-1 disabled:opacity-50"
              >
                {saving ? 'Saving…' : editingIdx === null ? 'Create' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default PermissionsTab;
