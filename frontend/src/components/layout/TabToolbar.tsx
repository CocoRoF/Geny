'use client';

/**
 * TabToolbar — standard slot layout for a search/filter/sort/extra row.
 *
 * Slots align like:  [search.....] [filters........] [extra] [sort]
 *
 * Each slot is optional; the toolbar collapses gracefully on narrow
 * widths via flex-wrap. Pass it to <TabShell toolbar={...}>.
 */

import { ReactNode } from 'react';
import { cn } from './cn';

export interface TabToolbarProps {
  search?: ReactNode;
  filters?: ReactNode;
  extra?: ReactNode;
  sort?: ReactNode;
  className?: string;
}

export function TabToolbar({
  search,
  filters,
  extra,
  sort,
  className,
}: TabToolbarProps) {
  return (
    <div
      className={cn(
        'flex items-center gap-3 flex-wrap',
        className,
      )}
    >
      {search && (
        <div className="min-w-[200px] flex-shrink-0 w-full sm:w-auto sm:max-w-xs">
          {search}
        </div>
      )}
      {filters && <div className="flex-1 min-w-0">{filters}</div>}
      {extra && <div className="flex items-center gap-1.5">{extra}</div>}
      {sort && <div className="ml-auto flex-shrink-0">{sort}</div>}
    </div>
  );
}

export default TabToolbar;
