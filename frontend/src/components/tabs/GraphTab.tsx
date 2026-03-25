'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { ReactFlowProvider } from '@xyflow/react';
import { useAppStore } from '@/store/useAppStore';
import { useWorkflowStore } from '@/store/useWorkflowStore';
import PropertyPanel from '@/components/workflow/PropertyPanel';
import WorkflowCanvas from '@/components/workflow/WorkflowCanvas';
import { agentApi } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { BarChart3, AlertTriangle, RefreshCw, X } from 'lucide-react';
import { useIsMobile } from '@/lib/useIsMobile';
import type { WorkflowDefinition } from '@/types/workflow';

// ========== Main GraphTab Component ==========

export default function GraphTab() {
  const { selectedSessionId, sessions, setActiveTab } = useAppStore();
  const { t } = useI18n();
  const { selectedNodeId, setSelectedNode, nodes } = useWorkflowStore();
  const isMobile = useIsMobile();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [workflowDef, setWorkflowDef] = useState<WorkflowDefinition | null>(null);

  // Get current session info
  const session = useMemo(
    () => sessions.find(s => s.session_id === selectedSessionId),
    [sessions, selectedSessionId],
  );

  // Load workflow definition for the selected session
  const fetchSessionWorkflow = useCallback(async () => {
    if (!selectedSessionId) return;
    setLoading(true);
    setError('');
    try {
      // Ensure node catalog is loaded first (needed for proper node rendering)
      const store = useWorkflowStore.getState();
      if (!store.nodeCatalog) {
        await store.loadCatalog();
      }

      // Fetch the workflow definition associated with this session
      const wfDef = await agentApi.getWorkflow(selectedSessionId);
      setWorkflowDef(wfDef);

      // Load into the workflow store for ReactFlow rendering
      useWorkflowStore.getState().loadFromDefinition(wfDef);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to load graph';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [selectedSessionId]);

  useEffect(() => {
    fetchSessionWorkflow();
  }, [fetchSessionWorkflow]);

  // Derive display metadata
  const graphName = session?.graph_name || workflowDef?.name || 'Simple';
  const isTemplate = workflowDef?.is_template ?? false;
  const nodeCount = workflowDef?.nodes?.length ?? nodes.length;
  const edgeCount = workflowDef?.edges?.length ?? 0;

  // ── No session selected ──
  if (!selectedSessionId) {
    return (
      <div className="flex flex-col h-full min-h-0 overflow-hidden">
        <div className="flex items-center justify-center flex-1">
          <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
            <BarChart3 size={32} className="mb-3 opacity-60 text-[var(--text-muted)]" />
            <h3 className="text-[1rem] font-medium text-[var(--text-secondary)] mb-2">
              {t('graphTab.selectSession')}
            </h3>
            <p className="text-[0.8125rem] text-[var(--text-muted)] max-w-[360px]">
              {t('graphTab.selectSessionDesc')}
              <button
                className="text-[var(--primary-color)] underline underline-offset-2 font-medium bg-transparent border-none cursor-pointer"
                onClick={() => setActiveTab('workflows')}
              >
                {t('graphTab.workflowsLink')}
              </button>
              {t('graphTab.selectSessionSuffix')}
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-2">
          <div className="w-6 h-6 border-2 border-[var(--primary-color)] border-t-transparent rounded-full animate-spin" />
          <span className="text-[0.8125rem] text-[var(--text-muted)]">{t('graphTab.loadingGraph')}</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3 text-center max-w-[400px]">
          <AlertTriangle size={28} className="text-[var(--warning-color)]" />
          <p className="text-[0.875rem] text-[var(--danger-color)]">{error}</p>
          <button
            className="px-4 py-2 text-[0.8125rem] rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-colors inline-flex items-center gap-1.5"
            onClick={fetchSessionWorkflow}
          >
            <RefreshCw size={12} /> {t('graphTab.resetBtn')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <ReactFlowProvider>
      <div className="flex flex-col h-full min-h-0 overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center justify-between h-10 px-2 md:px-4 bg-[var(--bg-secondary)] border-b border-[var(--border-color)] shrink-0 overflow-x-auto scrollbar-hide">
          <div className="flex items-center gap-2 md:gap-3 min-w-0">
            <span className="text-[12px] md:text-[13px] font-semibold text-[var(--text-primary)] flex items-center gap-2 shrink-0">
              {t('graphTab.title')}
            </span>

            {/* Graph name */}
            <span className="text-[11px] md:text-[12px] font-medium text-[var(--text-secondary)] truncate max-w-[120px] md:max-w-[200px]">
              {graphName}
            </span>

            {/* Template badge */}
            {isTemplate && (
              <span className="hidden sm:inline text-[10px] font-semibold py-[2px] px-1.5 rounded-md bg-[rgba(168,85,247,0.12)] text-[#c084fc] border border-[rgba(168,85,247,0.2)] uppercase tracking-wide shrink-0">
                Template
              </span>
            )}

            {/* Session name */}
            {session?.session_name && (
              <>
                <span className="w-px h-4 bg-[var(--border-color)] shrink-0 hidden md:block" />
                <span className="text-[11px] text-[var(--text-muted)] truncate max-w-[100px] md:max-w-[150px] hidden md:block">
                  {session.session_name}
                </span>
              </>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {/* Stats */}
            <span className="text-[10px] text-[var(--text-muted)]">
              {t('workflowEditor.nodesEdges', { nodes: nodeCount, edges: edgeCount })}
            </span>

            {/* Refresh */}
            <button
              className="h-7 px-2.5 text-[11px] font-medium rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-primary)] hover:text-[var(--text-primary)] transition-colors"
              onClick={fetchSessionWorkflow}
            >
              ⟳ {t('graphTab.resetBtn')}
            </button>
          </div>
        </div>

        {/* Canvas + Property Panel */}
        <div className="flex flex-1 min-h-0 relative">
          {/* ReactFlow Canvas */}
          <div className="flex-1 min-w-0">
            <WorkflowCanvas readOnly />
          </div>

          {/* Mobile backdrop for property panel */}
          {isMobile && selectedNodeId && (
            <div className="fixed inset-0 z-20 bg-black/40" onClick={() => setSelectedNode(null)} />
          )}

          {/* Property Panel — overlay on mobile, side panel on desktop */}
          <div
            className={`shrink-0 border-l border-[var(--border-color)] bg-[var(--bg-secondary)] overflow-y-auto transition-[width] duration-150 ${
              selectedNodeId
                ? 'fixed inset-y-0 right-0 z-30 w-[280px] md:static md:w-[300px] shadow-lg md:shadow-none'
                : 'w-0 overflow-hidden border-l-0'
            }`}
          >
            {/* Mobile close button */}
            {isMobile && selectedNodeId && (
              <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-color)]">
                <span className="text-xs font-medium text-[var(--text-secondary)]">{t('propertyPanel.title')}</span>
                <button
                  onClick={() => setSelectedNode(null)}
                  className="p-1 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)]"
                >
                  <X size={16} />
                </button>
              </div>
            )}
            <div className="w-[280px] md:w-[300px]">
              <PropertyPanel readOnly />
            </div>
          </div>
        </div>
      </div>
    </ReactFlowProvider>
  );
}
