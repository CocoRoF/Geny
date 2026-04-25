'use client';

import { useCallback, useRef, useEffect, useState, useMemo } from 'react';
import { useAppStore, type SessionData, type PendingHitlRequest } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { useIsMobile } from '@/lib/useIsMobile';
import type { LogEntry } from '@/types';
import ExecutionTimeline from '@/components/execution/ExecutionTimeline';
import StepDetailPanel from '@/components/execution/StepDetailPanel';
import HITLApprovalModal from '@/components/modals/HITLApprovalModal';
import RestoreCheckpointModal from '@/components/modals/RestoreCheckpointModal';
import SkillPanel from '@/components/skills/SkillPanel';
import {
  Square,
  Loader2,
  Terminal,
  Zap,
  X,
  Clock,
  CheckCircle2,
  XCircle,
  Play,
  PanelRightClose,
  ScrollText,
  FileOutput,
  History,
} from 'lucide-react';

/**
 * Inspect a `log` WS event for HITL stage transitions and derive the
 * next `pendingHitl` value. Returns:
 *  - `undefined` → no change (use the previous value)
 *  - `null`      → clear the pending request (decision/timeout landed)
 *  - object      → set a new pending request (request just opened)
 *
 * The backend marshals stage events through `session_logger.log_stage_event`
 * (`service/logging/session_logger.py:740`), so the relevant payload is at
 * `eventData.metadata.event_type` and `.metadata.data` rather than at the
 * top level of `eventData`.
 */
function deriveHitlFromLogEvent(
  eventData: Record<string, unknown>,
  current: PendingHitlRequest | null | undefined,
): PendingHitlRequest | null | undefined {
  const meta = eventData.metadata as Record<string, unknown> | undefined;
  if (!meta) return undefined;
  const evt = meta.event_type as string | undefined;
  if (!evt) return undefined;
  const data = (meta.data as Record<string, unknown> | undefined) || {};
  const token = typeof data.token === 'string' ? data.token : '';

  if (evt === 'hitl_request' && token) {
    return {
      token,
      reason: typeof data.reason === 'string' ? data.reason : '',
      severity: typeof data.severity === 'string' ? data.severity : 'warn',
      data,
      receivedAt: Date.now(),
    };
  }
  if ((evt === 'hitl_decision' || evt === 'hitl_timeout') && current && current.token === token) {
    return null;
  }
  return undefined;
}

export default function CommandTab() {
  const { selectedSessionId, sessions, getSessionData, updateSessionData } = useAppStore();
  const { t } = useI18n();
  const isMobile = useIsMobile();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [showAllLevels, setShowAllLevels] = useState(false);
  const [selectedStepIndex, setSelectedStepIndex] = useState<number | null>(null);
  const [detailPanelWidth, setDetailPanelWidth] = useState(55); // percentage
  const [isResizing, setIsResizing] = useState(false);
  const [activeView, setActiveView] = useState<'log' | 'result'>('log');
  const prevFinishedRef = useRef(false);

  // ── Execution health tracking ──
  const executionStartRef = useRef<number>(0);
  const lastLogReceivedRef = useRef<number>(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [lastActivityAge, setLastActivityAge] = useState(0); // ms since last activity
  const lastToolNameRef = useRef<string | null>(null);
  const [lastToolName, setLastToolName] = useState<string | null>(null);

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

  // ── Elapsed timer — ticks every second while executing ──
  useEffect(() => {
    if (!isExecuting) {
      setElapsedMs(0);
      setLastActivityAge(0);
      setLastToolName(null);
      lastToolNameRef.current = null;
      return;
    }
    const id = setInterval(() => {
      const now = Date.now();
      if (executionStartRef.current > 0) {
        setElapsedMs(now - executionStartRef.current);
      }
      if (lastLogReceivedRef.current > 0) {
        setLastActivityAge(now - lastLogReceivedRef.current);
      }
      setLastToolName(lastToolNameRef.current);
    }, 1000);
    return () => clearInterval(id);
  }, [isExecuting]);

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
        // Initialize timing from status response
        const now = Date.now();
        const statusElapsed = (status.elapsed_ms as number | undefined) ?? 0;
        executionStartRef.current = now - statusElapsed;
        const statusActivityAge = (status.last_activity_ms as number | undefined) ?? statusElapsed;
        lastLogReceivedRef.current = now - statusActivityAge;
        // Initialize last tool name from status response
        lastToolNameRef.current = (status.last_tool_name as string | undefined) || null;

        updateSessionData(selectedSessionId, {
          status: 'running',
          statusText: t('commandTab.statusExecuting'),
        });

        reconnectRef.current = agentApi.reconnectStream(
          selectedSessionId,
          (eventType, eventData) => {
            const cur = useAppStore.getState().sessionDataCache[selectedSessionId];
            switch (eventType) {
              case 'log': {
                lastLogReceivedRef.current = Date.now();
                const logLevel = (eventData as Record<string, unknown>).level as string | undefined;
                const logMeta = (eventData as Record<string, unknown>).metadata as Record<string, unknown> | undefined;
                if (logLevel === 'TOOL' || logLevel === 'TOOL_RES') {
                  lastToolNameRef.current = (logMeta?.tool_name as string) || null;
                } else if (logLevel && logLevel !== 'DEBUG' && logLevel !== 'INFO') {
                  lastToolNameRef.current = null;
                }
                const nextHitl = deriveHitlFromLogEvent(
                  eventData as Record<string, unknown>,
                  cur?.pendingHitl ?? null,
                );
                updateSessionData(selectedSessionId, {
                  logEntries: [...(cur?.logEntries || []), eventData as unknown as LogEntry],
                  ...(nextHitl !== undefined ? { pendingHitl: nextHitl } : {}),
                });
                break;
              }
              case 'heartbeat': {
                if (eventData.last_activity_ms != null) {
                  const serverAge = eventData.last_activity_ms as number;
                  const clientAge = Date.now() - lastLogReceivedRef.current;
                  if (serverAge > clientAge) {
                    lastLogReceivedRef.current = Date.now() - serverAge;
                  }
                }
                if (eventData.last_tool_name !== undefined) {
                  lastToolNameRef.current = (eventData.last_tool_name as string) || null;
                }
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
    const now = Date.now();
    executionStartRef.current = now;
    lastLogReceivedRef.current = now;
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
              lastLogReceivedRef.current = Date.now();
              const logLevel = (eventData as Record<string, unknown>).level as string | undefined;
              const logMeta = (eventData as Record<string, unknown>).metadata as Record<string, unknown> | undefined;
              if (logLevel === 'TOOL' || logLevel === 'TOOL_RES') {
                lastToolNameRef.current = (logMeta?.tool_name as string) || null;
              } else if (logLevel && logLevel !== 'DEBUG' && logLevel !== 'INFO') {
                lastToolNameRef.current = null;
              }
              const nextHitl = deriveHitlFromLogEvent(
                eventData as Record<string, unknown>,
                current?.pendingHitl ?? null,
              );
              updateSessionData(selectedSessionId, {
                logEntries: [...(current?.logEntries || []), eventData as unknown as LogEntry],
                ...(nextHitl !== undefined ? { pendingHitl: nextHitl } : {}),
              });
              break;
            }
            case 'heartbeat': {
              // Server-side activity tracking — use as fallback/correction
              if (eventData.last_activity_ms != null) {
                const serverAge = eventData.last_activity_ms as number;
                const clientAge = Date.now() - lastLogReceivedRef.current;
                // Use the larger value (more conservative)
                if (serverAge > clientAge) {
                  lastLogReceivedRef.current = Date.now() - serverAge;
                }
              }
              if (eventData.last_tool_name !== undefined) {
                lastToolNameRef.current = (eventData.last_tool_name as string) || null;
              }
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
      // Safety: if WebSocket/SSE stream closed without result/error event,
      // check if execution might still be running on the backend.
      const final = useAppStore.getState().sessionDataCache[selectedSessionId];
      if (final?.status === 'running') {
        try {
          const status = await agentApi.getExecutionStatus(selectedSessionId);
          if (status.active && !status.done) {
            // Execution still active — connection was lost
            updateSessionData(selectedSessionId, {
              status: 'error',
              statusText: t('commandTab.statusConnectionLost'),
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
    // On mobile, the Enter key always inserts a newline.
    // Run is only triggered by tapping the Run button in the UI.
    if (isMobile) return;
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleExecute();
    }
  }, [isMobile, handleExecute]);

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

  // ── Format elapsed time ──
  const formatElapsed = (ms: number): string => {
    const totalSec = Math.floor(ms / 1000);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${m}:${String(s).padStart(2, '0')}`;
  };

  // ── Format inactivity duration ──
  const formatInactivity = (ms: number): string => {
    const sec = Math.floor(ms / 1000);
    if (sec < 60) return `${sec}s`;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    if (m < 60) return s > 0 ? `${m}m ${s}s` : `${m}m`;
    const h = Math.floor(m / 60);
    return `${h}h ${m % 60}m`;
  };

  // ── HITL approval modal — shown whenever Stage 15 surfaces a pending
  // request and not yet resolved by a hitl_decision / hitl_timeout
  // event echoed back over the WS stream. The modal closes optimistically
  // on a successful resume; the WS event landing later just clears
  // pendingHitl again, which is a no-op.
  const pendingHitl = sessionData?.pendingHitl ?? null;
  const handleHitlClose = useCallback(() => {
    if (!selectedSessionId) return;
    updateSessionData(selectedSessionId, { pendingHitl: null });
  }, [selectedSessionId, updateSessionData]);

  // ── Restore-from-checkpoint modal (G7.2) — operator-triggered.
  // Visible button appears whenever the session has reached an
  // error / connection-lost state where a rewind is the natural recovery.
  // R5 (audit 20260425_3 §1.4): expand from `error` only to every
  // non-running, non-success terminal state — backend can emit
  // `crashed` / `disconnected` / `failed` etc. and operators
  // should see the recovery affordance there too.
  const [showRestore, setShowRestore] = useState(false);
  const status = sessionData?.status ?? '';
  const restoreEligible = status !== '' && status !== 'running' && status !== 'success';

  return (
    <div className="flex flex-col h-full bg-[var(--bg-primary)] relative">
      {/* HITL approval modal — global to the session view */}
      {selectedSessionId && pendingHitl && (
        <HITLApprovalModal
          sessionId={selectedSessionId}
          request={pendingHitl}
          onClose={handleHitlClose}
        />
      )}
      {/* Restore-from-checkpoint modal */}
      {selectedSessionId && showRestore && (
        <RestoreCheckpointModal
          sessionId={selectedSessionId}
          onClose={() => setShowRestore(false)}
        />
      )}
      {/* ── Header ── */}
      <div className="shrink-0 px-3 md:px-4 py-2 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[var(--primary-color)] to-[#6366f1] flex items-center justify-center shadow-sm shrink-0">
              <Terminal size={13} className="text-white" />
            </div>
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)] truncate max-w-[100px] md:max-w-none">
                {session.session_name || session.session_id.substring(0, 8)}
              </span>
              <div className="hidden sm:flex items-center gap-1.5">
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
          <div className="flex items-center gap-1.5 md:gap-2 shrink-0">
            {/* Elapsed timer — compact on mobile */}
            {isExecuting && elapsedMs > 0 && (
              <div className="inline-flex items-center gap-1.5 md:gap-2 px-2 md:px-2.5 py-1 rounded-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[0.625rem] md:text-[0.6875rem]">
                <Clock size={10} className="text-[var(--text-muted)]" />
                <span className="font-mono text-[var(--text-secondary)] font-medium">{formatElapsed(elapsedMs)}</span>
                <span className="text-[var(--text-muted)]">·</span>
                <span className="text-[var(--text-muted)]">{logEntries.length}</span>
                {!isMobile && lastActivityAge >= 10_000 && (
                  <>
                    <span className="text-[var(--text-muted)]">·</span>
                    {lastToolName ? (
                      <span className="text-[var(--text-muted)] font-mono">🔧 {lastToolName} ({formatInactivity(lastActivityAge)})</span>
                    ) : (
                      <span className="text-[var(--text-muted)] font-mono">{t('commandTab.noActivity')} {formatInactivity(lastActivityAge)}</span>
                    )}
                  </>
                )}
              </div>
            )}
            {/* Status badge — hidden on mobile when executing (timer is enough) */}
            {sessionData?.statusText && !(isMobile && isExecuting) && (
              <div className={`hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[0.6875rem] font-medium ${
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
            {/* Detail panel toggle — hidden on mobile (uses overlay) */}
            {selectedEntry && !isMobile && (
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
            {restoreEligible && !isExecuting && (
              <button
                className="h-7 w-7 rounded-md bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)] text-[var(--primary-color)] flex items-center justify-center transition-all border border-[var(--border-color)] cursor-pointer"
                onClick={() => setShowRestore(true)}
                title={t('restore.modalTitle')}
              >
                <History size={12} />
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
        <span className="text-[0.5625rem] text-[var(--text-muted)] opacity-50 mt-0.5 block px-0.5">
          {isMobile ? 'Tap Run to execute · Enter for newline' : 'Enter to execute · Shift+Enter for newline'}
        </span>
      </div>

      {/* ── Skill picker (G7.4) ── */}
      {selectedSessionId && !isMobile && (
        <div className="shrink-0 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
          <SkillPanel
            onPickSkill={(slash) => {
              const cur = (sessionData?.input ?? '').trimStart();
              const next = cur.startsWith('/')
                ? cur.replace(/^\S+/, slash)
                : `${slash} ${cur}`.trimEnd();
              updateSessionData(selectedSessionId, { input: next + ' ' });
              textareaRef.current?.focus();
            }}
          />
        </div>
      )}

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
              style={{
                width: selectedEntry && !isMobile ? `${100 - detailPanelWidth}%` : '100%',
                transition: isResizing ? 'none' : 'width 0.2s ease',
              }}
            >
              {/* Submitted command echo */}
              {commandEntry && (
                <div className="shrink-0 max-h-[120px] overflow-y-auto px-4 py-2 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)]">
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

            {/* ── Resize handle — desktop only ── */}
            {selectedEntry && !isMobile && (
              <div
                className="shrink-0 w-[4px] cursor-col-resize hover:bg-[var(--primary-color)] active:bg-[var(--primary-color)] transition-colors z-10"
                style={{ backgroundColor: isResizing ? 'var(--primary-color)' : 'transparent' }}
                onMouseDown={handleResizeStart}
              />
            )}

            {/* ── Right pane: Step Detail — overlay on mobile ── */}
            {selectedEntry && (
              isMobile ? (
                <div className="fixed inset-0 z-50 flex flex-col bg-[var(--bg-primary)]">
                  <div className="shrink-0 flex items-center justify-between px-3 py-2 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
                    <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">Detail</span>
                    <button
                      onClick={() => setSelectedStepIndex(null)}
                      className="h-8 w-8 rounded-md bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)] text-[var(--text-muted)] flex items-center justify-center transition-all border border-[var(--border-color)] cursor-pointer"
                    >
                      <X size={16} />
                    </button>
                  </div>
                  <div className="flex-1 min-h-0 overflow-auto">
                    <StepDetailPanel
                      entry={selectedEntry}
                      allEntries={logEntries}
                      onClose={() => setSelectedStepIndex(null)}
                    />
                  </div>
                </div>
              ) : (
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
              )
            )}
          </>
        )}
      </div>
    </div>
  );
}
