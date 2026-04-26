'use client';

/**
 * ModelConfigEditor — P.2 (cycle 20260426_2).
 *
 * Form panel for ``manifest.model`` (a.k.a. ``ModelConfig``). Mirrors
 * every field on executor's ``ModelConfig`` except ``api_key`` (deploy
 * secret).
 *
 * Save semantics: shallow-merge against current values; only changed
 * keys are PATCHed. Empty inputs are treated as "leave unchanged"
 * rather than "clear" — to clear an optional field, edit the manifest
 * via ImportManifestModal.
 */

import { useEffect, useMemo, useState } from 'react';
import { Save, RotateCcw } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ActionButton } from '@/components/layout';

const THINKING_TYPE_VALUES = ['enabled', 'disabled', 'adaptive'] as const;
const THINKING_DISPLAY_VALUES = ['summarized', 'omitted'] as const;
type ThinkingType = (typeof THINKING_TYPE_VALUES)[number];
type ThinkingDisplay = (typeof THINKING_DISPLAY_VALUES)[number] | '';

export interface ModelDraft {
  model: string;
  max_tokens: string;
  temperature: string;
  top_p: string;
  top_k: string;
  stop_sequences: string;       // one per line
  thinking_enabled: boolean;
  thinking_budget_tokens: string;
  thinking_type: ThinkingType | '';
  thinking_display: ThinkingDisplay;
}

export interface ModelConfigEditorProps {
  initial: Record<string, unknown>;
  saving: boolean;
  error: string | null;
  onSave: (changes: Record<string, unknown>) => void;
  onClearError: () => void;
}

function snapshotToDraft(src: Record<string, unknown>): ModelDraft {
  const tt = typeof src.thinking_type === 'string' && THINKING_TYPE_VALUES.includes(src.thinking_type as ThinkingType)
    ? (src.thinking_type as ThinkingType)
    : '';
  const td = typeof src.thinking_display === 'string' && THINKING_DISPLAY_VALUES.includes(src.thinking_display as ThinkingDisplay)
    ? (src.thinking_display as ThinkingDisplay)
    : '';
  const stop = Array.isArray(src.stop_sequences)
    ? (src.stop_sequences as string[]).join('\n')
    : '';
  return {
    model: typeof src.model === 'string' ? src.model : '',
    max_tokens: typeof src.max_tokens === 'number' ? String(src.max_tokens) : '',
    temperature: typeof src.temperature === 'number' ? String(src.temperature) : '',
    top_p: typeof src.top_p === 'number' ? String(src.top_p) : '',
    top_k: typeof src.top_k === 'number' ? String(src.top_k) : '',
    stop_sequences: stop,
    thinking_enabled: typeof src.thinking_enabled === 'boolean' ? src.thinking_enabled : false,
    thinking_budget_tokens:
      typeof src.thinking_budget_tokens === 'number' ? String(src.thinking_budget_tokens) : '',
    thinking_type: tt,
    thinking_display: td,
  };
}

function buildChanges(
  initial: Record<string, unknown>,
  draft: ModelDraft,
): { ok: true; changes: Record<string, unknown> } | { ok: false; error: string } {
  const out: Record<string, unknown> = {};

  if (draft.model && draft.model !== initial.model) out.model = draft.model;

  // ints
  for (const [key, raw, min] of [
    ['max_tokens', draft.max_tokens, 1] as const,
    ['top_k', draft.top_k, 1] as const,
    ['thinking_budget_tokens', draft.thinking_budget_tokens, 1] as const,
  ]) {
    if (!raw.trim()) continue;
    const n = Number.parseInt(raw, 10);
    if (Number.isNaN(n) || n < min) {
      return { ok: false, error: `${key}: must be an integer >= ${min}` };
    }
    if (n !== initial[key]) out[key] = n;
  }

  // floats with bounds
  if (draft.temperature.trim()) {
    const n = Number.parseFloat(draft.temperature);
    if (Number.isNaN(n) || n < 0 || n > 2) {
      return { ok: false, error: 'temperature: must be in [0.0, 2.0]' };
    }
    if (n !== initial.temperature) out.temperature = n;
  }
  if (draft.top_p.trim()) {
    const n = Number.parseFloat(draft.top_p);
    if (Number.isNaN(n) || n < 0 || n > 1) {
      return { ok: false, error: 'top_p: must be in [0.0, 1.0]' };
    }
    if (n !== initial.top_p) out.top_p = n;
  }

  // stop_sequences (newline-delimited)
  if (draft.stop_sequences.trim()) {
    const arr = draft.stop_sequences
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    const initJson = JSON.stringify(initial.stop_sequences ?? []);
    const newJson = JSON.stringify(arr);
    if (initJson !== newJson) out.stop_sequences = arr;
  }

  if (draft.thinking_enabled !== (initial.thinking_enabled ?? false)) {
    out.thinking_enabled = draft.thinking_enabled;
  }
  if (draft.thinking_type && draft.thinking_type !== initial.thinking_type) {
    out.thinking_type = draft.thinking_type;
  }
  if (draft.thinking_display && draft.thinking_display !== initial.thinking_display) {
    out.thinking_display = draft.thinking_display;
  }

  return { ok: true, changes: out };
}

export function ModelConfigEditor({
  initial,
  saving,
  error,
  onSave,
  onClearError,
}: ModelConfigEditorProps) {
  const [draft, setDraft] = useState<ModelDraft>(() => snapshotToDraft(initial));

  useEffect(() => {
    setDraft(snapshotToDraft(initial));
  }, [initial]);

  const buildResult = useMemo(() => buildChanges(initial, draft), [initial, draft]);
  const dirty = buildResult.ok ? Object.keys(buildResult.changes).length > 0 : true;

  const handleSave = () => {
    if (!buildResult.ok) return;
    if (Object.keys(buildResult.changes).length === 0) return;
    onSave(buildResult.changes);
  };

  const handleReset = () => {
    setDraft(snapshotToDraft(initial));
    onClearError();
  };

  const update = <K extends keyof ModelDraft>(key: K, value: ModelDraft[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
    onClearError();
  };

  return (
    <section className="flex flex-col gap-4 max-w-[720px]">
      <header className="flex items-center justify-between">
        <div className="flex flex-col gap-0.5">
          <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">
            Model config
          </h3>
          <p className="text-[0.75rem] text-[var(--text-muted)]">
            Sampling parameters + extended thinking knobs. Shallow-merged on
            save — only changed fields are sent. ``api_key`` is intentionally
            not editable here.
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <ActionButton icon={RotateCcw} onClick={handleReset} disabled={saving || !dirty}>
            Reset
          </ActionButton>
          <ActionButton
            variant="primary"
            icon={Save}
            onClick={handleSave}
            disabled={saving || !dirty || !buildResult.ok}
          >
            {saving ? 'Saving…' : 'Save'}
          </ActionButton>
        </div>
      </header>

      {error && (
        <div className="px-3 py-2 rounded-md bg-[rgba(239,68,68,0.1)] border border-[rgba(239,68,68,0.3)] text-[0.75rem] text-[var(--danger-color)]">
          {error}
        </div>
      )}
      {!buildResult.ok && (
        <div className="px-3 py-2 rounded-md bg-[rgba(245,158,11,0.1)] border border-[rgba(245,158,11,0.3)] text-[0.75rem] text-[var(--warning-color)]">
          {buildResult.error}
        </div>
      )}

      <div className="grid gap-1.5">
        <Label htmlFor="md-model">model</Label>
        <Input
          id="md-model"
          value={draft.model}
          onChange={(e) => update('model', e.target.value)}
          placeholder="claude-sonnet-4-20250514"
          className="font-mono text-[0.75rem]"
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="grid gap-1.5">
          <Label htmlFor="md-max-tokens">
            max_tokens <span className="opacity-60">(int &gt;= 1)</span>
          </Label>
          <Input
            id="md-max-tokens"
            value={draft.max_tokens}
            onChange={(e) => update('max_tokens', e.target.value)}
            placeholder="8192"
            inputMode="numeric"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="md-temp">
            temperature <span className="opacity-60">(0.0 – 2.0)</span>
          </Label>
          <Input
            id="md-temp"
            value={draft.temperature}
            onChange={(e) => update('temperature', e.target.value)}
            placeholder="0.0"
            inputMode="decimal"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="md-top-p">
            top_p <span className="opacity-60">(0.0 – 1.0)</span>
          </Label>
          <Input
            id="md-top-p"
            value={draft.top_p}
            onChange={(e) => update('top_p', e.target.value)}
            placeholder="(unset)"
            inputMode="decimal"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="md-top-k">
            top_k <span className="opacity-60">(int &gt;= 1)</span>
          </Label>
          <Input
            id="md-top-k"
            value={draft.top_k}
            onChange={(e) => update('top_k', e.target.value)}
            placeholder="(unset)"
            inputMode="numeric"
          />
        </div>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="md-stop">
          stop_sequences <span className="opacity-60">(one per line)</span>
        </Label>
        <Textarea
          id="md-stop"
          value={draft.stop_sequences}
          onChange={(e) => update('stop_sequences', e.target.value)}
          rows={3}
          className="font-mono text-[0.75rem]"
          placeholder={'</response>\nSTOP'}
        />
      </div>

      <fieldset className="grid gap-3 border border-[var(--border-color)] rounded-md p-3">
        <legend className="px-1 text-[0.75rem] font-medium text-[var(--text-secondary)]">
          Extended thinking
        </legend>
        <label className="flex items-center gap-2 text-[0.8125rem] cursor-pointer">
          <Switch
            checked={draft.thinking_enabled}
            onCheckedChange={(v) => update('thinking_enabled', !!v)}
          />
          thinking_enabled
        </label>
        <div className="grid grid-cols-3 gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="md-think-budget">
              thinking_budget_tokens <span className="opacity-60">(int &gt;= 1)</span>
            </Label>
            <Input
              id="md-think-budget"
              value={draft.thinking_budget_tokens}
              onChange={(e) => update('thinking_budget_tokens', e.target.value)}
              placeholder="10000"
              inputMode="numeric"
              disabled={!draft.thinking_enabled}
            />
          </div>
          <div className="grid gap-1.5">
            <Label>thinking_type</Label>
            <Select
              value={draft.thinking_type || undefined}
              onValueChange={(v) => update('thinking_type', v as ThinkingType)}
              disabled={!draft.thinking_enabled}
            >
              <SelectTrigger>
                <SelectValue placeholder="enabled" />
              </SelectTrigger>
              <SelectContent>
                {THINKING_TYPE_VALUES.map((v) => (
                  <SelectItem key={v} value={v}>{v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label>thinking_display</Label>
            <Select
              value={draft.thinking_display || undefined}
              onValueChange={(v) => update('thinking_display', v as ThinkingDisplay)}
              disabled={!draft.thinking_enabled}
            >
              <SelectTrigger>
                <SelectValue placeholder="(default)" />
              </SelectTrigger>
              <SelectContent>
                {THINKING_DISPLAY_VALUES.map((v) => (
                  <SelectItem key={v} value={v}>{v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </fieldset>
    </section>
  );
}

export default ModelConfigEditor;
