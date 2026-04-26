'use client';

/**
 * StatusBadge — small color-coded pill (shadcn-backed).
 *
 * Same tone API as before; underlying surface is shadcn's Badge
 * variants. The `onClick` prop still falls back to a button render so
 * tabs that use it for click-to-toggle don't break.
 */

import { ReactNode } from 'react';
import { LucideIcon } from 'lucide-react';
import { Badge, type BadgeProps } from '@/components/ui/badge';
import { cn } from './cn';

export type BadgeTone =
  | 'success'
  | 'danger'
  | 'warning'
  | 'info'
  | 'neutral'
  | 'primary';

const TONE_TO_VARIANT: Record<BadgeTone, BadgeProps['variant']> = {
  success: 'success',
  danger: 'danger',
  warning: 'warning',
  info: 'info',
  neutral: 'secondary',
  primary: 'default',
};

export interface StatusBadgeProps {
  tone?: BadgeTone;
  icon?: LucideIcon;
  children: ReactNode;
  uppercase?: boolean;
  className?: string;
  title?: string;
  onClick?: () => void;
}

export function StatusBadge({
  tone = 'neutral',
  icon: Icon,
  children,
  uppercase = false,
  className,
  title,
  onClick,
}: StatusBadgeProps) {
  const merged = cn(
    uppercase && 'uppercase tracking-wider font-mono',
    onClick && 'cursor-pointer hover:opacity-90 transition-opacity',
    className,
  );

  if (onClick) {
    return (
      <button type="button" onClick={onClick} title={title} className="inline-flex">
        <Badge variant={TONE_TO_VARIANT[tone]} className={merged}>
          {Icon && <Icon className="w-3 h-3" />}
          {children}
        </Badge>
      </button>
    );
  }

  return (
    <Badge variant={TONE_TO_VARIANT[tone]} className={merged} title={title}>
      {Icon && <Icon className="w-3 h-3" />}
      {children}
    </Badge>
  );
}

export default StatusBadge;
