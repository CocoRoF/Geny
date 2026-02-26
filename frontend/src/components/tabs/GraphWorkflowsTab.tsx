'use client';

import { useState, useEffect, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { workflowApi } from '@/lib/workflowApi';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';
import type { WorkflowDefinition } from '@/types/workflow';
import { useWorkflowStore } from '@/store/useWorkflowStore';

const WorkflowEditor = dynamic(() => import('@/components/tabs/WorkflowTab'), { ssr: false });

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

// ==================== Workflow Card ==

function WorkflowCard({
  workflow,
  isSelected,
  onSelect,
  onView,
  onEdit,
  onClone,
  onDelete,
}: {
  workflow: { id: string; name: string; description: string; nodeCount?: number; edgeCount?: number; graph_type?: string; is_template?: boolean };
  isSelected: boolean;
  onSelect: () => void;
  onView?: () => void;
  onEdit?: () => void;
  onClone?: () => void;
  onDelete?: () => void;
}) {
  const { t } = useI18n();
  const isTemplate = workflow.is_template;
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
          <h4 className="text-[0.875rem] font-semibold text-[var(--text-primary)] truncate">{workflow.name}</h4>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {isTemplate && (
            <span className="text-[10px] font-semibold py-0.5 px-1.5 rounded-md bg-[rgba(168,85,247,0.12)] text-[#c084fc] border border-[rgba(168,85,247,0.2)] uppercase tracking-wide">
              {t('workflowsTab.official')}
            </span>
          )}
        </div>
      </div>

      {/* Description */}
      <p className="text-[0.75rem] text-[var(--text-muted)] line-clamp-2 leading-[1.5]">{workflow.description || t('workflowsTab.noDescription')}</p>

      {/* Stats */}
      <div className="flex items-center gap-3 text-[0.6875rem] text-[var(--text-muted)]">
        {workflow.nodeCount !== undefined && (
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary-color)]" />
            {t('workflowsTab.nodes', { count: workflow.nodeCount })}
          </span>
        )}
        {workflow.edgeCount !== undefined && (
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--text-muted)]" />
            {t('workflowsTab.edges', { count: workflow.edgeCount })}
          </span>
        )}
      </div>

      {/* Action Buttons (visible on hover) */}
      <div className="absolute bottom-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
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
        {onDelete && !workflow.is_template && (
          <button
            className="w-7 h-7 flex items-center justify-center rounded-md bg-[var(--bg-primary)] border border-[rgba(239,68,68,0.2)] text-[var(--text-muted)] hover:text-[var(--danger-color)] hover:bg-[rgba(239,68,68,0.08)] text-sm font-medium transition-colors"
            title={t('common.delete')}
            onClick={e => { e.stopPropagation(); onDelete(); }}
          >
            ×
          </button>
        )}
      </div>
    </div>
  );
}

// ==================== Main Component ====================

export default function GraphWorkflowsTab() {
  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([]);
  const [templates, setTemplates] = useState<WorkflowDefinition[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<'list' | 'editor' | 'viewer'>('list');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [viewName, setViewName] = useState('');

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [wfRes, tmplRes] = await Promise.all([
        workflowApi.list(),
        workflowApi.listTemplates(),
      ]);
      setWorkflows(wfRes.workflows || []);
      setTemplates(tmplRes.templates || []);
    } catch (e: unknown) {
      setError((e as Error).message || 'Failed to load workflows');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleCreate = useCallback(async () => {
    if (!newName.trim()) return;
    try {
      await workflowApi.create({ name: newName.trim(), description: newDesc.trim() });
      setNewName('');
      setNewDesc('');
      setShowCreateDialog(false);
      await fetchAll();
    } catch (e: unknown) {
      setError((e as Error).message);
    }
  }, [newName, newDesc, fetchAll]);

  const handleClone = useCallback(async (id: string) => {
    try {
      await workflowApi.clone(id);
      await fetchAll();
    } catch (e: unknown) {
      setError((e as Error).message);
    }
  }, [fetchAll]);

  const handleDelete = useCallback(async (id: string, name: string) => {
    if (!confirm(t('workflowStore.deleteConfirm', { name }))) return;
    try {
      await workflowApi.delete(id);
      if (selectedId === id) setSelectedId(null);
      await fetchAll();
    } catch (e: unknown) {
      setError((e as Error).message);
    }
  }, [fetchAll, selectedId]);

  const { loadWorkflow, loadFromDefinition, loadCatalog } = useWorkflowStore();
  const { t } = useI18n();

  // Ensure node catalog is loaded so loadFromDefinition can resolve styles
  useEffect(() => { loadCatalog(); }, [loadCatalog]);

  const openEditor = useCallback(() => {
    setMode('editor');
  }, []);

  const handleEdit = useCallback(async (id: string) => {
    await loadWorkflow(id);
    setMode('editor');
  }, [loadWorkflow]);

  const handleView = useCallback(async (def: WorkflowDefinition) => {
    const store = useWorkflowStore.getState();
    if (!store.nodeCatalog) await store.loadCatalog();
    loadFromDefinition(def);
    setViewName(def.name);
    setMode('viewer');
  }, [loadFromDefinition]);

  // Editor mode → full WorkflowEditor
  if (mode === 'editor') {
    return (
      <div className="flex flex-col h-full min-h-0 overflow-hidden">
        <div className="flex items-center gap-3 h-10 px-4 bg-[var(--bg-secondary)] border-b border-[var(--border-color)] shrink-0">
          <button
            className="flex items-center gap-1.5 h-7 px-3 text-[11px] font-medium rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-primary)] hover:text-[var(--text-primary)] transition-colors"
            onClick={() => { setMode('list'); fetchAll(); }}
          >
            {t('workflowsTab.backToWorkflows')}
          </button>
          <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">{t('workflowsTab.workflowEditor')}</span>
        </div>
        <div className="flex-1 min-h-0">
          <WorkflowEditor />
        </div>
      </div>
    );
  }

  // Viewer mode → read-only WorkflowEditor
  if (mode === 'viewer') {
    return (
      <div className="flex flex-col h-full min-h-0 overflow-hidden">
        <div className="flex items-center gap-3 h-10 px-4 bg-[var(--bg-secondary)] border-b border-[var(--border-color)] shrink-0">
          <button
            className="flex items-center gap-1.5 h-7 px-3 text-[11px] font-medium rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-primary)] hover:text-[var(--text-primary)] transition-colors"
            onClick={() => { setMode('list'); }}
          >
            {t('workflowsTab.backToWorkflows')}
          </button>
          <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">{t('workflowsTab.viewPrefix')}{viewName}</span>
          <span className="text-[10px] font-semibold py-0.5 px-1.5 rounded-md bg-[rgba(107,114,128,0.12)] text-[var(--text-muted)] border border-[rgba(107,114,128,0.2)] uppercase tracking-wide">
            {t('workflowsTab.readOnly')}
          </span>
        </div>
        <div className="flex-1 min-h-0">
          <WorkflowEditor readOnly />
        </div>
      </div>
    );
  }

  // List mode
  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between py-4 px-6 bg-[var(--bg-secondary)] border-b border-[var(--border-color)] shrink-0">
        <div>
          <h2 className="text-[1.125rem] font-semibold text-[var(--text-primary)]">{t('workflowsTab.title')}</h2>
          <p className="text-[0.75rem] text-[var(--text-muted)] mt-0.5">
            {t('workflowsTab.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            className="h-8 px-3 text-[0.75rem] font-medium rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-primary)] hover:text-[var(--text-primary)] transition-colors"
            onClick={openEditor}
          >
            {t('workflowsTab.openEditor')}
          </button>
          <button
            className="h-8 px-3 text-[0.75rem] font-medium rounded-md border border-[rgba(59,130,246,0.3)] bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)] hover:bg-[rgba(59,130,246,0.18)] transition-colors"
            onClick={() => setShowCreateDialog(true)}
          >
            {t('workflowsTab.newWorkflow')}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mx-6 mt-3 p-2.5 rounded-md bg-[rgba(239,68,68,0.1)] text-[0.8125rem] text-[var(--danger-color)]">
          {error}
          <button className="ml-2 underline text-[0.75rem]" onClick={() => setError('')}>{t('common.dismiss')}</button>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {loading ? (
          <div className="flex items-center justify-center py-12 text-[var(--text-muted)] text-[0.875rem]">{t('workflowsTab.loadingWorkflows')}</div>
        ) : (
          <div className="space-y-6">
            {/* Official Templates */}
            {templates.length > 0 && (
              <section>
                <h3 className="text-[0.8125rem] font-semibold text-[var(--text-secondary)] mb-3 flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#c084fc]" />
                  {t('workflowsTab.officialTemplates')}
                  <span className="text-[0.6875rem] text-[var(--text-muted)] font-normal">({templates.length})</span>
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {templates.map(tmpl => (
                    <WorkflowCard
                      key={tmpl.id}
                      workflow={{ ...tmpl, nodeCount: tmpl.nodes?.length, edgeCount: tmpl.edges?.length }}
                      isSelected={selectedId === tmpl.id}
                      onSelect={() => setSelectedId(tmpl.id)}
                      onView={() => handleView(tmpl)}
                      onClone={() => handleClone(tmpl.id)}
                    />
                  ))}
                </div>
              </section>
            )}

            {/* User Workflows */}
            <section>
              <h3 className="text-[0.8125rem] font-semibold text-[var(--text-secondary)] mb-3 flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary-color)]" />
                {t('workflowsTab.customWorkflows')}
                <span className="text-[0.6875rem] text-[var(--text-muted)] font-normal">({workflows.filter(w => !w.is_template).length})</span>
              </h3>
              {workflows.filter(w => !w.is_template).length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 px-4 rounded-lg border border-dashed border-[var(--border-color)] bg-[var(--bg-primary)]">
                  <p className="text-[0.8125rem] text-[var(--text-muted)] mb-3">{t('workflowsTab.noCustom')}</p>
                  <button
                    className="h-8 px-3 text-[0.75rem] font-medium rounded-md border border-[rgba(59,130,246,0.3)] bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)] hover:bg-[rgba(59,130,246,0.18)] transition-colors"
                    onClick={() => setShowCreateDialog(true)}
                  >
                    {t('workflowsTab.createFirst')}
                  </button>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {workflows.filter(w => !w.is_template).map(w => (
                    <WorkflowCard
                      key={w.id}
                      workflow={{ ...w, nodeCount: w.nodes?.length, edgeCount: w.edges?.length }}
                      isSelected={selectedId === w.id}
                      onSelect={() => setSelectedId(w.id)}
                      onEdit={() => handleEdit(w.id)}
                      onClone={() => handleClone(w.id)}
                      onDelete={() => handleDelete(w.id, w.name)}
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
              <h3 className="text-[0.9375rem] font-semibold text-[var(--text-primary)]">{t('workflowsTab.newWorkflowTitle')}</h3>
              <button className="flex items-center justify-center w-7 h-7 rounded bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer text-lg" onClick={() => setShowCreateDialog(false)}>×</button>
            </div>
            <div className="p-5 flex flex-col gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">{t('workflowsTab.nameLabel')}</label>
                <input
                  className="w-full py-2 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)]"
                  placeholder={t('workflowsTab.namePlaceholder')}
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleCreate()}
                  autoFocus
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">{t('workflowsTab.descriptionLabel')}</label>
                <textarea
                  className="w-full py-2 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] resize-y"
                  rows={2}
                  placeholder={t('workflowsTab.descriptionPlaceholder')}
                  value={newDesc}
                  onChange={e => setNewDesc(e.target.value)}
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 py-3 px-5 border-t border-[var(--border-color)]">
              <button className="py-1.5 px-3 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.75rem] font-medium rounded-[var(--border-radius)] cursor-pointer border border-[var(--border-color)]" onClick={() => setShowCreateDialog(false)}>{t('common.cancel')}</button>
              <button className="py-1.5 px-3 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-medium rounded-[var(--border-radius)] cursor-pointer border-none disabled:opacity-50" onClick={handleCreate} disabled={!newName.trim()}>{t('common.create')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
