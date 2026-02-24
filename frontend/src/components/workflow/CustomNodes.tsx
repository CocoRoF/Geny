'use client';

import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { WorkflowNodeData } from '@/store/useWorkflowStore';

// ========== Start Node ==========

export const StartNode = memo(({ data, selected }: NodeProps) => {
  const d = data as unknown as WorkflowNodeData;
  return (
    <div
      className={`
        flex items-center justify-center w-[120px] h-[48px] rounded-full
        border-2 transition-all duration-150 cursor-pointer select-none
        ${selected
          ? 'border-[#10b981] shadow-[0_0_0_3px_rgba(16,185,129,0.25)]'
          : 'border-[#10b981]/40 hover:border-[#10b981]/70'}
      `}
      style={{ background: 'linear-gradient(135deg, rgba(16,185,129,0.15), rgba(16,185,129,0.05))' }}
    >
      <span className="text-[16px] mr-1.5">▶</span>
      <span className="text-[13px] font-semibold text-[#10b981]">{d.label}</span>
      <Handle
        type="source"
        position={Position.Bottom}
        id="default"
        className="!w-3 !h-3 !bg-[#10b981] !border-2 !border-[#18181b] !-bottom-1.5"
      />
    </div>
  );
});
StartNode.displayName = 'StartNode';

// ========== End Node ==========

export const EndNode = memo(({ data, selected }: NodeProps) => {
  const d = data as unknown as WorkflowNodeData;
  return (
    <div
      className={`
        flex items-center justify-center w-[120px] h-[48px] rounded-full
        border-2 transition-all duration-150 cursor-pointer select-none
        ${selected
          ? 'border-[#6b7280] shadow-[0_0_0_3px_rgba(107,114,128,0.25)]'
          : 'border-[#6b7280]/40 hover:border-[#6b7280]/70'}
      `}
      style={{ background: 'linear-gradient(135deg, rgba(107,114,128,0.15), rgba(107,114,128,0.05))' }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !bg-[#6b7280] !border-2 !border-[#18181b] !-top-1.5"
      />
      <span className="text-[16px] mr-1.5">⏹</span>
      <span className="text-[13px] font-semibold text-[#6b7280]">{d.label}</span>
    </div>
  );
});
EndNode.displayName = 'EndNode';

// ========== Standard Workflow Node ==========

export const WorkflowNode = memo(({ data, selected }: NodeProps) => {
  const d = data as unknown as WorkflowNodeData;
  const borderColor = d.color || '#3b82f6';

  return (
    <div
      className={`
        relative min-w-[180px] max-w-[220px] rounded-lg border-2
        transition-all duration-150 cursor-pointer select-none
        bg-[#18181b]
        ${selected ? 'shadow-[0_0_0_3px_rgba(59,130,246,0.3)]' : 'hover:shadow-md'}
      `}
      style={{
        borderColor: selected ? borderColor : `${borderColor}66`,
      }}
    >
      {/* Target handle (top) */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !border-2 !border-[#18181b] !-top-1.5"
        style={{ background: borderColor }}
      />

      {/* Header */}
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-t-[5px]"
        style={{ background: `${borderColor}15` }}
      >
        <span className="text-[14px] leading-none">{d.icon}</span>
        <span
          className="text-[12px] font-semibold truncate"
          style={{ color: borderColor }}
        >
          {d.label}
        </span>
      </div>

      {/* Category badge */}
      <div className="px-3 py-1.5 pb-2.5">
        <span
          className="inline-block text-[10px] px-1.5 py-0.5 rounded-[3px] font-medium"
          style={{ background: `${borderColor}20`, color: `${borderColor}cc` }}
        >
          {d.category}
        </span>
      </div>

      {/* Source handle (bottom) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="default"
        className="!w-3 !h-3 !border-2 !border-[#18181b] !-bottom-1.5"
        style={{ background: borderColor }}
      />
    </div>
  );
});
WorkflowNode.displayName = 'WorkflowNode';

// ========== Conditional Node (multiple output ports) ==========

export const ConditionalNode = memo(({ data, selected }: NodeProps) => {
  const d = data as unknown as WorkflowNodeData;
  const borderColor = d.color || '#3b82f6';
  const ports = d.outputPorts || [{ id: 'default', label: 'Next' }];

  return (
    <div
      className={`
        relative min-w-[200px] max-w-[240px] rounded-lg border-2
        transition-all duration-150 cursor-pointer select-none
        bg-[#18181b]
        ${selected ? 'shadow-[0_0_0_3px_rgba(59,130,246,0.3)]' : 'hover:shadow-md'}
      `}
      style={{
        borderColor: selected ? borderColor : `${borderColor}66`,
      }}
    >
      {/* Target handle (top) */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3 !h-3 !border-2 !border-[#18181b] !-top-1.5"
        style={{ background: borderColor }}
      />

      {/* Header with diamond icon */}
      <div
        className="flex items-center gap-2 px-3 py-2 rounded-t-[5px]"
        style={{ background: `${borderColor}15` }}
      >
        <span className="text-[14px] leading-none">{d.icon}</span>
        <span
          className="text-[12px] font-semibold truncate"
          style={{ color: borderColor }}
        >
          {d.label}
        </span>
        <span className="ml-auto text-[10px] text-[var(--text-muted)]">◆</span>
      </div>

      {/* Output ports */}
      <div className="px-3 py-2 space-y-1">
        {ports.map((port, i) => (
          <div
            key={port.id}
            className="flex items-center gap-1.5 text-[11px] text-[var(--text-secondary)]"
          >
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: borderColor }}
            />
            <span className="truncate">{port.label}</span>
          </div>
        ))}
      </div>

      {/* Output handles — one per port, spread across the bottom edge */}
      {ports.map((port, i) => {
        const total = ports.length;
        const pct = total === 1 ? 50 : 15 + (i * 70) / Math.max(total - 1, 1);
        return (
          <Handle
            key={port.id}
            type="source"
            position={Position.Bottom}
            id={port.id}
            className="!w-2.5 !h-2.5 !border-2 !border-[#18181b] !-bottom-1.5"
            style={{
              background: borderColor,
              left: `${pct}%`,
            }}
          />
        );
      })}
    </div>
  );
});
ConditionalNode.displayName = 'ConditionalNode';

// ========== Node Types mapping for React Flow ==========

export const workflowNodeTypes = {
  startNode: StartNode,
  endNode: EndNode,
  workflowNode: WorkflowNode,
  conditionalNode: ConditionalNode,
};
