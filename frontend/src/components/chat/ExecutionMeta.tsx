'use client';

import { formatDuration } from './chat-utils';

interface ExecutionMetaProps {
  durationMs?: number | null;
  costUsd?: number | null;
  className?: string;
}

/**
 * Compact inline display of execution duration and cost.
 */
export default function ExecutionMeta({ durationMs, costUsd, className }: ExecutionMetaProps) {
  if (!durationMs && !costUsd) return null;

  return (
    <span className={`inline-flex items-center gap-1.5 text-[0.5625rem] text-[var(--text-muted)] ${className || ''}`}>
      {typeof durationMs === 'number' && durationMs > 0 && (
        <span>({formatDuration(durationMs)})</span>
      )}
      {typeof costUsd === 'number' && costUsd > 0 && (
        <span>${costUsd.toFixed(3)}</span>
      )}
    </span>
  );
}
