'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { configApi } from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import { Eye, EyeOff } from 'lucide-react';
import NumberStepper from '@/components/ui/NumberStepper';
import InfoTooltip from '@/components/ui/InfoTooltip';
import type { ConfigItem, ConfigCategory, ConfigField, ConfigSchema } from '@/types';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

export default function SettingsTab() {
  const [configs, setConfigs] = useState<ConfigItem[]>([]);
  const [categories, setCategories] = useState<ConfigCategory[]>([]);
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [editing, setEditing] = useState<{ name: string; schema: ConfigSchema; values: Record<string, any> } | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importData, setImportData] = useState('');
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const loadConfigs = useCallback(async () => {
    try {
      const res = await configApi.list();
      setConfigs(res.configs || []);
      setCategories(res.categories || []);
    } catch (e: any) {
      setMsg({ type: 'error', text: e.message });
    }
  }, []);

  useEffect(() => { loadConfigs(); }, [loadConfigs]);
  useEffect(() => { if (msg) { const t = setTimeout(() => setMsg(null), 4000); return () => clearTimeout(t); } }, [msg]);

  const filtered = selectedCategory === 'all'
    ? configs
    : configs.filter(c => c.schema?.category === selectedCategory);

  const openEdit = async (name: string) => {
    try {
      const res = await configApi.get(name);
      setEditing({ name, schema: res.schema, values: { ...res.values } });
    } catch (e: any) {
      setMsg({ type: 'error', text: e.message });
    }
  };

  const updateField = (fieldName: string, value: any) => {
    setEditing(prev => prev ? { ...prev, values: { ...prev.values, [fieldName]: value } } : prev);
  };

  const saveConfig = async () => {
    if (!editing) return;
    const values: Record<string, any> = {};
    editing.schema.fields.forEach((field: ConfigField) => {
      const v = editing.values[field.name];
      if (field.type === 'textarea' && field.name.includes('_ids') && typeof v === 'string') {
        const text = v.trim();
        values[field.name] = text ? text.split(',').map((s: string) => s.trim()).filter(Boolean) : [];
      } else {
        values[field.name] = v;
      }
    });
    try {
      const res = await configApi.update(editing.name, values);
      if (res.success) { setMsg({ type: 'success', text: 'Configuration saved' }); setEditing(null); loadConfigs(); }
      else setMsg({ type: 'error', text: 'Save failed' });
    } catch (e: any) { setMsg({ type: 'error', text: e.message }); }
  };

  const resetConfig = async () => {
    if (!editing || !confirm(`Reset "${editing.schema.display_name}" to defaults?`)) return;
    try {
      const res = await configApi.reset(editing.name);
      if (res.success) { setMsg({ type: 'success', text: 'Reset to defaults' }); setEditing(null); loadConfigs(); }
    } catch (e: any) { setMsg({ type: 'error', text: e.message }); }
  };

  const exportConfigs = async () => {
    try {
      const res = await configApi.exportAll();
      if (res.success) {
        const blob = new Blob([JSON.stringify(res.configs, null, 2)], { type: 'application/json' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `geny-config-${new Date().toISOString().split('T')[0]}.json`;
        a.click();
        URL.revokeObjectURL(a.href);
        setMsg({ type: 'success', text: 'Exported' });
      }
    } catch (e: any) { setMsg({ type: 'error', text: e.message }); }
  };

  const importConfigs = async () => {
    if (!importData.trim()) return;
    try {
      const parsed = JSON.parse(importData);
      const res = await configApi.importAll(parsed);
      if (res.success) { setMsg({ type: 'success', text: res.message || 'Imported' }); setImportOpen(false); setImportData(''); loadConfigs(); }
      else setMsg({ type: 'error', text: res.message || 'Import failed' });
    } catch (e: any) { setMsg({ type: 'error', text: e.message || 'Invalid JSON' }); }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Toast */}
      {msg && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-2 rounded-[var(--border-radius)] text-[0.875rem] text-white ${msg.type === 'success' ? 'bg-[var(--success-color)]' : 'bg-[var(--danger-color)]'}`}>
          {msg.text}
        </div>
      )}

      {/* Header */}
      <div className="flex justify-between items-center py-4 px-5 border-b border-[var(--border-color)] bg-[var(--bg-secondary)] shrink-0">
        <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">Settings</h3>
        <div className="flex gap-2">
          <button className={cn("py-2 px-4 bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]", "!py-1.5 !px-3 text-[0.75rem]")} onClick={exportConfigs}>Export</button>
          <button className={cn("py-2 px-4 bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]", "!py-1.5 !px-3 text-[0.75rem]")} onClick={() => setImportOpen(true)}>Import</button>
          <button className={cn("py-2 px-4 bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]", "!py-1.5 !px-3 text-[0.75rem]")} onClick={loadConfigs}>Refresh</button>
        </div>
      </div>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Category Sidebar */}
        <div className="w-[200px] border-r border-[var(--border-color)] bg-[var(--bg-secondary)] overflow-y-auto">
          <div className="p-3">
            <button
              className={`w-full flex items-center gap-2.5 py-2.5 px-3 rounded-[var(--border-radius)] text-[0.875rem] font-medium text-left mb-1 transition-colors ${selectedCategory === 'all' ? 'bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'}`}
              onClick={() => setSelectedCategory('all')}
            >
              <span className="flex-1">All</span>
              <span className="text-[0.75rem] text-[var(--text-muted)] bg-[var(--bg-tertiary)] py-[2px] px-2 rounded-[10px]">{configs.length}</span>
            </button>
            {categories.map(cat => {
              const count = configs.filter(c => c.schema?.category === cat.name).length;
              return (
                <button key={cat.name}
                  className={`w-full flex items-center gap-2.5 py-2.5 px-3 rounded-[var(--border-radius)] text-[0.875rem] font-medium text-left mb-1 transition-colors ${selectedCategory === cat.name ? 'bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'}`}
                  onClick={() => setSelectedCategory(cat.name)}
                >
                  <span className="flex-1">{cat.label}</span>
                  <span className="text-[0.75rem] text-[var(--text-muted)] bg-[var(--bg-tertiary)] py-[2px] px-2 rounded-[10px]">{count}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Config List */}
        <div className="flex-1 overflow-y-auto p-5">
          {filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4"><p className="text-[0.8125rem] text-[var(--text-muted)]">No configurations found</p></div>
          ) : (
            <div className="flex flex-col gap-3">
              {filtered.map(config => {
                const schema = config.schema || {} as ConfigSchema;
                const values = config.values || {};
                const isEnabled = values.enabled === true;
                const configured = schema.fields?.filter((f: ConfigField) => {
                  const v = values[f.name];
                  return v !== undefined && v !== '' && v !== f.default;
                }).length || 0;
                const total = schema.fields?.length || 0;

                return (
                  <div key={schema.name}
                       className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius-lg)] py-4 px-5 cursor-pointer transition-all hover:bg-[var(--bg-hover)]"
                       style={{ borderLeft: `3px solid ${isEnabled ? 'var(--success-color)' : 'var(--text-muted)'}`, opacity: isEnabled ? 1 : 0.8 }}
                       onClick={() => openEdit(schema.name)}>
                    <div className="flex items-start gap-3.5">
                      <div className="flex-1 min-w-0">
                        <h4 className="text-[0.9375rem] font-semibold text-[var(--text-primary)] mb-1">{schema.display_name || schema.name}</h4>
                        <p className="text-[0.8125rem] text-[var(--text-secondary)] leading-[1.4] line-clamp-2">{schema.description || ''}</p>
                      </div>
                      <span className={`shrink-0 inline-block py-1 px-2.5 rounded-[12px] text-[0.75rem] font-medium ${isEnabled ? 'text-[var(--success-color)]' : 'text-[var(--text-muted)] bg-[var(--bg-tertiary)]'}`}
                            style={isEnabled ? { background: 'rgba(16, 185, 129, 0.15)' } : {}}>
                        {isEnabled ? 'Enabled' : 'Disabled'}
                      </span>
                    </div>
                    <div className="flex justify-between items-center mt-3 pt-3 border-t border-[var(--border-color)]">
                      <span className="text-[0.75rem] text-[var(--text-muted)]">{configured}/{total} fields configured</span>
                      {!config.valid && <span className="text-[0.75rem] text-[var(--warning-color)]">⚠️ {config.errors?.length || 0} issues</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Edit Modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setEditing(null)}>
          <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-[600px] max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center py-4 px-6 border-b border-[var(--border-color)]">
              <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">Edit: {editing.schema.display_name || editing.schema.name}</h3>
              <button className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer text-lg" onClick={() => setEditing(null)}>×</button>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-5">
              <form id="config-form" className="flex flex-col gap-6">
                {(() => {
                  const groups: Record<string, ConfigField[]> = {};
                  editing.schema.fields.forEach((f: ConfigField) => {
                    const g = f.group || 'general';
                    if (!groups[g]) groups[g] = [];
                    groups[g].push(f);
                  });
                  const groupLabels: Record<string, string> = {
                    connection: 'Connection', server: 'Server Settings', workspace: 'Workspace',
                    teams: 'Teams', permissions: 'Permissions', behavior: 'Behavior',
                    session: 'Session Settings', commands: 'Commands', graph: 'Microsoft Graph', general: 'General',
                    language: 'Language', api: 'API Settings', redis: 'Redis',
                    limits: 'Limits', telemetry: 'Telemetry', github: 'GitHub',
                  };
                  return Object.entries(groups).map(([groupName, fields]) => (
                    <div key={groupName} className="border border-[var(--border-color)] rounded-[var(--border-radius)] overflow-hidden">
                      <h4 className="text-[0.8125rem] font-semibold text-[var(--text-secondary)] py-3 px-4 bg-[var(--bg-tertiary)] m-0 border-b border-[var(--border-color)]">
                        {groupLabels[groupName] || groupName}
                      </h4>
                      <div className="p-4 flex flex-col gap-4">
                        {fields.map(field => {
                          const value = editing.values[field.name] ?? field.default ?? '';
                          return <ConfigFieldInput key={field.name} field={field} value={value} onChange={v => updateField(field.name, v)} />;
                        })}
                      </div>
                    </div>
                  ));
                })()}
              </form>
            </div>
            <div className="flex justify-end items-center gap-3 py-4 px-6 border-t border-[var(--border-color)]">
              <button className={cn("py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]", "!py-1.5 !px-3 text-[0.75rem]", '!text-[var(--danger-color)]')} onClick={resetConfig}>Reset to Defaults</button>
              <div className="flex gap-2">
                <button className={cn("py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]", "!py-1.5 !px-3 text-[0.75rem]")} onClick={() => setEditing(null)}>Cancel</button>
                <button className={cn("py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed", "!py-1.5 !px-3 text-[0.75rem]")} onClick={saveConfig}>Save</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Import Modal */}
      {importOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setImportOpen(false)}>
          <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[520px] max-h-[85vh] flex flex-col shadow-[var(--shadow-lg)]" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center py-4 px-6 border-b border-[var(--border-color)]">
              <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">Import Configuration</h3>
              <button className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer text-lg" onClick={() => setImportOpen(false)}>×</button>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-4">
              <textarea
                className="w-full p-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] font-mono text-[var(--text-primary)] resize-none focus:outline-none focus:border-[var(--primary-color)]"
                rows={10} placeholder="Paste configuration JSON here..."
                value={importData} onChange={e => setImportData(e.target.value)}
              />
            </div>
            <div className="flex justify-end items-center gap-3 py-4 px-6 border-t border-[var(--border-color)]">
              <button className={cn("py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]", "!py-1.5 !px-3 text-[0.75rem]")} onClick={() => setImportOpen(false)}>Cancel</button>
              <button className={cn("py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed", "!py-1.5 !px-3 text-[0.75rem]")} onClick={importConfigs}>Import</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ConfigFieldInput({ field, value, onChange }: { field: ConfigField; value: any; onChange: (v: any) => void }) {
  const [showPass, setShowPass] = useState(false);
  const id = `cf-${field.name}`;
  const effectiveType = field.type === 'password' ? 'string' : field.type;

  const labelEl = (
    <div className="flex items-center gap-1.5 mb-2">
      <label htmlFor={id} className="text-[0.8125rem] font-medium text-[var(--text-primary)]">{field.label}</label>
      {field.required && <span className="text-[var(--danger-color)]">*</span>}
      {field.description && <InfoTooltip text={field.description} />}
    </div>
  );

  const inputClasses = "w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)]";

  if (effectiveType === 'boolean') {
    const checked = !!value;
    return (
      <div className="flex items-center justify-between gap-3 py-1">
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          <label className="text-[0.8125rem] font-medium text-[var(--text-primary)]">{field.label}</label>
          {field.description && <InfoTooltip text={field.description} />}
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={checked}
          onClick={() => onChange(!checked)}
          className={`relative inline-flex h-[22px] w-[40px] shrink-0 cursor-pointer items-center rounded-full border-none transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary-color)] focus-visible:ring-offset-2 ${checked ? 'bg-[var(--primary-color)]' : 'bg-[var(--border-color)]'}`}
        >
          <span className={`pointer-events-none inline-block h-[18px] w-[18px] rounded-full bg-white shadow-sm transition-transform duration-200 ease-in-out ${checked ? 'translate-x-[20px]' : 'translate-x-[2px]'}`} />
        </button>
      </div>
    );
  }

  if (effectiveType === 'select') {
    return (
      <div>
        {labelEl}
        <select id={id} name={field.name} value={value ?? ''} onChange={e => onChange(e.target.value)} className={inputClasses}>
          <option value="">-- Select --</option>
          {(field.options || []).map((opt: any) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>
    );
  }

  if (effectiveType === 'textarea') {
    const textValue = Array.isArray(value) ? value.join(', ') : (value || '');
    return (
      <div>
        {labelEl}
        <textarea id={id} name={field.name} value={textValue}
                  onChange={e => onChange(e.target.value)}
                  rows={3} placeholder={field.placeholder || ''} className={inputClasses + ' resize-none font-mono'} />
      </div>
    );
  }

  if (effectiveType === 'number') {
    return (
      <div>
        {labelEl}
        <NumberStepper
          value={typeof value === 'number' ? value : (value ? Number(value) : 0)}
          onChange={onChange}
          min={field.min ?? 0}
          max={field.max ?? 99999}
        />
      </div>
    );
  }

  // string / url / email / password
  const inputType = field.secure ? (showPass ? 'text' : 'password')
    : effectiveType === 'url' ? 'url'
    : effectiveType === 'email' ? 'email'
    : 'text';

  return (
    <div>
      {labelEl}
      <div className="relative">
        <input type={inputType} id={id} name={field.name} value={value || ''}
               onChange={e => onChange(e.target.value)}
               placeholder={field.placeholder || ''} className={inputClasses + (field.secure ? ' pr-10' : '')} />
        {field.secure && (
          <button type="button"
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 flex items-center justify-center w-7 h-7 rounded-[var(--border-radius)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-all duration-150 border-none bg-transparent cursor-pointer"
                  onClick={() => setShowPass(!showPass)}
                  aria-label={showPass ? 'Hide' : 'Show'}>
            {showPass ? <EyeOff size={16} strokeWidth={1.8} /> : <Eye size={16} strokeWidth={1.8} />}
          </button>
        )}
      </div>
    </div>
  );
}
