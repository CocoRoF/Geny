'use client';

import { useCallback, useRef, useEffect, useState, useMemo } from 'react';
import { useAppStore, type SessionData } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import {
  Square,
  Loader2,
  Terminal,
  Zap,
  Wrench,
  ChevronDown,
  ChevronRight,
  Clock,
  CheckCircle2,
  XCircle,
  ArrowDown,
  Play,
} from 'lucide-react';

// ── Level badge colours ──
const LEVEL_COLORS: Record<string, { bg: string; text: string; gutter: string }> = {
  DEBUG:    { bg: 'rgba(113,113,122,0.08)', text: '#71717a', gutter: '#71717a' },
  INFO:     { bg: 'rgba(59,130,246,0.08)',  text: '#3b82f6', gutter: '#3b82f6' },
  WARNING:  { bg: 'rgba(245,158,11,0.08)',  text: '#f59e0b', gutter: '#f59e0b' },
  ERROR:    { bg: 'rgba(239,68,68,0.10)',   text: '#ef4444', gutter: '#ef4444' },
  COMMAND:  { bg: 'rgba(16,185,129,0.08)',  text: '#10b981', gutter: '#10b981' },
  RESPONSE: { bg: 'rgba(168,85,247,0.08)',  text: '#a855f7', gutter: '#a855f7' },
  ITER:     { bg: 'rgba(251,146,60,0.08)',  text: '#fb923c', gutter: '#fb923c' },
  TOOL:     { bg: 'rgba(34,211,238,0.08)',  text: '#22d3ee', gutter: '#22d3ee' },
  TOOL_RES: { bg: 'rgba(6,182,212,0.06)',   text: '#06b6d4', gutter: '#06b6d4' },
  STREAM:   { bg: 'rgba(148,163,184,0.06)', text: '#94a3b8', gutter: '#64748b' },
  GRAPH:    { bg: 'rgba(139,92,246,0.08)',   text: '#8b5cf6', gutter: '#8b5cf6' },
};

// Primary execution log levels (shown by default)
const PRIMARY_LEVELS = new Set([
  'COMMAND', 'RESPONSE', 'ERROR', 'WARNING', 'GRAPH', 'TOOL', 'ITER',
]);

interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
  metadata?: Record<string, unknown>;
}

// ── Single log line (terminal-style) ──
function LogLine({ entry }: { entry: LogEntry }) {
  const [expanded, setExpanded] = useState(false);
  const isLong = entry.message.length > 400;
  const colors = LEVEL_COLORS[entry.level] || { bg: 'rgba(100,116,139,0.08)', text: '#64748b', gutter: '#64748b' };

  const shortTime = useMemo(() => {
    try {
      const d = new Date(entry.timestamp);
      return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return entry.timestamp.slice(11, 19);
    }
  }, [entry.timestamp]);

  const displayMsg = entry.message.replace(/^PROMPT:\s*/, '').replace(/^SUCCESS:\s*/, '').replace(/^ERROR:\s*/, '');

  return (
    <div
      className="flex gap-0 hover:bg-[var(--bg-tertiary)] transition-colors group"
      onClick={() => isLong && setExpanded(!expanded)}
      style={{ cursor: isLong ? 'pointer' : 'default' }}
    >
      {/* Gutter: colored left strip */}
      <div className="w-[3px] shrink-0 rounded-sm" style={{ backgroundColor: colors.gutter, opacity: 0.6 }} />
      {/* Content */}
      <div className="flex-1 min-w-0 py-[5px] pl-3 pr-2">
        <div className="flex items-start gap-2">
          <span className="text-[0.5625rem] text-[var(--text-muted)] font-mono tabular-nums shrink-0 opacity-50 w-[52px] pt-[1px]">
            {shortTime}
          </span>
          <span
            className="inline-flex items-center justify-center rounded px-1.5 py-[0.5px] text-[0.5rem] font-bold uppercase tracking-wider shrink-0 min-w-[40px]"
            style={{ backgroundColor: colors.bg, color: colors.text }}
          >
            {entry.level}
          </span>
          <span className={`text-[0.75rem] leading-snug min-w-0 whitespace-pre-wrap break-words ${
            entry.level === 'ERROR' || entry.level === 'WARNING'
              ? `font-medium`
              : ''
          }`} style={{ color: entry.level === 'ERROR' ? '#ef4444' : entry.level === 'WARNING' ? '#f59e0b' : 'var(--text-secondary)' }}>
            {isLong && !expanded ? (
              <span>
                {displayMsg.slice(0, 200)}...
                <ChevronRight size={10} className="inline-block ml-1 text-[var(--text-muted)] opacity-50" />
              </span>
            ) : (
              displayMsg
            )}
          </span>
          {isLong && expanded && (
            <ChevronDown size={10} className="shrink-0 text-[var(--text-muted)] opacity-50" />
          )}
        </div>
      </div>
    </div>
  );
}

export default function CommandTab() {
  const { selectedSessionId, sessions, isExecuting, setIsExecuting, getSessionData, updateSessionData } = useAppStore();
  const { t } = useI18n();
  const outputEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const [showAllLevels, setShowAllLevels] = useState(false);

  const session = sessions.find(s => s.session_id === selectedSessionId);
  const sessionData: SessionData | null = selectedSessionId ? getSessionData(selectedSessionId) : null;
  const logEntries: LogEntry[] = useMemo(
    () => (sessionData?.logEntries || []) as LogEntry[],
    [sessionData?.logEntries],
  );

  // Filter logs
  const visibleLogs = useMemo(
    () => showAllLevels ? logEntries : logEntries.filter(e => PRIMARY_LEVELS.has(e.level)),
    [logEntries, showAllLevels],
  );
  const hiddenCount = logEntries.length - visibleLogs.length;

  // Auto-scroll
  useEffect(() => {
    if (!showScrollBtn) {
      outputEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logEntries.length, sessionData?.output, showScrollBtn]);

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    setShowScrollBtn(el.scrollHeight - el.scrollTop - el.clientHeight > 100);
  }, []);

  const scrollToBottom = useCallback(() => {
    outputEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    setShowScrollBtn(false);
  }, []);

  // Auto-resize textarea
  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (!selectedSessionId) return;
    updateSessionData(selectedSessionId, { input: e.target.value });
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }, [selectedSessionId, updateSessionData]);

  const handleExecute = useCallback(async () => {
    if (!selectedSessionId || !sessionData?.input?.trim()) return;
    const prompt = sessionData.input.trim();
    setIsExecuting(true);
    updateSessionData(selectedSessionId, {
      status: 'running',
      statusText: t('commandTab.statusExecuting'),
      output: '',
      logEntries: [],
      input: '',
    });
    if (textareaRef.current) textareaRef.current.style.height = 'auto';

    try {
      await agentApi.executeStream(
        selectedSessionId,
        { prompt },
        (eventType, eventData) => {
          const current = useAppStore.getState().sessionDataCache[selectedSessionId];
          switch (eventType) {
            case 'log': {
              updateSessionData(selectedSessionId, {
                logEntries: [...(current?.logEntries || []), eventData as unknown as LogEntry],
              });
              break;
            }
            case 'status': {
              const s = eventData.status as string;
              const msg = eventData.message as string;
              updateSessionData(selectedSessionId, {
                status: s === 'completed' ? 'success' : s,
                statusText: msg,
              });
              break;
            }
            case 'result': {
              const success = eventData.success as boolean;
              const output = (eventData.output || eventData.error || t('common.noOutput')) as string;
              const ms = eventData.duration_ms as number | undefined;
              updateSessionData(selectedSessionId, {
                output,
                status: success ? 'success' : 'error',
                statusText: success
                  ? `${t('commandTab.statusSuccess')}${ms ? ` (${(ms / 1000).toFixed(1)}s)` : ''}`
                  : `${(eventData.error || t('commandTab.statusFailed')) as string}`,
              });
              break;
            }
            case 'error': {
              updateSessionData(selectedSessionId, {
                output: (eventData.error || t('commandTab.requestFailed')) as string,
                status: 'error',
                statusText: t('commandTab.statusFailed'),
              });
              break;
            }
          }
        },
      );
    } catch (e: unknown) {
      updateSessionData(selectedSessionId, {
        output: e instanceof Error ? e.message : t('commandTab.requestFailed'),
        status: 'error',
        statusText: t('commandTab.requestFailed'),
      });
    } finally {
      setIsExecuting(false);
    }
  }, [selectedSessionId, sessionData?.input, setIsExecuting, updateSessionData, t]);

  const handleStop = useCallback(async () => {
    if (!selectedSessionId) return;
    try {
      await agentApi.stop(selectedSessionId);
      updateSessionData(selectedSessionId, { statusText: t('commandTab.statusStopped') });
    } catch { /* ignore */ }
  }, [selectedSessionId, updateSessionData, t]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleExecute();
    }
  }, [handleExecute]);

  // ── No session selected ──
  if (!selectedSessionId || !session) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-[var(--primary-color)] to-[#6366f1] flex items-center justify-center mb-4 shadow-lg">
            <Terminal size={22} className="text-white" />
          </div>
          <h3 className="text-[1rem] font-medium text-[var(--text-secondary)] mb-2">{t('commandTab.selectSession')}</h3>
          <p className="text-[0.8125rem] text-[var(--text-muted)]">{t('commandTab.selectSessionDesc')}</p>
        </div>
      </div>
    );
  }

  const commandEntry = logEntries.find(e => e.level === 'COMMAND');
  const responseEntry = [...logEntries].reverse().find(e => e.level === 'RESPONSE');
  const hasFinished = sessionData?.status === 'success' || sessionData?.status === 'error';
  const hasContent = commandEntry || isExecuting || logEntries.length > 0;

  return (
    <div className="flex flex-col h-full bg-[var(--bg-primary)] relative">
      {/* ── Header ── */}
      <div className="shrink-0 px-4 py-2 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[var(--primary-color)] to-[#6366f1] flex items-center justify-center shadow-sm shrink-0">
              <Terminal size={13} className="text-white" />
            </div>
            <div className="flex items-center gap-2 min-w-0 flex-wrap">
              <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)] truncate">
                {session.session_name || session.session_id.substring(0, 8)}
              </span>
              <div className="flex items-center gap-1.5">
                <span className="px-1.5 py-[1px] rounded text-[0.5625rem] font-bold text-white uppercase tracking-wider"
                  style={{ background: 'linear-gradient(135deg, #10b981, #059669)' }}>
                  {session.role}
                </span>
                <span className="inline-flex items-center gap-0.5 px-1.5 py-[1px] rounded text-[0.5625rem] bg-[rgba(100,116,139,0.1)] text-[var(--text-muted)]">
                  <Zap size={8} />{session.graph_name || t('commandTab.single')}
                </span>
                {session.tool_preset_name && (
                  <span className="inline-flex items-center gap-0.5 px-1.5 py-[1px] rounded text-[0.5625rem] bg-[rgba(100,116,139,0.1)] text-[var(--text-muted)]">
                    <Wrench size={8} />{session.tool_preset_name}
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {session.max_turns && (
              <span className="text-[0.625rem] text-[var(--text-muted)]">{t('commandTab.maxTurns')}: {session.max_turns}</span>
            )}
            {sessionData?.statusText && (
              <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[0.6875rem] font-medium ${
                sessionData.status === 'success' ? 'bg-[rgba(16,185,129,0.1)] text-[var(--success-color)] border border-[rgba(16,185,129,0.2)]'
                  : sessionData.status === 'error' ? 'bg-[rgba(239,68,68,0.1)] text-[var(--danger-color)] border border-[rgba(239,68,68,0.2)]'
                  : 'bg-[rgba(245,158,11,0.08)] text-[var(--warning-color)] border border-[rgba(245,158,11,0.2)]'
              }`}>
                {sessionData.status === 'success' && <CheckCircle2 size={11} />}
                {sessionData.status === 'error' && <XCircle size={11} />}
                {sessionData.status === 'running' && <Clock size={11} className="animate-pulse" />}
                {sessionData.statusText}
              </div>
            )}
            {isExecuting && (
              <button className="h-7 w-7 rounded-md bg-[var(--danger-color)] hover:brightness-110 text-white flex items-center justify-center transition-all border-none cursor-pointer" onClick={handleStop} title={t('commandTab.stopBtn')}>
                <Square size={12} />
              </button>
            )}
            <button
              className="h-7 px-3 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.6875rem] font-semibold flex items-center justify-center gap-1.5 transition-all border-none disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer shadow-sm"
              disabled={isExecuting || !sessionData?.input?.trim()}
              onClick={handleExecute}
              title={isExecuting ? t('commandTab.executingBtn') : t('commandTab.executeBtn')}
            >
              {isExecuting ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              {isExecuting ? 'Running' : 'Run'}
            </button>
          </div>
        </div>
      </div>

      {/* ── Command input ── */}
      <div className="shrink-0 border-b border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2">
        <textarea
          ref={textareaRef}
          className="w-full bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-md px-3 py-[6px] text-[var(--text-primary)] text-[0.8125rem] resize-none outline-none placeholder:text-[var(--text-muted)] leading-relaxed max-h-[160px] transition-all focus:border-[var(--primary-color)] focus:shadow-[0_0_0_2px_rgba(59,130,246,0.1)]"
          rows={1}
          placeholder={t('commandTab.placeholder')}
          value={sessionData?.input || ''}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          disabled={isExecuting}
        />
        <span className="text-[0.5625rem] text-[var(--text-muted)] opacity-50 mt-0.5 block px-0.5">Enter to execute · Shift+Enter for newline</span>
      </div>

      {/* ── Execution output area (BELOW) ── */}
      <div ref={scrollContainerRef} className="flex-1 overflow-y-auto scroll-smooth" onScroll={handleScroll}>
        {!hasContent ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <div className="w-16 h-16 rounded-2xl bg-[var(--bg-secondary)] border border-[var(--border-color)] flex items-center justify-center mb-5">
              <Terminal size={28} className="text-[var(--text-muted)] opacity-40" />
            </div>
            <p className="text-[0.875rem] text-[var(--text-muted)] mb-1">{t('commandTab.placeholder')}</p>
            <p className="text-[0.75rem] text-[var(--text-muted)] opacity-60">Results appear here. Full history is in the Logs tab.</p>
          </div>
        ) : (
          <div className="flex flex-col h-full">
            {/* ── Submitted command echo ── */}
            {commandEntry && (
              <div className="shrink-0 px-4 py-2 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)]">
                <span className="text-[0.75rem] text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap break-words">
                  {commandEntry.message.replace(/^PROMPT:\s*/, '')}
                </span>
              </div>
            )}

            {/* ── Log stream ── */}
            <div className="flex-1 min-h-0">
              {visibleLogs.length > 0 && (
                <div className="font-mono text-[0.75rem]">
                  <div className="flex items-center justify-between px-4 py-1.5 bg-[var(--bg-secondary)] border-b border-[var(--border-color)]">
                    <span className="text-[0.625rem] text-[var(--text-muted)] uppercase tracking-wider font-semibold flex items-center gap-1.5">
                      <Terminal size={9} className="opacity-60" />
                      Execution Log
                      <span className="font-normal opacity-70">({visibleLogs.length}{hiddenCount > 0 ? `/${logEntries.length}` : ''})</span>
                    </span>
                    {hiddenCount > 0 && (
                      <button
                        className="text-[0.5625rem] text-[var(--text-muted)] hover:text-[var(--primary-color)] transition-colors flex items-center gap-0.5 uppercase tracking-wider font-medium"
                        onClick={() => setShowAllLevels(!showAllLevels)}
                      >
                        {showAllLevels ? <ChevronDown size={9} /> : <ChevronRight size={9} />}
                        {showAllLevels ? 'Hide' : 'Show'} detail ({hiddenCount})
                      </button>
                    )}
                  </div>
                  <div className="divide-y divide-[var(--border-color)]/20">
                    {visibleLogs.map((entry, i) => <LogLine key={i} entry={entry} />)}
                  </div>
                </div>
              )}

              {/* ── Running indicator ── */}
              {isExecuting && (
                <div className="flex items-center gap-3 px-4 py-3 border-t border-[var(--border-color)]">
                  <div className="flex gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary-color)] animate-bounce [animation-delay:0ms]" />
                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary-color)] animate-bounce [animation-delay:150ms]" />
                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary-color)] animate-bounce [animation-delay:300ms]" />
                  </div>
                  <span className="text-[0.75rem] text-[var(--text-muted)]">{sessionData?.statusText || 'Executing...'}</span>
                </div>
              )}

              {/* ── Result panel ── */}
              {hasFinished && (
                <div className="px-3 pt-4 pb-6">
                  <div className={`rounded-lg border overflow-hidden ${
                    sessionData?.status === 'success'
                      ? 'border-[rgba(16,185,129,0.3)] bg-[rgba(16,185,129,0.04)]'
                      : 'border-[rgba(239,68,68,0.3)] bg-[rgba(239,68,68,0.04)]'
                  }`}>
                    <div className={`flex items-center justify-between px-4 py-2 ${
                      sessionData?.status === 'success'
                        ? 'bg-[rgba(16,185,129,0.08)] border-b border-[rgba(16,185,129,0.15)]'
                        : 'bg-[rgba(239,68,68,0.08)] border-b border-[rgba(239,68,68,0.15)]'
                    }`}>
                      <div className="flex items-center gap-2">
                        {sessionData?.status === 'success'
                          ? <CheckCircle2 size={14} className="text-[var(--success-color)]" />
                          : <XCircle size={14} className="text-[var(--danger-color)]" />}
                        <span className={`text-[0.75rem] font-semibold uppercase tracking-wider ${
                          sessionData?.status === 'success' ? 'text-[var(--success-color)]' : 'text-[var(--danger-color)]'
                        }`}>
                          {sessionData?.status === 'success' ? 'Result' : 'Error'}
                        </span>
                      </div>
                      {sessionData?.statusText && (
                        <span className="text-[0.6875rem] text-[var(--text-muted)]">{sessionData.statusText}</span>
                      )}
                    </div>
                    <div className="px-4 py-3">
                      {responseEntry ? (
                        <div className="text-[0.8125rem] text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap break-words">
                          {responseEntry.message.replace(/^SUCCESS:\s*/, '').replace(/^ERROR:\s*/, '')}
                        </div>
                      ) : sessionData?.output ? (
                        <pre className="text-[0.8125rem] text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap break-words font-[inherit]">
                          {sessionData.output}
                        </pre>
                      ) : null}
                    </div>
                  </div>
                </div>
              )}

              <div ref={outputEndRef} />
            </div>
          </div>
        )}
      </div>

      {/* Scroll-to-bottom */}
      {showScrollBtn && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10">
          <button className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[0.75rem] text-[var(--text-muted)] shadow-lg hover:bg-[var(--bg-hover)] transition-all" onClick={scrollToBottom}>
            <ArrowDown size={12} /> New events
          </button>
        </div>
      )}
    </div>
  );
}
