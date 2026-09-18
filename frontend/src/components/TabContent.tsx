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
const CloudTab = dynamic(() => import('@/components/tabs/CloudTab'), { ssr: false });
const InfoTab = dynamic(() => import('@/components/tabs/InfoTab'));
const SettingsTab = dynamic(() => import('@/components/tabs/SettingsTab'));
const SessionToolsTab = dynamic(() => import('@/components/tabs/SessionToolsTab'));
// Cycle 20260503_3 — the in-Geny ``MemoryTab`` was retired in favour
// of opening the canonical Opsidian app (``/opsidian``) in a new
// browser tab. ``TabNavigation`` flags the ``memory`` entry with an
// ``external`` URL resolver so clicking it never triggers an in-app
// view switch. The lazy import + TAB_MAP entry are gone with the
// component file itself.
const VTuberTab = dynamic(() => import('@/components/tabs/VTuberTab'), { ssr: false });
const Playground2DTab = dynamic(() => import('@/components/tabs/Playground2DTab'), { ssr: false });
const TasksTab = dynamic(() => import('@/components/tabs/TasksTab').then(m => m.TasksTab));
const HooksAutomationTab = dynamic(() => import('@/components/tabs/HooksAutomationTab').then(m => m.HooksAutomationTab));
const CanvasTab = dynamic(() => import('@/components/tabs/CanvasTab'));
// Cycle 20260429 Phase 6 — main-app `library` tab and its sub-tabs
// (hooks/skills/permissions/mcpServers/toolSets) are gone. They were
// the prototype that conflated env CRUD with host registries; the
// dedicated /environments route owns both surfaces now. Legacy
// activeTab values for those ids redirect to /environments?tab=...
// in useAppStore.setActiveTab.

const TAB_MAP: Record<string, React.ComponentType> = {
  cloud: CloudTab,
  main: MainTab,
  playground: PlaygroundTab,
  command: CommandTab,
  logs: LogsTab,
  storage: StorageTab,
  info: InfoTab,
  settings: SettingsTab,
  sessionTools: SessionToolsTab,
  vtuber: VTuberTab,
  playground2d: Playground2DTab,
  tasks: TasksTab,
  hooks: HooksAutomationTab,
  canvas: CanvasTab,
};

// Tabs that should stay mounted once activated (KeepAlive)
// canvas keeps its selection/page position + polling across tab
// switches — the chat-edit loop bounces between chat and canvas.
const KEEP_ALIVE_TABS = new Set(['vtuber', 'canvas']);

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
