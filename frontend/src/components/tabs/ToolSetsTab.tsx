'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useToolPresetStore } from '@/store/useToolPresetStore';
import { useI18n } from '@/lib/i18n';
import { twMerge } from 'tailwind-merge';
import {
  X, ArrowLeft, Check, Search,
  ChevronDown, ChevronRight, Wrench, Server, Package,
} from 'lucide-react';
import type { ToolPresetDefinition, ToolInfo } from '@/types';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

// ==================== Preset Card ====================

function PresetCard({
  preset,
  isSelected,
  onSelect,
  onView,
  onEdit,
  onClone,
  onDelete,
}: {
  preset: ToolPresetDefinition;
  isSelected: boolean;
  onSelect: () => void;
  onView?: () => void;
  onEdit?: () => void;
  onClone?: () => void;
  onDelete?: () => void;
}) {
  const { t } = useI18n();
  const isTemplate = preset.is_template;

  const customLabel = preset.custom_tools.includes('*')
    ? t('toolSetsTab.allCustomTools')
    : t('toolSetsTab.customToolCount', { count: preset.custom_tools.length });

  const mcpLabel = preset.mcp_servers.includes('*')
    ? t('toolSetsTab.allMcpServers')
    : t('toolSetsTab.mcpServerCount', { count: preset.mcp_servers.length });

  return (
    <div
      className={cn(
        'group relative flex flex-col gap-2 p-4 rounded-lg border cursor-pointer transition-all duration-150',
        isSelected
          ? 'border-[var(--primary-color)] bg-[rgba(59,130,246,0.08)] shadow-[0_0_0_1px_var(--primary-color)]'
          : 'border-[var(--border-color)] bg-[var(--bg-secondary)] hover:border-[var(--text-muted)] hover:bg-[var(--bg-tertiary)]',
      )}
      onClick={onSelect}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-6 h-6 rounded-md bg-gradient-to-br from-[#f59e0b] to-[#f97316] flex items-center justify-center shrink-0">
            <Package size={12} className="text-white" />
          </div>
          <h4 className="text-[0.875rem] font-semibold text-[var(--text-primary)] truncate">{preset.name}</h4>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {isTemplate && (
            <span className="text-[10px] font-semibold py-0.5 px-1.5 rounded-md bg-[rgba(168,85,247,0.12)] text-[#c084fc] border border-[rgba(168,85,247,0.2)] uppercase tracking-wide">
              {t('toolSetsTab.template')}
            </span>
          )}
        </div>
      </div>

      <p className="text-[0.75rem] text-[var(--text-muted)] line-clamp-2 leading-[1.5]">
        {preset.description || t('toolSetsTab.noDescription')}
      </p>

      <div className="flex items-center gap-3 text-[0.6875rem] text-[var(--text-muted)]">
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-color)]" />
          {customLabel}
        </span>
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--success-color)]" />
          {mcpLabel}
        </span>
      </div>

      {/* Action Buttons */}
      <div className="absolute bottom-2 right-2 flex items-center gap-1 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity">
        {onView && (
          <button
            className="h-7 px-2 flex items-center justify-center rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
            title={t('common.view')}
            onClick={e => { e.stopPropagation(); onView(); }}
          >
            {t('common.view')}
          </button>
        )}
        {onEdit && (
          <button
            className="h-7 px-2 flex items-center justify-center rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
            title={t('common.edit')}
            onClick={e => { e.stopPropagation(); onEdit(); }}
          >
            {t('common.edit')}
          </button>
        )}
        {onClone && (
          <button
            className="h-7 px-2 flex items-center justify-center rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
            title={t('common.clone')}
            onClick={e => { e.stopPropagation(); onClone(); }}
          >
            {t('common.clone')}
          </button>
        )}
        {onDelete && !isTemplate && (
          <button
            className="w-7 h-7 flex items-center justify-center rounded-md bg-[var(--bg-primary)] border border-[rgba(239,68,68,0.2)] text-[var(--text-muted)] hover:text-[var(--danger-color)] hover:bg-[rgba(239,68,68,0.08)] text-sm font-medium transition-colors"
            title={t('common.delete')}
            onClick={e => { e.stopPropagation(); onDelete(); }}
          >
            <X size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

// ==================== Tool Set Editor ====================

function ToolSetEditor({
  preset,
  onBack,
  readOnly = false,
}: {
  preset: ToolPresetDefinition;
  onBack: () => void;
  readOnly?: boolean;
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
  const [saving, setSaving] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  useEffect(() => { if (!catalog) loadCatalog(); }, [catalog, loadCatalog]);

  const allCustomToolNames = useMemo(
    () => catalog?.custom.map(t => t.name) ?? [],
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
        if (next.has('*')) { next.clear(); } else { next.clear(); next.add('*'); }
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
        if (next.has('*')) { next.clear(); } else { next.clear(); next.add('*'); }
      } else {
        next.delete('*');
        if (next.has(serverName)) next.delete(serverName);
        else next.add(serverName);
      }
      return next;
    });
  };

  const toggleGroup = (group: string) => {
    setExpandedGroups(prev => ({ ...prev, [group]: !prev[group] }));
  };

  // Group custom tools by source file
  const groupedCustomTools: Record<string, ToolInfo[]> = useMemo(() => {
    if (!catalog) return {};
    const groups: Record<string, ToolInfo[]> = {};
    for (const tool of catalog.custom) {
      const group = tool.group || 'other';
      if (!groups[group]) groups[group] = [];
      groups[group].push(tool);
    }
    return groups;
  }, [catalog]);

  const filteredBuiltIn = useMemo(() => {
    if (!catalog) return [];
    if (!searchTerm) return catalog.built_in;
    const q = searchTerm.toLowerCase();
    return catalog.built_in.filter(t => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q));
  }, [catalog, searchTerm]);

  const filteredCustomGroups = useMemo(() => {
    if (!searchTerm) return groupedCustomTools;
    const q = searchTerm.toLowerCase();
    const result: Record<string, ToolInfo[]> = {};
    for (const [group, tools] of Object.entries(groupedCustomTools)) {
      const filtered = tools.filter(t => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q));
      if (filtered.length > 0) result[group] = filtered;
    }
    return result;
  }, [groupedCustomTools, searchTerm]);

  const filteredMcpServers = useMemo(() => {
    if (!catalog) return [];
    if (!searchTerm) return catalog.mcp_servers;
    const q = searchTerm.toLowerCase();
    return catalog.mcp_servers.filter(s => s.name.toLowerCase().includes(q));
  }, [catalog, searchTerm]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await updatePreset(preset.id, {
        name: name.trim(),
        description: description.trim(),
        custom_tools: Array.from(selectedCustomTools),
        mcp_servers: Array.from(selectedMcpServers),
      });
      onBack();
    } catch {
      // error handled by store
    } finally {
      setSaving(false);
    }
  };

  const effectiveCustomCount = isAllCustom ? allCustomToolNames.length : selectedCustomTools.size;
  const builtInMcpCount = catalog?.mcp_servers.filter(s => s.is_built_in).length ?? 0;
  const effectiveMcpCount = isAllMcp ? allMcpServerNames.length : selectedMcpServers.size + builtInMcpCount;

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 h-10 px-4 bg-[var(--bg-secondary)] border-b border-[var(--border-color)] shrink-0">
        <button
          className="flex items-center gap-1.5 h-7 px-3 text-[11px] font-medium rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-primary)] hover:text-[var(--text-primary)] transition-colors"
          onClick={onBack}
        >
          <ArrowLeft size={12} />
          {t('toolSetsTab.backToList')}
        </button>
        <div className="w-6 h-6 rounded-md bg-gradient-to-br from-[#f59e0b] to-[#f97316] flex items-center justify-center shrink-0">
          <Package size={11} className="text-white" />
        </div>
        <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">
          {preset.name}
        </span>
        {readOnly && (
          <span className="text-[10px] font-semibold py-0.5 px-1.5 rounded-md bg-[rgba(107,114,128,0.12)] text-[var(--text-muted)] border border-[rgba(107,114,128,0.2)] uppercase tracking-wide">
            {t('toolSetsTab.readOnly')}
          </span>
        )}
        <div className="flex-1" />
        {!readOnly && (
          <button
            className="flex items-center gap-1.5 h-7 px-3 text-[11px] font-medium rounded-md border border-[rgba(59,130,246,0.3)] bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)] hover:bg-[rgba(59,130,246,0.18)] transition-colors disabled:opacity-50"
            onClick={handleSave}
            disabled={saving || !name.trim()}
          >
            {saving ? t('common.loading') : t('common.save')}
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6">
        <div className="max-w-[900px] mx-auto flex flex-col gap-6">
          {/* Meta Section */}
          <section className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg p-4 flex flex-col gap-3">
            <h3 className="text-[0.8125rem] font-semibold text-[var(--text-primary)] flex items-center gap-2">
              {t('toolSetsTab.presetInfo')}
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-x-4 gap-y-2 items-center">
              <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">{t('toolSetsTab.nameLabel')}</label>
              <input
                className="w-full py-1.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] disabled:opacity-60"
                value={name}
                onChange={e => setName(e.target.value)}
                disabled={readOnly}
                placeholder={t('toolSetsTab.namePlaceholder')}
              />
              <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">{t('toolSetsTab.descriptionLabel')}</label>
              <input
                className="w-full py-1.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] disabled:opacity-60"
                value={description}
                onChange={e => setDescription(e.target.value)}
                disabled={readOnly}
                placeholder={t('toolSetsTab.descriptionPlaceholder')}
              />
            </div>
          </section>

          {/* Stats Banner */}
          <div className="flex items-center gap-4 px-4 py-2.5 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg text-[0.75rem] flex-wrap">
            <span className="text-[var(--text-muted)]">
              {t('toolSetsTab.builtInAlways', { count: catalog?.built_in.length ?? 0 })}
            </span>
            <span className="w-px h-4 bg-[var(--border-color)] hidden sm:block" />
            <span className="text-[var(--accent-color)] font-medium">
              {t('toolSetsTab.customSelected', { count: effectiveCustomCount })}
            </span>
            <span className="w-px h-4 bg-[var(--border-color)] hidden sm:block" />
            <span className="text-[var(--success-color)] font-medium">
              {t('toolSetsTab.mcpSelected', { count: effectiveMcpCount })}
            </span>
          </div>

          {/* Search */}
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              className="w-full pl-9 pr-3 py-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg text-[0.8125rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] transition-all"
              placeholder={t('toolSetsTab.searchTools')}
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
            />
          </div>

          {/* Built-in Tools (always included, read-only) */}
          <section className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg overflow-hidden">
            <button
              className="w-full flex items-center gap-2 px-4 py-3 text-[0.8125rem] font-semibold text-[var(--text-primary)] bg-transparent border-none cursor-pointer hover:bg-[var(--bg-hover)] transition-colors text-left"
              onClick={() => toggleGroup('built_in')}
            >
              {expandedGroups.built_in ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <Wrench size={14} className="text-[var(--primary-color)]" />
              {t('toolSetsTab.builtInTools')}
              <span className="text-[0.6875rem] font-normal text-[var(--text-muted)]">
                ({filteredBuiltIn.length}) — {t('toolSetsTab.alwaysEnabled')}
              </span>
            </button>
            {expandedGroups.built_in && (
              <div className="px-4 pb-3 flex flex-col gap-0.5">
                {filteredBuiltIn.map(tool => (
                  <div key={tool.name} className="flex items-center gap-2 py-1.5 px-2 rounded-md text-[0.8125rem]">
                    <Check size={12} className="text-[var(--success-color)] shrink-0" />
                    <code className="text-[var(--primary-color)] text-[0.75rem] bg-[var(--bg-hover)] px-1.5 py-0.5 rounded shrink-0">{tool.name}</code>
                    <span className="text-[var(--text-muted)] text-[0.75rem] truncate">{tool.description}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Custom Tools (selectable) */}
          <section className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3">
              <button
                className="flex items-center gap-2 text-[0.8125rem] font-semibold text-[var(--text-primary)] bg-transparent border-none cursor-pointer"
                onClick={() => toggleGroup('custom_root')}
              >
                {expandedGroups.custom_root ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <Wrench size={14} className="text-[var(--accent-color)]" />
                {t('toolSetsTab.customTools')}
                <span className="text-[0.6875rem] font-normal text-[var(--text-muted)]">
                  ({catalog?.custom.length ?? 0})
                </span>
              </button>
              {!readOnly && (
                <button
                  className={cn(
                    'h-6 px-2 text-[0.6875rem] font-medium rounded-md border transition-colors cursor-pointer',
                    isAllCustom
                      ? 'border-[var(--accent-color)] bg-[rgba(245,158,11,0.12)] text-[var(--accent-color)]'
                      : 'border-[var(--border-color)] bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]',
                  )}
                  onClick={() => toggleCustomTool('*')}
                >
                  {isAllCustom ? t('toolSetsTab.allSelected') : t('toolSetsTab.selectAll')}
                </button>
              )}
            </div>
            {expandedGroups.custom_root && (
              <div className="px-4 pb-3 flex flex-col gap-2">
                {Object.entries(filteredCustomGroups).map(([group, tools]) => (
                  <div key={group}>
                    <button
                      className="flex items-center gap-1.5 text-[0.75rem] font-medium text-[var(--text-secondary)] bg-transparent border-none cursor-pointer p-0 mb-1"
                      onClick={() => toggleGroup(`custom_${group}`)}
                    >
                      {expandedGroups[`custom_${group}`] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
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
                                readOnly ? 'cursor-default' : 'cursor-pointer hover:bg-[var(--bg-hover)]',
                                checked && 'bg-[rgba(245,158,11,0.05)]',
                              )}
                            >
                              <input
                                type="checkbox"
                                className="accent-[var(--accent-color)] w-3.5 h-3.5"
                                checked={checked}
                                onChange={() => toggleCustomTool(tool.name)}
                                disabled={readOnly || isAllCustom}
                              />
                              <code className="text-[var(--accent-color)] text-[0.75rem] bg-[var(--bg-hover)] px-1.5 py-0.5 rounded shrink-0">{tool.name}</code>
                              <span className="text-[var(--text-muted)] text-[0.75rem] truncate">{tool.description}</span>
                            </label>
                          );
                        })}
                      </div>
                    )}
                  </div>
                ))}
                {Object.keys(filteredCustomGroups).length === 0 && (
                  <p className="text-[0.75rem] text-[var(--text-muted)] py-2 px-2">{t('toolSetsTab.noToolsFound')}</p>
                )}
              </div>
            )}
          </section>

          {/* MCP Servers (selectable) */}
          {(catalog?.mcp_servers.length ?? 0) > 0 && (
            <section className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg overflow-hidden">
              <div className="flex items-center justify-between px-4 py-3">
                <button
                  className="flex items-center gap-2 text-[0.8125rem] font-semibold text-[var(--text-primary)] bg-transparent border-none cursor-pointer"
                  onClick={() => toggleGroup('mcp_root')}
                >
                  {expandedGroups.mcp_root ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  <Server size={14} className="text-[var(--success-color)]" />
                  {t('toolSetsTab.mcpServers')}
                  <span className="text-[0.6875rem] font-normal text-[var(--text-muted)]">
                    ({catalog?.mcp_servers.length ?? 0})
                  </span>
                </button>
                {!readOnly && (
                  <button
                    className={cn(
                      'h-6 px-2 text-[0.6875rem] font-medium rounded-md border transition-colors cursor-pointer',
                      isAllMcp
                        ? 'border-[var(--success-color)] bg-[rgba(34,197,94,0.12)] text-[var(--success-color)]'
                        : 'border-[var(--border-color)] bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]',
                    )}
                    onClick={() => toggleMcpServer('*')}
                  >
                    {isAllMcp ? t('toolSetsTab.allSelected') : t('toolSetsTab.selectAll')}
                  </button>
                )}
              </div>
              {expandedGroups.mcp_root && (
                <div className="px-4 pb-3 flex flex-col gap-0.5">
                  {filteredMcpServers.map(server => {
                    const isBuiltIn = server.is_built_in ?? false;
                    const checked = isBuiltIn || isAllMcp || selectedMcpServers.has(server.name);
                    return (
                      <label
                        key={server.name}
                        className={cn(
                          'flex items-center gap-2 py-1.5 px-2 rounded-md text-[0.8125rem] transition-colors',
                          readOnly || isBuiltIn ? 'cursor-default' : 'cursor-pointer hover:bg-[var(--bg-hover)]',
                          checked && 'bg-[rgba(34,197,94,0.05)]',
                        )}
                      >
                        <input
                          type="checkbox"
                          className="accent-[var(--success-color)] w-3.5 h-3.5"
                          checked={checked}
                          onChange={() => toggleMcpServer(server.name)}
                          disabled={readOnly || isAllMcp || isBuiltIn}
                        />
                        <code className="text-[var(--success-color)] text-[0.75rem] bg-[var(--bg-hover)] px-1.5 py-0.5 rounded">{server.name}</code>
                        <span className="text-[0.6875rem] px-1.5 py-0.5 rounded-full bg-[var(--bg-hover)] text-[var(--text-muted)]">{server.type}</span>
                        {server.is_built_in && (
                          <span className="text-[10px] font-semibold py-[1px] px-1.5 rounded-md bg-[rgba(34,197,94,0.12)] text-[var(--success-color)] border border-[rgba(34,197,94,0.2)] uppercase tracking-wide shrink-0">
                            {t('toolSetsTab.builtInMcp')}
                          </span>
                        )}
                        {server.description && (
                          <span className="text-[var(--text-muted)] text-[0.6875rem] truncate">{server.description}</span>
                        )}
                      </label>
                    );
                  })}
                  {filteredMcpServers.length === 0 && (
                    <p className="text-[0.75rem] text-[var(--text-muted)] py-2 px-2">{t('toolSetsTab.noToolsFound')}</p>
                  )}
                </div>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

// ==================== Main Component ====================

export default function ToolSetsTab() {
  const { presets, isLoading, error, loadPresets, loadCatalog, deletePreset, clonePreset, createPreset } = useToolPresetStore();
  const { t } = useI18n();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<'list' | 'editor' | 'viewer'>('list');
  const [editingPreset, setEditingPreset] = useState<ToolPresetDefinition | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');

  const fetchAll = useCallback(async () => {
    await Promise.all([loadPresets(), loadCatalog()]);
  }, [loadPresets, loadCatalog]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const templates = presets.filter(p => p.is_template && p.id === 'template-all-tools');
  const userPresets = presets.filter(p => !p.is_template);

  const handleCreate = useCallback(async () => {
    if (!newName.trim()) return;
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
      // Go directly to editor
      setEditingPreset(created);
      setMode('editor');
    } catch {
      // error handled by store
    }
  }, [newName, newDesc, createPreset]);

  const handleClone = useCallback(async (id: string) => {
    const preset = presets.find(p => p.id === id);
    const name = `${preset?.name || 'Preset'} (Copy)`;
    try {
      await clonePreset(id, name);
    } catch {
      // error handled by store
    }
  }, [presets, clonePreset]);

  const handleDelete = useCallback(async (id: string, name: string) => {
    if (!confirm(t('toolSetsTab.deleteConfirm', { name }))) return;
    try {
      await deletePreset(id);
      if (selectedId === id) setSelectedId(null);
    } catch {
      // error handled by store
    }
  }, [deletePreset, selectedId, t]);

  const handleEdit = useCallback(async (preset: ToolPresetDefinition) => {
    setEditingPreset(preset);
    setMode('editor');
  }, []);

  const handleView = useCallback(async (preset: ToolPresetDefinition) => {
    setEditingPreset(preset);
    setMode('viewer');
  }, []);

  const handleBackToList = useCallback(() => {
    setMode('list');
    setEditingPreset(null);
    fetchAll();
  }, [fetchAll]);

  // Editor/Viewer mode
  if ((mode === 'editor' || mode === 'viewer') && editingPreset) {
    return (
      <ToolSetEditor
        preset={editingPreset}
        onBack={handleBackToList}
        readOnly={mode === 'viewer'}
      />
    );
  }

  // List mode
  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden bg-[var(--bg-primary)]">
      {/* Header */}
      <div className="shrink-0 flex items-center justify-between px-4 py-2 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[#f59e0b] to-[#f97316] flex items-center justify-center shadow-sm shrink-0">
            <Package size={13} className="text-white" />
          </div>
          <h3 className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">{t('toolSetsTab.title')}</h3>
        </div>
        <button
          className="h-7 px-2.5 text-[0.6875rem] font-medium rounded-md border border-[rgba(59,130,246,0.3)] bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)] hover:bg-[rgba(59,130,246,0.18)] transition-colors"
          onClick={() => setShowCreateDialog(true)}
        >
          {t('toolSetsTab.newPreset')}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="mx-6 mt-3 p-2.5 rounded-md bg-[rgba(239,68,68,0.1)] text-[0.8125rem] text-[var(--danger-color)]">
          {error}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-5">
        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-[var(--text-muted)] text-[0.875rem]">{t('toolSetsTab.loading')}</div>
        ) : (
          <div className="space-y-6">
            {/* Official Templates */}
            {templates.length > 0 && (
              <section>
                <h3 className="text-[0.8125rem] font-semibold text-[var(--text-secondary)] mb-3 flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#c084fc]" />
                  {t('toolSetsTab.officialTemplates')}
                  <span className="text-[0.6875rem] text-[var(--text-muted)] font-normal">({templates.length})</span>
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {templates.map(preset => (
                    <PresetCard
                      key={preset.id}
                      preset={preset}
                      isSelected={selectedId === preset.id}
                      onSelect={() => setSelectedId(preset.id)}
                      onView={() => handleView(preset)}
                      onClone={() => handleClone(preset.id)}
                    />
                  ))}
                </div>
              </section>
            )}

            {/* User Presets */}
            <section>
              <h3 className="text-[0.8125rem] font-semibold text-[var(--text-secondary)] mb-3 flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary-color)]" />
                {t('toolSetsTab.customPresets')}
                <span className="text-[0.6875rem] text-[var(--text-muted)] font-normal">({userPresets.length})</span>
              </h3>
              {userPresets.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 px-4 rounded-lg border border-dashed border-[var(--border-color)] bg-[var(--bg-primary)]">
                  <p className="text-[0.8125rem] text-[var(--text-muted)] mb-3">{t('toolSetsTab.noCustom')}</p>
                  <button
                    className="h-8 px-3 text-[0.75rem] font-medium rounded-md border border-[rgba(59,130,246,0.3)] bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)] hover:bg-[rgba(59,130,246,0.18)] transition-colors"
                    onClick={() => setShowCreateDialog(true)}
                  >
                    {t('toolSetsTab.createFirst')}
                  </button>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {userPresets.map(preset => (
                    <PresetCard
                      key={preset.id}
                      preset={preset}
                      isSelected={selectedId === preset.id}
                      onSelect={() => setSelectedId(preset.id)}
                      onEdit={() => handleEdit(preset)}
                      onClone={() => handleClone(preset.id)}
                      onDelete={() => handleDelete(preset.id, preset.name)}
                    />
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </div>

      {/* Create Dialog */}
      {showCreateDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setShowCreateDialog(false)}>
          <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[400px] shadow-[var(--shadow-lg)]" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center py-3 px-5 border-b border-[var(--border-color)]">
              <h3 className="text-[0.9375rem] font-semibold text-[var(--text-primary)]">{t('toolSetsTab.newPresetTitle')}</h3>
              <button className="flex items-center justify-center w-7 h-7 rounded bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer" onClick={() => setShowCreateDialog(false)}><X size={14} /></button>
            </div>
            <div className="p-5 flex flex-col gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">{t('toolSetsTab.nameLabel')}</label>
                <input
                  className="w-full py-2 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)]"
                  placeholder={t('toolSetsTab.namePlaceholder')}
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleCreate()}
                  autoFocus
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">{t('toolSetsTab.descriptionLabel')}</label>
                <textarea
                  className="w-full py-2 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] resize-none"
                  rows={3}
                  placeholder={t('toolSetsTab.descriptionPlaceholder')}
                  value={newDesc}
                  onChange={e => setNewDesc(e.target.value)}
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 py-3 px-5 border-t border-[var(--border-color)]">
              <button
                className="h-8 px-3 text-[0.75rem] font-medium rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-primary)] hover:text-[var(--text-primary)] transition-colors"
                onClick={() => setShowCreateDialog(false)}
              >
                {t('common.cancel')}
              </button>
              <button
                className="h-8 px-4 text-[0.75rem] font-medium rounded-md border-none bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white transition-colors disabled:opacity-50"
                disabled={!newName.trim()}
                onClick={handleCreate}
              >
                {t('common.create')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
