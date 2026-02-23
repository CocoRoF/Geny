'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { configApi } from '@/lib/api';
import type { ConfigItem, ConfigCategory, ConfigField, ConfigSchema } from '@/types';

const CATEGORY_ICONS: Record<string, string> = { general: '🔧', channels: '💬', security: '🔒', advanced: '⚡' };
const CONFIG_ICONS: Record<string, string> = { discord: '🎮', slack: '💼', teams: '👥', settings: '⚙️' };

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

  const saveConfig = async () => {
    if (!editing) return;
    const form = document.getElementById('config-form') as HTMLFormElement;
    const values: Record<string, any> = {};

    editing.schema.fields.forEach((field: ConfigField) => {
      const el = document.getElementById(`cf-${field.name}`) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null;
      if (!el) return;
      if (field.type === 'boolean') values[field.name] = (el as HTMLInputElement).checked;
      else if (field.type === 'number') values[field.name] = el.value ? Number(el.value) : null;
      else if (field.type === 'textarea' && field.name.includes('_ids')) {
        const text = (el as HTMLTextAreaElement).value.trim();
        values[field.name] = text ? text.split(',').map(s => s.trim()).filter(Boolean) : [];
      } else values[field.name] = el.value;
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
          <button className="btn btn-secondary btn-sm" onClick={exportConfigs}>Export</button>
          <button className="btn btn-secondary btn-sm" onClick={() => setImportOpen(true)}>Import</button>
          <button className="btn btn-secondary btn-sm" onClick={loadConfigs}>Refresh</button>
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
              <span className="text-[1rem]">⚙️</span>
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
                  <span className="text-[1rem]">{CATEGORY_ICONS[cat.name] || '📁'}</span>
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
            <div className="empty-state"><p>No configurations found</p></div>
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
                      <div className="text-[1.5rem] leading-none shrink-0">
                        {CONFIG_ICONS[schema.icon || ''] || CONFIG_ICONS[schema.name] || '⚙️'}
                      </div>
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
        <div className="modal-overlay" onClick={() => setEditing(null)}>
          <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-[600px] max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">Edit: {editing.schema.display_name || editing.schema.name}</h3>
              <button className="btn-close" onClick={() => setEditing(null)}>×</button>
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
                  };
                  return Object.entries(groups).map(([groupName, fields]) => (
                    <div key={groupName} className="border border-[var(--border-color)] rounded-[var(--border-radius)] overflow-hidden">
                      <h4 className="text-[0.8125rem] font-semibold text-[var(--text-secondary)] py-3 px-4 bg-[var(--bg-tertiary)] m-0 border-b border-[var(--border-color)]">
                        {groupLabels[groupName] || groupName}
                      </h4>
                      <div className="p-4 flex flex-col gap-4">
                        {fields.map(field => {
                          const value = editing.values[field.name] ?? field.default ?? '';
                          return <ConfigFieldInput key={field.name} field={field} value={value} />;
                        })}
                      </div>
                    </div>
                  ));
                })()}
              </form>
            </div>
            <div className="modal-footer">
              <button className="btn btn-sm text-[var(--danger-color)]" onClick={resetConfig}>Reset to Defaults</button>
              <div className="flex gap-2">
                <button className="btn btn-sm" onClick={() => setEditing(null)}>Cancel</button>
                <button className="btn btn-primary btn-sm" onClick={saveConfig}>Save</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Import Modal */}
      {importOpen && (
        <div className="modal-overlay" onClick={() => setImportOpen(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3 className="modal-title">Import Configuration</h3>
              <button className="btn-close" onClick={() => setImportOpen(false)}>×</button>
            </div>
            <div className="modal-body">
              <textarea
                className="w-full p-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] font-mono text-[var(--text-primary)] resize-none focus:outline-none focus:border-[var(--primary-color)]"
                rows={10} placeholder="Paste configuration JSON here..."
                value={importData} onChange={e => setImportData(e.target.value)}
              />
            </div>
            <div className="modal-footer">
              <button className="btn btn-sm" onClick={() => setImportOpen(false)}>Cancel</button>
              <button className="btn btn-primary btn-sm" onClick={importConfigs}>Import</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ConfigFieldInput({ field, value }: { field: ConfigField; value: any }) {
  const [showPass, setShowPass] = useState(false);
  const id = `cf-${field.name}`;
  const effectiveType = field.type === 'password' ? 'string' : field.type;

  const labelEl = (
    <div className="flex items-center gap-1.5 mb-2">
      <label htmlFor={id} className="text-[0.8125rem] font-medium text-[var(--text-primary)]">{field.label}</label>
      {field.required && <span className="text-[var(--danger-color)]">*</span>}
      {field.description && (
        <span className="text-[var(--text-muted)] cursor-help hover:text-[var(--text-secondary)] transition-colors" title={field.description}>ⓘ</span>
      )}
    </div>
  );

  const inputClasses = "w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)]";

  if (effectiveType === 'boolean') {
    return (
      <div className="flex items-center justify-between gap-3 py-1">
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          <label htmlFor={id} className="text-[0.8125rem] font-medium text-[var(--text-primary)]">{field.label}</label>
          {field.description && (
            <span className="text-[var(--text-muted)] cursor-help hover:text-[var(--text-secondary)] transition-colors" title={field.description}>ⓘ</span>
          )}
        </div>
        <input type="checkbox" id={id} name={field.name} defaultChecked={!!value} className="rounded" />
      </div>
    );
  }

  if (effectiveType === 'select') {
    return (
      <div>
        {labelEl}
        <select id={id} name={field.name} defaultValue={value} className={inputClasses}>
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
        <textarea id={id} name={field.name} defaultValue={textValue}
                  rows={3} placeholder={field.placeholder || ''} className={inputClasses + ' resize-none font-mono'} />
      </div>
    );
  }

  if (effectiveType === 'number') {
    return (
      <div>
        {labelEl}
        <input type="number" id={id} name={field.name} defaultValue={value}
               placeholder={field.placeholder || ''} min={field.min} max={field.max} className={inputClasses} />
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
        <input type={inputType} id={id} name={field.name} defaultValue={value || ''}
               placeholder={field.placeholder || ''} className={inputClasses + (field.secure ? ' pr-10' : '')} />
        {field.secure && (
          <button type="button" className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                  onClick={() => setShowPass(!showPass)}>
            {showPass ? '🙈' : '👁️'}
          </button>
        )}
      </div>
    </div>
  );
}
