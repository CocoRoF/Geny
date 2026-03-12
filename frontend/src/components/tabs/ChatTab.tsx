'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { chatApi } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import {
  Send, Loader2, MessageCircle, Users, Bot, User,
  Plus, ArrowLeft, Trash2, Hash, Clock,
} from 'lucide-react';
import type { ChatRoom, ChatRoomMessage } from '@/types';

// ==================== Helpers ====================

const getRoleColor = (role: string) => {
  switch (role) {
    case 'developer': return 'from-blue-500 to-cyan-500';
    case 'researcher': return 'from-amber-500 to-orange-500';
    case 'planner': return 'from-teal-500 to-emerald-500';
    default: return 'from-emerald-500 to-green-500';
  }
};

const getRoleBadgeStyle = (role: string) => {
  switch (role) {
    case 'developer': return 'background: linear-gradient(135deg, #3b82f6, #06b6d4)';
    case 'researcher': return 'background: linear-gradient(135deg, #f59e0b, #ea580c)';
    case 'planner': return 'background: linear-gradient(135deg, #14b8a6, #10b981)';
    default: return 'background: linear-gradient(135deg, #10b981, #059669)';
  }
};

const formatTime = (ts: string | Date) => {
  const d = typeof ts === 'string' ? new Date(ts) : ts;
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

const formatRelative = (ts: string) => {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
};

// ==================== Component ====================

type View = 'room-list' | 'create-room' | 'conversation';

export default function ChatTab() {
  const { sessions } = useAppStore();
  const { t } = useI18n();

  // Navigation
  const [view, setView] = useState<View>('room-list');
  const [activeRoomId, setActiveRoomId] = useState<string | null>(null);

  // Room list state
  const [rooms, setRooms] = useState<ChatRoom[]>([]);
  const [loadingRooms, setLoadingRooms] = useState(false);

  // Create room state
  const [newRoomName, setNewRoomName] = useState('');
  const [selectedSessionIds, setSelectedSessionIds] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);

  // Conversation state
  const [messages, setMessages] = useState<ChatRoomMessage[]>([]);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [activeRoom, setActiveRoom] = useState<ChatRoom | null>(null);
  const [typingAgents, setTypingAgents] = useState<Array<{ session_id: string; session_name: string; role: string }>>([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const aliveSessions = sessions.filter(s => s.status === 'running');

  // ── Load rooms ──
  const fetchRooms = useCallback(async () => {
    setLoadingRooms(true);
    try {
      const res = await chatApi.listRooms();
      setRooms(res.rooms);
    } catch {
      /* ignore */
    } finally {
      setLoadingRooms(false);
    }
  }, []);

  useEffect(() => {
    if (view === 'room-list') fetchRooms();
  }, [view, fetchRooms]);

  // ── Enter room ──
  const enterRoom = useCallback(async (roomId: string) => {
    setActiveRoomId(roomId);
    setView('conversation');
    setLoadingMessages(true);
    try {
      const [roomRes, msgsRes] = await Promise.all([
        chatApi.getRoom(roomId),
        chatApi.getRoomMessages(roomId),
      ]);
      setActiveRoom(roomRes);
      setMessages(msgsRes.messages);
    } catch {
      /* ignore */
    } finally {
      setLoadingMessages(false);
    }
  }, []);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input
  useEffect(() => {
    if (view === 'conversation') inputRef.current?.focus();
  }, [view]);

  // ── Create room ──
  const handleCreateRoom = useCallback(async () => {
    if (!newRoomName.trim() || selectedSessionIds.length === 0 || creating) return;
    setCreating(true);
    try {
      const room = await chatApi.createRoom({
        name: newRoomName.trim(),
        session_ids: selectedSessionIds,
      });
      setNewRoomName('');
      setSelectedSessionIds([]);
      enterRoom(room.id);
    } catch {
      /* ignore */
    } finally {
      setCreating(false);
    }
  }, [newRoomName, selectedSessionIds, creating, enterRoom]);

  // ── Delete room ──
  const handleDeleteRoom = useCallback(async (roomId: string) => {
    if (!confirm(t('chatTab.deleteRoomConfirm'))) return;
    try {
      await chatApi.deleteRoom(roomId);
      setRooms(prev => prev.filter(r => r.id !== roomId));
    } catch {
      /* ignore */
    }
  }, [t]);

  // ── Send message (room broadcast via SSE streaming) ──
  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || isSending || !activeRoomId) return;

    setInput('');
    setIsSending(true);

    // Optimistic user message (will be replaced by server-saved version)
    const optimisticId = `opt-${Date.now()}`;
    const optimistic: ChatRoomMessage = {
      id: optimisticId,
      type: 'user',
      content: trimmed,
      timestamp: new Date().toISOString(),
    };
    setMessages(prev => [...prev, optimistic]);

    // Populate typing agents from room members
    if (activeRoom) {
      const agents = activeRoom.session_ids
        .map(sid => {
          const s = sessions.find(sess => sess.session_id === sid);
          return s ? { session_id: sid, session_name: s.session_name || sid.substring(0, 8), role: s.role || 'worker' } : null;
        })
        .filter(Boolean) as Array<{ session_id: string; session_name: string; role: string }>;
      setTypingAgents(agents);
    }

    try {
      await chatApi.broadcastToRoom(
        activeRoomId,
        { message: trimmed },
        (eventType, eventData) => {
          const msg = eventData as ChatRoomMessage;

          switch (eventType) {
            case 'user_saved':
              // Replace optimistic user message with server-saved version
              setMessages(prev =>
                prev.map(m => m.id === optimisticId ? msg : m),
              );
              break;

            case 'agent_response':
              // Append agent message immediately & remove from typing
              setMessages(prev => [...prev, msg]);
              setTypingAgents(prev => prev.filter(a => a.session_id !== (msg as ChatRoomMessage & { session_id?: string }).session_id));
              break;

            case 'agent_skip':
              // Agent decided not relevant — remove from typing
              setTypingAgents(prev => prev.filter(a => a.session_id !== (eventData as Record<string, unknown>).session_id));
              break;

            case 'agent_error': {
              const errData = eventData as Record<string, unknown>;
              setMessages(prev => [...prev, {
                id: `err-${Date.now()}-${errData.session_id || ''}`,
                type: 'system' as const,
                content: `${errData.session_name || 'Agent'}: ${errData.error || 'Error'}`,
                timestamp: new Date().toISOString(),
              }]);
              setTypingAgents(prev => prev.filter(a => a.session_id !== errData.session_id));
              break;
            }

            case 'summary':
              // Append summary system message
              setMessages(prev => [...prev, msg]);
              break;

            case 'done':
              // Stream complete — clear all typing
              setTypingAgents([]);
              break;

            case 'error': {
              const errData2 = eventData as Record<string, unknown>;
              setMessages(prev => [...prev, {
                id: `sys-err-${Date.now()}`,
                type: 'system' as const,
                content: String(errData2.error || 'Unknown error'),
                timestamp: new Date().toISOString(),
              }]);
              break;
            }
          }
        },
      );
    } catch (e: unknown) {
      // Network/HTTP error
      setMessages(prev => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          type: 'system' as const,
          content: e instanceof Error ? e.message : t('chatTab.broadcastError'),
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsSending(false);
      setTypingAgents([]);
      inputRef.current?.focus();
    }
  }, [input, isSending, activeRoomId, activeRoom, sessions, t]);

  // ── Toggle session selection ──
  const toggleSession = (sid: string) => {
    setSelectedSessionIds(prev =>
      prev.includes(sid) ? prev.filter(id => id !== sid) : [...prev, sid],
    );
  };

  // =============== VIEWS ===============

  // ── Room List View ──
  if (view === 'room-list') {
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
            <button
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-medium cursor-pointer border-none transition-all shadow-sm"
              onClick={() => setView('create-room')}
            >
              <Plus size={14} />
              {t('chatTab.createRoom')}
            </button>
          </div>
        </div>

        {/* Room list */}
        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4 space-y-2">
          {loadingRooms && rooms.length === 0 && (
            <div className="flex justify-center py-10">
              <Loader2 size={24} className="animate-spin text-[var(--text-muted)]" />
            </div>
          )}

          {!loadingRooms && rooms.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <MessageCircle size={48} className="text-[var(--text-muted)] opacity-30 mb-4" />
              <h3 className="text-[0.9375rem] font-medium text-[var(--text-secondary)] mb-1">
                {t('chatTab.noRooms')}
              </h3>
              <p className="text-[0.8125rem] text-[var(--text-muted)] max-w-md">
                {t('chatTab.noRoomsDesc')}
              </p>
            </div>
          )}

          {rooms.map(room => (
            <div
              key={room.id}
              className="group flex items-center gap-3 px-4 py-3 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] hover:border-[var(--primary-color)] hover:bg-[rgba(59,130,246,0.04)] cursor-pointer transition-all"
              onClick={() => enterRoom(room.id)}
            >
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-500 flex items-center justify-center shrink-0 shadow-sm">
                <Hash size={18} className="text-white" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)] truncate">
                    {room.name}
                  </span>
                </div>
                <div className="flex items-center gap-3 mt-0.5">
                  <span className="flex items-center gap-1 text-[0.6875rem] text-[var(--text-muted)]">
                    <Users size={10} />
                    {room.session_ids.length} {t('chatTab.members')}
                  </span>
                  <span className="flex items-center gap-1 text-[0.6875rem] text-[var(--text-muted)]">
                    <MessageCircle size={10} />
                    {room.message_count}
                  </span>
                  <span className="flex items-center gap-1 text-[0.6875rem] text-[var(--text-muted)]">
                    <Clock size={10} />
                    {formatRelative(room.updated_at)}
                  </span>
                </div>
              </div>
              <button
                className="opacity-0 group-hover:opacity-100 p-1.5 rounded-md hover:bg-[rgba(239,68,68,0.1)] text-[var(--text-muted)] hover:text-red-500 transition-all border-none bg-transparent cursor-pointer"
                onClick={e => { e.stopPropagation(); handleDeleteRoom(room.id); }}
                title={t('chatTab.deleteRoom')}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Create Room View ──
  if (view === 'create-room') {
    return (
      <div className="flex flex-col h-full overflow-hidden">
        {/* Header */}
        <div className="shrink-0 px-6 py-3 bg-gradient-to-r from-[rgba(59,130,246,0.06)] to-transparent border-b border-[var(--border-color)]">
          <div className="flex items-center gap-3">
            <button
              className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--bg-tertiary)] border border-[var(--border-color)] hover:border-[var(--primary-color)] cursor-pointer transition-all"
              onClick={() => setView('room-list')}
            >
              <ArrowLeft size={14} className="text-[var(--text-secondary)]" />
            </button>
            <span className="text-[0.875rem] font-semibold text-[var(--text-primary)]">
              {t('chatTab.createRoom')}
            </span>
          </div>
        </div>

        {/* Form */}
        <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-5">
          {/* Room name */}
          <div>
            <label className="block text-[0.75rem] font-medium text-[var(--text-secondary)] mb-1.5">
              {t('chatTab.roomName')}
            </label>
            <input
              type="text"
              className="w-full px-3 py-2 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-primary)] text-[0.8125rem] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] transition-all"
              placeholder={t('chatTab.enterRoomName')}
              value={newRoomName}
              onChange={e => setNewRoomName(e.target.value)}
              autoFocus
            />
          </div>

          {/* Session selection */}
          <div>
            <label className="block text-[0.75rem] font-medium text-[var(--text-secondary)] mb-1.5">
              {t('chatTab.selectSessions')}
            </label>
            {sessions.length === 0 ? (
              <p className="text-[0.8125rem] text-[var(--text-muted)]">{t('chatTab.noActiveSessions')}</p>
            ) : (
              <div className="space-y-1.5">
                {sessions.map(s => {
                  const alive = s.status === 'running';
                  const selected = selectedSessionIds.includes(s.session_id);
                  return (
                    <div
                      key={s.session_id}
                      className={`flex items-center gap-3 px-3 py-2 rounded-lg border cursor-pointer transition-all ${
                        selected
                          ? 'border-[var(--primary-color)] bg-[rgba(59,130,246,0.06)]'
                          : 'border-[var(--border-color)] bg-[var(--bg-secondary)] hover:border-[var(--border-hover)]'
                      } ${!alive ? 'opacity-50' : ''}`}
                      onClick={() => toggleSession(s.session_id)}
                    >
                      <div
                        className={`w-4 h-4 rounded border-2 flex items-center justify-center transition-all ${
                          selected
                            ? 'border-[var(--primary-color)] bg-[var(--primary-color)]'
                            : 'border-[var(--border-color)]'
                        }`}
                      >
                        {selected && (
                          <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
                            <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        )}
                      </div>
                      <div
                        className={`w-6 h-6 rounded-full bg-gradient-to-br ${getRoleColor(s.role || 'worker')} flex items-center justify-center`}
                      >
                        <Bot size={12} className="text-white" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <span className="text-[0.8125rem] font-medium text-[var(--text-primary)] truncate block">
                          {s.session_name || s.session_id.substring(0, 8)}
                        </span>
                      </div>
                      <span
                        className="px-1.5 py-0.5 rounded text-[9px] font-bold text-white uppercase tracking-wider"
                        style={{ background: getRoleBadgeStyle(s.role || 'worker').replace('background: ', '') }}
                      >
                        {s.role || 'worker'}
                      </span>
                      <span className={`w-2 h-2 rounded-full ${alive ? 'bg-green-500' : 'bg-gray-400'}`} />
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Footer — create button */}
        <div className="shrink-0 px-6 py-3 border-t border-[var(--border-color)] bg-[var(--bg-primary)]">
          <button
            className="w-full py-2.5 rounded-lg bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium cursor-pointer border-none transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
            disabled={!newRoomName.trim() || selectedSessionIds.length === 0 || creating}
            onClick={handleCreateRoom}
          >
            {creating ? (
              <Loader2 size={14} className="animate-spin inline mr-2" />
            ) : null}
            {t('chatTab.createRoom')}
            {selectedSessionIds.length > 0 && ` (${selectedSessionIds.length})`}
          </button>
        </div>
      </div>
    );
  }

  // ── Conversation View ──
  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="shrink-0 px-6 py-3 bg-gradient-to-r from-[rgba(59,130,246,0.06)] to-transparent border-b border-[var(--border-color)]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--bg-tertiary)] border border-[var(--border-color)] hover:border-[var(--primary-color)] cursor-pointer transition-all"
              onClick={() => { setView('room-list'); setActiveRoomId(null); setMessages([]); setActiveRoom(null); }}
            >
              <ArrowLeft size={14} className="text-[var(--text-secondary)]" />
            </button>
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-500 flex items-center justify-center shadow-sm">
              <Hash size={16} className="text-white" />
            </div>
            <div className="flex flex-col">
              <span className="text-[0.875rem] font-semibold text-[var(--text-primary)]">
                {activeRoom?.name || '...'}
              </span>
              <span className="text-[0.6875rem] text-[var(--text-muted)]">
                {activeRoom?.session_ids.length || 0} {t('chatTab.members')}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
            <Users size={12} className="text-[var(--text-muted)]" />
            <span className="text-[0.75rem] text-[var(--text-secondary)]">
              {activeRoom?.session_ids.filter(id => aliveSessions.some(s => s.session_id === id)).length || 0} {t('chatTab.activeSessions', { count: '' }).replace(/ $/, '')}
            </span>
          </div>
        </div>
      </div>

      {/* Messages Area */}
      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4 space-y-3">
        {loadingMessages && (
          <div className="flex justify-center py-10">
            <Loader2 size={24} className="animate-spin text-[var(--text-muted)]" />
          </div>
        )}

        {!loadingMessages && messages.length === 0 && (
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
                  <div className="px-4 py-2.5 rounded-2xl rounded-tr-sm bg-[var(--primary-color)] text-white text-[0.8125rem] leading-relaxed whitespace-pre-wrap shadow-[0_2px_8px_rgba(59,130,246,0.2)]">
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
                      {msg.session_name || msg.session_id?.substring(0, 8)}
                    </span>
                    {msg.role && (
                      <span
                        className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold text-white uppercase tracking-wider"
                        style={{ background: getRoleBadgeStyle(msg.role).replace('background: ', '') }}
                      >
                        {msg.role}
                      </span>
                    )}
                    <span className="text-[0.6875rem] text-[var(--text-muted)]">
                      {formatTime(msg.timestamp)}
                    </span>
                    {msg.duration_ms && (
                      <span className="text-[0.625rem] text-[var(--text-muted)]">
                        ({(msg.duration_ms / 1000).toFixed(1)}s)
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

        {/* Typing Indicators */}
        {typingAgents.length > 0 && typingAgents.map(agent => (
          <div key={`typing-${agent.session_id}`} className="flex gap-2 items-end">
            <div
              className={`w-8 h-8 rounded-full bg-gradient-to-br ${getRoleColor(agent.role)} flex items-center justify-center shrink-0 shadow-sm`}
            >
              <Bot size={14} className="text-white" />
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[0.75rem] font-semibold text-[var(--text-primary)]">
                  {agent.session_name}
                </span>
                <span
                  className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold text-white uppercase tracking-wider"
                  style={{ background: getRoleBadgeStyle(agent.role).replace('background: ', '') }}
                >
                  {agent.role}
                </span>
              </div>
              <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-[var(--bg-secondary)] border border-[var(--border-color)] inline-flex items-center gap-1">
                <span className="typing-dot w-2 h-2 rounded-full bg-[var(--text-muted)] animate-[typingBounce_1.4s_ease-in-out_infinite]" style={{ animationDelay: '0s' }} />
                <span className="typing-dot w-2 h-2 rounded-full bg-[var(--text-muted)] animate-[typingBounce_1.4s_ease-in-out_infinite]" style={{ animationDelay: '0.2s' }} />
                <span className="typing-dot w-2 h-2 rounded-full bg-[var(--text-muted)] animate-[typingBounce_1.4s_ease-in-out_infinite]" style={{ animationDelay: '0.4s' }} />
              </div>
            </div>
          </div>
        ))}

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
        </div>
      </div>
    </div>
  );
}
