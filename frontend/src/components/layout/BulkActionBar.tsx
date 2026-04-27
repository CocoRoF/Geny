'use client';

/**
 * BulkActionBar — contextual bar shown when items are selected.
 *
 * Renders inside TabShell's `bulkBar` slot (between header/toolbar and
 * body). Shows the selection count, optional "select all" toggle,
 * and a slot for bulk action buttons. Hidden by callers when count=0.
 */

import { ReactNode } from 'react';
import { CheckSquare, Square, X } from 'lucide-react';
import { cn } from './cn';

export interface BulkActionBarProps {
  count: number;
  total?: number;
  onSelectAll?: () => void;
  onClear: () => void;
  actions?: ReactNode;
  label?: (count: number) => string;
  className?: string;
}

const defaultLabel = (n: number) => `${n}개 선택됨`;

export function BulkActionBar({
  count,
  total,
  onSelectAll,
  onClear,
  actions,
  label = defaultLabel,
  className,
}: BulkActionBarProps) {
  const allSelected = total !== undefined && count >= total && total > 0;

  return (
    <div
      className={cn(
        'flex items-center gap-3 text-[0.75rem] text-[hsl(var(--foreground))]',
        className,
      )}
    >
      {onSelectAll && total !== undefined && (
        <button
          type="button"
          onClick={onSelectAll}
          className="inline-flex items-center gap-1.5 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
          aria-label={allSelected ? '전체 해제' : '전체 선택'}
        >
          {allSelected ? (
            <CheckSquare className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />
          ) : (
            <Square className="w-3.5 h-3.5" />
          )}
          <span>{allSelected ? '전체 해제' : '전체 선택'}</span>
        </button>
      )}

      <span className="font-semibold tabular-nums">
        {label(count)}
        {total !== undefined && (
          <span className="ml-1 text-[hsl(var(--muted-foreground))] font-normal">
            / {total}
          </span>
        )}
      </span>

      {actions && <div className="flex items-center gap-1.5">{actions}</div>}

      <button
        type="button"
        onClick={onClear}
        className="ml-auto inline-flex items-center gap-1 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
        aria-label="선택 해제"
      >
        <X className="w-3.5 h-3.5" />
        <span>해제</span>
      </button>
    </div>
  );
}

export default BulkActionBar;
