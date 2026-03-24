'use client';

import { useCallback, useRef, useEffect, useState, useMemo } from 'react';
import { useAppStore, type SessionData } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import type { LogEntry } from '@/types';
import ExecutionTimeline from '@/components/execution/ExecutionTimeline';
import StepDetailPanel from '@/components/execution/StepDetailPanel';
import {
  Square,
  Loader2,
  Terminal,
  Zap,

  Clock,
  CheckCircle2,
  XCircle,
  Play,
  PanelRightClose,
  ScrollText,
  FileOutput,
} from 'lucide-react';

export default function CommandTab() {
  const { selectedSessionId, sessions, getSessionData, updateSessionData } = useAppStore();
  const { t } = useI18n();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [showAllLevels, setShowAllLevels] = useState(false);
  const [selectedStepIndex, setSelectedStepIndex] = useState<number | null>(null);
  const [detailPanelWidth, setDetailPanelWidth] = useState(55); // percentage
  const [isResizing, setIsResizing] = useState(false);
  const [activeView, setActiveView] = useState<'log' | 'result'>('log');
  const prevFinishedRef = useRef(false);

  const session = sessions.find(s => s.session_id === selectedSessionId);
  const sessionData: SessionData | null = selectedSessionId ? getSessionData(selectedSessionId) : null;
  const isExecuting = sessionData?.status === 'running';
  const logEntries: LogEntry[] = useMemo(
    () => (sessionData?.logEntries || []) as LogEntry[],
    [sessionData?.logEntries],
  );

  // Selected entry
  const selectedEntry = selectedStepIndex !== null ? logEntries[selectedStepIndex] : null;

  // Clear selection when session changes
  useEffect(() => {
    setSelectedStepIndex(null);
    setActiveView('log');
    prevFinishedRef.current = false;
  }, [selectedSessionId]);

  // Auto-switch to result when execution completes
  const hasFinished = sessionData?.status === 'success' || sessionData?.status === 'error';
  useEffect(() => {
    if (hasFinished && !prevFinishedRef.current) {
      setActiveView('result');
      setSelectedStepIndex(null);
    }
    prevFinishedRef.current = hasFinished;
  }, [hasFinished]);

  // ── Auto-reconnect to running execution on mount / visibility change ──
  const reconnectRef = useRef<{ close: () => void } | null>(null);

  useEffect(() => {
    if (!selectedSessionId) return;

    let cancelled = false;

    const tryReconnect = async () => {
      // Don't reconnect if we're already streaming
      if (reconnectRef.current) return;
      const current = useAppStore.getState().sessionDataCache[selectedSessionId];
      if (current?.status === 'running') return; // already streaming

      try {
        const status = await agentApi.getExecutionStatus(selectedSessionId);
        if (cancelled) return;
        if (!status.active || status.done) return;

        // Active execution found — reconnect SSE
        updateSessionData(selectedSessionId, {
          status: 'running',
          statusText: t('commandTab.statusExecuting'),
        });

        reconnectRef.current = agentApi.reconnectStream(
          selectedSessionId,
          (eventType, eventData) => {
            const cur = useAppStore.getState().sessionDataCache[selectedSessionId];
            switch (eventType) {
              case 'log':
                updateSessionData(selectedSessionId, {
                  logEntries: [...(cur?.logEntries || []), eventData as unknown as LogEntry],
                });
                break;
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
              case 'error':
                updateSessionData(selectedSessionId, {
                  output: (eventData.error || t('commandTab.requestFailed')) as string,
                  status: 'error',
                  statusText: t('commandTab.statusFailed'),
                });
                break;
              case 'done':
                reconnectRef.current = null;
                break;
            }
          },
        );
      } catch {
        // No active execution — that's fine
      }
    };

    // Check on mount
    tryReconnect();

    // Check on visibility change (phone unlock, tab refocus)
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        tryReconnect();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', handleVisibility);
      reconnectRef.current?.close();
      reconnectRef.current = null;
    };
  }, [selectedSessionId, updateSessionData, t]);

  // ── Resize handler for split pane ──
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
    const startX = e.clientX;
    const startWidth = detailPanelWidth;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const container = (e.target as HTMLElement).parentElement;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const deltaPercent = ((moveEvent.clientX - startX) / rect.width) * 100;
      const newWidth = Math.max(25, Math.min(75, startWidth - deltaPercent));
      setDetailPanelWidth(newWidth);
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [detailPanelWidth]);

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
    setSelectedStepIndex(null);
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
      // Safety: if SSE stream closed without result/error event, check if
      // execution might still be running on the backend before marking failed.
      const final = useAppStore.getState().sessionDataCache[selectedSessionId];
      if (final?.status === 'running') {
        // Try to poll the execution status once before giving up
        try {
          const holder = await fetch(`/api/agents/${selectedSessionId}/execute/events`);
          if (holder.ok) {
            // Execution still active — the reconnect logic in executeStream
            // exhausted its retries, so mark as connection-lost rather than generic fail
            updateSessionData(selectedSessionId, {
              status: 'error',
              statusText: t('commandTab.statusConnectionLost', 'Connection lost'),
            });
          } else {
            updateSessionData(selectedSessionId, {
              status: 'error',
              statusText: t('commandTab.statusFailed'),
            });
          }
        } catch {
          updateSessionData(selectedSessionId, {
            status: 'error',
            statusText: t('commandTab.statusFailed'),
          });
        }
      }
    }
  }, [selectedSessionId, sessionData?.input, updateSessionData, t]);

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
            {/* Detail panel toggle */}
            {selectedEntry && (
              <button
                onClick={() => setSelectedStepIndex(null)}
                className="h-7 w-7 rounded-md bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)] text-[var(--text-muted)] flex items-center justify-center transition-all border border-[var(--border-color)] cursor-pointer"
                title="Close detail panel"
              >
                <PanelRightClose size={13} />
              </button>
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

      {/* ── Main execution area: Split pane (Timeline | Detail) ── */}
      <div className="flex-1 flex min-h-0 relative">
        {!hasContent ? (
          /* Empty state */
          <div className="flex flex-col items-center justify-center w-full h-full text-center px-4">
            <div className="w-16 h-16 rounded-2xl bg-[var(--bg-secondary)] border border-[var(--border-color)] flex items-center justify-center mb-5">
              <Terminal size={28} className="text-[var(--text-muted)] opacity-40" />
            </div>
            <p className="text-[0.875rem] text-[var(--text-muted)] mb-1">{t('commandTab.placeholder')}</p>
            <p className="text-[0.75rem] text-[var(--text-muted)] opacity-60">Results appear here. Full history is in the Logs tab.</p>
          </div>
        ) : (
          <>
            {/* ── Left pane: Accordion (Log / Result) ── */}
            <div
              className="flex flex-col min-w-0 border-r border-[var(--border-color)]"
              style={{ width: selectedEntry ? `${100 - detailPanelWidth}%` : '100%', transition: isResizing ? 'none' : 'width 0.2s ease' }}
            >
              {/* Submitted command echo */}
              {commandEntry && (
                <div className="shrink-0 px-4 py-2 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)]">
                  <span className="text-[0.75rem] text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap break-words">
                    {commandEntry.message.replace(/^PROMPT:\s*/, '')}
                  </span>
                </div>
              )}

              {/* ── Section toggle headers ── */}
              <div className="shrink-0 flex border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
                {/* Log tab */}
                <button
                  className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-[0.6875rem] font-semibold transition-all border-none cursor-pointer ${
                    activeView === 'log'
                      ? 'text-[var(--primary-color)] bg-[rgba(59,130,246,0.06)] border-b-2 border-b-[var(--primary-color)]'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] bg-transparent'
                  }`}
                  style={{ borderBottom: activeView === 'log' ? '2px solid var(--primary-color)' : '2px solid transparent' }}
                  onClick={() => setActiveView('log')}
                >
                  <ScrollText size={12} />
                  Log
                  <span className={`text-[0.5625rem] font-normal ${activeView === 'log' ? 'opacity-70' : 'opacity-50'}`}>
                    ({logEntries.length})
                  </span>
                  {isExecuting && (
                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary-color)] animate-pulse" />
                  )}
                </button>

                {/* Result tab */}
                <button
                  className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-[0.6875rem] font-semibold transition-all border-none cursor-pointer ${
                    activeView === 'result' && hasFinished
                      ? (sessionData?.status === 'success'
                          ? 'text-[var(--success-color)] bg-[rgba(16,185,129,0.06)]'
                          : 'text-[var(--danger-color)] bg-[rgba(239,68,68,0.06)]')
                      : hasFinished
                        ? 'text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] bg-transparent'
                        : 'text-[var(--text-muted)] opacity-40 bg-transparent cursor-default'
                  }`}
                  style={{
                    borderBottom: activeView === 'result' && hasFinished
                      ? `2px solid ${sessionData?.status === 'success' ? 'var(--success-color)' : 'var(--danger-color)'}`
                      : '2px solid transparent',
                  }}
                  onClick={() => hasFinished && setActiveView('result')}
                  disabled={!hasFinished}
                >
                  <FileOutput size={12} />
                  Result
                  {hasFinished && (
                    sessionData?.status === 'success'
                      ? <CheckCircle2 size={10} className="text-[var(--success-color)]" />
                      : <XCircle size={10} className="text-[var(--danger-color)]" />
                  )}
                </button>
              </div>

              {/* ── Active section content ── */}
              {activeView === 'log' ? (
                /* Log view: Timeline */
                <div className="flex-1 min-h-0 overflow-hidden">
                  <ExecutionTimeline
                    entries={logEntries}
                    selectedIndex={selectedStepIndex}
                    onSelectEntry={setSelectedStepIndex}
                    showAllLevels={showAllLevels}
                    onToggleShowAll={() => setShowAllLevels(!showAllLevels)}
                    isExecuting={isExecuting}
                    statusText={sessionData?.statusText}
                  />
                </div>
              ) : (
                /* Result view */
                <div className="flex-1 min-h-0 overflow-auto">
                  {hasFinished && (
                    <div className={`h-full flex flex-col ${
                      sessionData?.status === 'success'
                        ? 'bg-[rgba(16,185,129,0.02)]'
                        : 'bg-[rgba(239,68,68,0.02)]'
                    }`}>
                      {/* Result header */}
                      <div className={`shrink-0 flex items-center justify-between px-4 py-2 ${
                        sessionData?.status === 'success'
                          ? 'bg-[rgba(16,185,129,0.08)] border-b border-[rgba(16,185,129,0.15)]'
                          : 'bg-[rgba(239,68,68,0.08)] border-b border-[rgba(239,68,68,0.15)]'
                      }`}>
                        <div className="flex items-center gap-2">
                          {sessionData?.status === 'success'
                            ? <CheckCircle2 size={13} className="text-[var(--success-color)]" />
                            : <XCircle size={13} className="text-[var(--danger-color)]" />}
                          <span className={`text-[0.75rem] font-semibold ${
                            sessionData?.status === 'success' ? 'text-[var(--success-color)]' : 'text-[var(--danger-color)]'
                          }`}>
                            {sessionData?.status === 'success' ? 'Result' : 'Error'}
                          </span>
                        </div>
                        {sessionData?.statusText && (
                          <span className="text-[0.6875rem] text-[var(--text-muted)]">{sessionData.statusText}</span>
                        )}
                      </div>
                      {/* Result body */}
                      <div className="flex-1 overflow-auto px-5 py-4">
                        {responseEntry ? (
                          <div className="text-[0.8125rem] text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap break-words">
                            {responseEntry.message.replace(/^SUCCESS:\s*/, '').replace(/^ERROR:\s*/, '')}
                          </div>
                        ) : sessionData?.output ? (
                          <pre className="text-[0.8125rem] text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap break-words font-[inherit] m-0">
                            {sessionData.output}
                          </pre>
                        ) : (
                          <p className="text-[0.8125rem] text-[var(--text-muted)] italic">No output</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* ── Resize handle ── */}
            {selectedEntry && (
              <div
                className="shrink-0 w-[4px] cursor-col-resize hover:bg-[var(--primary-color)] active:bg-[var(--primary-color)] transition-colors z-10"
                style={{ backgroundColor: isResizing ? 'var(--primary-color)' : 'transparent' }}
                onMouseDown={handleResizeStart}
              />
            )}

            {/* ── Right pane: Step Detail ── */}
            {selectedEntry && (
              <div
                className="min-w-0 border-l border-[var(--border-color)]"
                style={{ width: `${detailPanelWidth}%`, transition: isResizing ? 'none' : 'width 0.2s ease' }}
              >
                <StepDetailPanel
                  entry={selectedEntry}
                  allEntries={logEntries}
                  onClose={() => setSelectedStepIndex(null)}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
