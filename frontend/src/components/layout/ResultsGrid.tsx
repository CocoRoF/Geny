'use client';

/**
 * ResultsGrid — auto-fill card grid with built-in empty / loading states.
 *
 * - `items.length === 0 && loading` → skeleton grid
 * - `items.length === 0 && !loading` → renders `empty` (or default text)
 * - otherwise → maps via `renderItem`
 *
 * The grid uses `grid-cols-[repeat(auto-fill,minmax(<min>,1fr))]` so
 * cards fill the row and wrap automatically. `min` defaults to 260px.
 */

import { ReactNode } from 'react';
import { cn } from './cn';

export interface ResultsGridProps<T> {
  items: T[];
  renderItem: (item: T, index: number) => ReactNode;
  keyOf: (item: T) => string;
  loading?: boolean;
  empty?: ReactNode;
  minItemWidth?: number;
  gap?: 'sm' | 'md' | 'lg';
  skeletonCount?: number;
  className?: string;
}

const GAP: Record<NonNullable<ResultsGridProps<unknown>['gap']>, string> = {
  sm: 'gap-2',
  md: 'gap-3',
  lg: 'gap-4',
};

export function ResultsGrid<T>({
  items,
  renderItem,
  keyOf,
  loading = false,
  empty,
  minItemWidth = 260,
  gap = 'md',
  skeletonCount = 6,
  className,
}: ResultsGridProps<T>) {
  const gridStyle = {
    gridTemplateColumns: `repeat(auto-fill,minmax(${minItemWidth}px,1fr))`,
  };

  if (items.length === 0 && loading) {
    return (
      <div
        className={cn('grid', GAP[gap], className)}
        style={gridStyle}
      >
        {Array.from({ length: skeletonCount }, (_, i) => (
          <div
            key={i}
            className="h-32 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className={cn('w-full', className)}>
        {empty ?? (
          <div className="text-center text-[hsl(var(--muted-foreground))] py-12 text-sm">
            결과가 없습니다.
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn('grid', GAP[gap], className)}
      style={gridStyle}
    >
      {items.map((item, idx) => (
        <div key={keyOf(item)}>{renderItem(item, idx)}</div>
      ))}
    </div>
  );
}

export default ResultsGrid;
