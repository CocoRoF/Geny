'use client';

import type { ReactNode } from 'react';

export type BubbleMode = 'messenger' | 'vtuber' | 'command';

interface MessageBubbleProps {
  mode: BubbleMode;
  isUser: boolean;
  children: ReactNode;
  className?: string;
}

const modeStyles: Record<BubbleMode, { user: string; agent: string }> = {
  messenger: {
    user: '',
    agent: '',
  },
  vtuber: {
    user: 'max-w-[85%] px-3.5 py-2 rounded-2xl rounded-br-md bg-[var(--primary-color)] text-white text-[0.875rem] leading-relaxed whitespace-pre-wrap break-keep',
    agent: 'max-w-[85%] px-3.5 py-2.5 rounded-2xl rounded-bl-md bg-[var(--bg-tertiary)] text-[var(--text-primary)] break-keep',
  },
  command: {
    user: '',
    agent: '',
  },
};

/**
 * MessageBubble — mode-aware wrapper for chat messages.
 *
 * - `messenger`: no extra wrapping (uses flat layout)
 * - `vtuber`: speech bubble with rounded corners (user right-aligned, agent left-aligned)
 * - `command`: no extra wrapping (timeline layout)
 */
export default function MessageBubble({ mode, isUser, children, className = '' }: MessageBubbleProps) {
  const style = modeStyles[mode];
  const bubbleClass = isUser ? style.user : style.agent;

  // Messenger and command modes: no extra wrapping
  if (mode === 'messenger' || mode === 'command') {
    return <>{children}</>;
  }

  // VTuber mode: bubble only (caller handles flex alignment)
  return (
    <div className={`${bubbleClass} ${className}`}>
      {children}
    </div>
  );
}
