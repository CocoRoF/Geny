'use client';

/**
 * /overlay — the transparent avatar surface the desktop connector loads.
 *
 * Reuses the proven browser stack with NO porting: AvatarCanvas (Live2D/Spine)
 * driven by the same zustand store + avatar-state WS, and a hidden
 * VTuberChatPanel that orchestrates chat→TTS→lip-sync exactly as the dashboard
 * does. The connector points an Electron transparent window at
 * `${serverUrl}/overlay?token=<jwt>` (and optionally &session=&room=); a normal
 * browser can open the same URL (when logged in) to verify rendering.
 *
 * Query params:
 *   token   — JWT; stored to localStorage so apiCall + makeAuthedWs use it.
 *   session — session_id to render (default: first role==='vtuber' session).
 *   room    — chat room_id for TTS (default: the session's chat_room_id).
 */

import { useEffect, useRef, useState, type CSSProperties, type ReactNode, type PointerEvent as ReactPointerEvent } from 'react';
import dynamic from 'next/dynamic';
import { setToken } from '@/lib/authApi';
import { agentApi, chatApi } from '@/lib/api';
import { useVTuberStore } from '@/store/useVTuberStore';
import { getAudioManager } from '@/lib/audioManager';
import { parseEmotion } from '@/components/chat';

// Browser-only (pixi.js + Spine/Live2D runtime) — never SSR.
const AvatarCanvas = dynamic(() => import('@/components/avatar/AvatarCanvas'), { ssr: false });
const VTuberChatPanel = dynamic(() => import('@/components/live2d/VTuberChatPanel'), { ssr: false });
// Voice + screen DRIVERS live ONLY here (the avatar window), so audio plays once.
// Mounted hidden (off-screen) — they run getUserMedia / getDisplayMedia / TTS
// based on store state; the visible compact bar below toggles that same state.
const STTControls = dynamic(() => import('@/components/live2d/STTControls'), { ssr: false });
const PushToTalkDriver = dynamic(() => import('@/components/live2d/PushToTalkDriver'), { ssr: false });
const RealtimeVoiceDriver = dynamic(() => import('@/components/live2d/RealtimeVoiceDriver'), { ssr: false });
const RealtimeCaption = dynamic(() => import('@/components/live2d/RealtimeCaption'), { ssr: false });
const ConnectorBridgeClient = dynamic(() => import('@/components/live2d/ConnectorBridgeClient'), { ssr: false });
const ScreenObservationControls = dynamic(
  () => import('@/components/live2d/ScreenObservationControls'),
  { ssr: false },
);
// Visual-novel-style dialogue box pinned to the bottom of the avatar area.
const AvatarSubtitle = dynamic(() => import('@/components/live2d/AvatarSubtitle'), { ssr: false });

/** The locked-state chip, rendered in its OWN connector window.
 *
 * A locked avatar must let clicks reach the desktop — on EVERY platform.
 * That means the avatar window has to be input-transparent, which would
 * also swallow this control (Linux cannot forward events into such a
 * window, and hit-testing the cursor from the main process was measured
 * not to work there). Giving the chip its own always-interactive window
 * removes the conflict entirely instead of trading one broken side for
 * the other.
 *
 * It carries NO shared state on purpose: the capability toggles live in
 * the avatar window's store and stay there, so this window only needs to
 * send three intents.
 */
function LockedChip() {
  useEffect(() => {
    document.documentElement.style.background = 'transparent';
    document.body.style.background = 'transparent';
    const report = () => {
      const el = document.getElementById('geny-chip');
      const r = el?.getBoundingClientRect();
      if (r && r.width > 0) {
        window.connector?.windowControl.chipSize?.(Math.ceil(r.width), Math.ceil(r.height));
      }
    };
    report();
    const t = setInterval(report, 1000);
    return () => clearInterval(t);
  }, []);

  const onDrag = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button')) return;
    e.preventDefault();
    const onMove = (ev: MouseEvent) => window.connector?.windowControl.moveBy(ev.movementX, ev.movementY);
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      window.connector?.windowControl.moveEnd?.();
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  return (
    <div id="geny-chip" style={{ ...LOCK_ONLY, cursor: 'move' }} onMouseDown={onDrag}>
      <button type="button" onClick={() => window.connector?.windowControl.openControl()} title="채팅 창 열기" style={ICON_BTN}>
        <ChatIcon />
      </button>
      <button type="button" onClick={() => window.connector?.windowControl.openSettings()} title="설정 창 열기" style={ICON_BTN}>
        <GearIcon />
      </button>
      <button type="button" onClick={() => window.connector?.windowControl.setLocked?.(false)} title="잠금 해제" style={ICON_BTN}>
        <LockIcon open={false} />
      </button>
    </div>
  );
}

/** Bottom pixels the chip window covers, used until main reports the real
 *  figure (connectors older than the `overlay:chip-inset` channel never
 *  will). Mirrors main's own default chip box: 40px tall, 6px margin at
 *  each end. */
const FALLBACK_CHIP_INSET = 52;

/** Route entry: the connector opens this same URL twice — once as the
 *  avatar window, once (with ?chip=1) as the small always-clickable
 *  control window that survives the avatar going input-transparent. */
export default function OverlayRoute() {
  const [chip] = useState(
    () => typeof window !== 'undefined' && new URLSearchParams(location.search).get('chip') === '1',
  );
  return chip ? <LockedChip /> : <AvatarOverlay />;
}

function AvatarOverlay() {
  const [resolved, setResolved] = useState<{ sid: string; rid: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Locked (default): the avatar is click-through + fixed (no move/resize); only
  // the control bar is interactive. Unlocked: whole window draggable to reposition.
  const [locked, setLocked] = useState(true);
  // Pixels of this window's bottom edge that the chip window occupies.
  // -1 = main has not told us (old connector, or plain browser).
  const [chipInset, setChipInset] = useState(-1);
  // Push-to-talk (global hotkey toggles this). Tap on → mic listens; tapping
  // again (or the same hotkey) toggles off. On the down-edge we also barge in.
  const [pttActive, setPttActive] = useState(false);
  // Bottom dialogue-box subtitle (default ON; toggled in the connector settings,
  // arrives via overlayTuning.subtitlesEnabled).
  const [subtitlesEnabled, setSubtitlesEnabled] = useState(true);
  // Subtitle typewriter pace: ms per character (default 100 = one char / 0.1s).
  const [subtitleCharMs, setSubtitleCharMs] = useState(100);

  const fetchModels = useVTuberStore((s) => s.fetchModels);
  const fetchAssignment = useVTuberStore((s) => s.fetchAssignment);
  const subscribeAvatar = useVTuberStore((s) => s.subscribeAvatar);
  const unsubscribeAvatar = useVTuberStore((s) => s.unsubscribeAvatar);
  const assignedModel = useVTuberStore((s) => (resolved ? s.assignments[resolved.sid] : undefined));

  // Compact control state (the bar's toggles read/drive the same store the
  // hidden driver components use).
  const ttsEnabled = useVTuberStore((s) => s.ttsEnabled);
  const sttEnabled = useVTuberStore((s) => s.sttEnabled);
  const screenOn = useVTuberStore((s) => s.screenObservationEnabled);
  const toggleTTS = useVTuberStore((s) => s.toggleTTS);
  const toggleSTT = useVTuberStore((s) => s.toggleSTT);
  const toggleScreen = useVTuberStore((s) => s.toggleScreenObservation);
  const realtimeOn = useVTuberStore((s) => s.realtimeVoiceEnabled);
  const toggleRealtime = useVTuberStore((s) => s.toggleRealtimeVoice);
  const captionsOn = useVTuberStore((s) => s.realtimePartialsEnabled);
  const setCaptionsOn = useVTuberStore((s) => s.setRealtimePartialsEnabled);

  // 1) token + transparency + resolve the target session (once).
  useEffect(() => {
    // The desktop overlay window is transparent; globals.css paints an opaque
    // body, so clear it at runtime to composite onto the desktop.
    document.documentElement.style.background = 'transparent';
    document.body.style.background = 'transparent';

    const qs = new URLSearchParams(window.location.search);
    const token = qs.get('token');
    if (token) setToken(token);
    const wantSession = qs.get('session');
    const wantRoom = qs.get('room');

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    // Poll until a session exists, so the avatar self-heals when one is created
    // on the server (no connector restart needed).
    const attempt = async () => {
      if (cancelled) return;
      try {
        const sessions = await agentApi.list();
        // Prefer the requested session, but if it's missing (a stale/deleted id
        // saved from a prior run) fall back to auto-detecting a VTuber session,
        // so the overlay SELF-HEALS instead of waiting forever on a dead id.
        // Never fall back to a non-VTuber (e.g. worker) session — it has no
        // avatar/model to render.
        const target =
          (wantSession && sessions.find((s) => s.session_id === wantSession)) ||
          sessions.find((s) => s.role === 'vtuber') ||
          null;
        if (target) {
          if (!cancelled) {
            setError(null);
            setResolved({ sid: target.session_id, rid: wantRoom ?? target.chat_room_id ?? null });
          }
          return; // resolved — stop polling
        }
        if (!cancelled) {
          setError('VTuber 세션을 기다리는 중…\n서버에서 세션을 만들면 자동으로 떠요.');
          timer = setTimeout(attempt, 6000);
        }
      } catch (e) {
        if (!cancelled) {
          setError(`세션 연결 재시도 중…\n(${(e as Error).message})`);
          timer = setTimeout(attempt, 6000);
        }
      }
    };
    attempt();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  // 2) load models + this session's assignment.
  useEffect(() => {
    if (!resolved) return;
    fetchModels();
    fetchAssignment(resolved.sid);
  }, [resolved, fetchModels, fetchAssignment]);

  // 3) subscribe to avatar-state once a model is assigned (mirrors VTuberPanel).
  useEffect(() => {
    if (!resolved || !assignedModel) return;
    subscribeAvatar(resolved.sid);
    return () => unsubscribeAvatar(resolved.sid);
  }, [resolved, assignedModel, subscribeAvatar, unsubscribeAvatar]);

  // Position/view reset (settings → 위치 초기화): main moved the window back to
  // default; here we clear the saved pan/zoom and reload so the avatar returns to
  // its default framing (a fresh Live2D init with no restored view).
  useEffect(() => {
    const off = window.connector?.windowControl.onResetView?.(() => {
      try {
        for (let i = localStorage.length - 1; i >= 0; i--) {
          const k = localStorage.key(i);
          if (k && k.startsWith('geny_overlay_view_')) localStorage.removeItem(k);
        }
      } catch { /* ignore */ }
      window.location.reload();
    });
    return () => off?.();
  }, []);

  // Apply the lock state to the OS window. Locked → click-through (the avatar
  // ignores the mouse; only the control bar, via hover below, re-enables input).
  // Unlocked → the whole window captures input so it can be dragged to reposition.
  useEffect(() => {
    window.connector?.windowControl.setClickThrough(locked);
  }, [locked]);

  // The chip window is a separate window, so unlocking happens THERE.
  // Main relays it back here — without this the avatar would stay
  // input-transparent while its own UI believed it was unlocked.
  useEffect(() => {
    const off = window.connector?.windowControl.onSetLocked?.((v: boolean) => setLocked(v));
    return () => off?.();
  }, []);

  // How much of this window's bottom the chip window is covering.
  //
  // The chip is a separate always-on-top window parked over the bottom
  // centre of the avatar — exactly where the subtitle bubble and the
  // hands-free caption render. Nothing here can see another window, so
  // the buttons sat on top of the last line of speech. Main knows both
  // rectangles and publishes the reserved height; everything anchored to
  // the bottom lifts by it. 0 while the chip is hidden, so the unlocked
  // layout is unchanged.
  useEffect(() => {
    const off = window.connector?.windowControl.onChipInset?.((px: number) =>
      setChipInset(Number.isFinite(px) ? Math.max(0, px) : 0),
    );
    // The page mounts long after the chip's last visibility change, and
    // remounts on every reload — ask rather than wait for the next move.
    window.connector?.windowControl.requestChipInset?.();
    return () => off?.();
  }, []);

  // A connector that predates `onChipInset` still parks its chip over the
  // bottom of this window, so falling back to 0 would leave the overlap
  // exactly as it was. The chip is three fixed icons — its size is
  // stable — so the size it is created at is a safe reservation until
  // main reports the real number. Only while locked: unlocked, the chip
  // is hidden and the bar sits in normal flow.
  const bottomInset =
    chipInset >= 0 ? chipInset : locked ? FALLBACK_CHIP_INSET : 0;

  // Tell the connector which rectangle must stay clickable while the avatar
  // is click-through. Linux cannot forward events into a click-through
  // window, so hover-to-unlock is impossible there and the lock used to
  // swallow this very bar — the user could see the unlock button and not
  // press it. Main hit-tests the cursor against this instead.
  //
  // Re-reported on every layout change AND on a slow interval: the bar
  // grows and shrinks with its toggles, and a stale rectangle is a button
  // that stops responding.
  const barRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const report = () => {
      const api = window.connector?.windowControl;
      if (!api?.setInteractiveRects) return;
      const r = barRef.current?.getBoundingClientRect();
      api.setInteractiveRects(
        r && r.width > 0
          ? [{ x: Math.floor(r.x) - 4, y: Math.floor(r.y) - 4, w: Math.ceil(r.width) + 8, h: Math.ceil(r.height) + 8 }]
          : [],
      );
    };
    report();
    const t = setInterval(report, 700);
    window.addEventListener('resize', report);
    return () => {
      clearInterval(t);
      window.removeEventListener('resize', report);
    };
  }, [locked, ttsEnabled, sttEnabled, realtimeOn, captionsOn, screenOn]);

  // Capability tuning lives in the SETTINGS window (계정·음성·앱). It's a
  // different origin, so it arrives via the native config bridge: read it on
  // load and re-apply on every config:changed broadcast → the hidden TTS/STT/
  // screen drivers pick it up live (no reload).
  useEffect(() => {
    const conn = window.connector;
    if (!conn?.serverConfig) return;
    const apply = (t?: {
      ttsVolume?: number; sttSensitivity?: number; sttSilenceMs?: number;
      sttEchoCancellation?: boolean; sttNoiseSuppression?: boolean; sttAutoGain?: boolean;
      screenIntervalMs?: number; screenSourceId?: string | null;
      subtitlesEnabled?: boolean; subtitleCharMs?: number;
      audioOutputLabel?: string; audioInputLabel?: string;
    }) => {
      // Subtitle toggle + pace are independent of the other drivers and have
      // defaults, so read them even when `t` is absent.
      setSubtitlesEnabled(t?.subtitlesEnabled !== false);
      setSubtitleCharMs(typeof t?.subtitleCharMs === 'number' ? t.subtitleCharMs : 100);
      if (!t) return;
      const st = useVTuberStore.getState();
      if (typeof t.ttsVolume === 'number') st.setTTSVolume(t.ttsVolume);
      st.setSttSettings({
        ...(typeof t.sttSensitivity === 'number' ? { sttSensitivity: t.sttSensitivity } : {}),
        ...(typeof t.sttSilenceMs === 'number' ? { sttSilenceMs: t.sttSilenceMs } : {}),
        ...(typeof t.sttEchoCancellation === 'boolean' ? { sttEchoCancellation: t.sttEchoCancellation } : {}),
        ...(typeof t.sttNoiseSuppression === 'boolean' ? { sttNoiseSuppression: t.sttNoiseSuppression } : {}),
        ...(typeof t.sttAutoGain === 'boolean' ? { sttAutoGain: t.sttAutoGain } : {}),
      });
      st.setScreenSettings({
        ...(typeof t.screenIntervalMs === 'number' ? { screenIntervalMs: t.screenIntervalMs } : {}),
        ...('screenSourceId' in t ? { screenSourceId: t.screenSourceId ?? null } : {}),
      });
      // Audio device routing (TTS output + mic input), chosen by label in the
      // desktop 음성 tab → resolve + apply here (where the audio actually runs).
      if (typeof t.audioOutputLabel === 'string' || typeof t.audioInputLabel === 'string') {
        st.setAudioDevices({
          ...(typeof t.audioOutputLabel === 'string' ? { audioOutputLabel: t.audioOutputLabel } : {}),
          ...(typeof t.audioInputLabel === 'string' ? { audioInputLabel: t.audioInputLabel } : {}),
        });
      }
    };
    conn.serverConfig.get().then((c) => apply(c.overlayTuning)).catch(() => undefined);
    const off = conn.serverConfig.onChange((c) => apply(c.overlayTuning));
    return () => off?.();
  }, []);

  // Apply persisted audio-device routing on load (browser case + before any
  // tuning arrives), and start the devicechange watcher so a late VoiceMeeter
  // is picked up automatically.
  useEffect(() => {
    const st = useVTuberStore.getState();
    void import('@/lib/audioDevices').then(({ audioRouting }) => {
      audioRouting.setOutputLabel(st.audioOutputLabel || '');
      audioRouting.setInputLabel(st.audioInputLabel || '');
    });
  }, []);

  // ── the switches, reachable from every window (connector ≥0.30) ──
  // This page is where voice, microphone and screen actually run, so it owns
  // their state. It used to be the only place they could be switched — in the
  // unlocked bar, which a locked avatar (the default) does not show — so the
  // native chat window and the locked chip had no way to reach them. It now
  // tells the connector what it is doing, and does what the connector relays.
  const speakingNow = useVTuberStore((s) => (resolved ? !!s.ttsSpeaking[resolved.sid] : false));
  const hearingNow = useVTuberStore((s) => s.realtimeListening);
  useEffect(() => {
    window.connector?.avatar?.publish({
      sessionId: resolved?.sid ?? null,
      tts: ttsEnabled,
      stt: sttEnabled,
      realtime: realtimeOn,
      captions: captionsOn,
      screen: screenOn,
      ptt: pttActive,
      speaking: speakingNow,
      listening: hearingNow || pttActive,
    });
  }, [resolved, ttsEnabled, sttEnabled, realtimeOn, captionsOn, screenOn, pttActive, speakingNow, hearingNow]);

  useEffect(() => {
    const off = window.connector?.avatar?.onCommand((command) => {
      const st = useVTuberStore.getState();
      if (command.type === 'set') {
        const v = command.value;
        switch (command.key) {
          case 'tts':
            if (st.ttsEnabled !== v) st.toggleTTS();
            break;
          case 'stt':
            if (st.sttEnabled !== v) st.toggleSTT();
            break;
          case 'realtime':
            if (st.realtimeVoiceEnabled !== v) st.toggleRealtimeVoice();
            break;
          case 'captions':
            st.setRealtimePartialsEnabled(v);
            break;
          case 'screen':
            if (st.screenObservationEnabled !== v) st.toggleScreenObservation();
            break;
          case 'ptt':
            // Opening the mic while the avatar talks is a barge-in, exactly as
            // the global hotkey does it.
            if (v && resolved && st.ttsSpeaking[resolved.sid]) {
              st.stopSpeaking(resolved.sid);
              if (resolved.rid) chatApi.cancelTurn(resolved.rid).catch(() => undefined);
            }
            setPttActive(v);
            break;
        }
        return;
      }
      if (!resolved) return;
      if (command.type === 'speak') {
        const [emotion, clean] = parseEmotion(command.text);
        if (!clean.trim()) return;
        getAudioManager().ensureResumed();
        if (st.ttsSpeaking[resolved.sid]) st.stopSpeaking(resolved.sid);
        void st.speakResponse(resolved.sid, clean, emotion);
        return;
      }
      if (command.type === 'hush') st.stopSpeaking(resolved.sid);
    });
    return () => off?.();
  }, [resolved]);

  // Global push-to-talk hotkey (from the connector). On each press: if the avatar
  // is mid-TTS, barge in (cut audio + cancel the agent turn), then toggle the mic.
  useEffect(() => {
    if (!resolved) return;
    const handle = () => {
      const st = useVTuberStore.getState();
      if (st.ttsSpeaking[resolved.sid]) {
        st.stopSpeaking(resolved.sid);
        if (resolved.rid) chatApi.cancelTurn(resolved.rid).catch(() => undefined);
      }
      setPttActive((v) => !v);
    };
    const off = window.connector?.hotkeys?.onPushToTalk(handle);
    return () => off?.();
  }, [resolved]);

  // While locked, hovering the (tiny) control re-enables input so it is clickable;
  // leaving returns to click-through.
  const onBarEnter = () => {
    if (locked) window.connector?.windowControl.setClickThrough(false);
  };
  const onBarLeave = () => {
    if (locked) window.connector?.windowControl.setClickThrough(true);
  };

  // Drag the BOTTOM BAR to move the whole window. (The avatar itself keeps the
  // renderer's native pan/zoom — see AvatarCanvas interactive — so dragging the
  // avatar pans it, dragging the bar moves the window.) Clicks on buttons are
  // excluded so toggles still work.
  const onBarDrag = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('button')) return;
    // Stop the browser from starting a text selection / native drag on the
    // press — that gesture would otherwise capture the pointer and block the
    // window move.
    e.preventDefault();
    const onMove = (ev: MouseEvent) => window.connector?.windowControl.moveBy(ev.movementX, ev.movementY);
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      window.connector?.windowControl.moveEnd?.();
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  if (error) return <Loading label={error} error />;
  if (!resolved) return <Loading label="아바타 불러오는 중…" />;

  return (
    <div style={ROOT}>
      {/* Push-to-talk "listening" indicator (visual only). */}
      {pttActive && <div style={PTT_PILL}>🎙 듣는 중…</div>}

      {/* Avatar — the renderer's OWN crisp pan/zoom (drag = pan, wheel = zoom),
          active when the window is interactive (unlocked). No CSS scaling. */}
      <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        <AvatarCanvas
          sessionId={resolved.sid}
          interactive
          backgroundAlpha={0}
          className="w-full h-full"
          viewStorageKey={`geny_overlay_view_${resolved.sid}`}
        />
        {subtitlesEnabled && (
          <AvatarSubtitle
            sessionId={resolved.sid}
            charMs={subtitleCharMs}
            bottomInset={bottomInset}
          />
        )}
        {/* Live hands-free caption (what the mic is hearing, in real time). */}
        <RealtimeCaption bottomInset={bottomInset} />
      </div>

      {/* Unlocked → show a resize frame (outline + edge/corner handles) so the
          user can adjust the avatar window's width/height. Drag a handle to
          resize; the new size is saved per monitor. */}
      {!locked && <ResizeFrame />}

      {/* The bar is the MOVE handle: drag its background → move the whole window.
          Locked → just a small lock chip. Unlocked → the full compact bar. */}
      {locked ? (
        /* Nothing: while locked the avatar window is input-transparent on
           EVERY platform, so drawing controls here would show buttons that
           cannot be pressed. The connector's separate chip window carries
           them instead. */
        null
      ) : (
        <div ref={barRef} style={{ ...BAR, cursor: 'move' }} onMouseEnter={onBarEnter} onMouseLeave={onBarLeave} onMouseDown={onBarDrag}>
          {/* Drag handle (left of TTS) — a NON-button so bar-drag fires on it;
              widens the grab area and signals the window is movable. */}
          <span style={GRIP} title="드래그하여 아바타 이동">
            <GripIcon />
          </span>
          <Toggle active={ttsEnabled} onClick={toggleTTS} icon={<TtsIcon />} title="TTS — 음성 출력" />
          <Toggle active={sttEnabled} onClick={toggleSTT} icon={<MicIcon />} title="STT — 음성 입력 (마이크)" />
          <Toggle active={realtimeOn} onClick={toggleRealtime} icon={<HeadsetIcon />} title="핸즈프리 — 실시간 음성 대화 (말하면 자막이 뜨고, 멈추면 채팅으로 입력)" />
          {realtimeOn && (
            <Toggle active={captionsOn} onClick={() => setCaptionsOn(!captionsOn)} icon={<CaptionIcon />} title="자막 — 말하는 동안 인식 자막 표시" />
          )}
          <Toggle active={screenOn} onClick={toggleScreen} icon={<ScreenIcon />} title="화면 — 화면 관찰" />
          <span style={DIVIDER} />
          {/* 말풍선 — open the chat window (the control/chat window). */}
          <button type="button" onClick={() => window.connector?.windowControl.openControl()} title="채팅 창 열기" style={ICON_BTN}>
            <ChatIcon />
          </button>
          {/* 톱니바퀴 — open the settings window (계정·음성·앱: TTS/STT/화면 tuning). */}
          <button type="button" onClick={() => window.connector?.windowControl.openSettings()} title="설정 창 열기" style={ICON_BTN}>
            <GearIcon />
          </button>
          <button type="button" onClick={() => setLocked(true)} title="잠금" style={ICON_BTN}>
            <LockIcon open />
          </button>
        </div>
      )}

      {/* Hidden drivers: TTS+lip-sync (chat WS), STT recorder, screen capture,
          push-to-talk — run off-screen, toggled by the bar above via shared
          store state. The VISIBLE chat lives in the control window (chat tab). */}
      <div aria-hidden style={HIDDEN}>
        {resolved.rid && <VTuberChatPanel sessionId={resolved.sid} roomId={resolved.rid} />}
        {resolved.rid && <PushToTalkDriver sessionId={resolved.sid} roomId={resolved.rid} active={pttActive} />}
        <RealtimeVoiceDriver sessionId={resolved.sid} roomId={resolved.rid} active={realtimeOn} />
        <STTControls sessionId={resolved.sid} />
        <ScreenObservationControls sessionId={resolved.sid} />
        {/* Inverse-MCP capability bridge (desktop only; no-op in a browser). */}
        <ConnectorBridgeClient sessionId={resolved.sid} />
      </div>
    </div>
  );
}

// ── resize frame (unlocked) ──────────────────────────────────────────────────
// A dashed outline + 8 edge/corner handles overlaid on the whole window. Dragging
// a handle sends a pixel delta to main, which resizes the overlay from that edge;
// main persists the new size PER MONITOR. Only the handles capture the pointer —
// the rest is click-through so the avatar's pan/zoom still works in the middle.
const RESIZE_HANDLES: { edge: string; style: CSSProperties; cursor: string }[] = [
  { edge: 'n', style: { top: 0, left: 16, right: 16, height: 9 }, cursor: 'ns-resize' },
  { edge: 's', style: { bottom: 0, left: 16, right: 16, height: 9 }, cursor: 'ns-resize' },
  { edge: 'w', style: { left: 0, top: 16, bottom: 16, width: 9 }, cursor: 'ew-resize' },
  { edge: 'e', style: { right: 0, top: 16, bottom: 16, width: 9 }, cursor: 'ew-resize' },
  { edge: 'nw', style: { top: 0, left: 0, width: 18, height: 18 }, cursor: 'nwse-resize' },
  { edge: 'ne', style: { top: 0, right: 0, width: 18, height: 18 }, cursor: 'nesw-resize' },
  { edge: 'sw', style: { bottom: 0, left: 0, width: 18, height: 18 }, cursor: 'nesw-resize' },
  { edge: 'se', style: { bottom: 0, right: 0, width: 18, height: 18 }, cursor: 'nwse-resize' },
];
function ResizeFrame() {
  const start = (edge: string) => (e: ReactPointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const el = e.currentTarget as HTMLElement;
    try { el.setPointerCapture(e.pointerId); } catch { /* optional */ }
    const onMove = (ev: PointerEvent) =>
      window.connector?.windowControl.resizeOverlayBy?.(edge, ev.movementX, ev.movementY);
    const onUp = (ev: PointerEvent) => {
      try { el.releasePointerCapture(ev.pointerId); } catch { /* ignore */ }
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };
  return (
    <div style={RESIZE_FRAME}>
      <div style={RESIZE_LABEL}>크기 조절</div>
      {RESIZE_HANDLES.map((h) => (
        <div
          key={h.edge}
          onPointerDown={start(h.edge)}
          style={{ position: 'absolute', pointerEvents: 'auto', cursor: h.cursor, ...h.style }}
        />
      ))}
    </div>
  );
}

// ── compact bar pieces ───────────────────────────────────────────────────────
function Toggle({ active, onClick, icon, title }: { active: boolean; onClick: () => void; icon: ReactNode; title: string }) {
  return (
    <button type="button" onClick={onClick} title={title} aria-pressed={active} style={iconPill(active)}>
      {icon}
    </button>
  );
}

// ── Toggle icons (stroke style matches Chat/Gear/Lock) ──
function TtsIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <polygon points="11 5 6 9 3 9 3 15 6 15 11 19 11 5" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
    </svg>
  );
}
function MicIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10v1a7 7 0 0 0 14 0v-1" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </svg>
  );
}
function HeadsetIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M4 13v-1a8 8 0 0 1 16 0v1" />
      <rect x="2.5" y="13" width="4" height="6" rx="1.6" />
      <rect x="17.5" y="13" width="4" height="6" rx="1.6" />
      <path d="M19.5 19a3.5 3.5 0 0 1-3.5 3h-2.5" />
    </svg>
  );
}
function CaptionIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="2.5" y="5" width="19" height="14" rx="2.5" />
      <path d="M9 10.5a2.5 2.5 0 1 0 0 3M17 10.5a2.5 2.5 0 1 0 0 3" />
    </svg>
  );
}
function ScreenIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="2.5" y="3.5" width="19" height="13" rx="2" />
      <line x1="8.5" y1="20.5" x2="15.5" y2="20.5" />
      <line x1="12" y1="16.5" x2="12" y2="20.5" />
    </svg>
  );
}
function LockIcon({ open }: { open: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="11" width="18" height="11" rx="2" />
      <path d={open ? 'M7 11V7a5 5 0 0 1 9.9-1' : 'M7 11V7a5 5 0 0 1 10 0v4'} />
    </svg>
  );
}
function GripIcon() {
  return (
    <svg width="13" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      {[6, 12, 18].map((cy) => (
        <g key={cy}>
          <circle cx="9" cy={cy} r="1.7" />
          <circle cx="15" cy={cy} r="1.7" />
        </g>
      ))}
    </svg>
  );
}
function ChatIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 9.5 9.5 0 0 1-4-.9L3 21l1.9-5.5a8.38 8.38 0 0 1-.9-4 8.5 8.5 0 0 1 8.5-8.5 8.38 8.38 0 0 1 8.5 8.5z" />
    </svg>
  );
}
function GearIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

// Proper loading / error screen (the overlay window is transparent).
function Loading({ label, error }: { label: string; error?: boolean }) {
  return (
    <div style={LOAD_WRAP}>
      <style>{'@keyframes geny-spin{to{transform:rotate(360deg)}}'}</style>
      <div style={LOAD_CARD}>
        {error ? (
          <div style={{ fontSize: 22 }}>⚠️</div>
        ) : (
          <div style={SPINNER} />
        )}
        <div style={{ fontWeight: 700, fontSize: 13, letterSpacing: 0.3 }}>Geny</div>
        <div style={{ fontSize: 11, opacity: 0.65, maxWidth: 260, textAlign: 'center', lineHeight: 1.5, whiteSpace: 'pre-line' }}>{label}</div>
      </div>
    </div>
  );
}
// ── styles ───────────────────────────────────────────────────────────────────
const ROOT: CSSProperties = {
  width: '100vw', height: '100vh', overflow: 'hidden', background: 'transparent',
  display: 'flex', flexDirection: 'column',
  // The overlay is a pure control surface — nothing here is meant to be
  // selected. Without this, dragging the move-bar (or a resize handle) over any
  // label starts a native TEXT SELECTION that hijacks the pointer and stalls the
  // window move. Kill selection + the native image/text drag everywhere.
  userSelect: 'none', WebkitUserSelect: 'none',
  WebkitUserDrag: 'none',
} as CSSProperties;

const RESIZE_FRAME: CSSProperties = {
  position: 'fixed',
  inset: 0,
  pointerEvents: 'none',
  zIndex: 40,
  border: '1.5px dashed rgba(150,140,235,0.85)',
  boxShadow: 'inset 0 0 0 1px rgba(150,140,235,0.22)',
  borderRadius: 6,
};
const RESIZE_LABEL: CSSProperties = {
  position: 'absolute',
  top: 4,
  left: 0,
  right: 0,
  textAlign: 'center',
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: '0.06em',
  color: 'rgba(180,172,240,0.9)',
  textShadow: '0 1px 3px rgba(0,0,0,0.6)',
  pointerEvents: 'none',
};

const BAR: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  justifyContent: 'center',
  padding: '5px 8px',
  margin: '0 auto 8px',
  width: 'fit-content',
  maxWidth: 'calc(100% - 16px)',
  borderRadius: 999,
  background: 'rgba(18,18,24,0.82)',
  backdropFilter: 'blur(10px)',
  boxShadow: '0 4px 18px rgba(0,0,0,0.45)',
  color: '#e8e8f0',
};

const LOCK_ONLY: CSSProperties = {
  alignSelf: 'center',
  margin: '0 auto 10px',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 2,
  borderRadius: 999,
  background: 'rgba(18,18,24,0.7)',
  backdropFilter: 'blur(8px)',
  boxShadow: '0 2px 10px rgba(0,0,0,0.4)',
  color: '#cfd0e0',
  padding: '2px 4px',
};

const ICON_BTN: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 28,
  height: 28,
  border: 'none',
  background: 'transparent',
  borderRadius: 8,
  color: '#cfd0e0',
  cursor: 'pointer',
};

const DIVIDER: CSSProperties = { width: 1, height: 18, background: 'rgba(255,255,255,0.14)', margin: '0 2px' };

const GRIP: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  padding: '4px 4px',
  color: 'rgba(255,255,255,0.5)',
  cursor: 'grab',
};

const LOAD_WRAP: CSSProperties = {
  width: '100vw',
  height: '100vh',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'transparent',
};
const LOAD_CARD: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  gap: 10,
  padding: '20px 26px',
  borderRadius: 16,
  background: 'rgba(18,18,24,0.78)',
  backdropFilter: 'blur(10px)',
  boxShadow: '0 8px 30px rgba(0,0,0,0.5)',
  color: '#e8e8f0',
};
const SPINNER: CSSProperties = {
  width: 30,
  height: 30,
  borderRadius: '50%',
  border: '3px solid rgba(255,255,255,0.15)',
  borderTopColor: '#7c84ff',
  animation: 'geny-spin 0.8s linear infinite',
};

// Icon-only toggle: green fill when on, subtle when off (matches the bar).
function iconPill(active: boolean): CSSProperties {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 30,
    height: 28,
    border: 'none',
    borderRadius: 9,
    cursor: 'pointer',
    color: active ? '#0c0c10' : '#cfd0e0',
    background: active ? '#5be39a' : 'rgba(255,255,255,0.08)',
    boxShadow: active ? '0 0 8px rgba(91,227,154,0.45)' : 'none',
    transition: 'background 0.15s, color 0.15s',
  };
}
const HIDDEN: CSSProperties = { position: 'fixed', left: -99999, top: 0, width: 380, height: 380, opacity: 0, pointerEvents: 'none' };

const PTT_PILL: CSSProperties = {
  position: 'absolute',
  top: 10,
  left: '50%',
  transform: 'translateX(-50%)',
  zIndex: 5,
  padding: '4px 12px',
  borderRadius: 999,
  background: 'rgba(220,38,38,0.85)',
  color: '#fff',
  fontSize: 12,
  fontWeight: 700,
  boxShadow: '0 2px 10px rgba(0,0,0,0.4)',
  pointerEvents: 'none',
};

