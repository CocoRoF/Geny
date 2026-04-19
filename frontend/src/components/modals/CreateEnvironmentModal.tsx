'use client';

/**
 * CreateEnvironmentModal — v2 EnvironmentManifest 생성 UI.
 *
 * backend (`service/environment/schemas.py`) 가 받는 세 모드와 1:1 매핑:
 *   blank         — 빈 manifest (기본 stages + 빈 tools snapshot)
 *   from_session  — session 의 pipeline/agent 설정을 snapshot
 *   from_preset   — 백엔드 hardcoded preset (minimal / chat / agent / ...)
 *
 * Submit 시 store 의 `createEnvironment` 를 호출. 성공하면 store 가
 * `loadEnvironments()` 로 목록을 재로드하고, caller 쪽에서 modal 을
 * 닫는다.
 */

import { useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { useAppStore } from '@/store/useAppStore';
import { useI18n } from '@/lib/i18n';
import type { CreateEnvironmentMode, CreateEnvironmentPayload } from '@/types/environment';

// backend/service/environment/service.py:_PRESET_FACTORIES 와 동일 순서
const PRESET_OPTIONS: { value: string; labelKey: string }[] = [
  { value: 'minimal', labelKey: 'createEnvironment.presetMinimal' },
  { value: 'chat', labelKey: 'createEnvironment.presetChat' },
  { value: 'agent', labelKey: 'createEnvironment.presetAgent' },
  { value: 'evaluator', labelKey: 'createEnvironment.presetEvaluator' },
  { value: 'geny_vtuber', labelKey: 'createEnvironment.presetVTuber' },
];

const selectArrow: React.CSSProperties = {
  backgroundImage:
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")",
  backgroundRepeat: 'no-repeat',
  backgroundPosition: 'right 12px center',
};

interface Props {
  onClose: () => void;
  onCreated?: (envId: string) => void;
}

export default function CreateEnvironmentModal({ onClose, onCreated }: Props) {
  const { createEnvironment } = useEnvironmentStore();
  const sessions = useAppStore(s => s.sessions);
  const { t } = useI18n();

  const [mode, setMode] = useState<CreateEnvironmentMode>('blank');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [presetName, setPresetName] = useState('minimal');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const canSubmit =
    name.trim().length > 0 &&
    (mode !== 'from_session' || !!sessionId) &&
    (mode !== 'from_preset' || !!presetName) &&
    !submitting;

  const handleSubmit = async () => {
    setError('');
    setSubmitting(true);
    try {
      const payload: CreateEnvironmentPayload = {
        mode,
        name: name.trim(),
      };
      if (description.trim()) payload.description = description.trim();
      const parsedTags = tags
        .split(',')
        .map(s => s.trim())
        .filter(Boolean);
      if (parsedTags.length > 0) payload.tags = parsedTags;
      if (mode === 'from_session') payload.session_id = sessionId;
      if (mode === 'from_preset') payload.preset_name = presetName;

      const result = await createEnvironment(payload);
      onCreated?.(result.id);
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('createEnvironment.failed'));
    } finally {
      setSubmitting(false);
    }
  };

  if (typeof document === 'undefined') return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[480px] mx-4 max-h-[85vh] flex flex-col shadow-[var(--shadow-lg)]"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex justify-between items-center py-3 md:py-4 px-4 md:px-6 border-b border-[var(--border-color)]">
          <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">
            {t('createEnvironment.title')}
          </h3>
          <button
            className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 md:py-5 flex flex-col gap-4">
          {error && (
            <div className="text-[0.8125rem] text-[var(--danger-color)] bg-[rgba(239,68,68,0.1)] p-2.5 rounded-[6px]">
              {error}
            </div>
          )}

          {/* Mode selector — radio cards */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">
              {t('createEnvironment.mode')}
            </label>
            <div className="grid grid-cols-3 gap-2">
              {(['blank', 'from_session', 'from_preset'] as CreateEnvironmentMode[]).map(m => (
                <button
                  key={m}
                  type="button"
                  className={
                    'py-2 px-2.5 rounded-md border text-[0.75rem] font-medium cursor-pointer transition-all ' +
                    (mode === m
                      ? 'border-[var(--primary-color)] bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]'
                      : 'border-[var(--border-color)] bg-[var(--bg-primary)] text-[var(--text-secondary)] hover:border-[var(--text-muted)]')
                  }
                  onClick={() => setMode(m)}
                >
                  {t(`createEnvironment.mode_${m}`)}
                </button>
              ))}
            </div>
            <small className="text-[0.6875rem] text-[var(--text-muted)]">
              {t(`createEnvironment.mode_${mode}_hint`)}
            </small>
          </div>

          {/* Name */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">
              {t('createEnvironment.name')}
            </label>
            <input
              className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)]"
              placeholder={t('createEnvironment.namePlaceholder')}
              value={name}
              onChange={e => setName(e.target.value)}
            />
          </div>

          {/* Description */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">
              {t('createEnvironment.description')}
            </label>
            <textarea
              className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] resize-y"
              rows={3}
              placeholder={t('createEnvironment.descriptionPlaceholder')}
              value={description}
              onChange={e => setDescription(e.target.value)}
            />
          </div>

          {/* Tags */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">
              {t('createEnvironment.tags')}
            </label>
            <input
              className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)]"
              placeholder={t('createEnvironment.tagsPlaceholder')}
              value={tags}
              onChange={e => setTags(e.target.value)}
            />
          </div>

          {/* Mode-specific */}
          {mode === 'from_session' && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">
                {t('createEnvironment.sourceSession')}
              </label>
              <select
                className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer focus:outline-none focus:border-[var(--primary-color)] pr-8"
                style={selectArrow}
                value={sessionId}
                onChange={e => setSessionId(e.target.value)}
              >
                <option value="">{t('createEnvironment.selectSession')}</option>
                {sessions.map(s => (
                  <option key={s.session_id} value={s.session_id}>
                    {s.session_name || s.session_id.slice(0, 10)}
                  </option>
                ))}
              </select>
              {sessions.length === 0 && (
                <small className="text-[0.6875rem] text-[var(--text-muted)]">
                  {t('createEnvironment.noSessions')}
                </small>
              )}
            </div>
          )}

          {mode === 'from_preset' && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">
                {t('createEnvironment.preset')}
              </label>
              <select
                className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer focus:outline-none focus:border-[var(--primary-color)] pr-8"
                style={selectArrow}
                value={presetName}
                onChange={e => setPresetName(e.target.value)}
              >
                {PRESET_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>
                    {t(opt.labelKey)}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end items-center gap-3 py-3 md:py-4 px-4 md:px-6 border-t border-[var(--border-color)]">
          <button
            className="py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer border border-[var(--border-color)]"
            onClick={onClose}
          >
            {t('common.cancel')}
          </button>
          <button
            className="py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer border-none disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleSubmit}
            disabled={!canSubmit}
          >
            {submitting ? t('createEnvironment.creating') : t('createEnvironment.create')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
