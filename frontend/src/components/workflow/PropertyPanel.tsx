'use client';

import { useState, useCallback, useMemo } from 'react';
import { useWorkflowStore, type WorkflowNodeData } from '@/store/useWorkflowStore';
import type { WfNodeParameter, WfNodeTypeDef } from '@/types/workflow';

// ========== Field Renderers ==========

function StringField({ param, value, onChange }: {
  param: WfNodeParameter; value: string; onChange: (v: string) => void;
}) {
  return (
    <input
      type="text"
      value={value || ''}
      onChange={e => onChange(e.target.value)}
      placeholder={param.placeholder || param.description}
      className="
        w-full px-2.5 py-1.5 text-[12px]
        bg-[var(--bg-tertiary)] border border-[var(--border-color)]
        rounded-md text-[var(--text-primary)]
        placeholder:text-[var(--text-muted)]
        focus:outline-none focus:border-[var(--primary-color)]
        transition-colors
      "
    />
  );
}

function NumberField({ param, value, onChange }: {
  param: WfNodeParameter; value: number; onChange: (v: number) => void;
}) {
  return (
    <input
      type="number"
      value={value ?? param.default ?? 0}
      onChange={e => onChange(Number(e.target.value))}
      min={param.min}
      max={param.max}
      step={1}
      className="
        w-full px-2.5 py-1.5 text-[12px]
        bg-[var(--bg-tertiary)] border border-[var(--border-color)]
        rounded-md text-[var(--text-primary)]
        focus:outline-none focus:border-[var(--primary-color)]
        transition-colors
      "
    />
  );
}

function BooleanField({ value, onChange }: {
  param: WfNodeParameter; value: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <button
      onClick={() => onChange(!value)}
      className={`
        relative w-10 h-5 rounded-full transition-colors duration-200 shrink-0
        ${value ? 'bg-[var(--primary-color)]' : 'bg-[var(--bg-tertiary)] border border-[var(--border-color)]'}
      `}
    >
      <span
        className={`
          absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white
          transition-transform duration-200
          ${value ? 'translate-x-5' : 'translate-x-0'}
        `}
      />
    </button>
  );
}

function SelectField({ param, value, onChange }: {
  param: WfNodeParameter; value: string; onChange: (v: string) => void;
}) {
  return (
    <select
      value={value || ''}
      onChange={e => onChange(e.target.value)}
      className="
        w-full px-2.5 py-1.5 text-[12px]
        bg-[var(--bg-tertiary)] border border-[var(--border-color)]
        rounded-md text-[var(--text-primary)]
        focus:outline-none focus:border-[var(--primary-color)]
      "
    >
      <option value="">Select…</option>
      {param.options?.map(opt => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  );
}

function TextareaField({ param, value, onChange }: {
  param: WfNodeParameter; value: string; onChange: (v: string) => void;
}) {
  return (
    <textarea
      value={value || ''}
      onChange={e => onChange(e.target.value)}
      placeholder={param.placeholder || param.description}
      rows={4}
      className="
        w-full px-2.5 py-1.5 text-[12px]
        bg-[var(--bg-tertiary)] border border-[var(--border-color)]
        rounded-md text-[var(--text-primary)]
        placeholder:text-[var(--text-muted)]
        focus:outline-none focus:border-[var(--primary-color)]
        font-mono resize-y min-h-[60px]
      "
    />
  );
}

function PromptTemplateField({ param, value, onChange }: {
  param: WfNodeParameter; value: string; onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-1">
      <textarea
        value={value || ''}
        onChange={e => onChange(e.target.value)}
        placeholder={param.placeholder || 'Enter prompt template…'}
        rows={6}
        className="
          w-full px-2.5 py-2 text-[11px]
          bg-[#0d0d0f] border border-[var(--border-color)]
          rounded-md text-[#a5d6ff]
          placeholder:text-[var(--text-muted)]
          focus:outline-none focus:border-[var(--primary-color)]
          font-mono resize-y min-h-[80px] leading-relaxed
        "
      />
      <div className="text-[10px] text-[var(--text-muted)]">
        Use {'{field}'} for state variable substitution. Available: input, answer, review_feedback, last_output
      </div>
    </div>
  );
}

function JsonField({ param, value, onChange }: {
  param: WfNodeParameter; value: string; onChange: (v: string) => void;
}) {
  const [error, setError] = useState('');

  const handleChange = useCallback((v: string) => {
    onChange(v);
    try {
      if (v.trim()) JSON.parse(v);
      setError('');
    } catch {
      setError('Invalid JSON');
    }
  }, [onChange]);

  return (
    <div className="space-y-1">
      <textarea
        value={typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
        onChange={e => handleChange(e.target.value)}
        placeholder={param.placeholder || '{}'}
        rows={4}
        className={`
          w-full px-2.5 py-2 text-[11px]
          bg-[#0d0d0f] border rounded-md text-[#c3e88d]
          placeholder:text-[var(--text-muted)]
          focus:outline-none focus:border-[var(--primary-color)]
          font-mono resize-y min-h-[60px]
          ${error ? 'border-[var(--danger-color)]' : 'border-[var(--border-color)]'}
        `}
      />
      {error && <div className="text-[10px] text-[var(--danger-color)]">{error}</div>}
    </div>
  );
}

// ========== Parameter Field Router ==========

function ParameterField({ param, value, onChange }: {
  param: WfNodeParameter;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  switch (param.type) {
    case 'string':
      return <StringField param={param} value={value as string} onChange={onChange} />;
    case 'number':
      return <NumberField param={param} value={value as number} onChange={onChange} />;
    case 'boolean':
      return <BooleanField param={param} value={!!value} onChange={onChange} />;
    case 'select':
      return <SelectField param={param} value={value as string} onChange={onChange} />;
    case 'textarea':
      return <TextareaField param={param} value={value as string} onChange={onChange} />;
    case 'prompt_template':
      return <PromptTemplateField param={param} value={value as string} onChange={onChange} />;
    case 'json':
      return <JsonField param={param} value={value as string} onChange={onChange} />;
    default:
      return <StringField param={param} value={value as string} onChange={onChange} />;
  }
}

// ========== Main Property Panel ==========

export default function PropertyPanel() {
  const { selectedNodeId, nodes, nodeCatalog, updateNodeConfig, updateNodeLabel, deleteSelectedNode } = useWorkflowStore();

  const selectedNode = useMemo(
    () => nodes.find(n => n.id === selectedNodeId),
    [nodes, selectedNodeId],
  );

  const typeDef = useMemo<WfNodeTypeDef | undefined>(() => {
    if (!selectedNode || !nodeCatalog) return undefined;
    const nodeType = (selectedNode.data as WorkflowNodeData).nodeType;
    for (const catNodes of Object.values(nodeCatalog.categories)) {
      const found = catNodes.find(n => n.node_type === nodeType);
      if (found) return found;
    }
    return undefined;
  }, [selectedNode, nodeCatalog]);

  const handleConfigChange = useCallback(
    (paramName: string, value: unknown) => {
      if (!selectedNodeId || !selectedNode) return;
      const currentConfig = (selectedNode.data as WorkflowNodeData).config || {};
      updateNodeConfig(selectedNodeId, { ...currentConfig, [paramName]: value });
    },
    [selectedNodeId, selectedNode, updateNodeConfig],
  );

  const handleLabelChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (!selectedNodeId) return;
      updateNodeLabel(selectedNodeId, e.target.value);
    },
    [selectedNodeId, updateNodeLabel],
  );

  // ── No selection state ──
  if (!selectedNode) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-4 text-center">
        <div className="text-[24px] mb-2 opacity-40">🔧</div>
        <div className="text-[12px] text-[var(--text-muted)]">
          Select a node to edit its properties
        </div>
      </div>
    );
  }

  const data = selectedNode.data as WorkflowNodeData;
  const isStartOrEnd = data.nodeType === 'start' || data.nodeType === 'end';
  const parameters = typeDef?.parameters || [];

  // Group parameters
  const groups: Record<string, WfNodeParameter[]> = {};
  for (const p of parameters) {
    const g = p.group || 'general';
    if (!groups[g]) groups[g] = [];
    groups[g].push(p);
  }
  const groupOrder = ['general', 'prompt', 'output', 'behavior', 'routing'];
  const sortedGroups = Object.keys(groups).sort(
    (a, b) => (groupOrder.indexOf(a) === -1 ? 99 : groupOrder.indexOf(a)) - (groupOrder.indexOf(b) === -1 ? 99 : groupOrder.indexOf(b)),
  );

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-[var(--border-color)]">
        <div className="flex items-center gap-2">
          <span
            className="flex items-center justify-center w-7 h-7 rounded-md text-[14px]"
            style={{ background: `${data.color}20` }}
          >
            {data.icon}
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-[11px] font-bold text-[var(--text-secondary)] uppercase tracking-wider">
              Properties
            </div>
            <div className="text-[10px] text-[var(--text-muted)] truncate">
              {data.nodeType}
            </div>
          </div>
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
        {/* Node Label */}
        <div>
          <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-1.5">
            Node Label
          </label>
          <input
            type="text"
            value={data.label}
            onChange={handleLabelChange}
            className="
              w-full px-2.5 py-1.5 text-[12px]
              bg-[var(--bg-tertiary)] border border-[var(--border-color)]
              rounded-md text-[var(--text-primary)]
              focus:outline-none focus:border-[var(--primary-color)]
            "
          />
        </div>

        {/* Node ID (read-only) */}
        <div>
          <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-1.5">
            Node ID
          </label>
          <div className="px-2.5 py-1.5 text-[11px] font-mono text-[var(--text-muted)] bg-[var(--bg-primary)] rounded-md border border-[var(--border-color)]">
            {selectedNode.id}
          </div>
        </div>

        {/* Parameters by group */}
        {!isStartOrEnd && sortedGroups.map(group => (
          <div key={group}>
            <div className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider mb-2 pb-1 border-b border-[var(--border-color)]">
              {group}
            </div>
            <div className="space-y-3">
              {groups[group].map(param => {
                const val = data.config?.[param.name] ?? param.default;
                return (
                  <div key={param.name}>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-[11px] font-semibold text-[var(--text-secondary)]">
                        {param.label}
                        {param.required && <span className="text-[var(--danger-color)] ml-0.5">*</span>}
                      </label>
                      {param.type === 'boolean' && (
                        <ParameterField
                          param={param}
                          value={val}
                          onChange={v => handleConfigChange(param.name, v)}
                        />
                      )}
                    </div>
                    {param.description && (
                      <div className="text-[10px] text-[var(--text-muted)] mb-1.5 leading-relaxed">
                        {param.description}
                      </div>
                    )}
                    {param.type !== 'boolean' && (
                      <ParameterField
                        param={param}
                        value={val}
                        onChange={v => handleConfigChange(param.name, v)}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        {/* Output ports info */}
        {data.isConditional && data.outputPorts && (
          <div>
            <div className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider mb-2 pb-1 border-b border-[var(--border-color)]">
              Output Ports
            </div>
            <div className="space-y-1">
              {data.outputPorts.map(port => (
                <div
                  key={port.id}
                  className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-[var(--bg-tertiary)] text-[11px]"
                >
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ background: data.color }}
                  />
                  <span className="font-medium text-[var(--text-primary)]">{port.label}</span>
                  <span className="text-[var(--text-muted)] font-mono">({port.id})</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Actions footer */}
      {!isStartOrEnd && (
        <div className="px-3 py-2.5 border-t border-[var(--border-color)]">
          <button
            onClick={deleteSelectedNode}
            className="
              w-full flex items-center justify-center gap-1.5 px-3 py-1.5
              text-[11px] font-medium text-[var(--danger-color)]
              bg-[rgba(239,68,68,0.08)] hover:bg-[rgba(239,68,68,0.15)]
              border border-[rgba(239,68,68,0.2)] rounded-md
              transition-colors duration-150
            "
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            Delete Node
          </button>
        </div>
      )}
    </div>
  );
}
