'use client';

/**
 * StageInfoModal — the dedicated detail/help modal for a single
 * pipeline stage.
 *
 * Shell + composition; the renderer is StageInfoContent. The shell
 * is responsible for:
 *   - Dialog primitive integration (Esc / overlay / X button)
 *   - Stage header (number circle, name, category badge, code name)
 *   - Scrollable body region
 *   - Footer with close button
 */

import { X } from 'lucide-react';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { useI18n } from '@/lib/i18n';
import { useTheme } from '@/lib/theme';
import { getStageMetaByOrder } from '@/components/session-env/stageMetadata';
import StageInfoContent from './StageInfoContent';

export interface StageInfoModalProps {
  open: boolean;
  onClose: () => void;
  /** The stage order (1..21) to display. */
  order: number | null;
}

const HEADER_PALETTE = {
  light: {
    bg: 'rgb(220 252 231)',
    fg: 'rgb(4 120 87)',
    border: 'rgb(16 185 129)',
  },
  dark: {
    bg: 'rgb(6 78 59 / 0.45)',
    fg: 'rgb(110 231 183)',
    border: 'rgb(52 211 153)',
  },
} as const;

export default function StageInfoModal({
  open,
  onClose,
  order,
}: StageInfoModalProps) {
  const { t } = useI18n();
  const locale = useI18n((s) => s.locale);
  const { theme } = useTheme();
  const palette = HEADER_PALETTE[theme === 'dark' ? 'dark' : 'light'];

  if (order == null) return null;
  const meta = getStageMetaByOrder(order, locale);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent className="max-w-3xl p-0 max-h-[90vh] flex flex-col gap-0">
        {/* ── Header ── */}
        <header className="flex items-start gap-3 px-5 pt-5 pb-4 border-b border-[hsl(var(--border))] shrink-0">
          <span
            className="inline-flex items-center justify-center w-12 h-12 rounded-full text-[1rem] font-bold tabular-nums shrink-0"
            style={{
              background: palette.bg,
              color: palette.fg,
              border: `2px solid ${palette.border}`,
            }}
          >
            {order}
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-[1.1875rem] font-semibold text-[hsl(var(--foreground))]">
                {meta?.displayName ?? `Stage ${order}`}
              </h2>
              {meta?.categoryLabel && (
                <span
                  className="text-[0.625rem] uppercase tracking-wider px-1.5 py-0.5 rounded font-medium"
                  style={{
                    background: palette.bg,
                    color: palette.fg,
                  }}
                >
                  {meta.categoryLabel}
                </span>
              )}
              {meta?.name && (
                <code className="text-[0.6875rem] font-mono text-[hsl(var(--muted-foreground))]">
                  {meta.name}
                </code>
              )}
            </div>
            {meta?.description && (
              <p className="text-[0.8125rem] text-[hsl(var(--muted-foreground))] mt-1 leading-relaxed">
                {meta.description}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center justify-center w-8 h-8 rounded-md text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors shrink-0 -mt-1 -mr-1"
            aria-label={t('common.close')}
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        {/* ── Body ── */}
        <div className="flex-1 min-h-0 overflow-y-auto">
          <StageInfoContent order={order} />
        </div>

        {/* ── Footer ── */}
        <footer className="flex items-center justify-end gap-2 px-5 py-3 border-t border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[0.75rem] font-medium text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
          >
            {t('common.close')}
          </button>
        </footer>
      </DialogContent>
    </Dialog>
  );
}
