'use client';

import { ReactNode } from 'react';
import { LucideIcon } from 'lucide-react';

export interface EmptyStateProps {
  icon?: LucideIcon;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
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
          ? 'text-center text-[hsl(var(--muted-foreground))] py-4 text-xs'
          : 'flex flex-col items-center justify-center text-center py-12 px-4 h-full'
      }
    >
      {Icon && (
        <Icon
          className={
            compact
              ? 'w-4 h-4 mx-auto mb-1 opacity-50 text-[hsl(var(--muted-foreground))]'
              : 'w-10 h-10 mx-auto mb-3 opacity-40 text-[hsl(var(--muted-foreground))]'
          }
          strokeWidth={1.5}
        />
      )}
      <div
        className={
          compact
            ? 'text-[hsl(var(--muted-foreground))]'
            : 'text-sm font-medium text-[hsl(var(--foreground))]'
        }
      >
        {title}
      </div>
      {description && (
        <div
          className={
            compact
              ? 'mt-0.5 text-[hsl(var(--muted-foreground))]'
              : 'mt-1.5 text-xs max-w-md text-[hsl(var(--muted-foreground))]'
          }
        >
          {description}
        </div>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export default EmptyState;
