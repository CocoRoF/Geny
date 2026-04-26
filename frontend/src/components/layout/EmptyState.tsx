'use client';

import { ReactNode } from 'react';
import { LucideIcon } from 'lucide-react';

export interface EmptyStateProps {
  icon?: LucideIcon;
  title: ReactNode;
  description?: ReactNode;
  /** Single CTA element rendered below the description. */
  action?: ReactNode;
  /** Compact variant — half the padding, smaller text. Default false. */
  compact?: boolean;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  compact = false,
}: EmptyStateProps) {
  return (
    <div
      className={
        compact
          ? 'text-center text-[var(--text-muted)] py-4 text-[0.75rem]'
          : 'flex flex-col items-center justify-center text-center text-[var(--text-muted)] py-12 px-4'
      }
    >
      {Icon && (
        <Icon
          className={compact ? 'w-4 h-4 mx-auto mb-1 opacity-60' : 'w-8 h-8 mx-auto mb-2 opacity-60'}
        />
      )}
      <div className={compact ? '' : 'text-[0.875rem] font-medium text-[var(--text-secondary)]'}>
        {title}
      </div>
      {description && (
        <div className={compact ? 'mt-0.5' : 'mt-1 text-[0.75rem] max-w-md'}>
          {description}
        </div>
      )}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export default EmptyState;
