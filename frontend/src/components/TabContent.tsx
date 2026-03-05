'use client';

import dynamic from 'next/dynamic';
import { useAppStore } from '@/store/useAppStore';
import { useI18n } from '@/lib/i18n';

// Lazy load tab components
const MainTab = dynamic(() => import('@/components/tabs/MainTab'));
const PlaygroundTab = dynamic(() => import('@/components/tabs/PlaygroundTab'), { ssr: false });
const CommandTab = dynamic(() => import('@/components/tabs/CommandTab'));
const DashboardTab = dynamic(() => import('@/components/tabs/DashboardTab'));
const LogsTab = dynamic(() => import('@/components/tabs/LogsTab'));
const StorageTab = dynamic(() => import('@/components/tabs/StorageTab'));
const GraphTab = dynamic(() => import('@/components/tabs/GraphTab'), { ssr: false });
const GraphWorkflowsTab = dynamic(() => import('@/components/tabs/GraphWorkflowsTab'), { ssr: false });
const InfoTab = dynamic(() => import('@/components/tabs/InfoTab'));
const SettingsTab = dynamic(() => import('@/components/tabs/SettingsTab'));
const ToolPresetsTab = dynamic(() => import('@/components/tabs/ToolPresetsTab'));
const SessionToolsTab = dynamic(() => import('@/components/tabs/SessionToolsTab'));
const SharedFolderTab = dynamic(() => import('@/components/tabs/SharedFolderTab'));
const ChatTab = dynamic(() => import('@/components/tabs/ChatTab'));

const TAB_MAP: Record<string, React.ComponentType> = {
  main: MainTab,
  playground: PlaygroundTab,
  command: CommandTab,
  dashboard: DashboardTab,
  logs: LogsTab,
  storage: StorageTab,
  graph: GraphTab,
  workflows: GraphWorkflowsTab,
  tools: ToolPresetsTab,
  sessionTools: SessionToolsTab,
  sharedFolder: SharedFolderTab,
  chat: ChatTab,
  info: InfoTab,
  settings: SettingsTab,
};

export default function TabContent() {
  const activeTab = useAppStore(s => s.activeTab);
  const { t } = useI18n();
  const Component = TAB_MAP[activeTab];

  return (
    <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
      {Component ? <Component /> : <div className="p-8 text-[var(--text-muted)]">{t('common.unknownTab')}</div>}
    </div>
  );
}
