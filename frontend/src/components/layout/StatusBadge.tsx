'use client';

/**
 * StatusBadge — small color-coded pill.
 *
 * Replaces the ad-hoc inline styles scattered across CronTab,
 * HooksTab, TasksTab, AdminPanel, etc. Use the `tone` preset for
 * common semantics; pass `className` to override when nothing fits.
 */

import { ReactNode } from 'react';
import { LucideIcon } from 'lucide-react';
import { cn } from './cn';

export type BadgeTone =
  | 'success'
  | 'danger'
  | 'warning'
  | 'info'
  | 'neutral'
  | 'primary';

const TONE: Record<BadgeTone, string> = {
  success: 'bg-green-100 text-green-800 border-green-300',
  danger: 'bg-red-100 text-red-800 border-red-300',
  warning: 'bg-amber-100 text-amber-800 border-amber-300',
  info: 'bg-blue-100 text-blue-800 border-blue-300',
  neutral: 'bg-gray-100 text-gray-800 border-gray-300',
  primary: 'bg-[rgba(59,130,246,0.10)] text-[var(--primary-color)] border-[rgba(59,130,246,0.25)]',
};

export interface StatusBadgeProps {
  tone?: BadgeTone;
  icon?: LucideIcon;
  children: ReactNode;
  /** uppercase + monospace — handy for status labels like "live" / "down". */
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
  const Component = onClick ? 'button' : 'span';
  return (
    <Component
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      title={title}
      className={cn(
        'inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[0.625rem]',
        uppercase && 'uppercase tracking-wider font-mono',
        TONE[tone],
        onClick && 'hover:opacity-80 cursor-pointer',
        className,
      )}
    >
      {Icon && <Icon className="w-3 h-3" />}
      {children}
    </Component>
  );
}

export default StatusBadge;
