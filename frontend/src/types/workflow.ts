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
}

export interface WfOutputPort {
  id: string;
  label: string;
  description?: string;
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

// ==================== Category Display Info ====================

export const CATEGORY_INFO: Record<string, { label: string; icon: string; color: string }> = {
  special: { label: 'Special', icon: '⚡', color: '#10b981' },
  model: { label: 'Model', icon: '🤖', color: '#8b5cf6' },
  task: { label: 'Task', icon: '📋', color: '#ef4444' },
  logic: { label: 'Logic', icon: '🔀', color: '#6366f1' },
  memory: { label: 'Memory', icon: '🧠', color: '#ec4899' },
  resilience: { label: 'Resilience', icon: '🛡️', color: '#6b7280' },
};
