'use client';

/**
 * WorkspaceTab — sub-tab inside the session-level Environment.
 *
 * Promotes the WorkspaceBadge modal content into a first-class tab.
 * Shows the executor 1.3.0 WorkspaceStack (PR-D.5.1) for the active
 * session: the current frame, the full stack, and a Cleanup action
 * that pops everything above the root for stuck-worktree recovery.
 */

import { useEffect, useState } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentWorkspaceApi, AgentWorkspaceResponse } from '@/lib/api';
import { Folder, Trash2, RefreshCw, Layers } from 'lucide-react';
import { TabShell, EmptyState, ActionButton } from '@/components/layout';

export default function WorkspaceTab() {
  const sessionId = useAppStore((s) => s.selectedSessionId);
  const [snap, setSnap] = useState<AgentWorkspaceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    if (!sessionId) return;
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
    const id = window.setInterval(refresh, 10_000);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const onCleanup = async () => {
    if (!sessionId) return;
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

  if (!sessionId) {
    return (
      <TabShell title="Workspace" icon={Folder}>
        <EmptyState title="No session selected" />
      </TabShell>
    );
  }
  if (!snap) {
    return (
      <TabShell title="Workspace" icon={Folder}>
        <EmptyState title={loading ? 'Loading…' : 'Workspace info unavailable'} />
      </TabShell>
    );
  }
  if (!snap.available) {
    return (
      <TabShell title="Workspace" icon={Folder}>
        <EmptyState
          icon={Folder}
          title="Workspace stack not available"
          description="Requires executor ≥ 1.3.0 with the pipeline built; the legacy working_dir is still respected by tools."
        />
      </TabShell>
    );
  }

  return (
    <TabShell
      title="Workspace"
      icon={Folder}
      subtitle={
        <>
          depth <Layers size={10} className="inline" /> {snap.depth} ·{' '}
          <span className="font-mono">{snap.current?.cwd ?? '—'}</span>
        </>
      }
      actions={
        <>
          <ActionButton icon={RefreshCw} spinIcon={loading} onClick={refresh} disabled={loading}>
            Refresh
          </ActionButton>
          <ActionButton
            variant="danger"
            icon={Trash2}
            onClick={onCleanup}
            disabled={loading || snap.depth <= 1}
          >
            Cleanup
          </ActionButton>
        </>
      }
      error={error}
      onDismissError={() => setError(null)}
    >
      <div className="h-full overflow-y-auto p-4">
        {snap.stack.length === 0 ? (
          <EmptyState title="Stack is empty" />
        ) : (
          <ol className="space-y-2">
            {snap.stack.map((frame, idx) => {
              const isCurrent = idx === snap.stack.length - 1;
              return (
                <li
                  key={idx}
                  className={`border rounded p-3 ${
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
                      <span className="text-[var(--text-muted)] font-mono">{frame.git_branch}</span>
                    )}
                  </div>
                  <div className="font-mono text-[0.8125rem] mt-1 truncate" title={frame.cwd ?? ''}>
                    {frame.cwd ?? '—'}
                  </div>
                  {(Object.keys(frame.env_vars).length > 0 || frame.lsp_session_id) && (
                    <div className="text-[0.6875rem] text-[var(--text-muted)] mt-1 space-y-0.5">
                      {frame.lsp_session_id && (
                        <div>
                          lsp: <span className="font-mono">{frame.lsp_session_id}</span>
                        </div>
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
    </TabShell>
  );
}
