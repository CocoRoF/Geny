'use client';

/**
 * EnvironmentTab — global *Library* (system-wide pipeline definitions
 * + shared components).
 *
 * Scope: NEVER session-bound. Always operates on system files /
 * registries (settings.json, mcp/custom/, env manifest store). The
 * sister surface is SessionEnvironmentRootTab which mounts under the
 * session strip and operates on the env *bound* to the active session.
 *
 * Don't confuse the two:
 *   - "Library" (this tab)             → system catalog & shared rules
 *   - "Environment" (session-scoped)   → that one session's instance view
 *
 * Sub-tabs (all system-wide):
 *   library      → environment manifest CRUD (was: EnvironmentsTab)
 *   toolSets     → custom tool / MCP presets (was: ToolSetsTab)
 *   toolCatalog  → framework BUILT_IN_TOOL_CLASSES (was: ToolCatalogTab)
 *   permissions  → permission matrix (was: PermissionsTab)
 *   hooks        → hook entries + recent fires (was: HooksTab)
 *   skills       → bundled + user skills (was: SkillsTab)
 *   mcpServers   → custom MCP server JSON CRUD (was: McpServersTab)
 */

import dynamic from 'next/dynamic';
import { useAppStore } from '@/store/useAppStore';
import { SubTabNav, type SubTabDef } from '@/components/layout';
import {
  Library,
  FolderTree,
  Wrench,
  Package,
  Shield,
  Plug,
  Sparkles,
  Server,
} from 'lucide-react';

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
  { id: 'library', label: 'Environments', icon: FolderTree },
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
      {/* Strong scope header — distinguishes this from the session-
          scoped Environment tab. Color-coded with primary accent. */}
      <div className="shrink-0 px-4 py-2 border-b border-[var(--border-color)] bg-[rgba(59,130,246,0.04)] flex items-center gap-2">
        <Library size={14} className="text-[var(--primary-color)]" />
        <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">
          Library
        </span>
        <span className="text-[0.6875rem] text-[var(--text-muted)]">
          · System-wide pipeline definitions and shared components (settings.json, mcp/custom/, environments/)
        </span>
      </div>
      <SubTabNav tabs={SUB_TABS} active={subTab} onSelect={setSubTab} />
      <div className="flex-1 min-h-0 overflow-hidden">
        <Active />
      </div>
    </div>
  );
}
