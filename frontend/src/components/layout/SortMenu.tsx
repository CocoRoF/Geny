'use client';

/**
 * SortMenu — sort key dropdown + asc/desc toggle.
 *
 * Single component because the two controls are always read together.
 * Internally uses shadcn Select for the key picker; the direction is
 * a small icon button next to it.
 */

import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from './cn';

export interface SortOptionDef {
  id: string;
  label: string;
}

export type SortDirection = 'asc' | 'desc';

export interface SortMenuProps {
  options: SortOptionDef[];
  value: string;
  direction: SortDirection;
  onChange: (key: string, direction: SortDirection) => void;
  className?: string;
}

export function SortMenu({
  options,
  value,
  direction,
  onChange,
  className,
}: SortMenuProps) {
  const toggleDirection = () =>
    onChange(value, direction === 'asc' ? 'desc' : 'asc');

  const Icon = direction === 'asc' ? ArrowUp : direction === 'desc' ? ArrowDown : ArrowUpDown;

  return (
    <div className={cn('inline-flex items-center gap-1', className)}>
      <button
        type="button"
        onClick={toggleDirection}
        className="inline-flex items-center justify-center w-7 h-7 rounded border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
        title={direction === 'asc' ? '오름차순' : '내림차순'}
        aria-label="Toggle sort direction"
      >
        <Icon className="w-3.5 h-3.5" />
      </button>
      <Select value={value} onValueChange={(v) => onChange(v, direction)}>
        <SelectTrigger className="h-7 w-[140px] text-[0.75rem]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={opt.id} value={opt.id} className="text-[0.75rem]">
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export default SortMenu;
