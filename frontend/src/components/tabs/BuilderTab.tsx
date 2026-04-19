'use client';

/**
 * BuilderTab — per-stage editor for one EnvironmentManifest.
 *
 * Phase 6d-2 scope: load the env picked via `useEnvironmentStore.openInBuilder`,
 * render the manifest stages on the left, let users swap the artifact, toggle
 * active, and edit the raw config JSON on the right. Schema-driven form
 * generation lands in a follow-up PR — the textarea is the simple
 * interim surface.
 */

import { useEffect, useMemo, useState } from 'react';
import { Boxes, ChevronRight, Eye, EyeOff, RotateCcw, Save, X } from 'lucide-react';

import { catalogApi } from '@/lib/environmentApi';
import { useAppStore } from '@/store/useAppStore';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { useI18n } from '@/lib/i18n';
import JsonSchemaForm, {
  type JsonSchema,
} from '@/components/environment/JsonSchemaForm';
import type {
  ArtifactInfo,
  StageIntrospection,
  StageManifestEntry,
} from '@/types/environment';

interface StageDraft {
  artifact: string;
  active: boolean;
  configText: string;
}

function stageDraftFromEntry(entry: StageManifestEntry): StageDraft {
  return {
    artifact: entry.artifact,
    active: entry.active,
    configText: JSON.stringify(entry.config ?? {}, null, 2),
  };
}

function tryParseJson(
  text: string,
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const trimmed = text.trim();
  if (!trimmed) return { ok: true, value: {} };
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { ok: false, error: 'Config must be a JSON object' };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : 'Invalid JSON' };
  }
}

export default function BuilderTab() {
  const {
    builderEnvId,
    selectedEnvironment,
    loadEnvironment,
    updateStage,
    closeBuilder,
    clearSelection,
  } = useEnvironmentStore();
  const setActiveTab = useAppStore(s => s.setActiveTab);
  const { t } = useI18n();

  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [selectedOrder, setSelectedOrder] = useState<number | null>(null);
  const [draft, setDraft] = useState<StageDraft | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [savedFlash, setSavedFlash] = useState(false);
  const [artifactsByOrder, setArtifactsByOrder] = useState<
    Record<number, ArtifactInfo[] | 'loading' | 'error'>
  >({});
  const [schemaByKey, setSchemaByKey] = useState<
    Record<string, StageIntrospection | 'loading' | 'error'>
  >({});
  const [showPreview, setShowPreview] = useState(true);
  const [configMode, setConfigMode] = useState<'form' | 'json'>('form');

  // Load env whenever builderEnvId changes
  useEffect(() => {
    setSelectedOrder(null);
    if (!builderEnvId) return;
    setLoading(true);
    setLoadError('');
    loadEnvironment(builderEnvId)
      .catch((e: unknown) => {
        setLoadError(e instanceof Error ? e.message : t('builderTab.loadFailed'));
      })
      .finally(() => setLoading(false));
    return () => {
      clearSelection();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [builderEnvId]);

  const env = selectedEnvironment && selectedEnvironment.id === builderEnvId
    ? selectedEnvironment
    : null;
  const stages: StageManifestEntry[] = useMemo(() => {
    const list = env?.manifest?.stages ?? [];
    return [...list].sort((a, b) => a.order - b.order);
  }, [env]);

  // Auto-select first stage once manifest is present
  useEffect(() => {
    if (selectedOrder === null && stages.length > 0) {
      setSelectedOrder(stages[0].order);
    }
  }, [stages, selectedOrder]);

  const selectedStage = useMemo(
    () => stages.find(s => s.order === selectedOrder) ?? null,
    [stages, selectedOrder],
  );

  // Refresh draft when the selected stage changes
  useEffect(() => {
    if (selectedStage) {
      setDraft(stageDraftFromEntry(selectedStage));
      setSaveError('');
      setSavedFlash(false);
    } else {
      setDraft(null);
    }
  }, [selectedStage]);

  // Load artifact list for the currently selected order lazily
  useEffect(() => {
    if (selectedOrder === null) return;
    if (artifactsByOrder[selectedOrder]) return;
    setArtifactsByOrder(prev => ({ ...prev, [selectedOrder]: 'loading' }));
    catalogApi
      .listArtifacts(selectedOrder)
      .then(res => {
        setArtifactsByOrder(prev => ({ ...prev, [selectedOrder]: res.artifacts }));
      })
      .catch(() => {
        setArtifactsByOrder(prev => ({ ...prev, [selectedOrder]: 'error' }));
      });
  }, [selectedOrder, artifactsByOrder]);

  const artifactsForSelected = selectedOrder !== null ? artifactsByOrder[selectedOrder] : undefined;
  const configParse = draft ? tryParseJson(draft.configText) : null;
  const configInvalid = configParse && !configParse.ok;

  // Fetch schema for the currently drafted (order, artifact) combo lazily
  const schemaKey = selectedOrder !== null && draft ? `${selectedOrder}:${draft.artifact}` : null;
  useEffect(() => {
    if (!schemaKey || selectedOrder === null || !draft) return;
    if (schemaByKey[schemaKey]) return;
    setSchemaByKey(prev => ({ ...prev, [schemaKey]: 'loading' }));
    catalogApi
      .artifactByStage(selectedOrder, draft.artifact)
      .then(res => {
        setSchemaByKey(prev => ({ ...prev, [schemaKey]: res }));
      })
      .catch(() => {
        setSchemaByKey(prev => ({ ...prev, [schemaKey]: 'error' }));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schemaKey]);

  const activeIntrospection = schemaKey ? schemaByKey[schemaKey] : undefined;
  const configSchema: JsonSchema | null =
    activeIntrospection && typeof activeIntrospection === 'object' && activeIntrospection !== null
      ? ((activeIntrospection as StageIntrospection).config_schema as JsonSchema | null) ?? null
      : null;
  const schemaAvailable = !!configSchema && typeof configSchema === 'object';
  const effectiveConfigMode: 'form' | 'json' = schemaAvailable ? configMode : 'json';

  const isDirty = useMemo(() => {
    if (!selectedStage || !draft) return false;
    if (draft.artifact !== selectedStage.artifact) return true;
    if (draft.active !== selectedStage.active) return true;
    const original = JSON.stringify(selectedStage.config ?? {}, null, 2);
    return draft.configText.trim() !== original.trim();
  }, [draft, selectedStage]);

  const handleRevert = () => {
    if (selectedStage) setDraft(stageDraftFromEntry(selectedStage));
    setSaveError('');
    setSavedFlash(false);
  };

  const handleSave = async () => {
    if (!builderEnvId || !selectedStage || !draft) return;
    if (configInvalid) {
      setSaveError(t('builderTab.configInvalid'));
      return;
    }
    const parsed = configParse && configParse.ok ? configParse.value : {};
    setSaving(true);
    setSaveError('');
    setSavedFlash(false);
    try {
      await updateStage(builderEnvId, selectedStage.order, {
        artifact: draft.artifact,
        active: draft.active,
        config: parsed,
      });
      setSavedFlash(true);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : t('builderTab.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  // ─── Empty (no env picked) ───
  if (!builderEnvId) {
    return (
      <div className="flex-1 min-h-0 overflow-auto bg-[var(--bg-primary)]">
        <div className="max-w-[1200px] mx-auto p-6 flex flex-col gap-6">
          <header className="flex flex-col gap-1">
            <h2 className="text-[1.25rem] font-semibold text-[var(--text-primary)]">
              {t('builderTab.title')}
            </h2>
            <p className="text-[0.8125rem] text-[var(--text-muted)] max-w-[720px]">
              {t('builderTab.subtitle')}
            </p>
          </header>
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
            <Boxes size={32} className="text-[var(--text-muted)] opacity-60" />
            <p className="text-[0.875rem] text-[var(--text-secondary)]">
              {t('builderTab.emptyTitle')}
            </p>
            <p className="text-[0.75rem] text-[var(--text-muted)] max-w-[420px]">
              {t('builderTab.emptyHint')}
            </p>
            <button
              onClick={() => setActiveTab('environments')}
              className="mt-3 flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-semibold cursor-pointer border-none transition-colors"
            >
              {t('builderTab.openEnvironments')}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 overflow-hidden flex flex-col bg-[var(--bg-primary)]">
      {/* Header */}
      <header className="shrink-0 flex items-start justify-between gap-3 px-6 py-3 border-b border-[var(--border-color)]">
        <div className="flex flex-col gap-0.5 min-w-0">
          <h2 className="text-[1rem] font-semibold text-[var(--text-primary)] truncate">
            {env?.name ?? t('builderTab.loading')}
          </h2>
          <span className="text-[0.6875rem] font-mono text-[var(--text-muted)] truncate">
            {builderEnvId}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setShowPreview(p => !p)}
            className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
          >
            {showPreview ? <EyeOff size={12} /> : <Eye size={12} />}
            {showPreview ? t('builderTab.hidePreview') : t('builderTab.showPreview')}
          </button>
          <button
            onClick={() => {
              closeBuilder();
              setActiveTab('environments');
            }}
            className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-transparent border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
          >
            <X size={12} />
            {t('builderTab.closeLabel')}
          </button>
        </div>
      </header>

      {/* Body */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {/* Stage list */}
        <aside className="w-[260px] shrink-0 border-r border-[var(--border-color)] bg-[var(--bg-secondary)] flex flex-col">
          <div className="px-4 py-2.5 border-b border-[var(--border-color)] text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
            {t('builderTab.stages')}
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto">
            {loading && stages.length === 0 ? (
              <div className="p-4 text-[0.75rem] text-[var(--text-muted)]">
                {t('builderTab.loading')}
              </div>
            ) : loadError ? (
              <div className="m-3 p-2.5 rounded-md bg-[rgba(239,68,68,0.1)] border border-[rgba(239,68,68,0.3)] text-[0.75rem] text-[var(--danger-color)]">
                {loadError}
              </div>
            ) : stages.length === 0 ? (
              <div className="p-4 text-[0.75rem] text-[var(--text-muted)]">
                {t('builderTab.stagesEmpty')}
              </div>
            ) : (
              <ul className="flex flex-col">
                {stages.map(stage => {
                  const isActive = selectedOrder === stage.order;
                  return (
                    <li key={stage.order}>
                      <button
                        onClick={() => setSelectedOrder(stage.order)}
                        className={`w-full text-left px-4 py-2.5 border-b border-[var(--border-color)] flex items-center gap-2 cursor-pointer transition-colors ${
                          isActive
                            ? 'bg-[var(--bg-tertiary)] border-l-2 border-l-[var(--primary-color)]'
                            : 'bg-transparent hover:bg-[var(--bg-tertiary)]'
                        }`}
                      >
                        <span className="text-[0.6875rem] font-mono text-[var(--text-muted)] w-6 shrink-0">
                          {String(stage.order).padStart(2, '0')}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[0.8125rem] font-medium text-[var(--text-primary)] truncate">
                              {stage.name}
                            </span>
                            {!stage.active && (
                              <span className="text-[0.625rem] text-[var(--text-muted)] italic shrink-0">
                                {t('builderTab.stageInactive')}
                              </span>
                            )}
                          </div>
                          <div className="text-[0.6875rem] text-[var(--text-muted)] font-mono truncate">
                            {stage.artifact}
                          </div>
                        </div>
                        <ChevronRight size={12} className="text-[var(--text-muted)] opacity-60" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </aside>

        {/* Editor */}
        <main className="flex-1 min-w-0 flex overflow-hidden">
          <section className="flex-1 min-w-0 overflow-y-auto p-5 flex flex-col gap-5">
            {!selectedStage || !draft ? (
              <div className="text-[0.8125rem] text-[var(--text-muted)]">
                {t('builderTab.editorEmpty')}
              </div>
            ) : (
              <>
                {/* Stage heading */}
                <div className="flex flex-col gap-1">
                  <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">
                    {String(selectedStage.order).padStart(2, '0')} · {selectedStage.name}
                  </h3>
                  <p className="text-[0.6875rem] font-mono text-[var(--text-muted)]">
                    {selectedStage.name}
                  </p>
                </div>

                {/* Artifact picker */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                    {t('builderTab.artifact')}
                  </label>
                  {artifactsForSelected === 'loading' ? (
                    <div className="text-[0.75rem] text-[var(--text-muted)] italic">
                      {t('builderTab.artifactsLoading')}
                    </div>
                  ) : artifactsForSelected === 'error' ? (
                    <div className="text-[0.75rem] text-[var(--danger-color)]">
                      {t('builderTab.artifactsFailed')}
                    </div>
                  ) : (
                    <select
                      value={draft.artifact}
                      onChange={e => setDraft({ ...draft, artifact: e.target.value })}
                      className="py-1.5 px-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.8125rem] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] cursor-pointer"
                    >
                      {(Array.isArray(artifactsForSelected)
                        ? artifactsForSelected
                        : []
                      ).map(a => (
                        <option key={a.name} value={a.name}>
                          {a.name}
                          {a.is_default ? ' (default)' : ''}
                          {a.description ? ` — ${a.description}` : ''}
                        </option>
                      ))}
                      {/* Fallback: ensure current artifact is selectable even if backend omits it */}
                      {Array.isArray(artifactsForSelected) &&
                        !artifactsForSelected.some(a => a.name === draft.artifact) && (
                          <option value={draft.artifact}>{draft.artifact}</option>
                        )}
                    </select>
                  )}
                  <small className="text-[0.6875rem] text-[var(--text-muted)]">
                    {t('builderTab.artifactHint')}
                  </small>
                </div>

                {/* Active toggle */}
                <div className="flex flex-col gap-1.5">
                  <label className="inline-flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={draft.active}
                      onChange={e => setDraft({ ...draft, active: e.target.checked })}
                      className="w-3.5 h-3.5 cursor-pointer"
                    />
                    <span className="text-[0.8125rem] font-medium text-[var(--text-primary)]">
                      {t('builderTab.active')}
                    </span>
                  </label>
                  <small className="text-[0.6875rem] text-[var(--text-muted)]">
                    {t('builderTab.activeHint')}
                  </small>
                </div>

                {/* Config editor — form or JSON */}
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                      {t('builderTab.config')}
                    </label>
                    {schemaAvailable ? (
                      <div className="inline-flex rounded-md border border-[var(--border-color)] bg-[var(--bg-secondary)] p-0.5">
                        <button
                          onClick={() => setConfigMode('form')}
                          className={`px-2 py-0.5 rounded text-[0.6875rem] font-medium cursor-pointer transition-colors ${
                            effectiveConfigMode === 'form'
                              ? 'bg-[var(--primary-color)] text-white'
                              : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                          }`}
                        >
                          {t('builderTab.configForm')}
                        </button>
                        <button
                          onClick={() => setConfigMode('json')}
                          className={`px-2 py-0.5 rounded text-[0.6875rem] font-medium cursor-pointer transition-colors ${
                            effectiveConfigMode === 'json'
                              ? 'bg-[var(--primary-color)] text-white'
                              : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                          }`}
                        >
                          {t('builderTab.configJson')}
                        </button>
                      </div>
                    ) : activeIntrospection === 'loading' ? (
                      <span className="text-[0.625rem] text-[var(--text-muted)] italic">
                        {t('builderTab.schemaLoading')}
                      </span>
                    ) : activeIntrospection === 'error' ? (
                      <span className="text-[0.625rem] text-[var(--danger-color)]">
                        {t('builderTab.schemaFailed')}
                      </span>
                    ) : (
                      <span className="text-[0.625rem] text-[var(--text-muted)] italic">
                        {t('builderTab.schemaNone')}
                      </span>
                    )}
                  </div>

                  {effectiveConfigMode === 'form' && configSchema && configParse?.ok ? (
                    <div className="p-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)]">
                      <JsonSchemaForm
                        schema={configSchema}
                        value={configParse.value}
                        onChange={next => {
                          setDraft({
                            ...draft,
                            configText: JSON.stringify(next, null, 2),
                          });
                        }}
                      />
                    </div>
                  ) : (
                    <textarea
                      value={draft.configText}
                      onChange={e => setDraft({ ...draft, configText: e.target.value })}
                      rows={14}
                      spellCheck={false}
                      className={`py-2 px-3 rounded-md bg-[var(--bg-primary)] border font-mono text-[0.75rem] leading-[1.5] text-[var(--text-primary)] focus:outline-none focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] resize-y ${
                        configInvalid
                          ? 'border-[var(--danger-color)] focus:border-[var(--danger-color)]'
                          : 'border-[var(--border-color)] focus:border-[var(--primary-color)]'
                      }`}
                    />
                  )}

                  {configInvalid ? (
                    <small className="text-[0.6875rem] text-[var(--danger-color)]">
                      {t('builderTab.configInvalid')} ({configParse!.error})
                    </small>
                  ) : (
                    <small className="text-[0.6875rem] text-[var(--text-muted)]">
                      {schemaAvailable && effectiveConfigMode === 'form'
                        ? t('builderTab.configFormHint')
                        : t('builderTab.configHint')}
                    </small>
                  )}
                </div>

                {/* Strategies / chains (read-only for now) */}
                {Object.keys(selectedStage.strategies || {}).length > 0 && (
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                      {t('builderTab.strategies')}
                    </label>
                    <pre className="p-2.5 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.6875rem] leading-[1.5] font-mono text-[var(--text-secondary)] whitespace-pre-wrap">
                      {JSON.stringify(selectedStage.strategies, null, 2)}
                    </pre>
                  </div>
                )}
                {Object.keys(selectedStage.chain_order || {}).length > 0 && (
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                      {t('builderTab.chains')}
                    </label>
                    <pre className="p-2.5 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.6875rem] leading-[1.5] font-mono text-[var(--text-secondary)] whitespace-pre-wrap">
                      {JSON.stringify(selectedStage.chain_order, null, 2)}
                    </pre>
                  </div>
                )}

                {/* Error / saved flash */}
                {saveError && (
                  <div className="px-3 py-2 rounded-md bg-[rgba(239,68,68,0.1)] border border-[rgba(239,68,68,0.3)] text-[0.75rem] text-[var(--danger-color)]">
                    {saveError}
                  </div>
                )}
                {savedFlash && !saveError && (
                  <div className="px-3 py-2 rounded-md bg-[rgba(34,197,94,0.1)] border border-[rgba(34,197,94,0.3)] text-[0.75rem] text-[var(--success-color)]">
                    {t('builderTab.saved')}
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center justify-end gap-2 pt-2">
                  <button
                    onClick={handleRevert}
                    disabled={!isDirty || saving}
                    className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-transparent border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <RotateCcw size={12} />
                    {t('builderTab.revert')}
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={!isDirty || saving || !!configInvalid}
                    className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-semibold cursor-pointer border-none transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Save size={12} />
                    {saving ? t('builderTab.saving') : t('builderTab.save')}
                  </button>
                </div>
              </>
            )}
          </section>

          {/* Manifest preview panel */}
          {showPreview && (
            <aside className="hidden md:flex w-[360px] shrink-0 border-l border-[var(--border-color)] bg-[var(--bg-secondary)] flex-col">
              <div className="px-4 py-2.5 border-b border-[var(--border-color)] text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                {t('builderTab.manifestPreview')}
              </div>
              <pre className="flex-1 min-h-0 overflow-auto p-3 text-[0.6875rem] leading-[1.5] font-mono text-[var(--text-secondary)] whitespace-pre">
                {env?.manifest ? JSON.stringify(env.manifest, null, 2) : ''}
              </pre>
            </aside>
          )}
        </main>
      </div>
    </div>
  );
}
