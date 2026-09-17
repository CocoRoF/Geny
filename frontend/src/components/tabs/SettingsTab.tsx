'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { configApi, gaptApi, avatarApi } from '@/lib/api';
import ModelAccountsPanel from './ModelAccountsPanel';
import { llmAccountsApi } from '@/lib/llmAccountsApi';
import GaptSettingsPanel from './GaptSettingsPanel';
import GoogleSettingsPanel from './GoogleSettingsPanel';
import ConnectorsPanel from './ConnectorsPanel';
import AvatarSettingsPanel from './AvatarSettingsPanel';
import { SettingsCard, type CardStatusTone } from '@/components/settings/SettingsCard';
import SshServersEditor from '@/components/settings/SshServersEditor';
import { PROVIDERS } from '@/lib/modelCatalog';
import { useLLMBackendsHealthStore } from '@/store/useLLMBackendsHealthStore';
import { twMerge } from 'tailwind-merge';
import { Eye, EyeOff, AlertTriangle, X, BookOpen } from 'lucide-react';
import MarkdownRenderer from '@/components/file-viewer/MarkdownRenderer';
import NumberStepper from '@/components/ui/NumberStepper';
import InfoTooltip from '@/components/ui/InfoTooltip';
import Selector from '@/components/ui/Selector';
import { TabShell, IconButton } from '@/components/common/layout';
import { Settings as SettingsIcon, Download, Upload, RefreshCw, Boxes } from 'lucide-react';
import { useI18n, type Locale } from '@/lib/i18n';
import type { ConfigItem, ConfigCategory, ConfigField, ConfigSchema, ConfigI18nLocale } from '@/types';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

/** Resolve localized config-level metadata from schema i18n data */
export function getLocalizedSchema(schema: ConfigSchema, locale: Locale) {
  const loc: ConfigI18nLocale | undefined = locale !== 'en' ? schema.i18n?.[locale] : undefined;
  return {
    display_name: loc?.display_name || schema.display_name || schema.name,
    description: loc?.description || schema.description || '',
  };
}

/** Resolve localized field metadata from schema i18n data */
export function getLocalizedField(field: ConfigField, schema: ConfigSchema, locale: Locale) {
  const loc = locale !== 'en' ? schema.i18n?.[locale]?.fields?.[field.name] : undefined;
  return {
    label: loc?.label || field.label,
    description: loc?.description || field.description || '',
    placeholder: loc?.placeholder || field.placeholder || '',
  };
}

/** Resolve localized group name from schema i18n data */
export function getLocalizedGroup(groupName: string, schema: ConfigSchema, locale: Locale, fallbackGroups: Record<string, string>) {
  const loc = locale !== 'en' ? schema.i18n?.[locale]?.groups?.[groupName] : undefined;
  return loc || fallbackGroups[groupName] || groupName;
}

/** A field is visible unless its `visible_when` says otherwise: every
 *  {siblingField: [allowedValues]} entry must match the current form values
 *  (e.g. embedding fields shown only when memory_engine is "composite"). */
export function isFieldVisible(field: ConfigField, values: Record<string, unknown>): boolean {
  if (!field.visible_when) return true;
  return Object.entries(field.visible_when).every(([sibling, allowed]) =>
    allowed.includes(String(values[sibling] ?? ''))
  );
}

/** Read ``?settings_category=...`` once at mount so deep-links from
 *  the Environment editor (and any other page) can land directly on the
 *  intended sub-category — e.g. ``llm_backends`` to reach the LLM
 *  Backends panel without manual clicking. */
function readInitialCategory(): string {
  if (typeof window === 'undefined') return 'all';
  try {
    const params = new URLSearchParams(window.location.search);
    const v = params.get('settings_category');
    if (v && v.trim()) return v;
  } catch {
    /* ignore */
  }
  return 'all';
}

export default function SettingsTab() {
  const { t, tRaw, locale, setLocale } = useI18n();
  const [configs, setConfigs] = useState<ConfigItem[]>([]);
  const [categories, setCategories] = useState<ConfigCategory[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>(() => readInitialCategory());
  const [editing, setEditing] = useState<{ name: string; schema: ConfigSchema; values: Record<string, any> } | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importData, setImportData] = useState('');
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // LLM-backends count for the sidebar badge — derived, never hardcoded.
  // Source of truth = the live health snapshot (exactly what LLMBackendsPanel
  // renders as cards). Before that loads, fall back to the canonical provider
  // taxonomy (`modelCatalog.PROVIDERS`, which mirrors the executor
  // ClientRegistry) so the badge is correct on first paint and auto-updates
  // when a provider is added/removed — no manual sync.
  const llmHealthProviders = useLLMBackendsHealthStore((s) => s.providers);
  const llmHealthLoaded = useLLMBackendsHealthStore((s) => s.loaded);
  const fetchLlmHealth = useLLMBackendsHealthStore((s) => s.fetch);
  useEffect(() => {
    fetchLlmHealth();
  }, [fetchLlmHealth]);
  // The badge counts ACCOUNTS, not providers: "how many ways can this server
  // answer" is the question the Models section exists to answer, and a
  // provider with no account behind it answers nothing.
  const [accountCount, setAccountCount] = useState<number | null>(null);
  useEffect(() => {
    llmAccountsApi.list()
      .then((res) => setAccountCount(res.accounts.filter((a) => a.enabled).length))
      .catch(() => setAccountCount(null));
  }, []);
  const llmBackendCount = accountCount ?? (
    llmHealthLoaded && Object.keys(llmHealthProviders).length > 0
      ? Object.keys(llmHealthProviders).length
      : PROVIDERS.length
  );

  // GAPT connection — the "GAPT" settings category appears only when a GAPT
  // instance is wired up AND answering /health (same gate the header button uses).
  const [gaptRunning, setGaptRunning] = useState(false);
  const [avatarRunning, setAvatarRunning] = useState(false);
  useEffect(() => {
    let alive = true;
    gaptApi.status()
      .then((s) => { if (alive) setGaptRunning(!!s.running); })
      .catch(() => { if (alive) setGaptRunning(false); });
    avatarApi.status()
      .then((s) => { if (alive) setAvatarRunning(!!s.running); })
      .catch(() => { if (alive) setAvatarRunning(false); });
    return () => { alive = false; };
  }, []);

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
      setGuideOpen(false);
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
      if (res.success) {
        // Sync frontend locale when language config changes
        if (editing.name === 'language' && values.language) {
          const lang = values.language;
          if (lang === 'en' || lang === 'ko') setLocale(lang as Locale);
        }
        setMsg({ type: 'success', text: t('settings.configSaved') }); setEditing(null); loadConfigs();
      }
      else setMsg({ type: 'error', text: t('settings.saveFailed') });
    } catch (e: any) { setMsg({ type: 'error', text: e.message }); }
  };

  const resetConfig = async () => {
    if (!editing || !confirm(t('settings.resetConfirm', { name: getLocalizedSchema(editing.schema, locale).display_name }))) return;
    try {
      const res = await configApi.reset(editing.name);
      if (res.success) { setMsg({ type: 'success', text: t('settings.resetSuccess') }); setEditing(null); loadConfigs(); }
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
        setMsg({ type: 'success', text: t('settings.exported') });
      }
    } catch (e: any) { setMsg({ type: 'error', text: e.message }); }
  };

  const importConfigs = async () => {
    if (!importData.trim()) return;
    try {
      const parsed = JSON.parse(importData);
      const res = await configApi.importAll(parsed);
      if (res.success) { setMsg({ type: 'success', text: res.message || t('settings.imported') }); setImportOpen(false); setImportData(''); loadConfigs(); }
      else setMsg({ type: 'error', text: res.message || t('settings.importFailed') });
    } catch (e: any) { setMsg({ type: 'error', text: e.message || t('settings.invalidJson') }); }
  };

  return (
    <TabShell
      title={t('settings.title')}
      icon={SettingsIcon}
      actions={
        <>
          <IconButton icon={Download} title={t('common.export')} onClick={exportConfigs} />
          <IconButton icon={Upload} title={t('common.import')} onClick={() => setImportOpen(true)} />
          <IconButton icon={RefreshCw} title={t('common.refresh')} onClick={loadConfigs} />
        </>
      }
    >
      {/* Toast */}
      {msg && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-2 rounded-[var(--border-radius)] text-[0.875rem] text-white ${msg.type === 'success' ? 'bg-[var(--success-color)]' : 'bg-[var(--danger-color)]'}`}>
          {msg.text}
        </div>
      )}

      {/* Content — h-full (not flex-1) because TabShell.body is not a flex container.
           Inner sidebar + main pane each own their own scroll context so 12-section
           General never gets clipped, and short content (e.g. empty section list)
           still fills the viewport instead of collapsing to intrinsic height. */}
      <div className="flex flex-col md:flex-row h-full overflow-hidden">
        {/* Category Sidebar — horizontal scroll on mobile, vertical on desktop.
             min-h-0 lets the flex item shrink below content height so overflow-y-auto
             actually produces a scrollbar when categories overflow. */}
        <div className="md:w-[200px] md:h-full md:min-h-0 border-b md:border-b-0 md:border-r border-[var(--border-color)] bg-[var(--bg-secondary)] overflow-x-auto md:overflow-x-visible md:overflow-y-auto shrink-0">
          <div className="flex md:flex-col p-2 md:p-3 gap-1 md:gap-0">
            <button
              className={`whitespace-nowrap md:w-full flex items-center gap-2 md:gap-2.5 py-2 md:py-2.5 px-3 rounded-[var(--border-radius)] text-[0.8125rem] md:text-[0.875rem] font-medium text-left md:mb-1 transition-colors shrink-0 ${selectedCategory === 'all' ? 'bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'}`}
              onClick={() => setSelectedCategory('all')}
            >
              <span className="flex-1">{t('settings.all')}</span>
              <span className="text-[0.6875rem] md:text-[0.75rem] text-[var(--text-muted)] bg-[var(--bg-tertiary)] py-[2px] px-2 rounded-[10px]">{configs.length}</span>
            </button>
            {/* Models — every account this server can reach a model with.
                 The badge is the count of ENABLED accounts: the list on that
                 page is the default route, so the number is also "how many
                 hops a session has before it runs out". */}
            <button
              className={`whitespace-nowrap md:w-full flex items-center gap-2 md:gap-2.5 py-2 md:py-2.5 px-3 rounded-[var(--border-radius)] text-[0.8125rem] md:text-[0.875rem] font-medium text-left md:mb-1 transition-colors shrink-0 ${selectedCategory === 'llm_backends' ? 'bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'}`}
              onClick={() => setSelectedCategory('llm_backends')}
            >
              <span className="flex-1">{t('settings.models.navLabel')}</span>
              <span className="text-[0.6875rem] md:text-[0.75rem] text-[var(--text-muted)] bg-[var(--bg-tertiary)] py-[2px] px-2 rounded-[10px]">{llmBackendCount}</span>
            </button>
            {/* ── Geny's own settings (top) ── */}
            {categories.map(cat => {
              const count = configs.filter(c => c.schema?.category === cat.name).length;
              return (
                <button key={cat.name}
                  className={`whitespace-nowrap md:w-full flex items-center gap-2 md:gap-2.5 py-2 md:py-2.5 px-3 rounded-[var(--border-radius)] text-[0.8125rem] md:text-[0.875rem] font-medium text-left md:mb-1 transition-colors shrink-0 ${selectedCategory === cat.name ? 'bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'}`}
                  onClick={() => setSelectedCategory(cat.name)}
                >
                  <span className="flex-1">{cat.label}</span>
                  <span className="text-[0.6875rem] md:text-[0.75rem] text-[var(--text-muted)] bg-[var(--bg-tertiary)] py-[2px] px-2 rounded-[10px]">{count}</span>
                </button>
              );
            })}

            {/* ── External integrations (below the divider) — connect to
                 services outside Geny: GAPT / Google / MCP connectors / Avatar.
                 Visually separated from Geny's own settings above. ── */}
            <div className="shrink-0 md:mt-3 md:pt-3 md:border-t border-[var(--border-color)] mx-2 md:mx-1 self-center md:self-stretch border-l md:border-l-0 pl-2 md:pl-0">
              <span className="hidden md:block px-2 mb-1.5 text-[0.625rem] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                {t('settings.externalGroup')}
              </span>
            </div>
            {gaptRunning && (
              <button
                className={`whitespace-nowrap md:w-full flex items-center gap-2 md:gap-2.5 py-2 md:py-2.5 px-3 rounded-[var(--border-radius)] text-[0.8125rem] md:text-[0.875rem] font-medium text-left md:mb-1 transition-colors shrink-0 ${selectedCategory === 'gapt' ? 'bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'}`}
                onClick={() => setSelectedCategory('gapt')}
              >
                <span className="flex-1">GAPT</span>
                <span className="text-[0.6875rem] md:text-[0.75rem] text-[var(--text-muted)] bg-[var(--bg-tertiary)] py-[2px] px-2 rounded-[10px]">●</span>
              </button>
            )}
            <button
              className={`whitespace-nowrap md:w-full flex items-center gap-2 md:gap-2.5 py-2 md:py-2.5 px-3 rounded-[var(--border-radius)] text-[0.8125rem] md:text-[0.875rem] font-medium text-left md:mb-1 transition-colors shrink-0 ${selectedCategory === 'google' ? 'bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'}`}
              onClick={() => setSelectedCategory('google')}
            >
              <span className="flex-1">{t('googleSettings.navLabel')}</span>
              <span className="text-[0.6875rem] md:text-[0.75rem] text-[var(--text-muted)] bg-[var(--bg-tertiary)] py-[2px] px-2 rounded-[10px]">●</span>
            </button>
            <button
              className={`whitespace-nowrap md:w-full flex items-center gap-2 md:gap-2.5 py-2 md:py-2.5 px-3 rounded-[var(--border-radius)] text-[0.8125rem] md:text-[0.875rem] font-medium text-left md:mb-1 transition-colors shrink-0 ${selectedCategory === 'connectors' ? 'bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'}`}
              onClick={() => setSelectedCategory('connectors')}
            >
              <Boxes className="w-4 h-4 shrink-0" />
              <span className="flex-1">{t('connectors.navLabel')}</span>
              <span className="text-[0.6875rem] md:text-[0.75rem] text-[var(--text-muted)] bg-[var(--bg-tertiary)] py-[2px] px-2 rounded-[10px]">●</span>
            </button>
            {avatarRunning && (
              <button
                className={`whitespace-nowrap md:w-full flex items-center gap-2 md:gap-2.5 py-2 md:py-2.5 px-3 rounded-[var(--border-radius)] text-[0.8125rem] md:text-[0.875rem] font-medium text-left md:mb-1 transition-colors shrink-0 ${selectedCategory === 'avatar' ? 'bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'}`}
                onClick={() => setSelectedCategory('avatar')}
              >
                <span className="flex-1">Avatar</span>
                <span className="text-[0.6875rem] md:text-[0.75rem] text-[var(--text-muted)] bg-[var(--bg-tertiary)] py-[2px] px-2 rounded-[10px]">●</span>
              </button>
            )}
          </div>
        </div>

        {/* Config List — h-full + min-h-0 so content fills the row, and overflow-y-auto
             gives this pane its own scroll context independent from the sidebar. */}
        <div className="flex-1 h-full min-h-0 overflow-y-auto p-3 md:p-5">
          {selectedCategory === 'llm_backends' ? (
            <ModelAccountsPanel />
          ) : selectedCategory === 'gapt' ? (
            <GaptSettingsPanel />
          ) : selectedCategory === 'google' ? (
            <GoogleSettingsPanel />
          ) : selectedCategory === 'connectors' ? (
            <ConnectorsPanel />
          ) : selectedCategory === 'avatar' ? (
            <AvatarSettingsPanel />
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4"><p className="text-[0.8125rem] text-[var(--text-muted)]">{t('settings.noConfigs')}</p></div>
          ) : (
            <div className="flex flex-col gap-3">
              {filtered.map(config => {
                const schema = config.schema || {} as ConfigSchema;
                const values = config.values || {};
                const fields = schema.fields || [];
                const hasEnabledField = fields.some((f: ConfigField) => f.name === 'enabled');
                const total = fields.length;
                // A field's value can be: explicit (set to a non-default value),
                // default (no value but a default applies, or value == default), or
                // unset (no value and no default). A default is a *valid* state —
                // it must read as "default", never "not configured".
                const hasVal = (f: ConfigField) => {
                  const v = values[f.name];
                  return v !== undefined && v !== null && v !== '';
                };
                const hasDefault = (f: ConfigField) =>
                  f.default !== undefined && f.default !== null && f.default !== '';
                const isExplicit = (f: ConfigField) => hasVal(f) && values[f.name] !== f.default;
                const isEffective = (f: ConfigField) => hasVal(f) || hasDefault(f);
                const explicitCount = fields.filter(isExplicit).length;
                // Count fields that have an effective value (explicit OR default) —
                // so a default-valued field reads as set, not "0/1".
                const configured = fields.filter(isEffective).length;
                const ls = getLocalizedSchema(schema, locale);

                // Three card states for plain configs: configured (any explicit
                // value) / default (only defaults apply) / unset (nothing).
                const plainStatus = explicitCount > 0
                  ? 'configured'
                  : (configured > 0 ? 'default' : 'unset');
                const isActive = hasEnabledField
                  ? values.enabled === true
                  : plainStatus !== 'unset'; // default counts as "set" (full opacity)
                const badgeLabel = hasEnabledField
                  ? (values.enabled === true ? t('common.enabled') : t('common.disabled'))
                  : plainStatus === 'configured'
                    ? t('common.configured')
                    : plainStatus === 'default'
                      ? t('common.usingDefaults')
                      : t('common.notConfigured');
                // Restrained status dot: active/explicit → good, otherwise neutral.
                const tone: CardStatusTone = isActive ? 'good' : 'neutral';

                return (
                  <SettingsCard
                    key={schema.name}
                    title={ls.display_name}
                    status={{ tone, label: badgeLabel }}
                    onClick={() => openEdit(schema.name)}
                    footer={
                      <>
                        <span className="text-[0.72rem] text-[var(--text-tertiary)]">
                          {t('settings.fieldsConfigured', { count: configured, total })}
                        </span>
                        {!config.valid && (
                          <span className="text-[0.72rem] text-[var(--warning-color)] inline-flex items-center gap-1">
                            <AlertTriangle size={12} /> {t('settings.issues', { count: config.errors?.length || 0 })}
                          </span>
                        )}
                      </>
                    }
                  >
                    <span className="line-clamp-2">{ls.description}</span>
                  </SettingsCard>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Edit Modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setEditing(null)}>
          <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[600px] mx-4 max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center py-4 px-6 border-b border-[var(--border-color)]">
              <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">{t('settings.editPrefix')}{getLocalizedSchema(editing.schema, locale).display_name}</h3>
              <div className="flex items-center gap-2">
                {editing.schema.setup_guide && (
                  <button
                    type="button"
                    onClick={() => setGuideOpen(true)}
                    className="inline-flex items-center gap-1.5 py-1.5 px-3 rounded-[var(--border-radius)] bg-transparent border border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] text-[0.75rem] font-medium cursor-pointer transition-all duration-150"
                  >
                    <BookOpen size={14} /> {t('settingsTab.setupGuide')}
                  </button>
                )}
                <button className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer" onClick={() => setEditing(null)}><X size={16} /></button>
              </div>
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
                  const groupLabels = tRaw<Record<string, string>>('settings.groupLabels');
                  return Object.entries(groups).map(([groupName, fields]) => {
                    // Conditional visibility: drop fields whose visible_when
                    // fails, and hide the whole group (header included) when
                    // nothing remains — e.g. Embedding/Chunking under Synapse.
                    const visibleFields = fields.filter(f => isFieldVisible(f, editing!.values));
                    if (visibleFields.length === 0) return null;
                    return (
                    <div key={groupName} className="border border-[var(--border-color)] rounded-[var(--border-radius)] overflow-hidden">
                      <h4 className="text-[0.8125rem] font-semibold text-[var(--text-secondary)] py-3 px-4 bg-[var(--bg-tertiary)] m-0 border-b border-[var(--border-color)]">
                        {getLocalizedGroup(groupName, editing.schema, locale, groupLabels)}
                      </h4>
                      <div className="p-4 flex flex-col gap-4">
                        {visibleFields.map(field => {
                          // SSH servers: bespoke list-of-servers editor — the
                          // generic auto-form has no list-of-dicts widget.
                          if (editing.name === 'ssh' && field.name === 'servers') {
                            return (
                              <SshServersEditor
                                key={field.name}
                                value={editing.values.servers as any}
                                onChange={v => updateField('servers', v)}
                              />
                            );
                          }
                          const value = editing.values[field.name] ?? field.default ?? '';
                          const lf = getLocalizedField(field, editing.schema, locale);
                          return <ConfigFieldInput key={field.name} field={field} value={value} onChange={v => updateField(field.name, v)} allValues={editing.values} allFields={editing.schema.fields} onChangeField={updateField} localizedLabel={lf.label} localizedDescription={lf.description} localizedPlaceholder={lf.placeholder} />;
                        })}
                      </div>
                    </div>
                    );
                  });
                })()}
              </form>
            </div>
            <div className="flex justify-end items-center gap-3 py-4 px-6 border-t border-[var(--border-color)]">
              <button className={cn("py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]", "!py-1.5 !px-3 text-[0.75rem]", '!text-[var(--danger-color)]')} onClick={resetConfig}>{t('settings.resetToDefaults')}</button>
              <div className="flex gap-2">
                <button className={cn("py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]", "!py-1.5 !px-3 text-[0.75rem]")} onClick={() => setEditing(null)}>{t('common.cancel')}</button>
                <button className={cn("py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed", "!py-1.5 !px-3 text-[0.75rem]")} onClick={saveConfig}>{t('common.save')}</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Setup guide modal (Markdown) — overlays the edit modal */}
      {editing && guideOpen && editing.schema.setup_guide && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-sm" onClick={() => setGuideOpen(false)}>
          <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[760px] mx-4 max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center py-4 px-6 border-b border-[var(--border-color)]">
              <h3 className="flex items-center gap-2 text-[1rem] font-semibold text-[var(--text-primary)]">
                <BookOpen size={16} /> {getLocalizedSchema(editing.schema, locale).display_name} · {t('settingsTab.setupGuide')}
              </h3>
              <button className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer" onClick={() => setGuideOpen(false)}><X size={16} /></button>
            </div>
            <div className="flex-1 overflow-y-auto">
              <MarkdownRenderer content={editing.schema.setup_guide[locale] || editing.schema.setup_guide.ko || editing.schema.setup_guide.en || Object.values(editing.schema.setup_guide)[0] || ''} />
            </div>
          </div>
        </div>
      )}

      {/* Import Modal */}
      {importOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setImportOpen(false)}>
          <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[520px] max-h-[85vh] flex flex-col shadow-[var(--shadow-lg)]" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center py-4 px-6 border-b border-[var(--border-color)]">
              <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">{t('settings.importTitle')}</h3>
              <button className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer" onClick={() => setImportOpen(false)}><X size={16} /></button>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-4">
              <textarea
                className="w-full p-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] font-mono text-[var(--text-primary)] resize-none focus:outline-none focus:border-[var(--primary-color)]"
                rows={10} placeholder={t('settings.importPlaceholder')}
                value={importData} onChange={e => setImportData(e.target.value)}
              />
            </div>
            <div className="flex justify-end items-center gap-3 py-4 px-6 border-t border-[var(--border-color)]">
              <button className={cn("py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]", "!py-1.5 !px-3 text-[0.75rem]")} onClick={() => setImportOpen(false)}>{t('common.cancel')}</button>
              <button className={cn("py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed", "!py-1.5 !px-3 text-[0.75rem]")} onClick={importConfigs}>{t('common.import')}</button>
            </div>
          </div>
        </div>
      )}
    </TabShell>
  );
}

export function ConfigFieldInput({ field, value, onChange, allValues, allFields, onChangeField, localizedLabel, localizedDescription, localizedPlaceholder }: { field: ConfigField; value: any; onChange: (v: any) => void; allValues?: Record<string, unknown>; allFields?: ConfigField[]; onChangeField?: (name: string, v: any) => void; localizedLabel?: string; localizedDescription?: string; localizedPlaceholder?: string }) {
  const { t } = useI18n();
  const [showPass, setShowPass] = useState(false);
  const id = `cf-${field.name}`;
  const effectiveType = field.type === 'password' ? 'string' : field.type;
  const label = localizedLabel || field.label;
  const description = localizedDescription || field.description;
  const placeholder = localizedPlaceholder || field.placeholder;

  const labelEl = (
    <div className="flex items-center gap-1.5 mb-2">
      <label htmlFor={id} className="text-[0.8125rem] font-medium text-[var(--text-primary)]">{label}</label>
      {field.required && <span className="text-[var(--danger-color)]">*</span>}
      {description && <InfoTooltip text={description} />}
    </div>
  );

  const inputClasses = "w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)]";

  if (effectiveType === 'boolean') {
    const checked = !!value;
    return (
      <div className="flex items-center justify-between gap-3 py-1">
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          <label className="text-[0.8125rem] font-medium text-[var(--text-primary)]">{label}</label>
          {description && <InfoTooltip text={description} />}
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
    // Filter options by depends_on parent value
    const rawOptions = field.options || [];
    const parentValue = field.depends_on && allValues ? String(allValues[field.depends_on] ?? '') : '';
    const filteredOptions = field.depends_on && parentValue
      ? rawOptions.filter(opt => opt.group === parentValue)
      : rawOptions;

    // Handle parent field change — cascade reset dependent children
    const handleParentChange = (newValue: string) => {
      onChange(newValue);
      // Find child fields that depend on this field and reset them
      if (allFields && onChangeField) {
        for (const f of allFields) {
          if (f.depends_on === field.name) {
            const childOptions = (f.options || []).filter(opt => opt.group === newValue);
            onChangeField(f.name, childOptions.length > 0 ? childOptions[0].value : '');
          }
        }
      }
    };

    return (
      <div>
        {labelEl}
        <Selector
          variant="field"
          ariaLabel={field.name}
          value={String(value ?? '')}
          onChange={handleParentChange}
          placeholder={t('common.selectOption')}
          items={[
            { id: '', label: t('common.selectOption') },
            ...filteredOptions.map((opt) => ({ id: String(opt.value), label: opt.label })),
          ]}
        />
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
                  rows={3} placeholder={placeholder} className={inputClasses + ' resize-none font-mono'} />
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
               placeholder={placeholder} className={inputClasses + (field.secure ? ' pr-10' : '')} />
        {field.secure && (
          <button type="button"
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 flex items-center justify-center w-7 h-7 rounded-[var(--border-radius)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-all duration-150 border-none bg-transparent cursor-pointer"
                  onClick={() => setShowPass(!showPass)}
                  aria-label={showPass ? t('settings.hide') : t('settings.show')}>
            {showPass ? <EyeOff size={16} strokeWidth={1.8} /> : <Eye size={16} strokeWidth={1.8} />}
          </button>
        )}
      </div>
    </div>
  );
}
