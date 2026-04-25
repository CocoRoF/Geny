'use client';

/**
 * Mutation audit log viewer (G11.3 + G15).
 *
 * Lists every ``mutation.applied`` event the executor's PipelineMutator
 * emits — strategy swaps, chain reorders, tool bindings, model
 * overrides, etc. Scrollable chronological feed; click a row to open
 * the diff modal (G15).
 *
 * Like the other dashboard components, derives from the session's
 * logEntries array — no extra subscription.
 */

import { useMemo, useState } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { Wrench } from 'lucide-react';
import type { LogEntry, LogEntryMetadata } from '@/types';
import MutationDiffViewer, { type MutationDetail } from './MutationDiffViewer';

function extractMutations(entries: LogEntry[]): MutationDetail[] {
  const out: MutationDetail[] = [];
  for (const entry of entries) {
    const meta = entry.metadata as LogEntryMetadata | undefined;
    if (meta?.event_type !== 'mutation.applied' && meta?.event_type !== 'mutation_applied') continue;
    const data = (meta.data || {}) as Record<string, unknown>;
    const kind = String(data.kind ?? data.mutation_kind ?? 'unknown');
    const before = data.before;
    const after = data.after;
    const stage = data.stage_name ?? data.stage ?? '';
    const slot = data.slot_name ?? data.slot ?? '';
    const desc = stage || slot
      ? `${stage}${slot ? `.${slot}` : ''}: ${JSON.stringify(before) ?? '?'} → ${JSON.stringify(after) ?? '?'}`
      : entry.message;
    out.push({
      ts: entry.timestamp,
      kind,
      description: desc.slice(0, 200),
      actor: typeof data.actor === 'string' ? data.actor : null,
      before,
      after,
    });
  }
  return out.reverse();  // Newest first.
}

interface Props {
  sessionId: string;
}

export default function MutationLog({ sessionId }: Props) {
  const cache = useAppStore((s) => s.sessionDataCache[sessionId]);
  const entries = useMemo(() => (cache?.logEntries || []) as LogEntry[], [cache?.logEntries]);
  const mutations = useMemo(() => extractMutations(entries), [entries]);
  const [opened, setOpened] = useState<MutationDetail | null>(null);

  if (mutations.length === 0) {
    return (
      <div className="px-3 py-3 text-center text-[0.6875rem] text-[var(--text-muted)]">
        No pipeline mutations on this session yet.
      </div>
    );
  }

  return (
    <>
      <ul className="px-3 py-2 flex flex-col gap-1 max-h-[280px] overflow-auto">
        {mutations.map((row, idx) => (
          <li
            key={`${row.ts}-${idx}`}
            className="flex items-start gap-2 px-2 py-1.5 rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer text-[0.6875rem] transition-colors"
            onClick={() => setOpened(row)}
            title="Click for before/after diff"
          >
            <Wrench size={11} className="mt-0.5 shrink-0 text-[var(--primary-color)] opacity-70" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[var(--primary-color)] uppercase tracking-wider text-[0.5625rem]">
                  {row.kind}
                </span>
                <span className="text-[var(--text-muted)] font-mono opacity-60">
                  {row.ts.slice(11, 19)}
                </span>
                {row.actor && (
                  <span className="text-[var(--text-muted)] opacity-70">
                    · {row.actor}
                  </span>
                )}
              </div>
              <div className="text-[var(--text-secondary)] truncate font-mono mt-0.5">
                {row.description}
              </div>
            </div>
          </li>
        ))}
      </ul>

      {opened && (
        <MutationDiffViewer detail={opened} onClose={() => setOpened(null)} />
      )}
    </>
  );
}
