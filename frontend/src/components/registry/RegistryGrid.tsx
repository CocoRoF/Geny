'use client';

/**
 * RegistryGrid — responsive card grid used by all four registry
 * tabs. Mirrors the breakpoints from the env welcome card layout
 * so the visual rhythm carries through (`1 / md:2 / xl:3`).
 *
 * Rendered inside <RegistrySection> when grouping, or directly
 * inside <RegistryPageShell> body when there's no grouping.
 */

import type { ReactNode } from 'react';

export interface RegistryGridProps {
  children: ReactNode;
  /** Override columns at xl breakpoint (default 3). */
  xlCols?: 2 | 3 | 4;
}

export default function RegistryGrid({
  children,
  xlCols = 3,
}: RegistryGridProps) {
  const xlClass =
    xlCols === 2 ? 'xl:grid-cols-2' : xlCols === 4 ? 'xl:grid-cols-4' : 'xl:grid-cols-3';
  return (
    <div className={`grid grid-cols-1 md:grid-cols-2 ${xlClass} gap-2.5`}>
      {children}
    </div>
  );
}
