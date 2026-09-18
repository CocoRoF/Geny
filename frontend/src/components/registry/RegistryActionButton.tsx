'use client';

/**
 * RegistryActionButton — uniform 24×24 icon button for card-row
 * actions (edit / delete / power-toggle). Used inside <RegistryCard>
 * `actions` slot so the button cluster stays consistent across the
 * four registry tabs.
 *
 * Variants drive hover color:
 *
 *   default   — muted ↔ foreground, neutral hover
 *   primary   — muted ↔ violet primary
 *   danger    — muted ↔ red destructive
 *
 * Group hover: cards add `group` class; the buttons opt-in to
 * `group-hover:opacity-100` so they fade into view only when the
 * card is hovered, keeping the resting state clean.
 */

import type { MouseEventHandler } from 'react';
import type { LucideIcon } from 'lucide-react';

export interface RegistryActionButtonProps {
  icon: LucideIcon;
  onClick: MouseEventHandler<HTMLButtonElement>;
  title: string;
  variant?: 'default' | 'primary' | 'danger';
  disabled?: boolean;
  /** Make button always visible instead of fade-in on hover. */
  alwaysVisible?: boolean;
}

const VARIANT_CLASS: Record<NonNullable<RegistryActionButtonProps['variant']>, string> = {
  default:
    'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))]',
  primary:
    'text-[hsl(var(--muted-foreground))] hover:text-violet-500 hover:bg-violet-500/10',
  danger:
    'text-[hsl(var(--muted-foreground))] hover:text-red-500 hover:bg-red-500/10',
};

export default function RegistryActionButton({
  icon: Icon,
  onClick,
  title,
  variant = 'default',
  disabled = false,
  alwaysVisible = false,
}: RegistryActionButtonProps) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick(e);
      }}
      disabled={disabled}
      title={title}
      aria-label={title}
      className={`inline-flex items-center justify-center w-7 h-7 rounded transition-all ${
        VARIANT_CLASS[variant]
      } ${alwaysVisible ? '' : 'opacity-0 group-hover:opacity-100 focus:opacity-100'} ${
        disabled ? 'opacity-40 cursor-not-allowed' : ''
      }`}
    >
      <Icon className="w-3.5 h-3.5" />
    </button>
  );
}
