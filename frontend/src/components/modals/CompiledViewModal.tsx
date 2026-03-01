'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { workflowApi } from '@/lib/workflowApi';
import { useI18n } from '@/lib/i18n';
import { NodeIcon } from '@/components/workflow/icons';
import { Search, X, ArrowRight, AlertTriangle, Diamond, Code2, Database } from 'lucide-react';
import type { CompileViewResponse, CompileViewNodeDetail, CompileViewEdgeDetail, StateFieldUsage, NodeStateMapping } from '@/types/workflow';

interface Props {
  workflowId: string;
  workflowName: string;
  onClose: () => void;
}

type TabId = 'code' | 'nodes' | 'edges' | 'state';

export default function CompiledViewModal({ workflowId, workflowName, onClose }: Props) {
  const { t } = useI18n();
  const [data, setData] = useState<CompileViewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<TabId>('state');
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    let cancelled = false;
    workflowApi.compileView(workflowId)
      .then(res => { if (!cancelled) setData(res); })
      .catch(e => { if (!cancelled) setError(e.message || 'Failed to load compiled view'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [workflowId]);

  const toggleNode = useCallback((id: string) => {
    setExpandedNodes(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const handleCopyCode = useCallback(() => {
    if (data?.code) navigator.clipboard.writeText(data.code);
  }, [data]);

  // Filter nodes/edges by search
  const filteredNodes = useMemo(() => {
    if (!data || !searchQuery.trim()) return data?.nodes ?? [];
    const q = searchQuery.toLowerCase();
    return data.nodes.filter(n =>
      n.label.toLowerCase().includes(q) ||
      n.node_type.toLowerCase().includes(q) ||
      n.id.toLowerCase().includes(q) ||
      n.description?.toLowerCase().includes(q)
    );
  }, [data, searchQuery]);

  const filteredEdges = useMemo(() => {
    if (!data || !searchQuery.trim()) return data?.edges ?? [];
    const q = searchQuery.toLowerCase();
    return data.edges.filter(e =>
      e.source_label?.toLowerCase().includes(q) ||
      (e.target_label?.toLowerCase().includes(q)) ||
      e.description?.toLowerCase().includes(q) ||
      e.wiring?.toLowerCase().includes(q)
    );
  }, [data, searchQuery]);

  const filteredStateFields = useMemo(() => {
    if (!data?.state?.fields) return [];
    if (!searchQuery.trim()) return data.state.fields;
    const q = searchQuery.toLowerCase();
    return data.state.fields.filter((f: StateFieldUsage) =>
      f.name.toLowerCase().includes(q) ||
      f.description?.toLowerCase().includes(q) ||
      f.category?.toLowerCase().includes(q) ||
      f.type?.toLowerCase().includes(q) ||
      f.read_by?.some((n: string) => n.toLowerCase().includes(q)) ||
      f.written_by?.some((n: string) => n.toLowerCase().includes(q))
    );
  }, [data, searchQuery]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-xl w-[95vw] max-w-[1100px] h-[88vh] flex flex-col shadow-[0_25px_60px_rgba(0,0,0,0.5)]"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between py-3 px-5 border-b border-[var(--border-color)] shrink-0">
          <div className="flex items-center gap-3">
            <Search size={18} className="text-[var(--text-muted)]" />
            <div>
              <h3 className="text-[0.9375rem] font-semibold text-[var(--text-primary)]">
                {t('compiledView.title')}
              </h3>
              <p className="text-[0.6875rem] text-[var(--text-muted)]">
                {workflowName}
                {data?.summary && (
                  <> · {data.summary.total_nodes} {t('compiledView.nodes')} · {data.summary.total_edges} {t('compiledView.edges')} · {data.summary.state_fields_used ?? 0}/{data.summary.state_fields_total ?? 0} {t('compiledView.stateFields')}</>
                )}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Validation badge */}
            {data?.validation && (
              <span className={`text-[10px] font-semibold py-0.5 px-2 rounded-md border uppercase tracking-wide ${
                data.validation.valid
                  ? 'bg-[rgba(34,197,94,0.08)] text-[#4ade80] border-[rgba(34,197,94,0.2)]'
                  : 'bg-[rgba(239,68,68,0.08)] text-[#f87171] border-[rgba(239,68,68,0.2)]'
              }`}>
                {data.validation.valid ? t('compiledView.valid') : t('compiledView.invalid')}
              </span>
            )}
            <button
              className="flex items-center justify-center w-8 h-8 rounded-lg bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer"
              onClick={onClose}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Tabs + Search */}
        <div className="flex items-center gap-2 px-5 pt-3 pb-2 border-b border-[var(--border-color)] shrink-0">
          <div className="flex gap-1">
            {(['state', 'nodes', 'edges', 'code'] as TabId[]).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-3 py-1.5 text-[11px] font-medium rounded-md border transition-colors ${
                  activeTab === tab
                    ? 'bg-[rgba(59,130,246,0.12)] text-[var(--primary-color)] border-[rgba(59,130,246,0.3)]'
                    : 'bg-transparent text-[var(--text-muted)] border-transparent hover:text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]'
                }`}
              >
                {tab === 'state' ? <><Database size={11} className="inline -mt-px mr-1" />{t('compiledView.tabState')}</> :
                 tab === 'nodes' ? <><Diamond size={11} className="inline -mt-px mr-1" />{t('compiledView.tabNodes')}</> :
                 tab === 'edges' ? <><ArrowRight size={11} className="inline -mt-px mr-1" />{t('compiledView.tabEdges')}</> :
                 <><Code2 size={11} className="inline -mt-px mr-1" />{t('compiledView.tabCode')}</>}
              </button>
            ))}
          </div>
          <div className="flex-1" />
          {activeTab !== 'code' && (
            <input
              type="text"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder={t('compiledView.search')}
              className="h-7 w-[200px] px-2.5 text-[11px] bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)]"
            />
          )}
          {activeTab === 'code' && (
            <button
              onClick={handleCopyCode}
              className="inline-flex items-center gap-1 h-7 px-2.5 text-[11px] font-medium rounded-md border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-primary)] hover:text-[var(--text-primary)] transition-colors"
            >
              <NodeIcon name="copy" size={12} />
              {t('compiledView.copyCode')}
            </button>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-h-0 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-full text-[var(--text-muted)] text-[0.875rem] animate-pulse">
              {t('compiledView.loading')}
            </div>
          ) : error ? (
            <div className="flex items-center justify-center h-full text-[var(--danger-color)] text-[0.875rem]">
              <AlertTriangle size={14} className="inline -mt-px mr-1" /> {error}
            </div>
          ) : data ? (
            <>
              {activeTab === 'code' && <CodeView code={data.code} />}
              {activeTab === 'nodes' && (
                <NodesView
                  nodes={filteredNodes}
                  expandedNodes={expandedNodes}
                  toggleNode={toggleNode}
                />
              )}
              {activeTab === 'edges' && <EdgesView edges={filteredEdges} />}
              {activeTab === 'state' && data.state && (
                <StateView
                  fields={filteredStateFields}
                  perNode={data.state.per_node ?? []}
                  summary={data.state.summary}
                />
              )}
            </>
          ) : null}
        </div>

        {/* Footer — Summary */}
        {data?.summary && (
          <div className="flex items-center gap-4 px-5 py-2.5 border-t border-[var(--border-color)] shrink-0 text-[10px] text-[var(--text-muted)]">
            <span>{t('compiledView.summaryNodes', { count: data.summary.total_nodes })}</span>
            <span>{t('compiledView.summaryEdges', { count: data.summary.total_edges })}</span>
            <span>{t('compiledView.summaryConditional', { count: data.summary.conditional_edges })}</span>
            <span>{t('compiledView.summarySimple', { count: data.summary.simple_edges })}</span>
            <span>{t('compiledView.summaryState', { used: data.summary.state_fields_used ?? 0, total: data.summary.state_fields_total ?? 0 })}</span>
            {!data.validation.valid && (
              <span className="text-[var(--danger-color)]">
                {t('compiledView.summaryErrors', { count: data.validation.errors.length })}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}


// ════════════════════════════════════════════════════════════
// Code Tab — syntax-highlighted Python pseudo-code
// ════════════════════════════════════════════════════════════

function CodeView({ code }: { code: string }) {
  const lines = useMemo(() => code.split('\n'), [code]);

  return (
    <div className="h-full overflow-auto">
      <pre className="px-5 py-4 text-[12px] leading-[1.7] font-mono text-[var(--text-primary)] whitespace-pre overflow-x-auto">
        {lines.map((line, i) => (
          <CodeLine key={i} lineNo={i + 1} text={line} />
        ))}
      </pre>
    </div>
  );
}

function CodeLine({ lineNo, text }: { lineNo: number; text: string }) {
  const colored = useMemo(() => highlightPython(text), [text]);
  return (
    <div className="flex hover:bg-[rgba(255,255,255,0.02)]">
      <span className="w-[3.5em] text-right pr-4 text-[var(--text-muted)] select-none opacity-50 shrink-0">
        {lineNo}
      </span>
      <span dangerouslySetInnerHTML={{ __html: colored }} />
    </div>
  );
}

function highlightPython(line: string): string {
  if (!line.trim()) return '&nbsp;';

  // Full comment lines
  if (line.trimStart().startsWith('#')) {
    return `<span style="color:#6b7280;font-style:italic">${esc(line)}</span>`;
  }

  // Tokenize first so string/comment highlighting never collides with injected HTML
  const tokens: { text: string; kind: 'code' | 'string' | 'comment' }[] = [];
  let idx = 0;
  while (idx < line.length) {
    // Comment — rest of line
    if (line[idx] === '#') {
      tokens.push({ text: line.slice(idx), kind: 'comment' });
      break;
    }
    // String literal
    if (line[idx] === '"' || line[idx] === "'") {
      const q = line[idx];
      let end = idx + 1;
      while (end < line.length) {
        if (line[end] === '\\') { end += 2; continue; }
        if (line[end] === q) { end++; break; }
        end++;
      }
      tokens.push({ text: line.slice(idx, end), kind: 'string' });
      idx = end;
      continue;
    }
    // Plain code — consume until next string or comment boundary
    let end = idx + 1;
    while (end < line.length && line[end] !== '#' && line[end] !== '"' && line[end] !== "'") end++;
    tokens.push({ text: line.slice(idx, end), kind: 'code' });
    idx = end;
  }

  return tokens.map(t => {
    if (t.kind === 'comment')
      return `<span style="color:#6b7280;font-style:italic">${esc(t.text)}</span>`;
    if (t.kind === 'string')
      return `<span style="color:#4ade80">${esc(t.text)}</span>`;

    // Code token — single-pass tokenisation so injected HTML is never re-matched
    return highlightCodeSegment(t.text);
  }).join('');
}

const KW_SET = new Set([
  'from','import','def','return','if','elif','else','in','not',
  'and','or','await','async','class','for','True','False','None',
]);

/**
 * Highlight a code segment in a single pass — never injects HTML then
 * re-scans, so nested-match bugs are structurally impossible.
 */
function highlightCodeSegment(code: string): string {
  // Match keywords, graph API calls (longest first), or numbers in one alternation.
  // Capture groups: 1=graph API (multi-word), 2=word, 3=number
  const pattern =
    /\b(graph\.add_conditional_edges|graph\.add_node|graph\.add_edge|graph\.compile|StateGraph|CompiledStateGraph|START|END)\b|\b([a-zA-Z_]\w*)\b|\b(\d+)\b/g;

  let result = '';
  let lastIndex = 0;
  let m: RegExpExecArray | null;

  while ((m = pattern.exec(code)) !== null) {
    // Text before this match (operators, parens, etc.)
    if (m.index > lastIndex) result += esc(code.slice(lastIndex, m.index));

    if (m[1]) {
      // Graph API token
      result += `<span style="color:#60a5fa;font-weight:bold">${esc(m[1])}</span>`;
    } else if (m[2]) {
      // Identifier — check if it's a keyword
      if (KW_SET.has(m[2])) {
        result += `<span style="color:#c084fc">${esc(m[2])}</span>`;
      } else {
        result += esc(m[2]);
      }
    } else if (m[3]) {
      // Number literal
      result += `<span style="color:#fbbf24">${esc(m[3])}</span>`;
    }

    lastIndex = pattern.lastIndex;
  }

  // Remaining tail
  if (lastIndex < code.length) result += esc(code.slice(lastIndex));
  return result;
}

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}


// ════════════════════════════════════════════════════════════
// Nodes Tab
// ════════════════════════════════════════════════════════════

function NodesView({
  nodes,
  expandedNodes,
  toggleNode,
}: {
  nodes: CompileViewNodeDetail[];
  expandedNodes: Set<string>;
  toggleNode: (id: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="px-5 py-4 space-y-2">
      {nodes.map(node => {
        const isExpanded = expandedNodes.has(node.id);
        const roleColor = node.role === 'conditional'
          ? 'text-[#f59e0b]'
          : node.role === 'pseudo'
            ? 'text-[var(--text-muted)]'
            : 'text-[#60a5fa]';

        return (
          <div
            key={node.id}
            className="border border-[var(--border-color)] rounded-lg bg-[var(--bg-primary)] overflow-hidden"
          >
            {/* Node header */}
            <button
              onClick={() => toggleNode(node.id)}
              className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-[var(--bg-tertiary)] transition-colors cursor-pointer bg-transparent border-none"
            >
              <NodeIcon name={isExpanded ? 'chevron-down' : 'chevron-right'} size={10} className="opacity-40 w-3" />
              <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">
                {node.label}
              </span>
              <span className="text-[10px] font-mono text-[var(--text-muted)] bg-[var(--bg-secondary)] px-1.5 py-0.5 rounded">
                {node.id}
              </span>
              <span className={`text-[10px] font-semibold uppercase tracking-wide ${roleColor}`}>
                {node.role}
              </span>
              {node.is_conditional && (
                <span className="text-[10px] font-semibold py-0.5 px-1.5 rounded-md bg-[rgba(245,158,11,0.1)] text-[#f59e0b] border border-[rgba(245,158,11,0.2)]">
                  {t('compiledView.conditional')}
                </span>
              )}
              <span className="text-[10px] text-[var(--text-muted)] ml-auto font-mono">
                {node.node_type}
              </span>
            </button>

            {/* Expanded detail */}
            {isExpanded && (
              <div className="px-4 pb-3 pt-1 border-t border-[var(--border-color)] space-y-3">
                {/* Description */}
                <p className="text-[0.75rem] text-[var(--text-secondary)] leading-relaxed">
                  {node.description}
                </p>

                {/* Output Ports */}
                {node.output_ports && node.output_ports.length > 0 && (
                  <div>
                    <h5 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wide mb-1">
                      {t('compiledView.outputPorts')}
                    </h5>
                    <div className="flex flex-wrap gap-1.5">
                      {node.output_ports.map(port => (
                        <span
                          key={port.id}
                          className="text-[10px] font-mono py-0.5 px-2 rounded-md bg-[var(--bg-secondary)] text-[var(--text-secondary)] border border-[var(--border-color)]"
                          title={port.description}
                        >
                          {port.id} <ArrowRight size={10} className="inline mx-0.5" /> {port.label}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Routing Logic */}
                {node.routing_logic && (
                  <div>
                    <h5 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wide mb-1">
                      {t('compiledView.routingLogic')}
                    </h5>
                    <pre className="text-[11px] font-mono text-[var(--text-secondary)] bg-[var(--bg-secondary)] rounded-md p-2.5 whitespace-pre-wrap leading-relaxed border border-[var(--border-color)]">
                      {node.routing_logic}
                    </pre>
                  </div>
                )}

                {/* Targets */}
                {node.targets && node.targets.length > 0 && (
                  <div>
                    <h5 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wide mb-1">
                      {t('compiledView.targets')}
                    </h5>
                    <div className="space-y-1">
                      {node.targets.map((tgt, i) => (
                        <div key={i} className="flex items-center gap-2 text-[11px]">
                          <span className="font-mono text-[#f59e0b] bg-[rgba(245,158,11,0.08)] px-1.5 py-0.5 rounded">
                            {tgt.port}
                          </span>
                          <ArrowRight size={10} className="text-[var(--text-muted)]" />
                          <span className="font-semibold text-[var(--text-primary)]">{tgt.target_label}</span>
                          {tgt.label && (
                            <span className="text-[var(--text-muted)]">({tgt.label})</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Config */}
                {node.config && Object.keys(node.config).length > 0 && (
                  <div>
                    <h5 className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wide mb-1">
                      {t('compiledView.config')}
                    </h5>
                    <div className="grid grid-cols-1 gap-0.5">
                      {Object.entries(node.config).map(([key, val]) => (
                        <div key={key} className="flex gap-2 text-[11px] font-mono">
                          <span className="text-[#c084fc] shrink-0">{key}:</span>
                          <span className="text-[var(--text-secondary)] truncate" title={String(val)}>
                            {typeof val === 'string' && val.startsWith('(default:')
                              ? <span className="opacity-50">{val}</span>
                              : String(val).length > 80 ? String(val).slice(0, 80) + '…' : String(val)
                            }
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}


// ════════════════════════════════════════════════════════════
// Edges Tab
// ════════════════════════════════════════════════════════════

function EdgesView({ edges }: { edges: CompileViewEdgeDetail[] }) {
  const { t } = useI18n();
  return (
    <div className="px-5 py-4 space-y-2">
      {edges.map((edge, i) => {
        const isConditional = edge.wiring === 'conditional';
        const wiringColor = isConditional
          ? 'bg-[rgba(245,158,11,0.08)] text-[#f59e0b] border-[rgba(245,158,11,0.2)]'
          : edge.wiring === 'start'
            ? 'bg-[rgba(34,197,94,0.08)] text-[#4ade80] border-[rgba(34,197,94,0.2)]'
            : 'bg-[rgba(59,130,246,0.08)] text-[#60a5fa] border-[rgba(59,130,246,0.2)]';

        return (
          <div
            key={i}
            className="border border-[var(--border-color)] rounded-lg bg-[var(--bg-primary)] px-4 py-3"
          >
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-[10px] font-semibold py-0.5 px-1.5 rounded-md border uppercase tracking-wide ${wiringColor}`}>
                {edge.wiring}
              </span>
              <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">
                {edge.source_label}
              </span>
              {!isConditional && (
                <>
                  <ArrowRight size={12} className="text-[var(--text-muted)]" />
                  <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">
                    {edge.target_label}
                  </span>
                  {edge.port && edge.port !== 'default' && (
                    <span className="text-[10px] font-mono text-[var(--text-muted)] bg-[var(--bg-secondary)] px-1.5 py-0.5 rounded">
                      port: {edge.port}
                    </span>
                  )}
                </>
              )}
              {isConditional && edge.has_routing_function && (
                <span className="text-[10px] font-mono text-[#c084fc] bg-[rgba(192,132,252,0.08)] px-1.5 py-0.5 rounded border border-[rgba(192,132,252,0.2)]">
                  {t('compiledView.hasRouter')}
                </span>
              )}
            </div>

            {/* Conditional branches */}
            {isConditional && edge.branches && (
              <div className="mt-2 ml-4 space-y-1">
                {edge.branches.map((br, j) => (
                  <div key={j} className="flex items-center gap-2 text-[11px]">
                    <span className="font-mono text-[#f59e0b] bg-[rgba(245,158,11,0.08)] px-1.5 py-0.5 rounded">
                      {br.port}
                    </span>
                    <ArrowRight size={10} className="text-[var(--text-muted)]" />
                    <span className="font-semibold text-[var(--text-primary)]">{br.target_label}</span>
                    {br.label && (
                      <span className="text-[var(--text-muted)]">({br.label})</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}


// ════════════════════════════════════════════════════════════
// State Tab — state field analysis with category grouping
// ════════════════════════════════════════════════════════════

const CATEGORY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  core:     { bg: 'rgba(59,130,246,0.08)',  text: '#60a5fa', border: 'rgba(59,130,246,0.2)'  },
  task:     { bg: 'rgba(245,158,11,0.08)',  text: '#f59e0b', border: 'rgba(245,158,11,0.2)'  },
  memory:   { bg: 'rgba(168,85,247,0.08)',  text: '#c084fc', border: 'rgba(168,85,247,0.2)'  },
  control:  { bg: 'rgba(34,197,94,0.08)',   text: '#4ade80', border: 'rgba(34,197,94,0.2)'   },
  output:   { bg: 'rgba(236,72,153,0.08)',  text: '#f472b6', border: 'rgba(236,72,153,0.2)'  },
  metadata: { bg: 'rgba(148,163,184,0.08)', text: '#94a3b8', border: 'rgba(148,163,184,0.2)' },
};

function getCategoryStyle(category: string) {
  return CATEGORY_COLORS[category] ?? CATEGORY_COLORS.metadata;
}

const REDUCER_LABELS: Record<string, string> = {
  last_wins: 'Last Wins',
  append: 'Append',
  merge_by_id: 'Merge by ID',
  deduplicate: 'Deduplicate',
};

function StateView({
  fields,
  perNode,
  summary,
}: {
  fields: StateFieldUsage[];
  perNode: NodeStateMapping[];
  summary?: { total_builtin: number; used_count: number; unused_count: number; custom_count: number };
}) {
  const { t } = useI18n();
  const [viewMode, setViewMode] = useState<'fields' | 'nodes'>('fields');
  const [usageFilter, setUsageFilter] = useState<'all' | 'used' | 'unused'>('all');

  const toggleUsageFilter = useCallback((filter: 'used' | 'unused') => {
    setUsageFilter(prev => prev === filter ? 'all' : filter);
  }, []);

  // Apply usage filter then group by category
  const visibleFields = useMemo(() => {
    if (usageFilter === 'all') return fields;
    return fields.filter(f => usageFilter === 'used' ? f.is_used : !f.is_used);
  }, [fields, usageFilter]);

  const fieldsByCategory = useMemo(() => {
    const map = new Map<string, StateFieldUsage[]>();
    for (const f of visibleFields) {
      const cat = f.category || 'metadata';
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(f);
    }
    return map;
  }, [visibleFields]);

  return (
    <div className="px-5 py-4 space-y-4">
      {/* Summary bar */}
      {summary && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
            {t('compiledView.stateSummary')}
          </span>
          <span className="text-[11px] font-mono py-0.5 px-2 rounded-md bg-[rgba(59,130,246,0.08)] text-[#60a5fa] border border-[rgba(59,130,246,0.2)]">
            {t('compiledView.stateBuiltIn')}: {summary.total_builtin}
          </span>
          <button
            onClick={() => toggleUsageFilter('used')}
            className={`text-[11px] font-mono py-0.5 px-2 rounded-md border cursor-pointer transition-all ${
              usageFilter === 'used'
                ? 'bg-[rgba(34,197,94,0.2)] text-[#4ade80] border-[rgba(34,197,94,0.5)] ring-1 ring-[rgba(34,197,94,0.3)]'
                : 'bg-[rgba(34,197,94,0.08)] text-[#4ade80] border-[rgba(34,197,94,0.2)] hover:bg-[rgba(34,197,94,0.14)]'
            }`}
          >
            {t('compiledView.stateUsed')}: {summary.used_count}
          </button>
          {summary.unused_count > 0 && (
            <button
              onClick={() => toggleUsageFilter('unused')}
              className={`text-[11px] font-mono py-0.5 px-2 rounded-md border cursor-pointer transition-all ${
                usageFilter === 'unused'
                  ? 'bg-[rgba(148,163,184,0.2)] text-[#94a3b8] border-[rgba(148,163,184,0.5)] ring-1 ring-[rgba(148,163,184,0.3)]'
                  : 'bg-[rgba(148,163,184,0.08)] text-[#94a3b8] border-[rgba(148,163,184,0.2)] hover:bg-[rgba(148,163,184,0.14)]'
              }`}
            >
              {t('compiledView.stateUnused')}: {summary.unused_count}
            </button>
          )}
          {summary.custom_count > 0 && (
            <span className="text-[11px] font-mono py-0.5 px-2 rounded-md bg-[rgba(236,72,153,0.08)] text-[#f472b6] border border-[rgba(236,72,153,0.2)]">
              {t('compiledView.stateCustom')}: {summary.custom_count}
            </span>
          )}
          <div className="flex-1" />
          {/* View mode toggle */}
          <div className="flex gap-0.5 bg-[var(--bg-primary)] rounded-md border border-[var(--border-color)] p-0.5">
            <button
              onClick={() => setViewMode('fields')}
              className={`px-2 py-0.5 text-[10px] font-medium rounded cursor-pointer border-none transition-colors ${
                viewMode === 'fields'
                  ? 'bg-[rgba(59,130,246,0.12)] text-[var(--primary-color)]'
                  : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
              }`}
            >
              {t('compiledView.stateByField')}
            </button>
            <button
              onClick={() => setViewMode('nodes')}
              className={`px-2 py-0.5 text-[10px] font-medium rounded cursor-pointer border-none transition-colors ${
                viewMode === 'nodes'
                  ? 'bg-[rgba(59,130,246,0.12)] text-[var(--primary-color)]'
                  : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
              }`}
            >
              {t('compiledView.stateByNode')}
            </button>
          </div>
        </div>
      )}

      {/* ─── Fields View ─── */}
      {viewMode === 'fields' && (
        <div className="space-y-4">
          {Array.from(fieldsByCategory.entries()).map(([category, catFields]) => {
            const style = getCategoryStyle(category);
            return (
              <div key={category}>
                {/* Category header */}
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className="text-[10px] font-semibold uppercase tracking-wide py-0.5 px-2 rounded-md border"
                    style={{ backgroundColor: style.bg, color: style.text, borderColor: style.border }}
                  >
                    {category}
                  </span>
                  <span className="text-[10px] text-[var(--text-muted)]">
                    {catFields.length} {catFields.length === 1 ? 'field' : 'fields'}
                  </span>
                </div>

                {/* Field cards */}
                <div className="space-y-1.5">
                  {catFields.map(field => (
                    <StateFieldCard key={field.name} field={field} />
                  ))}
                </div>
              </div>
            );
          })}
          {fields.length === 0 && (
            <p className="text-center text-[var(--text-muted)] text-[0.8125rem] py-8">
              {t('compiledView.stateNoFields')}
            </p>
          )}
        </div>
      )}

      {/* ─── Per-Node View ─── */}
      {viewMode === 'nodes' && (
        <div className="space-y-2">
          {perNode.map(node => (
            <div
              key={node.node_id}
              className="border border-[var(--border-color)] rounded-lg bg-[var(--bg-primary)] px-4 py-3"
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">
                  {node.node_label}
                </span>
                <span className="text-[10px] font-mono text-[var(--text-muted)] bg-[var(--bg-secondary)] px-1.5 py-0.5 rounded">
                  {node.node_type}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {/* Reads */}
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--text-muted)] block mb-1">
                    {t('compiledView.stateReads')}
                  </span>
                  <div className="flex flex-wrap gap-1">
                    {node.reads.length > 0 ? node.reads.map(r => (
                      <span key={r} className="text-[10px] font-mono py-0.5 px-1.5 rounded bg-[rgba(59,130,246,0.08)] text-[#60a5fa] border border-[rgba(59,130,246,0.15)]">
                        {r}
                      </span>
                    )) : (
                      <span className="text-[10px] text-[var(--text-muted)] italic">—</span>
                    )}
                  </div>
                </div>
                {/* Writes */}
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--text-muted)] block mb-1">
                    {t('compiledView.stateWrites')}
                  </span>
                  <div className="flex flex-wrap gap-1">
                    {node.writes.length > 0 ? node.writes.map(w => (
                      <span key={w} className="text-[10px] font-mono py-0.5 px-1.5 rounded bg-[rgba(245,158,11,0.08)] text-[#f59e0b] border border-[rgba(245,158,11,0.15)]">
                        {w}
                      </span>
                    )) : (
                      <span className="text-[10px] text-[var(--text-muted)] italic">—</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          ))}
          {perNode.length === 0 && (
            <p className="text-center text-[var(--text-muted)] text-[0.8125rem] py-8">
              {t('compiledView.stateNoNodes')}
            </p>
          )}
        </div>
      )}
    </div>
  );
}


/** Individual state field card with read/write node lists. */
function StateFieldCard({ field }: { field: StateFieldUsage }) {
  const { t } = useI18n();
  const style = getCategoryStyle(field.category);
  const reducerLabel = REDUCER_LABELS[field.reducer] ?? field.reducer;

  return (
    <div
      className={`border rounded-lg px-4 py-2.5 transition-colors ${
        field.is_used
          ? 'border-[var(--border-color)] bg-[var(--bg-primary)]'
          : 'border-[var(--border-color)] bg-[var(--bg-primary)] opacity-50'
      }`}
    >
      {/* Top row: name, type, badges */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[0.8125rem] font-semibold font-mono text-[var(--text-primary)]">
          {field.name}
        </span>
        <span className="text-[10px] font-mono text-[var(--text-muted)] bg-[var(--bg-secondary)] px-1.5 py-0.5 rounded">
          {field.type}
        </span>
        <span
          className="text-[10px] font-semibold py-0.5 px-1.5 rounded-md border uppercase tracking-wide"
          style={{ backgroundColor: style.bg, color: style.text, borderColor: style.border }}
        >
          {field.category}
        </span>
        {field.reducer && field.reducer !== 'last_wins' && (
          <span className="text-[10px] font-mono py-0.5 px-1.5 rounded-md bg-[rgba(168,85,247,0.08)] text-[#c084fc] border border-[rgba(168,85,247,0.2)]">
            ⟳ {reducerLabel}
          </span>
        )}
        {!field.is_used && (
          <span className="text-[10px] font-semibold py-0.5 px-1.5 rounded-md bg-[rgba(148,163,184,0.08)] text-[#94a3b8] border border-[rgba(148,163,184,0.2)] uppercase tracking-wide">
            {t('compiledView.stateUnusedBadge')}
          </span>
        )}
        {!field.is_builtin && (
          <span className="text-[10px] font-semibold py-0.5 px-1.5 rounded-md bg-[rgba(236,72,153,0.08)] text-[#f472b6] border border-[rgba(236,72,153,0.2)] uppercase tracking-wide">
            {t('compiledView.stateCustomBadge')}
          </span>
        )}
      </div>

      {/* Description */}
      <p className="text-[0.6875rem] text-[var(--text-secondary)] mt-1 leading-relaxed">
        {field.description}
      </p>

      {/* Read/Write nodes */}
      {(field.read_by.length > 0 || field.written_by.length > 0) && (
        <div className="flex gap-4 mt-2">
          {field.read_by.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap">
              <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wide mr-0.5">
                {t('compiledView.stateReadBy')}
              </span>
              {field.read_by.map(n => (
                <span key={n} className="text-[10px] font-mono py-0.5 px-1.5 rounded bg-[rgba(59,130,246,0.06)] text-[#60a5fa] border border-[rgba(59,130,246,0.12)]">
                  {n}
                </span>
              ))}
            </div>
          )}
          {field.written_by.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap">
              <span className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wide mr-0.5">
                {t('compiledView.stateWrittenBy')}
              </span>
              {field.written_by.map(n => (
                <span key={n} className="text-[10px] font-mono py-0.5 px-1.5 rounded bg-[rgba(245,158,11,0.06)] text-[#f59e0b] border border-[rgba(245,158,11,0.12)]">
                  {n}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
