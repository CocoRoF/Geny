'use client';

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { commandApi } from '@/lib/api';
import { useIsMobile } from '@/lib/useIsMobile';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';
import {
  ClipboardList,
  Wrench,
  Search,
  BookOpen,
  RefreshCw,
  ChevronLeft,
  ChevronsLeft,
  ChevronsRight,
  ChevronRight,
  PanelRightClose,
  ScrollText,
  X,
} from 'lucide-react';
import type { LogEntry } from '@/types';
import LogEntryCard from '@/components/execution/LogEntryCard';
import StepDetailPanel from '@/components/execution/StepDetailPanel';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

// ==================== Log Group Definitions ====================

interface LogGroup {
  id: string;
  labelKey: string;
  descKey: string;
  levels: string[];
  Icon: React.ComponentType<{ size?: number; className?: string }>;
}

const LOG_GROUPS: LogGroup[] = [
  {
    id: 'brief',
    labelKey: 'groupBrief',
    descKey: 'groupBriefDesc',
    levels: ['INFO', 'COMMAND', 'RESPONSE', 'ERROR', 'WARNING'],
    Icon: ClipboardList,
  },
  {
    id: 'default',
    labelKey: 'groupDefault',
    descKey: 'groupDefaultDesc',
    levels: ['INFO', 'COMMAND', 'RESPONSE', 'ERROR', 'WARNING', 'TOOL', 'TOOL_RES', 'ITER'],
    Icon: Wrench,
  },
  {
    id: 'detail',
    labelKey: 'groupDetail',
    descKey: 'groupDetailDesc',
    levels: ['INFO', 'COMMAND', 'RESPONSE', 'ERROR', 'WARNING', 'TOOL', 'TOOL_RES', 'ITER', 'GRAPH', 'STREAM'],
    Icon: Search,
  },
  {
    id: 'all',
    labelKey: 'groupAll',
    descKey: 'groupAllDesc',
    levels: [],
    Icon: BookOpen,
  },
];

const ALL_LEVELS = ['INFO', 'ERROR', 'WARNING', 'DEBUG', 'COMMAND', 'RESPONSE', 'GRAPH', 'ITER', 'TOOL', 'TOOL_RES', 'STREAM'] as const;

const PAGE_SIZE = 50;

export default function LogsTab() {
  const { selectedSessionId, sessions } = useAppStore();
  const { t } = useI18n();
  const isMobile = useIsMobile();
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [totalEntries, setTotalEntries] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [filter, setFilter] = useState('group:default');
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [viewMode, setViewMode] = useState<'vtuber' | 'sub'>('vtuber');

  // VTuber/Sub-Worker dual-view support
  const session = useMemo(
    () => sessions.find(s => s.session_id === selectedSessionId),
    [sessions, selectedSessionId],
  );

  const linkedSubWorkerSession = useMemo(() => {
    if (!session || session.session_type !== 'vtuber') return null;
    return sessions.find(s => s.session_type === 'sub' && s.linked_session_id === session.session_id) ?? null;
  }, [session, sessions]);

  const hasDualView = !!linkedSubWorkerSession;

  // Resolve which session ID to fetch logs for
  const targetSessionId = useMemo(() => {
    if (!hasDualView || viewMode === 'vtuber') return selectedSessionId;
    return linkedSubWorkerSession?.session_id ?? selectedSessionId;
  }, [hasDualView, viewMode, selectedSessionId, linkedSubWorkerSession]);

  // Context for the sticky header — which session's env/role/type we're looking at.
  const contextSession = useMemo(() => {
    if (!targetSessionId) return null;
    return sessions.find(s => s.session_id === targetSessionId) ?? null;
  }, [sessions, targetSessionId]);

  // Reset viewMode when session changes
  useEffect(() => { setViewMode('vtuber'); }, [selectedSessionId]);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Split pane state
  const [detailPanelWidth, setDetailPanelWidth] = useState(55);
  const [isResizing, setIsResizing] = useState(false);

  const totalPages = Math.max(1, Math.ceil(totalEntries / PAGE_SIZE));

  const selectedEntry = selectedIdx !== null ? entries[selectedIdx] : null;

  /** Resolve the current filter to a comma-separated level string for the API. */
  const apiLevelParam = useMemo(() => {
    if (!filter) return undefined;
    if (filter.startsWith('group:')) {
      const groupId = filter.slice(6);
      const group = LOG_GROUPS.find(g => g.id === groupId);
      if (!group || group.levels.length === 0) return undefined;
      return group.levels.join(',');
    }
    return filter;
  }, [filter]);

  const fetchLogs = useCallback(async (page: number) => {
    if (!targetSessionId) return;
    setLoading(true);
    try {
      const offset = (page - 1) * PAGE_SIZE;
      const res = await commandApi.getLogs(targetSessionId, PAGE_SIZE, apiLevelParam, offset);
      setEntries(res.entries || []);
      setTotalEntries(res.total_entries || 0);
      setSelectedIdx(null);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [targetSessionId, apiLevelParam]);

  // Fetch on session/filter/page change
  useEffect(() => {
    fetchLogs(currentPage);
  }, [fetchLogs, currentPage]);

  // Reset to page 1 when session or filter changes
  useEffect(() => {
    setCurrentPage(1);
  }, [targetSessionId, apiLevelParam]);

  // Clear selection when session changes
  useEffect(() => {
    setSelectedIdx(null);
  }, [targetSessionId]);

  // Scroll to top when entries change
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [entries]);

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

  if (!selectedSessionId) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center justify-center py-12 px-4">
          <h3 className="text-[1rem] font-medium text-[var(--text-secondary)] mb-2">{t('logsTab.selectSession')}</h3>
          <p className="text-[0.8125rem] text-[var(--text-muted)]">{t('logsTab.selectSessionDesc')}</p>
        </div>
      </div>
    );
  }

  const pageStart = (currentPage - 1) * PAGE_SIZE + 1;
  const pageEnd = Math.min(currentPage * PAGE_SIZE, totalEntries);

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden bg-[var(--bg-primary)]">
      {/* ── Header bar ── */}
      <div className="shrink-0 flex flex-row items-center justify-between px-3 md:px-4 py-2 gap-1.5 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
        <div className="hidden md:flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[#8b5cf6] to-[#6366f1] flex items-center justify-center shadow-sm shrink-0">
            <ScrollText size={13} className="text-white" />
          </div>
          <h3 className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">{t('logsTab.title')}</h3>

          {/* VTuber / Sub-Worker toggle */}
          {hasDualView && (
            <div className="flex items-center h-6 rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] overflow-hidden shrink-0">
              <button
                className={`px-2 h-full text-[10px] font-semibold transition-colors border-none cursor-pointer ${
                  viewMode === 'vtuber'
                    ? 'bg-[var(--primary-color)] text-white'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] bg-transparent'
                }`}
                onClick={() => setViewMode('vtuber')}
              >
                VTuber
              </button>
              <button
                className={`px-2 h-full text-[10px] font-semibold transition-colors border-none cursor-pointer ${
                  viewMode === 'sub'
                    ? 'bg-[var(--primary-color)] text-white'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] bg-transparent'
                }`}
                onClick={() => setViewMode('sub')}
              >
                Sub-Worker
              </button>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* VTuber / Sub-Worker toggle — mobile */}
          {hasDualView && (
            <div className="flex md:hidden items-center h-6 rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] overflow-hidden shrink-0">
              <button
                className={`px-2 h-full text-[10px] font-semibold transition-colors border-none cursor-pointer ${
                  viewMode === 'vtuber'
                    ? 'bg-[var(--primary-color)] text-white'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] bg-transparent'
                }`}
                onClick={() => setViewMode('vtuber')}
              >
                VTuber
              </button>
              <button
                className={`px-2 h-full text-[10px] font-semibold transition-colors border-none cursor-pointer ${
                  viewMode === 'sub'
                    ? 'bg-[var(--primary-color)] text-white'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] bg-transparent'
                }`}
                onClick={() => setViewMode('sub')}
              >
                Sub-Worker
              </button>
            </div>
          )}

          {/* Filter selector */}
          <select
            className="flex-1 sm:flex-initial py-1 pl-2 pr-6 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] text-[0.6875rem] font-medium cursor-pointer appearance-none transition-all hover:border-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)]"
            style={{
              backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")",
              backgroundRepeat: 'no-repeat',
              backgroundPosition: 'right 6px center',
            }}
            value={filter}
            onChange={e => { setFilter(e.target.value); setCurrentPage(1); }}
          >
            {LOG_GROUPS.map(g => (
              <option key={g.id} value={`group:${g.id}`}>
                {t(`logsTab.${g.labelKey}`)} — {t(`logsTab.${g.descKey}`)}
              </option>
            ))}
            <option disabled>{'─'.repeat(20)}</option>
            {ALL_LEVELS.map(l => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>

          <button
            className={cn(
              "h-7 px-2.5 rounded-md bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.6875rem] font-medium cursor-pointer transition-all border border-[var(--border-color)] inline-flex items-center gap-1.5",
              loading && "opacity-60 pointer-events-none",
            )}
            onClick={() => fetchLogs(currentPage)}
            disabled={loading}
          >
            <RefreshCw size={11} className={loading ? 'animate-spin' : ''} /> {t('common.refresh')}
          </button>

          {/* Close detail panel button */}
          {selectedEntry && (
            <button
              onClick={() => setSelectedIdx(null)}
              className="h-7 w-7 rounded-md bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)] text-[var(--text-muted)] flex items-center justify-center transition-all border border-[var(--border-color)] cursor-pointer"
              title="Close detail panel"
            >
              <PanelRightClose size={13} />
            </button>
          )}
        </div>
      </div>

      {/* ── Context band: env / role / session_type for the target session ── */}
      {contextSession && (
        <div className="shrink-0 flex flex-wrap items-center gap-1.5 px-3 md:px-4 py-1.5 border-b border-[var(--border-color)] bg-[var(--bg-primary)]">
          {contextSession.env_id && (
            <span
              className="inline-flex items-center gap-1 px-1.5 py-[1px] rounded border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[10px] font-medium text-[var(--text-secondary)]"
              title={contextSession.env_id}
            >
              <span className="text-[var(--text-muted)]">{t('logsTab.contextEnv')}</span>
              <span className="font-mono text-[var(--text-primary)] max-w-[180px] truncate">{contextSession.env_id}</span>
            </span>
          )}
          {contextSession.role && (
            <span className="inline-flex items-center gap-1 px-1.5 py-[1px] rounded border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[10px] font-medium text-[var(--text-secondary)]">
              <span className="text-[var(--text-muted)]">{t('logsTab.contextRole')}</span>
              <span className="font-mono text-[var(--text-primary)]">{contextSession.role}</span>
            </span>
          )}
          {contextSession.session_type && (
            <span className="inline-flex items-center gap-1 px-1.5 py-[1px] rounded border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[10px] font-medium text-[var(--text-secondary)]">
              <span className="text-[var(--text-muted)]">{t('logsTab.contextSessionType')}</span>
              <span className="font-mono text-[var(--text-primary)]">{contextSession.session_type}</span>
            </span>
          )}
          {contextSession.linked_session_id && (
            <span
              className="inline-flex items-center gap-1 px-1.5 py-[1px] rounded border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[10px] font-medium text-[var(--text-secondary)]"
              title={contextSession.linked_session_id}
            >
              <span className="text-[var(--text-muted)]">{t('logsTab.contextLinked')}</span>
              <span className="font-mono text-[var(--text-primary)] max-w-[140px] truncate">{contextSession.linked_session_id}</span>
            </span>
          )}
        </div>
      )}

      {/* ── Main content: Split pane ── */}
      <div className="flex-1 flex min-h-0 relative">
        {/* ── Left pane: Log entry list ── */}
        <div
          className="flex flex-col min-w-0 min-h-0"
          style={{
            width: selectedEntry && !isMobile ? `${100 - detailPanelWidth}%` : '100%',
            transition: isResizing ? 'none' : 'width 0.2s ease',
          }}
        >
          {/* Entry list */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-1.5">
            {entries.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 px-4">
                <ScrollText size={32} className="text-[var(--text-muted)] opacity-30 mb-3" />
                <p className="text-[0.8125rem] text-[var(--text-muted)]">
                  {loading ? 'Loading...' : t('logsTab.noLogs')}
                </p>
              </div>
            ) : (
              <div className="space-y-[2px]">
                {entries.map((entry, idx) => (
                  <LogEntryCard
                    key={`${currentPage}-${idx}`}
                    entry={entry}
                    isSelected={selectedIdx === idx}
                    onClick={() => {
                      if (selectedIdx === idx) {
                        setSelectedIdx(null);
                      } else {
                        setSelectedIdx(idx);
                      }
                    }}
                  />
                ))}
              </div>
            )}
          </div>

          {/* ── Pagination bar ── */}
          {totalEntries > 0 && (
            <div className="shrink-0 flex flex-col sm:flex-row items-start sm:items-center justify-between px-3 py-1.5 gap-1 border-t border-[var(--border-color)] bg-[var(--bg-secondary)]">
              <span className="text-[0.625rem] text-[var(--text-muted)]">
                {pageStart}–{pageEnd} of {totalEntries.toLocaleString()} entries (newest first)
              </span>
              <div className="flex items-center gap-0.5">
                <button
                  className="w-8 h-8 md:w-7 md:h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-30 disabled:pointer-events-none border-none bg-transparent cursor-pointer"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage(1)}
                  title="First page"
                >
                  <ChevronsLeft size={13} />
                </button>
                <button
                  className="w-8 h-8 md:w-7 md:h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-30 disabled:pointer-events-none border-none bg-transparent cursor-pointer"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                  title="Previous page"
                >
                  <ChevronLeft size={13} />
                </button>

                {/* Page number buttons — fewer on mobile */}
                {(() => {
                  const pages: number[] = [];
                  const maxVisible = isMobile ? 3 : 5;
                  let start = Math.max(1, currentPage - Math.floor(maxVisible / 2));
                  const end = Math.min(totalPages, start + maxVisible - 1);
                  if (end - start + 1 < maxVisible) start = Math.max(1, end - maxVisible + 1);
                  for (let i = start; i <= end; i++) pages.push(i);
                  return pages.map(p => (
                    <button
                      key={p}
                      className={cn(
                        "w-8 h-8 md:w-7 md:h-7 rounded-md flex items-center justify-center text-[0.6875rem] font-medium transition-colors border-none cursor-pointer",
                        p === currentPage
                          ? "bg-[var(--primary-color)] text-white"
                          : "text-[var(--text-secondary)] bg-transparent hover:bg-[var(--bg-hover)]",
                      )}
                      onClick={() => setCurrentPage(p)}
                    >
                      {p}
                    </button>
                  ));
                })()}

                <button
                  className="w-8 h-8 md:w-7 md:h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-30 disabled:pointer-events-none border-none bg-transparent cursor-pointer"
                  disabled={currentPage >= totalPages}
                  onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                  title="Next page"
                >
                  <ChevronRight size={13} />
                </button>
                <button
                  className="w-8 h-8 md:w-7 md:h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-colors disabled:opacity-30 disabled:pointer-events-none border-none bg-transparent cursor-pointer"
                  disabled={currentPage >= totalPages}
                  onClick={() => setCurrentPage(totalPages)}
                  title="Last page"
                >
                  <ChevronsRight size={13} />
                </button>
              </div>
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

        {/* ── Right pane: Detail panel — overlay on mobile ── */}
        {selectedEntry && (
          isMobile ? (
            <div className="fixed inset-0 z-50 flex flex-col bg-[var(--bg-primary)]">
              <div className="shrink-0 flex items-center justify-between px-3 py-2 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
                <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">Detail</span>
                <button
                  onClick={() => setSelectedIdx(null)}
                  className="h-8 w-8 rounded-md bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)] text-[var(--text-muted)] flex items-center justify-center transition-all border border-[var(--border-color)] cursor-pointer"
                >
                  <X size={16} />
                </button>
              </div>
              <div className="flex-1 min-h-0 overflow-auto">
                <StepDetailPanel
                  entry={selectedEntry}
                  allEntries={entries}
                  onClose={() => setSelectedIdx(null)}
                />
              </div>
            </div>
          ) : (
            <div
              className="min-w-0 border-l border-[var(--border-color)]"
              style={{
                width: `${detailPanelWidth}%`,
                transition: isResizing ? 'none' : 'width 0.2s ease',
              }}
            >
              <StepDetailPanel
                entry={selectedEntry}
                allEntries={entries}
                onClose={() => setSelectedIdx(null)}
              />
            </div>
          )
        )}
      </div>
    </div>
  );
}
