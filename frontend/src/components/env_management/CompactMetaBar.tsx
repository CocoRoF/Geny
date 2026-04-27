'use client';

/**
 * CompactMetaBar — single-row environment metadata + actions bar.
 *
 * Replaces the bulky multi-row TopBar form (cycle 20260427_2 PR-2).
 * Sits directly below the page header so the canvas can take the rest
 * of the viewport.
 *
 * Layout (left → right):
 *   [name input] [tags + popover for desc] | [warnings] | [⚙ globals] [Save]
 *
 * Description and full validation list move into popovers (click the
 * ⓘ button or "X warnings" chip) so the bar stays at ~52px tall
 * regardless of content.
 */

import { useState, useRef, useEffect } from 'react';
import {
  AlertTriangle,
  Info,
  Plus,
  Save,
  Settings2,
  Trash2,
  X,
} from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ActionButton } from '@/components/layout';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';

export interface CompactMetaBarProps {
  onSaved: (newEnvId: string) => void;
  onOpenGlobals: () => void;
}

export default function CompactMetaBar({
  onSaved,
  onOpenGlobals,
}: CompactMetaBarProps) {
  const { t } = useI18n();
  const draft = useEnvironmentDraftStore((s) => s.draft);
  const saving = useEnvironmentDraftStore((s) => s.saving);
  const errorBanner = useEnvironmentDraftStore((s) => s.error);
  const validationErrors = useEnvironmentDraftStore((s) => s.validationErrors);
  const resetDraft = useEnvironmentDraftStore((s) => s.resetDraft);
  const patchMetadata = useEnvironmentDraftStore((s) => s.patchMetadata);
  const saveDraft = useEnvironmentDraftStore((s) => s.saveDraft);
  const isDirty = useEnvironmentDraftStore((s) => s.isDirty);
  const stageDirty = useEnvironmentDraftStore((s) => s.stageDirty);
  const clearError = useEnvironmentDraftStore((s) => s.clearError);

  const [descOpen, setDescOpen] = useState(false);
  const [validOpen, setValidOpen] = useState(false);
  const [tagInput, setTagInput] = useState('');
  const descRef = useRef<HTMLDivElement | null>(null);
  const validRef = useRef<HTMLDivElement | null>(null);

  // Close popovers on outside click
  useEffect(() => {
    if (!descOpen && !validOpen) return;
    const handler = (e: MouseEvent) => {
      if (descOpen && descRef.current && !descRef.current.contains(e.target as Node)) {
        setDescOpen(false);
      }
      if (validOpen && validRef.current && !validRef.current.contains(e.target as Node)) {
        setValidOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [descOpen, validOpen]);

  if (!draft) {
    // No draft yet — still render the bar with disabled actions so the
    // chrome stays consistent across overview / stage / empty views.
    return (
      <div className="flex items-center gap-3 h-[52px] px-4 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0">
        <span className="text-[0.8125rem] text-[hsl(var(--muted-foreground))] italic">
          {t('envManagement.compactBar.noDraft')}
        </span>
        <div className="flex-1" />
        {errorBanner && (
          <button
            type="button"
            onClick={clearError}
            className="inline-flex items-center gap-1 text-[0.7rem] text-red-600 dark:text-red-400 hover:underline"
          >
            <AlertTriangle className="w-3 h-3" />
            {errorBanner}
            <X className="w-3 h-3 ml-1" />
          </button>
        )}
      </div>
    );
  }

  const nameValid = draft.metadata.name.trim().length > 0;
  const errorCount = validationErrors.filter((e) => e.severity === 'error').length;
  const warningCount = validationErrors.filter((e) => e.severity !== 'error').length;
  const blockedByValidation = errorCount > 0;
  const saveDisabled = !nameValid || blockedByValidation || saving;

  const handleSave = async () => {
    try {
      const res = await saveDraft({
        name: draft.metadata.name,
        description: draft.metadata.description,
        tags: draft.metadata.tags,
      });
      onSaved(res.id);
    } catch {
      /* error surfaces via store.error */
    }
  };

  const handleDiscard = () => {
    if (isDirty() && !confirm(t('envManagement.confirmDiscard'))) return;
    resetDraft();
  };

  const addTag = () => {
    const tag = tagInput.trim();
    if (!tag) return;
    if ((draft.metadata.tags || []).includes(tag)) {
      setTagInput('');
      return;
    }
    patchMetadata({ tags: [...(draft.metadata.tags || []), tag] });
    setTagInput('');
  };

  const removeTag = (tag: string) =>
    patchMetadata({
      tags: (draft.metadata.tags || []).filter((t) => t !== tag),
    });

  return (
    <div className="flex items-center gap-3 h-[52px] px-4 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0">
      {/* ── Name input ── */}
      <div className="flex items-center gap-1.5">
        <span className="text-[0.625rem] uppercase tracking-wider font-semibold text-[hsl(var(--muted-foreground))]">
          {t('envManagement.nameLabel')}
        </span>
        <Input
          value={draft.metadata.name}
          onChange={(e) => patchMetadata({ name: e.target.value })}
          placeholder={t('envManagement.namePlaceholder')}
          className={`h-7 w-[180px] text-[0.8125rem] font-medium ${
            !nameValid ? 'border-red-500/50' : ''
          }`}
        />
      </div>

      {/* ── Description popover trigger ── */}
      <div className="relative" ref={descRef}>
        <button
          type="button"
          onClick={() => setDescOpen((v) => !v)}
          className={`inline-flex items-center justify-center w-7 h-7 rounded-md border transition-colors ${
            draft.metadata.description
              ? 'border-[hsl(var(--primary)/0.4)] bg-[hsl(var(--primary)/0.08)] text-[hsl(var(--primary))]'
              : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]'
          }`}
          title={t('envManagement.compactBar.descriptionTip')}
        >
          <Info className="w-3.5 h-3.5" />
        </button>
        {descOpen && (
          <div className="absolute left-0 top-full mt-1 z-30 w-[360px] p-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-lg">
            <label className="text-[0.6875rem] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
              {t('envManagement.descriptionLabel')}
            </label>
            <Textarea
              value={draft.metadata.description}
              onChange={(e) => patchMetadata({ description: e.target.value })}
              placeholder={t('envManagement.descriptionPlaceholder')}
              rows={3}
              className="mt-1 text-[0.8125rem] resize-none"
              autoFocus
            />
          </div>
        )}
      </div>

      {/* ── Tags inline ── */}
      <div className="flex items-center gap-1 min-w-0 flex-1 overflow-x-auto scrollbar-hide">
        {(draft.metadata.tags || []).slice(0, 6).map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[hsl(var(--accent))] text-[0.6875rem] text-[hsl(var(--foreground))] shrink-0"
          >
            {tag}
            <button
              type="button"
              onClick={() => removeTag(tag)}
              className="text-[hsl(var(--muted-foreground))] hover:text-red-500 leading-none"
              aria-label="remove tag"
            >
              ×
            </button>
          </span>
        ))}
        {(draft.metadata.tags || []).length > 6 && (
          <span className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] shrink-0">
            +{(draft.metadata.tags || []).length - 6}
          </span>
        )}
        <div className="inline-flex items-center gap-0.5 shrink-0">
          <Input
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addTag();
              }
            }}
            placeholder={t('envManagement.addTag')}
            className="h-6 w-[100px] text-[0.6875rem]"
          />
          {tagInput.trim() && (
            <button
              type="button"
              onClick={addTag}
              className="inline-flex items-center justify-center w-6 h-6 rounded text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--primary))] hover:bg-[hsl(var(--accent))]"
              aria-label="add tag"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* ── Status pills ── */}
      <div className="flex items-center gap-2 shrink-0">
        {stageDirty.size > 0 && (
          <span className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] tabular-nums">
            {t('envManagement.editedStages', { n: String(stageDirty.size) })}
          </span>
        )}
        {(errorCount > 0 || warningCount > 0) && (
          <div className="relative" ref={validRef}>
            <button
              type="button"
              onClick={() => setValidOpen((v) => !v)}
              className={`inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[0.6875rem] font-medium transition-colors ${
                errorCount > 0
                  ? 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300'
                  : 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300'
              }`}
            >
              <AlertTriangle className="w-3 h-3" />
              {errorCount > 0
                ? t('envManagement.validationErrorsRed', { n: String(errorCount) })
                : t('envManagement.validationWarnings', { n: String(warningCount) })}
            </button>
            {validOpen && (
              <div className="absolute right-0 top-full mt-1 z-30 w-[420px] max-h-[380px] overflow-y-auto p-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] shadow-lg">
                <div className="text-[0.6875rem] uppercase tracking-wider font-semibold text-[hsl(var(--muted-foreground))] mb-2">
                  {t('envManagement.viewValidationDetails')}
                </div>
                <ul className="flex flex-col gap-1">
                  {validationErrors.map((v, i) => (
                    <li
                      key={`${v.path}_${i}`}
                      className={`flex items-start gap-1.5 px-2 py-1.5 rounded border ${
                        v.severity === 'error'
                          ? 'bg-red-500/5 border-red-500/30 text-red-700 dark:text-red-300'
                          : 'bg-amber-500/5 border-amber-500/30 text-amber-700 dark:text-amber-300'
                      }`}
                    >
                      <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
                      <div className="flex-1 min-w-0 text-[0.7rem]">
                        <code className="text-[0.625rem] font-mono opacity-70">
                          {v.path}
                        </code>
                        <div className="mt-0.5">{v.message}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Globals + Discard + Save ── */}
      <div className="flex items-center gap-1.5 shrink-0">
        <button
          type="button"
          onClick={onOpenGlobals}
          className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[0.7rem] font-medium text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
          title={t('envManagement.compactBar.globalsTip')}
        >
          <Settings2 className="w-3.5 h-3.5" />
          {t('envManagement.compactBar.globalsLabel')}
        </button>
        <ActionButton icon={Trash2} onClick={handleDiscard} disabled={saving}>
          {t('envManagement.discard')}
        </ActionButton>
        <ActionButton
          variant="primary"
          icon={Save}
          onClick={handleSave}
          disabled={saveDisabled}
          spinIcon={saving}
        >
          {saving ? t('envManagement.saving') : t('envManagement.save')}
        </ActionButton>
      </div>
    </div>
  );
}
