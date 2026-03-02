'use client';

import { useState, useEffect, useCallback } from 'react';
import { toolPresetApi } from '@/lib/toolPresetApi';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';
import {
  X, Plus, Server, Wrench, Copy, Pencil, Check,
  ChevronDown, ChevronUp, Shield, Eye, ArrowLeft,
} from 'lucide-react';
import type { ToolPreset, AvailableToolsResponse } from '@/types';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

// ==================== Toggle Switch ====================

function Toggle({
  checked,
  onChange,
  disabled = false,
  size = 'md',
}: {
  checked: boolean;
  onChange?: (value: boolean) => void;
  disabled?: boolean;
  size?: 'sm' | 'md';
}) {
  const w = size === 'sm' ? 'w-8' : 'w-9';
  const h = size === 'sm' ? 'h-[18px]' : 'h-5';
  const dot = size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4';
  const translate = size === 'sm' ? 'translate-x-[14px]' : 'translate-x-[16px]';

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      className={cn(
        'relative inline-flex items-center shrink-0 rounded-full transition-colors duration-200 cursor-pointer border-none',
        w, h,
        checked ? 'bg-[var(--primary-color)]' : 'bg-[var(--text-muted)]/30',
        disabled && 'opacity-40 cursor-not-allowed',
      )}
      onClick={() => onChange?.(!checked)}
    >
      <span
        className={cn(
          'inline-block rounded-full bg-white shadow-sm transition-transform duration-200',
          dot,
          checked ? translate : 'translate-x-[2px]',
        )}
      />
    </button>
  );
}

// ==================== Toggle Section (for Edit & View) ====================

function ToggleSection({
  title,
  icon,
  items,
  selected,
  isWildcard,
  readOnly = false,
  onChange,
  onToggleWildcard,
}: {
  title: string;
  icon: React.ReactNode;
  items: { name: string; description: string }[];
  selected: string[];
  isWildcard: boolean;
  readOnly?: boolean;
  onChange?: (name: string, checked: boolean) => void;
  onToggleWildcard?: () => void;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(true);

  const itemNames = new Set(items.map(i => i.name));
  const enabledCount = isWildcard ? items.length : selected.filter(s => itemNames.has(s)).length;

  return (
    <div className="border border-[var(--border-color)] rounded-lg overflow-hidden">
      {/* Section Header */}
      <button
        className="w-full flex items-center gap-2 py-2.5 px-3.5 bg-[var(--bg-secondary)] text-left text-[0.8125rem] font-medium text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        {icon}
        <span className="flex-1">{title}</span>
        <span className={cn(
          'text-[0.6875rem] font-semibold px-1.5 py-0.5 rounded-md',
          enabledCount > 0
            ? 'bg-[rgba(59,130,246,0.12)] text-[var(--primary-color)]'
            : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]',
        )}>
          {enabledCount}/{items.length}
        </span>
        {expanded ? <ChevronUp size={14} className="text-[var(--text-muted)]" /> : <ChevronDown size={14} className="text-[var(--text-muted)]" />}
      </button>

      {expanded && (
        <div className="border-t border-[var(--border-color)]">
          {/* Enable All row */}
          {!readOnly && (
            <>
              <div className="flex items-center justify-between py-2.5 px-3.5 bg-[var(--bg-primary)]">
                <span className="text-[0.8125rem] font-semibold text-[var(--primary-color)]">{t('toolPresets.enableAll')}</span>
                <Toggle checked={isWildcard} onChange={() => onToggleWildcard?.()} />
              </div>
              <div className="h-px bg-[var(--border-color)]" />
            </>
          )}

          {items.length === 0 ? (
            <p className="text-[0.75rem] text-[var(--text-muted)] py-4 text-center">{t('toolPresets.noneAvailable')}</p>
          ) : (
            <div className="divide-y divide-[var(--border-color)]">
              {items.map(item => {
                const isOn = isWildcard || selected.includes(item.name);
                return (
                  <div
                    key={item.name}
                    className={cn(
                      'flex items-center gap-3 py-2.5 px-3.5 transition-colors',
                      !readOnly && !isWildcard && 'hover:bg-[var(--bg-tertiary)]',
                      readOnly && !isOn && 'opacity-40',
                    )}
                  >
                    {/* Status dot for view mode / toggle for edit mode */}
                    {readOnly ? (
                      <span className={cn(
                        'w-2 h-2 rounded-full shrink-0',
                        isOn ? 'bg-[var(--success-color)] shadow-[0_0_4px_var(--success-color)]' : 'bg-[var(--text-muted)]/40',
                      )} />
                    ) : (
                      <Toggle
                        checked={isOn}
                        onChange={v => onChange?.(item.name, v)}
                        disabled={isWildcard}
                        size="sm"
                      />
                    )}

                    {/* Info */}
                    <div className="flex flex-col min-w-0 flex-1">
                      <span className={cn(
                        'text-[0.8125rem] font-mono truncate',
                        isOn ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]',
                      )}>
                        {item.name}
                      </span>
                      {item.description && (
                        <span className="text-[0.6875rem] text-[var(--text-muted)] line-clamp-1">{item.description}</span>
                      )}
                    </div>

                    {/* Badge */}
                    {readOnly && (
                      <span className={cn(
                        'text-[0.625rem] font-semibold px-1.5 py-0.5 rounded-md uppercase tracking-wider shrink-0',
                        isOn
                          ? 'bg-[rgba(16,185,129,0.12)] text-[#10b981]'
                          : 'bg-[rgba(107,114,128,0.12)] text-[var(--text-muted)]',
                      )}>
                        {isOn ? t('toolPresets.on') : t('toolPresets.off')}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
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
  preset: ToolPreset;
  isSelected: boolean;
  onSelect: () => void;
  onView?: () => void;
  onEdit?: () => void;
  onClone?: () => void;
  onDelete?: () => void;
}) {
  const { t } = useI18n();
  const isWildcardServers = preset.allowed_servers.length === 1 && preset.allowed_servers[0] === '*';
  const isWildcardTools = preset.allowed_tools.length === 1 && preset.allowed_tools[0] === '*';
  const serverCount = isWildcardServers ? t('toolPresets.allServers') : t('toolPresets.serverCount', { count: preset.allowed_servers.length });
  const toolCount = isWildcardTools ? t('toolPresets.allTools') : t('toolPresets.toolCount', { count: preset.allowed_tools.length });

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
      {/* Header Row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Shield size={14} className="shrink-0 text-[var(--primary-color)]" />
          <h4 className="text-[0.875rem] font-semibold text-[var(--text-primary)] truncate">{preset.name}</h4>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {preset.is_template && (
            <span className="text-[10px] font-semibold py-0.5 px-1.5 rounded-md bg-[rgba(168,85,247,0.12)] text-[#c084fc] border border-[rgba(168,85,247,0.2)] uppercase tracking-wide">
              {t('toolPresets.template')}
            </span>
          )}
        </div>
      </div>

      {/* Description */}
      <p className="text-[0.75rem] text-[var(--text-muted)] line-clamp-2 leading-[1.5]">
        {preset.description || t('toolPresets.noDescription')}
      </p>

      {/* Stats */}
      <div className="flex items-center gap-3 text-[0.6875rem] text-[var(--text-muted)]">
        <span className="flex items-center gap-1">
          <Server size={10} className="text-[var(--primary-color)]" />
          {serverCount}
        </span>
        <span className="flex items-center gap-1">
          <Wrench size={10} className="text-[var(--text-muted)]" />
          {toolCount}
        </span>
      </div>

      {/* Action Buttons (visible on hover) */}
      <div className="absolute bottom-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {onView && (
          <button
            className="h-7 px-2 flex items-center gap-1 justify-center rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
            title={t('common.view')}
            onClick={e => { e.stopPropagation(); onView(); }}
          >
            <Eye size={12} />
            {t('common.view')}
          </button>
        )}
        {onEdit && !preset.is_template && (
          <button
            className="h-7 px-2 flex items-center gap-1 justify-center rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
            title={t('common.edit')}
            onClick={e => { e.stopPropagation(); onEdit(); }}
          >
            <Pencil size={12} />
          </button>
        )}
        {onClone && (
          <button
            className="h-7 px-2 flex items-center justify-center rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
            title={t('common.clone')}
            onClick={e => { e.stopPropagation(); onClone(); }}
          >
            <Copy size={12} />
          </button>
        )}
        {onDelete && !preset.is_template && (
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

// ==================== View Panel (read-only) ====================

function ViewPanel({
  preset,
  available,
  onBack,
  onEdit,
  onClone,
}: {
  preset: ToolPreset;
  available: AvailableToolsResponse;
  onBack: () => void;
  onEdit?: () => void;
  onClone: () => void;
}) {
  const { t } = useI18n();
  const isWildcardServers = preset.allowed_servers.length === 1 && preset.allowed_servers[0] === '*';
  const isWildcardTools = preset.allowed_tools.length === 1 && preset.allowed_tools[0] === '*';

  const availServerNames = new Set(available.servers.map(s => s.name));
  const availToolNames = new Set(available.tools.map(t => t.name));
  const enabledServerCount = isWildcardServers ? available.servers.length : preset.allowed_servers.filter(s => s !== '*' && availServerNames.has(s)).length;
  const enabledToolCount = isWildcardTools ? available.tools.length : preset.allowed_tools.filter(s => s !== '*' && availToolNames.has(s)).length;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between py-3 px-5 border-b border-[var(--border-color)] shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <button
            className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer transition-colors"
            onClick={onBack}
          >
            <ArrowLeft size={16} />
          </button>
          <div className="flex items-center gap-2 min-w-0">
            <Shield size={16} className="text-[var(--primary-color)] shrink-0" />
            <h3 className="text-[0.9375rem] font-semibold text-[var(--text-primary)] truncate">{preset.name}</h3>
            {preset.is_template && (
              <span className="text-[10px] font-semibold py-0.5 px-1.5 rounded-md bg-[rgba(168,85,247,0.12)] text-[#c084fc] border border-[rgba(168,85,247,0.2)] uppercase tracking-wide shrink-0">
                {t('toolPresets.template')}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {onEdit && (
            <button
              className="py-1.5 px-3 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)] inline-flex items-center gap-1.5"
              onClick={onEdit}
            >
              <Pencil size={13} /> {t('common.edit')}
            </button>
          )}
          <button
            className="py-1.5 px-3 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)] inline-flex items-center gap-1.5"
            onClick={onClone}
          >
            <Copy size={13} /> {t('common.clone')}
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {/* Description */}
        {preset.description && (
          <p className="text-[0.8125rem] text-[var(--text-muted)] leading-[1.6]">{preset.description}</p>
        )}

        {/* Summary badges */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center gap-1.5 text-[0.75rem] font-medium py-1 px-2.5 rounded-full bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)] border border-[rgba(59,130,246,0.15)]">
            <Server size={12} />
            {enabledServerCount}/{available.servers.length} {t('toolPresets.serversEnabled')}
          </span>
          <span className="inline-flex items-center gap-1.5 text-[0.75rem] font-medium py-1 px-2.5 rounded-full bg-[rgba(16,185,129,0.1)] text-[#10b981] border border-[rgba(16,185,129,0.15)]">
            <Wrench size={12} />
            {enabledToolCount}/{available.tools.length} {t('toolPresets.toolsEnabled')}
          </span>
        </div>

        {/* MCP Servers — read-only */}
        <ToggleSection
          title={t('toolPresets.mcpServers')}
          icon={<Server size={14} className="text-[var(--primary-color)]" />}
          items={available.servers.map(s => ({ name: s.name, description: s.description }))}
          selected={preset.allowed_servers.filter(s => s !== '*')}
          isWildcard={isWildcardServers}
          readOnly
        />

        {/* Built-in Tools — read-only */}
        <ToggleSection
          title={t('toolPresets.builtInTools')}
          icon={<Wrench size={14} className="text-[var(--text-muted)]" />}
          items={available.tools.map(tool => ({ name: tool.name, description: tool.description }))}
          selected={preset.allowed_tools.filter(s => s !== '*')}
          isWildcard={isWildcardTools}
          readOnly
        />
      </div>
    </div>
  );
}

// ==================== Edit Panel ====================

function EditPanel({
  preset,
  available,
  onSave,
  onCancel,
  isNew,
}: {
  preset: ToolPreset;
  available: AvailableToolsResponse;
  onSave: (data: { name: string; description: string; allowed_servers: string[]; allowed_tools: string[] }) => void;
  onCancel: () => void;
  isNew: boolean;
}) {
  const { t } = useI18n();
  const [name, setName] = useState(preset.name);
  const [description, setDescription] = useState(preset.description);
  const [allowedServers, setAllowedServers] = useState<string[]>(preset.allowed_servers);
  const [allowedTools, setAllowedTools] = useState<string[]>(preset.allowed_tools);
  const [saving, setSaving] = useState(false);

  const isWildcardServers = allowedServers.length === 1 && allowedServers[0] === '*';
  const isWildcardTools = allowedTools.length === 1 && allowedTools[0] === '*';

  const handleServerChange = (name: string, checked: boolean) => {
    setAllowedServers(prev =>
      checked ? [...prev, name] : prev.filter(s => s !== name)
    );
  };

  const handleToolChange = (name: string, checked: boolean) => {
    setAllowedTools(prev =>
      checked ? [...prev, name] : prev.filter(s => s !== name)
    );
  };

  const handleSubmit = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await onSave({
        name: name.trim(),
        description: description.trim(),
        allowed_servers: allowedServers,
        allowed_tools: allowedTools,
      });
    } finally {
      setSaving(false);
    }
  };

  // Count enabled items for summary
  const availServerNames = new Set(available.servers.map(s => s.name));
  const availToolNames = new Set(available.tools.map(t => t.name));
  const enabledServerCount = isWildcardServers ? available.servers.length : allowedServers.filter(s => s !== '*' && availServerNames.has(s)).length;
  const enabledToolCount = isWildcardTools ? available.tools.length : allowedTools.filter(s => s !== '*' && availToolNames.has(s)).length;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between py-3 px-5 border-b border-[var(--border-color)] shrink-0">
        <h3 className="text-[0.9375rem] font-semibold text-[var(--text-primary)]">
          {isNew ? t('toolPresets.newPreset') : t('toolPresets.editPreset')}
        </h3>
        <div className="flex items-center gap-2">
          <button
            className="py-1.5 px-3 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]"
            onClick={onCancel}
          >
            {t('common.cancel')}
          </button>
          <button
            className="py-1.5 px-3 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
            onClick={handleSubmit}
            disabled={!name.trim() || saving}
          >
            <Check size={14} />
            {saving ? t('common.loading') : t('common.save')}
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {/* Name */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">{t('toolPresets.nameLabel')}</label>
          <input
            className="w-full py-2 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)]"
            placeholder={t('toolPresets.namePlaceholder')}
            value={name}
            onChange={e => setName(e.target.value)}
          />
        </div>

        {/* Description */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">{t('toolPresets.descriptionLabel')}</label>
          <textarea
            className="w-full py-2 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] resize-y"
            rows={2}
            placeholder={t('toolPresets.descriptionPlaceholder')}
            value={description}
            onChange={e => setDescription(e.target.value)}
          />
        </div>

        {/* Summary */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center gap-1.5 text-[0.75rem] font-medium py-1 px-2.5 rounded-full bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)] border border-[rgba(59,130,246,0.15)]">
            <Server size={12} />
            {enabledServerCount}/{available.servers.length} {t('toolPresets.serversEnabled')}
          </span>
          <span className="inline-flex items-center gap-1.5 text-[0.75rem] font-medium py-1 px-2.5 rounded-full bg-[rgba(16,185,129,0.1)] text-[#10b981] border border-[rgba(16,185,129,0.15)]">
            <Wrench size={12} />
            {enabledToolCount}/{available.tools.length} {t('toolPresets.toolsEnabled')}
          </span>
        </div>

        {/* MCP Servers */}
        <ToggleSection
          title={t('toolPresets.mcpServers')}
          icon={<Server size={14} className="text-[var(--primary-color)]" />}
          items={available.servers.map(s => ({ name: s.name, description: s.description }))}
          selected={allowedServers.filter(s => s !== '*')}
          isWildcard={isWildcardServers}
          onChange={handleServerChange}
          onToggleWildcard={() => setAllowedServers(isWildcardServers ? [] : ['*'])}
        />

        {/* Built-in Tools */}
        <ToggleSection
          title={t('toolPresets.builtInTools')}
          icon={<Wrench size={14} className="text-[var(--text-muted)]" />}
          items={available.tools.map(tool => ({ name: tool.name, description: tool.description }))}
          selected={allowedTools.filter(s => s !== '*')}
          isWildcard={isWildcardTools}
          onChange={handleToolChange}
          onToggleWildcard={() => setAllowedTools(isWildcardTools ? [] : ['*'])}
        />
      </div>
    </div>
  );
}

// ==================== Main Component ====================

export default function ToolPresetsTab() {
  const { t } = useI18n();
  const [presets, setPresets] = useState<ToolPreset[]>([]);
  const [available, setAvailable] = useState<AvailableToolsResponse>({ servers: [], tools: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<'list' | 'view' | 'edit' | 'create'>('list');
  const [editPreset, setEditPreset] = useState<ToolPreset | null>(null);
  const [viewPreset, setViewPreset] = useState<ToolPreset | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [presetsRes, availRes] = await Promise.all([
        toolPresetApi.list(),
        toolPresetApi.listAvailable(),
      ]);
      setPresets(presetsRes.presets || []);
      setAvailable(availRes);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const templates = presets.filter(p => p.is_template);
  const custom = presets.filter(p => !p.is_template);

  const handleView = (id: string) => {
    const preset = presets.find(p => p.id === id);
    if (!preset) return;
    setViewPreset(preset);
    setMode('view');
  };

  const handleClone = async (id: string) => {
    try {
      const cloned = await toolPresetApi.clone(id);
      setPresets(prev => [...prev, cloned]);
      setSelectedId(cloned.id);
      // If cloned from view, go to edit
      if (mode === 'view') {
        setEditPreset(cloned);
        setMode('edit');
        setViewPreset(null);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDelete = async (id: string) => {
    const preset = presets.find(p => p.id === id);
    if (!preset) return;
    if (!confirm(t('toolPresets.deleteConfirm', { name: preset.name }))) return;
    try {
      await toolPresetApi.delete(id);
      setPresets(prev => prev.filter(p => p.id !== id));
      if (selectedId === id) setSelectedId(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleEdit = (id: string) => {
    const preset = presets.find(p => p.id === id);
    if (!preset) return;
    setEditPreset(preset);
    setViewPreset(null);
    setMode('edit');
  };

  const handleCreate = () => {
    setEditPreset({
      id: '',
      name: '',
      description: '',
      allowed_servers: [],
      allowed_tools: [],
      is_template: false,
      created_at: '',
      updated_at: '',
    });
    setMode('create');
  };

  const handleSave = async (data: { name: string; description: string; allowed_servers: string[]; allowed_tools: string[] }) => {
    try {
      if (mode === 'create') {
        const created = await toolPresetApi.create(data);
        setPresets(prev => [...prev, created]);
        setSelectedId(created.id);
      } else if (editPreset) {
        const updated = await toolPresetApi.update(editPreset.id, data);
        setPresets(prev => prev.map(p => p.id === updated.id ? updated : p));
      }
      setMode('list');
      setEditPreset(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const goBackToList = () => {
    setMode('list');
    setEditPreset(null);
    setViewPreset(null);
  };

  // ── View Mode ──
  if (mode === 'view' && viewPreset) {
    return (
      <div className="flex flex-col h-full bg-[var(--bg-primary)]">
        <ViewPanel
          preset={viewPreset}
          available={available}
          onBack={goBackToList}
          onEdit={viewPreset.is_template ? undefined : () => handleEdit(viewPreset.id)}
          onClone={() => handleClone(viewPreset.id)}
        />
      </div>
    );
  }

  // ── Edit / Create Mode ──
  if ((mode === 'edit' || mode === 'create') && editPreset) {
    return (
      <div className="flex flex-col h-full bg-[var(--bg-primary)]">
        <EditPanel
          preset={editPreset}
          available={available}
          onSave={handleSave}
          onCancel={goBackToList}
          isNew={mode === 'create'}
        />
      </div>
    );
  }

  // ── List View ──
  return (
    <div className="flex flex-col h-full bg-[var(--bg-primary)]">
      {/* Header */}
      <div className="flex items-center justify-between py-4 px-5 border-b border-[var(--border-color)] shrink-0">
        <div>
          <h2 className="text-[1rem] font-semibold text-[var(--text-primary)] m-0">{t('toolPresets.title')}</h2>
          <p className="text-[0.75rem] text-[var(--text-muted)] mt-1">{t('toolPresets.subtitle')}</p>
        </div>
        <button
          className="py-1.5 px-3 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none inline-flex items-center gap-1.5"
          onClick={handleCreate}
        >
          <Plus size={14} /> {t('toolPresets.newPreset')}
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {error && (
          <div className="text-[0.8125rem] text-[var(--danger-color)] bg-[rgba(239,68,68,0.1)] p-2.5 rounded-[6px] mb-4">{error}</div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-12 text-[var(--text-muted)]">{t('common.loading')}</div>
        ) : (
          <>
            {/* Templates */}
            {templates.length > 0 && (
              <div className="mb-6">
                <h3 className="text-[0.75rem] font-semibold uppercase tracking-wide text-[var(--text-muted)] mb-3">{t('toolPresets.builtInTemplates')}</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {templates.map(p => (
                    <PresetCard
                      key={p.id}
                      preset={p}
                      isSelected={selectedId === p.id}
                      onSelect={() => setSelectedId(p.id)}
                      onView={() => handleView(p.id)}
                      onClone={() => handleClone(p.id)}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Custom Presets */}
            <div>
              <h3 className="text-[0.75rem] font-semibold uppercase tracking-wide text-[var(--text-muted)] mb-3">{t('toolPresets.customPresets')}</h3>
              {custom.length === 0 ? (
                <div className="text-center py-8">
                  <p className="text-[0.8125rem] text-[var(--text-muted)] mb-3">{t('toolPresets.noCustom')}</p>
                  <button
                    className="text-[0.8125rem] text-[var(--primary-color)] hover:underline cursor-pointer bg-transparent border-none"
                    onClick={handleCreate}
                  >
                    {t('toolPresets.createFirst')}
                  </button>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {custom.map(p => (
                    <PresetCard
                      key={p.id}
                      preset={p}
                      isSelected={selectedId === p.id}
                      onSelect={() => setSelectedId(p.id)}
                      onView={() => handleView(p.id)}
                      onEdit={() => handleEdit(p.id)}
                      onClone={() => handleClone(p.id)}
                      onDelete={() => handleDelete(p.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
