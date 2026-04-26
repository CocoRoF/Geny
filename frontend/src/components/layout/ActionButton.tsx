'use client';

/**
 * ActionButton — header-row action button (shadcn-backed).
 *
 * Forwards to ui/Button under the hood; keeps the original three-variant
 * API (primary / secondary / danger) so existing call sites don't change.
 * The `spinIcon` prop continues to animate the icon via animate-spin.
 */

import { ButtonHTMLAttributes, ReactNode } from 'react';
import { LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from './cn';

type Variant = 'primary' | 'secondary' | 'danger';

const VARIANT_TO_SHADCN: Record<Variant, 'default' | 'outline' | 'destructive'> = {
  primary: 'default',
  secondary: 'outline',
  danger: 'destructive',
};

export interface ActionButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  icon?: LucideIcon;
  spinIcon?: boolean;
  children?: ReactNode;
}

export function ActionButton({
  variant = 'secondary',
  icon: Icon,
  spinIcon = false,
  children,
  className,
  ...rest
}: ActionButtonProps) {
  const isDanger = variant === 'danger';
  return (
    <Button
      variant={VARIANT_TO_SHADCN[variant]}
      size="sm"
      className={cn(
        // outline+danger needs a tint; keep the pre-shadcn red look.
        isDanger && 'bg-transparent text-red-600 border border-red-300 hover:bg-red-50 dark:text-red-400 dark:border-red-500/40 dark:hover:bg-red-500/10',
        className,
      )}
      {...rest}
    >
      {Icon && <Icon className={cn('w-3 h-3', spinIcon && 'animate-spin')} />}
      {children}
    </Button>
  );
}

export default ActionButton;
