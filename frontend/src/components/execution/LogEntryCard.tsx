'use client';

import { useMemo } from 'react';
import type { LogEntry, LogEntryMetadata } from '@/types';
import {
  Terminal,
  Wrench,
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
  ChevronRight,
  FileCode2,
  Clock,
} from 'lucide-react';

// ── Level visual config (same system as ExecutionTimeline) ──
const LEVEL_CONFIG: Record<string, { icon: typeof Terminal; color: string; bgColor: string; label: string }> = {
  COMMAND:   { icon: Send,          color: '#10b981', bgColor: 'rgba(16,185,129,0.08)',   label: 'Command' },
  RESPONSE:  { icon: MessageSquare, color: '#a855f7', bgColor: 'rgba(168,85,247,0.08)',  label: 'Response' },
  TOOL:      { icon: Wrench,        color: '#22d3ee', bgColor: 'rgba(34,211,238,0.08)',   label: 'Tool' },
  TOOL_RES:  { icon: CheckCircle2,  color: '#06b6d4', bgColor: 'rgba(6,182,212,0.06)',    label: 'Result' },
  ITER:      { icon: Hash,          color: '#fb923c', bgColor: 'rgba(251,146,60,0.08)',   label: 'Iteration' },
  GRAPH:     { icon: Zap,           color: '#8b5cf6', bgColor: 'rgba(139,92,246,0.08)',   label: 'Graph' },
  ERROR:     { icon: XCircle,       color: '#ef4444', bgColor: 'rgba(239,68,68,0.10)',    label: 'Error' },
  WARNING:   { icon: AlertTriangle, color: '#f59e0b', bgColor: 'rgba(245,158,11,0.08)',   label: 'Warning' },
  INFO:      { icon: Eye,           color: '#3b82f6', bgColor: 'rgba(59,130,246,0.08)',   label: 'Info' },
  DEBUG:     { icon: Terminal,      color: '#71717a', bgColor: 'rgba(113,113,122,0.08)',   label: 'Debug' },
  STREAM:    { icon: Terminal,      color: '#94a3b8', bgColor: 'rgba(148,163,184,0.06)',   label: 'Stream' },
};

// ── Format timestamp ──
function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return ts.slice(11, 19);
  }
}

// ── Structured description for an entry ──
function getEntryDescription(entry: LogEntry): string {
  const meta = entry.metadata as LogEntryMetadata | undefined;

  if (entry.level === 'TOOL' && meta?.tool_name) {
    if (meta.file_changes) {
      const fc = meta.file_changes;
      const filename = fc.file_path.replace(/\\/g, '/').split('/').pop() || fc.file_path;
      const op = fc.operation === 'create' ? 'Create' : fc.operation === 'edit' ? 'Edit' : fc.operation === 'multi_edit' ? 'Multi-edit' : 'Write';
      return `${op}: ${filename}`;
    }
    if (meta.command_data) {
      const cmd = meta.command_data.command;
      return `Bash: \`${cmd.length > 80 ? cmd.slice(0, 80) + '...' : cmd}\``;
    }
    if (meta.file_read) {
      const filename = meta.file_read.file_path.replace(/\\/g, '/').split('/').pop() || '';
      const lines = meta.file_read.start_line
        ? ` (L${meta.file_read.start_line}${meta.file_read.end_line ? `-${meta.file_read.end_line}` : '+'})`
        : '';
      return `Read: ${filename}${lines}`;
    }
    return meta.detail || meta.tool_name;
  }

  if (entry.level === 'TOOL_RES' && meta?.tool_name) {
    const status = meta.is_error ? 'ERROR' : 'OK';
    const dur = meta.duration_ms != null ? ` (${meta.duration_ms}ms)` : '';
    return `${meta.tool_name}: ${status}${dur}`;
  }

  if (entry.level === 'ITER' && meta?.iteration != null) {
    const status = meta.success ? '✅' : meta.success === false ? '❌' : '';
    const dur = meta.duration_ms ? ` — ${(meta.duration_ms / 1000).toFixed(1)}s` : '';
    const cost = meta.cost_usd ? ` — $${meta.cost_usd.toFixed(4)}` : '';
    return `Iteration #${meta.iteration} ${status}${dur}${cost}`;
  }

  if (entry.level === 'GRAPH' && meta?.event_type) {
    return meta.event_type + (meta.node_name ? `: ${meta.node_name}` : '');
  }

  // Delegation events — render as "<tag> <arrow> <peer>" regardless of level.
  const event = meta && typeof (meta as Record<string, unknown>).event === 'string'
    ? ((meta as Record<string, unknown>).event as string)
    : undefined;
  if (event === 'delegation.sent' || event === 'delegation.received') {
    const m = meta as Record<string, unknown>;
    const tag = typeof m.tag === 'string' ? m.tag : '';
    const peerId = event === 'delegation.sent' ? m.to_session_id : m.from_session_id;
    const peer = typeof peerId === 'string' ? `${peerId.slice(0, 8)}…` : '';
    const arrow = event === 'delegation.sent' ? '→' : '←';
    const taskId = typeof m.task_id === 'string' ? ` (task ${m.task_id})` : '';
    return `${tag} ${arrow} ${peer}${taskId}`.trim();
  }

  // Generic: strip prefixes and truncate
  const msg = entry.message
    .replace(/^PROMPT:\s*/, '')
    .replace(/^SUCCESS:\s*/, '')
    .replace(/^ERROR:\s*/, '')
    .replace(/^FAILED:\s*/, '');
  return msg.length > 120 ? msg.slice(0, 120) + '...' : msg;
}

// ── File change badges ──
function FileChangeBadges({ meta }: { meta: LogEntryMetadata }) {
  if (!meta.file_changes) return null;
  const fc = meta.file_changes;
  return (
    <span className="inline-flex items-center gap-2 ml-auto shrink-0">
      {fc.lines_added > 0 && (
        <span className="inline-flex items-center gap-[2px] text-[0.625rem] font-mono font-bold text-[var(--success-color,#22c55e)]">
          <Plus size={9} />{fc.lines_added}
        </span>
      )}
      {fc.lines_removed > 0 && (
        <span className="inline-flex items-center gap-[2px] text-[0.625rem] font-mono font-bold text-[var(--danger-color,#ef4444)]">
          <Minus size={9} />{fc.lines_removed}
        </span>
      )}
    </span>
  );
}

// ── Tool name pill ──
function ToolNamePill({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-[1px] rounded bg-[rgba(34,211,238,0.1)] text-[#22d3ee] text-[0.625rem] font-semibold shrink-0">
      <Wrench size={9} />
      {name}
    </span>
  );
}

// ════════════════════════════════════════════════════════════════
// LogEntryCard
// ════════════════════════════════════════════════════════════════
export interface LogEntryCardProps {
  entry: LogEntry;
  isSelected: boolean;
  onClick: () => void;
}

export default function LogEntryCard({ entry, isSelected, onClick }: LogEntryCardProps) {
  const config = LEVEL_CONFIG[entry.level] || LEVEL_CONFIG.DEBUG;
  const Icon = config.icon;
  const meta = entry.metadata as LogEntryMetadata | undefined;
  const description = useMemo(() => getEntryDescription(entry), [entry]);
  const hasDetail = ['TOOL', 'ITER', 'GRAPH', 'COMMAND', 'RESPONSE', 'ERROR', 'TOOL_RES'].includes(entry.level);

  return (
    <div
      className={`flex items-start gap-3 px-3 py-2.5 rounded-lg transition-all group ${
        hasDetail ? 'cursor-pointer' : 'cursor-default'
      } ${isSelected
        ? 'bg-[rgba(59,130,246,0.10)] ring-1 ring-[rgba(59,130,246,0.3)]'
        : 'hover:bg-[var(--bg-tertiary)]'
      }`}
      onClick={() => hasDetail && onClick()}
    >
      {/* Icon */}
      <div
        className="mt-[2px] w-[22px] h-[22px] rounded-full flex items-center justify-center shrink-0 border"
        style={{
          backgroundColor: isSelected ? config.color : config.bgColor,
          borderColor: `${config.color}40`,
        }}
      >
        <Icon size={10} style={{ color: isSelected ? 'white' : config.color }} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Top row: level badge, timestamp, tool name, change badges */}
        <div className="flex items-center gap-2 mb-0.5 flex-wrap">
          <span
            className="text-[0.5625rem] font-bold uppercase tracking-wider shrink-0"
            style={{ color: config.color }}
          >
            {config.label}
          </span>
          <span className="text-[0.5625rem] text-[var(--text-muted)] font-mono tabular-nums opacity-60 shrink-0">
            {formatTimestamp(entry.timestamp)}
          </span>
          {meta?.tool_name && entry.level === 'TOOL' && (
            <ToolNamePill name={meta.tool_name} />
          )}
          {meta?.file_changes && <FileChangeBadges meta={meta} />}
          {meta?.duration_ms != null && entry.level !== 'TOOL' && (
            <span className="inline-flex items-center gap-0.5 text-[0.5625rem] text-[var(--text-muted)] ml-auto shrink-0">
              <Clock size={9} />{meta.duration_ms}ms
            </span>
          )}
          {hasDetail && (
            <ChevronRight
              size={10}
              className={`shrink-0 transition-transform ${
                isSelected
                  ? 'text-[var(--primary-color)] rotate-90'
                  : 'text-[var(--text-muted)] opacity-0 group-hover:opacity-50 max-md:opacity-50'
              } ${!meta?.file_changes && !meta?.duration_ms ? 'ml-auto' : ''}`}
            />
          )}
        </div>

        {/* Description */}
        <div
          className="text-[0.75rem] leading-snug truncate"
          style={{
            color: entry.level === 'ERROR' ? 'var(--danger-color)' :
              entry.level === 'WARNING' ? 'var(--warning-color)' :
              'var(--text-secondary)',
          }}
        >
          {description}
        </div>

        {/* File path subtitle for tool entries */}
        {meta?.file_changes?.file_path && (
          <div className="flex items-center gap-1 mt-0.5 text-[0.625rem] text-[var(--text-muted)] truncate">
            <FileCode2 size={9} className="shrink-0 opacity-60" />
            <span className="truncate opacity-70">{meta.file_changes.file_path}</span>
          </div>
        )}
      </div>
    </div>
  );
}
