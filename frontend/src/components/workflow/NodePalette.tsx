'use client';

import { useState, useCallback } from 'react';
import { useWorkflowStore } from '@/store/useWorkflowStore';
import { CATEGORY_INFO, type WfNodeTypeDef } from '@/types/workflow';

// ========== Draggable Palette Item ==========

function PaletteItem({ nodeDef }: { nodeDef: WfNodeTypeDef }) {
  const { setPaletteDragging } = useWorkflowStore();

  const onDragStart = useCallback(
    (e: React.DragEvent) => {
      e.dataTransfer.setData('application/workflow-node', JSON.stringify(nodeDef));
      e.dataTransfer.effectAllowed = 'move';
      setPaletteDragging(true);
    },
    [nodeDef, setPaletteDragging],
  );

  const onDragEnd = useCallback(() => {
    setPaletteDragging(false);
  }, [setPaletteDragging]);

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className="
        flex items-center gap-2.5 px-3 py-2 rounded-lg
        border border-transparent cursor-grab
        bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)]
        hover:border-[var(--border-subtle)]
        transition-all duration-150 select-none
        active:cursor-grabbing active:scale-[0.97]
      "
      title={nodeDef.description}
    >
      {/* Icon */}
      <span
        className="flex items-center justify-center w-7 h-7 rounded-md text-[14px] shrink-0"
        style={{ background: `${nodeDef.color}20` }}
      >
        {nodeDef.icon}
      </span>

      {/* Label + description */}
      <div className="min-w-0 flex-1">
        <div className="text-[12px] font-semibold text-[var(--text-primary)] truncate">
          {nodeDef.label}
        </div>
        <div className="text-[10px] text-[var(--text-muted)] truncate leading-tight mt-0.5">
          {nodeDef.description}
        </div>
      </div>

      {/* Conditional badge */}
      {nodeDef.is_conditional && (
        <span className="text-[10px] text-[var(--text-muted)] shrink-0 font-mono">◆</span>
      )}
    </div>
  );
}

// ========== Category Section ==========

function CategorySection({
  category,
  nodes,
  isOpen,
  onToggle,
}: {
  category: string;
  nodes: WfNodeTypeDef[];
  isOpen: boolean;
  onToggle: () => void;
}) {
  const info = CATEGORY_INFO[category] || { label: category, icon: '📦', color: '#64748b' };

  return (
    <div className="mb-1">
      {/* Category header */}
      <button
        className="
          flex items-center gap-2 w-full px-3 py-2 text-left
          hover:bg-[var(--bg-hover)] rounded-md transition-colors duration-100
        "
        onClick={onToggle}
      >
        <span className="text-[13px]">{info.icon}</span>
        <span className="text-[12px] font-semibold text-[var(--text-secondary)] uppercase tracking-wider flex-1">
          {info.label}
        </span>
        <span className="text-[10px] text-[var(--text-muted)] mr-1">{nodes.length}</span>
        <svg
          className={`w-3.5 h-3.5 text-[var(--text-muted)] transition-transform duration-150 ${isOpen ? 'rotate-90' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </button>

      {/* Node list */}
      {isOpen && (
        <div className="space-y-1 px-1 pb-1">
          {nodes.map(n => (
            <PaletteItem key={n.node_type} nodeDef={n} />
          ))}
        </div>
      )}
    </div>
  );
}

// ========== Main Palette Component ==========

export default function NodePalette() {
  const { nodeCatalog } = useWorkflowStore();
  const [openCategories, setOpenCategories] = useState<Set<string>>(
    new Set(['model', 'task', 'logic', 'memory', 'resilience']),
  );
  const [search, setSearch] = useState('');

  const toggleCategory = useCallback((cat: string) => {
    setOpenCategories(prev => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }, []);

  if (!nodeCatalog) {
    return (
      <div className="flex items-center justify-center h-32 text-[var(--text-muted)] text-[12px]">
        Loading nodes…
      </div>
    );
  }

  // Filter by search
  const filtered: Record<string, WfNodeTypeDef[]> = {};
  const q = search.toLowerCase();
  for (const [cat, nodes] of Object.entries(nodeCatalog.categories)) {
    const matching = q
      ? nodes.filter(n => n.label.toLowerCase().includes(q) || n.description.toLowerCase().includes(q))
      : nodes;
    if (matching.length > 0) filtered[cat] = matching;
  }

  // Category sort order
  const order = ['model', 'task', 'logic', 'memory', 'resilience'];
  const sortedCategories = Object.keys(filtered).sort(
    (a, b) => (order.indexOf(a) === -1 ? 99 : order.indexOf(a)) - (order.indexOf(b) === -1 ? 99 : order.indexOf(b)),
  );

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-[var(--border-color)]">
        <div className="text-[11px] font-bold text-[var(--text-secondary)] uppercase tracking-wider mb-2">
          Node Palette
        </div>
        {/* Search */}
        <div className="relative">
          <svg
            className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--text-muted)]"
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search nodes…"
            className="
              w-full pl-7 pr-2 py-1.5 text-[12px]
              bg-[var(--bg-tertiary)] border border-[var(--border-color)]
              rounded-md text-[var(--text-primary)]
              placeholder:text-[var(--text-muted)]
              focus:outline-none focus:border-[var(--primary-color)]
            "
          />
        </div>
      </div>

      {/* Scrollable node list */}
      <div className="flex-1 overflow-y-auto p-1.5 space-y-0.5">
        {sortedCategories.map(cat => (
          <CategorySection
            key={cat}
            category={cat}
            nodes={filtered[cat]}
            isOpen={openCategories.has(cat)}
            onToggle={() => toggleCategory(cat)}
          />
        ))}

        {sortedCategories.length === 0 && (
          <div className="text-center text-[var(--text-muted)] text-[12px] py-8">
            No matching nodes found
          </div>
        )}
      </div>

      {/* Tip */}
      <div className="px-3 py-2 border-t border-[var(--border-color)] text-[10px] text-[var(--text-muted)]">
        Drag nodes onto the canvas to add them to your workflow.
      </div>
    </div>
  );
}
