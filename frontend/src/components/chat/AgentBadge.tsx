'use client';

import { getRoleBadgeBg } from './chat-utils';

interface AgentBadgeProps {
  role: string;
  className?: string;
}

/**
 * Small inline role badge with role-specific gradient background — developer, researcher, planner, worker.
 */
export default function AgentBadge({ role, className }: AgentBadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-1.5 py-[1px] rounded text-[0.5625rem] font-bold text-white uppercase tracking-wider ${className || ''}`}
      style={{ background: getRoleBadgeBg(role) }}
    >
      {role}
    </span>
  );
}
