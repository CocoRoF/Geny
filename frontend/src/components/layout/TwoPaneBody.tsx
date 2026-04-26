'use client';

/**
 * TwoPaneBody — sidebar (list/categories) + main content.
 *
 * Used by tabs that need a vertical list selector on the left and a
 * detail / editor on the right. Sits inside TabShell's body slot.
 *
 * Sidebar width is fixed (default 224px / 14rem) — calling it
 * "responsive" usually means the operator has to scroll horizontally
 * on mobile, so we just hide it on small screens and the parent tab
 * decides whether to fall back to a flat list. Most operator tools
 * are dev-only anyway.
 */

import { ReactNode } from 'react';
import { cn } from './cn';

export interface TwoPaneBodyProps {
  sidebar: ReactNode;
  /** When set, sidebar header label rendered above the sidebar list. */
  sidebarTitle?: ReactNode;
  /** Sidebar width preset. */
  sidebarWidth?: 'narrow' | 'medium' | 'wide';
  children: ReactNode;
  /** Padding inside the right (main) pane. Default 'md'. */
  mainPadding?: 'none' | 'sm' | 'md' | 'lg';
}

const SIDEBAR_WIDTH: Record<NonNullable<TwoPaneBodyProps['sidebarWidth']>, string> = {
  narrow: 'w-44',     // 11rem — sidebar of mostly-short labels
  medium: 'w-56',     // 14rem — default
  wide: 'w-64',       // 16rem — labels with badges/descriptions
};

const MAIN_PADDING: Record<NonNullable<TwoPaneBodyProps['mainPadding']>, string> = {
  none: '',
  sm: 'p-2',
  md: 'p-3',
  lg: 'p-4',
};

export function TwoPaneBody({
  sidebar,
  sidebarTitle,
  sidebarWidth = 'medium',
  children,
  mainPadding = 'md',
}: TwoPaneBodyProps) {
  return (
    <div className="flex h-full min-h-0">
      <aside
        className={cn(
          SIDEBAR_WIDTH[sidebarWidth],
          'shrink-0 border-r border-[var(--border-color)] overflow-y-auto p-2',
        )}
      >
        {sidebarTitle && (
          <div className="text-[0.625rem] uppercase tracking-wider text-[var(--text-muted)] font-semibold px-2 py-1">
            {sidebarTitle}
          </div>
        )}
        {sidebar}
      </aside>
      <main
        className={cn(
          'flex-1 min-w-0 overflow-y-auto',
          MAIN_PADDING[mainPadding],
        )}
      >
        {children}
      </main>
    </div>
  );
}

export default TwoPaneBody;
