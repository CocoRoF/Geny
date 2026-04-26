'use client';

/**
 * DetailDrawer — right-side dismissible panel.
 *
 * Used inside a tab's main pane to show a selected-item detail view
 * without navigating away. ToolCatalog uses this for tool details;
 * McpServers / Logs / Memory could adopt it for their detail pane.
 *
 * Renders nothing when `open` is false — caller manages mount/unmount
 * via useState, no animation overhead.
 */

import { ReactNode } from 'react';
import { X } from 'lucide-react';
import { cn } from './cn';

export interface DetailDrawerProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  /** Fixed width — keeps the underlying main pane stable. */
  width?: 'sm' | 'md' | 'lg';
  /** Right-aligned actions in the header (e.g. edit / delete). */
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
        'shrink-0 border-l border-[var(--border-color)] overflow-y-auto bg-[var(--bg-primary)]',
      )}
    >
      <header className="flex items-center justify-between gap-2 px-4 py-2 border-b border-[var(--border-color)] sticky top-0 bg-[var(--bg-primary)] z-10">
        <h3 className="text-sm font-semibold flex-1 truncate">{title}</h3>
        <div className="flex items-center gap-1 shrink-0">
          {headerActions}
          <button
            type="button"
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
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
