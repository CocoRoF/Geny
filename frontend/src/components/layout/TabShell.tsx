'use client';

/**
 * TabShell — universal tab outer chrome.
 *
 * Every tab (excluding Playground / Playground2D / VTuber / Command /
 * Chat which keep their bespoke layouts) wraps its body in TabShell.
 * Provides:
 *   - consistent header (icon + title + subtitle + actions slot)
 *   - shared error banner (with optional dismiss)
 *   - vertical body that fills the parent (`flex-1 min-h-0`)
 *
 * This is the *outermost* layout. Two-pane / drawer layouts go inside
 * the body via TwoPaneBody / DetailDrawer.
 */

import { ReactNode } from 'react';
import { LucideIcon, AlertCircle, X } from 'lucide-react';
import { cn } from './cn';

export interface TabShellProps {
  title: string;
  /** Short one-liner under the title. Optional. */
  subtitle?: ReactNode;
  /** Lucide icon shown left of the title. */
  icon?: LucideIcon;
  /**
   * Right-aligned actions row. Pass any combination of buttons / badges.
   * Convention: primary action first (e.g. "Add"), then refresh,
   * then meta badges (live/gated, capacity, etc.).
   */
  actions?: ReactNode;
  /** When set, an error banner renders above the body. */
  error?: string | null;
  onDismissError?: () => void;
  /** Shown beneath the header, above the error banner. Use for tab-wide
   * filters / category bars that aren't part of the body layout. */
  toolbar?: ReactNode;
  /** Add extra top-padding to the body slot — defaults to 0 because
   * TwoPaneBody manages its own gutters. */
  bodyPadding?: 'none' | 'sm' | 'md' | 'lg';
  children: ReactNode;
}

const PADDING_MAP: Record<NonNullable<TabShellProps['bodyPadding']>, string> = {
  none: '',
  sm: 'p-2',
  md: 'p-3',
  lg: 'p-4',
};

export function TabShell({
  title,
  subtitle,
  icon: Icon,
  actions,
  error,
  onDismissError,
  toolbar,
  bodyPadding = 'none',
  children,
}: TabShellProps) {
  return (
    <div className="flex flex-col h-full min-h-0 bg-[var(--bg-primary)]">
      {/* ── Header ── */}
      <header className="px-4 py-3 border-b border-[var(--border-color)] flex items-start justify-between gap-3 shrink-0">
        <div className="min-w-0">
          <h2 className="text-base font-semibold flex items-center gap-1.5 truncate">
            {Icon && <Icon size={14} className="text-[var(--primary-color)] shrink-0" />}
            <span className="truncate">{title}</span>
          </h2>
          {subtitle && (
            <div className="text-[0.75rem] text-[var(--text-muted)] mt-0.5 truncate">
              {subtitle}
            </div>
          )}
        </div>
        {actions && (
          <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
            {actions}
          </div>
        )}
      </header>

      {/* ── Optional toolbar ── */}
      {toolbar && (
        <div className="px-4 py-2 border-b border-[var(--border-color)] shrink-0">
          {toolbar}
        </div>
      )}

      {/* ── Error banner ── */}
      {error && (
        <div
          className="mx-3 mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2 flex items-start gap-1.5"
          role="alert"
        >
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span className="flex-1 break-words">{error}</span>
          {onDismissError && (
            <button
              type="button"
              onClick={onDismissError}
              className="text-red-600 hover:text-red-800"
              aria-label="Dismiss"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* ── Body ── */}
      <div className={cn('flex-1 min-h-0 overflow-hidden', PADDING_MAP[bodyPadding])}>
        {children}
      </div>
    </div>
  );
}

export default TabShell;
