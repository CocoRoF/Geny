'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { chatApi } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { Send, Loader2, MessageCircle, Users, Bot, User } from 'lucide-react';
import type { ChatSessionResponse } from '@/types';

// ==================== Message Types ====================

interface ChatMessage {
  id: string;
  type: 'user' | 'agent' | 'system';
  content: string;
  timestamp: Date;
  // Agent-specific (when type === 'agent')
  sessionId?: string;
  sessionName?: string;
  role?: string;
  durationMs?: number;
}

// ==================== Component ====================

export default function ChatTab() {
  const { sessions } = useAppStore();
  const { t } = useI18n();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const aliveSessions = sessions.filter(s => s.status === 'running');

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || isSending) return;

    const userMsgId = `user-${Date.now()}`;

    // Add user message
    const userMessage: ChatMessage = {
      id: userMsgId,
      type: 'user',
      content: trimmed,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsSending(true);

    // Add system "broadcasting..." message
    const broadcastMsgId = `sys-${Date.now()}`;
    setMessages(prev => [
      ...prev,
      {
        id: broadcastMsgId,
        type: 'system',
        content: t('chatTab.broadcasting', { count: String(aliveSessions.length) }),
        timestamp: new Date(),
      },
    ]);

    try {
      const result = await chatApi.broadcast({ message: trimmed });

      // Remove broadcasting message
      setMessages(prev => prev.filter(m => m.id !== broadcastMsgId));

      // Add responses from sessions that responded
      const agentMessages: ChatMessage[] = result.responses
        .filter((r: ChatSessionResponse) => r.responded && r.output)
        .map((r: ChatSessionResponse) => ({
          id: `agent-${r.session_id}-${Date.now()}`,
          type: 'agent' as const,
          content: r.output!,
          timestamp: new Date(),
          sessionId: r.session_id,
          sessionName: r.session_name || r.session_id.substring(0, 8),
          role: r.role || 'worker',
          durationMs: r.duration_ms || undefined,
        }));

      if (agentMessages.length === 0) {
        // No one responded
        setMessages(prev => [
          ...prev,
          {
            id: `sys-noreply-${Date.now()}`,
            type: 'system',
            content: t('chatTab.noResponses'),
            timestamp: new Date(),
          },
        ]);
      } else {
        setMessages(prev => [...prev, ...agentMessages]);
      }

      // Add summary system message if multiple sessions
      if (result.total_sessions > 0) {
        setMessages(prev => [
          ...prev,
          {
            id: `sys-summary-${Date.now()}`,
            type: 'system',
            content: t('chatTab.broadcastSummary', {
              responded: String(result.responded_count),
              total: String(result.total_sessions),
              duration: String((result.total_duration_ms / 1000).toFixed(1)),
            }),
            timestamp: new Date(),
          },
        ]);
      }
    } catch (e: unknown) {
      // Remove broadcasting message
      setMessages(prev => prev.filter(m => m.id !== broadcastMsgId));

      setMessages(prev => [
        ...prev,
        {
          id: `sys-error-${Date.now()}`,
          type: 'system',
          content: e instanceof Error ? e.message : t('chatTab.broadcastError'),
          timestamp: new Date(),
        },
      ]);
    } finally {
      setIsSending(false);
      inputRef.current?.focus();
    }
  }, [input, isSending, aliveSessions.length, t]);

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const getRoleColor = (role: string) => {
    switch (role) {
      case 'manager':
        return 'from-purple-500 to-indigo-500';
      case 'developer':
        return 'from-blue-500 to-cyan-500';
      case 'researcher':
        return 'from-amber-500 to-orange-500';
      default:
        return 'from-emerald-500 to-green-500';
    }
  };

  const getRoleBadgeStyle = (role: string) => {
    switch (role) {
      case 'manager':
        return 'background: linear-gradient(135deg, #8b5cf6, #6366f1)';
      case 'developer':
        return 'background: linear-gradient(135deg, #3b82f6, #06b6d4)';
      case 'researcher':
        return 'background: linear-gradient(135deg, #f59e0b, #ea580c)';
      default:
        return 'background: linear-gradient(135deg, #10b981, #059669)';
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="shrink-0 px-6 py-3 bg-gradient-to-r from-[rgba(59,130,246,0.06)] to-transparent border-b border-[var(--border-color)]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[var(--primary-color)] flex items-center justify-center shadow-[0_0_12px_rgba(59,130,246,0.25)]">
              <MessageCircle size={16} className="text-white" />
            </div>
            <div className="flex flex-col">
              <span className="text-[0.875rem] font-semibold text-[var(--text-primary)]">
                {t('chatTab.title')}
              </span>
              <span className="text-[0.6875rem] text-[var(--text-muted)]">
                {t('chatTab.subtitle')}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
            <Users size={12} className="text-[var(--text-muted)]" />
            <span className="text-[0.75rem] text-[var(--text-secondary)]">
              {t('chatTab.activeSessions', { count: String(aliveSessions.length) })}
            </span>
          </div>
        </div>
      </div>

      {/* Messages Area */}
      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4 space-y-3">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <MessageCircle size={48} className="text-[var(--text-muted)] opacity-30 mb-4" />
            <h3 className="text-[0.9375rem] font-medium text-[var(--text-secondary)] mb-1">
              {t('chatTab.emptyTitle')}
            </h3>
            <p className="text-[0.8125rem] text-[var(--text-muted)] max-w-md">
              {t('chatTab.emptyDesc')}
            </p>
          </div>
        )}

        {messages.map(msg => {
          if (msg.type === 'user') {
            return (
              <div key={msg.id} className="flex justify-end gap-2">
                <div className="max-w-[70%] flex flex-col items-end">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[0.6875rem] text-[var(--text-muted)]">
                      {formatTime(msg.timestamp)}
                    </span>
                    <span className="text-[0.75rem] font-semibold text-[var(--primary-color)]">
                      You
                    </span>
                  </div>
                  <div className="px-4 py-2.5 rounded-2xl rounded-tr-sm bg-[var(--primary-color)] text-white text-[0.8125rem] leading-relaxed shadow-[0_2px_8px_rgba(59,130,246,0.2)]">
                    {msg.content}
                  </div>
                </div>
                <div className="w-8 h-8 rounded-full bg-[var(--primary-color)] flex items-center justify-center shrink-0 mt-5">
                  <User size={14} className="text-white" />
                </div>
              </div>
            );
          }

          if (msg.type === 'agent') {
            return (
              <div key={msg.id} className="flex gap-2">
                <div
                  className={`w-8 h-8 rounded-full bg-gradient-to-br ${getRoleColor(msg.role || 'worker')} flex items-center justify-center shrink-0 mt-5 shadow-sm`}
                >
                  <Bot size={14} className="text-white" />
                </div>
                <div className="max-w-[70%] flex flex-col">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[0.75rem] font-semibold text-[var(--text-primary)]">
                      {msg.sessionName}
                    </span>
                    <span
                      className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold text-white uppercase tracking-wider"
                      style={{ ...(msg.role ? { background: getRoleBadgeStyle(msg.role).replace('background: ', '') } : {}) }}
                    >
                      {msg.role}
                    </span>
                    <span className="text-[0.6875rem] text-[var(--text-muted)]">
                      {formatTime(msg.timestamp)}
                    </span>
                    {msg.durationMs && (
                      <span className="text-[0.625rem] text-[var(--text-muted)]">
                        ({(msg.durationMs / 1000).toFixed(1)}s)
                      </span>
                    )}
                  </div>
                  <div className="px-4 py-2.5 rounded-2xl rounded-tl-sm bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-primary)] text-[0.8125rem] leading-relaxed whitespace-pre-wrap">
                    {msg.content}
                  </div>
                </div>
              </div>
            );
          }

          // System message
          return (
            <div key={msg.id} className="flex justify-center">
              <span className="px-3 py-1 rounded-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-muted)]">
                {msg.content}
              </span>
            </div>
          );
        })}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="shrink-0 px-6 py-3 border-t border-[var(--border-color)] bg-[var(--bg-primary)]">
        <div className="relative flex items-end gap-3">
          <textarea
            ref={inputRef}
            className="flex-1 p-3 pr-12 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-xl text-[var(--text-primary)] text-[0.8125rem] font-[inherit] resize-none min-h-[44px] max-h-[120px] transition-all placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)]"
            placeholder={t('chatTab.inputPlaceholder')}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            rows={1}
            disabled={isSending}
          />
          <button
            className="absolute right-2 bottom-2 w-8 h-8 rounded-lg bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white flex items-center justify-center cursor-pointer transition-all duration-150 border-none disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
            disabled={isSending || !input.trim()}
            onClick={handleSend}
          >
            {isSending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Send size={14} />
            )}
          </button>
        </div>
        <div className="flex items-center justify-between mt-1.5">
          <span className="text-[0.625rem] text-[var(--text-muted)]">
            Enter {t('chatTab.sendHint')} · Shift+Enter {t('chatTab.newlineHint')}
          </span>
          {aliveSessions.length === 0 && (
            <span className="text-[0.625rem] text-[var(--warning-color)]">
              {t('chatTab.noActiveSessions')}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
