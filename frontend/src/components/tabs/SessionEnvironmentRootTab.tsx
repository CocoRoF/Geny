'use client';

/**
 * SessionEnvironmentRootTab — *session-bound* Environment view.
 *
 * Scope: requires a selected session. Operates strictly on what's
 * loaded into THAT session (manifest of bound env, currently-loaded
 * tools, workspace stack). System-wide editing happens in the global
 * EnvironmentTab ("Library") — sister surface.
 *
 * Sub-tabs (all session-scoped):
 *   manifest   → SessionEnvironmentTab — stage tree of bound env
 *   tools      → SessionToolsTab — tools actually loaded
 *   workspace  → WorkspaceTab — WorkspaceStack snapshot + cleanup
 *
 * Hard guard: renders an explicit empty state when no session is
 * selected. Direct deeplinks to this tab without a session won't
 * silently render half-broken sub-tabs.
 */

import dynamic from 'next/dynamic';
import { useAppStore } from '@/store/useAppStore';
import { SubTabNav, type SubTabDef, EmptyState } from '@/components/layout';
import { Folder, Layers, Wrench, FolderOpen } from 'lucide-react';

const SessionEnvironmentTab = dynamic(
  () => import('@/components/tabs/SessionEnvironmentTab'),
  { ssr: false },
);
const SessionToolsTab = dynamic(() => import('@/components/tabs/SessionToolsTab'));
const WorkspaceTab = dynamic(() => import('@/components/tabs/WorkspaceTab'));

const SUB_TABS: SubTabDef[] = [
  { id: 'manifest', label: 'Manifest', icon: Layers },
  { id: 'tools', label: 'Tools', icon: Wrench },
  { id: 'workspace', label: 'Workspace', icon: FolderOpen },
];

const SUB_TAB_COMPONENT: Record<string, React.ComponentType> = {
  manifest: SessionEnvironmentTab,
  tools: SessionToolsTab,
  workspace: WorkspaceTab,
};

export default function SessionEnvironmentRootTab() {
  const sessionId = useAppStore((s) => s.selectedSessionId);
  const sessions = useAppStore((s) => s.sessions);
  const subTab = useAppStore((s) => s.sessionEnvSubTab);
  const setSubTab = useAppStore((s) => s.setSessionEnvSubTab);

  const session = sessions.find((s) => s.session_id === sessionId);
  const sessionLabel = session?.session_name || sessionId?.slice(0, 12) || '';
  const envId = session?.env_id ?? null;

  // Hard guard: never render session-scoped sub-tabs without a session.
  if (!sessionId || !session) {
    return (
      <div className="flex flex-col h-full min-h-0">
        <div className="shrink-0 px-4 py-2 border-b border-[var(--border-color)] bg-[rgba(245,158,11,0.06)] flex items-center gap-2">
          <Folder size={14} className="text-[var(--warning-color)]" />
          <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">
            Environment
          </span>
          <span className="text-[0.6875rem] text-[var(--text-muted)]">
            · session-scoped
          </span>
        </div>
        <EmptyState
          icon={Folder}
          title="No session selected"
          description="The session-scoped Environment view shows the manifest, loaded tools, and workspace stack of a single session. Pick one from the sidebar."
        />
      </div>
    );
  }

  const Active = SUB_TAB_COMPONENT[subTab] ?? SessionEnvironmentTab;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Strong scope header — distinguishes this from global Library. */}
      <div className="shrink-0 px-4 py-2 border-b border-[var(--border-color)] bg-[rgba(16,185,129,0.05)] flex items-center gap-2 flex-wrap">
        <Folder size={14} className="text-[var(--success-color)]" />
        <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">
          Environment
        </span>
        <span className="text-[0.6875rem] text-[var(--text-muted)]">
          · session{' '}
        </span>
        <code className="text-[0.6875rem] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-tertiary)]">
          {sessionLabel}
        </code>
        {envId ? (
          <>
            <span className="text-[0.6875rem] text-[var(--text-muted)]">
              · bound env{' '}
            </span>
            <code className="text-[0.6875rem] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-tertiary)]">
              {envId}
            </code>
          </>
        ) : (
          <span className="text-[0.6875rem] text-[var(--warning-color)]">
            · no env bound (using default manifest)
          </span>
        )}
      </div>
      <SubTabNav tabs={SUB_TABS} active={subTab} onSelect={setSubTab} />
      <div className="flex-1 min-h-0 overflow-hidden">
        <Active />
      </div>
    </div>
  );
}
