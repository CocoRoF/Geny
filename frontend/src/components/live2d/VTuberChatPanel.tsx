'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { chatApi } from '@/lib/api';
import { grabCurrentScreenAttachment } from '@/lib/screenFrameAccess';
import { resizeImageIfNeeded, isImageFile } from '@/lib/imageAttachments';
import { getChatWSManager } from '@/lib/chatWsManager';
import { getAudioManager } from '@/lib/audioManager';
import { useVTuberStore } from '@/store/useVTuberStore';
import { useCreatureStateStore } from '@/store/useCreatureStateStore';
import { useI18n } from '@/lib/i18n';
import { parseEmotion, EMOTION_COLORS, ChatMarkdown, FileChangeSummary, AgentBadge, ExecutionMeta, MessageBubble, apiPathOf, AuthedChatImage, openAuthedLink } from '@/components/chat';
import SelectionActionMenu from '@/components/chat/SelectionActionMenu';
import { ChevronDown, ChevronRight, XCircle, Paperclip, X as XIcon } from 'lucide-react';
import type { ChatRoomMessage, ChatAttachment, FileChanges, AgentProgressState, AgentLogEntry } from '@/types';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  agentRole?: string;
  sessionName?: string;
  durationMs?: number;
  fileChanges?: FileChanges[];
  attachments?: ChatAttachment[];
}

// ── Compact execution log panel for VTuber ──

function VTuberLogPanel({ logs, logCursor }: { logs: AgentLogEntry[]; logCursor?: number }) {
  const [expanded, setExpanded] = useState(false);
  if (!logs.length) return null;

  const levelColor = (level: string) => {
    switch (level) {
      case 'GRAPH': return 'text-purple-400';
      case 'TOOL': return 'text-blue-400';
      case 'TOOL_RES': return 'text-cyan-400';
      default: return 'text-[var(--text-muted)]';
    }
  };

  return (
    <div className="mt-0.5">
      <button
        className="flex items-center gap-0.5 text-[0.625rem] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors bg-transparent border-none cursor-pointer p-0"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        <span>{logCursor ?? logs.length} steps</span>
      </button>
      {expanded && (
        <div className="mt-0.5 pl-1 border-l border-[var(--border-color)] space-y-0 max-h-[120px] overflow-y-auto">
          {logs.map((log, i) => (
            <div key={i} className="flex items-start gap-1 text-[0.5625rem] font-mono leading-tight">
              <span className={`shrink-0 font-semibold ${levelColor(log.level)}`}>{log.level}</span>
              <span className="text-[var(--text-secondary)] truncate">{log.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function VTuberProgressPanel({ agents }: { agents: AgentProgressState[] }) {
  const active = agents.filter(a => a.status === 'pending' || a.status === 'executing' || a.status === 'queued');
  if (active.length === 0) return null;

  return (
    <div className="space-y-1">
      {active.map(agent => (
        <div key={agent.session_id} className="flex justify-start">
          <div className="max-w-[85%] px-3 py-1.5 rounded-2xl rounded-bl-md bg-[var(--bg-tertiary)] text-[var(--text-primary)]">
            <div className="flex items-center gap-1.5">
              <AgentBadge role={agent.role} />
              <span className="text-[0.75rem] text-[var(--text-muted)]">{agent.session_name}</span>
              {agent.thinking_preview && (
                <span className="text-[0.6875rem] text-[var(--text-muted)] truncate max-w-[120px]">
                  {agent.thinking_preview}
                </span>
              )}
              <span className="inline-flex items-center gap-0.5">
                <span className="w-1 h-1 rounded-full bg-[var(--text-muted)] animate-[typingBounce_1.4s_ease-in-out_infinite]" style={{ animationDelay: '0s' }} />
                <span className="w-1 h-1 rounded-full bg-[var(--text-muted)] animate-[typingBounce_1.4s_ease-in-out_infinite]" style={{ animationDelay: '0.2s' }} />
                <span className="w-1 h-1 rounded-full bg-[var(--text-muted)] animate-[typingBounce_1.4s_ease-in-out_infinite]" style={{ animationDelay: '0.4s' }} />
              </span>
              {typeof agent.elapsed_ms === 'number' && agent.elapsed_ms > 0 && (
                <span className="text-[0.5625rem] text-[var(--text-muted)]">
                  ({(agent.elapsed_ms / 1000).toFixed(1)}s)
                </span>
              )}
            </div>
            {agent.recent_logs && agent.recent_logs.length > 0 && (
              <VTuberLogPanel logs={agent.recent_logs} logCursor={agent.log_cursor} />
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * VTuberChatPanel — Conversational chat overlay for VTuber sessions.
 *
 * Uses the Chat Room system for DB-backed persistence:
 *  - Loads history on mount via getRoomMessages()
 *  - Sends messages via sendMessage()
 *  - Receives responses in real-time via SSE subscription
 *
 * Messages survive tab switches because they are stored in DB.
 */
export default function VTuberChatPanel({
  sessionId,
  roomId: givenRoomId,
}: {
  sessionId: string;
  /** Optional. Left out, the panel asks the server which room this session
   *  talks in — the same answer the desktop app and the phone get. */
  roomId?: string | null;
}) {
  // Where this session's conversation lives. The SERVER decides: one session,
  // one room, and every screen that asks gets the same one. A caller may pass
  // a room it already knows (the session list carries it), but nothing here
  // picks one by its own rule — that is what gave one session three
  // conversations, one per screen.
  const [resolvedRoomId, setResolvedRoomId] = useState<string | null>(givenRoomId ?? null);
  const roomId = givenRoomId ?? resolvedRoomId;
  useEffect(() => {
    if (givenRoomId || !sessionId) return;
    let cancelled = false;
    chatApi.roomForSession(sessionId)
      .then((room) => { if (!cancelled) setResolvedRoomId(room.id); })
      .catch(() => { if (!cancelled) setResolvedRoomId(null); });
    return () => { cancelled = true; };
  }, [givenRoomId, sessionId]);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [agentProgress, setAgentProgress] = useState<AgentProgressState[] | null>(null);
  const [broadcastActive, setBroadcastActive] = useState(false);
  const [streamingTexts, setStreamingTexts] = useState<Record<string, { content: string; session_name: string; role: string }>>({});
  // Pending image / file attachments for the next outgoing message.
  // Each entry is the result of POST /api/uploads (already on disk).
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachment[]>([]);
  const [uploadingCount, setUploadingCount] = useState(0);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const { t } = useI18n();
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const lastMsgIdRef = useRef<string | null>(null);
  const sseRef = useRef<{ close: () => void } | null>(null);

  // 백그라운드 탭 감지: 백그라운드에서 수신된 assistant 메시지는 TTS에 넣지 않고
  // 마지막 메시지만 기록해두었다가 탭 복귀 시 재생
  const isTabVisibleRef = useRef(typeof document !== 'undefined' ? !document.hidden : true);
  const pendingTTSRef = useRef<{ text: string; emotion: string } | null>(null);

  // TTS-fix (2026-04-26): per-msg-id dedup so duplicate WS subscriptions
  // (StrictMode double-mount, panel re-render with stale closure, etc.)
  // can't make the same message trigger TTS twice. Each message id can
  // only enter the TTS pipeline once for the lifetime of this panel.
  const ttsHandledMsgIdsRef = useRef<Set<string>>(new Set());

  // TTS store
  const ttsEnabled = useVTuberStore((s) => s.ttsEnabled);
  const ttsSpeaking = useVTuberStore((s) => s.ttsSpeaking[sessionId] ?? false);
  const speakResponse = useVTuberStore((s) => s.speakResponse);
  const stopSpeaking = useVTuberStore((s) => s.stopSpeaking);

  // 탭 visibility 감지 + 복귀 시 마지막 대기 TTS 재생
  useEffect(() => {
    const handleVisibilityChange = () => {
      const wasHidden = !isTabVisibleRef.current;
      isTabVisibleRef.current = !document.hidden;

      // 탭 복귀 시: 백그라운드에서 쌓인 마지막 메시지만 TTS 재생
      if (wasHidden && isTabVisibleRef.current) {
        const pending = pendingTTSRef.current;
        if (pending && useVTuberStore.getState().ttsEnabled) {
          pendingTTSRef.current = null;
          useVTuberStore.getState().speakResponse(sessionId, pending.text, pending.emotion);
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [sessionId]);

  // Convert ChatRoomMessage to display format
  const toDisplayMessage = useCallback((msg: ChatRoomMessage): ChatMessage => {
    const role = msg.type === 'user' ? 'user' : msg.type === 'system' ? 'system' : 'assistant';
    return {
      id: msg.id,
      role,
      content: msg.content,
      timestamp: new Date(msg.timestamp).getTime(),
      agentRole: msg.role ?? undefined,
      sessionName: msg.session_name ?? undefined,
      durationMs: msg.duration_ms ?? undefined,
      fileChanges: msg.file_changes,
      attachments: msg.attachments,
    };
  }, []);

  // Stick-to-bottom: follow new messages AND streaming/progress growth (which
  // mutate the DOM without changing the `messages` array). A MutationObserver
  // keeps the view pinned to the bottom while the user is already there; if they
  // scroll up to read history we stop yanking them down until they return.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = () =>
      el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    let stick = true;
    const onScroll = () => {
      stick = nearBottom();
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    const mo = new MutationObserver(() => {
      if (stick) el.scrollTop = el.scrollHeight;
    });
    mo.observe(el, { childList: true, subtree: true, characterData: true });
    // initial pin
    el.scrollTop = el.scrollHeight;
    return () => {
      mo.disconnect();
      el.removeEventListener('scroll', onScroll);
    };
  }, [historyLoaded]);

  // Load history + subscribe SSE when roomId is available
  useEffect(() => {
    if (!roomId) return;

    let cancelled = false;

    const init = async () => {
      try {
        const historyResp = await chatApi.getRoomMessages(roomId);
        if (cancelled) return;

        const loaded = historyResp.messages.map(toDisplayMessage);
        setMessages(loaded);
        setHistoryLoaded(true);

        if (loaded.length > 0) {
          lastMsgIdRef.current = historyResp.messages[historyResp.messages.length - 1].id;
        }

        // Subscribe via ChatRoomWSManager — roomId당 단일 WS 보장
        const unsub = getChatWSManager().subscribe(
          roomId,
          lastMsgIdRef.current,
          (eventType, eventData) => {
            if (eventType === 'message') {
              const msg = eventData as unknown as ChatRoomMessage;
              if (!msg.id) return;
              lastMsgIdRef.current = msg.id;
              const displayMsg = toDisplayMessage(msg);

              // Remove streaming bubble for this agent (final message replaces it)
              if (msg.session_id) {
                setStreamingTexts((prev) => {
                  if (!(msg.session_id! in prev)) return prev;
                  const next = { ...prev };
                  delete next[msg.session_id!];
                  return next;
                });
              }

              setMessages((prev) => {
                if (prev.some((m) => m.id === msg.id)) return prev;
                return [...prev, displayMsg];
              });

              // Drop every memory subsystem event from this turn into
              // the VTuber LOGS panel so the operator can watch
              // MemoryProvider activity (note writes, vector indexing,
              // curated promotions, knowledge searches) line by line —
              // mirrors how the TTS path already feeds the panel.
              if (msg.session_id && msg.memory_events?.length) {
                const store = useVTuberStore.getState();
                // One console row per turn so an operator looking at
                // devtools can confirm the WS payload actually carries
                // memory_events even if something downstream swallows
                // them later. Cheap — fires at most once per turn.
                console.debug(
                  '[VTuberChatPanel] received',
                  msg.memory_events.length,
                  'memory event(s) for session',
                  msg.session_id,
                  msg.memory_events.map((e) => e.event_type),
                );
                for (const ev of msg.memory_events) {
                  try {
                    store.addLog(
                      msg.session_id,
                      'info',
                      ev.source,
                      ev.message,
                      ev as unknown as Record<string, unknown>,
                    );
                  } catch (err) {
                    console.warn(
                      '[VTuberChatPanel] addLog failed for memory event',
                      ev,
                      err,
                    );
                  }
                }
              }

              // Refresh the per-session creature state snapshot once per turn
              // so the VTuberTab status badge / InfoTab Status sub-tab stay
              // current with backend mood/vitals updates.
              if (displayMsg.role === 'assistant') {
                useCreatureStateStore.getState().fetch(sessionId);
              }

              // Avatar overlay subtitle — the VTuber's OWN final dialogue closes
              // the streaming subtitle (text settled, streaming=false). Keyed on
              // session match so sub-agent messages don't hijack the box.
              if (displayMsg.role === 'assistant' && msg.session_id === sessionId) {
                const [, subFinal] = parseEmotion(displayMsg.content);
                if (subFinal.trim()) useVTuberStore.getState().setSubtitle(sessionId, subFinal, false);
              }

              // Auto TTS for assistant messages
              if (displayMsg.role === 'assistant') {
                // TTS-fix (2026-04-26): suppress auto-TTS for messages
                // the user didn't initiate. ``thinking_trigger`` /
                // ``sub_worker_reply`` / ``inbox_drain`` come from
                // background pathways (idle reflections, sub-worker
                // forwarding) — auto-speaking them queues voice on
                // top of any in-flight turn and produces the
                // "multiple voices played for one user message" bug
                // the user reported. The message still appears in the
                // chat panel; the per-message Speak button is the
                // explicit-opt-in path.
                // NOTE: 'subagent_result' is intentionally NOT suppressed —
                // an owned sub-agent's completion arrives when the VTuber is
                // idle / post-turn (never concurrent with a user turn), so the
                // VTuber should speak it. Do not add it to this list.
                const isAutoTriggered =
                  msg.source === 'thinking_trigger' ||
                  msg.source === 'sub_worker_reply' ||
                  msg.source === 'inbox_drain';
                if (isAutoTriggered) {
                  // skip auto-TTS for auto-triggered messages
                } else if (ttsHandledMsgIdsRef.current.has(msg.id)) {
                  // TTS-fix: dedup against double-fired handlers
                  // (StrictMode, stale closure rebinds, etc.)
                } else {
                  ttsHandledMsgIdsRef.current.add(msg.id);
                  const [emotion, cleanText] = parseEmotion(displayMsg.content);
                  if (cleanText.trim()) {
                    const store = useVTuberStore.getState();
                    if (store.ttsEnabled) {
                      if (isTabVisibleRef.current) {
                        // beginTTSTurn 이 handleSend 시점에 호출되어 새 턴이
                        // 이미 열렸다. live 가 한 클립이라도 뿌렸으면 finalize
                        // 가 꼬리만 flush 하고, 뿌린 게 없으면 (스트리밍 미진입
                        // / agent.session_id 불일치 / 토큰이 한꺼번에 도착해
                        // push 가 한 번도 호출 안 됨 등) finalize 가 fullText
                        // 전체를 한 클립으로 합성한다. 어느 경로든 단일 발화
                        // 보장. 절대 speakResponse 와 함께 호출하지 말 것
                        // (= 같은 텍스트 중복 발화의 원인).
                        store.finalizeTTSTurn(sessionId, cleanText, emotion);
                      } else {
                        // 백그라운드 탭: 마지막 메시지만 기록 (탭 복귀 시 재생)
                        pendingTTSRef.current = { text: cleanText, emotion };
                      }
                    }
                  }
                }
              }
            } else if (eventType === 'agent_progress') {
              const progress = eventData as unknown as { agents: AgentProgressState[] };
              setAgentProgress(progress.agents);

              // Update streaming text from agent progress
              const store = useVTuberStore.getState();
              const ttsLive = store.ttsEnabled && isTabVisibleRef.current;
              for (const agent of progress.agents) {
                if (agent.streaming_text && agent.status === 'executing') {
                  setStreamingTexts((prev) => ({
                    ...prev,
                    [agent.session_id]: {
                      content: agent.streaming_text!,
                      session_name: agent.session_name,
                      role: agent.role,
                    },
                  }));

                  // Avatar overlay subtitle — mirror THIS session's live response
                  // (independent of TTS, so the dialogue box shows even with voice
                  // off). [emotion] prefix stripped.
                  if (agent.session_id === sessionId) {
                    const [, subClean] = parseEmotion(agent.streaming_text);
                    store.setSubtitle(sessionId, subClean, true);
                  }

                  // Live chat-stream pre-emit: 완성된 문장이 있으면 즉시 TTS.
                  // streaming_text 가 비어있거나 한 글자여도 extractor 가
                  // 내부적으로 no-op 처리하므로 안전하다. parseEmotion 으로
                  // [tag] 접두부 제거.
                  //
                  // **중요**: 이 panel 의 sessionId 와 일치하는 agent 만
                  // pushStreamingText 호출. 그렇지 않으면 _liveEmittedByTurn
                  // 카운터가 다른 키 (agent.session_id) 에 적혀 turn 추적이
                  // 무너지고 finalizeTTSTurn 이 turn 에 클립이 없는 줄 알고
                  // fullText 를 한번 더 합성 → 중복 발화 발생.
                  if (ttsLive && agent.session_id === sessionId) {
                    const [liveEmotion, liveClean] = parseEmotion(agent.streaming_text);
                    if (liveClean.trim()) {
                      store.pushStreamingText(sessionId, liveClean, liveEmotion);
                    }
                  }
                }
              }
            } else if (eventType === 'broadcast_status') {
              const status = eventData as unknown as { finished: boolean };
              setBroadcastActive(!status.finished);
            } else if (eventType === 'broadcast_done') {
              setAgentProgress(null);
              setBroadcastActive(false);
              // Safety net: ensure the subtitle settles even if the final message
              // arrived without a matching session_id — the box can then dismiss.
              useVTuberStore.getState().settleSubtitle(sessionId);
            }
          },
          () => lastMsgIdRef.current,
        );

        sseRef.current = { close: unsub };
      } catch (e) {
        console.error('[VTuberChatPanel] Failed to init chat room:', e);
        setHistoryLoaded(true);
      }
    };

    init();

    return () => {
      cancelled = true;
      sseRef.current?.close();
      sseRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId]);

  // Reset state when session/room changes
  useEffect(() => {
    setMessages([]);
    setHistoryLoaded(false);
    lastMsgIdRef.current = null;
  }, [sessionId, roomId]);

  // Core send — takes the message text explicitly (not from the input state) so
  // it can be driven both by the in-app composer and by an external trigger
  // (the desktop connector's global quick-chat hotkey).
  const sendText = useCallback(async (rawText: string, extraAttachments?: ChatAttachment[]) => {
    const text = rawText.trim();
    const hasAttachments = pendingAttachments.length > 0 || (extraAttachments?.length ?? 0) > 0;
    if ((!text && !hasAttachments) || sending || !roomId) return;
    if (uploadingCount > 0) return;  // wait for in-flight uploads

    // iOS WebKit: 채팅 전송은 user gesture이므로 이 시점에 AudioContext를 활성화.
    // ttsEnabled가 기본 true인 경우 toggleTTS()가 호출되지 않으므로,
    // 채팅 전송 시점에서 오디오를 언락해야 이후 auto-TTS가 작동한다.
    if (useVTuberStore.getState().ttsEnabled) {
      getAudioManager().ensureResumed();
      // Live chat-stream pre-emit: 새 턴 시작을 TTS 파이프라인에 알림.
      // 이전 턴의 잔여 클립이 있으면 overlap 방지를 위해 폐기된다.
      useVTuberStore.getState().beginTTSTurn(sessionId);
    }

    const attachmentsToSend = [...pendingAttachments, ...(extraAttachments ?? [])];
    setPendingAttachments([]);
    setAttachmentError(null);
    setSending(true);

    try {
      // When screen observation is ON, attach the current frame so the
      // avatar sees the screen as you talk (OLV turn-attach). No-op in
      // windows without a live stream (e.g. the /connector chat window) —
      // those rely on the ambient observation + memory recall instead.
      if (useVTuberStore.getState().screenObservationEnabled) {
        const screen = await grabCurrentScreenAttachment();
        if (screen) attachmentsToSend.push(screen);
      }

      const resp = await chatApi.sendMessage(roomId, {
        message: text,
        attachments: attachmentsToSend.length > 0 ? attachmentsToSend : undefined,
      });

      if (resp.user_message) {
        const userMsg = toDisplayMessage(resp.user_message);
        lastMsgIdRef.current = resp.user_message.id;
        setMessages((prev) => {
          if (prev.some((m) => m.id === resp.user_message.id)) return prev;
          return [...prev, userMsg];
        });
      }
    } catch {
      const errorMsg: ChatMessage = {
        id: `e-${Date.now()}`,
        role: 'assistant',
        content: `[neutral] ${t('vtuberChat.errorMessage')}`,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }, [sending, roomId, toDisplayMessage, pendingAttachments, uploadingCount, sessionId, t]);

  const handleSend = useCallback(() => {
    const hasAttachments = pendingAttachments.length > 0;
    if ((!input.trim() && !hasAttachments) || sending || !roomId || uploadingCount > 0) return;
    const text = input;
    setInput('');
    void sendText(text);
  }, [input, sending, roomId, uploadingCount, pendingAttachments, sendText]);

  // Desktop connector: the global-hotkey quick-chat bar relays its text here, so
  // a message typed in the floating bar travels the SAME path as the in-app
  // composer — the VTuber answers (avatar TTS + reply) exactly as usual.
  useEffect(() => {
    const onQuickSend = window.connector?.messaging?.onQuickSend;
    if (!onQuickSend) return;
    type QuickPayload =
      | string
      | { text: string; images?: Array<{ name: string; type: string; dataUrl: string }> };
    const dispose = onQuickSend((payload: QuickPayload) => {
      void (async () => {
        // Legacy bars relay a bare string; current ones send {text, images}.
        const { text, images } =
          typeof payload === 'string' ? { text: payload, images: undefined } : payload;
        let uploaded: ChatAttachment[] = [];
        if (images?.length) {
          try {
            // data URL → File, then the SAME prepare+upload path as the in-app
            // composer (client-side image resize + server caps stay unified).
            const files = await Promise.all(
              images.map(async (img) => {
                const blob = await (await fetch(img.dataUrl)).blob();
                return new File([blob], img.name || 'pasted.png', {
                  type: img.type || blob.type || 'image/png',
                });
              })
            );
            const prepared = await Promise.all(
              files.map((f) => (isImageFile(f) ? resizeImageIfNeeded(f) : Promise.resolve(f)))
            );
            uploaded = await chatApi.uploadAttachments(prepared);
          } catch (e) {
            setAttachmentError(e instanceof Error ? e.message : String(e));
            if (!text.trim()) return; // nothing sendable — surface the error only
          }
        }
        await sendText(text, uploaded.length ? uploaded : undefined);
      })();
    });
    return () => dispose?.();
  }, [sendText]);

  // ── Attachment helpers ────────────────────────────────────────────
  const MAX_ATTACHMENTS = 8;
  const MAX_FILE_BYTES = 10 * 1024 * 1024;
  const MAX_DOCUMENT_BYTES = 50 * 1024 * 1024; // office/pdf get the larger backend cap

  const addFiles = useCallback(async (files: File[]) => {
    if (!files.length) return;
    setAttachmentError(null);

    const remaining = MAX_ATTACHMENTS - pendingAttachments.length;
    const accepted = files.slice(0, Math.max(0, remaining));
    if (accepted.length < files.length) {
      setAttachmentError(t('vtuberChat.attachmentLimit') ?? `Up to ${MAX_ATTACHMENTS} attachments per message.`);
    }
    if (accepted.length === 0) return;

    setUploadingCount((c) => c + accepted.length);
    try {
      // Resize images on the client side before uploading. Non-image
      // files pass through untouched (resizeImageIfNeeded is a no-op).
      const prepared = await Promise.all(
        accepted.map(async (f) => {
          if (f.size > (/\.(docx|xlsx|pptx|pdf|wav|mp3|m4a|ogg|oga|webm|flac)$/i.test(f.name) ? MAX_DOCUMENT_BYTES : MAX_FILE_BYTES) && !isImageFile(f)) {
            throw new Error(`${f.name}: file too large (>10 MiB)`);
          }
          return isImageFile(f) ? resizeImageIfNeeded(f) : f;
        })
      );
      // Final guard after resize.
      for (const f of prepared) {
        if (f.size > (/\.(docx|xlsx|pptx|pdf|wav|mp3|m4a|ogg|oga|webm|flac)$/i.test(f.name) ? MAX_DOCUMENT_BYTES : MAX_FILE_BYTES)) {
          throw new Error(`${f.name}: still too large after resize`);
        }
      }
      const uploaded = await chatApi.uploadAttachments(prepared);
      setPendingAttachments((prev) => [...prev, ...uploaded].slice(0, MAX_ATTACHMENTS));
    } catch (e) {
      setAttachmentError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploadingCount((c) => Math.max(0, c - accepted.length));
    }
  }, [pendingAttachments.length, t]);

  const removeAttachment = useCallback((idx: number) => {
    setPendingAttachments((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length) void addFiles(files);
    // Reset so the same file can be picked again later.
    if (e.target) e.target.value = '';
  }, [addFiles]);

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files: File[] = [];
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.kind === 'file') {
        const f = it.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length) {
      e.preventDefault();
      void addFiles(files);
    }
  }, [addFiles]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    if (!e.dataTransfer.types.includes('Files')) return;
    e.preventDefault();
    setDragActive(true);
  }, []);
  const handleDragLeave = useCallback((e: React.DragEvent) => {
    // Only reset when leaving the panel boundary (relatedTarget outside).
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setDragActive(false);
  }, []);
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length) void addFiles(files);
  }, [addFiles]);

  const handleCancelBroadcast = useCallback(async () => {
    if (!roomId) return;
    try {
      await chatApi.cancelTurn(roomId);
    } catch (e) {
      console.error('[VTuberChatPanel] Failed to cancel broadcast:', e);
    }
  }, [roomId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Strip emotion tag for display, return [emotion, cleanText]
  const parseMessage = (content: string): [string | null, string] => {
    const [emo, clean] = parseEmotion(content);
    return emo === 'neutral' && !content.startsWith('[neutral]') ? [null, content] : [emo, clean];
  };

  // No chat room available yet
  if (!roomId) {
    return (
      <div className="flex flex-col h-full items-center justify-center text-[var(--text-muted)] text-sm opacity-60">
        {t('vtuberChat.preparingRoom')}
      </div>
    );
  }

  return (
    <div
      className="flex flex-col h-full relative"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {dragActive && (
        <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-[var(--primary-color)]/10 border-2 border-dashed border-[var(--primary-color)] rounded-md">
          <span className="text-[0.875rem] font-medium text-[var(--primary-color)]">
            {t('vtuberChat.dropToAttach') ?? 'Drop files to attach'}
          </span>
        </div>
      )}
      {/* Messages area */}
      <SelectionActionMenu
        containerRef={scrollRef}
        onAskGeny={(text) => void sendText(t('selectionMenu.askGenyTemplate', { text }))}
      />
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-2.5 min-h-0"
      >
        {historyLoaded && messages.length === 0 && (
          <div className="flex-1 flex items-center justify-center text-[var(--text-muted)] text-sm opacity-60">
            {t('vtuberChat.startConversation')}
          </div>
        )}
        {!historyLoaded && (
          <div className="flex-1 flex items-center justify-center text-[var(--text-muted)] text-sm opacity-60">
            <span className="animate-pulse">{t('vtuberChat.loadingHistory')}</span>
          </div>
        )}
        {messages.map((msg) => {
          const isUser = msg.role === 'user';
          const isSystem = msg.role === 'system';
          const [emotion, text] = isUser || isSystem ? [null, msg.content] : parseMessage(msg.content);

          // System messages (e.g. "1/1 sessions responded") — subtle inline
          if (isSystem) {
            return (
              <div key={msg.id} className="flex justify-center py-0.5">
                <span className="text-[0.6875rem] text-[var(--text-muted)] opacity-50">
                  {text}
                </span>
              </div>
            );
          }

          return (
            <div
              key={msg.id}
              className={`flex ${isUser ? 'justify-end' : 'justify-start'} group`}
            >
              <MessageBubble mode="vtuber" isUser={isUser}>
                {/* Role badge + duration for assistant */}
                {!isUser && msg.agentRole && (
                  <div className="flex items-center gap-1.5 mb-1">
                    <AgentBadge role={msg.agentRole} />
                    {msg.durationMs ? <ExecutionMeta durationMs={msg.durationMs} /> : null}
                  </div>
                )}
                {emotion && (
                  <span
                    className="text-[0.6875rem] mr-1.5 inline-flex items-center gap-1"
                    style={{ color: EMOTION_COLORS[emotion] ?? '#8b949e', opacity: 0.75 }}
                  >
                    <span
                      style={{
                        width: 5,
                        height: 5,
                        borderRadius: '50%',
                        background: EMOTION_COLORS[emotion] ?? '#8b949e',
                      }}
                    />
                    {emotion}
                  </span>
                )}
                {isUser ? (
                  <span>{text}</span>
                ) : (
                  <ChatMarkdown content={text} className="text-[0.875rem]" />
                )}
                {/* Attachments (images / files) — user uploads AND files the
                    agent delivered via SendUserFile (workspace-canvas P1). */}
                {msg.attachments && msg.attachments.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {msg.attachments.map((att, i) => {
                      // Auth-gated session-storage URLs need a Bearer fetch
                      // (no cookie in the connector; bare clicks 401).
                      const attApiPath = apiPathOf(att.url ?? undefined);
                      return att.kind === 'image' && att.url ? (
                        attApiPath ? (
                          <div key={`${att.attachment_id ?? att.url ?? i}`} className="max-w-[200px]">
                            <AuthedChatImage path={attApiPath} alt={att.name ?? 'image'} />
                          </div>
                        ) : (
                          <a
                            key={`${att.attachment_id ?? att.url ?? i}`}
                            href={att.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block"
                          >
                            <img
                              src={att.url}
                              alt={att.name ?? 'image'}
                              className="max-w-[160px] max-h-[160px] object-cover rounded-md border border-[var(--border-color)]"
                            />
                          </a>
                        )
                      ) : att.kind === 'audio' && att.url && !attApiPath ? (
                        // inline player for public-store audio (parity with
                        // the messenger); auth-gated URLs use the chip below
                        <div key={`${att.attachment_id ?? att.url ?? i}`} className="max-w-[240px]">
                          <audio src={att.url} controls className="w-full h-8" />
                          <div className="text-[0.65rem] text-[var(--text-muted)] truncate mt-0.5">{att.name}</div>
                        </div>
                      ) : (
                        <div
                          key={`${att.attachment_id ?? att.url ?? i}`}
                          className="flex items-center gap-1.5 px-2 py-1 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-md text-[0.6875rem] text-[var(--text-secondary)]"
                        >
                          <Paperclip size={12} />
                          {att.url && attApiPath ? (
                            <a
                              href={att.url}
                              onClick={(e) => { e.preventDefault(); void openAuthedLink(attApiPath); }}
                              className="underline truncate max-w-[160px] cursor-pointer"
                            >
                              {att.name ?? 'file'}
                            </a>
                          ) : att.url ? (
                            <a href={att.url} target="_blank" rel="noopener noreferrer" className="underline truncate max-w-[160px]">
                              {att.name ?? 'file'}
                            </a>
                          ) : (
                            <span className="truncate max-w-[160px]">{att.name ?? 'file'}</span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
                {/* File changes */}
                {!isUser && msg.fileChanges && msg.fileChanges.length > 0 && (
                  <div className="mt-1.5">
                    <FileChangeSummary fileChanges={msg.fileChanges} />
                  </div>
                )}
              </MessageBubble>
              {/* TTS Speak button for assistant messages */}
              {!isUser && ttsEnabled && (
                <button
                  onClick={() => {
                    // iOS WebKit: user gesture 컨텍스트에서 AudioContext 활성화 보장
                    getAudioManager().ensureResumed();
                    const [emo, clean] = parseEmotion(msg.content);
                    if (clean.trim()) {
                      if (ttsSpeaking) stopSpeaking(sessionId);
                      speakResponse(sessionId, clean, emo);
                    }
                  }}
                  className="self-center ml-1 opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity cursor-pointer"
                  title={t('tts.speakMessage') ?? 'Read aloud'}
                >
                  <svg className="w-3.5 h-3.5 text-[var(--text-muted)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M11 5L6 9H2v6h4l5 4V5z" />
                    <path d="M15.54 8.46a5 5 0 010 7.07" />
                  </svg>
                </button>
              )}
            </div>
          );
        })}
        {/* Streaming text bubbles (token-level real-time) */}
        {Object.entries(streamingTexts).map(([sid, st]) => (
          <div key={`stream-${sid}`} className="flex justify-start">
            <div className="max-w-[85%] px-3.5 py-2 rounded-2xl rounded-bl-md bg-[var(--bg-tertiary)] text-[var(--text-primary)] text-[0.875rem]">
              <div className="text-[0.625rem] text-[var(--text-muted)] mb-1 font-medium">{st.session_name}</div>
              <ChatMarkdown content={st.content} className="text-[0.875rem]" />
              <span className="animate-pulse text-[var(--text-muted)]">▍</span>
            </div>
          </div>
        ))}
        {/* Agent progress during broadcast */}
        {agentProgress && agentProgress.length > 0 && (
          <VTuberProgressPanel agents={agentProgress} />
        )}
        {/* Cancel broadcast button */}
        {broadcastActive && (
          <div className="flex justify-center py-1">
            <button
              className="flex items-center gap-1 text-[0.6875rem] text-red-400 hover:text-red-300 transition-colors bg-transparent border-none cursor-pointer p-0"
              onClick={handleCancelBroadcast}
            >
              <XCircle size={14} />
              <span>{t('vtuberChat.cancelTurn')}</span>
            </button>
          </div>
        )}
        {sending && (
          <div className="flex justify-start">
            <div className="px-3.5 py-2 rounded-2xl rounded-bl-md bg-[var(--bg-tertiary)] text-[var(--text-muted)] text-[0.875rem]">
              <span className="animate-pulse">...</span>
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="px-3 py-2.5 border-t border-[var(--border-color)] bg-[var(--bg-secondary)] shrink-0">
        {/* Pending attachment chips */}
        {(pendingAttachments.length > 0 || uploadingCount > 0 || attachmentError) && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {pendingAttachments.map((att, idx) => (
              <div
                key={`${att.attachment_id ?? att.url ?? idx}`}
                className="relative group flex items-center gap-1.5 px-1.5 py-1 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-md max-w-[160px]"
              >
                {att.kind === 'image' && att.url ? (
                  <img
                    src={att.url}
                    alt={att.name ?? 'image'}
                    className="w-8 h-8 object-cover rounded"
                  />
                ) : (
                  <div className="w-8 h-8 flex items-center justify-center rounded bg-[var(--bg-primary)]">
                    <Paperclip size={14} className="text-[var(--text-muted)]" />
                  </div>
                )}
                <span className="text-[0.6875rem] text-[var(--text-secondary)] truncate">
                  {att.name ?? att.kind}
                </span>
                <button
                  type="button"
                  className="ml-0.5 text-[var(--text-muted)] hover:text-red-400 cursor-pointer bg-transparent border-none p-0"
                  onClick={() => removeAttachment(idx)}
                  aria-label="Remove attachment"
                >
                  <XIcon size={12} />
                </button>
              </div>
            ))}
            {uploadingCount > 0 && (
              <div className="flex items-center gap-1.5 px-2 py-1 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-md text-[0.6875rem] text-[var(--text-muted)]">
                <span className="animate-pulse">{t('vtuberChat.uploading') ?? 'Uploading\u2026'}</span>
              </div>
            )}
            {attachmentError && (
              <div className="text-[0.6875rem] text-red-400">{attachmentError}</div>
            )}
          </div>
        )}
        <div className="flex items-end gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,audio/*,.pdf,.docx,.xlsx,.pptx,.csv,.md,.txt,.json,.zip,.wav,.mp3,.m4a,.ogg,.webm,.flac"
            multiple
            className="hidden"
            onChange={handleFileInputChange}
          />
          <button
            type="button"
            className="shrink-0 w-9 h-9 flex items-center justify-center rounded-full bg-[var(--bg-tertiary)] text-[var(--text-secondary)] cursor-pointer hover:text-[var(--text-primary)] disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
            onClick={() => fileInputRef.current?.click()}
            disabled={sending || pendingAttachments.length >= MAX_ATTACHMENTS}
            title={t('vtuberChat.attachFile') ?? 'Attach image'}
            aria-label="Attach image"
          >
            <Paperclip size={16} />
          </button>
          <textarea
            ref={inputRef}
            className="flex-1 resize-none px-3 py-2 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-xl text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--primary-color)] transition-colors max-h-[120px]"
            placeholder={t('vtuberChat.inputPlaceholder')}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            disabled={sending}
          />
          <button
            className="shrink-0 w-9 h-9 flex items-center justify-center rounded-full bg-[var(--primary-color)] text-white cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed transition-opacity hover:opacity-90"
            onClick={handleSend}
            disabled={sending || uploadingCount > 0 || (!input.trim() && pendingAttachments.length === 0)}
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
