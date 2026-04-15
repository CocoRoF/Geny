'use client';

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { useMessengerStore } from '@/store/useMessengerStore';
import { useAppStore } from '@/store/useAppStore';
import { useI18n } from '@/lib/i18n';
import { Bot, User, Loader2, MessageCircle, Clock, ChevronDown, ChevronRight, XCircle } from 'lucide-react';
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso';
import dynamic from 'next/dynamic';
import type { ChatRoomMessage, AgentLogEntry } from '@/types';
import { ChatMarkdown, FileChangeSummary, AgentBadge, ExecutionMeta, getRoleColor, formatTime, formatDate } from '@/components/chat';

const MiniAvatar = dynamic(() => import('@/components/live2d/MiniAvatar'), { ssr: false });

// ── Flat list item types for Virtuoso ──
type ListItem =
  | { kind: 'date'; date: string }
  | { kind: 'message'; msg: ChatRoomMessage };

function buildFlatList(messages: ChatRoomMessage[]): ListItem[] {
  const items: ListItem[] = [];
  let currentDate = '';

  for (const msg of messages) {
    const dateStr = formatDate(msg.timestamp);
    if (dateStr !== currentDate) {
      currentDate = dateStr;
      items.push({ kind: 'date', date: dateStr });
    }
    items.push({ kind: 'message', msg });
  }

  return items;
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
        <div className="text-[0.8125rem] text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap break-keep">
          {msg.content}
        </div>
      </div>
    </div>
  );
}

function AgentMessage({ msg }: { msg: ChatRoomMessage }) {
  const { setSelectedMemberId, setFileChangeDetail } = useMessengerStore();
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
          {msg.role && <AgentBadge role={msg.role} />}
          <span className="text-[0.625rem] text-[var(--text-muted)]">
            {formatTime(msg.timestamp)}
          </span>
          <ExecutionMeta durationMs={msg.duration_ms} />
        </div>
        <ChatMarkdown content={msg.content} />
        {msg.file_changes && msg.file_changes.length > 0 && (
          <FileChangeSummary fileChanges={msg.file_changes} onViewDetail={setFileChangeDetail} />
        )}
      </div>
    </div>
  );
}

function SystemMessage({ msg }: { msg: ChatRoomMessage }) {
  const meta = msg.meta;
  const isQueued = meta?.queued === true;

  return (
    <div className="flex justify-center px-4 py-1.5">
      <span className={`px-3 py-1 rounded-full border text-[0.6875rem] max-w-[80%] text-center ${
        isQueued
          ? 'bg-amber-500/10 border-amber-500/30 text-amber-600 dark:text-amber-400'
          : 'bg-[var(--bg-tertiary)] border-[var(--border-color)] text-[var(--text-muted)]'
      }`}>
        {isQueued && <Clock size={12} className="mr-1 inline text-amber-500" />}
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
        {role && role !== 'processing' && <AgentBadge role={role} className="shrink-0" />}
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

// Inline execution log viewer for a single agent
function AgentLogPanel({ logs, logCursor }: { logs: AgentLogEntry[]; logCursor?: number }) {
  const [expanded, setExpanded] = useState(false);
  if (!logs.length) return null;

  const levelColor = (level: string) => {
    switch (level) {
      case 'GRAPH': return 'text-purple-500';
      case 'TOOL': return 'text-blue-500';
      case 'TOOL_RES': return 'text-cyan-500';
      case 'INFO': return 'text-[var(--text-muted)]';
      default: return 'text-[var(--text-secondary)]';
    }
  };

  return (
    <div className="mt-1">
      <button
        className="flex items-center gap-1 text-[0.6875rem] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors bg-transparent border-none cursor-pointer p-0"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span>{logCursor ?? logs.length} steps</span>
      </button>
      {expanded && (
        <div className="mt-1 pl-1 border-l-2 border-[var(--border-color)] space-y-0.5 max-h-[200px] overflow-y-auto">
          {logs.map((log, i) => (
            <div key={i} className="flex items-start gap-1.5 text-[0.625rem] font-mono">
              <span className={`shrink-0 font-semibold ${levelColor(log.level)}`}>
                {log.level}
              </span>
              {log.node_name && (
                <span className="text-purple-400 shrink-0">{log.node_name}</span>
              )}
              {log.tool_name && (
                <span className="text-blue-400 shrink-0">{log.tool_name}</span>
              )}
              <span className="text-[var(--text-secondary)] truncate">{log.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Per-agent progress indicator during broadcast
function AgentProgressIndicator({ agents }: { agents: import('@/types').AgentProgressState[] }) {
  // Show agents that are pending, executing, or queued (waiting for current task)
  const activeAgents = agents.filter(a =>
    a.status === 'pending' || a.status === 'executing' || a.status === 'queued'
  );

  if (activeAgents.length === 0) return null;

  return (
    <div className="space-y-1">
      {activeAgents.map(agent => (
        <div key={agent.session_id}>
          <TypingIndicator
            name={agent.session_name}
            role={agent.role}
            sessionId={agent.session_id}
            thinkingPreview={agent.thinking_preview}
            elapsedMs={agent.elapsed_ms}
          />
          {agent.recent_logs && agent.recent_logs.length > 0 && (
            <div className="pl-[52px]">
              <AgentLogPanel logs={agent.recent_logs} logCursor={agent.log_cursor} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Item renderer for Virtuoso ──
function ItemRenderer({ item }: { item: ListItem }) {
  if (item.kind === 'date') {
    return <DateDivider date={item.date} />;
  }
  const msg = item.msg;
  if (msg.type === 'user') return <UserMessage msg={msg} />;
  if (msg.type === 'agent') return <AgentMessage msg={msg} />;
  return <SystemMessage msg={msg} />;
}

// ── Main Component ──

function ConnectionBanner() {
  const connectionState = useMessengerStore((s) => s.connectionState);
  const ensureWS = useMessengerStore((s) => s._ensureWS);
  const { t } = useI18n();

  if (connectionState === 'connected') return null;

  return (
    <div className={`flex items-center justify-center gap-2 px-4 py-1.5 text-[0.75rem] font-medium ${
      connectionState === 'reconnecting'
        ? 'bg-yellow-500/10 text-yellow-400'
        : 'bg-red-500/10 text-red-400'
    }`}>
      {connectionState === 'reconnecting' ? (
        <>
          <Loader2 size={12} className="animate-spin" />
          <span>{t('messenger.reconnecting') || 'Reconnecting...'}</span>
        </>
      ) : (
        <>
          <span>{t('messenger.disconnected') || 'Connection lost'}</span>
          <button
            className="underline hover:text-red-300 transition-colors bg-transparent border-none cursor-pointer p-0 text-[0.75rem]"
            onClick={ensureWS}
          >
            {t('messenger.reconnectNow') || 'Reconnect'}
          </button>
        </>
      )}
    </div>
  );
}

export default function MessageList() {
  const { messages, loadingMessages, loadingOlderMessages, hasMoreMessages, broadcastStatus, agentProgress, loadOlderMessages, cancelBroadcast } = useMessengerStore();
  const { t } = useI18n();
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const isAtBottomRef = useRef(true);

  // Build flat list for Virtuoso
  const flatItems = useMemo(() => buildFlatList(messages), [messages]);

  // Track whether user is at bottom for followOutput
  const handleAtBottomStateChange = useCallback((atBottom: boolean) => {
    isAtBottomRef.current = atBottom;
  }, []);

  // Load older messages when top is reached
  const handleStartReached = useCallback(() => {
    if (!loadingOlderMessages && hasMoreMessages) {
      loadOlderMessages();
    }
  }, [loadingOlderMessages, hasMoreMessages, loadOlderMessages]);

  // Follow output only when at bottom
  const followOutput = useCallback((isAtBottom: boolean) => {
    return isAtBottom ? 'smooth' : false;
  }, []);

  // Scroll to bottom when broadcast progress changes
  useEffect(() => {
    if (broadcastStatus && !broadcastStatus.finished && isAtBottomRef.current) {
      virtuosoRef.current?.scrollToIndex({ index: 'LAST', behavior: 'smooth' });
    }
  }, [agentProgress, broadcastStatus]);

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

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <Virtuoso
        ref={virtuosoRef}
        data={flatItems}
        startReached={handleStartReached}
        followOutput={followOutput}
        atBottomStateChange={handleAtBottomStateChange}
        atBottomThreshold={60}
        increaseViewportBy={{ top: 400, bottom: 200 }}
        itemContent={(_index, item) => <ItemRenderer item={item} />}
        components={{
          Header: () => (
            <div>
              <ConnectionBanner />
              <div className="h-4" />
              {loadingOlderMessages && (
                <div className="flex justify-center py-2">
                  <Loader2 size={16} className="animate-spin text-[var(--text-muted)]" />
                </div>
              )}
              {hasMoreMessages && !loadingOlderMessages && (
                <div className="flex justify-center py-2">
                  <button
                    className="text-[0.75rem] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors bg-transparent border border-[var(--border-color)] rounded-full px-4 py-1 cursor-pointer"
                    onClick={loadOlderMessages}
                  >
                    {t('messenger.loadEarlier') || 'Load earlier messages'}
                  </button>
                </div>
              )}
            </div>
          ),
          Footer: () => (
            <div>
              {broadcastStatus && !broadcastStatus.finished && (
                <>
                  {agentProgress && agentProgress.length > 0 ? (
                    <AgentProgressIndicator agents={agentProgress} />
                  ) : (
                    <TypingIndicator
                      name={`${broadcastStatus.completed}/${broadcastStatus.total}`}
                      role="processing"
                    />
                  )}
                  <div className="flex justify-center py-1">
                    <button
                      className="flex items-center gap-1 text-[0.6875rem] text-red-400 hover:text-red-300 transition-colors bg-transparent border-none cursor-pointer p-0"
                      onClick={cancelBroadcast}
                    >
                      <XCircle size={14} />
                      <span>{t('messenger.cancelBroadcast') || 'Cancel'}</span>
                    </button>
                  </div>
                </>
              )}
              <div className="h-2" />
            </div>
          ),
        }}
      />
    </div>
  );
}
