'use client';

import { useEffect } from 'react';
import dynamic from 'next/dynamic';
import { useAppStore } from '@/store/useAppStore';
import { useVTuberStore } from '@/store/useVTuberStore';
import { useI18n } from '@/lib/i18n';

const Live2DCanvas = dynamic(() => import('@/components/live2d/Live2DCanvas'), { ssr: false });

/**
 * VTuberTab — Session tab for Live2D avatar display & control.
 *
 * Features:
 *  - Model selector dropdown (assign model to current session)
 *  - Full-size Live2D rendering canvas
 *  - Emotion tester buttons (per model's emotion map)
 *  - Real-time avatar state display
 *  - SSE subscription lifecycle management
 */

export default function VTuberTab() {
  const { t } = useI18n();
  const selectedSessionId = useAppStore((s) => s.selectedSessionId);
  const sessionId = selectedSessionId || '';

  // Use individual selectors to avoid full-store re-renders on every SSE event
  const models = useVTuberStore((s) => s.models);
  const modelsLoaded = useVTuberStore((s) => s.modelsLoaded);
  const assignedModelName = useVTuberStore((s) => s.assignments[sessionId]);
  const currentState = useVTuberStore((s) => s.avatarStates[sessionId]);
  const fetchModels = useVTuberStore((s) => s.fetchModels);
  const assignModel = useVTuberStore((s) => s.assignModel);
  const unassignModel = useVTuberStore((s) => s.unassignModel);
  const fetchAssignment = useVTuberStore((s) => s.fetchAssignment);
  const subscribeAvatar = useVTuberStore((s) => s.subscribeAvatar);
  const unsubscribeAvatar = useVTuberStore((s) => s.unsubscribeAvatar);
  const setEmotion = useVTuberStore((s) => s.setEmotion);
  const assignedModel = useVTuberStore((s) => s.getModelForSession(sessionId));

  // Load models on mount
  useEffect(() => {
    if (!modelsLoaded) fetchModels();
  }, [modelsLoaded, fetchModels]);

  // Fetch assignment when session changes
  useEffect(() => {
    if (sessionId) fetchAssignment(sessionId);
  }, [sessionId, fetchAssignment]);

  // Subscribe to avatar SSE when assigned
  useEffect(() => {
    if (!sessionId || !assignedModelName) return;
    subscribeAvatar(sessionId);
    return () => unsubscribeAvatar(sessionId);
  }, [sessionId, assignedModelName, subscribeAvatar, unsubscribeAvatar]);

  if (!sessionId) {
    return (
      <div className="flex-1 flex items-center justify-center text-[var(--text-muted)] text-sm">
        {t('common.selectSession') ?? 'Select a session to get started'}
      </div>
    );
  }

  const emotionKeys = assignedModel ? Object.keys(assignedModel.emotionMap) : [];

  return (
    <div className="flex flex-col h-full">
      {/* ── Top Bar ── */}
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-[var(--border-color)] bg-[var(--bg-secondary)] shrink-0 flex-wrap">
        {/* Model selector */}
        <div className="flex items-center gap-2">
          <label className="text-[0.75rem] text-[var(--text-muted)] font-medium">
            {t('vtuber.model') ?? 'Model'}
          </label>
          <select
            className="px-2 py-1 text-[0.75rem] rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[var(--text-primary)] outline-none cursor-pointer min-w-[140px]"
            value={assignedModelName || ''}
            onChange={(e) => {
              if (e.target.value) {
                assignModel(sessionId, e.target.value);
              } else {
                unassignModel(sessionId);
              }
            }}
          >
            <option value="">
              {t('vtuber.selectModel') ?? 'Select model...'}
            </option>
            {models.map((m) => (
              <option key={m.name} value={m.name}>
                {m.display_name}
              </option>
            ))}
          </select>
        </div>

        {/* Emotion tester */}
        {assignedModel && emotionKeys.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[0.6875rem] text-[var(--text-muted)] font-medium mr-1">
              {t('vtuber.emotions') ?? 'Emotions'}:
            </span>
            {emotionKeys.map((emo) => (
              <button
                key={emo}
                onClick={() => setEmotion(sessionId, emo)}
                className={`px-2 py-0.5 text-[0.6875rem] rounded-full border cursor-pointer transition-all duration-150 ${
                  currentState?.emotion === emo
                    ? 'bg-[var(--primary-color)] text-white border-[var(--primary-color)]'
                    : 'bg-transparent text-[var(--text-secondary)] border-[var(--border-color)] hover:bg-[var(--bg-tertiary)]'
                }`}
              >
                {emo}
              </button>
            ))}
          </div>
        )}

        {/* State badge */}
        {currentState && (
          <div className="ml-auto flex items-center gap-2 text-[0.6875rem] text-[var(--text-muted)]">
            <span className="px-2 py-0.5 rounded-full bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)] font-medium">
              {currentState.emotion}
            </span>
            <span className="opacity-60">
              {currentState.motion_group}[{currentState.motion_index}]
            </span>
          </div>
        )}
      </div>

      {/* ── Canvas Area ── */}
      <div className="flex-1 min-h-0 relative bg-[var(--bg-primary)]">
        {assignedModelName ? (
          <Live2DCanvas sessionId={sessionId} />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-[var(--text-muted)]">
            <svg className="w-16 h-16 opacity-30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
            </svg>
            <p className="text-sm">
              {t('vtuber.noModel') ?? 'No model assigned. Select a model above.'}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
