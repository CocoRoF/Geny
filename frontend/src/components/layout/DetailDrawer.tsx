'use client';

import { ReactNode } from 'react';
import { X } from 'lucide-react';
import { cn } from './cn';

export interface DetailDrawerProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  width?: 'sm' | 'md' | 'lg';
  headerActions?: ReactNode;
  children: ReactNode;
}

const WIDTH: Record<NonNullable<DetailDrawerProps['width']>, string> = {
  sm: 'w-80',
  md: 'w-96',
  lg: 'w-[28rem]',
};

export function DetailDrawer({
  open,
  onClose,
  title,
  width = 'md',
  headerActions,
  children,
}: DetailDrawerProps) {
  if (!open) return null;
  return (
    <aside
      className={cn(
        WIDTH[width],
        'shrink-0 border-l border-[hsl(var(--border))] overflow-y-auto bg-[hsl(var(--card))]',
      )}
    >
      <header className="flex items-center justify-between gap-2 px-4 py-2 border-b border-[hsl(var(--border))] sticky top-0 bg-[hsl(var(--card))] z-10">
        <h3 className="text-sm font-semibold flex-1 truncate">{title}</h3>
        <div className="flex items-center gap-1 shrink-0">
          {headerActions}
          <button
            type="button"
            onClick={onClose}
            className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </header>
      <div className="p-4">{children}</div>
    </aside>
  );
}

export default DetailDrawer;
