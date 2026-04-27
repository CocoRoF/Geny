'use client';

/**
 * TabFooter — sticky status row (counts, pagination, hints).
 *
 * Three slots: `left` (typically counts), `center` (pagination), `right`
 * (extra hints). Renders inside TabShell's `footer` slot.
 */

import { ReactNode } from 'react';
import { cn } from './cn';

export interface TabFooterProps {
  left?: ReactNode;
  center?: ReactNode;
  right?: ReactNode;
  className?: string;
}

export function TabFooter({ left, center, right, className }: TabFooterProps) {
  return (
    <div className={cn('flex items-center gap-3 w-full', className)}>
      {left && <div className="flex-shrink-0">{left}</div>}
      {center && <div className="flex-1 flex items-center justify-center">{center}</div>}
      {right && <div className="ml-auto flex-shrink-0">{right}</div>}
    </div>
  );
}

export interface CountSummaryProps {
  total: number;
  shown?: number;
  selected?: number;
  unit?: string;
}

export function CountSummary({
  total,
  shown,
  selected,
  unit = '개',
}: CountSummaryProps) {
  const parts: string[] = [];
  parts.push(`총 ${total.toLocaleString()}${unit}`);
  if (shown !== undefined && shown !== total) {
    parts.push(`표시 ${shown.toLocaleString()}${unit}`);
  }
  if (selected !== undefined && selected > 0) {
    parts.push(`선택 ${selected.toLocaleString()}${unit}`);
  }
  return <span className="tabular-nums">{parts.join(' · ')}</span>;
}

export default TabFooter;
