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
    user: 'max-w-[80%] px-3.5 py-2 rounded-2xl rounded-br-md bg-[var(--primary-color)] text-white whitespace-pre-wrap break-words',
    agent: 'max-w-[80%] px-3.5 py-2 rounded-2xl rounded-bl-md bg-[var(--bg-tertiary)] text-[var(--text-primary)]',
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

  // VTuber mode: speech bubble wrapper
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`${bubbleClass} ${className}`}>
        {children}
      </div>
    </div>
  );
}
