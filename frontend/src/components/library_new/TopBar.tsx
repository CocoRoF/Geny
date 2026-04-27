'use client';

/**
 * TopBar — header for the Library (NEW) tab.
 *
 * Hosts the env metadata form (name / description / tags) plus the Save
 * and Discard actions. Save is enabled only when:
 *   - draft exists
 *   - name is non-empty
 *   - no blocking validation errors
 *   - not currently saving
 *
 * The Save flow lives in useEnvironmentDraftStore.saveDraft(); this
 * component only owns presentation + the metadata form fields it shows
 * inline (which double-write to draft.metadata so the saved env keeps
 * what the user typed).
 */

import { useState } from 'react';
import { Save, Trash2, AlertTriangle } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ActionButton } from '@/components/layout';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import StartFromPicker from './StartFromPicker';

interface TopBarProps {
  onSaved: (newEnvId: string) => void;
}

export default function TopBar({ onSaved }: TopBarProps) {
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

  const [tagInput, setTagInput] = useState('');

  const handleDiscard = () => {
    if (isDirty() && !confirm(t('libraryNewTab.confirmDiscard'))) return;
    resetDraft();
  };

  const handleSave = async () => {
    if (!draft) return;
    try {
      const res = await saveDraft({
        name: draft.metadata.name,
        description: draft.metadata.description,
        tags: draft.metadata.tags,
      });
      onSaved(res.id);
    } catch {
      /* error surfaces via store.error banner */
    }
  };

  const addTag = () => {
    const tag = tagInput.trim();
    if (!tag || !draft) return;
    if ((draft.metadata.tags || []).includes(tag)) {
      setTagInput('');
      return;
    }
    patchMetadata({ tags: [...(draft.metadata.tags || []), tag] });
    setTagInput('');
  };

  const removeTag = (tag: string) => {
    if (!draft) return;
    patchMetadata({
      tags: (draft.metadata.tags || []).filter((t) => t !== tag),
    });
  };

  // ── Empty state — no draft yet
  if (!draft) {
    return (
      <div className="flex flex-col gap-4 px-5 py-4 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div>
          <h2 className="text-base font-semibold text-[hsl(var(--foreground))]">
            {t('libraryNewTab.welcomeTitle')}
          </h2>
          <p className="text-[0.8125rem] text-[hsl(var(--muted-foreground))] mt-0.5 max-w-[720px]">
            {t('libraryNewTab.welcomeDescription')}
          </p>
        </div>
        <StartFromPicker />
        {errorBanner && (
          <div className="px-3 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-[0.75rem] text-red-700 dark:text-red-300 flex items-start gap-2">
            <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <span className="flex-1">{errorBanner}</span>
          </div>
        )}
      </div>
    );
  }

  // ── Draft active — show metadata form + Save/Discard
  const nameValid = draft.metadata.name.trim().length > 0;
  const errorCount = validationErrors.filter((e) => e.severity === 'error').length;
  const warningCount = validationErrors.filter((e) => e.severity !== 'error').length;
  const blockedByValidation = errorCount > 0;
  const saveDisabled = !nameValid || blockedByValidation || saving;

  return (
    <div className="flex flex-col gap-3 px-5 py-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="flex items-start gap-3 flex-wrap">
        {/* ── Name ── */}
        <div className="flex flex-col gap-1 min-w-[260px] flex-1">
          <label className="text-[0.6875rem] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
            {t('libraryNewTab.nameLabel')}
            <span className="ml-1 text-red-500">*</span>
          </label>
          <Input
            value={draft.metadata.name}
            onChange={(e) => patchMetadata({ name: e.target.value })}
            placeholder={t('libraryNewTab.namePlaceholder')}
            className="h-8 text-[0.875rem] font-medium"
          />
        </div>

        {/* ── Description ── */}
        <div className="flex flex-col gap-1 min-w-[260px] flex-[2]">
          <label className="text-[0.6875rem] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
            {t('libraryNewTab.descriptionLabel')}
          </label>
          <Textarea
            value={draft.metadata.description}
            onChange={(e) => patchMetadata({ description: e.target.value })}
            placeholder={t('libraryNewTab.descriptionPlaceholder')}
            rows={1}
            className="text-[0.8125rem] resize-none min-h-[32px] py-1.5"
          />
        </div>

        {/* ── Save / Discard ── */}
        <div className="flex items-end gap-1.5 pb-0.5">
          <ActionButton
            icon={Trash2}
            onClick={handleDiscard}
            disabled={saving}
          >
            {t('libraryNewTab.discard')}
          </ActionButton>
          <ActionButton
            variant="primary"
            icon={Save}
            onClick={handleSave}
            disabled={saveDisabled}
            spinIcon={saving}
          >
            {saving ? t('libraryNewTab.saving') : t('libraryNewTab.save')}
          </ActionButton>
        </div>
      </div>

      {/* ── Tags row ── */}
      <div className="flex items-center gap-2 flex-wrap">
        <label className="text-[0.6875rem] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
          {t('libraryNewTab.tagsLabel')}
        </label>
        <div className="flex items-center gap-1 flex-wrap">
          {(draft.metadata.tags || []).map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[hsl(var(--accent))] text-[0.7rem] text-[hsl(var(--foreground))]"
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
        </div>
        <div className="flex items-center gap-1">
          <Input
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addTag();
              }
            }}
            placeholder={t('libraryNewTab.addTag')}
            className="h-7 w-[140px] text-[0.75rem]"
          />
          <ActionButton onClick={addTag} disabled={!tagInput.trim()}>
            {t('common.add')}
          </ActionButton>
        </div>
      </div>

      {/* ── Status row ── */}
      <div className="flex items-center gap-3 text-[0.7rem] text-[hsl(var(--muted-foreground))]">
        <span>
          {t('libraryNewTab.editedStages', { n: String(stageDirty.size) })}
        </span>
        {errorCount > 0 && (
          <span className="inline-flex items-center gap-1 text-red-600 dark:text-red-400">
            <AlertTriangle className="w-3 h-3" />
            {t('libraryNewTab.validationErrorsRed', { n: String(errorCount) })}
          </span>
        )}
        {warningCount > 0 && (
          <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400">
            <AlertTriangle className="w-3 h-3" />
            {t('libraryNewTab.validationWarnings', { n: String(warningCount) })}
          </span>
        )}
      </div>

      {/* ── Validation detail (warnings + errors) ── */}
      {validationErrors.length > 0 && (
        <details className="text-[0.7rem]">
          <summary className="cursor-pointer text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]">
            {t('libraryNewTab.viewValidationDetails')}
          </summary>
          <ul className="mt-1.5 flex flex-col gap-1">
            {validationErrors.map((v, i) => (
              <li
                key={`${v.path}_${i}`}
                className={`flex items-start gap-1.5 px-2 py-1 rounded border ${
                  v.severity === 'error'
                    ? 'bg-red-500/5 border-red-500/30 text-red-700 dark:text-red-300'
                    : 'bg-amber-500/5 border-amber-500/30 text-amber-700 dark:text-amber-300'
                }`}
              >
                <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <code className="text-[0.625rem] font-mono opacity-70">
                    {v.path}
                  </code>
                  <div className="mt-0.5">{v.message}</div>
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}

      {errorBanner && (
        <div className="px-3 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-[0.75rem] text-red-700 dark:text-red-300 flex items-start gap-2">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span className="flex-1">{errorBanner}</span>
        </div>
      )}
    </div>
  );
}
