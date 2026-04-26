'use client';

/**
 * SubTabNav — horizontal pill nav (shadcn-backed).
 *
 * Same prop API. Internally uses the same active-state visual as
 * shadcn's TabsTrigger (underline + accent bg) so the global tab
 * strip and the sub-tab strip feel like the same family.
 */

import { ReactNode } from 'react';
import { LucideIcon } from 'lucide-react';
import { cn } from './cn';

export interface SubTabDef {
  id: string;
  label: ReactNode;
  icon?: LucideIcon;
  count?: number;
}

export interface SubTabNavProps {
  tabs: SubTabDef[];
  active: string;
  onSelect: (id: string) => void;
}

export function SubTabNav({ tabs, active, onSelect }: SubTabNavProps) {
  return (
    <nav
      className="flex items-center gap-0.5 px-2 md:px-3 h-9 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0 overflow-x-auto scrollbar-hide"
      role="tablist"
    >
      {tabs.map(({ id, label, icon: Icon, count }) => {
        const isActive = active === id;
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onSelect(id)}
            className={cn(
              'relative inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium whitespace-nowrap transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]',
              isActive
                ? 'text-[hsl(var(--foreground))] bg-[hsl(var(--accent))]'
                : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))]',
            )}
          >
            {Icon && (
              <Icon
                size={11}
                className={
                  isActive ? 'text-[hsl(var(--primary))]' : 'opacity-70'
                }
              />
            )}
            <span>{label}</span>
            {count !== undefined && (
              <span className="text-[hsl(var(--muted-foreground))] text-[0.625rem]">
                ({count})
              </span>
            )}
            {isActive && (
              <span className="absolute -bottom-px left-2 right-2 h-0.5 rounded-sm bg-[hsl(var(--primary))]" />
            )}
          </button>
        );
      })}
    </nav>
  );
}

export default SubTabNav;
