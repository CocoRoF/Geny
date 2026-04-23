'use client';

import type { LogEntry, LogEntryMetadata } from '@/types';
import DiffViewer from './DiffViewer';
import CodeBlock from './CodeBlock';
import {
  X,
  FileCode2,
  Terminal,
  Eye,
  Wrench,
  CheckCircle2,
  XCircle,
  Clock,
  Hash,
  ChevronRight,
  Zap,
  AlertTriangle,
} from 'lucide-react';

// ── Tool result finder ──
function findToolResult(entries: LogEntry[], toolId?: string): LogEntry | undefined {
  if (!toolId) return undefined;
  return entries.find(
    (e) => e.level === 'TOOL_RES' && e.metadata?.tool_id === toolId,
  );
}

// ── JSON prettifier ──
function tryParseJSON(str: string): string {
  try {
    const obj = JSON.parse(str);
    return JSON.stringify(obj, null, 2);
  } catch {
    return str;
  }
}

// ── Timestamp formatter ──
function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
  } catch {
    return ts.slice(11, 23);
  }
}

// ── Metadata Row ──
function MetaRow({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start gap-2 py-1">
      <span className="text-[0.625rem] font-semibold uppercase tracking-wider text-[var(--text-muted)] shrink-0 w-[90px] pt-[1px]">
        {label}
      </span>
      <span className={`text-[0.6875rem] text-[var(--text-secondary)] break-all min-w-0 ${mono ? 'font-mono' : ''}`}>
        {value}
      </span>
    </div>
  );
}

// ── Section wrapper ──
function Section({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <div className="flex items-center gap-1.5 mb-2">
        {icon}
        <span className="text-[0.6875rem] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
          {title}
        </span>
      </div>
      {children}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// Tool Use Detail
// ════════════════════════════════════════════════════════════════
function ToolUseDetail({ entry, allEntries }: { entry: LogEntry; allEntries: LogEntry[] }) {
  const meta = entry.metadata as LogEntryMetadata;
  const toolName = meta?.tool_name || 'unknown';
  const toolResult = findToolResult(allEntries, meta?.tool_id);
  const resultMeta = toolResult?.metadata as LogEntryMetadata | undefined;

  return (
    <div className="space-y-4">
      {/* Tool info */}
      <Section title="Tool Call" icon={<Wrench size={12} className="text-[#22d3ee]" />}>
        <div className="bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)] p-3">
          <MetaRow label="Tool" value={<span className="font-semibold text-[#22d3ee]">{toolName}</span>} />
          {meta?.tool_id && <MetaRow label="ID" value={meta.tool_id} mono />}
          {meta?.detail && <MetaRow label="Detail" value={meta.detail} />}
          <MetaRow label="Time" value={formatTime(entry.timestamp)} mono />
        </div>
      </Section>

      {/* File diff display */}
      {meta?.file_changes && (
        <Section title="File Changes" icon={<FileCode2 size={12} className="text-[var(--warning-color)]" />}>
          <DiffViewer fileChanges={meta.file_changes} />
        </Section>
      )}

      {/* Command display */}
      {meta?.command_data && (
        <Section title="Command" icon={<Terminal size={12} className="text-[#10b981]" />}>
          <CodeBlock
            content={meta.command_data.command}
            variant="terminal"
            title={meta.command_data.working_dir ? `$ in ${meta.command_data.working_dir}` : '$ Command'}
          />
        </Section>
      )}

      {/* File read display */}
      {meta?.file_read && (
        <Section title="File Read" icon={<Eye size={12} className="text-[#3b82f6]" />}>
          <div className="bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)] p-3">
            <MetaRow label="File" value={meta.file_read.file_path} mono />
            {meta.file_read.start_line && (
              <MetaRow
                label="Lines"
                value={`${meta.file_read.start_line}${meta.file_read.end_line ? ` – ${meta.file_read.end_line}` : '+'}`}
                mono
              />
            )}
          </div>
        </Section>
      )}

      {/* Tool result */}
      {toolResult && (
        <Section
          title={resultMeta?.is_error ? 'Tool Error' : 'Tool Result'}
          icon={
            resultMeta?.is_error
              ? <XCircle size={12} className="text-[var(--danger-color)]" />
              : <CheckCircle2 size={12} className="text-[var(--success-color)]" />
          }
        >
          <div className={`rounded-lg border overflow-hidden ${
            resultMeta?.is_error
              ? 'border-[rgba(239,68,68,0.3)] bg-[rgba(239,68,68,0.04)]'
              : 'border-[var(--border-color)] bg-[var(--bg-secondary)]'
          }`}>
            {/* Result header */}
            <div className={`flex items-center justify-between px-3 py-1.5 border-b ${
              resultMeta?.is_error
                ? 'border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.06)]'
                : 'border-[var(--border-color)] bg-[var(--bg-tertiary)]'
            }`}>
              <span className={`text-[0.625rem] font-semibold uppercase tracking-wider ${
                resultMeta?.is_error ? 'text-[var(--danger-color)]' : 'text-[var(--text-muted)]'
              }`}>
                {resultMeta?.is_error ? 'Error' : 'Output'}
              </span>
              <div className="flex items-center gap-2">
                {resultMeta?.duration_ms != null && (
                  <span className="flex items-center gap-0.5 text-[0.5625rem] text-[var(--text-muted)]">
                    <Clock size={9} />{resultMeta.duration_ms}ms
                  </span>
                )}
                {resultMeta?.result_length != null && (
                  <span className="text-[0.5625rem] text-[var(--text-muted)]">
                    {resultMeta.result_length.toLocaleString()} chars
                  </span>
                )}
              </div>
            </div>

            {/* Result content — use CodeBlock for file read results, plain text otherwise */}
            {resultMeta?.result_preview ? (
              meta?.file_read?.file_path ? (
                <CodeBlock
                  content={resultMeta.result_preview}
                  filePath={meta.file_read.file_path}
                  startLine={meta.file_read.start_line || 1}
                />
              ) : meta?.command_data ? (
                <CodeBlock
                  content={resultMeta.result_preview}
                  variant="terminal"
                  title="Output"
                />
              ) : (
                <div className="px-3 py-2 max-h-[400px] overflow-auto">
                  <pre className="text-[0.6875rem] leading-relaxed font-mono text-[var(--text-secondary)] whitespace-pre-wrap break-words m-0">
                    {resultMeta.result_preview}
                  </pre>
                </div>
              )
            ) : (
              <div className="px-3 py-2 text-[0.6875rem] text-[var(--text-muted)] italic">
                No output
              </div>
            )}

            {resultMeta?.is_truncated && (
              <div className="flex items-center gap-1 px-3 py-1 bg-[rgba(245,158,11,0.04)] border-t border-[var(--border-color)] text-[0.5625rem] text-[var(--warning-color)]">
                <AlertTriangle size={9} />
                Output truncated ({resultMeta.result_length?.toLocaleString()} chars total)
              </div>
            )}
          </div>
        </Section>
      )}

      {/* Raw input preview (for tools without specific viewers) */}
      {!meta?.file_changes && !meta?.command_data && !meta?.file_read && meta?.input_preview && (
        <Section title="Input" icon={<ChevronRight size={12} className="text-[var(--text-muted)]" />}>
          <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 max-h-[300px] overflow-auto">
            <pre className="text-[0.6875rem] leading-relaxed font-mono text-[var(--text-secondary)] whitespace-pre-wrap break-words m-0">
              {tryParseJSON(meta.input_preview)}
            </pre>
          </div>
        </Section>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// Iteration Detail
// ════════════════════════════════════════════════════════════════
function IterationDetail({ entry }: { entry: LogEntry }) {
  const meta = entry.metadata as LogEntryMetadata;
  return (
    <div className="space-y-4">
      <Section title="Iteration" icon={<Hash size={12} className="text-[#fb923c]" />}>
        <div className="bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)] p-3">
          {meta?.iteration != null && <MetaRow label="Iteration" value={`#${meta.iteration}`} />}
          {meta?.success != null && (
            <MetaRow label="Status" value={
              <span className={meta.success ? 'text-[var(--success-color)]' : 'text-[var(--danger-color)]'}>
                {meta.success ? 'Success' : 'Failed'}
              </span>
            } />
          )}
          {meta?.duration_ms != null && <MetaRow label="Duration" value={`${meta.duration_ms}ms`} mono />}
          {meta?.cost_usd != null && <MetaRow label="Cost" value={`$${meta.cost_usd.toFixed(6)}`} mono />}
          {meta?.tool_call_count != null && <MetaRow label="Tool Calls" value={String(meta.tool_call_count)} />}
          {meta?.is_complete != null && <MetaRow label="Complete" value={meta.is_complete ? 'Yes' : 'No'} />}
          {meta?.stop_reason && <MetaRow label="Stop Reason" value={meta.stop_reason} />}
        </div>
      </Section>

      {meta?.preview && (
        <Section title="Output Preview" icon={<Eye size={12} className="text-[var(--text-muted)]" />}>
          <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 max-h-[400px] overflow-auto">
            <pre className="text-[0.6875rem] leading-relaxed text-[var(--text-secondary)] whitespace-pre-wrap break-words m-0">
              {meta.preview}
            </pre>
          </div>
        </Section>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// Stage Event Detail (also handles legacy GRAPH rows)
// ════════════════════════════════════════════════════════════════
function StageEventDetail({ entry }: { entry: LogEntry }) {
  const meta = entry.metadata as LogEntryMetadata;
  const stageName = meta?.stage_name || meta?.node_name;
  return (
    <div className="space-y-4">
      <Section title="Stage Event" icon={<Zap size={12} className="text-[#8b5cf6]" />}>
        <div className="bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)] p-3">
          {meta?.event_type && <MetaRow label="Event" value={meta.event_type} />}
          {meta?.stage_display_name && <MetaRow label="Stage" value={meta.stage_display_name} mono />}
          {!meta?.stage_display_name && stageName && <MetaRow label="Stage" value={stageName} mono />}
          {meta?.stage_order != null && <MetaRow label="Order" value={`#${meta.stage_order}`} mono />}
          {meta?.iteration != null && <MetaRow label="Iteration" value={`#${meta.iteration}`} mono />}
          {meta?.event_id && <MetaRow label="Event ID" value={meta.event_id} mono />}
          <MetaRow label="Time" value={formatTime(entry.timestamp)} mono />
        </div>
      </Section>

      {meta?.data && Object.keys(meta.data).length > 0 && (
        <Section title="Event Data" icon={<ChevronRight size={12} className="text-[var(--text-muted)]" />}>
          <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 max-h-[400px] overflow-auto">
            <pre className="text-[0.6875rem] leading-relaxed font-mono text-[var(--text-secondary)] whitespace-pre-wrap break-words m-0">
              {JSON.stringify(meta.data, null, 2)}
            </pre>
          </div>
        </Section>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// Generic Detail (COMMAND, RESPONSE, ERROR, etc.)
// ════════════════════════════════════════════════════════════════
function GenericDetail({ entry }: { entry: LogEntry }) {
  const meta = entry.metadata as LogEntryMetadata | undefined;
  const displayMsg = entry.message
    .replace(/^PROMPT:\s*/, '')
    .replace(/^SUCCESS:\s*/, '')
    .replace(/^ERROR:\s*/, '')
    .replace(/^FAILED:\s*/, '');

  // Pull a few high-signal fields out of the metadata for a quick
  // top-of-panel summary; the full metadata blob is rendered below as
  // formatted JSON so nothing is hidden. This is what surfaces the
  // routing details on entries like "[SUB_WORKER_RESULT] → d12cd2e2…"
  // (event=delegation.sent, to_session_id=…, tag=…) and
  // "Recipient busy — message queued to inbox" (event=inbox.delivered).
  const metaRecord = (meta ?? {}) as Record<string, unknown>;
  const event =
    typeof metaRecord.event === 'string' ? (metaRecord.event as string) : undefined;
  const tag =
    typeof metaRecord.tag === 'string' ? (metaRecord.tag as string) : undefined;
  const fromId =
    typeof metaRecord.from_session_id === 'string' ? (metaRecord.from_session_id as string) : undefined;
  const toId =
    typeof metaRecord.to_session_id === 'string' ? (metaRecord.to_session_id as string) : undefined;
  const errorField =
    typeof metaRecord.error === 'string' ? (metaRecord.error as string) : undefined;
  const fullMessageLen = entry.message?.length ?? 0;

  // Only render the JSON section when there's *more* metadata than
  // the small structured rows we already display, otherwise it's
  // visual noise.
  const interestingMetaKeys = Object.keys(metaRecord).filter(
    (k) => !['event', 'tag', 'from_session_id', 'to_session_id', 'error'].includes(k),
  );
  const hasExtraMeta = interestingMetaKeys.length > 0;

  return (
    <div className="space-y-4">
      <Section title={entry.level} icon={<ChevronRight size={12} className="text-[var(--text-muted)]" />}>
        <div className="bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)] p-3">
          <MetaRow label="Level" value={entry.level} />
          <MetaRow label="Time" value={formatTime(entry.timestamp)} mono />
          {event && <MetaRow label="Event" value={event} mono />}
          {tag && <MetaRow label="Tag" value={tag} mono />}
          {fromId && <MetaRow label="From" value={fromId} mono />}
          {toId && <MetaRow label="To" value={toId} mono />}
          {meta?.duration_ms != null && <MetaRow label="Duration" value={`${meta.duration_ms}ms`} mono />}
          {meta?.cost_usd != null && <MetaRow label="Cost" value={`$${meta.cost_usd.toFixed(6)}`} mono />}
          {fullMessageLen > 0 && (
            <MetaRow label="Message len" value={`${fullMessageLen} chars`} mono />
          )}
          {errorField && (
            <MetaRow
              label="Error"
              value={<span className="text-[var(--danger-color)]">{errorField}</span>}
            />
          )}
        </div>
      </Section>

      <Section title="Content" icon={<Eye size={12} className="text-[var(--text-muted)]" />}>
        <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 max-h-[600px] overflow-auto">
          <pre className="text-[0.75rem] leading-relaxed text-[var(--text-primary)] whitespace-pre-wrap break-words m-0">
            {displayMsg || <span className="text-[var(--text-muted)] italic">(no message body)</span>}
          </pre>
        </div>
      </Section>

      {hasExtraMeta && (
        <Section title="Metadata" icon={<Hash size={12} className="text-[var(--text-muted)]" />}>
          <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] px-3 py-2 max-h-[400px] overflow-auto">
            <pre className="text-[0.6875rem] leading-relaxed text-[var(--text-secondary)] whitespace-pre-wrap break-words m-0 font-mono">
              {JSON.stringify(metaRecord, null, 2)}
            </pre>
          </div>
        </Section>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// Main StepDetailPanel
// ════════════════════════════════════════════════════════════════
export interface StepDetailPanelProps {
  entry: LogEntry;
  allEntries: LogEntry[];
  onClose: () => void;
}

const LEVEL_LABELS: Record<string, { label: string; color: string }> = {
  TOOL: { label: 'Tool Call', color: '#22d3ee' },
  TOOL_RES: { label: 'Tool Result', color: '#06b6d4' },
  COMMAND: { label: 'Command', color: '#10b981' },
  RESPONSE: { label: 'Response', color: '#a855f7' },
  ERROR: { label: 'Error', color: '#ef4444' },
  WARNING: { label: 'Warning', color: '#f59e0b' },
  ITER: { label: 'Iteration', color: '#fb923c' },
  STAGE: { label: 'Stage', color: '#8b5cf6' },
  GRAPH: { label: 'Stage', color: '#8b5cf6' },
  INFO: { label: 'Info', color: '#3b82f6' },
  DEBUG: { label: 'Debug', color: '#71717a' },
  STREAM: { label: 'Stream', color: '#94a3b8' },
};

export default function StepDetailPanel({ entry, allEntries, onClose }: StepDetailPanelProps) {
  const levelInfo = LEVEL_LABELS[entry.level] || { label: entry.level, color: '#64748b' };

  return (
    <div className="flex flex-col h-full bg-[var(--bg-primary)]">
      {/* Panel header */}
      <div className="shrink-0 flex items-center justify-between px-4 py-2 bg-[var(--bg-secondary)] border-b border-[var(--border-color)]">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="inline-flex items-center justify-center rounded px-1.5 py-[1px] text-[0.5625rem] font-bold uppercase tracking-wider shrink-0"
            style={{ backgroundColor: `${levelInfo.color}15`, color: levelInfo.color }}
          >
            {levelInfo.label}
          </span>
          <span className="text-[0.75rem] text-[var(--text-secondary)] truncate min-w-0">
            {entry.metadata?.tool_name || entry.metadata?.event_type || formatTime(entry.timestamp)}
          </span>
        </div>
        <button
          onClick={onClose}
          className="w-6 h-6 rounded-md flex items-center justify-center hover:bg-[var(--bg-hover)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-all cursor-pointer border-none bg-transparent shrink-0"
        >
          <X size={14} />
        </button>
      </div>

      {/* Panel body */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {entry.level === 'TOOL' && <ToolUseDetail entry={entry} allEntries={allEntries} />}
        {entry.level === 'ITER' && <IterationDetail entry={entry} />}
        {(entry.level === 'STAGE' || entry.level === 'GRAPH') && <StageEventDetail entry={entry} />}
        {!['TOOL', 'ITER', 'STAGE', 'GRAPH'].includes(entry.level) && <GenericDetail entry={entry} />}
      </div>
    </div>
  );
}
