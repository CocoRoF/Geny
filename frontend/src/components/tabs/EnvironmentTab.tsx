'use client';

/**
 * EnvironmentTab — global consolidated configuration tab.
 *
 * Hosts the 7 sub-tabs that together describe a geny-executor
 * pipeline definition (philosophy: "환경 = 잘 만들어진 파이프라인;
 * 권한·훅·스킬·도구·MCP는 모두 그 구성요소"):
 *
 *   library      → environment CRUD (was: EnvironmentsTab)
 *   toolSets     → custom tool / MCP presets (was: ToolSetsTab)
 *   toolCatalog  → framework BUILT_IN_TOOL_CLASSES (was: ToolCatalogTab)
 *   permissions  → permission matrix (was: PermissionsTab)
 *   hooks        → hook entries + recent fires (was: HooksTab)
 *   skills       → bundled + user skills (was: SkillsTab)
 *   mcpServers   → custom MCP server JSON CRUD (was: McpServersTab)
 *
 * Each sub-tab keeps its own TabShell internal chrome — the parent
 * tab strip already conveys "Environment" so we don't add a third
 * header level. SubTabNav lives just below the page tab strip.
 */

import dynamic from 'next/dynamic';
import { useAppStore } from '@/store/useAppStore';
import { SubTabNav, type SubTabDef } from '@/components/layout';
import {
  FolderTree,
  Wrench,
  Package,
  Shield,
  Plug,
  Sparkles,
  Server,
} from 'lucide-react';

// Lazy-load each sub-tab so initial Environment mount stays small.
const EnvironmentsTab = dynamic(() => import('@/components/tabs/EnvironmentsTab'));
const ToolSetsTab = dynamic(() => import('@/components/tabs/ToolSetsTab'));
const ToolCatalogTab = dynamic(() =>
  import('@/components/tabs/ToolCatalogTab').then((m) => m.ToolCatalogTab),
);
const PermissionsTab = dynamic(() =>
  import('@/components/tabs/PermissionsTab').then((m) => m.PermissionsTab),
);
const HooksTab = dynamic(() =>
  import('@/components/tabs/HooksTab').then((m) => m.HooksTab),
);
const SkillsTab = dynamic(() =>
  import('@/components/tabs/SkillsTab').then((m) => m.SkillsTab),
);
const McpServersTab = dynamic(() =>
  import('@/components/tabs/McpServersTab').then((m) => m.McpServersTab),
);

const SUB_TABS: SubTabDef[] = [
  { id: 'library', label: 'Library', icon: FolderTree },
  { id: 'toolSets', label: 'Tool Sets', icon: Wrench },
  { id: 'toolCatalog', label: 'Tool Catalog', icon: Package },
  { id: 'permissions', label: 'Permissions', icon: Shield },
  { id: 'hooks', label: 'Hooks', icon: Plug },
  { id: 'skills', label: 'Skills', icon: Sparkles },
  { id: 'mcpServers', label: 'MCP Servers', icon: Server },
];

const SUB_TAB_COMPONENT: Record<string, React.ComponentType> = {
  library: EnvironmentsTab,
  toolSets: ToolSetsTab,
  toolCatalog: ToolCatalogTab,
  permissions: PermissionsTab,
  hooks: HooksTab,
  skills: SkillsTab,
  mcpServers: McpServersTab,
};

export default function EnvironmentTab() {
  const subTab = useAppStore((s) => s.envSubTab);
  const setSubTab = useAppStore((s) => s.setEnvSubTab);
  const Active = SUB_TAB_COMPONENT[subTab] ?? EnvironmentsTab;

  return (
    <div className="flex flex-col h-full min-h-0">
      <SubTabNav tabs={SUB_TABS} active={subTab} onSelect={setSubTab} />
      <div className="flex-1 min-h-0 overflow-hidden">
        <Active />
      </div>
    </div>
  );
}
