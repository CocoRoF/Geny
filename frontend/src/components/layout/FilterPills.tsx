'use client';

/**
 * FilterPills — single-select or multi-select chip row.
 *
 * `mode='single'` behaves like a segmented control (the active id is
 * always one option, never null). `mode='multi'` toggles each id in
 * the active set; the caller passes an array.
 */

import { ReactNode } from 'react';
import { LucideIcon } from 'lucide-react';
import { cn } from './cn';

export interface FilterPillDef {
  id: string;
  label: ReactNode;
  icon?: LucideIcon;
  count?: number;
  tone?: 'default' | 'danger' | 'warning' | 'success' | 'info';
}

export interface FilterPillsSingleProps {
  mode?: 'single';
  pills: FilterPillDef[];
  active: string;
  onSelect: (id: string) => void;
  className?: string;
}

export interface FilterPillsMultiProps {
  mode: 'multi';
  pills: FilterPillDef[];
  active: string[];
  onToggle: (id: string) => void;
  className?: string;
}

export type FilterPillsProps = FilterPillsSingleProps | FilterPillsMultiProps;

const TONE_CLASSES: Record<NonNullable<FilterPillDef['tone']>, string> = {
  default: 'data-[active=true]:bg-[hsl(var(--primary))] data-[active=true]:text-[hsl(var(--primary-foreground))]',
  danger: 'data-[active=true]:bg-red-500/15 data-[active=true]:text-red-700 dark:data-[active=true]:text-red-300 data-[active=true]:border-red-500/40',
  warning: 'data-[active=true]:bg-amber-500/15 data-[active=true]:text-amber-700 dark:data-[active=true]:text-amber-300 data-[active=true]:border-amber-500/40',
  success: 'data-[active=true]:bg-emerald-500/15 data-[active=true]:text-emerald-700 dark:data-[active=true]:text-emerald-300 data-[active=true]:border-emerald-500/40',
  info: 'data-[active=true]:bg-blue-500/15 data-[active=true]:text-blue-700 dark:data-[active=true]:text-blue-300 data-[active=true]:border-blue-500/40',
};

export function FilterPills(props: FilterPillsProps) {
  const isActive = (id: string) =>
    props.mode === 'multi' ? props.active.includes(id) : props.active === id;

  const handleClick = (id: string) => {
    if (props.mode === 'multi') props.onToggle(id);
    else props.onSelect(id);
  };

  return (
    <div className={cn('flex items-center gap-1.5 flex-wrap', props.className)}>
      {props.pills.map(({ id, label, icon: Icon, count, tone = 'default' }) => {
        const active = isActive(id);
        return (
          <button
            key={id}
            type="button"
            data-active={active}
            onClick={() => handleClick(id)}
            className={cn(
              'inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-[0.75rem] font-medium transition-colors',
              'border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--muted-foreground))]',
              'hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]',
              TONE_CLASSES[tone],
            )}
          >
            {Icon && <Icon className="w-3 h-3" />}
            <span>{label}</span>
            {count !== undefined && (
              <span className="opacity-70 tabular-nums">({count})</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export default FilterPills;
