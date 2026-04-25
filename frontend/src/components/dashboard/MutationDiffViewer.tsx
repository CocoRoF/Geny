'use client';

/**
 * Mutation diff viewer modal (G15).
 *
 * Renders before/after JSON for a single PipelineMutator mutation
 * row side-by-side. No diff highlighting library — just two
 * formatted blocks. Operators can spot changes by line. The point
 * is to surface the actual values; visual diff polish is a follow-up.
 */

import { useEffect } from 'react';
import { X, Wrench } from 'lucide-react';

interface MutationDetail {
  ts: string;
  kind: string;
  description: string;
  actor: string | null;
  before: unknown;
  after: unknown;
}

interface Props {
  detail: MutationDetail;
  onClose: () => void;
}

function pretty(value: unknown): string {
  if (value === undefined) return '(none)';
  // Bug 1.6 (audit 20260425_3): JSON.stringify throws on circular
  // references. Detect cycles via a WeakSet and substitute "[Circular]"
  // so the operator sees structure instead of "[object Object]".
  const seen = new WeakSet<object>();
  try {
    return JSON.stringify(
      value,
      (_, v) => {
        if (typeof v === 'object' && v !== null) {
          if (seen.has(v as object)) return '[Circular]';
          seen.add(v as object);
        }
        return v;
      },
      2,
    );
  } catch {
    return String(value);
  }
}

export default function MutationDiffViewer({ detail, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[720px] max-h-[85vh] flex flex-col shadow-[var(--shadow-lg)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2 px-5 py-3 border-b border-[var(--border-color)]">
          <div className="flex items-center gap-2 min-w-0">
            <Wrench size={14} className="text-[var(--primary-color)]" />
            <h3 className="text-[0.875rem] font-semibold text-[var(--text-primary)] truncate">
              Mutation diff
            </h3>
            <span className="font-mono text-[0.625rem] uppercase tracking-wider text-[var(--primary-color)]">
              {detail.kind}
            </span>
          </div>
          <button
            className="h-7 w-7 rounded text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] flex items-center justify-center"
            onClick={onClose}
          >
            <X size={14} />
          </button>
        </div>

        <div className="flex-1 overflow-auto px-5 py-4 flex flex-col gap-3">
          <div className="text-[0.6875rem] text-[var(--text-muted)] flex items-center gap-2 flex-wrap">
            <span className="font-mono">{detail.ts}</span>
            {detail.actor && <><span>·</span><span>{detail.actor}</span></>}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <section>
              <h4 className="text-[0.625rem] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-1">
                Before
              </h4>
              <pre className="text-[0.6875rem] font-mono leading-relaxed bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-md px-3 py-2 max-h-[420px] overflow-auto whitespace-pre-wrap break-words m-0 text-[var(--text-secondary)]">
                {pretty(detail.before)}
              </pre>
            </section>
            <section>
              <h4 className="text-[0.625rem] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-1">
                After
              </h4>
              <pre className="text-[0.6875rem] font-mono leading-relaxed bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-md px-3 py-2 max-h-[420px] overflow-auto whitespace-pre-wrap break-words m-0 text-[var(--text-secondary)]">
                {pretty(detail.after)}
              </pre>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}

export type { MutationDetail };
