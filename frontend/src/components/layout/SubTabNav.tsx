'use client';

/**
 * SubTabNav — horizontal pill nav for sub-tabs inside a host tab.
 *
 * Used by EnvironmentTab (global + session) to host configuration
 * sub-tabs (Library / Tool Sets / Permissions / Hooks / …). Renders a
 * compact strip just below the page-level TabNavigation so the host
 * tab's identity stays at the top while the operator switches contexts
 * inside.
 *
 * Visual budget: matches TabShell's header height so the layout
 * doesn't shift when switching between sub-tabs that have / don't
 * have their own internal headers.
 */

import { ReactNode } from 'react';
import { LucideIcon } from 'lucide-react';
import { cn } from './cn';

export interface SubTabDef {
  id: string;
  label: ReactNode;
  /** Optional icon shown before the label. */
  icon?: LucideIcon;
  /** Optional count badge ("(3)"). Pass undefined to hide. */
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
      className="flex items-center gap-0.5 px-2 md:px-3 h-9 border-b border-[var(--border-color)] bg-[var(--bg-secondary)] shrink-0 overflow-x-auto scrollbar-hide"
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
              'relative inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-[0.75rem] font-medium whitespace-nowrap transition-colors',
              isActive
                ? 'text-[var(--text-primary)] bg-[var(--bg-tertiary)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]',
            )}
          >
            {Icon && <Icon size={11} className={isActive ? 'text-[var(--primary-color)]' : ''} />}
            <span>{label}</span>
            {count !== undefined && (
              <span className="text-[var(--text-muted)] text-[0.625rem]">({count})</span>
            )}
            {isActive && (
              <span className="absolute -bottom-px left-2 right-2 h-0.5 rounded-sm bg-[var(--primary-color)]" />
            )}
          </button>
        );
      })}
    </nav>
  );
}

export default SubTabNav;
