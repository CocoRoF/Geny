'use client';

/**
 * WorkspaceBadge + StackModal (PR-E.4.5).
 *
 * Sits in the CommandTab header next to the elapsed timer. Shows the
 * current workspace cwd + depth at a glance and opens a modal
 * detailing the full stack with a Cleanup action.
 *
 * Hidden when the agent's workspace endpoint reports available=false
 * (executor < 1.3.0 or pipeline not built yet).
 */

import { useEffect, useState } from 'react';
import { agentWorkspaceApi, AgentWorkspaceResponse } from '@/lib/api';
import { Folder, X, Trash2, RefreshCw, Layers } from 'lucide-react';

interface Props {
  sessionId: string;
}

function basename(path: string | null | undefined): string {
  if (!path) return '—';
  const parts = path.split('/').filter(Boolean);
  return parts[parts.length - 1] || path;
}

export function WorkspaceBadge({ sessionId }: Props) {
  const [snap, setSnap] = useState<AgentWorkspaceResponse | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await agentWorkspaceApi.get(sessionId);
      setSnap(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // Re-poll every 10s — workspace state changes on tool calls only.
    const id = window.setInterval(refresh, 10_000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  if (!snap || !snap.available) return null;

  const onCleanup = async () => {
    if (!window.confirm('Pop every workspace frame above the root?')) return;
    setLoading(true);
    setError(null);
    try {
      await agentWorkspaceApi.cleanup(sessionId);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const cwdLabel = basename(snap.current?.cwd);
  const depthLabel = snap.depth;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[0.6875rem] font-medium hover:border-[var(--primary-color)] transition-colors"
        title={snap.current?.cwd ?? 'workspace'}
      >
        <Folder size={11} className="text-[var(--text-muted)]" />
        <span className="font-mono truncate max-w-[120px]">{cwdLabel}</span>
        {depthLabel > 1 && (
          <>
            <span className="text-[var(--text-muted)]">·</span>
            <span className="inline-flex items-center gap-0.5 text-[var(--text-muted)]">
              <Layers size={9} />
              {depthLabel}
            </span>
          </>
        )}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="bg-[var(--bg-primary)] rounded-lg border border-[var(--border-color)] w-full max-w-lg p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold flex items-center gap-1.5">
                <Folder size={14} className="text-[var(--primary-color)]" />
                Workspace stack
                <span className="text-[var(--text-muted)] font-normal">
                  (depth {snap.depth})
                </span>
              </h3>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={refresh}
                  disabled={loading}
                  className="text-[var(--text-muted)] hover:text-[var(--primary-color)] disabled:opacity-50"
                  title="Refresh"
                >
                  <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
                </button>
                <button
                  type="button"
                  onClick={onCleanup}
                  disabled={loading || snap.depth <= 1}
                  className="text-[var(--text-muted)] hover:text-red-600 disabled:opacity-30"
                  title={snap.depth <= 1 ? 'Already at root' : 'Pop everything above root'}
                >
                  <Trash2 size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                >
                  <X size={14} />
                </button>
              </div>
            </header>

            {error && (
              <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2 mb-2">
                {error}
              </div>
            )}

            {snap.stack.length === 0 ? (
              <div className="text-xs text-[var(--text-muted)] italic">
                Stack is empty.
              </div>
            ) : (
              <ol className="space-y-2">
                {snap.stack.map((frame, idx) => {
                  const isCurrent = idx === snap.stack.length - 1;
                  return (
                    <li
                      key={idx}
                      className={`border rounded p-2 ${
                        isCurrent
                          ? 'border-[var(--primary-color)] bg-[rgba(59,130,246,0.04)]'
                          : 'border-[var(--border-color)]'
                      }`}
                    >
                      <div className="flex items-center justify-between text-[0.6875rem]">
                        <span className="font-mono text-[var(--text-muted)]">
                          #{idx} {idx === 0 ? '(root)' : isCurrent ? '(current)' : ''}
                        </span>
                        {frame.git_branch && (
                          <span className="text-[var(--text-muted)] font-mono">
                            {frame.git_branch}
                          </span>
                        )}
                      </div>
                      <div className="font-mono text-[0.75rem] mt-0.5 truncate" title={frame.cwd ?? ''}>
                        {frame.cwd ?? '—'}
                      </div>
                      {(Object.keys(frame.env_vars).length > 0 || frame.lsp_session_id) && (
                        <div className="text-[0.6875rem] text-[var(--text-muted)] mt-1 space-y-0.5">
                          {frame.lsp_session_id && (
                            <div>lsp: <span className="font-mono">{frame.lsp_session_id}</span></div>
                          )}
                          {Object.keys(frame.env_vars).length > 0 && (
                            <div>
                              env: <span className="font-mono">
                                {Object.keys(frame.env_vars).join(', ')}
                              </span>
                            </div>
                          )}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        </div>
      )}
    </>
  );
}

export default WorkspaceBadge;
