'use client';

import { useMemo, useRef, useEffect, useCallback, useState } from 'react';
import type { LogEntry, LogEntryMetadata } from '@/types';
import {
  Terminal,
  Wrench,
  ChevronDown,
  ChevronRight,
  Hash,
  Zap,
  MessageSquare,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Eye,
  Send,
  Plus,
  Minus,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Lock,
  ShieldOff,
} from 'lucide-react';

// ── Level metadata ──
const LEVEL_CONFIG: Record<string, { icon: typeof Terminal; color: string; bgColor: string; label: string }> = {
  COMMAND:  { icon: Send,          color: '#10b981', bgColor: 'rgba(16,185,129,0.08)',  label: 'Command' },
  RESPONSE: { icon: MessageSquare, color: '#a855f7', bgColor: 'rgba(168,85,247,0.08)', label: 'Response' },
  TOOL:     { icon: Wrench,        color: '#22d3ee', bgColor: 'rgba(34,211,238,0.08)', label: 'Tool' },
  TOOL_RES: { icon: CheckCircle2,  color: '#06b6d4', bgColor: 'rgba(6,182,212,0.06)',  label: 'Result' },
  ITER:     { icon: Hash,          color: '#fb923c', bgColor: 'rgba(251,146,60,0.08)', label: 'Iteration' },
  STAGE:    { icon: Zap,           color: '#8b5cf6', bgColor: 'rgba(139,92,246,0.08)', label: 'Stage' },
  // Legacy rows — same visual so mixed-era timelines stay coherent.
  GRAPH:    { icon: Zap,           color: '#8b5cf6', bgColor: 'rgba(139,92,246,0.08)', label: 'Stage' },
  ERROR:    { icon: XCircle,       color: '#ef4444', bgColor: 'rgba(239,68,68,0.10)',  label: 'Error' },
  WARNING:  { icon: AlertTriangle, color: '#f59e0b', bgColor: 'rgba(245,158,11,0.08)', label: 'Warning' },
  INFO:     { icon: Eye,           color: '#3b82f6', bgColor: 'rgba(59,130,246,0.08)', label: 'Info' },
  DEBUG:    { icon: Terminal,      color: '#71717a', bgColor: 'rgba(113,113,122,0.08)', label: 'Debug' },
  STREAM:   { icon: Terminal,      color: '#94a3b8', bgColor: 'rgba(148,163,184,0.06)', label: 'Stream' },
};

// Primary levels shown by default
const PRIMARY_LEVELS = new Set([
  'COMMAND', 'RESPONSE', 'ERROR', 'WARNING', 'STAGE', 'GRAPH', 'TOOL', 'ITER',
]);

/**
 * Visual override for Stage 11 (tool_review) events. The backend emits
 * three flavours through `session_logger.log_stage_event`:
 *   - `tool_review_flag`    — one per reviewer hit, severity-coloured.
 *   - `tool_review_error`   — a reviewer raised; render as warning.
 *   - `tool_review_summary` — N flags this turn, dashboard hint.
 * Returning ``null`` falls back to the generic STAGE rendering.
 */
type ReviewVisual = {
  icon: typeof Terminal;
  color: string;
  bgColor: string;
  label: string;
  description: string;
};

function getToolReviewVisual(meta: LogEntryMetadata | undefined): ReviewVisual | null {
  if (!meta) return null;
  const evt = meta.event_type;
  const data = (meta.data || {}) as Record<string, unknown>;

  // G6.6: Stage 4 guard escalations + Stage 10 hook blocks surface as
  // ``loop_signal`` events (agent_session bridges loop.escalate /
  // loop.error). Render with a Lock / ShieldOff so operators can spot
  // permission / hook denials at a glance instead of fishing through
  // generic STAGE rows.
  if (evt === 'loop_signal') {
    const signal = (typeof data.signal === 'string' ? data.signal : '').toLowerCase();
    if (signal.includes('permission')) {
      // PR-E.2.3 — when the executor includes matched_rule details on
      // the loop event, splice them into the description so operators
      // see *which* rule fired without opening the detail panel.
      const matched = data.matched_rule as Record<string, unknown> | undefined;
      const ruleSummary = matched
        ? ` · rule [${String(matched.tool_name ?? '*')}` +
          (matched.pattern ? ` ${String(matched.pattern)}` : '') +
          `→${String(matched.behavior ?? 'deny')}` +
          (matched.source ? ` from ${String(matched.source)}` : '') + ']'
        : '';
      return {
        icon: Lock,
        color: '#ef4444',
        bgColor: 'rgba(239,68,68,0.10)',
        label: 'Denied',
        description: `Permission denied: ${signal}${ruleSummary}`,
      };
    }
    if (signal.includes('hook')) {
      return {
        icon: ShieldOff,
        color: '#ef4444',
        bgColor: 'rgba(239,68,68,0.10)',
        label: 'Hook block',
        description: `Hook blocked: ${signal}`,
      };
    }
    if (signal.includes('budget') || signal.includes('iteration')) {
      return {
        icon: ShieldOff,
        color: '#f59e0b',
        bgColor: 'rgba(245,158,11,0.10)',
        label: 'Guard',
        description: `Guard escalation: ${signal}`,
      };
    }
    // Generic loop signal — neutral icon, amber tone.
    return {
      icon: ShieldAlert,
      color: '#f59e0b',
      bgColor: 'rgba(245,158,11,0.10)',
      label: 'Loop signal',
      description: signal || 'loop escalation',
    };
  }

  // PR-E.2.3 — Stage 4 guard outcomes (permission/iteration/budget).
  if (evt === 'guard_event') {
    const guardName = typeof data.guard_name === 'string' ? data.guard_name : 'guard';
    const message = typeof data.message === 'string' ? data.message : '';
    const passed = data.passed === true;
    const isPermission = guardName === 'permission';
    return {
      icon: isPermission ? Lock : ShieldAlert,
      color: passed ? '#f59e0b' : '#ef4444',
      bgColor: passed ? 'rgba(245,158,11,0.10)' : 'rgba(239,68,68,0.10)',
      label: passed ? `Guard warn · ${guardName}` : `Guard reject · ${guardName}`,
      description: message || `${guardName} ${passed ? 'warned' : 'rejected'}`,
    };
  }

  if (evt !== 'tool_review_flag' && evt !== 'tool_review_error' && evt !== 'tool_review_summary') {
    return null;
  }

  if (evt === 'tool_review_summary') {
    const flags = typeof data.flags === 'number' ? data.flags : 0;
    return {
      icon: ShieldCheck,
      color: '#f59e0b',
      bgColor: 'rgba(245,158,11,0.10)',
      label: 'Review',
      description: `Tool review: ${flags} flag${flags === 1 ? '' : 's'} this turn`,
    };
  }

  if (evt === 'tool_review_error') {
    const reviewer = typeof data.reviewer === 'string' ? data.reviewer : 'unknown';
    const err = typeof data.error === 'string' ? data.error : 'reviewer crashed';
    return {
      icon: ShieldX,
      color: '#ef4444',
      bgColor: 'rgba(239,68,68,0.10)',
      label: 'Review error',
      description: `${reviewer}: ${err}`,
    };
  }

  // tool_review_flag — colour by severity.
  const severity = (typeof data.severity === 'string' ? data.severity : 'info').toLowerCase();
  const reviewer = typeof data.reviewer === 'string' ? data.reviewer : 'unknown';
  const reason = typeof data.reason === 'string' ? data.reason : '';
  const sev = severity === 'critical' || severity === 'block' || severity === 'error'
    ? { icon: ShieldX,     color: '#ef4444', bgColor: 'rgba(239,68,68,0.10)' }
    : severity === 'warn' || severity === 'warning'
      ? { icon: ShieldAlert, color: '#f59e0b', bgColor: 'rgba(245,158,11,0.10)' }
      : { icon: ShieldCheck, color: '#0ea5e9', bgColor: 'rgba(14,165,233,0.10)' };
  return {
    ...sev,
    label: `Flag · ${severity}`,
    description: `${reviewer}${reason ? `: ${reason}` : ''}`,
  };
}

function formatShortTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return ts.slice(11, 19);
  }
}

// ── Get description for a log entry ──
function getStepDescription(entry: LogEntry): string {
  const meta = entry.metadata as LogEntryMetadata | undefined;

  if (entry.level === 'TOOL' && meta?.tool_name) {
    // Show tool name and detail for tool calls
    if (meta.file_changes) {
      const fc = meta.file_changes;
      const filename = fc.file_path.replace(/\\/g, '/').split('/').pop() || fc.file_path;
      return `${meta.tool_name}: ${filename}`;
    }
    if (meta.command_data) {
      const cmd = meta.command_data.command;
      return `${meta.tool_name}: ${cmd.length > 60 ? cmd.slice(0, 60) + '...' : cmd}`;
    }
    if (meta.file_read) {
      const filename = meta.file_read.file_path.replace(/\\/g, '/').split('/').pop() || '';
      return `${meta.tool_name}: ${filename}`;
    }
    return meta.detail || meta.tool_name;
  }

  if (entry.level === 'TOOL_RES' && meta?.tool_name) {
    const status = meta.is_error ? 'ERROR' : 'OK';
    const dur = meta.duration_ms != null ? ` (${meta.duration_ms}ms)` : '';
    return `${meta.tool_name}: ${status}${dur}`;
  }

  if (entry.level === 'ITER' && meta?.iteration != null) {
    const status = meta.success ? '✅' : '❌';
    return `Iteration #${meta.iteration} ${status}`;
  }

  if (entry.level === 'GRAPH' && meta?.event_type) {
    return meta.event_type + (meta.node_name ? `: ${meta.node_name}` : '');
  }

  // Generic: strip prefixes and truncate
  const msg = entry.message
    .replace(/^PROMPT:\s*/, '')
    .replace(/^SUCCESS:\s*/, '')
    .replace(/^ERROR:\s*/, '')
    .replace(/^FAILED:\s*/, '');
  return msg.length > 80 ? msg.slice(0, 80) + '...' : msg;
}

// ── File change badge for tool entries ──
function FileChangeBadge({ meta }: { meta: LogEntryMetadata }) {
  if (!meta.file_changes) return null;
  const fc = meta.file_changes;
  return (
    <span className="inline-flex items-center gap-1.5 ml-1">
      {fc.lines_added > 0 && (
        <span className="inline-flex items-center gap-[2px] text-[0.5rem] font-mono font-bold text-[var(--success-color,#22c55e)]">
          <Plus size={8} />{fc.lines_added}
        </span>
      )}
      {fc.lines_removed > 0 && (
        <span className="inline-flex items-center gap-[2px] text-[0.5rem] font-mono font-bold text-[var(--danger-color,#ef4444)]">
          <Minus size={8} />{fc.lines_removed}
        </span>
      )}
    </span>
  );
}

// ── Single Timeline Entry ──
interface TimelineEntryProps {
  entry: LogEntry;
  index: number;
  isSelected: boolean;
  isLast: boolean;
  durationMs: number | null;
  onClick: (index: number) => void;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const sec = ms / 1000;
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}m ${s}s`;
}

function TimelineEntry({ entry, index, isSelected, isLast, durationMs, onClick }: TimelineEntryProps) {
  const meta = entry.metadata as LogEntryMetadata | undefined;
  // Stage-11 tool_review entries get a richer severity-coloured rendering;
  // everything else falls through to the generic per-level config.
  const reviewOverride = useMemo(() => getToolReviewVisual(meta), [meta]);
  const baseConfig = LEVEL_CONFIG[entry.level] || LEVEL_CONFIG.DEBUG;
  const config = reviewOverride ?? baseConfig;
  const Icon = config.icon;
  const description = useMemo(
    () => reviewOverride ? reviewOverride.description : getStepDescription(entry),
    [entry, reviewOverride],
  );
  const hasDetail = !!reviewOverride
    || ['TOOL', 'ITER', 'GRAPH', 'COMMAND', 'RESPONSE', 'ERROR'].includes(entry.level);

  return (
    <div
      className={`flex gap-0 transition-all group ${
        hasDetail ? 'cursor-pointer' : 'cursor-default'
      } ${isSelected ? 'bg-[rgba(59,130,246,0.08)]' : 'hover:bg-[var(--bg-tertiary)]'}`}
      onClick={() => hasDetail && onClick(index)}
    >
      {/* Timeline connector */}
      <div className="w-[36px] shrink-0 flex flex-col items-center relative">
        {/* Vertical line */}
        {!isLast && (
          <div
            className="absolute top-[22px] bottom-0 w-[1.5px]"
            style={{ backgroundColor: `${config.color}20` }}
          />
        )}
        {/* Icon node */}
        <div
          className="relative z-10 mt-[8px] w-[18px] h-[18px] rounded-full flex items-center justify-center shrink-0 border"
          style={{
            backgroundColor: isSelected ? config.color : config.bgColor,
            borderColor: `${config.color}40`,
          }}
        >
          <Icon size={9} style={{ color: isSelected ? 'white' : config.color }} />
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 py-2 md:py-[6px] pr-3">
        <div className="flex items-center gap-1.5 mb-[1px] flex-wrap">
          <span
            className="text-[0.5rem] font-bold uppercase tracking-wider shrink-0"
            style={{ color: config.color }}
          >
            {config.label}
          </span>
          <span className="text-[0.5rem] text-[var(--text-muted)] font-mono tabular-nums opacity-50 shrink-0">
            {formatShortTime(entry.timestamp)}
          </span>
          {durationMs != null && durationMs > 0 && (
            <span className="text-[0.5rem] font-mono tabular-nums text-[var(--text-muted)] opacity-70 shrink-0">
              {formatDuration(durationMs)}
            </span>
          )}
          {meta?.file_changes && <FileChangeBadge meta={meta} />}
          {hasDetail && (
            <ChevronRight
              size={9}
              className={`ml-auto shrink-0 transition-transform ${
                isSelected ? 'text-[var(--primary-color)] rotate-90' : 'text-[var(--text-muted)] opacity-0 group-hover:opacity-50 max-md:opacity-50'
              }`}
            />
          )}
        </div>
        <div
          className="text-[0.75rem] md:text-[0.6875rem] leading-snug truncate"
          style={{
            color: entry.level === 'ERROR' ? 'var(--danger-color)' :
              entry.level === 'WARNING' ? 'var(--warning-color)' :
              'var(--text-secondary)',
          }}
        >
          {description}
        </div>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// Main ExecutionTimeline Component
// ════════════════════════════════════════════════════════════════
export interface ExecutionTimelineProps {
  entries: LogEntry[];
  selectedIndex: number | null;
  onSelectEntry: (index: number | null) => void;
  showAllLevels: boolean;
  onToggleShowAll: () => void;
  isExecuting?: boolean;
  statusText?: string;
}

export default function ExecutionTimeline({
  entries,
  selectedIndex,
  onSelectEntry,
  showAllLevels,
  onToggleShowAll,
  isExecuting,
  statusText,
}: ExecutionTimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  // Live timer tick — refreshes every second while executing so last entry duration updates
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!isExecuting) return;
    const id = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, [isExecuting]);

  // Filter entries
  const visibleEntries = useMemo(
    () => showAllLevels ? entries : entries.filter((e) => PRIMARY_LEVELS.has(e.level)),
    [entries, showAllLevels],
  );
  // Count entries that are NOT primary (would be hidden in filtered mode)
  const detailLevelCount = useMemo(
    () => entries.filter((e) => !PRIMARY_LEVELS.has(e.level)).length,
    [entries],
  );

  // Map visible index → original index
  const visibleToOriginalIndex = useMemo(() => {
    if (showAllLevels) return visibleEntries.map((_, i) => i);
    return visibleEntries.map((ve) => entries.indexOf(ve));
  }, [entries, visibleEntries, showAllLevels]);

  // Auto-scroll to bottom
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [entries.length]);

  const handleClick = useCallback(
    (visibleIdx: number) => {
      const originalIdx = visibleToOriginalIndex[visibleIdx];
      if (selectedIndex === originalIdx) {
        onSelectEntry(null); // Toggle off
      } else {
        onSelectEntry(originalIdx);
      }
    },
    [visibleToOriginalIndex, selectedIndex, onSelectEntry],
  );

  return (
    <div className="flex flex-col h-full">
      {/* Timeline header */}
      <div className="shrink-0 flex items-center justify-between px-3 py-1.5 bg-[var(--bg-secondary)] border-b border-[var(--border-color)]">
        <span className="text-[0.625rem] text-[var(--text-muted)] uppercase tracking-wider font-semibold flex items-center gap-1.5">
          <Terminal size={9} className="opacity-60" />
          Execution Log
          <span className="font-normal opacity-70">
            ({visibleEntries.length}{detailLevelCount > 0 && !showAllLevels ? `/${entries.length}` : ''})
          </span>
        </span>
        {detailLevelCount > 0 && (
          <button
            className="text-[0.625rem] text-[var(--text-muted)] hover:text-[var(--primary-color)] transition-colors flex items-center gap-0.5 font-medium cursor-pointer border-none bg-transparent p-0"
            onClick={onToggleShowAll}
          >
            {showAllLevels ? <ChevronDown size={9} /> : <ChevronRight size={9} />}
            {showAllLevels ? 'Hide' : 'Show'} detail ({detailLevelCount})
          </button>
        )}
      </div>

      {/* Timeline entries */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {visibleEntries.map((entry, i) => {
          const nextTs = i < visibleEntries.length - 1
            ? new Date(visibleEntries[i + 1].timestamp).getTime()
            : isExecuting ? Date.now() : null;
          const curTs = new Date(entry.timestamp).getTime();
          const dur = nextTs != null ? nextTs - curTs : null;
          return (
            <TimelineEntry
              key={i}
              entry={entry}
              index={i}
              isSelected={selectedIndex === visibleToOriginalIndex[i]}
              isLast={i === visibleEntries.length - 1 && !isExecuting}
              durationMs={dur}
              onClick={handleClick}
            />
          );
        })}

        {/* Running indicator */}
        {isExecuting && (
          <div className="flex items-center gap-3 px-3 py-3">
            <div className="w-[36px] shrink-0 flex flex-col items-center relative">
              <div className="w-[18px] h-[18px] rounded-full flex items-center justify-center bg-[rgba(59,130,246,0.15)] border border-[rgba(59,130,246,0.3)]">
                <div className="w-2 h-2 rounded-full bg-[var(--primary-color)] animate-pulse" />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex gap-1">
                <span className="w-1 h-1 rounded-full bg-[var(--primary-color)] animate-bounce [animation-delay:0ms]" />
                <span className="w-1 h-1 rounded-full bg-[var(--primary-color)] animate-bounce [animation-delay:150ms]" />
                <span className="w-1 h-1 rounded-full bg-[var(--primary-color)] animate-bounce [animation-delay:300ms]" />
              </div>
              <span className="text-[0.6875rem] text-[var(--text-muted)]">{statusText || 'Executing...'}</span>
            </div>
          </div>
        )}

        <div ref={endRef} />
      </div>
    </div>
  );
}
