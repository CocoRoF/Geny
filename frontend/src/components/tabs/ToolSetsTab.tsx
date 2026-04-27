'use client';

/**
 * ToolSetsTab — unified preset manager (Tool Sets + Tool Catalog merged).
 *
 * Single screen, two panes:
 *   left  — preset list (templates + user presets) + "📖 카탈로그" entry
 *   right — selected preset's editor, or read-only catalog browser
 *
 * The framework tool catalog is no longer a separate tab; it's a sidebar
 * entry on the left (read-only browse) AND an info drawer reachable from
 * any tool checkbox in the editor (so creators see exactly what each
 * tool does while choosing).
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { twMerge } from 'tailwind-merge';
import {
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  Info,
  Package,
  Plus,
  RefreshCw,
  Server,
  Trash2,
  Wrench,
  X,
} from 'lucide-react';
import { useToolPresetStore } from '@/store/useToolPresetStore';
import { useI18n } from '@/lib/i18n';
import {
  TabShell,
  TwoPaneBody,
  EditorModal,
  EmptyState,
  ActionButton,
  StatusBadge,
  SearchInput,
  DetailDrawer,
} from '@/components/layout';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { frameworkToolApi, type FrameworkToolDetail } from '@/lib/api';
import type { ToolPresetDefinition, ToolInfo } from '@/types';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

const CATALOG_VIEW_ID = '__catalog__';

const CAPABILITY_BADGES: Array<[keyof FrameworkToolDetail['capabilities'], string, string]> = [
  ['read_only', 'read-only', 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'],
  ['destructive', 'destructive', 'bg-red-500/15 text-red-700 dark:text-red-300'],
  ['concurrency_safe', 'parallel', 'bg-blue-500/15 text-blue-700 dark:text-blue-300'],
  ['idempotent', 'idempotent', 'bg-violet-500/15 text-violet-700 dark:text-violet-300'],
  ['network_egress', 'network', 'bg-amber-500/15 text-amber-700 dark:text-amber-300'],
];

// ──────────────────────────────────────────────────────────────────
// Sidebar
// ──────────────────────────────────────────────────────────────────

interface PresetSidebarProps {
  templates: ToolPresetDefinition[];
  userPresets: ToolPresetDefinition[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  search: string;
  onSearch: (q: string) => void;
}

function PresetSidebar({
  templates,
  userPresets,
  selectedId,
  onSelect,
  search,
  onSearch,
}: PresetSidebarProps) {
  const { t } = useI18n();
  const q = search.trim().toLowerCase();
  const matches = (p: ToolPresetDefinition) =>
    !q || p.name.toLowerCase().includes(q) || p.description.toLowerCase().includes(q);

  const visTemplates = templates.filter(matches);
  const visUser = userPresets.filter(matches);

  return (
    <div className="flex flex-col gap-3 p-1">
      <SearchInput
        value={search}
        onChange={onSearch}
        placeholder={t('toolSetsTab.searchPresets')}
      />

      {/* Read-only catalog entry — sits above the preset groups */}
      <button
        type="button"
        onClick={() => onSelect(CATALOG_VIEW_ID)}
        className={cn(
          'flex items-center gap-2 px-2 py-1.5 rounded-md text-[0.8125rem] text-left transition-colors',
          selectedId === CATALOG_VIEW_ID
            ? 'bg-[hsl(var(--accent))] text-[hsl(var(--foreground))] font-semibold'
            : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]',
        )}
      >
        <BookOpen className="w-3.5 h-3.5 shrink-0" />
        <span className="truncate">{t('toolSetsTab.catalogEntry')}</span>
      </button>

      {visTemplates.length > 0 && (
        <SidebarSection
          title={t('toolSetsTab.officialTemplates')}
          accent="bg-violet-400"
          presets={visTemplates}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      )}

      <SidebarSection
        title={t('toolSetsTab.customPresets')}
        accent="bg-[hsl(var(--primary))]"
        presets={visUser}
        selectedId={selectedId}
        onSelect={onSelect}
        emptyHint={t('toolSetsTab.noCustom')}
      />
    </div>
  );
}

interface SidebarSectionProps {
  title: string;
  accent: string;
  presets: ToolPresetDefinition[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  emptyHint?: string;
}

function SidebarSection({
  title,
  accent,
  presets,
  selectedId,
  onSelect,
  emptyHint,
}: SidebarSectionProps) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1.5 px-1 text-[0.625rem] uppercase tracking-wider text-[hsl(var(--muted-foreground))] font-semibold">
        <span className={cn('w-1.5 h-1.5 rounded-full', accent)} />
        {title}
        <span className="opacity-70">({presets.length})</span>
      </div>
      {presets.map(p => (
        <button
          key={p.id}
          type="button"
          onClick={() => onSelect(p.id)}
          className={cn(
            'flex items-center gap-2 px-2 py-1.5 rounded-md text-[0.8125rem] text-left transition-colors',
            selectedId === p.id
              ? 'bg-[hsl(var(--accent))] text-[hsl(var(--foreground))] font-semibold'
              : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]',
          )}
        >
          <span className="truncate flex-1">{p.name}</span>
          {p.is_template && (
            <span className="text-[0.6rem] uppercase tracking-wider text-violet-500 dark:text-violet-300 shrink-0">
              {/* template marker */}T
            </span>
          )}
        </button>
      ))}
      {presets.length === 0 && emptyHint && (
        <div className="px-2 py-1 text-[0.6875rem] text-[hsl(var(--muted-foreground))] italic">
          {emptyHint}
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────
// Catalog view (read-only browse)
// ──────────────────────────────────────────────────────────────────

function CatalogView({
  tools,
  groups,
  loading,
  onPickTool,
}: {
  tools: FrameworkToolDetail[];
  groups: string[];
  loading: boolean;
  onPickTool: (t: FrameworkToolDetail) => void;
}) {
  const { t } = useI18n();
  const [search, setSearch] = useState('');
  const [activeGroup, setActiveGroup] = useState<string>('__all__');

  const groupCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const tool of tools) counts[tool.feature_group] = (counts[tool.feature_group] || 0) + 1;
    return counts;
  }, [tools]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return tools.filter(tt => {
      if (activeGroup !== '__all__' && tt.feature_group !== activeGroup) return false;
      if (q && !(tt.name.toLowerCase().includes(q) || tt.description.toLowerCase().includes(q))) return false;
      return true;
    });
  }, [tools, search, activeGroup]);

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex items-center gap-3 p-4 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0">
        <BookOpen className="w-4 h-4 text-[hsl(var(--primary))]" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-[hsl(var(--foreground))]">
            {t('toolSetsTab.catalogTitle')}
          </div>
          <div className="text-[0.7rem] text-[hsl(var(--muted-foreground))]">
            {t('toolSetsTab.catalogSubtitle', { n: String(tools.length) })}
          </div>
        </div>
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder={t('toolSetsTab.searchTools')}
          className="max-w-[260px]"
        />
      </div>

      <div className="flex items-center gap-1.5 px-4 py-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0 overflow-x-auto">
        {(['__all__', ...groups] as const).map(g => {
          const isActive = activeGroup === g;
          const label = g === '__all__' ? t('toolSetsTab.allGroups') : g;
          const count = g === '__all__' ? tools.length : (groupCounts[g] ?? 0);
          return (
            <button
              key={g}
              type="button"
              onClick={() => setActiveGroup(g)}
              className={cn(
                'inline-flex items-center gap-1 px-2.5 py-1 rounded-full border text-[0.7rem] font-medium whitespace-nowrap transition-colors',
                isActive
                  ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] border-[hsl(var(--primary))]'
                  : 'border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]',
              )}
            >
              {label}
              <span className="opacity-70 tabular-nums">({count})</span>
            </button>
          );
        })}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        {visible.length === 0 ? (
          <EmptyState
            icon={Wrench}
            title={loading ? t('common.loading') : t('toolSetsTab.noToolsFound')}
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {visible.map(tool => (
              <button
                key={tool.name}
                type="button"
                onClick={() => onPickTool(tool)}
                className="text-left border border-[hsl(var(--border))] rounded-md p-3 hover:border-[hsl(var(--primary))] hover:shadow-sm transition-all bg-[hsl(var(--card))]"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono font-semibold text-[0.875rem] truncate text-[hsl(var(--foreground))]">
                    {tool.name}
                  </span>
                  <span className="text-[0.625rem] uppercase tracking-wider text-[hsl(var(--muted-foreground))] shrink-0">
                    {tool.feature_group}
                  </span>
                </div>
                <div className="text-[0.75rem] text-[hsl(var(--muted-foreground))] mt-1 line-clamp-2">
                  {tool.description || '—'}
                </div>
                <div className="flex flex-wrap gap-1 mt-2">
                  {CAPABILITY_BADGES.map(([key, label, klass]) =>
                    tool.capabilities[key] ? (
                      <span
                        key={String(key)}
                        className={cn('inline-block text-[0.5625rem] px-1.5 py-0.5 rounded', klass)}
                      >
                        {label}
                      </span>
                    ) : null,
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────
// Preset editor
// ──────────────────────────────────────────────────────────────────

function PresetEditor({
  preset,
  frameworkTools,
  readOnly,
  onSaved,
  onClone,
  onDelete,
  onPickTool,
}: {
  preset: ToolPresetDefinition;
  frameworkTools: FrameworkToolDetail[];
  readOnly: boolean;
  onSaved: () => void;
  onClone: () => void;
  onDelete: (() => void) | null;
  onPickTool: (t: FrameworkToolDetail) => void;
}) {
  const { catalog, loadCatalog, updatePreset } = useToolPresetStore();
  const { t } = useI18n();

  const [name, setName] = useState(preset.name);
  const [description, setDescription] = useState(preset.description);
  const [selectedCustomTools, setSelectedCustomTools] = useState<Set<string>>(
    () => new Set(preset.custom_tools.includes('*') ? ['*'] : preset.custom_tools),
  );
  const [selectedMcpServers, setSelectedMcpServers] = useState<Set<string>>(
    () => new Set(preset.mcp_servers.includes('*') ? ['*'] : preset.mcp_servers),
  );
  const [builtInMode, setBuiltInMode] = useState<'inherit' | 'allowlist' | 'blocklist'>(
    (preset.built_in_mode as 'inherit' | 'allowlist' | 'blocklist') ?? 'inherit',
  );
  const [builtInTools, setBuiltInTools] = useState<Set<string>>(
    () => new Set(preset.built_in_tools ?? []),
  );
  const [builtInDeny, setBuiltInDeny] = useState<Set<string>>(
    () => new Set(preset.built_in_deny ?? []),
  );
  const [saving, setSaving] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    framework_builtin: true,
    custom_root: true,
    mcp_root: true,
  });

  // Reset local state when switching presets.
  useEffect(() => {
    setName(preset.name);
    setDescription(preset.description);
    setSelectedCustomTools(new Set(preset.custom_tools.includes('*') ? ['*'] : preset.custom_tools));
    setSelectedMcpServers(new Set(preset.mcp_servers.includes('*') ? ['*'] : preset.mcp_servers));
    setBuiltInMode((preset.built_in_mode as 'inherit' | 'allowlist' | 'blocklist') ?? 'inherit');
    setBuiltInTools(new Set(preset.built_in_tools ?? []));
    setBuiltInDeny(new Set(preset.built_in_deny ?? []));
    setSearchTerm('');
  }, [preset.id, preset.name, preset.description, preset.custom_tools, preset.mcp_servers, preset.built_in_mode, preset.built_in_tools, preset.built_in_deny]);

  useEffect(() => {
    if (!catalog) loadCatalog();
  }, [catalog, loadCatalog]);

  const allCustomToolNames = useMemo(
    () => catalog?.custom.map(tool => tool.name) ?? [],
    [catalog],
  );
  const allMcpServerNames = useMemo(
    () => catalog?.mcp_servers.map(s => s.name) ?? [],
    [catalog],
  );

  const isAllCustom = selectedCustomTools.has('*');
  const isAllMcp = selectedMcpServers.has('*');

  const toggleCustomTool = (toolName: string) => {
    if (readOnly) return;
    setSelectedCustomTools(prev => {
      const next = new Set(prev);
      if (toolName === '*') {
        if (next.has('*')) next.clear();
        else { next.clear(); next.add('*'); }
      } else {
        next.delete('*');
        if (next.has(toolName)) next.delete(toolName);
        else next.add(toolName);
      }
      return next;
    });
  };

  const toggleMcpServer = (serverName: string) => {
    if (readOnly) return;
    setSelectedMcpServers(prev => {
      const next = new Set(prev);
      if (serverName === '*') {
        if (next.has('*')) next.clear();
        else { next.clear(); next.add('*'); }
      } else {
        next.delete('*');
        if (next.has(serverName)) next.delete(serverName);
        else next.add(serverName);
      }
      return next;
    });
  };

  const toggleGroup = (group: string) =>
    setExpandedGroups(prev => ({ ...prev, [group]: !prev[group] }));

  const groupedCustomTools = useMemo<Record<string, ToolInfo[]>>(() => {
    if (!catalog) return {};
    const groups: Record<string, ToolInfo[]> = {};
    for (const tool of catalog.custom) {
      const g = tool.group || 'other';
      (groups[g] ??= []).push(tool);
    }
    return groups;
  }, [catalog]);

  const matches = (s: string) => !searchTerm || s.toLowerCase().includes(searchTerm.toLowerCase());

  const filteredFrameworkTools = useMemo(
    () =>
      frameworkTools.filter(tool =>
        matches(tool.name) || matches(tool.description) || matches(tool.feature_group),
      ),
    [frameworkTools, searchTerm],
  );

  const filteredCustomGroups = useMemo<Record<string, ToolInfo[]>>(() => {
    if (!searchTerm) return groupedCustomTools;
    const result: Record<string, ToolInfo[]> = {};
    for (const [group, tools] of Object.entries(groupedCustomTools)) {
      const hits = tools.filter(t => matches(t.name) || matches(t.description));
      if (hits.length > 0) result[group] = hits;
    }
    return result;
  }, [groupedCustomTools, searchTerm]);

  const filteredMcpServers = useMemo(() => {
    if (!catalog) return [];
    return catalog.mcp_servers.filter(s => matches(s.name));
  }, [catalog, searchTerm]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updatePreset(preset.id, {
        name: name.trim(),
        description: description.trim(),
        custom_tools: Array.from(selectedCustomTools),
        mcp_servers: Array.from(selectedMcpServers),
        built_in_mode: builtInMode,
        built_in_tools: Array.from(builtInTools),
        built_in_deny: Array.from(builtInDeny),
      });
      onSaved();
    } catch {
      // store surfaces error
    } finally {
      setSaving(false);
    }
  };

  const effectiveCustomCount = isAllCustom ? allCustomToolNames.length : selectedCustomTools.size;
  const builtInMcpCount = catalog?.mcp_servers.filter(s => s.is_built_in).length ?? 0;
  const effectiveMcpCount = isAllMcp ? allMcpServerNames.length : selectedMcpServers.size + builtInMcpCount;
  const frameworkPickerActive = builtInMode !== 'inherit';
  const frameworkPickerSet = builtInMode === 'allowlist' ? builtInTools : builtInDeny;
  const frameworkPickerSetter = builtInMode === 'allowlist' ? setBuiltInTools : setBuiltInDeny;
  const dirty =
    name !== preset.name ||
    description !== preset.description ||
    JSON.stringify(Array.from(selectedCustomTools).sort()) !== JSON.stringify([...preset.custom_tools].sort()) ||
    JSON.stringify(Array.from(selectedMcpServers).sort()) !== JSON.stringify([...preset.mcp_servers].sort()) ||
    builtInMode !== ((preset.built_in_mode as string) ?? 'inherit') ||
    JSON.stringify(Array.from(builtInTools).sort()) !== JSON.stringify([...(preset.built_in_tools ?? [])].sort()) ||
    JSON.stringify(Array.from(builtInDeny).sort()) !== JSON.stringify([...(preset.built_in_deny ?? [])].sort());

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Inline header (preset name + save/clone/delete) */}
      <div className="shrink-0 flex items-center gap-2 px-4 py-2 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <Package className="w-4 h-4 text-amber-500 shrink-0" />
        <span className="text-[0.875rem] font-semibold text-[hsl(var(--foreground))] truncate">
          {preset.name}
        </span>
        {preset.is_template && (
          <StatusBadge tone="primary" uppercase>{t('toolSetsTab.template')}</StatusBadge>
        )}
        {readOnly && (
          <StatusBadge tone="neutral" uppercase>{t('toolSetsTab.readOnly')}</StatusBadge>
        )}
        <div className="flex-1" />
        <ActionButton icon={Plus} onClick={onClone}>{t('common.clone')}</ActionButton>
        {onDelete && (
          <ActionButton icon={Trash2} variant="danger" onClick={onDelete}>
            {t('common.delete')}
          </ActionButton>
        )}
        {!readOnly && (
          <ActionButton
            variant="primary"
            icon={Check}
            onClick={handleSave}
            disabled={saving || !name.trim() || !dirty}
          >
            {saving ? t('common.loading') : t('common.save')}
          </ActionButton>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4 md:p-6">
        <div className="max-w-[900px] mx-auto flex flex-col gap-6">
          <section className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-lg p-4 flex flex-col gap-3">
            <h3 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
              {t('toolSetsTab.presetInfo')}
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-x-4 gap-y-2 items-center">
              <Label className="text-[0.75rem]">{t('toolSetsTab.nameLabel')}</Label>
              <Input
                value={name}
                onChange={e => setName(e.target.value)}
                disabled={readOnly}
                placeholder={t('toolSetsTab.namePlaceholder')}
              />
              <Label className="text-[0.75rem]">{t('toolSetsTab.descriptionLabel')}</Label>
              <Input
                value={description}
                onChange={e => setDescription(e.target.value)}
                disabled={readOnly}
                placeholder={t('toolSetsTab.descriptionPlaceholder')}
              />
            </div>
          </section>

          <div className="flex items-center gap-4 px-4 py-2.5 bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-lg text-[0.75rem] flex-wrap">
            <span className="text-[hsl(var(--muted-foreground))]">
              {t('toolSetsTab.builtInAlways', { count: catalog?.built_in.length ?? 0 })}
            </span>
            <span className="w-px h-4 bg-[hsl(var(--border))] hidden sm:block" />
            <span className="text-amber-600 dark:text-amber-400 font-medium">
              {t('toolSetsTab.customSelected', { count: effectiveCustomCount })}
            </span>
            <span className="w-px h-4 bg-[hsl(var(--border))] hidden sm:block" />
            <span className="text-emerald-600 dark:text-emerald-400 font-medium">
              {t('toolSetsTab.mcpSelected', { count: effectiveMcpCount })}
            </span>
          </div>

          <SearchInput
            value={searchTerm}
            onChange={setSearchTerm}
            placeholder={t('toolSetsTab.searchTools')}
          />

          {/* ── Framework built-ins ── */}
          <Section
            title={t('toolSetsTab.frameworkBuiltins')}
            icon={Wrench}
            iconClassName="text-[hsl(var(--primary))]"
            count={`${frameworkPickerActive ? frameworkPickerSet.size : frameworkTools.length} / ${frameworkTools.length}`}
            note={builtInMode}
            expanded={!!expandedGroups.framework_builtin}
            onToggle={() => toggleGroup('framework_builtin')}
          >
            <div className="flex items-center gap-3 text-[0.75rem] mb-2">
              {(['inherit', 'allowlist', 'blocklist'] as const).map(m => (
                <label key={m} className="flex items-center gap-1">
                  <input
                    type="radio"
                    name={`bim-${preset.id}`}
                    checked={builtInMode === m}
                    onChange={() => !readOnly && setBuiltInMode(m)}
                    disabled={readOnly}
                  />
                  {m === 'inherit' ? t('toolSetsTab.builtInInherit') : m}
                </label>
              ))}
            </div>
            {builtInMode === 'inherit' ? (
              <p className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
                {t('toolSetsTab.builtInInheritDesc', { n: String(frameworkTools.length) })}
              </p>
            ) : (
              <ul className="grid grid-cols-1 md:grid-cols-2 gap-1 max-h-72 overflow-y-auto">
                {filteredFrameworkTools.map(tool => {
                  const isOn = frameworkPickerSet.has(tool.name);
                  return (
                    <li key={tool.name} className="text-[0.75rem] flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={isOn}
                        onChange={() => {
                          if (readOnly) return;
                          frameworkPickerSetter(prev => {
                            const next = new Set(prev);
                            if (next.has(tool.name)) next.delete(tool.name);
                            else next.add(tool.name);
                            return next;
                          });
                        }}
                        disabled={readOnly}
                      />
                      <code className="text-[hsl(var(--primary))] text-[0.6875rem] bg-[hsl(var(--accent))] px-1 rounded">
                        {tool.name}
                      </code>
                      <span className="text-[hsl(var(--muted-foreground))] text-[0.6875rem] truncate flex-1">
                        {tool.feature_group}
                      </span>
                      <button
                        type="button"
                        onClick={() => onPickTool(tool)}
                        title={t('toolSetsTab.viewToolInfo')}
                        className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] shrink-0"
                      >
                        <Info className="w-3 h-3" />
                      </button>
                    </li>
                  );
                })}
                {filteredFrameworkTools.length === 0 && (
                  <li className="text-[hsl(var(--muted-foreground))] italic col-span-2 text-[0.75rem]">
                    {t('toolSetsTab.noToolsFound')}
                  </li>
                )}
              </ul>
            )}
          </Section>

          {/* ── Custom tools (always-included viewer + selectable below) ── */}
          <Section
            title={t('toolSetsTab.builtInTools')}
            icon={Wrench}
            iconClassName="text-[hsl(var(--primary))]"
            count={String(catalog?.built_in.length ?? 0)}
            note={t('toolSetsTab.alwaysEnabled')}
            expanded={!!expandedGroups.built_in}
            onToggle={() => toggleGroup('built_in')}
          >
            <div className="flex flex-col gap-0.5">
              {(catalog?.built_in ?? []).filter(tool => matches(tool.name) || matches(tool.description)).map(tool => (
                <div key={tool.name} className="flex items-center gap-2 py-1.5 px-2 rounded-md text-[0.8125rem]">
                  <Check className="w-3 h-3 text-emerald-500 shrink-0" />
                  <code className="text-[hsl(var(--primary))] text-[0.75rem] bg-[hsl(var(--accent))] px-1.5 py-0.5 rounded shrink-0">{tool.name}</code>
                  <span className="text-[hsl(var(--muted-foreground))] text-[0.75rem] truncate">{tool.description}</span>
                </div>
              ))}
            </div>
          </Section>

          <Section
            title={t('toolSetsTab.customTools')}
            icon={Wrench}
            iconClassName="text-amber-500"
            count={String(catalog?.custom.length ?? 0)}
            extra={
              !readOnly && (
                <button
                  type="button"
                  onClick={() => toggleCustomTool('*')}
                  className={cn(
                    'h-6 px-2 text-[0.6875rem] font-medium rounded-md border transition-colors cursor-pointer',
                    isAllCustom
                      ? 'border-amber-500 bg-amber-500/15 text-amber-600 dark:text-amber-400'
                      : 'border-[hsl(var(--border))] bg-transparent text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]',
                  )}
                >
                  {isAllCustom ? t('toolSetsTab.allSelected') : t('toolSetsTab.selectAll')}
                </button>
              )
            }
            expanded={!!expandedGroups.custom_root}
            onToggle={() => toggleGroup('custom_root')}
          >
            <div className="flex flex-col gap-2">
              {Object.entries(filteredCustomGroups).map(([group, tools]) => (
                <div key={group}>
                  <button
                    type="button"
                    className="flex items-center gap-1.5 text-[0.75rem] font-medium text-[hsl(var(--muted-foreground))] bg-transparent border-none cursor-pointer p-0 mb-1"
                    onClick={() => toggleGroup(`custom_${group}`)}
                  >
                    {expandedGroups[`custom_${group}`] ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                    {group.replace(/_/g, ' ')} ({tools.length})
                  </button>
                  {expandedGroups[`custom_${group}`] && (
                    <div className="ml-4 flex flex-col gap-0.5">
                      {tools.map(tool => {
                        const checked = isAllCustom || selectedCustomTools.has(tool.name);
                        return (
                          <label
                            key={tool.name}
                            className={cn(
                              'flex items-center gap-2 py-1.5 px-2 rounded-md text-[0.8125rem] transition-colors',
                              readOnly ? 'cursor-default' : 'cursor-pointer hover:bg-[hsl(var(--accent))]',
                              checked && 'bg-amber-500/5',
                            )}
                          >
                            <input
                              type="checkbox"
                              className="accent-amber-500 w-3.5 h-3.5"
                              checked={checked}
                              onChange={() => toggleCustomTool(tool.name)}
                              disabled={readOnly || isAllCustom}
                            />
                            <code className="text-amber-600 dark:text-amber-400 text-[0.75rem] bg-[hsl(var(--accent))] px-1.5 py-0.5 rounded shrink-0">{tool.name}</code>
                            <span className="text-[hsl(var(--muted-foreground))] text-[0.75rem] truncate">{tool.description}</span>
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
              {Object.keys(filteredCustomGroups).length === 0 && (
                <p className="text-[0.75rem] text-[hsl(var(--muted-foreground))] py-2 px-2">
                  {t('toolSetsTab.noToolsFound')}
                </p>
              )}
            </div>
          </Section>

          {(catalog?.mcp_servers.length ?? 0) > 0 && (
            <Section
              title={t('toolSetsTab.mcpServers')}
              icon={Server}
              iconClassName="text-emerald-500"
              count={String(catalog?.mcp_servers.length ?? 0)}
              extra={
                !readOnly && (
                  <button
                    type="button"
                    onClick={() => toggleMcpServer('*')}
                    className={cn(
                      'h-6 px-2 text-[0.6875rem] font-medium rounded-md border transition-colors cursor-pointer',
                      isAllMcp
                        ? 'border-emerald-500 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                        : 'border-[hsl(var(--border))] bg-transparent text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--foreground))]',
                    )}
                  >
                    {isAllMcp ? t('toolSetsTab.allSelected') : t('toolSetsTab.selectAll')}
                  </button>
                )
              }
              expanded={!!expandedGroups.mcp_root}
              onToggle={() => toggleGroup('mcp_root')}
            >
              <div className="flex flex-col gap-0.5">
                {filteredMcpServers.map(server => {
                  const isBuiltIn = server.is_built_in ?? false;
                  const checked = isBuiltIn || isAllMcp || selectedMcpServers.has(server.name);
                  return (
                    <label
                      key={server.name}
                      className={cn(
                        'flex items-center gap-2 py-1.5 px-2 rounded-md text-[0.8125rem] transition-colors',
                        readOnly || isBuiltIn ? 'cursor-default' : 'cursor-pointer hover:bg-[hsl(var(--accent))]',
                        checked && 'bg-emerald-500/5',
                      )}
                    >
                      <input
                        type="checkbox"
                        className="accent-emerald-500 w-3.5 h-3.5"
                        checked={checked}
                        onChange={() => toggleMcpServer(server.name)}
                        disabled={readOnly || isAllMcp || isBuiltIn}
                      />
                      <code className="text-emerald-600 dark:text-emerald-400 text-[0.75rem] bg-[hsl(var(--accent))] px-1.5 py-0.5 rounded">{server.name}</code>
                      <span className="text-[0.6875rem] px-1.5 py-0.5 rounded-full bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))]">{server.type}</span>
                      {isBuiltIn && (
                        <StatusBadge tone="success" uppercase>{t('toolSetsTab.builtInMcp')}</StatusBadge>
                      )}
                      {server.description && (
                        <span className="text-[hsl(var(--muted-foreground))] text-[0.6875rem] truncate">{server.description}</span>
                      )}
                    </label>
                  );
                })}
                {filteredMcpServers.length === 0 && (
                  <p className="text-[0.75rem] text-[hsl(var(--muted-foreground))] py-2 px-2">
                    {t('toolSetsTab.noToolsFound')}
                  </p>
                )}
              </div>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({
  title,
  icon: Icon,
  iconClassName,
  count,
  note,
  extra,
  expanded,
  onToggle,
  children,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  iconClassName?: string;
  count?: string;
  note?: string;
  extra?: React.ReactNode;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3">
        <button
          type="button"
          onClick={onToggle}
          className="flex items-center gap-2 text-[0.8125rem] font-semibold text-[hsl(var(--foreground))] bg-transparent border-none cursor-pointer text-left"
        >
          {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          <Icon className={cn('w-3.5 h-3.5', iconClassName)} />
          {title}
          {count && (
            <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
              ({count})
            </span>
          )}
          {note && (
            <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
              — {note}
            </span>
          )}
        </button>
        {extra}
      </div>
      {expanded && <div className="px-4 pb-3">{children}</div>}
    </section>
  );
}

// ──────────────────────────────────────────────────────────────────
// Main tab
// ──────────────────────────────────────────────────────────────────

export default function ToolSetsTab() {
  const { presets, isLoading, error, loadPresets, loadCatalog, deletePreset, clonePreset, createPreset } = useToolPresetStore();
  const { t } = useI18n();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [creating, setCreating] = useState(false);
  const [pickedTool, setPickedTool] = useState<FrameworkToolDetail | null>(null);

  // Framework tool catalog (used both by the read-only catalog view and
  // the per-preset "framework built-ins" picker).
  const [frameworkTools, setFrameworkTools] = useState<FrameworkToolDetail[]>([]);
  const [frameworkGroups, setFrameworkGroups] = useState<string[]>([]);
  const [frameworkLoading, setFrameworkLoading] = useState(false);

  const fetchFramework = useCallback(async () => {
    setFrameworkLoading(true);
    try {
      const r = await frameworkToolApi.list();
      setFrameworkTools(r.tools);
      setFrameworkGroups(r.groups);
    } catch {
      // Surface via store error if the user clicks Refresh
    } finally {
      setFrameworkLoading(false);
    }
  }, []);

  const fetchAll = useCallback(async () => {
    await Promise.all([loadPresets(), loadCatalog(), fetchFramework()]);
  }, [loadPresets, loadCatalog, fetchFramework]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const templates = useMemo(
    () => presets.filter(p => p.is_template && p.id === 'template-all-tools'),
    [presets],
  );
  const userPresets = useMemo(() => presets.filter(p => !p.is_template), [presets]);

  // Auto-select first user preset if nothing is selected (so the editor
  // is never blank on a populated install).
  useEffect(() => {
    if (selectedId !== null) return;
    if (userPresets.length > 0) {
      setSelectedId(userPresets[0].id);
    } else if (templates.length > 0) {
      setSelectedId(templates[0].id);
    }
  }, [selectedId, userPresets, templates]);

  const selectedPreset = useMemo(() => {
    if (!selectedId || selectedId === CATALOG_VIEW_ID) return null;
    return presets.find(p => p.id === selectedId) ?? null;
  }, [selectedId, presets]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const created = await createPreset({
        name: newName.trim(),
        description: newDesc.trim(),
        custom_tools: [],
        mcp_servers: [],
      });
      setNewName('');
      setNewDesc('');
      setShowCreateDialog(false);
      setSelectedId(created.id);
    } catch {
      // store handles
    } finally {
      setCreating(false);
    }
  };

  const handleClone = async (preset: ToolPresetDefinition) => {
    try {
      const cloned = await clonePreset(preset.id, `${preset.name} (Copy)`);
      setSelectedId(cloned.id);
    } catch {
      // store handles
    }
  };

  const handleDelete = async (preset: ToolPresetDefinition) => {
    if (!confirm(t('toolSetsTab.deleteConfirm', { name: preset.name }))) return;
    try {
      await deletePreset(preset.id);
      if (selectedId === preset.id) setSelectedId(null);
    } catch {
      // store handles
    }
  };

  const headerActions = (
    <>
      <ActionButton
        icon={RefreshCw}
        spinIcon={isLoading || frameworkLoading}
        disabled={isLoading || frameworkLoading}
        onClick={fetchAll}
      >
        {t('common.refresh')}
      </ActionButton>
      <ActionButton icon={Plus} variant="primary" onClick={() => setShowCreateDialog(true)}>
        {t('toolSetsTab.newPreset')}
      </ActionButton>
    </>
  );

  const showCatalog = selectedId === CATALOG_VIEW_ID;
  const subtitle = showCatalog
    ? t('toolSetsTab.subtitleCatalog')
    : selectedPreset
      ? t('toolSetsTab.subtitleEditing', { name: selectedPreset.name })
      : t('toolSetsTab.subtitleEmpty');

  const main = showCatalog ? (
    <CatalogView
      tools={frameworkTools}
      groups={frameworkGroups}
      loading={frameworkLoading}
      onPickTool={setPickedTool}
    />
  ) : selectedPreset ? (
    <PresetEditor
      key={selectedPreset.id}
      preset={selectedPreset}
      frameworkTools={frameworkTools}
      readOnly={selectedPreset.is_template}
      onSaved={() => loadPresets()}
      onClone={() => handleClone(selectedPreset)}
      onDelete={selectedPreset.is_template ? null : () => handleDelete(selectedPreset)}
      onPickTool={setPickedTool}
    />
  ) : (
    <EmptyState
      icon={Package}
      title={t('toolSetsTab.empty')}
      description={t('toolSetsTab.emptyHint')}
      action={
        <div className="flex items-center gap-2">
          <ActionButton icon={Plus} variant="primary" onClick={() => setShowCreateDialog(true)}>
            {t('toolSetsTab.newPreset')}
          </ActionButton>
          <ActionButton icon={BookOpen} onClick={() => setSelectedId(CATALOG_VIEW_ID)}>
            {t('toolSetsTab.openCatalog')}
          </ActionButton>
        </div>
      }
    />
  );

  return (
    <>
      <TabShell
        title={t('toolSetsTab.title')}
        subtitle={subtitle}
        icon={Package}
        actions={headerActions}
        loading={isLoading || frameworkLoading}
        error={error}
      >
        <TwoPaneBody
          sidebar={
            <PresetSidebar
              templates={templates}
              userPresets={userPresets}
              selectedId={selectedId}
              onSelect={(id) => {
                setSelectedId(id);
                setPickedTool(null);
              }}
              search={search}
              onSearch={setSearch}
            />
          }
          sidebarTitle={t('toolSetsTab.sidebarTitle')}
          sidebarWidth="medium"
          mainPadding="none"
        >
          {main}
        </TwoPaneBody>
      </TabShell>

      <EditorModal
        open={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        title={t('toolSetsTab.newPresetTitle')}
        saving={creating}
        footer={
          <>
            <ActionButton onClick={() => setShowCreateDialog(false)} disabled={creating}>
              {t('common.cancel')}
            </ActionButton>
            <ActionButton
              variant="primary"
              icon={Plus}
              onClick={handleCreate}
              disabled={creating || !newName.trim()}
            >
              {creating ? t('common.loading') : t('common.create')}
            </ActionButton>
          </>
        }
      >
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="preset-name">{t('toolSetsTab.nameLabel')}</Label>
            <Input
              id="preset-name"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder={t('toolSetsTab.namePlaceholder')}
              onKeyDown={e => e.key === 'Enter' && handleCreate()}
              autoFocus
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="preset-desc">{t('toolSetsTab.descriptionLabel')}</Label>
            <Textarea
              id="preset-desc"
              value={newDesc}
              onChange={e => setNewDesc(e.target.value)}
              placeholder={t('toolSetsTab.descriptionPlaceholder')}
              rows={3}
            />
          </div>
        </div>
      </EditorModal>

      <DetailDrawer
        open={!!pickedTool}
        onClose={() => setPickedTool(null)}
        title={<span className="font-mono">{pickedTool?.name}</span>}
      >
        {pickedTool && (
          <div className="flex flex-col gap-3">
            <Field label={t('toolSetsTab.tool.group')} value={pickedTool.feature_group} />
            <Field
              label={t('toolSetsTab.tool.description')}
              value={
                <span className="whitespace-pre-wrap">{pickedTool.description || '—'}</span>
              }
            />
            <div>
              <FieldLabel>{t('toolSetsTab.tool.capabilities')}</FieldLabel>
              <div className="flex flex-wrap gap-1">
                {Object.entries(pickedTool.capabilities).map(([k, v]) => (
                  <span
                    key={k}
                    className="text-[0.6rem] px-1.5 py-0.5 rounded bg-[hsl(var(--accent))] font-mono"
                  >
                    {k}: {String(v)}
                  </span>
                ))}
                {Object.keys(pickedTool.capabilities).length === 0 && (
                  <span className="text-[hsl(var(--muted-foreground))] text-[0.75rem]">—</span>
                )}
              </div>
            </div>
            <div>
              <FieldLabel>{t('toolSetsTab.tool.inputSchema')}</FieldLabel>
              <pre className="text-[0.625rem] font-mono bg-[hsl(var(--accent))] rounded p-2 overflow-x-auto">
                {JSON.stringify(pickedTool.input_schema, null, 2)}
              </pre>
            </div>
            <div className="pt-2 border-t border-[hsl(var(--border))]">
              <ActionButton
                icon={X}
                onClick={() => setPickedTool(null)}
              >
                {t('common.close')}
              </ActionButton>
            </div>
          </div>
        )}
      </DetailDrawer>
    </>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <div className="text-[0.8125rem]">{value}</div>
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] uppercase tracking-wider mb-1">
      {children}
    </div>
  );
}
