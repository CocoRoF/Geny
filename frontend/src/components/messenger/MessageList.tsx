'use client';

import { useEffect, useRef } from 'react';
import { useMessengerStore } from '@/store/useMessengerStore';
import { useAppStore } from '@/store/useAppStore';
import { useI18n } from '@/lib/i18n';
import { Bot, User, Loader2, MessageCircle, FileCode2, Plus, Minus } from 'lucide-react';
import dynamic from 'next/dynamic';
import type { ChatRoomMessage, FileChanges } from '@/types';

const MiniAvatar = dynamic(() => import('@/components/live2d/MiniAvatar'), { ssr: false });

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
          <span className="text-[0.625rem] text-[var(--text-muted)]">
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

function FileChangeSummary({ fileChanges }: { fileChanges: FileChanges[] }) {
  const { setFileChangeDetail } = useMessengerStore();
  const totalAdded = fileChanges.reduce((s, f) => s + f.lines_added, 0);
  const totalRemoved = fileChanges.reduce((s, f) => s + f.lines_removed, 0);

  const shortName = (fp: string) => {
    const parts = fp.replace(/\\/g, '/').split('/');
    return parts[parts.length - 1] || fp;
  };

  return (
    <button
      type="button"
      className="mt-2 w-full text-left rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors cursor-pointer p-0"
      onClick={() => setFileChangeDetail(fileChanges)}
    >
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-[var(--border-color)]">
        <FileCode2 size={12} className="text-[var(--text-muted)] shrink-0" />
        <span className="text-[0.6875rem] font-medium text-[var(--text-secondary)]">
          {fileChanges.length} file{fileChanges.length > 1 ? 's' : ''} changed
        </span>
        <span className="ml-auto flex items-center gap-2 text-[0.625rem] font-mono">
          {totalAdded > 0 && (
            <span className="flex items-center gap-0.5 text-[var(--success-color,#22c55e)]">
              <Plus size={9} />
              {totalAdded}
            </span>
          )}
          {totalRemoved > 0 && (
            <span className="flex items-center gap-0.5 text-[var(--danger-color,#ef4444)]">
              <Minus size={9} />
              {totalRemoved}
            </span>
          )}
        </span>
      </div>
      <div className="px-3 py-1.5 space-y-0.5">
        {fileChanges.map((fc, i) => (
          <div key={i} className="flex items-center gap-2 text-[0.625rem]">
            <span
              className="px-1 py-[0.5px] rounded text-[0.5rem] font-bold uppercase tracking-wider"
              style={{
                backgroundColor: fc.operation === 'create' ? 'rgba(34,197,94,0.1)' :
                  fc.operation === 'edit' || fc.operation === 'multi_edit' ? 'rgba(245,158,11,0.1)' :
                  'rgba(59,130,246,0.1)',
                color: fc.operation === 'create' ? 'var(--success-color)' :
                  fc.operation === 'edit' || fc.operation === 'multi_edit' ? 'var(--warning-color)' :
                  'var(--primary-color)',
              }}
            >
              {fc.operation === 'multi_edit' ? 'edit' : fc.operation}
            </span>
            <span className="font-mono text-[var(--text-secondary)] truncate">{shortName(fc.file_path)}</span>
            <span className="ml-auto flex items-center gap-1.5 font-mono shrink-0">
              {fc.lines_added > 0 && <span className="text-[var(--success-color,#22c55e)]">+{fc.lines_added}</span>}
              {fc.lines_removed > 0 && <span className="text-[var(--danger-color,#ef4444)]">-{fc.lines_removed}</span>}
            </span>
          </div>
        ))}
      </div>
    </button>
  );
}

function AgentMessage({ msg }: { msg: ChatRoomMessage }) {
  const { setSelectedMemberId } = useMessengerStore();
  return (
    <div className="flex gap-3 px-4 md:px-6 py-1.5 hover:bg-[var(--bg-hover)] transition-colors group">
      <button
        className="mt-0.5 border-none cursor-pointer p-0 bg-transparent transition-transform hover:scale-110"
        onClick={() => msg.session_id && setSelectedMemberId(msg.session_id)}
      >
        <MiniAvatar
          sessionId={msg.session_id || ''}
          size={36}
          fallbackGradient={getRoleColor(msg.role || 'worker')}
          fallbackContent={<Bot size={15} className="text-white" />}
          className="shadow-sm"
        />
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
          <span className="text-[0.625rem] text-[var(--text-muted)]">
            {formatTime(msg.timestamp)}
          </span>
          {typeof msg.duration_ms === 'number' && msg.duration_ms > 0 && (
            <span className="text-[0.5625rem] text-[var(--text-muted)]">
              ({(msg.duration_ms / 1000).toFixed(1)}s)
            </span>
          )}
        </div>
        <div className="text-[0.8125rem] text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap break-words">
          {msg.content}
        </div>
        {msg.file_changes && msg.file_changes.length > 0 && (
          <FileChangeSummary fileChanges={msg.file_changes} />
        )}
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

function TypingIndicator({ name, role, sessionId, thinkingPreview, elapsedMs }: { name: string; role: string; sessionId?: string; thinkingPreview?: string | null; elapsedMs?: number }) {
  return (
    <div className="flex gap-3 px-4 md:px-6 py-1.5">
      <MiniAvatar
        sessionId={sessionId || ''}
        size={36}
        fallbackGradient={getRoleColor(role)}
        fallbackContent={<Bot size={15} className="text-white" />}
        className="shadow-sm"
      />
      <div className="flex items-center gap-2 min-w-0 flex-1">
        {/* Name + Role badge */}
        <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)] shrink-0">{name}</span>
        {role && role !== 'processing' && (
          <span
            className="inline-flex items-center px-1.5 py-[1px] rounded text-[0.5625rem] font-bold text-white uppercase tracking-wider shrink-0"
            style={{ background: getRoleBadgeBg(role) }}
          >
            {role}
          </span>
        )}
        {/* Thinking preview bubble */}
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[var(--bg-secondary)] border border-[var(--border-color)] min-w-0">
          {thinkingPreview && (
            <span className="text-[0.75rem] text-[var(--text-muted)] truncate max-w-[180px]">
              {thinkingPreview}
            </span>
          )}
          <div className="flex items-center gap-1 shrink-0">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--text-muted)] animate-[typingBounce_1.4s_ease-in-out_infinite]" style={{ animationDelay: '0s' }} />
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--text-muted)] animate-[typingBounce_1.4s_ease-in-out_infinite]" style={{ animationDelay: '0.2s' }} />
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--text-muted)] animate-[typingBounce_1.4s_ease-in-out_infinite]" style={{ animationDelay: '0.4s' }} />
          </div>
          {typeof elapsedMs === 'number' && elapsedMs > 0 && (
            <span className="text-[0.6875rem] text-[var(--text-muted)] shrink-0">
              ({(elapsedMs / 1000).toFixed(1)}s)
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// Per-agent progress indicator during broadcast
function AgentProgressIndicator({ agents }: { agents: import('@/types').AgentProgressState[] }) {
  // Only show agents that are still pending or executing
  const activeAgents = agents.filter(a => a.status === 'pending' || a.status === 'executing');

  if (activeAgents.length === 0) return null;

  return (
    <div className="space-y-1">
      {activeAgents.map(agent => (
        <TypingIndicator
          key={agent.session_id}
          name={agent.session_name}
          role={agent.role}
          sessionId={agent.session_id}
          thinkingPreview={agent.thinking_preview}
          elapsedMs={agent.elapsed_ms}
        />
      ))}
    </div>
  );
}

// ── Main Component ──

export default function MessageList() {
  const { messages, loadingMessages, broadcastStatus, agentProgress } = useMessengerStore();
  const { t } = useI18n();
  const endRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages / broadcast progress
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, broadcastStatus, agentProgress]);

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

      {/* Broadcast in-progress indicator */}
      {broadcastStatus && !broadcastStatus.finished && (
        <>
          {/* Show per-agent progress if available */}
          {agentProgress && agentProgress.length > 0 ? (
            <AgentProgressIndicator agents={agentProgress} />
          ) : (
            /* Fallback: show generic counter */
            <TypingIndicator
              name={`${broadcastStatus.completed}/${broadcastStatus.total}`}
              role="processing"
            />
          )}
        </>
      )}

      <div ref={endRef} className="h-2" />
    </div>
  );
}
