'use client';

/**
 * RealtimeVoiceDriver — hands-free voice conversation, integrated with the
 * VISIBLE chat.
 *
 * When `active`, it opens the realtime voice WebSocket (`/ws/voice/realtime/
 * {sid}`) and streams the mic to the backend, which runs Silero VAD and, on
 * end-of-speech, transcribes the utterance. In the default `stt_only` mode
 * the server just returns the transcript and THIS driver posts it to the
 * chat room exactly like typing — so the spoken message appears as a user
 * bubble and the persona's reply comes back through the normal chat + TTS
 * path (visible, with lip-sync). The user can SEE what was heard.
 *
 * Live feedback (store): `realtimeListening` while the server hears speech,
 * `realtimePartial` for the interim transcript — rendered as a "듣는 중…"
 * pill so it's obvious the mic is live.
 *
 * Barge-in: on the server's `speech_start`, cut the current TTS and cancel
 * the in-flight persona reply (same as the push-to-talk hotkey).
 *
 * Input modes (store `realtimeInputMode`):
 *   server_vad (default) — stream raw PCM; backend VAD decides end-of-speech.
 *   client_vad           — browser segments utterances (webm) and uploads.
 */

import { useCallback, useEffect, useRef } from 'react';
import { useVoiceActivityRecorder } from '@/lib/useVoiceActivityRecorder';
import { useVTuberStore } from '@/store/useVTuberStore';
import { getAudioManager } from '@/lib/audioManager';
import { openRealtimeVoiceWs, chatApi } from '@/lib/api';
import { startPcmStream, type PcmStreamHandle } from '@/lib/pcmStreamer';
import { audioRouting } from '@/lib/audioDevices';
import { grabCurrentScreenAttachment } from '@/lib/screenFrameAccess';

interface ServerEvent {
  type: string;
  data?: Record<string, unknown>;
}

export default function RealtimeVoiceDriver({
  sessionId,
  roomId,
  active,
}: {
  sessionId: string;
  roomId?: string | null;
  active: boolean;
}) {
  const inputMode = useVTuberStore((s) => s.realtimeInputMode);
  const clientVad = inputMode === 'client_vad';

  const wsRef = useRef<WebSocket | null>(null);
  const pcmHandleRef = useRef<PcmStreamHandle | null>(null);
  // Dedup guard so a duplicated final transcript can't post the message twice.
  const lastSentRef = useRef<{ text: string; at: number }>({ text: '', at: 0 });

  // ── barge-in: cut current TTS + cancel the in-flight chat reply ──
  const bargeIn = useCallback(() => {
    const st = useVTuberStore.getState();
    st.stopSpeaking(sessionId);
    if (roomId) chatApi.cancelTurn(roomId).catch(() => {});
  }, [sessionId, roomId]);

  // ── send a finished transcript into the VISIBLE chat (like typing) ──
  const sendToChat = useCallback(
    async (text: string) => {
      const msg = text.trim();
      if (!msg || !roomId) return;
      // Dedup: a duplicated final transcript (server retry) must not double-post.
      const now = Date.now();
      if (msg === lastSentRef.current.text && now - lastSentRef.current.at < 4000) return;
      lastSentRef.current = { text: msg, at: now };
      try {
        const st = useVTuberStore.getState();
        if (st.ttsEnabled) {
          getAudioManager().ensureResumed();
          st.beginTTSTurn(sessionId);
        }
        const screen = st.screenObservationEnabled
          ? await grabCurrentScreenAttachment()
          : null;
        await chatApi.sendMessage(roomId, {
          message: msg,
          attachments: screen ? [screen] : undefined,
        });
      } catch (e) {
        console.error('[realtime-voice] broadcast failed', e);
      }
    },
    [sessionId, roomId],
  );

  const handleServerEvent = useCallback(
    (msg: ServerEvent) => {
      const st = useVTuberStore.getState();
      const d = msg.data ?? {};
      switch (msg.type) {
        case 'ready':
          break;
        case 'speech_start':
          st.setRealtimeListening(true);
          st.setRealtimePartial('');
          bargeIn(); // user started talking → interrupt the reply
          break;
        case 'speech_end':
          st.setRealtimeListening(false);
          break;
        case 'transcript': {
          const text = String(d.text ?? '');
          if (d.final) {
            st.setRealtimeListening(false);
            st.setRealtimePartial('');
            if (text) void sendToChat(text); // → visible chat message + reply
          } else {
            // interim caption: stable_chars = settled prefix (rendered solid).
            st.setRealtimePartial(text, Number(d.stable_chars ?? 0));
          }
          break;
        }
        default:
          // stt_only mode: the server does not stream reply audio here —
          // the reply comes through the normal chat/TTS path.
          break;
      }
    },
    [bargeIn, sendToChat],
  );

  // Keep the WS onmessage bound to the LATEST handler so a late-resolving
  // roomId (null → real id) isn't stuck in a stale closure.
  const handlerRef = useRef(handleServerEvent);
  handlerRef.current = handleServerEvent;

  // ── WebSocket lifecycle + server_vad PCM streaming ───────────────
  useEffect(() => {
    if (!active) return;
    let closed = false;
    const ws = openRealtimeVoiceWs(sessionId);
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;
    getAudioManager().ensureResumed();

    const resetIndicators = () => {
      const st = useVTuberStore.getState();
      st.setRealtimeListening(false);
      st.setRealtimePartial('');
    };

    ws.onopen = () => {
      if (closed) return;
      ws.send(
        JSON.stringify({
          type: 'start',
          language: '',
          input_mode: inputMode,
          stt_only: true,
          partials: useVTuberStore.getState().realtimePartialsEnabled,
        }),
      );
      if (!clientVad) void startMic();
    };

    // Open (or re-open) the mic on the chosen input device. Re-openable so a
    // late-appearing device (VoiceMeeter) can be switched to live.
    const startMic = async () => {
      const deviceId = (await audioRouting.currentInputDeviceId()) || undefined;
      pcmHandleRef.current?.stop();
      pcmHandleRef.current = null;
      try {
        const h = await startPcmStream({
          deviceId,
          onFrame: (pcm) => {
            const sock = wsRef.current;
            if (sock && sock.readyState === WebSocket.OPEN) sock.send(pcm);
          },
        });
        if (closed) h.stop();
        else pcmHandleRef.current = h;
      } catch (e) {
        console.error('[realtime-voice] pcm stream failed', e);
      }
    };

    // The mic input device changed (e.g. VoiceMeeter just came up) → restart the
    // capture on the new device without dropping the WS.
    const offInput = clientVad
      ? undefined
      : audioRouting.onInputChange(() => {
          if (!closed && wsRef.current?.readyState === WebSocket.OPEN) void startMic();
        });
    ws.onmessage = (ev) => {
      if (typeof ev.data !== 'string') return;
      try {
        handlerRef.current(JSON.parse(ev.data));
      } catch {
        /* ignore */
      }
    };
    // On drop/error: reset the indicator and release the mic (the worklet
    // would otherwise keep capturing into a dead socket). No auto-reconnect —
    // the user re-toggles 대화, which re-runs this effect cleanly.
    ws.onclose = ws.onerror = () => {
      resetIndicators();
      pcmHandleRef.current?.stop();
      pcmHandleRef.current = null;
    };

    return () => {
      closed = true;
      offInput?.();
      pcmHandleRef.current?.stop();
      pcmHandleRef.current = null;
      try {
        ws.close();
      } catch {
        /* already closing */
      }
      wsRef.current = null;
      resetIndicators();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, sessionId, inputMode, clientVad]);

  // ── client_vad path (browser segments utterances) ────────────────
  const onSpeechStart = useCallback(() => {
    useVTuberStore.getState().setRealtimeListening(true);
    bargeIn();
  }, [bargeIn]);

  const onUtterance = useCallback(async (blob: Blob) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      ws.send(await blob.arrayBuffer());
    } catch (e) {
      console.error('[realtime-voice] utterance send failed', e);
    }
  }, []);

  useVoiceActivityRecorder({
    enabled: active && clientVad,
    onUtterance,
    onSpeechStart,
    pauseWhileSpeaking: false,
    isAgentSpeaking: false,
    speechThreshold: useVTuberStore.getState().sttSensitivity,
    silenceTrailMs: useVTuberStore.getState().sttSilenceMs,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  });

  return null;
}
