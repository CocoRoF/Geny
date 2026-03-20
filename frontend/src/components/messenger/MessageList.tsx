'use client';

import { useEffect, useRef } from 'react';
import { useMessengerStore } from '@/store/useMessengerStore';
import { useAppStore } from '@/store/useAppStore';
import { useI18n } from '@/lib/i18n';
import { Bot, User, Loader2, MessageCircle } from 'lucide-react';
import type { ChatRoomMessage } from '@/types';

// ── Helpers ──

const getRoleColor = (role: string) => {
  switch (role) {
    case 'developer': return 'from-blue-500 to-cyan-500';
    case 'researcher': return 'from-amber-500 to-orange-500';
    case 'planner': return 'from-teal-500 to-emerald-500';
    default: return 'from-emerald-500 to-green-500';
  }
};

const getRoleBadgeBg = (role: string) => {
  switch (role) {
    case 'developer': return 'linear-gradient(135deg, #3b82f6, #06b6d4)';
    case 'researcher': return 'linear-gradient(135deg, #f59e0b, #ea580c)';
    case 'planner': return 'linear-gradient(135deg, #14b8a6, #10b981)';
    default: return 'linear-gradient(135deg, #10b981, #059669)';
  }
};

const formatTime = (ts: string) => {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

const formatDate = (ts: string) => {
  const d = new Date(ts);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
};

// Group messages by date
function groupByDate(messages: ChatRoomMessage[]): Array<{ date: string; messages: ChatRoomMessage[] }> {
  const groups: Array<{ date: string; messages: ChatRoomMessage[] }> = [];
  let currentDate = '';

  for (const msg of messages) {
    const dateStr = formatDate(msg.timestamp);
    if (dateStr !== currentDate) {
      currentDate = dateStr;
      groups.push({ date: dateStr, messages: [msg] });
    } else {
      groups[groups.length - 1].messages.push(msg);
    }
  }

  return groups;
}

// ── Message Components ──

function UserMessage({ msg }: { msg: ChatRoomMessage }) {
  const userName = useAppStore((s) => s.userName);
  const userTitle = useAppStore((s) => s.userTitle);
  const displayName = userName
    ? userTitle ? `${userName}(${userTitle})` : userName
    : 'You';
  return (
    <div className="flex gap-3 px-4 md:px-6 py-1.5 hover:bg-[var(--bg-hover)] transition-colors group">
      <div className="w-9 h-9 rounded-full bg-[var(--primary-color)] flex items-center justify-center shrink-0 mt-0.5 shadow-sm">
        <User size={15} className="text-white" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-0.5">
          <span className="text-[0.8125rem] font-semibold text-[var(--primary-color)]">{displayName}</span>
          <span className="text-[0.625rem] text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-opacity">
            {formatTime(msg.timestamp)}
          </span>
        </div>
        <div className="text-[0.8125rem] text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap break-words">
          {msg.content}
        </div>
      </div>
    </div>
  );
}

function AgentMessage({ msg }: { msg: ChatRoomMessage }) {
  const { setSelectedMemberId } = useMessengerStore();
  return (
    <div className="flex gap-3 px-4 md:px-6 py-1.5 hover:bg-[var(--bg-hover)] transition-colors group">
      <button
        className={`w-9 h-9 rounded-full bg-gradient-to-br ${getRoleColor(msg.role || 'worker')} flex items-center justify-center shrink-0 mt-0.5 shadow-sm border-none cursor-pointer transition-transform hover:scale-110`}
        onClick={() => msg.session_id && setSelectedMemberId(msg.session_id)}
      >
        <Bot size={15} className="text-white" />
      </button>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5 flex-wrap">
          <button
            className="text-[0.8125rem] font-semibold text-[var(--text-primary)] hover:underline bg-transparent border-none cursor-pointer p-0"
            onClick={() => msg.session_id && setSelectedMemberId(msg.session_id)}
          >
            {msg.session_name || msg.session_id?.substring(0, 8)}
          </button>
          {msg.role && (
            <span
              className="inline-flex items-center px-1.5 py-[1px] rounded text-[0.5625rem] font-bold text-white uppercase tracking-wider"
              style={{ background: getRoleBadgeBg(msg.role) }}
            >
              {msg.role}
            </span>
          )}
          <span className="text-[0.625rem] text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-opacity">
            {formatTime(msg.timestamp)}
          </span>
          {msg.duration_ms != null && (
            <span className="text-[0.5625rem] text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-opacity">
              ({(msg.duration_ms / 1000).toFixed(1)}s)
            </span>
          )}
        </div>
        <div className="text-[0.8125rem] text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap break-words">
          {msg.content}
        </div>
      </div>
    </div>
  );
}

function SystemMessage({ msg }: { msg: ChatRoomMessage }) {
  return (
    <div className="flex justify-center px-4 py-1.5">
      <span className="px-3 py-1 rounded-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-muted)] max-w-[80%] text-center">
        {msg.content}
      </span>
    </div>
  );
}

function DateDivider({ date }: { date: string }) {
  return (
    <div className="flex items-center gap-3 px-6 py-3">
      <div className="flex-1 h-px bg-[var(--border-color)]" />
      <span className="text-[0.6875rem] font-medium text-[var(--text-muted)] shrink-0">
        {date}
      </span>
      <div className="flex-1 h-px bg-[var(--border-color)]" />
    </div>
  );
}

function TypingIndicator({ name, role }: { name: string; role: string }) {
  return (
    <div className="flex gap-3 px-4 md:px-6 py-1.5">
      <div
        className={`w-9 h-9 rounded-full bg-gradient-to-br ${getRoleColor(role)} flex items-center justify-center shrink-0 mt-0.5 shadow-sm`}
      >
        <Bot size={15} className="text-white" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">{name}</span>
          {role && (
            <span
              className="inline-flex items-center px-1.5 py-[1px] rounded text-[0.5625rem] font-bold text-white uppercase tracking-wider"
              style={{ background: getRoleBadgeBg(role) }}
            >
              {role}
            </span>
          )}
        </div>
        <div className="inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-2xl bg-[var(--bg-secondary)] border border-[var(--border-color)]">
          <span className="w-2 h-2 rounded-full bg-[var(--text-muted)] animate-[typingBounce_1.4s_ease-in-out_infinite]" style={{ animationDelay: '0s' }} />
          <span className="w-2 h-2 rounded-full bg-[var(--text-muted)] animate-[typingBounce_1.4s_ease-in-out_infinite]" style={{ animationDelay: '0.2s' }} />
          <span className="w-2 h-2 rounded-full bg-[var(--text-muted)] animate-[typingBounce_1.4s_ease-in-out_infinite]" style={{ animationDelay: '0.4s' }} />
        </div>
      </div>
    </div>
  );
}

// ── Main Component ──

export default function MessageList() {
  const { messages, loadingMessages, typingAgents } = useMessengerStore();
  const { t } = useI18n();
  const endRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages / typing
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, typingAgents]);

  if (loadingMessages) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 size={28} className="animate-spin text-[var(--text-muted)]" />
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
        <div className="w-16 h-16 rounded-2xl bg-[var(--bg-tertiary)] flex items-center justify-center mb-4">
          <MessageCircle size={28} className="text-[var(--text-muted)] opacity-40" />
        </div>
        <h3 className="text-[0.9375rem] font-semibold text-[var(--text-secondary)] mb-1">
          {t('messenger.emptyTitle')}
        </h3>
        <p className="text-[0.8125rem] text-[var(--text-muted)] max-w-sm">
          {t('messenger.emptyDesc')}
        </p>
      </div>
    );
  }

  const groups = groupByDate(messages);

  return (
    <div ref={containerRef} className="flex-1 min-h-0 overflow-y-auto">
      {/* Top spacer */}
      <div className="h-4" />

      {groups.map((group, gi) => (
        <div key={gi}>
          <DateDivider date={group.date} />
          {group.messages.map(msg => {
            if (msg.type === 'user') return <UserMessage key={msg.id} msg={msg} />;
            if (msg.type === 'agent') return <AgentMessage key={msg.id} msg={msg} />;
            return <SystemMessage key={msg.id} msg={msg} />;
          })}
        </div>
      ))}

      {/* Typing indicators */}
      {typingAgents.map(agent => (
        <TypingIndicator
          key={`typing-${agent.session_id}`}
          name={agent.session_name}
          role={agent.role}
        />
      ))}

      <div ref={endRef} className="h-2" />
    </div>
  );
}
