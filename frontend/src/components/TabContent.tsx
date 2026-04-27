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
const AdminPanel = dynamic(() => import('@/components/admin/AdminPanel'));
const ToolSetsTab = dynamic(() => import('@/components/tabs/ToolSetsTab'));
const MemoryTab = dynamic(() => import('@/components/tabs/MemoryTab'));
const EnvironmentsTab = dynamic(() => import('@/components/tabs/EnvironmentsTab'));
const VTuberTab = dynamic(() => import('@/components/tabs/VTuberTab'), { ssr: false });
const Playground2DTab = dynamic(() => import('@/components/tabs/Playground2DTab'), { ssr: false });
const TasksTab = dynamic(() => import('@/components/tabs/TasksTab').then(m => m.TasksTab));
const CronTab = dynamic(() => import('@/components/tabs/CronTab').then(m => m.CronTab));
const PermissionsTab = dynamic(() => import('@/components/tabs/PermissionsTab').then(m => m.PermissionsTab));
const HooksTab = dynamic(() => import('@/components/tabs/HooksTab').then(m => m.HooksTab));
const SkillsTab = dynamic(() => import('@/components/tabs/SkillsTab').then(m => m.SkillsTab));
const McpServersTab = dynamic(() => import('@/components/tabs/McpServersTab').then(m => m.McpServersTab));
// Consolidated Environment tabs (philosophy: env = pipeline; tools /
// permissions / hooks / skills / mcp are all components of it).
const EnvironmentTab = dynamic(() => import('@/components/tabs/EnvironmentTab'));
const SessionEnvironmentRootTab = dynamic(() => import('@/components/tabs/SessionEnvironmentRootTab'));
// Cycle 20260427_1 — Library (NEW) visual 21-stage builder.
const LibraryNewTab = dynamic(() => import('@/components/library_new/LibraryNewTab'));

const TAB_MAP: Record<string, React.ComponentType> = {
  main: MainTab,
  playground: PlaygroundTab,
  command: CommandTab,
  logs: LogsTab,
  storage: StorageTab,
  // Consolidated Environment surfaces:
  //  - `library` = global pipeline DESIGN (system-wide files).
  //  - `sessionEnvironment` = per-session bound-env view.
  // Old activeTab values for the now-sub-tabs are handled by
  // useAppStore.setActiveTab redirects.
  library: EnvironmentTab,
  // Cycle 20260427_1 — visual 21-stage env builder (parallel to library).
  library_new: LibraryNewTab,
  sessionEnvironment: SessionEnvironmentRootTab,
  // Legacy aliases — kept so direct mounts still work even if a code
  // path bypasses setActiveTab. They render the same components the
  // sub-tabs do.
  graph: SessionEnvironmentTab,
  sharedFolder: SharedFolderTab,
  info: InfoTab,
  settings: SettingsTab,
  sessionTools: SessionToolsTab,
  dashboard: DashboardTab,
  admin: AdminPanel,
  toolSets: ToolSetsTab,
  memory: MemoryTab,
  vtuber: VTuberTab,
  playground2d: Playground2DTab,
  environments: EnvironmentsTab,
  builder: EnvironmentsTab,
  tasks: TasksTab,
  cron: CronTab,
  // PR-Merge — toolCatalog removed; the catalog browser is now a
  // sidebar entry inside the unified Tool Sets tab. Direct mounts via
  // legacy activeTab='toolCatalog' get redirected by setActiveTab.
  toolCatalog: ToolSetsTab,
  permissions: PermissionsTab,
  hooks: HooksTab,
  skills: SkillsTab,
  mcpServers: McpServersTab,
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
