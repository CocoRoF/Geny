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
import { ArrowLeft, Boxes, ChevronRight, Eye, EyeOff, RotateCcw, Save, Settings2, Sliders, Wrench, X } from 'lucide-react';

import { catalogApi } from '@/lib/environmentApi';
import { externalToolCatalogApi } from '@/lib/api';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { useI18n } from '@/lib/i18n';
import JsonSchemaForm, {
  type JsonSchema,
} from '@/components/environment/JsonSchemaForm';
import {
  ChainsEditor,
  StrategiesEditor,
} from '@/components/environment/StrategyEditors';
import ToolsEditor, {
  emptyTools,
  toolsDraftFromSnapshot,
  toolsSnapshotsEqual,
  validateToolsDraft,
  type ToolsDraft,
} from '@/components/environment/ToolsEditor';
import PipelineConfigEditor from '@/components/builder/PipelineConfigEditor';
import ModelConfigEditor from '@/components/builder/ModelConfigEditor';
import type {
  ArtifactInfo,
  StageIntrospection,
  StageManifestEntry,
  ToolsSnapshot,
} from '@/types/environment';

interface StageDraft {
  artifact: string;
  active: boolean;
  configText: string;
  strategies: Record<string, string>;
  strategyConfigs: Record<string, Record<string, unknown>>;
  chainOrder: Record<string, string[]>;
  // S.1 (cycle 20260426_2) — per-stage ModelConfig override.
  // Stored as raw JSON text so an empty / null value cleanly maps to
  // "no override" and operators can paste any subset of ModelConfig
  // fields without the editor enforcing a particular shape.
  modelOverrideText: string;
  // S.2 (cycle 20260426_2) — per-stage StageToolBinding (s10).
  // Same rationale as modelOverrideText. Empty = inherit pipeline
  // tool roster.
  toolBindingText: string;
}

function stageDraftFromEntry(entry: StageManifestEntry): StageDraft {
  return {
    artifact: entry.artifact,
    active: entry.active,
    configText: JSON.stringify(entry.config ?? {}, null, 2),
    strategies: { ...(entry.strategies ?? {}) },
    strategyConfigs: Object.fromEntries(
      Object.entries(entry.strategy_configs ?? {}).map(([k, v]) => [
        k,
        { ...(v as Record<string, unknown>) },
      ]),
    ),
    chainOrder: Object.fromEntries(
      Object.entries(entry.chain_order ?? {}).map(([k, v]) => [k, [...v]]),
    ),
    modelOverrideText:
      entry.model_override == null
        ? ''
        : JSON.stringify(entry.model_override, null, 2),
    toolBindingText:
      entry.tool_binding == null
        ? ''
        : JSON.stringify(entry.tool_binding, null, 2),
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
    replaceManifest,
    updatePipeline,
    updateModel,
    closeBuilder,
    clearSelection,
  } = useEnvironmentStore();
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
  const [builderView, setBuilderView] = useState<'stages' | 'tools' | 'pipeline' | 'model'>('stages');
  const [toolsDraft, setToolsDraft] = useState<ToolsDraft | null>(null);
  const [toolsSaving, setToolsSaving] = useState(false);
  const [toolsError, setToolsError] = useState('');
  const [toolsSavedFlash, setToolsSavedFlash] = useState(false);
  // T.1 (cycle 20260426_2) — external tool catalog (Geny tool_loader names).
  // ``null`` = loading; ``[]`` = loaded but empty.
  const [externalCatalog, setExternalCatalog] = useState<
    Array<{ name: string; category: string; description: string }> | null
  >(null);
  // P.2 (cycle 20260426_2) — pipeline + model patch state.
  const [pipelineSaving, setPipelineSaving] = useState(false);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [modelSaving, setModelSaving] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);

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

  // T.1 (cycle 20260426_2) — load the external tool catalog once per
  // builder mount. Cached at module level by lib/api so subsequent
  // mounts hit memory.
  useEffect(() => {
    let cancelled = false;
    externalToolCatalogApi
      .list()
      .then((res) => {
        if (cancelled) return;
        setExternalCatalog(
          res.tools.map((t) => ({
            name: t.name,
            category: t.category,
            description: t.description,
          })),
        );
      })
      .catch(() => {
        // Empty array → editor renders the "no candidates" empty state,
        // which is reasonable when the catalog endpoint isn't reachable.
        if (!cancelled) setExternalCatalog([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
    if (draft.configText.trim() !== original.trim()) return true;
    // S.1 — model_override.
    const moOriginal =
      selectedStage.model_override == null
        ? ''
        : JSON.stringify(selectedStage.model_override, null, 2);
    if (draft.modelOverrideText.trim() !== moOriginal.trim()) return true;
    // S.2 — tool_binding.
    const tbOriginal =
      selectedStage.tool_binding == null
        ? ''
        : JSON.stringify(selectedStage.tool_binding, null, 2);
    if (draft.toolBindingText.trim() !== tbOriginal.trim()) return true;
    if (
      JSON.stringify(draft.strategies) !==
      JSON.stringify(selectedStage.strategies ?? {})
    )
      return true;
    if (
      JSON.stringify(draft.strategyConfigs) !==
      JSON.stringify(selectedStage.strategy_configs ?? {})
    )
      return true;
    if (
      JSON.stringify(draft.chainOrder) !==
      JSON.stringify(selectedStage.chain_order ?? {})
    )
      return true;
    return false;
  }, [draft, selectedStage]);

  const handleRevert = () => {
    if (selectedStage) setDraft(stageDraftFromEntry(selectedStage));
    setSaveError('');
    setSavedFlash(false);
  };

  const manifestTools: ToolsSnapshot = useMemo(
    () => env?.manifest?.tools ?? emptyTools(),
    [env],
  );

  // Sync tools draft when the underlying manifest changes
  useEffect(() => {
    if (env?.manifest) {
      setToolsDraft(toolsDraftFromSnapshot(env.manifest.tools));
      setToolsError('');
      setToolsSavedFlash(false);
    } else {
      setToolsDraft(null);
    }
  }, [env]);

  const toolsValidation = useMemo(
    () => (toolsDraft ? validateToolsDraft(toolsDraft) : null),
    [toolsDraft],
  );
  const toolsDirty = useMemo(() => {
    if (!toolsDraft || !toolsValidation || !toolsValidation.snapshot) return false;
    return !toolsSnapshotsEqual(toolsValidation.snapshot, manifestTools);
  }, [toolsDraft, toolsValidation, manifestTools]);

  const handleToolsRevert = () => {
    if (env?.manifest) {
      setToolsDraft(toolsDraftFromSnapshot(env.manifest.tools));
    }
    setToolsError('');
    setToolsSavedFlash(false);
  };

  const handleToolsSave = async () => {
    if (!builderEnvId || !env?.manifest || !toolsValidation || !toolsValidation.snapshot) return;
    setToolsSaving(true);
    setToolsError('');
    setToolsSavedFlash(false);
    try {
      await replaceManifest(builderEnvId, {
        ...env.manifest,
        tools: toolsValidation.snapshot,
      });
      setToolsSavedFlash(true);
    } catch (e: unknown) {
      setToolsError(e instanceof Error ? e.message : t('builderTab.toolsSaveFailed'));
    } finally {
      setToolsSaving(false);
    }
  };

  // P.2 (cycle 20260426_2) — pipeline + model save handlers.
  const handlePipelineSave = async (changes: Record<string, unknown>) => {
    if (!builderEnvId) return;
    setPipelineSaving(true);
    setPipelineError(null);
    try {
      await updatePipeline(builderEnvId, changes);
    } catch (e: unknown) {
      setPipelineError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setPipelineSaving(false);
    }
  };

  const handleModelSave = async (changes: Record<string, unknown>) => {
    if (!builderEnvId) return;
    setModelSaving(true);
    setModelError(null);
    try {
      await updateModel(builderEnvId, changes);
    } catch (e: unknown) {
      setModelError(e instanceof Error ? e.message : 'Save failed');
    } finally {
      setModelSaving(false);
    }
  };

  const pipelineInitial = useMemo<Record<string, unknown>>(
    () => (env?.manifest?.pipeline as Record<string, unknown> | undefined) ?? {},
    [env],
  );
  const modelInitial = useMemo<Record<string, unknown>>(
    () => (env?.manifest?.model as Record<string, unknown> | undefined) ?? {},
    [env],
  );

  const handleSave = async () => {
    if (!builderEnvId || !selectedStage || !draft) return;
    if (configInvalid) {
      setSaveError(t('builderTab.configInvalid'));
      return;
    }
    const parsed = configParse && configParse.ok ? configParse.value : {};

    // S.1 — model_override: empty text means "no override". A non-empty
    // value must be a JSON object.
    let modelOverride: Record<string, unknown> | null = null;
    const moTrim = draft.modelOverrideText.trim();
    if (moTrim) {
      try {
        const v = JSON.parse(moTrim);
        if (typeof v !== 'object' || v === null || Array.isArray(v)) {
          setSaveError('model_override must be a JSON object (or empty to clear)');
          return;
        }
        modelOverride = v as Record<string, unknown>;
      } catch (e) {
        setSaveError(
          'model_override: invalid JSON (' + (e instanceof Error ? e.message : 'parse error') + ')',
        );
        return;
      }
    }

    // S.2 — tool_binding: same shape contract.
    let toolBinding: Record<string, unknown> | null = null;
    const tbTrim = draft.toolBindingText.trim();
    if (tbTrim) {
      try {
        const v = JSON.parse(tbTrim);
        if (typeof v !== 'object' || v === null || Array.isArray(v)) {
          setSaveError('tool_binding must be a JSON object (or empty to inherit)');
          return;
        }
        toolBinding = v as Record<string, unknown>;
      } catch (e) {
        setSaveError(
          'tool_binding: invalid JSON (' + (e instanceof Error ? e.message : 'parse error') + ')',
        );
        return;
      }
    }

    setSaving(true);
    setSaveError('');
    setSavedFlash(false);
    try {
      await updateStage(builderEnvId, selectedStage.order, {
        artifact: draft.artifact,
        active: draft.active,
        config: parsed,
        strategies: draft.strategies,
        strategy_configs: draft.strategyConfigs,
        chain_order: draft.chainOrder,
        // ``modelOverride`` is null when the operator left the textarea
        // empty — backend treats null as "leave as-is" (None ignored).
        // To explicitly clear an existing override, the operator can
        // edit the manifest via ImportManifestModal — same convention
        // as the Pipeline / Model editors.
        ...(modelOverride !== null ? { model_override: modelOverride } : {}),
        ...(toolBinding !== null ? { tool_binding: toolBinding } : {}),
      });
      setSavedFlash(true);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : t('builderTab.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  // BuilderTab is only mounted when builderEnvId is non-null (the parent
  // EnvironmentsTab does the gating). The empty-state branch is therefore
  // dead code and has been removed; if a stale render slips through we
  // fall back to nothing so the parent can recover by re-rendering its
  // list view.
  if (!builderEnvId) {
    return null;
  }

  return (
    <div className="flex-1 min-h-0 overflow-hidden flex flex-col bg-[var(--bg-primary)]">
      {/* Header */}
      <header className="shrink-0 flex items-start justify-between gap-3 px-6 py-3 border-b border-[var(--border-color)]">
        <div className="flex flex-col gap-0.5 min-w-0">
          <button
            onClick={closeBuilder}
            className="flex items-center gap-1 text-[0.6875rem] font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)] bg-transparent border-none p-0 cursor-pointer self-start"
          >
            <ArrowLeft size={10} />
            {t('builderTab.backToEnvironments')}
          </button>
          <h2 className="text-[1rem] font-semibold text-[var(--text-primary)] truncate">
            {env?.name ?? t('builderTab.loading')}
          </h2>
          <span className="text-[0.6875rem] font-mono text-[var(--text-muted)] truncate">
            {builderEnvId}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="inline-flex rounded-md border border-[var(--border-color)] bg-[var(--bg-secondary)] p-0.5">
            <button
              onClick={() => setBuilderView('stages')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[0.75rem] font-medium cursor-pointer transition-colors ${
                builderView === 'stages'
                  ? 'bg-[var(--primary-color)] text-white'
                  : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              <Boxes size={12} />
              {t('builderTab.viewStages')}
            </button>
            <button
              onClick={() => setBuilderView('pipeline')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[0.75rem] font-medium cursor-pointer transition-colors ${
                builderView === 'pipeline'
                  ? 'bg-[var(--primary-color)] text-white'
                  : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              <Sliders size={12} />
              Pipeline
            </button>
            <button
              onClick={() => setBuilderView('model')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[0.75rem] font-medium cursor-pointer transition-colors ${
                builderView === 'model'
                  ? 'bg-[var(--primary-color)] text-white'
                  : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              <Settings2 size={12} />
              Model
            </button>
            <button
              onClick={() => setBuilderView('tools')}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[0.75rem] font-medium cursor-pointer transition-colors ${
                builderView === 'tools'
                  ? 'bg-[var(--primary-color)] text-white'
                  : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
              }`}
            >
              <Wrench size={12} />
              {t('builderTab.viewTools')}
            </button>
          </div>
          <button
            onClick={() => setShowPreview(p => !p)}
            className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
          >
            {showPreview ? <EyeOff size={12} /> : <Eye size={12} />}
            {showPreview ? t('builderTab.hidePreview') : t('builderTab.showPreview')}
          </button>
          <button
            onClick={closeBuilder}
            className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-transparent border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
          >
            <X size={12} />
            {t('builderTab.closeLabel')}
          </button>
        </div>
      </header>

      {/* Body */}
      <div className="flex-1 min-h-0 flex overflow-hidden">
        {builderView === 'pipeline' ? (
          <main className="flex-1 min-w-0 overflow-y-auto p-5">
            {loading && !env ? (
              <div className="text-[0.8125rem] text-[var(--text-muted)]">
                {t('builderTab.loading')}
              </div>
            ) : (
              <PipelineConfigEditor
                initial={pipelineInitial}
                saving={pipelineSaving}
                error={pipelineError}
                onSave={handlePipelineSave}
                onClearError={() => setPipelineError(null)}
              />
            )}
          </main>
        ) : builderView === 'model' ? (
          <main className="flex-1 min-w-0 overflow-y-auto p-5">
            {loading && !env ? (
              <div className="text-[0.8125rem] text-[var(--text-muted)]">
                {t('builderTab.loading')}
              </div>
            ) : (
              <ModelConfigEditor
                initial={modelInitial}
                saving={modelSaving}
                error={modelError}
                onSave={handleModelSave}
                onClearError={() => setModelError(null)}
              />
            )}
          </main>
        ) : builderView === 'tools' ? (
          <main className="flex-1 min-w-0 flex overflow-hidden">
            <section className="flex-1 min-w-0 overflow-y-auto p-5 flex flex-col gap-5">
              <div className="flex flex-col gap-1">
                <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">
                  {t('builderTab.toolsTitle')}
                </h3>
                <p className="text-[0.75rem] text-[var(--text-muted)] max-w-[680px]">
                  {t('builderTab.toolsSubtitle')}
                </p>
              </div>

              {loading && !env ? (
                <div className="text-[0.8125rem] text-[var(--text-muted)]">
                  {t('builderTab.loading')}
                </div>
              ) : loadError ? (
                <div className="px-3 py-2 rounded-md bg-[rgba(239,68,68,0.1)] border border-[rgba(239,68,68,0.3)] text-[0.75rem] text-[var(--danger-color)]">
                  {loadError}
                </div>
              ) : !toolsDraft ? (
                <div className="text-[0.8125rem] text-[var(--text-muted)]">
                  {t('builderTab.loading')}
                </div>
              ) : (
                <>
                  <ToolsEditor
                    draft={toolsDraft}
                    onChange={setToolsDraft}
                    externalCatalog={externalCatalog}
                    labels={{
                      allowlist: t('builderTab.allowlist'),
                      allowlistHint: t('builderTab.allowlistHint'),
                      blocklist: t('builderTab.blocklist'),
                      blocklistHint: t('builderTab.blocklistHint'),
                      adhocTools: t('builderTab.adhocTools'),
                      adhocToolsHint: t('builderTab.adhocToolsHint'),
                      mcpServers: t('builderTab.mcpServers'),
                      mcpServersHint: t('builderTab.mcpServersHint'),
                      patternsPlaceholder: t('builderTab.patternsPlaceholder'),
                      jsonArrayPlaceholder: t('builderTab.jsonArrayPlaceholder'),
                      entriesCount: t('builderTab.entriesCount'),
                    }}
                  />

                  {toolsError && (
                    <div className="px-3 py-2 rounded-md bg-[rgba(239,68,68,0.1)] border border-[rgba(239,68,68,0.3)] text-[0.75rem] text-[var(--danger-color)]">
                      {toolsError}
                    </div>
                  )}
                  {toolsSavedFlash && !toolsError && (
                    <div className="px-3 py-2 rounded-md bg-[rgba(34,197,94,0.1)] border border-[rgba(34,197,94,0.3)] text-[0.75rem] text-[var(--success-color)]">
                      {t('builderTab.toolsSaved')}
                    </div>
                  )}

                  <div className="flex items-center justify-end gap-2 pt-2">
                    <button
                      onClick={handleToolsRevert}
                      disabled={!toolsDirty || toolsSaving}
                      className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-transparent border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <RotateCcw size={12} />
                      {t('builderTab.revert')}
                    </button>
                    <button
                      onClick={handleToolsSave}
                      disabled={
                        !toolsDirty ||
                        toolsSaving ||
                        (toolsValidation ? toolsValidation.hasErrors : true)
                      }
                      className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-semibold cursor-pointer border-none transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <Save size={12} />
                      {toolsSaving ? t('builderTab.saving') : t('builderTab.toolsSave')}
                    </button>
                  </div>
                </>
              )}
            </section>

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
        ) : (
          <>
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

                {/* Strategies */}
                {activeIntrospection &&
                typeof activeIntrospection === 'object' &&
                activeIntrospection !== null &&
                Object.keys(
                  (activeIntrospection as StageIntrospection).strategy_slots || {},
                ).length > 0 ? (
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                      {t('builderTab.strategies')}
                    </label>
                    <StrategiesEditor
                      slots={(activeIntrospection as StageIntrospection).strategy_slots}
                      strategies={draft.strategies}
                      strategyConfigs={draft.strategyConfigs}
                      onChangeStrategies={next =>
                        setDraft({ ...draft, strategies: next })
                      }
                      onChangeStrategyConfigs={next =>
                        setDraft({ ...draft, strategyConfigs: next })
                      }
                    />
                  </div>
                ) : null}

                {/* Chains */}
                {activeIntrospection &&
                typeof activeIntrospection === 'object' &&
                activeIntrospection !== null &&
                Object.keys(
                  (activeIntrospection as StageIntrospection).strategy_chains || {},
                ).length > 0 ? (
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                      {t('builderTab.chains')}
                    </label>
                    <ChainsEditor
                      chains={(activeIntrospection as StageIntrospection).strategy_chains}
                      chainOrder={draft.chainOrder}
                      onChangeChainOrder={next =>
                        setDraft({ ...draft, chainOrder: next })
                      }
                    />
                  </div>
                ) : null}

                {/* S.1 (cycle 20260426_2) — per-stage model_override.
                    Subset of ModelConfig fields; empty = inherit
                    pipeline defaults. JSON textarea kept simple since
                    overrides are rare and operators typically know
                    the field names. */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                    Model override <span className="opacity-60 normal-case">(optional)</span>
                  </label>
                  <textarea
                    value={draft.modelOverrideText}
                    onChange={e =>
                      setDraft({ ...draft, modelOverrideText: e.target.value })
                    }
                    rows={5}
                    spellCheck={false}
                    placeholder={'(empty = inherit pipeline model)\nExample:\n{"model": "claude-haiku-3-5", "temperature": 0.2}'}
                    className="py-2 px-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] focus:border-[var(--primary-color)] font-mono text-[0.75rem] leading-[1.5] text-[var(--text-primary)] focus:outline-none focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] resize-y"
                  />
                  <small className="text-[0.6875rem] text-[var(--text-muted)]">
                    Subset of ModelConfig fields (model / temperature / max_tokens / thinking_*) applied
                    only to this stage. Empty textarea inherits the pipeline-level model.
                  </small>
                </div>

                {/* S.2 (cycle 20260426_2) — per-stage tool_binding.
                    Mostly meaningful on s10 (Tool stage); shown on every
                    stage for symmetry with the manifest schema. The
                    canonical shape is {"mode": "inherit" | "allowlist"
                    | "blocklist", "patterns": [...]} but the executor
                    accepts any dict so we keep the editor schema-loose. */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                    Tool binding <span className="opacity-60 normal-case">(optional, mostly s10)</span>
                  </label>
                  <textarea
                    value={draft.toolBindingText}
                    onChange={e =>
                      setDraft({ ...draft, toolBindingText: e.target.value })
                    }
                    rows={5}
                    spellCheck={false}
                    placeholder={'(empty = inherit pipeline tool roster)\nExample:\n{"mode": "allowlist", "patterns": ["Bash", "Read"]}'}
                    className="py-2 px-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] focus:border-[var(--primary-color)] font-mono text-[0.75rem] leading-[1.5] text-[var(--text-primary)] focus:outline-none focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] resize-y"
                  />
                  <small className="text-[0.6875rem] text-[var(--text-muted)]">
                    Restricts which tools this stage can dispatch.
                    Canonical shape: <code className="font-mono">{'{"mode": "inherit"|"allowlist"|"blocklist", "patterns": [...]}'}</code>.
                    Empty textarea inherits the pipeline tool roster.
                  </small>
                </div>

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
          </>
        )}
      </div>
    </div>
  );
}
