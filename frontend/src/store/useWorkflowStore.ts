/**
 * Workflow Editor Store — Zustand state management for the workflow editor.
 */

import { create } from 'zustand';
import {
  type Edge,
  type Node,
  type OnNodesChange,
  type OnEdgesChange,
  type OnConnect,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  MarkerType,
} from '@xyflow/react';
import { workflowApi } from '@/lib/workflowApi';
import type {
  WfNodeCatalog,
  WfNodeTypeDef,
  WorkflowDefinition,
  WfNodeInstance,
  WfEdge,
} from '@/types/workflow';

// ==================== Node Data Type ====================

export interface WorkflowNodeData {
  label: string;
  nodeType: string;
  icon: string;
  color: string;
  category: string;
  isConditional: boolean;
  config: Record<string, unknown>;
  outputPorts: Array<{ id: string; label: string }>;
  [key: string]: unknown;
}

// ==================== Store Types ====================

interface WorkflowEditorState {
  // React Flow state
  nodes: Node<WorkflowNodeData>[];
  edges: Edge[];
  selectedNodeId: string | null;

  // Catalog
  nodeCatalog: WfNodeCatalog | null;

  // Workflow data
  workflows: WorkflowDefinition[];
  currentWorkflow: WorkflowDefinition | null;
  isDirty: boolean;

  // UI
  isPaletteDragging: boolean;
  isLoading: boolean;
  error: string | null;

  // Actions — React Flow
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  setSelectedNode: (id: string | null) => void;

  // Actions — Node manipulation
  addNode: (nodeType: WfNodeTypeDef, position: { x: number; y: number }) => string;
  updateNodeConfig: (nodeId: string, config: Record<string, unknown>) => void;
  updateNodeLabel: (nodeId: string, label: string) => void;
  deleteSelectedNode: () => void;

  // Actions — Data
  loadCatalog: () => Promise<void>;
  loadWorkflows: () => Promise<void>;
  loadWorkflow: (id: string) => Promise<void>;
  saveWorkflow: () => Promise<void>;
  createWorkflow: (name: string, description?: string) => Promise<void>;
  deleteWorkflow: (id: string) => Promise<void>;
  cloneWorkflow: (id: string) => Promise<void>;
  loadFromDefinition: (def: WorkflowDefinition) => void;

  // Actions — Workflow palette drag
  setPaletteDragging: (v: boolean) => void;

  // Actions — Dirty flag
  markDirty: () => void;
}

// ==================== Helpers ====================

function wfNodeToReactFlow(
  inst: WfNodeInstance,
  catalog: WfNodeCatalog | null,
): Node<WorkflowNodeData> {
  // Find the type definition
  let typeDef: WfNodeTypeDef | undefined;
  if (catalog) {
    for (const nodes of Object.values(catalog.categories)) {
      typeDef = nodes.find(n => n.node_type === inst.node_type);
      if (typeDef) break;
    }
  }

  const isStart = inst.node_type === 'start';
  const isEnd = inst.node_type === 'end';

  return {
    id: inst.id,
    type: isStart ? 'startNode' : isEnd ? 'endNode' : typeDef?.is_conditional ? 'conditionalNode' : 'workflowNode',
    position: inst.position,
    data: {
      label: inst.label || typeDef?.label || inst.node_type,
      nodeType: inst.node_type,
      icon: isStart ? '▶' : isEnd ? '⏹' : (typeDef?.icon || '⚡'),
      color: isStart ? '#10b981' : isEnd ? '#6b7280' : (typeDef?.color || '#3b82f6'),
      category: typeDef?.category || 'general',
      isConditional: typeDef?.is_conditional || false,
      config: inst.config,
      outputPorts: typeDef?.output_ports || [{ id: 'default', label: 'Next' }],
    },
  };
}

function wfEdgeToReactFlow(edge: WfEdge): Edge {
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.source_port || 'default',
    label: edge.label || undefined,
    type: 'smoothstep',
    animated: false,
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
    style: { stroke: '#64748b', strokeWidth: 2 },
    labelStyle: { fontSize: 11, fill: '#a1a1aa', fontWeight: 500 },
    labelBgStyle: { fill: '#18181b', fillOpacity: 0.9 },
    labelBgPadding: [6, 3] as [number, number],
    labelBgBorderRadius: 4,
  };
}

function reactFlowToWfNodes(nodes: Node<WorkflowNodeData>[]): WfNodeInstance[] {
  return nodes.map(n => ({
    id: n.id,
    node_type: n.data.nodeType,
    label: n.data.label,
    config: n.data.config || {},
    position: { x: n.position.x, y: n.position.y },
  }));
}

function reactFlowToWfEdges(edges: Edge[]): WfEdge[] {
  return edges.map(e => ({
    id: e.id,
    source: e.source,
    target: e.target,
    source_port: e.sourceHandle || 'default',
    label: (e.label as string) || '',
  }));
}

let _nodeIdCounter = 1;
function genNodeId(): string {
  return `n_${Date.now().toString(36)}_${_nodeIdCounter++}`;
}
function genEdgeId(): string {
  return `e_${Date.now().toString(36)}_${_nodeIdCounter++}`;
}

// ==================== Store ====================

export const useWorkflowStore = create<WorkflowEditorState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  nodeCatalog: null,
  workflows: [],
  currentWorkflow: null,
  isDirty: false,
  isPaletteDragging: false,
  isLoading: false,
  error: null,

  // ── React Flow change handlers ──

  onNodesChange: (changes) => {
    set({ nodes: applyNodeChanges(changes, get().nodes) as Node<WorkflowNodeData>[], isDirty: true });
  },

  onEdgesChange: (changes) => {
    set({ edges: applyEdgeChanges(changes, get().edges), isDirty: true });
  },

  onConnect: (connection) => {
    const newEdge: Edge = {
      ...connection,
      id: genEdgeId(),
      type: 'smoothstep',
      animated: false,
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      style: { stroke: '#64748b', strokeWidth: 2 },
    };
    set({ edges: addEdge(newEdge, get().edges), isDirty: true });
  },

  setSelectedNode: (id) => set({ selectedNodeId: id }),

  // ── Node manipulation ──

  addNode: (nodeType, position) => {
    const id = genNodeId();
    const isStart = nodeType.node_type === 'start';
    const isEnd = nodeType.node_type === 'end';

    // Collect default config from parameters
    const defaultConfig: Record<string, unknown> = {};
    for (const param of nodeType.parameters) {
      if (param.default !== undefined) {
        defaultConfig[param.name] = param.default;
      }
    }

    const newNode: Node<WorkflowNodeData> = {
      id,
      type: isStart ? 'startNode' : isEnd ? 'endNode' : nodeType.is_conditional ? 'conditionalNode' : 'workflowNode',
      position,
      data: {
        label: nodeType.label,
        nodeType: nodeType.node_type,
        icon: isStart ? '▶' : isEnd ? '⏹' : nodeType.icon,
        color: isStart ? '#10b981' : isEnd ? '#6b7280' : nodeType.color,
        category: nodeType.category,
        isConditional: nodeType.is_conditional,
        config: defaultConfig,
        outputPorts: nodeType.output_ports,
      },
    };

    set({ nodes: [...get().nodes, newNode], isDirty: true });
    return id;
  },

  updateNodeConfig: (nodeId, config) => {
    set({
      nodes: get().nodes.map(n =>
        n.id === nodeId ? { ...n, data: { ...n.data, config } } : n
      ),
      isDirty: true,
    });
  },

  updateNodeLabel: (nodeId, label) => {
    set({
      nodes: get().nodes.map(n =>
        n.id === nodeId ? { ...n, data: { ...n.data, label } } : n
      ),
      isDirty: true,
    });
  },

  deleteSelectedNode: () => {
    const { selectedNodeId, nodes, edges } = get();
    if (!selectedNodeId) return;
    set({
      nodes: nodes.filter(n => n.id !== selectedNodeId),
      edges: edges.filter(e => e.source !== selectedNodeId && e.target !== selectedNodeId),
      selectedNodeId: null,
      isDirty: true,
    });
  },

  // ── Data operations ──

  loadCatalog: async () => {
    try {
      const catalog = await workflowApi.getNodeCatalog();
      set({ nodeCatalog: catalog });
    } catch (e) {
      console.error('Failed to load node catalog:', e);
      set({ error: 'Failed to load node catalog' });
    }
  },

  loadWorkflows: async () => {
    try {
      set({ isLoading: true });
      const { workflows } = await workflowApi.list();
      set({ workflows, isLoading: false });
    } catch (e) {
      console.error('Failed to load workflows:', e);
      set({ error: 'Failed to load workflows', isLoading: false });
    }
  },

  loadWorkflow: async (id: string) => {
    try {
      set({ isLoading: true });
      const workflow = await workflowApi.get(id);
      get().loadFromDefinition(workflow);
      set({ isLoading: false });
    } catch (e) {
      console.error('Failed to load workflow:', e);
      set({ error: 'Failed to load workflow', isLoading: false });
    }
  },

  saveWorkflow: async () => {
    const { currentWorkflow, nodes, edges } = get();
    if (!currentWorkflow) return;
    if (currentWorkflow.is_template) {
      set({ error: 'Cannot save a template. Clone it first.' });
      return;
    }

    try {
      set({ isLoading: true });
      const wfNodes = reactFlowToWfNodes(nodes);
      const wfEdges = reactFlowToWfEdges(edges);
      const updated = await workflowApi.update(currentWorkflow.id, {
        nodes: wfNodes,
        edges: wfEdges,
        name: currentWorkflow.name,
        description: currentWorkflow.description,
      });
      set({ currentWorkflow: updated, isDirty: false, isLoading: false });
    } catch (e) {
      console.error('Failed to save workflow:', e);
      set({ error: 'Failed to save workflow', isLoading: false });
    }
  },

  createWorkflow: async (name, description) => {
    try {
      set({ isLoading: true });
      // Create with start and end nodes
      const startNode: WfNodeInstance = {
        id: 'start', node_type: 'start', label: 'Start',
        config: {}, position: { x: 400, y: 40 },
      };
      const endNode: WfNodeInstance = {
        id: 'end', node_type: 'end', label: 'End',
        config: {}, position: { x: 400, y: 300 },
      };

      const workflow = await workflowApi.create({
        name: name || 'Untitled Workflow',
        description: description || '',
        nodes: [startNode, endNode],
        edges: [],
      });

      get().loadFromDefinition(workflow);
      await get().loadWorkflows();
      set({ isLoading: false });
    } catch (e) {
      console.error('Failed to create workflow:', e);
      set({ error: 'Failed to create workflow', isLoading: false });
    }
  },

  deleteWorkflow: async (id) => {
    try {
      await workflowApi.delete(id);
      const { currentWorkflow } = get();
      if (currentWorkflow?.id === id) {
        set({ currentWorkflow: null, nodes: [], edges: [] });
      }
      await get().loadWorkflows();
    } catch (e) {
      console.error('Failed to delete workflow:', e);
    }
  },

  cloneWorkflow: async (id) => {
    try {
      set({ isLoading: true });
      const clone = await workflowApi.clone(id);
      get().loadFromDefinition(clone);
      await get().loadWorkflows();
      set({ isLoading: false });
    } catch (e) {
      console.error('Failed to clone workflow:', e);
      set({ error: 'Failed to clone workflow', isLoading: false });
    }
  },

  loadFromDefinition: (def: WorkflowDefinition) => {
    const catalog = get().nodeCatalog;
    const rfNodes = def.nodes.map(n => wfNodeToReactFlow(n, catalog));
    const rfEdges = def.edges.map(e => wfEdgeToReactFlow(e));
    set({
      currentWorkflow: def,
      nodes: rfNodes,
      edges: rfEdges,
      isDirty: false,
      selectedNodeId: null,
      error: null,
    });
  },

  setPaletteDragging: (v) => set({ isPaletteDragging: v }),
  markDirty: () => set({ isDirty: true }),
}));
