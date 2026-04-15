'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { chatApi } from '@/lib/api';
import { getChatWSManager } from '@/lib/chatWsManager';
import { useVTuberStore } from '@/store/useVTuberStore';
import { useI18n } from '@/lib/i18n';
import { parseEmotion, EMOTION_COLORS, ChatMarkdown, FileChangeSummary, AgentBadge, ExecutionMeta, MessageBubble } from '@/components/chat';
import { ChevronDown, ChevronRight, XCircle } from 'lucide-react';
import type { ChatRoomMessage, FileChanges, AgentProgressState, AgentLogEntry } from '@/types';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  agentRole?: string;
  sessionName?: string;
  durationMs?: number;
  fileChanges?: FileChanges[];
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
 *  - Sends messages via broadcastToRoom()
 *  - Receives responses in real-time via SSE subscription
 *
 * Messages survive tab switches because they are stored in DB.
 */
export default function VTuberChatPanel({
  sessionId,
  roomId,
}: {
  sessionId: string;
  roomId?: string | null;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [agentProgress, setAgentProgress] = useState<AgentProgressState[] | null>(null);
  const [broadcastActive, setBroadcastActive] = useState(false);
  const [streamingTexts, setStreamingTexts] = useState<Record<string, { content: string; session_name: string; role: string }>>({});
  const { t } = useI18n();
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const lastMsgIdRef = useRef<string | null>(null);
  const sseRef = useRef<{ close: () => void } | null>(null);

  // 백그라운드 탭 감지: 백그라운드에서 수신된 assistant 메시지는 TTS에 넣지 않고
  // 마지막 메시지만 기록해두었다가 탭 복귀 시 재생
  const isTabVisibleRef = useRef(typeof document !== 'undefined' ? !document.hidden : true);
  const pendingTTSRef = useRef<{ text: string; emotion: string } | null>(null);

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
    };
  }, []);

  // Auto-scroll on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

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

              // Auto TTS for assistant messages
              if (displayMsg.role === 'assistant') {
                const [emotion, cleanText] = parseEmotion(displayMsg.content);
                if (cleanText.trim()) {
                  const store = useVTuberStore.getState();
                  if (store.ttsEnabled) {
                    if (isTabVisibleRef.current) {
                      // 탭이 보이면 즉시 TTS 큐에 추가
                      store.speakResponse(sessionId, cleanText, emotion);
                    } else {
                      // 백그라운드 탭: 마지막 메시지만 기록 (탭 복귀 시 재생)
                      pendingTTSRef.current = { text: cleanText, emotion };
                    }
                  }
                }
              }
            } else if (eventType === 'agent_progress') {
              const progress = eventData as unknown as { agents: AgentProgressState[] };
              setAgentProgress(progress.agents);

              // Update streaming text from agent progress
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
                }
              }
            } else if (eventType === 'broadcast_status') {
              const status = eventData as unknown as { finished: boolean };
              setBroadcastActive(!status.finished);
            } else if (eventType === 'broadcast_done') {
              setAgentProgress(null);
              setBroadcastActive(false);
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

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || sending || !roomId) return;

    setInput('');
    setSending(true);

    try {
      const resp = await chatApi.broadcastToRoom(roomId, { message: text });

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
  }, [input, sending, roomId, toDisplayMessage]);

  const handleCancelBroadcast = useCallback(async () => {
    if (!roomId) return;
    try {
      await chatApi.cancelBroadcast(roomId);
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
    <div className="flex flex-col h-full">
      {/* Messages area */}
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
              <span>{t('messenger.cancelBroadcast')}</span>
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
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            className="flex-1 resize-none px-3 py-2 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-xl text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--primary-color)] transition-colors max-h-[120px]"
            placeholder={t('vtuberChat.inputPlaceholder')}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={sending}
          />
          <button
            className="shrink-0 w-9 h-9 flex items-center justify-center rounded-full bg-[var(--primary-color)] text-white cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed transition-opacity hover:opacity-90"
            onClick={handleSend}
            disabled={sending || !input.trim()}
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
