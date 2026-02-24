'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import type { GraphStructure, GraphNode, GraphEdge } from '@/types';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

// ========== Layout Constants ==========
const L = {
  nodeWidth: 180, nodeHeight: 56, startEndRadius: 28,
  horizontalGap: 80, verticalGap: 100, padding: 60, arrowSize: 8,
};

// ========== Layout Engine ==========

function computeLayout(data: GraphStructure): Record<string, { x: number; y: number }> {
  if (data.graph_type === 'simple') return computeSimpleLayout(data.nodes);
  return computeAutonomousLayout(data.nodes);
}

function computeSimpleLayout(nodes: GraphNode[]) {
  const positions: Record<string, { x: number; y: number }> = {};
  const order = ['__start__', 'context_guard', 'agent', 'process_output', '__end__'];
  const centerX = 400, startY = L.padding;
  order.forEach((id, i) => { positions[id] = { x: centerX, y: startY + i * (L.nodeHeight + L.verticalGap) }; });
  return positions;
}

function computeAutonomousLayout(nodes: GraphNode[]) {
  const positions: Record<string, { x: number; y: number }> = {};
  const colW = L.nodeWidth + L.horizontalGap; // 260
  const step = L.nodeHeight + 22; // 78
  const branchGap = 100;
  const colX = { easy: 180, medium: 180 + colW, hard: 180 + colW * 2 };
  const topCenter = (colX.easy + colX.hard) / 2;

  let y = L.padding;
  positions['__start__'] = { x: topCenter, y }; y += step;
  positions['memory_inject'] = { x: topCenter, y }; y += step;
  positions['guard_classify'] = { x: topCenter, y }; y += step;
  positions['classify_difficulty'] = { x: topCenter, y }; y += step;
  positions['post_classify'] = { x: topCenter, y };
  const branchBase = y + branchGap;

  // Easy
  y = branchBase;
  positions['guard_direct'] = { x: colX.easy, y }; y += step;
  positions['direct_answer'] = { x: colX.easy, y }; y += step;
  positions['post_direct'] = { x: colX.easy, y };

  // Medium
  y = branchBase;
  ['guard_answer', 'answer', 'post_answer', 'guard_review', 'review', 'post_review', 'iter_gate_medium'].forEach(id => {
    positions[id] = { x: colX.medium, y }; y += step;
  });

  // Hard
  y = branchBase;
  ['guard_create_todos', 'create_todos', 'post_create_todos', 'guard_execute', 'execute_todo',
   'post_execute', 'check_progress', 'iter_gate_hard', 'guard_final_review', 'final_review',
   'post_final_review', 'guard_final_answer', 'final_answer', 'post_final_answer'].forEach(id => {
    positions[id] = { x: colX.hard, y }; y += step;
  });

  const maxY = Math.max(...Object.values(positions).map(p => p.y));
  positions['__end__'] = { x: topCenter, y: maxY + branchGap };
  return positions;
}

// ========== Node Utilities ==========
const NODE_ICONS: Record<string, string> = {
  context_guard: '🛡️', agent: '🤖', process_output: '⚙️', classify_difficulty: '🔀',
  direct_answer: '⚡', answer: '💬', review: '📋', create_todos: '📝',
  execute_todo: '🔨', check_progress: '📊', final_review: '✅', final_answer: '🎯',
  memory_inject: '🧠', guard_classify: '🛡️', guard_direct: '🛡️', guard_answer: '🛡️',
  guard_review: '🛡️', guard_create_todos: '🛡️', guard_execute: '🛡️',
  guard_final_review: '🛡️', guard_final_answer: '🛡️',
  post_classify: '📌', post_direct: '📌', post_answer: '📌', post_review: '📌',
  post_create_todos: '📌', post_execute: '📌', post_final_review: '📌', post_final_answer: '📌',
  iter_gate_medium: '🚧', iter_gate_hard: '🚧',
};

function getPathColor(node: GraphNode) {
  if (node.type === 'resilience') return '#6b7280';
  const p = node.path;
  if (p === 'easy') return '#10b981';
  if (p === 'medium') return '#f59e0b';
  if (p === 'hard') return '#ef4444';
  return '#3b82f6';
}

function getNodeFill(node: GraphNode) {
  if (node.type === 'start') return '#3b82f6';
  if (node.type === 'end') return '#6b7280';
  if (node.type === 'resilience') return '#1e293b';
  return '#18181b';
}

function getNodeStroke(node: GraphNode) {
  if (node.type === 'start' || node.type === 'end') return 'none';
  return getPathColor(node) + '60';
}

// ========== Main Component ==========

export default function GraphTab() {
  const { selectedSessionId, sessions, setActiveTab } = useAppStore();
  const [graphData, setGraphData] = useState<GraphStructure | null>(null);
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Pan/zoom state
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [scale, setScale] = useState(1);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0 });

  const fetchGraph = useCallback(async () => {
    if (!selectedSessionId) return;
    setLoading(true);
    setError('');
    try {
      const data = await agentApi.getGraph(selectedSessionId);
      setGraphData(data);
      const pos = computeLayout(data);
      setPositions(pos);
      // Fit to viewport
      const allX = Object.values(pos).map(p => p.x);
      const allY = Object.values(pos).map(p => p.y);
      const svgW = Math.max(...allX) + L.nodeWidth + L.padding * 2;
      const svgH = Math.max(...allY) + L.nodeHeight + L.padding * 2;
      if (wrapperRef.current) {
        const rect = wrapperRef.current.getBoundingClientRect();
        const sx = rect.width / svgW;
        const sy = rect.height / svgH;
        const s = Math.min(sx, sy, 1);
        setPan({ x: (rect.width - svgW * s) / 2, y: (rect.height - svgH * s) / 2 });
        setScale(s);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [selectedSessionId]);

  useEffect(() => { fetchGraph(); }, [fetchGraph]);

  // Pan handlers
  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      setPan({ x: e.clientX - dragStart.current.x, y: e.clientY - dragStart.current.y });
    };
    const onMouseUp = () => { dragging.current = false; };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => { window.removeEventListener('mousemove', onMouseMove); window.removeEventListener('mouseup', onMouseUp); };
  }, []);

  const onWrapperMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('.graph-node-g')) return;
    dragging.current = true;
    dragStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
  };

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.08 : 0.08;
    const newScale = Math.max(0.15, Math.min(2.5, scale + delta));
    const rect = wrapperRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const ratio = newScale / scale;
    setPan({ x: mx - ratio * (mx - pan.x), y: my - ratio * (my - pan.y) });
    setScale(newScale);
  };

  // ── No session selected ──
  if (!selectedSessionId) {
    return (
      <div className="flex flex-col h-full min-h-0 overflow-hidden">
        <div className="flex items-center justify-center flex-1">
          <div className="flex flex-col items-center justify-center py-12 px-4">
            <h3 className="text-[1rem] font-medium text-[var(--text-secondary)] mb-2">Select a Session</h3>
            <p className="text-[0.8125rem] text-[var(--text-muted)]">Choose a session to view its graph, or go to <button className="text-[var(--primary-color)] underline underline-offset-2 font-medium bg-transparent border-none cursor-pointer" onClick={() => setActiveTab('workflows')}>Workflows</button> to manage graph workflows</p>
          </div>
        </div>
      </div>
    );
  }

  if (loading) return <div className="flex items-center justify-center h-full text-[var(--text-muted)]">Loading graph...</div>;
  if (error) return <div className="flex items-center justify-center h-full text-[var(--danger-color)] text-[0.875rem]">{error}</div>;
  if (!graphData) return null;

  // Calculate SVG dimensions
  const allX = Object.values(positions).map(p => p.x);
  const allY = Object.values(positions).map(p => p.y);
  const svgW = allX.length ? Math.max(...allX) + L.nodeWidth + L.padding * 2 : 800;
  const svgH = allY.length ? Math.max(...allY) + L.nodeHeight + L.padding * 2 : 600;

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden rounded-lg" style={{ background: '#0c0c0f' }}>
      {/* Toolbar */}
      <div className="flex items-center justify-between py-3 px-4 bg-[var(--bg-secondary)] border-b border-[var(--border-color)] shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-[15px] font-semibold text-[var(--text-primary)] flex items-center gap-2">
            Graph
          </span>
          <span className={`text-[11px] font-semibold py-[2px] px-2 rounded-[10px] uppercase tracking-[0.5px] ${graphData.graph_type === 'autonomous' ? 'text-[#c084fc] border border-[rgba(168,85,247,0.3)]' : 'text-[#60a5fa] border border-[rgba(59,130,246,0.3)]'}`}
                style={{ background: graphData.graph_type === 'autonomous' ? 'rgba(168, 85, 247, 0.15)' : 'rgba(59, 130, 246, 0.15)' }}>
            {graphData.graph_type === 'autonomous' ? 'Autonomous' : 'Simple'}
          </span>
          <span className="text-[13px] text-[var(--text-secondary)] max-w-[200px] truncate">{graphData.session_name}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <button className="flex items-center justify-center w-8 h-8 border border-[var(--border-color)] rounded-[6px] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] cursor-pointer transition-all hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                  onClick={() => setScale(s => Math.min(2.5, s + 0.15))}>+</button>
          <button className="flex items-center justify-center w-8 h-8 border border-[var(--border-color)] rounded-[6px] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] cursor-pointer transition-all hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                  onClick={() => setScale(s => Math.max(0.15, s - 0.15))}>−</button>
          <button className="py-1.5 px-3 text-[0.75rem] bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]" onClick={fetchGraph}>⟳ Reset</button>
        </div>
      </div>

      <div className="flex flex-1 min-h-0 overflow-hidden relative">
        {/* SVG Container */}
        <div ref={wrapperRef}
             className="flex-1 overflow-hidden cursor-grab active:cursor-grabbing select-none"
             style={{
               background: 'radial-gradient(circle at 50% 50%, rgba(59, 130, 246, 0.03) 0%, transparent 70%), linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)',
               backgroundSize: '100% 100%, 30px 30px, 30px 30px',
             }}
             onMouseDown={onWrapperMouseDown}
             onWheel={onWheel}>
          <svg width={svgW} height={svgH} viewBox={`0 0 ${svgW} ${svgH}`}
               style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`, transformOrigin: '0 0' }}>
            <defs>
              <marker id="arrow-n" markerWidth={L.arrowSize} markerHeight={L.arrowSize} refX={L.arrowSize} refY={L.arrowSize/2} orient="auto">
                <path d={`M0,0 L${L.arrowSize},${L.arrowSize/2} L0,${L.arrowSize} Z`} fill="#6b7280" />
              </marker>
              <marker id="arrow-c" markerWidth={L.arrowSize} markerHeight={L.arrowSize} refX={L.arrowSize} refY={L.arrowSize/2} orient="auto">
                <path d={`M0,0 L${L.arrowSize},${L.arrowSize/2} L0,${L.arrowSize} Z`} fill="#f59e0b" />
              </marker>
              <filter id="nshadow" x="-10%" y="-10%" width="130%" height="140%">
                <feDropShadow dx="0" dy="2" stdDeviation="3" floodOpacity="0.15" />
              </filter>
            </defs>

            {/* Edges */}
            <g>
              {graphData.edges.map((edge, idx) => {
                const src = positions[edge.source];
                const tgt = positions[edge.target];
                if (!src || !tgt) return null;
                const isCond = edge.conditional === true;
                const isBack = tgt.y < src.y;
                const srcNode = graphData.nodes.find(n => n.id === edge.source);
                const tgtNode = graphData.nodes.find(n => n.id === edge.target);

                let x1 = src.x, y1 = src.y, x2 = tgt.x, y2 = tgt.y;
                if (srcNode?.type === 'start' || srcNode?.type === 'end') y1 += L.startEndRadius;
                else y1 += (srcNode?.type === 'resilience' ? Math.round(L.nodeHeight * 0.8)/2 : L.nodeHeight/2);
                if (tgtNode?.type === 'start' || tgtNode?.type === 'end') y2 -= L.startEndRadius;
                else y2 -= (tgtNode?.type === 'resilience' ? Math.round(L.nodeHeight * 0.8)/2 : L.nodeHeight/2);

                if (isBack) {
                  const srcDims = srcNode?.type === 'resilience' ? Math.round(L.nodeWidth*0.78) : L.nodeWidth;
                  const tgtDims = tgtNode?.type === 'resilience' ? Math.round(L.nodeWidth*0.78) : L.nodeWidth;
                  x1 = src.x - srcDims/2; y1 = src.y;
                  x2 = tgt.x - tgtDims/2; y2 = tgt.y;
                }

                let d: string;
                if (isBack) {
                  d = `M${x1},${y1} C${x1-50},${y1} ${x2-50},${y2} ${x2},${y2}`;
                } else if (Math.abs(x2-x1) < 5) {
                  d = `M${x1},${y1} L${x2},${y2}`;
                } else {
                  const cpY = Math.min(y1, y2) + Math.abs(y2-y1)*0.4;
                  d = `M${x1},${y1} C${x1},${cpY} ${x2},${cpY} ${x2},${y2}`;
                }

                return (
                  <g key={idx}>
                    <path d={d} fill="none" stroke={isCond ? '#f59e0b' : '#6b7280'}
                          strokeWidth={isCond ? 1.5 : 1} strokeDasharray={isCond ? '6 3' : 'none'}
                          markerEnd={isCond ? 'url(#arrow-c)' : 'url(#arrow-n)'} opacity={0.6} />
                    {edge.label && (() => {
                      const mx = isBack ? Math.min(x1,x2)-40 : (x1+x2)/2;
                      const my = (y1+y2)/2;
                      return (
                        <>
                          <rect x={mx-edge.label.length*3.5-6} y={my-9} width={edge.label.length*7+12} height={18}
                                rx={4} fill="var(--bg-primary)" opacity={0.9} />
                          <text x={mx} y={my+4} textAnchor="middle" fontSize={10} fill={isCond ? '#f59e0b' : '#9ca3af'}>{edge.label}</text>
                        </>
                      );
                    })()}
                  </g>
                );
              })}
            </g>

            {/* Nodes */}
            <g>
              {graphData.nodes.map(node => {
                const pos = positions[node.id];
                if (!pos) return null;
                const isSelected = selectedNode?.id === node.id;
                const isRes = node.type === 'resilience';
                const nw = isRes ? Math.round(L.nodeWidth*0.78) : L.nodeWidth;
                const nh = isRes ? Math.round(L.nodeHeight*0.80) : L.nodeHeight;

                if (node.type === 'start' || node.type === 'end') {
                  return (
                    <g key={node.id} className="graph-node-g cursor-pointer" onClick={() => setSelectedNode(node)}>
                      <circle cx={pos.x} cy={pos.y} r={L.startEndRadius}
                              fill={getNodeFill(node)} stroke={isSelected ? '#3b82f6' : 'none'} strokeWidth={2}
                              filter="url(#nshadow)" />
                      <text x={pos.x} y={pos.y+5} textAnchor="middle" fontSize={12} fill="white" fontWeight="bold">{node.label}</text>
                    </g>
                  );
                }

                return (
                  <g key={node.id} className="graph-node-g cursor-pointer" onClick={() => setSelectedNode(node)}>
                    <rect x={pos.x-nw/2} y={pos.y-nh/2} width={nw} height={nh}
                          rx={isRes ? 8 : 12} ry={isRes ? 8 : 12}
                          fill={getNodeFill(node)} stroke={isSelected ? '#3b82f6' : getNodeStroke(node)}
                          strokeWidth={isSelected ? 2 : 1} filter="url(#nshadow)" />
                    <text x={pos.x-nw/2+(isRes?12:16)} y={pos.y+5} fontSize={12}>{NODE_ICONS[node.id] || '●'}</text>
                    <text x={pos.x+(isRes?2:6)} y={pos.y+5} textAnchor="middle" fontSize={isRes ? 10 : 11}
                          fill="#e5e7eb" fontWeight={isRes ? 'normal' : '500'}>{node.label}</text>
                    {node.prompt_template && (
                      <>
                        <circle cx={pos.x+nw/2-8} cy={pos.y-nh/2+8} r={6} fill="#3b82f6" />
                        <text x={pos.x+nw/2-8} y={pos.y-nh/2+11} textAnchor="middle" fontSize={8} fill="white" fontWeight="bold">P</text>
                      </>
                    )}
                  </g>
                );
              })}
            </g>
          </svg>
        </div>

      {/* Detail Panel */}
      {selectedNode && (
        <div className="w-[320px] border-l flex flex-col" style={{ background: '#141417', borderColor: '#27272a' }}>
          <div className="flex justify-between items-center px-4 py-3 border-b" style={{ borderColor: '#27272a' }}>
            <div className="flex items-center gap-2">
              <span className="text-[16px]">{NODE_ICONS[selectedNode.id] || '●'}</span>
              <h3 className="text-[0.875rem] font-semibold text-[var(--text-primary)]">{selectedNode.label}</h3>
            </div>
            <button className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer text-lg" style={{ width: '28px', height: '28px' }} onClick={() => setSelectedNode(null)}>×</button>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-4 text-[0.75rem]">
            {/* Badges */}
            <div className="flex flex-wrap gap-1">
              <span className="px-2 py-0.5 rounded bg-[var(--bg-tertiary)] text-[var(--text-muted)]">{selectedNode.type.toUpperCase()}</span>
              {selectedNode.metadata?.path && (
                <span className="px-2 py-0.5 rounded" style={{ background: getPathColor(selectedNode) + '20', color: getPathColor(selectedNode) }}>
                  {selectedNode.metadata.path.charAt(0).toUpperCase() + selectedNode.metadata.path.slice(1)} Path
                </span>
              )}
              {selectedNode.prompt_template && <span className="px-2 py-0.5 rounded bg-[var(--primary-color)]/20 text-[var(--primary-color)]">Has Prompt</span>}
            </div>

            {/* Description */}
            <div>
              <h4 className="font-semibold text-[var(--text-muted)] mb-1">Description</h4>
              <p className="text-[var(--text-secondary)]">{selectedNode.description}</p>
            </div>

            {/* Node ID */}
            <div>
              <h4 className="font-semibold text-[var(--text-muted)] mb-1">Node ID</h4>
              <code className="text-[var(--text-secondary)] bg-[var(--bg-tertiary)] px-2 py-0.5 rounded">{selectedNode.id}</code>
            </div>

            {/* Edges */}
            {graphData && (() => {
              const inEdges = graphData.edges.filter(e => e.target === selectedNode.id);
              const outEdges = graphData.edges.filter(e => e.source === selectedNode.id);
              return (
                <>
                  {inEdges.length > 0 && (
                    <div>
                      <h4 className="font-semibold text-[var(--text-muted)] mb-1">Incoming ({inEdges.length})</h4>
                      <div className="space-y-1">
                        {inEdges.map((e, i) => {
                          const srcN = graphData.nodes.find(n => n.id === e.source);
                          return (
                            <div key={i} className="flex items-center gap-1 px-2 py-1 rounded bg-[var(--bg-tertiary)] cursor-pointer hover:bg-[var(--bg-hover)]"
                                 onClick={() => { const n = graphData.nodes.find(n => n.id === e.source); if(n) setSelectedNode(n); }}>
                              <span className="text-[var(--text-muted)]">{srcN?.label || e.source}</span>
                              <span className="text-[var(--text-muted)]">→</span>
                              <span>{selectedNode.label}</span>
                              {e.label && <span className="text-[var(--warning-color)]">[{e.label}]</span>}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  {outEdges.length > 0 && (
                    <div>
                      <h4 className="font-semibold text-[var(--text-muted)] mb-1">Outgoing ({outEdges.length})</h4>
                      <div className="space-y-1">
                        {outEdges.map((e, i) => {
                          const tgtN = graphData.nodes.find(n => n.id === e.target);
                          return (
                            <div key={i} className="flex items-center gap-1 px-2 py-1 rounded bg-[var(--bg-tertiary)] cursor-pointer hover:bg-[var(--bg-hover)]"
                                 onClick={() => { const n = graphData.nodes.find(n => n.id === e.target); if(n) setSelectedNode(n); }}>
                              <span>{selectedNode.label}</span>
                              <span className="text-[var(--text-muted)]">→</span>
                              <span className="text-[var(--text-muted)]">{tgtN?.label || e.target}</span>
                              {e.label && <span className="text-[var(--warning-color)]">[{e.label}]</span>}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  {/* Condition map */}
                  {(() => {
                    const condEdge = outEdges.find(e => e.condition_map);
                    if (!condEdge?.condition_map) return null;
                    return (
                      <div>
                        <h4 className="font-semibold text-[var(--text-muted)] mb-1">Conditional Routing</h4>
                        <div className="space-y-1">
                          {Object.entries(condEdge.condition_map).map(([cond, target]) => {
                            const tn = graphData.nodes.find(n => n.id === target);
                            return (
                              <div key={cond} className="flex items-center gap-1 px-2 py-1 rounded bg-[var(--bg-tertiary)]">
                                <span className="text-[var(--warning-color)]">{cond}</span>
                                <span className="text-[var(--text-muted)]">→</span>
                                <span className="cursor-pointer hover:text-[var(--primary-color)]"
                                      onClick={() => { const n = graphData.nodes.find(n => n.id === target); if(n) setSelectedNode(n); }}>
                                  {tn?.label || target}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })()}
                </>
              );
            })()}

            {/* Prompt template */}
            {selectedNode.prompt_template && (
              <div>
                <h4 className="font-semibold text-[var(--text-muted)] mb-1">Prompt Template</h4>
                <pre className="p-2 rounded bg-[var(--bg-tertiary)] text-[var(--text-secondary)] whitespace-pre-wrap font-mono text-[10px] max-h-[200px] overflow-y-auto">
                  {selectedNode.prompt_template}
                </pre>
              </div>
            )}

            {/* Metadata */}
            {selectedNode.metadata && (() => {
              const displayMeta = { ...selectedNode.metadata };
              delete displayMeta.path;
              delete displayMeta.inner_graph;
              if (Object.keys(displayMeta).length === 0) return null;
              return (
                <div>
                  <h4 className="font-semibold text-[var(--text-muted)] mb-1">Metadata</h4>
                  <pre className="p-2 rounded bg-[var(--bg-tertiary)] text-[var(--text-secondary)] whitespace-pre-wrap font-mono text-[10px]">
                    {JSON.stringify(displayMeta, null, 2)}
                  </pre>
                </div>
              );
            })()}

            {/* Inner graph */}
            {selectedNode.metadata?.inner_graph && (
              <div>
                <h4 className="font-semibold text-[var(--text-muted)] mb-1">Inner Graph</h4>
                <p className="text-[var(--text-secondary)] mb-2">{selectedNode.metadata.inner_graph.description}</p>
                <div className="flex flex-wrap gap-1">
                  {selectedNode.metadata.inner_graph.nodes.map((n: any, i: number) => (
                    <span key={i} className={`px-2 py-0.5 rounded text-[10px] ${n.type === 'start' || n.type === 'end' ? 'text-[var(--primary-color)]' : 'bg-[var(--bg-tertiary)] text-[var(--text-secondary)]'}`}
                          style={n.type === 'start' || n.type === 'end' ? { background: 'rgba(59, 130, 246, 0.2)' } : {}}>
                      {n.label}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      </div>
    </div>
  );
}
