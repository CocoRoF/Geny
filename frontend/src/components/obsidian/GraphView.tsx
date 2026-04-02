'use client';

import { useCallback, useMemo, useEffect, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeMouseHandler,
  MarkerType,
  ConnectionLineType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useObsidianStore } from '@/store/useObsidianStore';
import { memoryApi } from '@/lib/api';

const CATEGORY_COLORS: Record<string, string> = {
  daily: '#f59e0b',
  topics: '#3b82f6',
  entities: '#10b981',
  projects: '#8b5cf6',
  insights: '#ec4899',
  root: '#64748b',
};

const IMPORTANCE_SIZE: Record<string, number> = {
  critical: 80,
  high: 65,
  medium: 50,
  low: 40,
};

function forceLayout(
  graphNodes: { id: string; label: string; category: string; importance: string }[],
  graphEdges: { source: string; target: string }[],
): { x: number; y: number; id: string }[] {
  // Simple force-directed layout
  const positions: Record<string, { x: number; y: number }> = {};
  const len = graphNodes.length;
  if (len === 0) return [];

  // Initialize in a circle
  graphNodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / len;
    const radius = Math.min(400, 80 * Math.sqrt(len));
    positions[n.id] = {
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
    };
  });

  // Run 120 iterations of simple force simulation
  for (let iter = 0; iter < 120; iter++) {
    const forces: Record<string, { fx: number; fy: number }> = {};
    graphNodes.forEach((n) => (forces[n.id] = { fx: 0, fy: 0 }));

    // Repulsion between all nodes
    for (let i = 0; i < len; i++) {
      for (let j = i + 1; j < len; j++) {
        const a = graphNodes[i].id;
        const b = graphNodes[j].id;
        const dx = positions[a].x - positions[b].x;
        const dy = positions[a].y - positions[b].y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const repulse = 15000 / (dist * dist);
        const fx = (dx / dist) * repulse;
        const fy = (dy / dist) * repulse;
        forces[a].fx += fx;
        forces[a].fy += fy;
        forces[b].fx -= fx;
        forces[b].fy -= fy;
      }
    }

    // Attraction along edges
    graphEdges.forEach((e) => {
      if (!positions[e.source] || !positions[e.target]) return;
      const dx = positions[e.target].x - positions[e.source].x;
      const dy = positions[e.target].y - positions[e.source].y;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const attract = dist * 0.005;
      const fx = dx * attract;
      const fy = dy * attract;
      forces[e.source].fx += fx;
      forces[e.source].fy += fy;
      forces[e.target].fx -= fx;
      forces[e.target].fy -= fy;
    });

    // Center gravity
    graphNodes.forEach((n) => {
      forces[n.id].fx -= positions[n.id].x * 0.001;
      forces[n.id].fy -= positions[n.id].y * 0.001;
    });

    // Apply forces with damping
    const damping = 0.8 - iter * 0.004;
    graphNodes.forEach((n) => {
      const f = forces[n.id];
      const maxForce = 10;
      positions[n.id].x += Math.max(-maxForce, Math.min(maxForce, f.fx * damping));
      positions[n.id].y += Math.max(-maxForce, Math.min(maxForce, f.fy * damping));
    });
  }

  return graphNodes.map((n) => ({
    id: n.id,
    x: positions[n.id].x,
    y: positions[n.id].y,
  }));
}

export default function GraphView() {
  const {
    graphNodes,
    graphEdges,
    files,
    selectedSessionId,
    openFile,
    setFileDetail,
    setViewMode,
  } = useObsidianStore();

  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const layoutPositions = useMemo(
    () => forceLayout(graphNodes, graphEdges),
    [graphNodes, graphEdges]
  );

  const initialNodes: Node[] = useMemo(
    () =>
      graphNodes.map((gn) => {
        const pos = layoutPositions.find((p) => p.id === gn.id) || { x: 0, y: 0 };
        const size = IMPORTANCE_SIZE[gn.importance] || 50;
        const color = CATEGORY_COLORS[gn.category] || '#64748b';
        return {
          id: gn.id,
          position: { x: pos.x, y: pos.y },
          data: {
            label: gn.label,
            category: gn.category,
            importance: gn.importance,
          },
          style: {
            background: color,
            color: '#fff',
            border: 'none',
            borderRadius: '50%',
            width: size,
            height: size,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: Math.max(8, size / 6),
            fontWeight: 600,
            textAlign: 'center' as const,
            padding: 4,
            cursor: 'pointer',
            boxShadow: `0 0 ${size / 3}px ${color}40`,
            transition: 'transform 150ms ease, box-shadow 150ms ease',
            overflow: 'hidden',
            lineHeight: '1.2',
            wordBreak: 'break-word' as const,
          },
          type: 'default',
        };
      }),
    [graphNodes, layoutPositions]
  );

  const initialEdges: Edge[] = useMemo(
    () =>
      graphEdges.map((ge, i) => ({
        id: `e-${i}`,
        source: ge.source,
        target: ge.target,
        animated: false,
        style: { stroke: 'var(--text-muted)', strokeWidth: 1, opacity: 0.4 },
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: 'var(--text-muted)' },
        type: 'default',
      })),
    [graphEdges]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => {
    setNodes(initialNodes);
    setEdges(initialEdges);
  }, [initialNodes, initialEdges, setNodes, setEdges]);

  const onNodeClick: NodeMouseHandler = useCallback(
    async (_, node) => {
      openFile(node.id);
      setViewMode('editor');
      if (selectedSessionId) {
        try {
          const detail = await memoryApi.readFile(selectedSessionId, node.id);
          setFileDetail(detail);
        } catch (e) {
          console.error('Failed to read:', e);
        }
      }
    },
    [selectedSessionId, openFile, setFileDetail, setViewMode]
  );

  if (graphNodes.length === 0) {
    return (
      <div className="obs-graph-empty">
        <p>No memory graph data available for this session.</p>
        <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          Memory notes with [[wikilinks]] will appear as connected nodes.
        </p>
      </div>
    );
  }

  return (
    <div className="obs-graph">
      {/* Legend */}
      <div className="obs-graph-legend">
        {Object.entries(CATEGORY_COLORS).map(([cat, color]) => (
          <span key={cat} className="obs-graph-legend-item">
            <span className="obs-graph-legend-dot" style={{ background: color }} />
            {cat}
          </span>
        ))}
      </div>

      {/* Hover tooltip */}
      {hoveredNode && files[hoveredNode] && (
        <div className="obs-graph-tooltip">
          <div className="obs-graph-tooltip-title">{files[hoveredNode].title}</div>
          <div className="obs-graph-tooltip-meta">
            {files[hoveredNode].tags.map((t) => `#${t}`).join(' ')}
          </div>
        </div>
      )}

      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onNodeMouseEnter={(_, node) => setHoveredNode(node.id)}
        onNodeMouseLeave={() => setHoveredNode(null)}
        connectionLineType={ConnectionLineType.SmoothStep}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        minZoom={0.1}
        maxZoom={3}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="var(--border-color)" gap={20} size={1} />
        <Controls
          showInteractive={false}
          style={{
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border-color)',
            borderRadius: 8,
          }}
        />
        <MiniMap
          nodeColor={(n) => CATEGORY_COLORS[n.data?.category as string] || '#64748b'}
          maskColor="var(--overlay-bg)"
          style={{
            background: 'var(--minimap-bg)',
            border: '1px solid var(--border-color)',
            borderRadius: 8,
          }}
        />
      </ReactFlow>
    </div>
  );
}
