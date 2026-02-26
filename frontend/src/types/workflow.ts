// ==================== Workflow Types ====================

export interface WfNodeParameter {
  name: string;
  label: string;
  type: 'string' | 'number' | 'boolean' | 'select' | 'textarea' | 'json' | 'prompt_template';
  default?: unknown;
  required?: boolean;
  description?: string;
  placeholder?: string;
  options?: Array<{ value: string; label: string }>;
  min?: number;
  max?: number;
  group?: string;
  /** When true, changes to this parameter dynamically recompute output ports. */
  generates_ports?: boolean;
}

export interface WfOutputPort {
  id: string;
  label: string;
  description?: string;
}

/** Help section inside a node help guide. */
export interface WfHelpSection {
  title: string;
  content: string;
}

/** Complete help content for a node, in one locale. */
export interface WfNodeHelp {
  title: string;
  summary: string;
  sections: WfHelpSection[];
}

/** Locale-specific translations for a node. */
export interface WfNodeI18n {
  label?: string;
  description?: string;
  parameters?: Record<string, { label?: string; description?: string }>;
  output_ports?: Record<string, { label?: string; description?: string }>;
  groups?: Record<string, string>;
  help?: WfNodeHelp;
}

/** A registered node type definition (from the backend catalog). */
export interface WfNodeTypeDef {
  node_type: string;
  label: string;
  description: string;
  category: string;
  icon: string;
  color: string;
  is_conditional: boolean;
  parameters: WfNodeParameter[];
  output_ports: WfOutputPort[];
  /** i18n translations keyed by locale (e.g. 'ko', 'en') */
  i18n?: Record<string, WfNodeI18n>;
}

export interface WfNodeCatalog {
  categories: Record<string, WfNodeTypeDef[]>;
  total: number;
}

/** A node instance in a workflow definition. */
export interface WfNodeInstance {
  id: string;
  node_type: string;
  label: string;
  config: Record<string, unknown>;
  position: { x: number; y: number };
}

/** An edge in a workflow definition. */
export interface WfEdge {
  id: string;
  source: string;
  target: string;
  source_port: string;
  label: string;
}

/** Complete workflow definition from the backend. */
export interface WorkflowDefinition {
  id: string;
  name: string;
  description: string;
  nodes: WfNodeInstance[];
  edges: WfEdge[];
  created_at: string;
  updated_at: string;
  is_template: boolean;
  template_name?: string;
}

export interface WorkflowListResponse {
  workflows: WorkflowDefinition[];
  total: number;
}

export interface WorkflowValidateResponse {
  valid: boolean;
  errors: string[];
}

export interface WorkflowExecuteResponse {
  success: boolean;
  workflow_id: string;
  session_id: string;
  final_answer: string;
  is_complete: boolean;
  iterations: number;
  difficulty?: string;
  error?: string;
}

/** Compiled graph inspection response. */
export interface CompileViewNodeDetail {
  id: string;
  label: string;
  node_type: string;
  category?: string;
  role: string;
  description: string;
  is_conditional?: boolean;
  has_routing_function?: boolean;
  output_ports?: { id: string; label: string; description: string }[];
  targets?: { port: string; target_id: string; target_label: string; label: string }[];
  config?: Record<string, unknown>;
  routing_logic?: string;
}

export interface CompileViewEdgeBranch {
  port: string;
  target: string;
  target_label: string;
  label: string;
}

export interface CompileViewEdgeDetail {
  source: string;
  source_label: string;
  target: string | null;
  target_label: string | null;
  port: string | null;
  wiring: 'start' | 'simple' | 'conditional';
  has_routing_function?: boolean;
  description: string;
  branches?: CompileViewEdgeBranch[];
}

export interface CompileViewResponse {
  code: string;
  nodes: CompileViewNodeDetail[];
  edges: CompileViewEdgeDetail[];
  summary: {
    workflow_name: string;
    workflow_id: string;
    total_nodes: number;
    total_edges: number;
    conditional_edges: number;
    simple_edges: number;
    pseudo_nodes: number;
    is_valid: boolean;
  };
  validation: {
    valid: boolean;
    errors: string[];
  };
}

// ==================== Category Display Info ====================

export const CATEGORY_INFO: Record<string, { label: string; icon: string; color: string }> = {
  special: { label: 'Special', icon: '⚡', color: '#10b981' },
  model: { label: 'Model', icon: '🤖', color: '#8b5cf6' },
  task: { label: 'Task', icon: '📋', color: '#ef4444' },
  logic: { label: 'Logic', icon: '🔀', color: '#6366f1' },
  memory: { label: 'Memory', icon: '🧠', color: '#ec4899' },
  resilience: { label: 'Resilience', icon: '🛡️', color: '#6b7280' },
};
