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
import { toast } from 'sonner';
import { agentApi, skillsApi, frameworkSettingsApi, SkillDetail } from '@/lib/api';
import { Sparkles, Plus, Pencil, Trash2, RefreshCw, Power } from 'lucide-react';
import {
  TabShell,
  EditorModal,
  EmptyState,
  StatusBadge,
  ActionButton,
} from '@/components/layout';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';

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
      toast.success(editingExisting ? `Updated /${payload.id}` : `Created /${payload.id}`);
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
      toast.success(`Deleted /${id}`);
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
    <TabShell
      title="Skills"
      icon={Sparkles}
      subtitle={
        <>
          {skills.length} loaded · {userIds.size} user
          {userSkillsEnabled !== null && (
            <>
              {' · '}
              <StatusBadge
                tone={userSkillsEnabled ? 'success' : 'neutral'}
                icon={Power}
                onClick={onToggleEnabled}
              >
                user_skills_enabled: {userSkillsEnabled ? 'true' : 'false'}
              </StatusBadge>
            </>
          )}
        </>
      }
      actions={
        <>
          <ActionButton variant="primary" icon={Plus} onClick={openCreate}>
            Add user skill
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
          <EmptyState icon={Sparkles} title="No skills loaded." />
        )}
      </div>

      <EditorModal
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        title={editingExisting ? `Edit /${form.id}` : 'New user skill'}
        saving={saving}
        width="xl"
        footer={
          <>
            <ActionButton onClick={() => setEditorOpen(false)} disabled={saving}>
              Cancel
            </ActionButton>
            <ActionButton variant="primary" onClick={submitForm} disabled={saving}>
              {saving ? 'Saving…' : editingExisting ? 'Save' : 'Create'}
            </ActionButton>
          </>
        }
      >
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="skill-id">ID *</Label>
            <Input
              id="skill-id"
              value={form.id}
              onChange={(e) => setForm({ ...form, id: e.target.value })}
              disabled={editingExisting}
              placeholder="lower-case, dash/underscore allowed"
              className="font-mono"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="skill-name">Name *</Label>
            <Input
              id="skill-name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="skill-desc">Description *</Label>
            <Input
              id="skill-desc"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div className="grid gap-1.5">
              <Label htmlFor="skill-cat">Category</Label>
              <Input
                id="skill-cat"
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="skill-eff">Effort</Label>
              <Input
                id="skill-eff"
                value={form.effort}
                onChange={(e) => setForm({ ...form, effort: e.target.value })}
                placeholder="low / medium / high"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="skill-model">Model override</Label>
              <Input
                id="skill-model"
                value={form.model_override}
                onChange={(e) => setForm({ ...form, model_override: e.target.value })}
                className="font-mono"
              />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="skill-tools">Allowed tools <span className="opacity-60">(CSV; empty = inherit)</span></Label>
            <Input
              id="skill-tools"
              value={form.allowed_tools}
              onChange={(e) => setForm({ ...form, allowed_tools: e.target.value })}
              placeholder="Read, Write, Bash"
              className="font-mono"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="skill-ex">Examples <span className="opacity-60">(one per line)</span></Label>
            <Textarea
              id="skill-ex"
              value={form.examples}
              onChange={(e) => setForm({ ...form, examples: e.target.value })}
              rows={2}
              className="font-mono"
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="skill-body">Body <span className="opacity-60">(markdown — what the LLM sees)</span></Label>
            <Textarea
              id="skill-body"
              value={form.body}
              onChange={(e) => setForm({ ...form, body: e.target.value })}
              rows={10}
              className="font-mono"
            />
          </div>
        </div>
      </EditorModal>
    </TabShell>
  );
}

export default SkillsTab;
