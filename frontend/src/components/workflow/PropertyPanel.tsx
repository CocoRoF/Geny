'use client';

import { useState, useCallback, useMemo } from 'react';
import { useWorkflowStore, type WorkflowNodeData } from '@/store/useWorkflowStore';
import { useI18n } from '@/lib/i18n';
import type { WfNodeParameter, WfNodeTypeDef, WfNodeI18n, WfStructuredOutputSchema } from '@/types/workflow';
import NodeHelpModal from './NodeHelpModal';

// ========== i18n Helper ==========

/**
 * Resolve a localised value from a node's i18n data.
 * Falls back to the original English value when no translation exists.
 */
function useNodeI18n(typeDef?: WfNodeTypeDef): WfNodeI18n | undefined {
  const { locale } = useI18n();
  return useMemo(() => {
    if (!typeDef?.i18n) return undefined;
    return typeDef.i18n[locale] ?? typeDef.i18n['ko'] ?? undefined;
  }, [typeDef, locale]);
}

/** Return a localised parameter label/description, falling back to the English defaults. */
function getParamI18n(param: WfNodeParameter, i18n?: WfNodeI18n) {
  const pI18n = i18n?.parameters?.[param.name];
  return {
    label: pI18n?.label || param.label,
    description: pI18n?.description || param.description,
  };
}

/** Return a localised group name. */
function getGroupI18n(group: string, i18n?: WfNodeI18n): string {
  return i18n?.groups?.[group] || group;
}

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
  const { t } = useI18n();
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
      <option value="">{t('propertyPanel.select')}</option>
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
  const { t } = useI18n();
  return (
    <div className="space-y-1">
      <textarea
        value={value || ''}
        onChange={e => onChange(e.target.value)}
        placeholder={param.placeholder || t('propertyPanel.promptPlaceholder')}
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
        {t('propertyPanel.promptHelp')}
      </div>
    </div>
  );
}

function JsonField({ param, value, onChange }: {
  param: WfNodeParameter; value: string; onChange: (v: string) => void;
}) {
  const { t } = useI18n();
  const [error, setError] = useState('');

  const handleChange = useCallback((v: string) => {
    onChange(v);
    // Skip JSON validation for generates_ports params — they accept
    // comma-separated text (e.g. "easy, medium, hard") as well as JSON.
    if (param.generates_ports) {
      setError('');
      return;
    }
    try {
      if (v.trim()) JSON.parse(v);
      setError('');
    } catch {
      setError(t('propertyPanel.invalidJson'));
    }
  }, [onChange, param.generates_ports]);

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

// ========== Structured Output Schema Preview ==========

function StructuredOutputPreview({ schema, color }: {
  schema: WfStructuredOutputSchema;
  color?: string;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-[rgba(99,102,241,0.25)] bg-[rgba(99,102,241,0.04)] overflow-hidden">
      {/* Header — always visible */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="
          w-full flex items-center gap-2 px-2.5 py-2
          text-left hover:bg-[rgba(99,102,241,0.08)]
          transition-colors duration-150
        "
      >
        <span className="text-[13px]">📐</span>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-bold text-[var(--primary-color)] uppercase tracking-wider">
            {t('propertyPanel.structuredOutput')}
          </div>
          <div className="text-[9px] text-[var(--text-muted)] truncate mt-0.5">
            {schema.name}
          </div>
        </div>
        <svg
          className={`w-3 h-3 text-[var(--text-muted)] transition-transform duration-200 shrink-0 ${expanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Expandable detail */}
      {expanded && (
        <div className="px-2.5 pb-2.5 space-y-2 border-t border-[rgba(99,102,241,0.15)]">
          {/* Description */}
          {schema.description && (
            <div className="text-[10px] text-[var(--text-muted)] pt-2 leading-relaxed">
              {schema.description}
            </div>
          )}

          {/* Fields table */}
          <div className="space-y-1">
            <div className="text-[9px] font-bold text-[var(--text-muted)] uppercase tracking-wider">
              {t('propertyPanel.schemaFields')}
            </div>
            {schema.fields.map(field => (
              <div
                key={field.name}
                className="
                  flex flex-col gap-0.5 px-2 py-1.5 rounded-md
                  bg-[var(--bg-primary)] border border-[var(--border-color)]
                "
              >
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] font-mono font-semibold text-[#c3e88d]">
                    {field.name}
                  </span>
                  <span className="text-[9px] font-mono text-[var(--text-muted)]">
                    {field.type}
                  </span>
                  {field.required && (
                    <span className="text-[8px] px-1 py-0 rounded bg-[rgba(239,68,68,0.15)] text-[var(--danger-color)] font-bold">
                      {t('propertyPanel.required')}
                    </span>
                  )}
                </div>
                {field.dynamic_note && (
                  <div className="text-[9px] text-[var(--primary-color)] leading-snug flex items-start gap-1">
                    <span className="shrink-0 mt-px">⚡</span>
                    <span>{field.dynamic_note}</span>
                  </div>
                )}
                {field.description && (
                  <div className="text-[9px] text-[var(--text-muted)] leading-snug">
                    {field.description}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Example JSON */}
          {schema.example && (
            <div className="space-y-1">
              <div className="text-[9px] font-bold text-[var(--text-muted)] uppercase tracking-wider">
                {t('propertyPanel.schemaExample')}
              </div>
              <pre className="
                px-2.5 py-2 text-[10px] leading-relaxed
                bg-[#0d0d0f] border border-[var(--border-color)]
                rounded-md font-mono text-[#a5d6ff] overflow-x-auto
                max-h-[120px] overflow-y-auto
              ">
                {JSON.stringify(schema.example, null, 2)}
              </pre>
            </div>
          )}

          {/* Validation badge */}
          <div className="flex items-center gap-1.5 pt-0.5">
            <span className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded-full bg-[rgba(16,185,129,0.1)] text-[#10b981] border border-[rgba(16,185,129,0.2)]">
              <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              {t('propertyPanel.pydanticValidated')}
            </span>
            <span className="flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded-full bg-[rgba(99,102,241,0.1)] text-[var(--primary-color)] border border-[rgba(99,102,241,0.2)]">
              <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              {t('propertyPanel.autoRetry')}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// ========== Main Property Panel ==========

export default function PropertyPanel({ readOnly = false }: { readOnly?: boolean }) {
  const { selectedNodeId, nodes, nodeCatalog, updateNodeConfig, updateNodeLabel, deleteSelectedNode } = useWorkflowStore();
  const { t, locale } = useI18n();
  const [showHelp, setShowHelp] = useState(false);

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

  // Resolve i18n for the current locale
  const nodeI18n = useNodeI18n(typeDef);

  // Help content for the current locale
  const helpData = useMemo(() => {
    if (!typeDef?.i18n) return undefined;
    const localeI18n = typeDef.i18n[locale] ?? typeDef.i18n['en'];
    return localeI18n?.help;
  }, [typeDef, locale]);

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
          {t('propertyPanel.selectNode')}
        </div>
      </div>
    );
  }

  const data = selectedNode.data as WorkflowNodeData;
  const isStartOrEnd = data.nodeType === 'start' || data.nodeType === 'end';
  const parameters = typeDef?.parameters || [];

  // Localised label & description for the header
  const nodeLabel = nodeI18n?.label || typeDef?.label || data.nodeType;
  const nodeDescription = nodeI18n?.description || typeDef?.description || '';

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
              {t('propertyPanel.title')}
            </div>
            <div className="text-[10px] text-[var(--text-muted)] truncate">
              {data.nodeType}
            </div>
          </div>
          {/* Help button — only shown for nodes with help content */}
          {helpData && (
            <button
              onClick={() => setShowHelp(true)}
              title={t('propertyPanel.helpTooltip')}
              className="
                flex items-center justify-center w-6 h-6 rounded-md shrink-0
                text-[11px] font-bold
                text-[var(--primary-color)] bg-[rgba(99,102,241,0.1)]
                hover:bg-[rgba(99,102,241,0.2)]
                border border-[rgba(99,102,241,0.2)]
                transition-colors duration-150
              "
            >
              ?
            </button>
          )}
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
        {/* Node Label */}
        <div>
          <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-1.5">
            {t('propertyPanel.nodeLabel')}
          </label>
          <input
            type="text"
            value={data.label}
            onChange={handleLabelChange}
            readOnly={readOnly}
            disabled={readOnly}
            className="
              w-full px-2.5 py-1.5 text-[12px]
              bg-[var(--bg-tertiary)] border border-[var(--border-color)]
              rounded-md text-[var(--text-primary)]
              focus:outline-none focus:border-[var(--primary-color)]
              disabled:opacity-60 disabled:cursor-not-allowed
            "
          />
        </div>

        {/* Node ID (read-only) */}
        <div>
          <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-1.5">
            {t('propertyPanel.nodeId')}
          </label>
          <div className="px-2.5 py-1.5 text-[11px] font-mono text-[var(--text-muted)] bg-[var(--bg-primary)] rounded-md border border-[var(--border-color)]">
            {selectedNode.id}
          </div>
        </div>

        {/* Parameters by group — with i18n labels */}
        {!isStartOrEnd && sortedGroups.map(group => (
          <div key={group}>
            <div className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider mb-2 pb-1 border-b border-[var(--border-color)]">
              {getGroupI18n(group, nodeI18n)}
            </div>
            <div className={`space-y-3 ${readOnly ? 'opacity-70 pointer-events-none' : ''}`}>
              {groups[group].map(param => {
                const val = data.config?.[param.name] ?? param.default;
                const pi18n = getParamI18n(param, nodeI18n);
                return (
                  <div key={param.name}>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-[11px] font-semibold text-[var(--text-secondary)]">
                        {pi18n.label}
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
                    {pi18n.description && (
                      <div className="text-[10px] text-[var(--text-muted)] mb-1.5 leading-relaxed">
                        {pi18n.description}
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

        {/* Structured Output Schema — shown for nodes that use validated LLM output */}
        {typeDef?.structured_output_schema && (
          <StructuredOutputPreview
            schema={typeDef.structured_output_schema}
            color={data.color}
          />
        )}

        {/* Output ports info — with i18n labels */}
        {data.isConditional && data.outputPorts && (
          <div>
            <div className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider mb-2 pb-1 border-b border-[var(--border-color)]">
              {t('propertyPanel.outputPorts')}
            </div>
            <div className="space-y-1">
              {data.outputPorts.map(port => {
                const portI18n = nodeI18n?.output_ports?.[port.id];
                return (
                  <div
                    key={port.id}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-[var(--bg-tertiary)] text-[11px]"
                  >
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ background: data.color }}
                    />
                    <span className="font-medium text-[var(--text-primary)]">
                      {portI18n?.label || port.label}
                    </span>
                    <span className="text-[var(--text-muted)] font-mono">({port.id})</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Actions footer */}
      {!isStartOrEnd && !readOnly && (
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
            {t('propertyPanel.deleteNode')}
          </button>
        </div>
      )}

      {/* Help Modal */}
      {showHelp && helpData && (
        <NodeHelpModal
          help={helpData}
          icon={data.icon}
          color={data.color}
          onClose={() => setShowHelp(false)}
        />
      )}
    </div>
  );
}
