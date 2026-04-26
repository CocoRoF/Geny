'use client';

/**
 * TabShell — universal tab outer chrome (shadcn-backed).
 *
 * Same prop API as the original layout primitive — all 14 tabs that
 * adopted it get the visual upgrade for free. Internals now use the
 * tokenised palette (hsl(var(--card)) / hsl(var(--border)) / ...) so
 * the surface tracks the active light/dark theme.
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
  toolbar?: ReactNode;
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

      {/* ── Optional toolbar ── */}
      {toolbar && (
        <div className="px-4 py-2 border-b border-[hsl(var(--border))] shrink-0 bg-[hsl(var(--card))]">
          {toolbar}
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
      <div className={cn('flex-1 min-h-0 overflow-hidden', PADDING_MAP[bodyPadding])}>
        {children}
      </div>
    </div>
  );
}

export default TabShell;
