'use client';

import { useEffect, useState, useCallback } from 'react';
import { ReactFlowProvider } from '@xyflow/react';
import { useWorkflowStore } from '@/store/useWorkflowStore';
import NodePalette from '@/components/workflow/NodePalette';
import PropertyPanel from '@/components/workflow/PropertyPanel';
import WorkflowCanvas from '@/components/workflow/WorkflowCanvas';
import { workflowApi } from '@/lib/workflowApi';
import type { WorkflowDefinition } from '@/types/workflow';

// ==================== Toolbar ====================

function WorkflowToolbar() {
  const {
    workflows,
    currentWorkflow,
    isDirty,
    isLoading,
    error,
    loadWorkflow,
    saveWorkflow,
    createWorkflow,
    cloneWorkflow,
    deleteWorkflow,
    loadFromDefinition,
  } = useWorkflowStore();

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [templates, setTemplates] = useState<WorkflowDefinition[]>([]);
  const [showTemplates, setShowTemplates] = useState(false);

  // Load templates on mount
  useEffect(() => {
    workflowApi.listTemplates().then(res => setTemplates(res.templates)).catch(() => {});
  }, []);

  const handleCreate = useCallback(async () => {
    if (!newName.trim()) return;
    await createWorkflow(newName.trim());
    setNewName('');
    setShowCreate(false);
  }, [newName, createWorkflow]);

  const handleDelete = useCallback(async () => {
    if (!currentWorkflow) return;
    if (!confirm(`Delete workflow "${currentWorkflow.name}"?`)) return;
    await deleteWorkflow(currentWorkflow.id);
  }, [currentWorkflow, deleteWorkflow]);

  const handleLoadTemplate = useCallback(
    (t: WorkflowDefinition) => {
      loadFromDefinition(t);
      setShowTemplates(false);
    },
    [loadFromDefinition],
  );

  return (
    <div className="flex items-center gap-2 h-10 px-3 bg-[var(--bg-secondary)] border-b border-[var(--border-color)] shrink-0">
      {/* Workflow selector */}
      <select
        value={currentWorkflow?.id || ''}
        onChange={e => e.target.value && loadWorkflow(e.target.value)}
        className="
          h-7 px-2 text-[11px]
          bg-[var(--bg-tertiary)] border border-[var(--border-color)]
          rounded-md text-[var(--text-primary)]
          focus:outline-none focus:border-[var(--primary-color)]
          max-w-[180px]
        "
      >
        <option value="">Select workflow…</option>
        {workflows.map(w => (
          <option key={w.id} value={w.id}>
            {w.name} {w.is_template ? '(template)' : ''}
          </option>
        ))}
      </select>

      {/* New */}
      {showCreate ? (
        <div className="flex items-center gap-1">
          <input
            type="text"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreate()}
            placeholder="Workflow name"
            autoFocus
            className="h-7 px-2 text-[11px] w-[130px] bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)]"
          />
          <ToolbarBtn onClick={handleCreate} title="Confirm" disabled={!newName.trim()}>
            ✓
          </ToolbarBtn>
          <ToolbarBtn onClick={() => setShowCreate(false)} title="Cancel">
            ✕
          </ToolbarBtn>
        </div>
      ) : (
        <ToolbarBtn onClick={() => setShowCreate(true)} title="New workflow">
          ＋ New
        </ToolbarBtn>
      )}

      {/* Templates */}
      <div className="relative">
        <ToolbarBtn onClick={() => setShowTemplates(!showTemplates)} title="Load template">
          📋 Template
        </ToolbarBtn>
        {showTemplates && templates.length > 0 && (
          <div className="absolute top-full left-0 mt-1 z-50 min-w-[200px] bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg shadow-xl overflow-hidden">
            {templates.map(t => (
              <button
                key={t.id}
                onClick={() => handleLoadTemplate(t)}
                className="w-full text-left px-3 py-2 text-[11px] text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] transition-colors border-b border-[var(--border-color)] last:border-b-0"
              >
                <div className="font-semibold">{t.name}</div>
                <div className="text-[10px] text-[var(--text-muted)]">{t.description}</div>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="w-px h-5 bg-[var(--border-color)]" />

      {/* Save */}
      <ToolbarBtn
        onClick={() => saveWorkflow()}
        disabled={!currentWorkflow || !isDirty}
        title="Save workflow"
        accent={isDirty}
      >
        💾 Save{isDirty ? '*' : ''}
      </ToolbarBtn>

      {/* Clone */}
      {currentWorkflow && (
        <ToolbarBtn onClick={() => cloneWorkflow(currentWorkflow.id)} title="Clone workflow">
          📑 Clone
        </ToolbarBtn>
      )}

      {/* Delete */}
      {currentWorkflow && !currentWorkflow.is_template && (
        <ToolbarBtn onClick={handleDelete} danger title="Delete workflow">
          🗑 Delete
        </ToolbarBtn>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Status */}
      {isLoading && (
        <span className="text-[10px] text-[var(--text-muted)] animate-pulse">Loading…</span>
      )}
      {error && (
        <span className="text-[10px] text-[var(--danger-color)] max-w-[200px] truncate" title={error}>
          ⚠ {error}
        </span>
      )}

      {/* Workflow info */}
      {currentWorkflow && (
        <span className="text-[10px] text-[var(--text-muted)]">
          {currentWorkflow.nodes?.length || 0} nodes · {currentWorkflow.edges?.length || 0} edges
        </span>
      )}
    </div>
  );
}

function ToolbarBtn({
  children,
  onClick,
  disabled,
  title,
  accent,
  danger,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  accent?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`
        h-7 px-2.5 text-[11px] font-medium rounded-md
        border transition-colors duration-150 whitespace-nowrap
        disabled:opacity-40 disabled:cursor-not-allowed
        ${danger
          ? 'text-[var(--danger-color)] border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.06)] hover:bg-[rgba(239,68,68,0.12)]'
          : accent
            ? 'text-[var(--primary-color)] border-[rgba(59,130,246,0.3)] bg-[rgba(59,130,246,0.1)] hover:bg-[rgba(59,130,246,0.18)]'
            : 'text-[var(--text-secondary)] border-[var(--border-color)] bg-[var(--bg-tertiary)] hover:bg-[var(--bg-primary)] hover:text-[var(--text-primary)]'
        }
      `}
    >
      {children}
    </button>
  );
}

// ==================== Main Tab ====================

export default function WorkflowTab() {
  const { loadCatalog, loadWorkflows, selectedNodeId } = useWorkflowStore();

  // Init on mount — catalog must load before workflows so nodes get proper metadata
  useEffect(() => {
    const init = async () => {
      await loadCatalog();
      await loadWorkflows();
    };
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <ReactFlowProvider>
      <div className="flex flex-col h-full">
        <WorkflowToolbar />
        <div className="flex flex-1 min-h-0">
          {/* Left: Node Palette */}
          <div className="w-[240px] shrink-0 border-r border-[var(--border-color)] bg-[var(--bg-secondary)] overflow-y-auto">
            <NodePalette />
          </div>

          {/* Center: Canvas */}
          <div className="flex-1 min-w-0">
            <WorkflowCanvas />
          </div>

          {/* Right: Property Panel */}
          {selectedNodeId && (
            <div className="w-[300px] shrink-0 border-l border-[var(--border-color)] bg-[var(--bg-secondary)] overflow-y-auto">
              <PropertyPanel />
            </div>
          )}
        </div>
      </div>
    </ReactFlowProvider>
  );
}
