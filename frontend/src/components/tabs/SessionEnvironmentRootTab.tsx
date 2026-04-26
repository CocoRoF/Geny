'use client';

/**
 * SessionEnvironmentRootTab — session-scoped consolidated Environment.
 *
 * Mirrors the global EnvironmentTab but with session-relevant
 * sub-tabs: the manifest of the bound env, the actually-loaded tools,
 * and the WorkspaceStack. Other session-runtime surfaces (Memory /
 * Tasks / Cron) intentionally stay as their own session tabs because
 * they're runtime state, not pipeline definition.
 */

import dynamic from 'next/dynamic';
import { useAppStore } from '@/store/useAppStore';
import { SubTabNav, type SubTabDef } from '@/components/layout';
import { Layers, Wrench, Folder } from 'lucide-react';

const SessionEnvironmentTab = dynamic(
  () => import('@/components/tabs/SessionEnvironmentTab'),
  { ssr: false },
);
const SessionToolsTab = dynamic(() => import('@/components/tabs/SessionToolsTab'));
const WorkspaceTab = dynamic(() => import('@/components/tabs/WorkspaceTab'));

const SUB_TABS: SubTabDef[] = [
  { id: 'manifest', label: 'Manifest', icon: Layers },
  { id: 'tools', label: 'Tools', icon: Wrench },
  { id: 'workspace', label: 'Workspace', icon: Folder },
];

const SUB_TAB_COMPONENT: Record<string, React.ComponentType> = {
  manifest: SessionEnvironmentTab,
  tools: SessionToolsTab,
  workspace: WorkspaceTab,
};

export default function SessionEnvironmentRootTab() {
  const subTab = useAppStore((s) => s.sessionEnvSubTab);
  const setSubTab = useAppStore((s) => s.setSessionEnvSubTab);
  const Active = SUB_TAB_COMPONENT[subTab] ?? SessionEnvironmentTab;

  return (
    <div className="flex flex-col h-full min-h-0">
      <SubTabNav tabs={SUB_TABS} active={subTab} onSelect={setSubTab} />
      <div className="flex-1 min-h-0 overflow-hidden">
        <Active />
      </div>
    </div>
  );
}
