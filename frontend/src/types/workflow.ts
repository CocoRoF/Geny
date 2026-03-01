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

/** A single field in a structured output schema. */
export interface WfStructuredOutputField {
  name: string;
  type: string;
  required: boolean;
  description?: string;
  dynamic_note?: string;
}

/** Structured output schema metadata for frontend display. */
export interface WfStructuredOutputSchema {
  name: string;
  description: string;
  fields: WfStructuredOutputField[];
  example?: Record<string, unknown>;
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
  /** Structured output schema — present when node uses Pydantic-validated LLM output. */
  structured_output_schema?: WfStructuredOutputSchema;
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

/** A single state field usage entry from the workflow state analysis. */
export interface StateFieldUsage {
  name: string;
  type: string;
  description: string;
  category: string;
  reducer: string;
  default: unknown;
  is_builtin: boolean;
  read_by: string[];
  written_by: string[];
  is_used: boolean;
}

/** Per-node state read/write summary. */
export interface NodeStateMapping {
  node_id: string;
  node_label: string;
  node_type: string;
  reads: string[];
  writes: string[];
}

/** Complete state analysis from the compile-view. */
export interface CompileViewStateAnalysis {
  fields: StateFieldUsage[];
  fields_by_category: Record<string, StateFieldUsage[]>;
  used_fields: StateFieldUsage[];
  unused_builtin_fields: StateFieldUsage[];
  custom_fields: StateFieldUsage[];
  per_node: NodeStateMapping[];
  summary: {
    total_builtin: number;
    used_count: number;
    unused_count: number;
    custom_count: number;
  };
}

export interface CompileViewResponse {
  code: string;
  nodes: CompileViewNodeDetail[];
  edges: CompileViewEdgeDetail[];
  state: CompileViewStateAnalysis;
  summary: {
    workflow_name: string;
    workflow_id: string;
    total_nodes: number;
    total_edges: number;
    conditional_edges: number;
    simple_edges: number;
    pseudo_nodes: number;
    is_valid: boolean;
    state_fields_used?: number;
    state_fields_total?: number;
  };
  validation: {
    valid: boolean;
    errors: string[];
  };
}

// ==================== Category Display Info ====================

export const CATEGORY_INFO: Record<string, { label: string; icon: string; color: string }> = {
  special: { label: 'Special', icon: 'zap', color: '#10b981' },
  model: { label: 'Model', icon: 'bot', color: '#8b5cf6' },
  task: { label: 'Task', icon: 'list-todo', color: '#ef4444' },
  logic: { label: 'Logic', icon: 'git-branch', color: '#6366f1' },
  memory: { label: 'Memory', icon: 'brain', color: '#ec4899' },
  resilience: { label: 'Resilience', icon: 'shield-check', color: '#6b7280' },
};
