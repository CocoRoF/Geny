'use client';

import { useCallback, useRef, useMemo, type DragEvent } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { useWorkflowStore, type WorkflowNodeData } from '@/store/useWorkflowStore';
import { workflowNodeTypes } from './CustomNodes';

export default function WorkflowCanvas() {
  const rfRef = useRef<ReactFlowInstance<Node<WorkflowNodeData>, Edge> | null>(null);

  const {
    nodes,
    edges,
    selectedNodeId,
    onNodesChange,
    onEdgesChange,
    onConnect,
    addNode,
    setSelectedNode,
    nodeCatalog,
  } = useWorkflowStore();

  // ── Selection tracking ──
  const handleSelectionChange = useCallback(
    ({ nodes: sel }: { nodes: Array<{ id: string }> }) => {
      if (sel.length === 1) {
        setSelectedNode(sel[0].id);
      } else if (sel.length === 0 && selectedNodeId) {
        setSelectedNode(null);
      }
    },
    [setSelectedNode, selectedNodeId],
  );

  // ── Edge validation: prevent duplicate / self-connections ──
  const isValidConnection = useCallback((connection: { source: string | null; target: string | null; sourceHandle?: string | null }) => {
    if (!connection.source || !connection.target) return false;
    if (connection.source === connection.target) return false;
    const existing = useWorkflowStore.getState().edges;
    return !existing.some(
      e =>
        e.source === connection.source &&
        e.target === connection.target &&
        e.sourceHandle === connection.sourceHandle,
    );
  }, []);

  // ── Drag & Drop from palette ──
  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData('application/workflow-node');
      if (!raw || !rfRef.current || !nodeCatalog) return;

      let payload: { nodeType: string };
      try {
        payload = JSON.parse(raw);
      } catch {
        return;
      }

      // Find the type definition from catalog
      let typeDef = null;
      for (const catNodes of Object.values(nodeCatalog.categories)) {
        const found = catNodes.find(n => n.node_type === payload.nodeType);
        if (found) { typeDef = found; break; }
      }
      if (!typeDef) return;

      // Convert screen coords → flow coords
      const position = rfRef.current.screenToFlowPosition({
        x: e.clientX,
        y: e.clientY,
      });

      addNode(typeDef, position);
    },
    [nodeCatalog, addNode],
  );

  const handleInit = useCallback((instance: ReactFlowInstance<Node<WorkflowNodeData>, Edge>) => {
    rfRef.current = instance;
  }, []);

  // ── Default edge options ──
  const defaultEdgeOptions = useMemo(
    () => ({
      type: 'smoothstep' as const,
      animated: false,
      style: { stroke: 'var(--text-muted)', strokeWidth: 1.5 },
    }),
    [],
  );

  return (
    <div className="h-full w-full relative workflow-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onInit={handleInit}
        onSelectionChange={handleSelectionChange}
        isValidConnection={isValidConnection}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        nodeTypes={workflowNodeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        snapToGrid
        snapGrid={[16, 16]}
        minZoom={0.15}
        maxZoom={2}
        deleteKeyCode="Delete"
        multiSelectionKeyCode="Shift"
        proOptions={{ hideAttribution: true }}
        className="bg-[var(--bg-primary)]"
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="var(--border-color)" />
        <Controls
          showZoom
          showFitView
          showInteractive={false}
          className="!bg-[var(--bg-secondary)] !border-[var(--border-color)] !shadow-lg [&>button]:!bg-[var(--bg-secondary)] [&>button]:!border-[var(--border-color)] [&>button]:!fill-[var(--text-secondary)] [&>button:hover]:!bg-[var(--bg-tertiary)]"
        />
        <MiniMap
          nodeStrokeWidth={3}
          nodeColor={(n) => {
            const d = n.data as WorkflowNodeData;
            return d.color || '#6366f1';
          }}
          maskColor="rgba(0,0,0,0.65)"
          className="!bg-[var(--bg-secondary)] !border-[var(--border-color)]"
        />
      </ReactFlow>

      {/* Canvas hint overlay (shown when empty) */}
      {nodes.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
          <div className="text-center p-6 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border-color)] shadow-lg">
            <div className="text-[28px] mb-2">🎨</div>
            <div className="text-[13px] font-semibold text-[var(--text-secondary)] mb-1">
              Design Your Workflow
            </div>
            <div className="text-[11px] text-[var(--text-muted)] leading-relaxed max-w-[260px]">
              Drag nodes from the palette or load a template to get started.
              Connect nodes by dragging from handles.
            </div>
          </div>
        </div>
      )}

      {/* Global canvas styles */}
      <style jsx global>{`
        .workflow-canvas .react-flow__edge-path {
          stroke: var(--text-muted);
          stroke-width: 1.5px;
        }
        .workflow-canvas .react-flow__edge.selected .react-flow__edge-path {
          stroke: var(--primary-color);
          stroke-width: 2px;
        }
        .workflow-canvas .react-flow__edge-text {
          font-size: 10px;
          fill: var(--text-muted);
        }
        .workflow-canvas .react-flow__handle {
          width: 8px;
          height: 8px;
          border: 1.5px solid var(--text-muted);
          background: var(--bg-secondary);
        }
        .workflow-canvas .react-flow__handle:hover {
          background: var(--primary-color);
          border-color: var(--primary-color);
        }
        .workflow-canvas .react-flow__connection-line {
          stroke: var(--primary-color);
          stroke-width: 2px;
          stroke-dasharray: 5 5;
        }
      `}</style>
    </div>
  );
}
