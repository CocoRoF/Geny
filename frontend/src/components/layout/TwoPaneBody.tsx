'use client';

import { ReactNode } from 'react';
import { cn } from './cn';

export interface TwoPaneBodyProps {
  sidebar: ReactNode;
  sidebarTitle?: ReactNode;
  sidebarWidth?: 'narrow' | 'medium' | 'wide';
  children: ReactNode;
  mainPadding?: 'none' | 'sm' | 'md' | 'lg';
}

const SIDEBAR_WIDTH: Record<NonNullable<TwoPaneBodyProps['sidebarWidth']>, string> = {
  narrow: 'w-44',
  medium: 'w-56',
  wide: 'w-64',
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
          'shrink-0 border-r border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-y-auto p-2',
        )}
      >
        {sidebarTitle && (
          <div className="text-[0.625rem] uppercase tracking-wider text-[hsl(var(--muted-foreground))] font-semibold px-2 py-1">
            {sidebarTitle}
          </div>
        )}
        {sidebar}
      </aside>
      <main className={cn('flex-1 min-w-0 overflow-y-auto', MAIN_PADDING[mainPadding])}>
        {children}
      </main>
    </div>
  );
}

export default TwoPaneBody;
