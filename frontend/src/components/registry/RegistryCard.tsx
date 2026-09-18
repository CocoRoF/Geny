'use client';

/**
 * RegistryCard — uniform item card for host-registry tabs. Now a thin adapter
 * over the canonical {@link EntityCard} so it shares one tone & manner with
 * every other card. Public props are unchanged: tinted icon tile, title +
 * subtitle, clamped description, tone badges, star + action slots, footer meta,
 * hover-lift, muted/active variants.
 */

import { createElement, type ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { EntityCard, type EntityBadge } from '@/components/common/layout/EntityCard';

export interface RegistryCardBadge {
  label: ReactNode;
  tone?: 'neutral' | 'good' | 'warn' | 'info' | 'danger';
  icon?: LucideIcon;
}

export interface RegistryCardProps {
  icon?: LucideIcon;
  title: ReactNode;
  titleMono?: boolean;
  subtitle?: ReactNode;
  description?: ReactNode;
  badges?: RegistryCardBadge[];
  star?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
  variant?: 'default' | 'muted';
  onClick?: () => void;
  active?: boolean;
}

export default function RegistryCard({
  icon,
  title,
  titleMono = false,
  subtitle,
  description,
  badges,
  star,
  actions,
  meta,
  variant = 'default',
  onClick,
  active = false,
}: RegistryCardProps) {
  return (
    <EntityCard
      icon={icon ? createElement(icon, { strokeWidth: 2 }) : undefined}
      iconTone="primary"
      title={title}
      titleMono={titleMono}
      subtitle={subtitle}
      badges={badges as EntityBadge[] | undefined}
      star={star}
      headerActions={actions}
      footerMeta={meta}
      bodyClamp
      variant={variant === 'muted' ? 'muted' : 'elevated'}
      onClick={onClick}
      active={active}
    >
      {description}
    </EntityCard>
  );
}
