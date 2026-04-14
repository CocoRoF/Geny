'use client';

import { useMemo } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { Layers, Zap, Brain, Shield, Database, Wrench, BarChart3, MessageSquare } from 'lucide-react';

/**
 * Pipeline Visualization Tab
 *
 * Shows the geny-executor 16-stage Pipeline structure for the
 * currently selected session. Replaces the old workflow node graph.
 */

const PIPELINE_STAGES = [
  { id: 's01', name: 'Input', icon: MessageSquare, category: 'ingress', desc: 'Validate & normalize input' },
  { id: 's02', name: 'Context', icon: Database, category: 'ingress', desc: 'Load history & memory' },
  { id: 's03', name: 'System', icon: Brain, category: 'ingress', desc: 'Build system prompt' },
  { id: 's04', name: 'Guard', icon: Shield, category: 'preflight', desc: 'Budget & safety checks' },
  { id: 's05', name: 'Cache', icon: Zap, category: 'preflight', desc: 'Prompt caching optimization' },
  { id: 's06', name: 'API', icon: Zap, category: 'execution', desc: 'Call Anthropic API' },
  { id: 's07', name: 'Token', icon: BarChart3, category: 'execution', desc: 'Track token usage & cost' },
  { id: 's08', name: 'Think', icon: Brain, category: 'execution', desc: 'Extended thinking blocks' },
  { id: 's09', name: 'Parse', icon: Layers, category: 'execution', desc: 'Parse response & signals' },
  { id: 's10', name: 'Tool', icon: Wrench, category: 'execution', desc: 'Execute tool calls' },
  { id: 's11', name: 'Agent', icon: MessageSquare, category: 'execution', desc: 'Multi-agent orchestration' },
  { id: 's12', name: 'Evaluate', icon: BarChart3, category: 'decision', desc: 'Quality & completion check' },
  { id: 's13', name: 'Loop', icon: Zap, category: 'decision', desc: 'Continue or finish' },
  { id: 's14', name: 'Emit', icon: MessageSquare, category: 'egress', desc: 'Output to consumers' },
  { id: 's15', name: 'Memory', icon: Database, category: 'egress', desc: 'Persist conversation' },
  { id: 's16', name: 'Yield', icon: Layers, category: 'egress', desc: 'Format final result' },
];

const CATEGORY_COLORS: Record<string, string> = {
  ingress: 'bg-blue-500/10 border-blue-500/30 text-blue-400',
  preflight: 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400',
  execution: 'bg-green-500/10 border-green-500/30 text-green-400',
  decision: 'bg-purple-500/10 border-purple-500/30 text-purple-400',
  egress: 'bg-orange-500/10 border-orange-500/30 text-orange-400',
};

const CATEGORY_LABELS: Record<string, string> = {
  ingress: 'Ingress',
  preflight: 'Pre-flight',
  execution: 'Execution (Loop)',
  decision: 'Decision',
  egress: 'Egress',
};

const PRESET_LABELS: Record<string, { label: string; desc: string }> = {
  'worker_adaptive': {
    label: 'Worker Adaptive',
    desc: 'Binary classify (easy/not_easy) + autonomous execution',
  },
  'worker_easy': {
    label: 'Worker Easy',
    desc: 'Single-turn Q&A with memory context',
  },
  'vtuber': {
    label: 'VTuber',
    desc: 'Conversational agent with persona & memory reflection',
  },
};

export default function GraphTab() {
  const { selectedSessionId, sessions } = useAppStore();

  const session = useMemo(
    () => sessions.find(s => s.session_id === selectedSessionId),
    [sessions, selectedSessionId],
  );

  if (!session) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-500">
        Select a session to view pipeline
      </div>
    );
  }

  // Determine preset from workflow_id
  const workflowId = session.workflow_id || '';
  let presetKey = 'worker_adaptive';
  if (workflowId.includes('vtuber')) presetKey = 'vtuber';
  else if (workflowId.includes('simple')) presetKey = 'worker_easy';

  const preset = PRESET_LABELS[presetKey] || PRESET_LABELS['worker_adaptive'];

  return (
    <div className="h-full flex flex-col p-4 overflow-auto">
      {/* Header */}
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
          <Layers className="w-5 h-5" />
          Pipeline: {preset.label}
        </h2>
        <p className="text-sm text-zinc-400 mt-1">{preset.desc}</p>
        <p className="text-xs text-zinc-500 mt-1">
          Session: {session.session_name || session.session_id.slice(0, 8)} | Model: {session.model || 'default'}
        </p>
      </div>

      {/* Pipeline Stages */}
      <div className="flex-1">
        {Object.entries(CATEGORY_LABELS).map(([cat, label]) => {
          const stages = PIPELINE_STAGES.filter(s => s.category === cat);
          if (stages.length === 0) return null;
          const colorClass = CATEGORY_COLORS[cat] || '';

          return (
            <div key={cat} className="mb-4">
              <div className="text-xs font-medium text-zinc-500 uppercase mb-2">{label}</div>
              <div className="flex flex-wrap gap-2">
                {stages.map((stage) => {
                  const Icon = stage.icon;
                  return (
                    <div
                      key={stage.id}
                      className={`flex items-center gap-2 px-3 py-2 rounded-lg border ${colorClass} text-sm`}
                    >
                      <Icon className="w-4 h-4 flex-shrink-0" />
                      <div>
                        <div className="font-medium">{stage.id}: {stage.name}</div>
                        <div className="text-xs opacity-70">{stage.desc}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}

        {/* Loop indicator */}
        <div className="mt-4 p-3 rounded-lg border border-zinc-700 bg-zinc-800/50 text-sm text-zinc-400">
          <div className="font-medium text-zinc-300 mb-1">Execution Loop</div>
          <div>s06 (API) → s13 (Loop) repeats until completion signal or max_turns reached.</div>
          {presetKey === 'worker_adaptive' && (
            <div className="mt-1 text-xs">
              <span className="text-green-400">easy</span>: 1 turn |{' '}
              <span className="text-yellow-400">not_easy</span>: up to 30 turns with tool execution
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
