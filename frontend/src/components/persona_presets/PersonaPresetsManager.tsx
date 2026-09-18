'use client';

/**
 * Persona — the Geny persona builder.
 *
 * Preset model (mirrors environments / tool presets): built-in **presets** are
 * read-only starters; the user **clones** one into an editable **custom** persona.
 * A persona = structured config (MBTI/Enneagram/archetype + OCEAN + expressive
 * sliders + speech + emotion + identity) that compiles to a persona prompt the
 * backend injects when an environment attaches it.
 *
 * The LIST view uses the shared host-registry chrome (RegistryPageShell /
 * RegistryGrid / RegistryCard); the builder is the per-persona edit screen.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { ArrowLeft, Save, Wand2, Drama, Trash2, Copy, Lock } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import RegistryPageShell from '@/components/registry/RegistryPageShell';
import RegistryGrid from '@/components/registry/RegistryGrid';
import RegistryCard, {
  type RegistryCardBadge,
} from '@/components/registry/RegistryCard';
import RegistryActionButton from '@/components/registry/RegistryActionButton';
import RegistryEmptyState from '@/components/registry/RegistryEmptyState';
import {
  personaPresetsApi,
  type PersonaPresetSummary,
  type PersonaPresetDefinition,
  type PersonaFrameworks,
} from '@/lib/api';

const EMPTY: PersonaPresetDefinition = {
  name: '',
  description: '',
  mbti: '',
  enneagram: '',
  archetype: '',
  ocean: { openness: 50, conscientiousness: 50, extraversion: 50, agreeableness: 50, neuroticism: 50 },
  style: { warmth: 50, humor: 50, playfulness: 50, formality: 50, assertiveness: 50, verbosity: 50, emoji: 50, enthusiasm: 50, directness: 50 },
  speech: { honorific: 'auto', self_reference: '', catchphrases: [], verbal_tics: [] },
  emotion: { default_mood: 'neutral', expressiveness: 50, preferred_tags: [] },
  identity: { display_name: '', age_vibe: '', role: '', interests: [], backstory: '' },
  prompt_override: '',
};

const clone = (d: PersonaPresetDefinition): PersonaPresetDefinition =>
  JSON.parse(JSON.stringify(d));

export default function PersonaPresetsManager() {
  const { t } = useI18n();
  const [presets, setPresets] = useState<PersonaPresetSummary[]>([]);
  const [frameworks, setFrameworks] = useState<PersonaFrameworks | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<'list' | 'edit'>('list');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [readOnly, setReadOnly] = useState(false);
  const [draft, setDraft] = useState<PersonaPresetDefinition>(clone(EMPTY));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = await personaPresetsApi.list();
      setPresets(p.presets);
      if (!frameworks) setFrameworks(await personaPresetsApi.frameworks());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [frameworks]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fail = (e: unknown) =>
    toast.error(t('personaPresets.failed', { error: e instanceof Error ? e.message : String(e) }));

  const openNew = () => {
    setEditingId(null);
    setReadOnly(false);
    setDraft(clone(EMPTY));
    setMode('edit');
  };

  const open = async (id: string, ro: boolean) => {
    try {
      const full = await personaPresetsApi.get(id);
      setEditingId(id);
      setReadOnly(ro);
      setDraft({ ...clone(EMPTY), ...full });
      setMode('edit');
    } catch (e) {
      fail(e);
    }
  };

  // Clone any definition into a fresh editable custom persona, then open it.
  const cloneFrom = async (src: PersonaPresetDefinition) => {
    try {
      const copy: PersonaPresetDefinition = {
        ...clone(src),
        id: undefined,
        is_template: false,
        name: t('personaPresets.copyName', { name: src.name }),
      };
      const created = await personaPresetsApi.create(copy);
      toast.success(t('personaPresets.cloned', { name: created.name }));
      await load();
      setEditingId(created.id ?? null);
      setReadOnly(false);
      setDraft({ ...clone(EMPTY), ...created });
      setMode('edit');
    } catch (e) {
      fail(e);
    }
  };

  const cloneById = async (id: string) => {
    try {
      cloneFrom(await personaPresetsApi.get(id));
    } catch (e) {
      fail(e);
    }
  };

  const remove = async (p: PersonaPresetSummary) => {
    if (!window.confirm(t('personaPresets.deleteConfirm', { name: p.name }))) return;
    try {
      await personaPresetsApi.remove(p.id);
      toast.success(t('personaPresets.deleted', { name: p.name }));
      void load();
    } catch (e) {
      fail(e);
    }
  };

  const save = async () => {
    if (!draft.name.trim()) {
      toast.error(t('personaPresets.nameRequired'));
      return;
    }
    try {
      if (editingId) await personaPresetsApi.update(editingId, draft);
      else await personaPresetsApi.create(draft);
      toast.success(t('personaPresets.saved', { name: draft.name }));
      setMode('list');
      void load();
    } catch (e) {
      fail(e);
    }
  };

  if (mode === 'edit' && frameworks) {
    return (
      <Editor
        draft={draft}
        setDraft={setDraft}
        frameworks={frameworks}
        editing={!!editingId}
        readOnly={readOnly}
        onBack={() => setMode('list')}
        onSave={save}
        onClone={() => cloneFrom(draft)}
      />
    );
  }

  const builtins = presets.filter((p) => p.is_template);
  const customs = presets.filter((p) => !p.is_template);

  const card = (p: PersonaPresetSummary, builtin: boolean) => {
    const badges: RegistryCardBadge[] = [];
    if (p.mbti) badges.push({ label: p.mbti, tone: 'info' });
    if (p.enneagram) badges.push({ label: `E${p.enneagram}`, tone: 'neutral' });
    if (p.archetype) badges.push({ label: p.archetype, tone: 'neutral' });
    if (builtin) badges.push({ label: t('personaPresets.template'), tone: 'neutral', icon: Lock });
    return (
      <RegistryCard
        key={p.id}
        icon={Drama}
        title={p.name}
        description={p.description}
        badges={badges}
        onClick={() => void open(p.id, builtin)}
        actions={
          builtin ? (
            <RegistryActionButton icon={Copy} title={t('personaPresets.clone')} variant="primary" onClick={() => void cloneById(p.id)} />
          ) : (
            <>
              <RegistryActionButton icon={Copy} title={t('personaPresets.clone')} onClick={() => void cloneById(p.id)} />
              <RegistryActionButton icon={Trash2} title={t('personaPresets.delete')} variant="danger" onClick={() => void remove(p)} />
            </>
          )
        }
      />
    );
  };

  return (
    <RegistryPageShell
      title={t('personaPresets.title')}
      subtitle={t('personaPresets.subtitle')}
      icon={Drama}
      countLabel={presets.length ? `${presets.length}개` : undefined}
      addLabel={t('personaPresets.new')}
      onAdd={openNew}
      onRefresh={() => void load()}
      loading={loading}
      error={error}
      onDismissError={() => setError(null)}
    >
      {presets.length === 0 && !loading ? (
        <RegistryEmptyState
          icon={Drama}
          title={t('personaPresets.empty.title')}
          hint={t('personaPresets.empty.desc')}
          addLabel={t('personaPresets.new')}
          onAdd={openNew}
        />
      ) : (
        <>
          {builtins.length > 0 && (
            <Group label={t('personaPresets.sections.presets')} hint={t('personaPresets.sections.presetsHint')}>
              <RegistryGrid>{builtins.map((p) => card(p, true))}</RegistryGrid>
            </Group>
          )}
          <Group label={t('personaPresets.sections.custom')} hint={t('personaPresets.sections.customHint')}>
            {customs.length > 0 ? (
              <RegistryGrid>{customs.map((p) => card(p, false))}</RegistryGrid>
            ) : (
              <p className="text-[0.75rem] text-[hsl(var(--muted-foreground))] px-0.5">
                {t('personaPresets.custom.empty')}
              </p>
            )}
          </Group>
        </>
      )}
    </RegistryPageShell>
  );
}

function Group({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-end justify-between gap-2">
        <span className="text-[0.6875rem] uppercase tracking-wider text-[hsl(var(--muted-foreground))] font-semibold">{label}</span>
        {hint && <span className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────

function Editor({
  draft,
  setDraft,
  frameworks,
  editing,
  readOnly,
  onBack,
  onSave,
  onClone,
}: {
  draft: PersonaPresetDefinition;
  setDraft: (d: PersonaPresetDefinition) => void;
  frameworks: PersonaFrameworks;
  editing: boolean;
  readOnly: boolean;
  onBack: () => void;
  onSave: () => void;
  onClone: () => void;
}) {
  const { t } = useI18n();
  const [preview, setPreview] = useState('');
  const [compiling, setCompiling] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Live compile (debounced) so the author sees the actual injected prompt.
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    setCompiling(true);
    timer.current = setTimeout(async () => {
      try {
        const r = await personaPresetsApi.compile(draft);
        setPreview(r.compiled_prompt);
      } catch {
        /* preview is best-effort */
      } finally {
        setCompiling(false);
      }
    }, 350);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [draft]);

  const patch = (p: Partial<PersonaPresetDefinition>) => setDraft({ ...draft, ...p });
  const patchOcean = (k: keyof PersonaPresetDefinition['ocean'], v: number) =>
    setDraft({ ...draft, ocean: { ...draft.ocean, [k]: v } });
  const patchStyle = (k: keyof PersonaPresetDefinition['style'], v: number) =>
    setDraft({ ...draft, style: { ...draft.style, [k]: v } });
  const patchSpeech = (p: Partial<PersonaPresetDefinition['speech']>) =>
    setDraft({ ...draft, speech: { ...draft.speech, ...p } });
  const patchEmotion = (p: Partial<PersonaPresetDefinition['emotion']>) =>
    setDraft({ ...draft, emotion: { ...draft.emotion, ...p } });
  const patchIdentity = (p: Partial<PersonaPresetDefinition['identity']>) =>
    setDraft({ ...draft, identity: { ...draft.identity, ...p } });

  return (
    <div className="flex flex-col h-full min-h-0 bg-[hsl(var(--background))] text-[hsl(var(--foreground))]">
      {/* sticky chrome */}
      <div className="flex items-center justify-between gap-3 px-6 py-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0">
        <button onClick={onBack} className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md text-[0.8125rem] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors">
          <ArrowLeft size={15} /> {t('personaPresets.back')}
        </button>
        {readOnly ? (
          <button onClick={onClone} className="inline-flex items-center gap-1.5 h-8 px-3.5 rounded-md bg-violet-500 hover:bg-violet-600 text-white text-[0.8125rem] font-medium transition-colors shadow-sm">
            <Copy size={15} /> {t('personaPresets.cloneAndEdit')}
          </button>
        ) : (
          <button onClick={onSave} className="inline-flex items-center gap-1.5 h-8 px-3.5 rounded-md bg-violet-500 hover:bg-violet-600 text-white text-[0.8125rem] font-medium transition-colors shadow-sm">
            <Save size={15} /> {editing ? t('personaPresets.update') : t('personaPresets.create')}
          </button>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-[1200px] mx-auto px-6 py-6 flex flex-col gap-4">
          {readOnly && (
            <div className="flex items-start gap-2 px-3 py-2 rounded-lg border border-amber-500/25 bg-amber-500/5 text-[0.75rem] text-amber-800 dark:text-amber-300">
              <Lock className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>{t('personaPresets.readOnlyBanner')}</span>
            </div>
          )}
          <div className="grid lg:grid-cols-2 gap-5">
            {/* ── left: the builder form (disabled wholesale when read-only) ── */}
            <fieldset disabled={readOnly} className="flex flex-col gap-5 min-w-0 m-0 p-0 border-0 disabled:opacity-70">
              <Section title={t('personaPresets.sections.basic')}>
                <Text label={t('personaPresets.f.name')} value={draft.name} onChange={(v) => patch({ name: v })} placeholder="예: 밝은 비서" />
                <Text label={t('personaPresets.f.description')} value={draft.description} onChange={(v) => patch({ description: v })} />
              </Section>

              <Section title={t('personaPresets.sections.framework')}>
                <div className="grid grid-cols-3 gap-2">
                  <Select label="MBTI" value={draft.mbti} onChange={(v) => patch({ mbti: v })}
                    options={[{ value: '', label: '—' }, ...frameworks.mbti.map((m) => ({ value: m.code, label: `${m.code} ${m.label_ko}` }))]} />
                  <Select label="Enneagram" value={draft.enneagram} onChange={(v) => patch({ enneagram: v })}
                    options={[{ value: '', label: '—' }, ...frameworks.enneagram.map((m) => ({ value: m.code, label: `${m.code} ${m.label_ko}` }))]} />
                  <Select label={t('personaPresets.f.archetype')} value={draft.archetype} onChange={(v) => patch({ archetype: v })}
                    options={[{ value: '', label: '—' }, ...frameworks.archetypes.map((m) => ({ value: m.code, label: m.label_ko }))]} />
                </div>
              </Section>

              <Section title={t('personaPresets.sections.ocean')}>
                {frameworks.ocean_axes.map((a) => (
                  <Slider key={a.key} label={a.label_ko} low={a.low} high={a.high}
                    value={(draft.ocean as unknown as Record<string, number>)[a.key] ?? 50}
                    onChange={(v) => patchOcean(a.key as keyof PersonaPresetDefinition['ocean'], v)} />
                ))}
              </Section>

              <Section title={t('personaPresets.sections.style')}>
                {frameworks.style_axes.map((a) => (
                  <Slider key={a.key} label={a.label_ko} low={a.low} high={a.high}
                    value={(draft.style as unknown as Record<string, number>)[a.key] ?? 50}
                    onChange={(v) => patchStyle(a.key as keyof PersonaPresetDefinition['style'], v)} />
                ))}
              </Section>

              <Section title={t('personaPresets.sections.speech')}>
                <Select label={t('personaPresets.f.honorific')} value={draft.speech.honorific} onChange={(v) => patchSpeech({ honorific: v })}
                  options={frameworks.honorifics.map((h) => ({ value: h.code, label: h.label_ko }))} />
                <Text label={t('personaPresets.f.selfReference')} value={draft.speech.self_reference} onChange={(v) => patchSpeech({ self_reference: v })} placeholder="예: 나, 저, 이름" />
                <CommaList label={t('personaPresets.f.catchphrases')} value={draft.speech.catchphrases} onChange={(v) => patchSpeech({ catchphrases: v })} />
                <CommaList label={t('personaPresets.f.verbalTics')} value={draft.speech.verbal_tics} onChange={(v) => patchSpeech({ verbal_tics: v })} />
              </Section>

              <Section title={t('personaPresets.sections.emotion')}>
                <Select label={t('personaPresets.f.defaultMood')} value={draft.emotion.default_mood} onChange={(v) => patchEmotion({ default_mood: v })}
                  options={frameworks.emotion_tags.map((tag) => ({ value: tag, label: tag }))} />
                <Slider label={t('personaPresets.f.expressiveness')} low={t('personaPresets.low')} high={t('personaPresets.high')}
                  value={draft.emotion.expressiveness} onChange={(v) => patchEmotion({ expressiveness: v })} />
                <TagPicker label={t('personaPresets.f.preferredTags')} all={frameworks.emotion_tags}
                  value={draft.emotion.preferred_tags} onChange={(v) => patchEmotion({ preferred_tags: v })} />
              </Section>

              <Section title={t('personaPresets.sections.identity')}>
                <div className="grid grid-cols-2 gap-2">
                  <Text label={t('personaPresets.f.displayName')} value={draft.identity.display_name} onChange={(v) => patchIdentity({ display_name: v })} />
                  <Text label={t('personaPresets.f.ageVibe')} value={draft.identity.age_vibe} onChange={(v) => patchIdentity({ age_vibe: v })} placeholder="예: 또래 친구" />
                </div>
                <Text label={t('personaPresets.f.role')} value={draft.identity.role} onChange={(v) => patchIdentity({ role: v })} placeholder="예: 다정한 AI 친구" />
                <CommaList label={t('personaPresets.f.interests')} value={draft.identity.interests} onChange={(v) => patchIdentity({ interests: v })} />
                <Area label={t('personaPresets.f.backstory')} value={draft.identity.backstory} onChange={(v) => patchIdentity({ backstory: v })} rows={3} />
              </Section>
            </fieldset>

            {/* ── right: live preview + override ── */}
            <div className="flex flex-col gap-3 lg:sticky lg:top-0 lg:self-start">
              <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[0.78rem] font-semibold text-[hsl(var(--foreground))] flex items-center gap-1.5">
                    <Wand2 size={14} className="text-[hsl(var(--primary))]" /> {t('personaPresets.preview')}
                  </span>
                  <span className="text-[0.65rem] text-[hsl(var(--muted-foreground))] font-mono">
                    {compiling ? '…' : `${preview.length} chars`}
                  </span>
                </div>
                <pre className="whitespace-pre-wrap text-[0.72rem] leading-relaxed text-[hsl(var(--foreground))] font-mono max-h-[40vh] overflow-y-auto">
                  {preview || t('personaPresets.previewEmpty')}
                </pre>
              </div>
              <fieldset disabled={readOnly} className="m-0 p-0 border-0 disabled:opacity-70">
                <Area
                  label={t('personaPresets.f.override')}
                  hint={t('personaPresets.overrideHint')}
                  value={draft.prompt_override}
                  onChange={(v) => patch({ prompt_override: v })}
                  rows={4}
                />
              </fieldset>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── primitives (hsl token system, to match the env-editor neighbours) ──

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2.5">
      <h3 className="text-[0.7rem] font-semibold uppercase tracking-wide text-[hsl(var(--muted-foreground))]">{title}</h3>
      <div className="flex flex-col gap-2.5">{children}</div>
    </div>
  );
}

const inputCls =
  'w-full h-9 px-2.5 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[0.8125rem] text-[hsl(var(--foreground))] focus:outline-none focus:ring-2 focus:ring-violet-500/40 disabled:cursor-not-allowed';

function Lbl({ children }: { children: React.ReactNode }) {
  return <label className="text-[0.72rem] font-medium text-[hsl(var(--foreground))]">{children}</label>;
}

function Text({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <Lbl>{label}</Lbl>
      <input className={inputCls} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function Area({ label, value, onChange, rows = 3, hint }: { label: string; value: string; onChange: (v: string) => void; rows?: number; hint?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <Lbl>{label}</Lbl>
      <textarea
        rows={rows}
        className="w-full px-2.5 py-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[0.8125rem] text-[hsl(var(--foreground))] focus:outline-none focus:ring-2 focus:ring-violet-500/40 resize-y disabled:cursor-not-allowed"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && <span className="text-[0.65rem] text-[hsl(var(--muted-foreground))]">{hint}</span>}
    </div>
  );
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <div className="flex flex-col gap-1">
      <Lbl>{label}</Lbl>
      <select className={inputCls} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}

function Slider({ label, low, high, value, onChange }: { label: string; low: string; high: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-0.5">
        <span className="text-[0.72rem] font-medium text-[hsl(var(--foreground))]">{label}</span>
        <span className="text-[0.65rem] font-mono text-[hsl(var(--muted-foreground))]">{value}</span>
      </div>
      <input type="range" min={0} max={100} value={value} onChange={(e) => onChange(parseInt(e.target.value, 10))} className="w-full accent-violet-600 disabled:cursor-not-allowed" />
      <div className="flex items-center justify-between text-[0.6rem] text-[hsl(var(--muted-foreground))]">
        <span>{low}</span><span>{high}</span>
      </div>
    </div>
  );
}

function CommaList({ label, value, onChange }: { label: string; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <Text
      label={label}
      value={value.join(', ')}
      onChange={(v) => onChange(v.split(',').map((s) => s.trim()).filter(Boolean))}
      placeholder="쉼표로 구분"
    />
  );
}

function TagPicker({ label, all, value, onChange }: { label: string; all: string[]; value: string[]; onChange: (v: string[]) => void }) {
  const toggle = (tag: string) =>
    onChange(value.includes(tag) ? value.filter((x) => x !== tag) : [...value, tag]);
  return (
    <div className="flex flex-col gap-1.5">
      <Lbl>{label}</Lbl>
      <div className="flex flex-wrap gap-1.5">
        {all.map((tag) => {
          const on = value.includes(tag);
          return (
            <button
              key={tag}
              type="button"
              onClick={() => toggle(tag)}
              className={
                'text-[0.68rem] px-2 py-0.5 rounded-full border transition-colors disabled:cursor-not-allowed ' +
                (on
                  ? 'bg-violet-600 border-violet-600 text-white'
                  : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:border-violet-400')
              }
            >
              {tag}
            </button>
          );
        })}
      </div>
    </div>
  );
}
