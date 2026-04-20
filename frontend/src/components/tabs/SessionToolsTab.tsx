'use client';

import { useState, useEffect, useMemo } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { useToolPresetStore } from '@/store/useToolPresetStore';
import { useI18n } from '@/lib/i18n';
import {
  ChevronDown, ChevronRight, Wrench, Check, Server, Search, Boxes,
} from 'lucide-react';
import type { ToolInfo } from '@/types';

export default function SessionToolsTab() {
  const { selectedSessionId, sessions } = useAppStore();
  const { presets, catalog, loadPresets, loadCatalog } = useToolPresetStore();
  const { t } = useI18n();
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    built_in: true,
    custom_root: true,
  });
  const [searchTerm, setSearchTerm] = useState('');
  const [viewMode, setViewMode] = useState<'vtuber' | 'sub'>('vtuber');

  useEffect(() => { loadPresets(); loadCatalog(); }, [loadPresets, loadCatalog]);

  const session = sessions.find(s => s.session_id === selectedSessionId);

  // Find linked Sub-Worker session (if current is VTuber)
  const linkedSubWorkerSession = useMemo(() => {
    if (!session || session.session_type !== 'vtuber') return null;
    return sessions.find(s => s.session_type === 'sub' && s.linked_session_id === session.session_id) ?? null;
  }, [session, sessions]);

  const hasDualView = !!linkedSubWorkerSession;

  // Resolve which session to display
  const targetSession = useMemo(() => {
    if (!hasDualView || viewMode === 'vtuber') return session;
    return linkedSubWorkerSession ?? session;
  }, [hasDualView, viewMode, session, linkedSubWorkerSession]);

  // Reset viewMode when session changes
  useEffect(() => { setViewMode('vtuber'); }, [selectedSessionId]);

  const filteredBuiltIn = useMemo(() => {
    if (!catalog) return [];
    if (!searchTerm) return catalog.built_in;
    const q = searchTerm.toLowerCase();
    return catalog.built_in.filter(t => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q));
  }, [catalog, searchTerm]);

  const filteredMcpServers = useMemo(() => {
    if (!catalog) return [];
    if (!searchTerm) return catalog.mcp_servers;
    const q = searchTerm.toLowerCase();
    return catalog.mcp_servers.filter(s => s.name.toLowerCase().includes(q));
  }, [catalog, searchTerm]);

  // No session selected
  if (!selectedSessionId || !session) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center justify-center py-12 px-4">
          <h3 className="text-[1rem] font-medium text-[var(--text-secondary)] mb-2">
            {t('sessionTools.selectSession')}
          </h3>
          <p className="text-[0.8125rem] text-[var(--text-muted)]">
            {t('sessionTools.selectSessionDesc')}
          </p>
        </div>
      </div>
    );
  }

  const presetId = targetSession?.tool_preset_id;
  const boundPreset = presetId ? presets.find(p => p.id === presetId) : null;

  // Resolve which tools are enabled
  const isAllCustom = boundPreset?.custom_tools.includes('*') ?? true;
  const enabledCustomTools = new Set(isAllCustom ? [] : boundPreset?.custom_tools ?? []);
  const isAllMcp = boundPreset?.mcp_servers.includes('*') ?? true;
  const enabledMcpServers = new Set(isAllMcp ? [] : boundPreset?.mcp_servers ?? []);

  // Group & filter custom tools
  const groupedCustomTools: Record<string, ToolInfo[]> = {};
  if (catalog) {
    const q = searchTerm.toLowerCase();
    for (const tool of catalog.custom) {
      if (q && !tool.name.toLowerCase().includes(q) && !tool.description.toLowerCase().includes(q)) continue;
      const group = tool.group || 'other';
      if (!groupedCustomTools[group]) groupedCustomTools[group] = [];
      groupedCustomTools[group].push(tool);
    }
  }

  const toggleGroup = (group: string) => {
    setExpandedGroups(prev => ({ ...prev, [group]: !prev[group] }));
  };

  const customToolCount = isAllCustom
    ? (catalog?.custom.length ?? 0)
    : enabledCustomTools.size;

  // Built-in MCP servers are always included regardless of preset filter
  const builtInMcpCount = catalog?.mcp_servers.filter(s => s.is_built_in).length ?? 0;
  const mcpServerCount = isAllMcp
    ? (catalog?.mcp_servers.length ?? 0)
    : enabledMcpServers.size + builtInMcpCount;

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden bg-[var(--bg-primary)]">
      {/* Header bar */}
      <div className="shrink-0 hidden md:flex items-center justify-between px-4 py-2 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[#f59e0b] to-[#f97316] flex items-center justify-center shadow-sm shrink-0">
            <Wrench size={13} className="text-white" />
          </div>
          <h3 className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">
            {t('sessionTools.title')}
          </h3>

          {/* VTuber / Sub-Worker toggle */}
          {hasDualView && (
            <div className="flex items-center h-6 rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)] overflow-hidden shrink-0">
              <button
                className={`px-2 h-full text-[10px] font-semibold transition-colors ${
                  viewMode === 'vtuber'
                    ? 'bg-[var(--primary-color)] text-white'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
                }`}
                onClick={() => setViewMode('vtuber')}
              >
                VTuber
              </button>
              <button
                className={`px-2 h-full text-[10px] font-semibold transition-colors ${
                  viewMode === 'sub'
                    ? 'bg-[var(--primary-color)] text-white'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'
                }`}
                onClick={() => setViewMode('sub')}
              >
                Sub-Worker
              </button>
            </div>
          )}

          {/* Preset name */}
          {boundPreset && (
            <>
              <span className="w-px h-4 bg-[var(--border-color)]" />
              <span className="text-[0.75rem] font-medium text-[var(--text-secondary)] truncate max-w-[200px]">
                {boundPreset.name}
              </span>
              {boundPreset.is_template && (
                <span className="text-[10px] font-semibold py-[2px] px-1.5 rounded-md bg-[rgba(168,85,247,0.12)] text-[#c084fc] border border-[rgba(168,85,247,0.2)] uppercase tracking-wide shrink-0">
                  {t('toolSetsTab.template')}
                </span>
              )}
            </>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Stats pills */}
          <span className="text-[10px] text-[var(--text-muted)]">
            {t('sessionTools.builtInCount', { count: catalog?.built_in.length ?? 0 })}
          </span>
          <span className="w-px h-3 bg-[var(--border-color)]" />
          <span className="text-[10px] text-[var(--accent-color)]">
            {t('sessionTools.customCount', { count: customToolCount })}
          </span>
          <span className="w-px h-3 bg-[var(--border-color)]" />
          <span className="text-[10px] text-[var(--success-color)]">
            {t('sessionTools.mcpCount', { count: mcpServerCount })}
          </span>
        </div>
      </div>

      {/* Preset info bar (if bound) */}
      {!boundPreset && (
        <div className="shrink-0 px-4 py-2 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)] text-[0.75rem] text-[var(--text-muted)]">
          {presetId
            ? t('sessionTools.presetNotFound', { id: presetId })
            : t('sessionTools.defaultPreset')}
        </div>
      )}
      {boundPreset?.description && (
        <div className="shrink-0 px-4 py-2 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)] text-[0.75rem] text-[var(--text-muted)]">
          {boundPreset.description}
        </div>
      )}

      {/* Search */}
      <div className="shrink-0 px-4 py-2 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            className="w-full pl-8 pr-3 py-1.5 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-md text-[0.75rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] transition-all"
            placeholder={t('sessionTools.searchPlaceholder')}
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
          />
        </div>
      </div>

      {/* Tool list */}
      <div className="flex-1 overflow-y-auto">
        {/* Built-in Tools */}
        <div className="border-b border-[var(--border-color)]">
          <button
            className="w-full flex items-center gap-2 px-4 py-2.5 text-[0.8125rem] font-semibold text-[var(--text-primary)] bg-[var(--bg-secondary)] border-none cursor-pointer hover:bg-[var(--bg-hover)] transition-colors text-left"
            onClick={() => toggleGroup('built_in')}
          >
            {expandedGroups.built_in ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            <Wrench size={13} className="text-[var(--primary-color)]" />
            <span>{t('sessionTools.builtInTools')}</span>
            <span className="text-[0.6875rem] font-normal text-[var(--text-muted)]">
              ({filteredBuiltIn.length}) — {t('sessionTools.alwaysEnabled')}
            </span>
          </button>
          {expandedGroups.built_in && (
            <div className="px-4 pb-2 bg-[var(--bg-primary)]">
              {filteredBuiltIn.map(tool => (
                <div key={tool.name} className="flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-[var(--bg-hover)] transition-colors">
                  <Check size={11} className="text-[var(--success-color)] shrink-0" />
                  <code className="text-[var(--primary-color)] text-[0.75rem] bg-[var(--bg-hover)] px-1.5 py-0.5 rounded shrink-0">{tool.name}</code>
                  <span className="text-[var(--text-muted)] text-[0.75rem] truncate">{tool.description}</span>
                </div>
              ))}
              {filteredBuiltIn.length === 0 && (
                <p className="text-[0.75rem] text-[var(--text-muted)] py-3 text-center">{t('sessionTools.noResults')}</p>
              )}
            </div>
          )}
        </div>

        {/* Custom Tools */}
        <div className="border-b border-[var(--border-color)]">
          <button
            className="w-full flex items-center gap-2 px-4 py-2.5 text-[0.8125rem] font-semibold text-[var(--text-primary)] bg-[var(--bg-secondary)] border-none cursor-pointer hover:bg-[var(--bg-hover)] transition-colors text-left"
            onClick={() => toggleGroup('custom_root')}
          >
            {expandedGroups.custom_root ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            <Boxes size={13} className="text-[var(--accent-color)]" />
            <span>{t('sessionTools.customTools')}</span>
            <span className="text-[0.6875rem] font-normal text-[var(--text-muted)]">
              ({customToolCount})
              {isAllCustom && ` — ${t('sessionTools.allEnabled')}`}
            </span>
          </button>
          {expandedGroups.custom_root && (
            <div className="px-4 pb-2 bg-[var(--bg-primary)]">
              {Object.entries(groupedCustomTools).map(([group, tools]) => (
                <div key={group} className="mb-1">
                  <button
                    className="flex items-center gap-1.5 text-[0.75rem] font-medium text-[var(--text-secondary)] bg-transparent border-none cursor-pointer p-0 py-1.5"
                    onClick={() => toggleGroup(`custom_${group}`)}
                  >
                    {expandedGroups[`custom_${group}`] ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                    {group.replace(/_/g, ' ')} ({tools.length})
                  </button>
                  {expandedGroups[`custom_${group}`] && (
                    <div className="ml-4">
                      {tools.map(tool => {
                        const enabled = isAllCustom || enabledCustomTools.has(tool.name);
                        return (
                          <div
                            key={tool.name}
                            className={`flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-[var(--bg-hover)] transition-colors ${!enabled ? 'opacity-40' : ''}`}
                          >
                            {enabled
                              ? <Check size={11} className="text-[var(--success-color)] shrink-0" />
                              : <span className="w-[11px] h-[11px] shrink-0" />}
                            <code className="text-[var(--accent-color)] text-[0.75rem] bg-[var(--bg-hover)] px-1.5 py-0.5 rounded shrink-0">{tool.name}</code>
                            <span className="text-[var(--text-muted)] text-[0.75rem] truncate">{tool.description}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
              {Object.keys(groupedCustomTools).length === 0 && (
                <p className="text-[0.75rem] text-[var(--text-muted)] py-3 text-center">{t('sessionTools.noResults')}</p>
              )}
            </div>
          )}
        </div>

        {/* MCP Servers */}
        {(catalog?.mcp_servers.length ?? 0) > 0 && (
          <div className="border-b border-[var(--border-color)]">
            <button
              className="w-full flex items-center gap-2 px-4 py-2.5 text-[0.8125rem] font-semibold text-[var(--text-primary)] bg-[var(--bg-secondary)] border-none cursor-pointer hover:bg-[var(--bg-hover)] transition-colors text-left"
              onClick={() => toggleGroup('mcp_root')}
            >
              {expandedGroups.mcp_root ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              <Server size={13} className="text-[var(--success-color)]" />
              <span>{t('sessionTools.mcpServers')}</span>
              <span className="text-[0.6875rem] font-normal text-[var(--text-muted)]">
                ({mcpServerCount})
                {isAllMcp && ` — ${t('sessionTools.allEnabled')}`}
              </span>
            </button>
            {expandedGroups.mcp_root && (
              <div className="px-4 pb-2 bg-[var(--bg-primary)]">
                {filteredMcpServers.map(server => {
                  const enabled = server.is_built_in || isAllMcp || enabledMcpServers.has(server.name);
                  return (
                    <div
                      key={server.name}
                      className={`flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-[var(--bg-hover)] transition-colors ${!enabled ? 'opacity-40' : ''}`}
                    >
                      {enabled
                        ? <Check size={11} className="text-[var(--success-color)] shrink-0" />
                        : <span className="w-[11px] h-[11px] shrink-0" />}
                      <code className="text-[var(--success-color)] text-[0.75rem] bg-[var(--bg-hover)] px-1.5 py-0.5 rounded">{server.name}</code>
                      <span className="text-[0.6875rem] px-1.5 py-0.5 rounded-full bg-[var(--bg-hover)] text-[var(--text-muted)]">{server.type}</span>
                      {server.is_built_in && (
                        <span className="text-[10px] font-semibold py-[1px] px-1.5 rounded-md bg-[rgba(34,197,94,0.12)] text-[var(--success-color)] border border-[rgba(34,197,94,0.2)] uppercase tracking-wide shrink-0">
                          {t('sessionTools.builtInMcp')}
                        </span>
                      )}
                      {server.description && (
                        <span className="text-[var(--text-muted)] text-[0.6875rem] truncate">{server.description}</span>
                      )}
                    </div>
                  );
                })}
                {filteredMcpServers.length === 0 && (
                  <p className="text-[0.75rem] text-[var(--text-muted)] py-3 text-center">{t('sessionTools.noResults')}</p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
