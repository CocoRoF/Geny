'use client';

/**
 * PushToTalkDriver — runs the mic recorder while `active`, transcribes each
 * utterance and sends it as a real CHAT TURN (not an inbox note like
 * STTControls), so the avatar replies. Mounted hidden in the overlay window;
 * toggled by the global push-to-talk hotkey.
 *
 * Barge-in: it does NOT pause while the agent is speaking (pauseWhileSpeaking
 * false) — the overlay cuts the current TTS on the hotkey down-edge, and this
 * keeps capturing so the user can talk over the avatar.
 */

import { useCallback } from 'react';
import { useVoiceActivityRecorder } from '@/lib/useVoiceActivityRecorder';
import { useVTuberStore } from '@/store/useVTuberStore';
import { getAudioManager } from '@/lib/audioManager';
import { sttApi, chatApi } from '@/lib/api';
import { grabCurrentScreenAttachment } from '@/lib/screenFrameAccess';

export default function PushToTalkDriver({
  sessionId,
  roomId,
  active,
}: {
  sessionId: string;
  roomId: string;
  active: boolean;
}) {
  const onUtterance = useCallback(
    async (blob: Blob) => {
      try {
        const { text } = await sttApi.transcribe(blob);
        const msg = (text || '').trim();
        if (!msg) return;
        // Mirror VTuberChatPanel.handleSend so the reply auto-speaks.
        if (useVTuberStore.getState().ttsEnabled) {
          getAudioManager().ensureResumed();
          useVTuberStore.getState().beginTTSTurn(sessionId);
        }
        // When screen observation is ON, attach the CURRENT frame so the
        // avatar sees what's on screen as you speak (OLV turn-attach model).
        // Reuses the already-open observation stream — no extra prompt; null
        // when the toggle is off or no stream in this window.
        const screen = useVTuberStore.getState().screenObservationEnabled
          ? await grabCurrentScreenAttachment()
          : null;
        await chatApi.sendMessage(roomId, {
          message: msg,
          attachments: screen ? [screen] : undefined,
        });
      } catch (e) {
        console.error('[push-to-talk]', e);
      }
    },
    [sessionId, roomId],
  );

  useVoiceActivityRecorder({
    enabled: active,
    onUtterance,
    pauseWhileSpeaking: false, // we want to be able to interrupt the avatar
    isAgentSpeaking: false,
    speechThreshold: 0.06, // slightly higher so TTS bleed doesn't self-trigger
  });

  return null;
}
