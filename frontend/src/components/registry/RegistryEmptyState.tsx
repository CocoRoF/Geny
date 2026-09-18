'use client';

/**
 * RegistryEmptyState — centered card mirroring the env welcome's
 * primary-CTA pattern. Lives inside the body of `RegistryPageShell`
 * when the registry has no entries yet.
 *
 *   ┌─ rounded-xl card, generous padding ───────────────────────────┐
 *   │                                                                │
 *   │                  [icon-tile, large]                            │
 *   │                                                                │
 *   │                       {title}                                  │
 *   │                  {hint, muted, narrow}                         │
 *   │                                                                │
 *   │                    [+ Add entity]                              │
 *   │                                                                │
 *   └────────────────────────────────────────────────────────────────┘
 *
 * Cycle 20260429 Phase 8.1 — promoted from a thin dashed-border
 * notice to a card with the same rhythm as `OverviewView`'s
 * welcome card. The four registry tabs felt sparse + unloved
 * before; the larger card reads "this is a real surface, here's
 * what to do".
 */

import { Plus, type LucideIcon } from 'lucide-react';

export interface RegistryEmptyStateProps {
  icon: LucideIcon;
  title: string;
  hint?: string;
  /** Primary CTA label. */
  addLabel?: string;
  onAdd?: () => void;
}

export default function RegistryEmptyState({
  icon: Icon,
  title,
  hint,
  addLabel,
  onAdd,
}: RegistryEmptyStateProps) {
  return (
    <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="flex flex-col items-center justify-center gap-4 px-6 py-16 text-center">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-[hsl(var(--primary)/0.08)]">
          <Icon className="w-7 h-7 text-[hsl(var(--primary))]" strokeWidth={1.75} />
        </div>
        <div className="space-y-1.5 max-w-[480px]">
          <div className="text-[1rem] font-semibold text-[hsl(var(--foreground))]">
            {title}
          </div>
          {hint && (
            <p className="text-[0.8125rem] text-[hsl(var(--muted-foreground))] leading-relaxed">
              {hint}
            </p>
          )}
        </div>
        {onAdd && addLabel && (
          <button
            type="button"
            onClick={onAdd}
            className="mt-1 inline-flex items-center gap-1.5 h-9 px-4 rounded-md bg-violet-500 text-white text-[0.8125rem] font-medium hover:bg-violet-600 transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4" />
            {addLabel}
          </button>
        )}
      </div>
    </div>
  );
}
