'use client';

import { FileCode2, Plus, Minus } from 'lucide-react';
import { shortFileName } from './chat-utils';
import type { FileChanges } from '@/types';

interface FileChangeSummaryProps {
  fileChanges: FileChanges[];
  /** Callback when clicked — e.g. to open a detail viewer. */
  onViewDetail?: (fileChanges: FileChanges[]) => void;
}

/**
 * Compact summary of file changes attached to an agent message.
 * Shows file count, lines added/removed, and per-file breakdown.
 */
export default function FileChangeSummary({ fileChanges, onViewDetail }: FileChangeSummaryProps) {
  const totalAdded = fileChanges.reduce((s, f) => s + f.lines_added, 0);
  const totalRemoved = fileChanges.reduce((s, f) => s + f.lines_removed, 0);

  const Tag = onViewDetail ? 'button' : 'div';

  return (
    <Tag
      type={onViewDetail ? 'button' : undefined}
      className="mt-2 w-full text-left rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors cursor-pointer p-0"
      onClick={onViewDetail ? () => onViewDetail(fileChanges) : undefined}
    >
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-[var(--border-color)]">
        <FileCode2 size={12} className="text-[var(--text-muted)] shrink-0" />
        <span className="text-[0.6875rem] font-medium text-[var(--text-secondary)]">
          {fileChanges.length} file{fileChanges.length > 1 ? 's' : ''} changed
        </span>
        <span className="ml-auto flex items-center gap-2 text-[0.625rem] font-mono">
          {totalAdded > 0 && (
            <span className="flex items-center gap-0.5 text-[var(--success-color,#22c55e)]">
              <Plus size={9} />
              {totalAdded}
            </span>
          )}
          {totalRemoved > 0 && (
            <span className="flex items-center gap-0.5 text-[var(--danger-color,#ef4444)]">
              <Minus size={9} />
              {totalRemoved}
            </span>
          )}
        </span>
      </div>
      <div className="px-3 py-1.5 space-y-0.5">
        {fileChanges.map((fc, i) => (
          <div key={i} className="flex items-center gap-2 text-[0.625rem]">
            <span
              className="px-1 py-[0.5px] rounded text-[0.5rem] font-bold uppercase tracking-wider"
              style={{
                backgroundColor: fc.operation === 'create' ? 'rgba(34,197,94,0.1)' :
                  fc.operation === 'edit' || fc.operation === 'multi_edit' ? 'rgba(245,158,11,0.1)' :
                  'rgba(59,130,246,0.1)',
                color: fc.operation === 'create' ? 'var(--success-color)' :
                  fc.operation === 'edit' || fc.operation === 'multi_edit' ? 'var(--warning-color)' :
                  'var(--primary-color)',
              }}
            >
              {fc.operation === 'multi_edit' ? 'edit' : fc.operation}
            </span>
            <span className="font-mono text-[var(--text-secondary)] truncate">{shortFileName(fc.file_path)}</span>
            <span className="ml-auto flex items-center gap-1.5 font-mono shrink-0">
              {fc.lines_added > 0 && <span className="text-[var(--success-color,#22c55e)]">+{fc.lines_added}</span>}
              {fc.lines_removed > 0 && <span className="text-[var(--danger-color,#ef4444)]">-{fc.lines_removed}</span>}
            </span>
          </div>
        ))}
      </div>
    </Tag>
  );
}
