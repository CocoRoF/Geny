'use client';

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { useMessengerStore } from '@/store/useMessengerStore';
import { useAppStore } from '@/store/useAppStore';
import { useI18n } from '@/lib/i18n';
import { Bot, User, Loader2, MessageCircle, Clock, ChevronDown, ChevronRight, XCircle, Paperclip } from 'lucide-react';
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso';
import SelectionActionMenu from '@/components/chat/SelectionActionMenu';
import ProcessTimeline, { type TimelineCall } from '@/components/chat/ProcessTimeline';
import dynamic from 'next/dynamic';
import type { ChatRoomMessage, AgentLogEntry, ChatAttachment } from '@/types';
import { ChatMarkdown, FileChangeSummary, AgentBadge, ExecutionMeta, getRoleColor, formatTime, formatDate, apiPathOf, AuthedChatImage, openAuthedLink } from '@/components/chat';

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

// ── Attachment rendering (shared between user + agent bubbles; also
//    reused by ChatTab for room-chat messages) ──

export function AttachmentList({ attachments }: { attachments: ChatAttachment[] }) {
  if (!attachments.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {attachments.map((att, i) => {
        const href = att.url ?? att.data;
        const key = `${att.attachment_id ?? att.url ?? i}`;
        // Session-storage attachments (/api/agents/<sid>/storage-raw/...)
        // are auth-gated: a bare <img>/<a> can't carry the Bearer token
        // (no cookie in the connector; direct clicks 401). Route those
        // through an authed blob fetch; public /static/uploads stays plain.
        const apiPath = apiPathOf(href ?? undefined);

        if (att.kind === 'image' && href) {
          if (apiPath) {
            return (
              <div key={key} className="max-w-[220px]">
                <AuthedChatImage path={apiPath} alt={att.name ?? 'image'} />
              </div>
            );
          }
          return (
            <a
              key={key}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="block"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={href}
                alt={att.name ?? 'image'}
                className="max-w-[180px] max-h-[180px] object-cover rounded-md border border-[var(--border-color)]"
              />
            </a>
          );
        }

        // Audio attachments from the public upload store get an inline
        // player (auth-gated storage paths fall through to the chip+link).
        if (att.kind === 'audio' && href && !apiPath) {
          return (
            <div key={key} className="max-w-[260px]">
              <audio src={href} controls className="w-full h-9" />
              <div className="text-[0.7rem] text-[var(--text-muted)] truncate mt-0.5">{att.name}</div>
            </div>
          );
        }

        const inner = (
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[0.75rem] text-[var(--text-secondary)] max-w-[240px]">
            <Paperclip size={12} className="text-[var(--text-muted)] shrink-0" />
            <span className="truncate">{att.name ?? att.kind}</span>
          </div>
        );

        if (href && apiPath) {
          return (
            <a
              key={key}
              href={href}
              onClick={(e) => { e.preventDefault(); void openAuthedLink(apiPath); }}
              className="no-underline cursor-pointer"
            >
              {inner}
            </a>
          );
        }
        return href ? (
          <a
            key={key}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="no-underline"
          >
            {inner}
          </a>
        ) : (
          <div key={key}>{inner}</div>
        );
      })}
    </div>
  );
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
        {msg.content && (
          <div className="text-[0.8125rem] text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap break-keep">
            {msg.content}
          </div>
        )}
        {msg.attachments && msg.attachments.length > 0 && (
          <AttachmentList attachments={msg.attachments} />
        )}
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
        {msg.attachments && msg.attachments.length > 0 && (
          <AttachmentList attachments={msg.attachments} />
        )}
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

/**
 * What an agent is doing, while it does it.
 *
 * This used to print the log: `TOOL Bash 🔧 Bash` in monospace behind an
 * "N steps" toggle. It is the same process timeline the desktop app draws
 * now, from the same model in `shared/chat/tool-view` — so a tool call is
 * described identically in both, and neither recognises a vendor by name.
 */
function AgentLogPanel({ logs }: { logs: AgentLogEntry[]; logCursor?: number }) {
  const calls = useMemo(() => foldCalls(logs), [logs]);
  if (calls.length === 0) return null;
  return <ProcessTimeline calls={calls} live />;
}

/**
 * TOOL / TOOL_RES log entries → one call each.
 *
 * Paired by `tool_id` where the server sent one, and otherwise by name onto
 * the most recent call still waiting for its result — production carries both
 * shapes, because a batch summary arrives with neither id nor name.
 */
function foldCalls(logs: AgentLogEntry[]): TimelineCall[] {
  const calls: TimelineCall[] = [];
  logs.forEach((log, i) => {
    if (log.level === 'TOOL') {
      calls.push({
        key: log.tool_id ?? `${i}:${log.tool_name ?? 'tool'}`,
        name: log.tool_name ?? 'tool',
        input: log.input_preview,
        ok: null,
      });
      return;
    }
    if (log.level !== 'TOOL_RES') return;
    const match = log.tool_id
      ? calls.find((c) => c.key === log.tool_id)
      : [...calls].reverse().find((c) =>
        c.ok === null && (!log.tool_name || c.name === log.tool_name));
    if (!match) return;
    match.ok = !log.is_error;
    match.result = log.result_preview;
    match.durationMs = log.duration_ms;
  });
  return calls;
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
              <AgentLogPanel logs={agent.recent_logs} />
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
  const { messages, loadingMessages, loadingOlderMessages, hasMoreMessages, broadcastStatus, agentProgress, loadOlderMessages, cancelBroadcast, sendMessage } = useMessengerStore();
  const { t } = useI18n();
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const listContainerRef = useRef<HTMLDivElement>(null);
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
    <div ref={listContainerRef} className="flex-1 min-h-0 flex flex-col">
      <SelectionActionMenu
        containerRef={listContainerRef}
        onAskGeny={(text) => void sendMessage(t('selectionMenu.askGenyTemplate', { text }))}
      />
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
