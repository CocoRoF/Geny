'use client';

/**
 * The persona builder, over the agent you are looking at.
 *
 * Making a persona is a big screen — MBTI, OCEAN, nine expressive sliders,
 * speech, emotion, identity — and it used to live on a page of its own, which
 * meant leaving the agent to build a character for it and coming back to
 * attach it. The builder is unchanged; it just opens here, and the selector
 * behind it refreshes when you close, so a persona you just made is already
 * in the list.
 */

import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

import PersonaPresetsManager from '@/components/persona_presets/PersonaPresetsManager';
import { useI18n } from '@/lib/i18n';

export default function PersonaStudioModal({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();

  // Escape closes it, and the page behind does not scroll while it is open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  if (typeof document === 'undefined') return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 p-3 md:p-6"
      role="dialog"
      aria-modal="true"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="flex flex-col w-full max-w-[1100px] h-[min(88vh,900px)] rounded-[var(--border-radius)] border border-[var(--border-color)] bg-[var(--bg-primary)] shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between shrink-0 py-3 px-4 md:px-5 border-b border-[var(--border-color)]">
          <span className="text-[0.9375rem] font-semibold text-[var(--text-primary)]">
            {t('personaStudio.title') ?? '페르소나'}
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close') ?? '닫기'}
            className="flex items-center justify-center w-7 h-7 rounded-md bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] border-none cursor-pointer transition-colors"
          >
            <X size={16} />
          </button>
        </div>
        {/* The builder scrolls inside the dialog; the dialog itself never does. */}
        <div className="flex-1 min-h-0 overflow-auto">
          <PersonaPresetsManager />
        </div>
      </div>
    </div>,
    document.body,
  );
}
