'use client';

import dynamic from 'next/dynamic';
import { useVTuberStore } from '@/store/useVTuberStore';

const Live2DCanvas = dynamic(() => import('@/components/live2d/Live2DCanvas'), { ssr: false });

/**
 * MiniAvatar — compact Live2D avatar for inline use (chat messages, member lists).
 *
 * Falls back to a plain styled circle when no model is assigned.
 */

interface MiniAvatarProps {
  sessionId: string;
  size?: number;
  className?: string;
  /** Gradient CSS class for fallback circle (matches role color) */
  fallbackGradient?: string;
  /** Content to show inside fallback circle */
  fallbackContent?: React.ReactNode;
}

export default function MiniAvatar({
  sessionId,
  size = 36,
  className = '',
  fallbackGradient = 'from-emerald-500 to-green-500',
  fallbackContent,
}: MiniAvatarProps) {
  const assignedModelName = useVTuberStore((s) => s.assignments[sessionId]);

  if (!assignedModelName) {
    return (
      <div
        className={`rounded-full bg-gradient-to-br ${fallbackGradient} flex items-center justify-center shrink-0 ${className}`}
        style={{ width: size, height: size }}
      >
        {fallbackContent}
      </div>
    );
  }

  return (
    <div
      className={`rounded-lg overflow-hidden shrink-0 ${className}`}
      style={{ width: size, height: size }}
    >
      <Live2DCanvas
        sessionId={sessionId}
        interactive={false}
        backgroundAlpha={0}
      />
    </div>
  );
}
