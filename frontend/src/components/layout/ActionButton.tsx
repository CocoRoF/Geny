'use client';

/**
 * ActionButton — header-row action button.
 *
 * Used in TabShell.actions slots so every tab's "Add" / "Refresh" /
 * "Save" buttons match. Three variants:
 *
 *   - primary    — filled accent (Add / Save)
 *   - secondary  — bordered (Refresh / Cancel)
 *   - danger     — bordered red (Delete / rare)
 *
 * Loading icons should be passed in via `icon` and animate via the
 * caller (`<RefreshCw className={loading ? 'animate-spin' : ''} />`).
 */

import { ReactNode, ButtonHTMLAttributes } from 'react';
import { LucideIcon } from 'lucide-react';
import { cn } from './cn';

type Variant = 'primary' | 'secondary' | 'danger';

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-[var(--primary-color)] text-white hover:bg-[var(--primary-hover)] border border-[var(--primary-color)]',
  secondary: 'border border-[var(--border-color)] hover:bg-[var(--bg-tertiary)] text-[var(--text-primary)]',
  danger: 'border border-red-300 text-red-700 hover:bg-red-50',
};

export interface ActionButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  icon?: LucideIcon;
  /** When true, the icon spins (renders nothing differently — the
   * caller can also just pass an iconClassName themselves). */
  spinIcon?: boolean;
  children?: ReactNode;
}

export function ActionButton({
  variant = 'secondary',
  icon: Icon,
  spinIcon = false,
  children,
  className,
  type = 'button',
  ...rest
}: ActionButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        'flex items-center gap-1 text-xs rounded px-2 py-1 transition-colors disabled:opacity-50',
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {Icon && <Icon className={cn('w-3 h-3', spinIcon && 'animate-spin')} />}
      {children}
    </button>
  );
}

export default ActionButton;
