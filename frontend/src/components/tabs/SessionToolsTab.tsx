'use client';

import { useState, useEffect } from 'react';
import { useToolPresetStore } from '@/store/useToolPresetStore';
import { Copy, Trash2, ChevronDown, ChevronRight } from 'lucide-react';
import type { ToolPresetDefinition, ToolInfo } from '@/types';

export default function SessionToolsTab() {
  const { presets, catalog, isLoading, error, loadPresets, loadCatalog, deletePreset, clonePreset } = useToolPresetStore();

  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({ presets: true, catalog: true });
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  useEffect(() => { loadPresets(); loadCatalog(); }, [loadPresets, loadCatalog]);

  const toggleSection = (section: string) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };
  const toggleGroup = (group: string) => {
    setExpandedGroups(prev => ({ ...prev, [group]: !prev[group] }));
  };

  const handleClone = async (preset: ToolPresetDefinition) => {
    const name = `${preset.name} (Copy)`;
    try { await clonePreset(preset.id, name); } catch { /* ignore */ }
  };

  const handleDelete = async (preset: ToolPresetDefinition) => {
    if (preset.is_template) return;
    try { await deletePreset(preset.id); } catch { /* ignore */ }
  };

  // Group custom tools by source file
  const groupedCustomTools: Record<string, ToolInfo[]> = {};
  if (catalog) {
    for (const tool of catalog.custom) {
      const group = tool.group || 'other';
      if (!groupedCustomTools[group]) groupedCustomTools[group] = [];
      groupedCustomTools[group].push(tool);
    }
  }

  return (
    <div className="h-full overflow-y-auto p-4 md:p-6 flex flex-col gap-6">
      {error && <div className="text-[0.8125rem] text-[var(--danger-color)] bg-[rgba(239,68,68,0.1)] p-2.5 rounded-[6px]">{error}</div>}

      {/* ── Tool Presets Section ── */}
      <section>
        <button
          className="flex items-center gap-2 text-[0.9375rem] font-semibold text-[var(--text-primary)] bg-transparent border-none cursor-pointer p-0 mb-3"
          onClick={() => toggleSection('presets')}
        >
          {expandedSections.presets ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          Tool Presets
          <span className="text-[0.75rem] font-normal text-[var(--text-muted)]">({presets.length})</span>
        </button>

        {expandedSections.presets && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {presets.map(preset => (
              <div key={preset.id} className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg p-3 flex flex-col gap-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-[1rem]">{preset.icon || '🔧'}</span>
                    <span className="text-[0.875rem] font-medium text-[var(--text-primary)]">{preset.name}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button className="p-1 rounded bg-transparent border-none text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer" title="Clone" onClick={() => handleClone(preset)}>
                      <Copy size={14} />
                    </button>
                    {!preset.is_template && (
                      <button className="p-1 rounded bg-transparent border-none text-[var(--text-muted)] hover:text-[var(--danger-color)] hover:bg-[var(--bg-hover)] cursor-pointer" title="Delete" onClick={() => handleDelete(preset)}>
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </div>
                {preset.description && (
                  <p className="text-[0.75rem] text-[var(--text-muted)] line-clamp-2">{preset.description}</p>
                )}
                <div className="flex flex-wrap gap-1 mt-1">
                  {preset.is_template && <span className="text-[0.6875rem] px-1.5 py-0.5 rounded-full bg-[rgba(59,130,246,0.15)] text-[var(--primary-color)]">template</span>}
                  <span className="text-[0.6875rem] px-1.5 py-0.5 rounded-full bg-[var(--bg-hover)] text-[var(--text-muted)]">
                    {preset.custom_tools.includes('*') ? 'all custom tools' : `${preset.custom_tools.length} custom tools`}
                  </span>
                  <span className="text-[0.6875rem] px-1.5 py-0.5 rounded-full bg-[var(--bg-hover)] text-[var(--text-muted)]">
                    {preset.mcp_servers.includes('*') ? 'all MCP servers' : `${preset.mcp_servers.length} MCP servers`}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Tool Catalog Section ── */}
      <section>
        <button
          className="flex items-center gap-2 text-[0.9375rem] font-semibold text-[var(--text-primary)] bg-transparent border-none cursor-pointer p-0 mb-3"
          onClick={() => toggleSection('catalog')}
        >
          {expandedSections.catalog ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          Tool Catalog
          {catalog && <span className="text-[0.75rem] font-normal text-[var(--text-muted)]">({catalog.total_python_tools} tools, {catalog.total_mcp_servers} MCP servers)</span>}
        </button>

        {expandedSections.catalog && catalog && (
          <div className="flex flex-col gap-4">
            {/* Built-in Tools */}
            <div>
              <button
                className="flex items-center gap-1.5 text-[0.8125rem] font-medium text-[var(--text-secondary)] bg-transparent border-none cursor-pointer p-0 mb-2"
                onClick={() => toggleGroup('built_in')}
              >
                {expandedGroups.built_in ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                Built-in Tools ({catalog.built_in.length})
              </button>
              {expandedGroups.built_in && (
                <div className="ml-4 flex flex-col gap-1">
                  {catalog.built_in.map(t => (
                    <div key={t.name} className="flex items-baseline gap-2 py-1 text-[0.8125rem]">
                      <code className="text-[var(--primary-color)] text-[0.75rem] bg-[var(--bg-hover)] px-1.5 py-0.5 rounded">{t.name}</code>
                      <span className="text-[var(--text-muted)] text-[0.75rem] truncate">{t.description}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Custom Tools grouped by source */}
            {Object.entries(groupedCustomTools).map(([group, tools]) => (
              <div key={group}>
                <button
                  className="flex items-center gap-1.5 text-[0.8125rem] font-medium text-[var(--text-secondary)] bg-transparent border-none cursor-pointer p-0 mb-2"
                  onClick={() => toggleGroup(group)}
                >
                  {expandedGroups[group] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  {group.replace(/_/g, ' ')} ({tools.length})
                </button>
                {expandedGroups[group] && (
                  <div className="ml-4 flex flex-col gap-1">
                    {tools.map(t => (
                      <div key={t.name} className="flex items-baseline gap-2 py-1 text-[0.8125rem]">
                        <code className="text-[var(--accent-color)] text-[0.75rem] bg-[var(--bg-hover)] px-1.5 py-0.5 rounded">{t.name}</code>
                        <span className="text-[var(--text-muted)] text-[0.75rem] truncate">{t.description}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {/* MCP Servers */}
            {catalog.mcp_servers.length > 0 && (
              <div>
                <button
                  className="flex items-center gap-1.5 text-[0.8125rem] font-medium text-[var(--text-secondary)] bg-transparent border-none cursor-pointer p-0 mb-2"
                  onClick={() => toggleGroup('mcp')}
                >
                  {expandedGroups.mcp ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  External MCP Servers ({catalog.mcp_servers.length})
                </button>
                {expandedGroups.mcp && (
                  <div className="ml-4 flex flex-col gap-1">
                    {catalog.mcp_servers.map(s => (
                      <div key={s.name} className="flex items-center gap-2 py-1 text-[0.8125rem]">
                        <code className="text-[var(--success-color)] text-[0.75rem] bg-[var(--bg-hover)] px-1.5 py-0.5 rounded">{s.name}</code>
                        <span className="text-[0.6875rem] px-1.5 py-0.5 rounded-full bg-[var(--bg-hover)] text-[var(--text-muted)]">{s.type}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        {expandedSections.catalog && !catalog && isLoading && (
          <div className="text-[0.8125rem] text-[var(--text-muted)]">Loading catalog...</div>
        )}
      </section>
    </div>
  );
}
