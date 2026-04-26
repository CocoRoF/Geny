'use client';

/**
 * EditorModal — shared Add/Edit modal scaffold.
 *
 * Centered overlay with consistent header/body/footer layout. Closes
 * on outer click + ESC unless `saving` is true. The body can be a
 * form, JSON textarea, or anything else — caller owns the content.
 *
 * Convention: use this for tabs that have a "create new entity" + "edit
 * existing entity" path. Confirm dialogs (delete) stay on
 * window.confirm — that's deliberately ugly so destructive actions
 * surface as friction rather than nice modals.
 */

import { ReactNode, useEffect } from 'react';
import { X } from 'lucide-react';
import { cn } from './cn';

export interface EditorModalProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  /** Disables outer-click-to-close + ESC + the close button. */
  saving?: boolean;
  /** Footer actions; usually Cancel + Save. */
  footer?: ReactNode;
  /** Width preset. */
  width?: 'sm' | 'md' | 'lg' | 'xl';
  /** Optional inline error banner inside the modal body. */
  error?: string | null;
  children: ReactNode;
}

const WIDTH: Record<NonNullable<EditorModalProps['width']>, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-2xl',
};

export function EditorModal({
  open,
  onClose,
  title,
  saving = false,
  footer,
  width = 'md',
  error,
  children,
}: EditorModalProps) {
  // ESC closes when not saving.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving) onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, saving, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
      onClick={() => !saving && onClose()}
    >
      <div
        className={cn(
          WIDTH[width],
          'w-full max-h-[85vh] bg-[var(--bg-primary)] rounded-lg border border-[var(--border-color)] flex flex-col overflow-hidden',
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between gap-2 px-4 py-2 border-b border-[var(--border-color)] shrink-0">
          <h3 className="text-sm font-semibold flex-1 truncate">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)] disabled:opacity-30"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </header>
        <div className="overflow-y-auto p-4 flex-1 min-h-0">
          {error && (
            <div
              className="mb-2 text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2"
              role="alert"
            >
              {error}
            </div>
          )}
          {children}
        </div>
        {footer && (
          <footer className="px-4 py-2 border-t border-[var(--border-color)] flex items-center justify-end gap-2 shrink-0">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}

export default EditorModal;
