'use client';

import { useVTuberStore } from '@/store/useVTuberStore';
import { useI18n } from '@/lib/i18n';

/**
 * EmotionTester — button grid to manually set avatar emotions.
 * Useful for debugging and demoing the Live2D expression system.
 */

interface EmotionTesterProps {
  sessionId: string;
  className?: string;
}

export default function EmotionTester({ sessionId, className = '' }: EmotionTesterProps) {
  const { t } = useI18n();
  const setEmotion = useVTuberStore((s) => s.setEmotion);
  const currentState = useVTuberStore((s) => s.avatarStates[sessionId]);
  const model = useVTuberStore((s) => s.getModelForSession(sessionId));

  if (!model) return null;

  const emotions = Object.keys(model.emotionMap);

  return (
    <div className={`px-3 py-2.5 ${className}`}>
      <h4 className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2">
        {t('vtuber.emotions') ?? 'Emotions'}
      </h4>
      <div className="flex flex-wrap gap-1.5">
        {emotions.map((emotion) => (
          <button
            key={emotion}
            onClick={() => setEmotion(sessionId, emotion)}
            className={`px-2.5 py-1 text-[0.6875rem] font-medium rounded-md border cursor-pointer transition-all duration-150 ${
              currentState?.emotion === emotion
                ? 'bg-[var(--primary-color)] text-white border-[var(--primary-color)] shadow-[0_0_6px_rgba(59,130,246,0.3)]'
                : 'bg-[var(--bg-primary)] text-[var(--text-secondary)] border-[var(--border-color)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]'
            }`}
          >
            {emotion}
          </button>
        ))}
      </div>
    </div>
  );
}
