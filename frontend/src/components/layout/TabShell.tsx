'use client';

/**
 * TabShell — universal tab outer chrome (shadcn-backed).
 *
 * Layered chrome (top → bottom):
 *   header   — title / subtitle / icon / actions
 *   toolbar  — single ReactNode or array (each rendered as a row)
 *   bulkBar  — contextual bar (shown when bulk selection active)
 *   loading  — thin progress strip
 *   error    — dismissable banner
 *   body     — children (optional auto-scroll when bodyScroll='auto')
 *   footer   — sticky status row (counts, pagination)
 */

import { ReactNode } from 'react';
import { LucideIcon, AlertCircle, X } from 'lucide-react';
import { cn } from './cn';

export interface TabShellProps {
  title: string;
  subtitle?: ReactNode;
  icon?: LucideIcon;
  actions?: ReactNode;
  error?: string | null;
  onDismissError?: () => void;
  toolbar?: ReactNode | ReactNode[];
  bulkBar?: ReactNode;
  footer?: ReactNode;
  loading?: boolean;
  bodyPadding?: 'none' | 'sm' | 'md' | 'lg';
  bodyScroll?: 'auto' | 'none';
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
  bulkBar,
  footer,
  loading = false,
  bodyPadding = 'none',
  bodyScroll = 'none',
  children,
}: TabShellProps) {
  const toolbarRows = Array.isArray(toolbar)
    ? toolbar.filter(Boolean)
    : toolbar
      ? [toolbar]
      : [];

  return (
    <div className="flex flex-col h-full min-h-0 bg-[hsl(var(--background))] text-[hsl(var(--foreground))]">
      {/* ── Header ── */}
      <header className="px-4 py-3 border-b border-[hsl(var(--border))] flex items-start justify-between gap-3 shrink-0 bg-[hsl(var(--card))]">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold tracking-tight flex items-center gap-1.5 truncate">
            {Icon && (
              <Icon
                size={14}
                strokeWidth={2.25}
                className="text-[hsl(var(--primary))] shrink-0"
              />
            )}
            <span className="truncate">{title}</span>
          </h2>
          {subtitle && (
            <div className="text-[0.7rem] text-[hsl(var(--muted-foreground))] mt-1 truncate">
              {subtitle}
            </div>
          )}
        </div>
        {actions && (
          <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
            {actions}
          </div>
        )}
      </header>

      {/* ── Toolbar rows ── */}
      {toolbarRows.map((row, idx) => (
        <div
          key={idx}
          className="px-4 py-2 border-b border-[hsl(var(--border))] shrink-0 bg-[hsl(var(--card))]"
        >
          {row}
        </div>
      ))}

      {/* ── Bulk action bar (contextual) ── */}
      {bulkBar && (
        <div className="px-4 py-1.5 border-b border-[hsl(var(--border))] shrink-0 bg-[hsl(var(--accent))]">
          {bulkBar}
        </div>
      )}

      {/* ── Loading strip ── */}
      {loading && (
        <div className="h-0.5 shrink-0 overflow-hidden bg-[hsl(var(--accent))]">
          <div className="h-full w-1/3 bg-[hsl(var(--primary))] animate-loading-strip" />
        </div>
      )}

      {/* ── Error banner ── */}
      {error && (
        <div
          className="mx-3 mt-3 text-xs text-red-700 dark:text-red-300 bg-red-500/10 border border-red-500/30 rounded-md px-3 py-2 flex items-start gap-2"
          role="alert"
        >
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span className="flex-1 break-words">{error}</span>
          {onDismissError && (
            <button
              type="button"
              onClick={onDismissError}
              className="text-red-700/70 dark:text-red-300/70 hover:text-red-700 dark:hover:text-red-300 transition-colors"
              aria-label="Dismiss"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      )}

      {/* ── Body ── */}
      <div
        className={cn(
          'flex-1 min-h-0',
          bodyScroll === 'auto' ? 'overflow-y-auto' : 'overflow-hidden',
          PADDING_MAP[bodyPadding],
        )}
      >
        {children}
      </div>

      {/* ── Footer (sticky status bar) ── */}
      {footer && (
        <div className="px-4 py-1.5 border-t border-[hsl(var(--border))] shrink-0 bg-[hsl(var(--card))] text-[0.7rem] text-[hsl(var(--muted-foreground))]">
          {footer}
        </div>
      )}
    </div>
  );
}

export default TabShell;
