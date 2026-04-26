'use client';

/**
 * SkillsTab — view + edit user skills (PR-F.2.4 + PR-F.2.5).
 *
 * Lists every loaded skill (bundled + user) and lets the operator
 * create / edit / delete user skills via /api/skills/user. A header
 * toggle flips ``settings.skills.user_skills_enabled`` so the skills
 * actually load on the next session — no env var required.
 */

import { useEffect, useMemo, useState } from 'react';
import { agentApi, skillsApi, frameworkSettingsApi, SkillDetail } from '@/lib/api';
import { Sparkles, Plus, Pencil, Trash2, X, RefreshCw, Power } from 'lucide-react';

interface SkillRow {
  id: string | null;
  name: string | null;
  description: string | null;
  allowed_tools: string[];
  category?: string | null;
  effort?: string | null;
  examples?: string[];
}

interface FormState {
  id: string;
  name: string;
  description: string;
  body: string;
  category: string;
  effort: string;
  model_override: string;
  allowed_tools: string;
  examples: string;
}

const EMPTY_FORM: FormState = {
  id: '',
  name: '',
  description: '',
  body: '',
  category: '',
  effort: '',
  model_override: '',
  allowed_tools: '',
  examples: '',
};

function formToPayload(f: FormState) {
  return {
    id: f.id.trim(),
    name: f.name.trim(),
    description: f.description.trim(),
    body: f.body,
    model_override: f.model_override.trim() || null,
    category: f.category.trim() || null,
    effort: f.effort.trim() || null,
    allowed_tools: f.allowed_tools.split(',').map((s) => s.trim()).filter(Boolean),
    examples: f.examples.split('\n').map((s) => s.trim()).filter(Boolean),
  };
}

function detailToForm(d: SkillDetail): FormState {
  return {
    id: d.id,
    name: d.name ?? '',
    description: d.description ?? '',
    body: d.body,
    category: d.category ?? '',
    effort: d.effort ?? '',
    model_override: d.model ?? '',
    allowed_tools: d.allowed_tools.join(', '),
    examples: d.examples.join('\n'),
  };
}

export function SkillsTab() {
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [userSkillsEnabled, setUserSkillsEnabled] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingExisting, setEditingExisting] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  // Map id → details cache so we know which rows are user-editable.
  const [userIds, setUserIds] = useState<Set<string>>(new Set());

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await agentApi.skillsList();
      setSkills(list.skills as SkillRow[]);

      // Probe each detail to identify user skills (cheap — there are
      // typically <30 skills total and these endpoints are local).
      const ids = (list.skills.map((s) => s.id).filter(Boolean) as string[]);
      const details = await Promise.allSettled(ids.map((id) => skillsApi.get(id)));
      const userSet = new Set<string>();
      details.forEach((r) => {
        if (r.status === 'fulfilled' && r.value.is_user_skill) userSet.add(r.value.id);
      });
      setUserIds(userSet);

      // Settings.json side: skills.user_skills_enabled.
      try {
        const sec = await frameworkSettingsApi.get('skills');
        const v = sec.values as { user_skills_enabled?: boolean };
        setUserSkillsEnabled(!!v.user_skills_enabled);
      } catch {
        setUserSkillsEnabled(null);
      }
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
    const map = new Map<string, SkillRow[]>();
    skills.forEach((s) => {
      const cat = s.category || (s.id && userIds.has(s.id) ? 'user' : 'bundled');
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(s);
    });
    return map;
  }, [skills, userIds]);

  const openCreate = () => {
    setEditingExisting(false);
    setForm(EMPTY_FORM);
    setEditorOpen(true);
  };

  const openEdit = async (id: string) => {
    setEditingExisting(true);
    try {
      const detail = await skillsApi.get(id);
      setForm(detailToForm(detail));
      setEditorOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const submitForm = async () => {
    const payload = formToPayload(form);
    if (!payload.id || !payload.name || !payload.description) {
      setError('id, name, description are all required');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editingExisting) {
        await skillsApi.replaceUserSkill(payload);
      } else {
        await skillsApi.createUserSkill(payload);
      }
      setEditorOpen(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (id: string) => {
    if (!window.confirm(`Delete user skill /${id}?`)) return;
    try {
      await skillsApi.deleteUserSkill(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const onToggleEnabled = async () => {
    if (userSkillsEnabled === null) return;
    setError(null);
    try {
      await frameworkSettingsApi.patch('skills', {
        user_skills_enabled: !userSkillsEnabled,
      });
      setUserSkillsEnabled((v) => !v);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <header className="px-4 py-3 border-b border-[var(--border-color)] flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold flex items-center gap-2">
            <Sparkles size={14} className="text-[var(--primary-color)]" />
            Skills
          </h2>
          <p className="text-[0.75rem] text-[var(--text-muted)]">
            {skills.length} loaded · {userIds.size} user
            {userSkillsEnabled !== null && (
              <>
                {' · '}
                <button
                  type="button"
                  onClick={onToggleEnabled}
                  className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[0.625rem] ${
                    userSkillsEnabled
                      ? 'bg-green-100 text-green-800 border-green-300'
                      : 'bg-gray-100 text-gray-800 border-gray-300'
                  }`}
                >
                  <Power className="w-3 h-3" />
                  user_skills_enabled: {userSkillsEnabled ? 'true' : 'false'}
                </button>
              </>
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
            Add user skill
          </button>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-1 text-xs border rounded px-2 py-1 disabled:opacity-50"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
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
        {Array.from(grouped.entries()).map(([cat, rows]) => (
          <section key={cat}>
            <h3 className="text-[0.6875rem] uppercase tracking-wider text-[var(--text-muted)] font-semibold mb-1">
              {cat} <span className="font-normal">({rows.length})</span>
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
              {rows.map((s, idx) => {
                const isUser = !!(s.id && userIds.has(s.id));
                return (
                  <div
                    key={s.id ?? `${cat}-${idx}`}
                    className="border border-[var(--border-color)] rounded p-2 hover:border-[var(--primary-color)]"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-semibold text-[0.8125rem]">/{s.id}</span>
                      {isUser && (
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => s.id && openEdit(s.id)}
                            className="text-[var(--text-muted)] hover:text-[var(--primary-color)]"
                            title="Edit"
                          >
                            <Pencil className="w-3 h-3" />
                          </button>
                          <button
                            type="button"
                            onClick={() => s.id && onDelete(s.id)}
                            className="text-[var(--text-muted)] hover:text-red-600"
                            title="Delete"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      )}
                    </div>
                    <div className="text-[0.75rem] text-[var(--text-secondary)] mt-1 line-clamp-2">
                      {s.description ?? s.name ?? '—'}
                    </div>
                    {s.allowed_tools.length > 0 && (
                      <div className="text-[0.625rem] text-[var(--text-muted)] mt-1">
                        {s.allowed_tools.length} tool{s.allowed_tools.length === 1 ? '' : 's'}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        ))}
        {!loading && skills.length === 0 && (
          <div className="text-sm text-[var(--text-muted)] text-center py-8">
            No skills loaded.
          </div>
        )}
      </div>

      {editorOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={() => !saving && setEditorOpen(false)}
        >
          <div
            className="bg-[var(--bg-primary)] rounded-lg border border-[var(--border-color)] w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="px-4 py-2 border-b border-[var(--border-color)] flex items-center justify-between">
              <h3 className="text-sm font-semibold">
                {editingExisting ? `Edit /${form.id}` : 'New user skill'}
              </h3>
              <button
                type="button"
                onClick={() => setEditorOpen(false)}
                disabled={saving}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              >
                <X size={14} />
              </button>
            </header>
            <div className="overflow-y-auto p-4 grid gap-2 text-[0.75rem]">
              <label>
                <div className="text-[var(--text-muted)] mb-0.5">ID *</div>
                <input
                  value={form.id}
                  onChange={(e) => setForm({ ...form, id: e.target.value })}
                  disabled={editingExisting}
                  placeholder="lower-case, dash/underscore allowed"
                  className="w-full border rounded px-2 py-1 text-[0.8125rem] font-mono disabled:opacity-50"
                />
              </label>
              <label>
                <div className="text-[var(--text-muted)] mb-0.5">Name *</div>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full border rounded px-2 py-1 text-[0.8125rem]"
                />
              </label>
              <label>
                <div className="text-[var(--text-muted)] mb-0.5">Description *</div>
                <input
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  className="w-full border rounded px-2 py-1 text-[0.8125rem]"
                />
              </label>
              <div className="grid grid-cols-3 gap-2">
                <label>
                  <div className="text-[var(--text-muted)] mb-0.5">Category</div>
                  <input
                    value={form.category}
                    onChange={(e) => setForm({ ...form, category: e.target.value })}
                    className="w-full border rounded px-2 py-1 text-[0.8125rem]"
                  />
                </label>
                <label>
                  <div className="text-[var(--text-muted)] mb-0.5">Effort (low/medium/high)</div>
                  <input
                    value={form.effort}
                    onChange={(e) => setForm({ ...form, effort: e.target.value })}
                    className="w-full border rounded px-2 py-1 text-[0.8125rem]"
                  />
                </label>
                <label>
                  <div className="text-[var(--text-muted)] mb-0.5">Model override</div>
                  <input
                    value={form.model_override}
                    onChange={(e) => setForm({ ...form, model_override: e.target.value })}
                    className="w-full border rounded px-2 py-1 text-[0.8125rem] font-mono"
                  />
                </label>
              </div>
              <label>
                <div className="text-[var(--text-muted)] mb-0.5">Allowed tools (CSV; empty = inherit)</div>
                <input
                  value={form.allowed_tools}
                  onChange={(e) => setForm({ ...form, allowed_tools: e.target.value })}
                  placeholder="Read, Write, Bash"
                  className="w-full border rounded px-2 py-1 text-[0.8125rem] font-mono"
                />
              </label>
              <label>
                <div className="text-[var(--text-muted)] mb-0.5">Examples (one per line)</div>
                <textarea
                  value={form.examples}
                  onChange={(e) => setForm({ ...form, examples: e.target.value })}
                  rows={2}
                  className="w-full border rounded px-2 py-1 text-[0.8125rem] font-mono"
                />
              </label>
              <label>
                <div className="text-[var(--text-muted)] mb-0.5">Body (markdown — what the LLM sees)</div>
                <textarea
                  value={form.body}
                  onChange={(e) => setForm({ ...form, body: e.target.value })}
                  rows={10}
                  className="w-full border rounded px-2 py-1 text-[0.8125rem] font-mono"
                />
              </label>
            </div>
            <footer className="px-4 py-2 border-t border-[var(--border-color)] flex justify-end gap-2">
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
                disabled={saving}
                className="text-xs bg-[var(--primary-color)] text-white rounded px-3 py-1 disabled:opacity-50"
              >
                {saving ? 'Saving…' : editingExisting ? 'Save' : 'Create'}
              </button>
            </footer>
          </div>
        </div>
      )}
    </div>
  );
}

export default SkillsTab;
