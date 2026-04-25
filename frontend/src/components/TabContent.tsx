'use client';

import { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';
import { useAppStore } from '@/store/useAppStore';
import { useI18n } from '@/lib/i18n';

// Lazy load tab components
const MainTab = dynamic(() => import('@/components/tabs/MainTab'));
const PlaygroundTab = dynamic(() => import('@/components/tabs/PlaygroundTab'), { ssr: false });
const CommandTab = dynamic(() => import('@/components/tabs/CommandTab'));
const LogsTab = dynamic(() => import('@/components/tabs/LogsTab'));
const StorageTab = dynamic(() => import('@/components/tabs/StorageTab'));
const SessionEnvironmentTab = dynamic(() => import('@/components/tabs/SessionEnvironmentTab'), { ssr: false });
const InfoTab = dynamic(() => import('@/components/tabs/InfoTab'));
const SettingsTab = dynamic(() => import('@/components/tabs/SettingsTab'));
const SharedFolderTab = dynamic(() => import('@/components/tabs/SharedFolderTab'));
const SessionToolsTab = dynamic(() => import('@/components/tabs/SessionToolsTab'));
const DashboardTab = dynamic(() => import('@/components/tabs/DashboardTab'));
const ToolSetsTab = dynamic(() => import('@/components/tabs/ToolSetsTab'));
const MemoryTab = dynamic(() => import('@/components/tabs/MemoryTab'));
const EnvironmentsTab = dynamic(() => import('@/components/tabs/EnvironmentsTab'));
const VTuberTab = dynamic(() => import('@/components/tabs/VTuberTab'), { ssr: false });
const Playground2DTab = dynamic(() => import('@/components/tabs/Playground2DTab'), { ssr: false });

const TAB_MAP: Record<string, React.ComponentType> = {
  main: MainTab,
  playground: PlaygroundTab,
  command: CommandTab,
  logs: LogsTab,
  storage: StorageTab,
  environment: SessionEnvironmentTab,
  // Legacy 'graph' tab is now the per-session Environment view (manifest-driven).
  graph: SessionEnvironmentTab,
  sharedFolder: SharedFolderTab,
  info: InfoTab,
  settings: SettingsTab,
  sessionTools: SessionToolsTab,
  dashboard: DashboardTab,
  toolSets: ToolSetsTab,
  memory: MemoryTab,
  vtuber: VTuberTab,
  playground2d: Playground2DTab,
  environments: EnvironmentsTab,
  // Legacy 'builder' tab merged into Environments — route any stale
  // activeTab values to the same component, which switches into builder
  // mode when useEnvironmentStore.builderEnvId is set.
  builder: EnvironmentsTab,
};

// Tabs that should stay mounted once activated (KeepAlive)
const KEEP_ALIVE_TABS = new Set(['vtuber']);

export default function TabContent() {
  const activeTab = useAppStore(s => s.activeTab);
  const { t } = useI18n();

  // Track which keep-alive tabs have been mounted at least once
  const [mountedKeepAlive, setMountedKeepAlive] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (KEEP_ALIVE_TABS.has(activeTab) && !mountedKeepAlive.has(activeTab)) {
      setMountedKeepAlive((prev) => new Set(prev).add(activeTab));
    }
  }, [activeTab, mountedKeepAlive]);

  // Non-keep-alive active tab
  const ActiveComponent = !KEEP_ALIVE_TABS.has(activeTab) ? TAB_MAP[activeTab] : null;

  return (
    <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
      {/* Keep-alive tabs: render once mounted, hide when inactive */}
      {Array.from(mountedKeepAlive).map((tabKey) => {
        const Comp = TAB_MAP[tabKey];
        if (!Comp) return null;
        const isActive = activeTab === tabKey;
        return (
          <div
            key={tabKey}
            className={isActive ? 'flex-1 min-h-0 flex flex-col' : 'hidden'}
          >
            <Comp />
          </div>
        );
      })}

      {/* Normal tabs: mount/unmount on switch */}
      {ActiveComponent ? <ActiveComponent /> : (!KEEP_ALIVE_TABS.has(activeTab) && !TAB_MAP[activeTab] && <div className="p-8 text-[var(--text-muted)]">{t('common.unknownTab')}</div>)}
    </div>
  );
}
