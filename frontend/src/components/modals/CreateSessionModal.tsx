'use client';

import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { workflowApi } from '@/lib/workflowApi';
import { toolPresetApi } from '@/lib/toolApi';
import NumberStepper from '@/components/ui/NumberStepper';
import InfoTooltip from '@/components/ui/InfoTooltip';
import { X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import type { CreateAgentRequest, SessionInfo, ToolPresetDefinition } from '@/types';
import type { WorkflowDefinition } from '@/types/workflow';

const selectArrow: React.CSSProperties = {
  backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")",
  backgroundRepeat: 'no-repeat',
  backgroundPosition: 'right 12px center',
};

interface Props { onClose: () => void; }

const MODEL_OPTIONS_BASE = [
  { value: '', labelKey: 'createSession.modelDefault' },
  { value: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { value: 'claude-opus-4-5-20251101', label: 'Claude Opus 4.5' },
  { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5' },
  { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5' },
  { value: 'claude-opus-4-20250514', label: 'Claude Opus 4' },
  { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
  { value: 'claude-haiku-4-20250414', label: 'Claude Haiku 4' },
];

export default function CreateSessionModal({ onClose }: Props) {
  const { createSession, prompts, loadPrompts, loadPromptContent } = useAppStore();
  const { t } = useI18n();

  const [formState, setFormState] = useState<CreateAgentRequest>({
    session_name: '',
    role: 'developer',
    model: '',
    max_turns: 50,
    timeout: 21600,
    max_iterations: 50,
    system_prompt: '',
  });
  const [selectedPrompt, setSelectedPrompt] = useState('geny-default');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [availableWorkflows, setAvailableWorkflows] = useState<WorkflowDefinition[]>([]);
  const [templateWorkflows, setTemplateWorkflows] = useState<WorkflowDefinition[]>([]);
  const [selectedWorkflow, setSelectedWorkflow] = useState('template-optimized-autonomous');
  const [toolPresets, setToolPresets] = useState<ToolPresetDefinition[]>([]);
  const [selectedPreset, setSelectedPreset] = useState('');

  useEffect(() => { loadPrompts(); }, [loadPrompts]);

  // Load default prompt template content on mount
  useEffect(() => {
    if (selectedPrompt && !formState.system_prompt) {
      loadPromptContent(selectedPrompt).then(content => {
        if (content) setFormState(f => ({ ...f, system_prompt: content }));
      });
    }
  }, [selectedPrompt, loadPromptContent]);

  // Load available workflows
  useEffect(() => {
    Promise.all([
      workflowApi.list().catch(() => ({ workflows: [] })),
      workflowApi.listTemplates().catch(() => ({ templates: [] })),
      toolPresetApi.list().catch(() => ({ presets: [] })),
    ]).then(([wfRes, tmplRes, presetRes]) => {
      const tmpls = tmplRes.templates || [];
      setTemplateWorkflows(tmpls);
      const userWfs = (wfRes.workflows || []).filter(w => !w.is_template);
      setAvailableWorkflows(userWfs);
      setToolPresets(presetRes.presets || []);
    });
  }, []);

  const handlePromptChange = async (name: string) => {
    setSelectedPrompt(name);
    if (name) {
      const content = await loadPromptContent(name);
      if (content) setFormState(f => ({ ...f, system_prompt: content }));
    } else {
      // "None" selected — clear template content
      setFormState(f => ({ ...f, system_prompt: '' }));
    }
  };

  const handleRoleChange = (role: string) => {
    setFormState(f => ({ ...f, role }));
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setError('');
    try {
      const payload: CreateAgentRequest = { ...formState };
      // Always send workflow_id directly — backend resolves from store
      const allWfs = [...templateWorkflows, ...availableWorkflows];
      const wf = allWfs.find(w => w.id === selectedWorkflow);
      payload.workflow_id = selectedWorkflow;
      payload.graph_name = wf?.name || selectedWorkflow;
      // Send tool preset if explicitly selected
      if (selectedPreset) {
        payload.tool_preset_id = selectedPreset;
      }
      await createSession(payload);
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('createSession.failedToCreate'));
    } finally {
      setSubmitting(false);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[480px] mx-4 max-h-[85vh] flex flex-col shadow-[var(--shadow-lg)]" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex justify-between items-center py-3 md:py-4 px-4 md:px-6 border-b border-[var(--border-color)]">
          <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">{t('createSession.title')}</h3>
          <button className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer" onClick={onClose}><X size={16} /></button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 md:py-5 flex flex-col gap-4">
          {error && <div className="text-[0.8125rem] text-[var(--danger-color)] bg-[rgba(239,68,68,0.1)] p-2.5 rounded-[6px] mb-2">{error}</div>}

          {/* Session Name */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">{t('createSession.sessionName')}</label>
            <input
              className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)]"
              placeholder={t('createSession.sessionNamePlaceholder')}
              value={formState.session_name || ''} onChange={e => setFormState(f => ({ ...f, session_name: e.target.value }))} />
          </div>

          {/* Role + Model */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">{t('createSession.role')}</label>
              <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={formState.role} onChange={e => handleRoleChange(e.target.value)}>
                <option value="developer">{t('createSession.roleDeveloper')}</option>
                <option value="worker">{t('createSession.roleWorker')}</option>
                <option value="researcher">{t('createSession.roleResearcher')}</option>
                <option value="planner">{t('createSession.rolePlanner')}</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">{t('createSession.model')}</label>
              <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={formState.model || ''} onChange={e => setFormState(f => ({ ...f, model: e.target.value }))}>
                {MODEL_OPTIONS_BASE.map(opt => (
                  <option key={opt.value} value={opt.value}>{'labelKey' in opt ? t(opt.labelKey as string) : opt.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Prompt Template */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.promptTemplate')} <InfoTooltip text={t('createSession.promptTemplateHelp')} /></label>
            <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={selectedPrompt} onChange={e => handlePromptChange(e.target.value)}>
              <option value="">{t('createSession.templateNone')}</option>
              {prompts.map(p => (
                <option key={p.name} value={p.name}>{p.name}</option>
              ))}
            </select>
          </div>

          {/* Max Turns + Timeout */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.maxTurns')} <InfoTooltip text={t('createSession.maxTurnsHelp')} /></label>
              <NumberStepper value={formState.max_turns ?? 50} onChange={v => setFormState(f => ({ ...f, max_turns: v }))} min={1} max={500} step={5} />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.timeout')} <InfoTooltip text={t('createSession.timeoutHelp')} /></label>
              <NumberStepper value={formState.timeout ?? 21600} onChange={v => setFormState(f => ({ ...f, timeout: v }))} min={10} max={86400} step={60} />
            </div>
          </div>

          {/* Graph Workflow */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.graphWorkflow')} <InfoTooltip text={t('createSession.graphWorkflowHelp')} /></label>
            <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={selectedWorkflow} onChange={e => setSelectedWorkflow(e.target.value)}>
              {templateWorkflows.length > 0 && (
                <optgroup label={t('createSession.officialTemplates')}>
                  {templateWorkflows.map(w => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
                </optgroup>
              )}
              {availableWorkflows.length > 0 && (
                <optgroup label={t('createSession.customWorkflows')}>
                  {availableWorkflows.map(w => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
            <small className="text-[0.75rem] text-[var(--text-muted)] mt-0.5">
              {(() => {
                const allWfs = [...templateWorkflows, ...availableWorkflows];
                const wf = allWfs.find(w => w.id === selectedWorkflow);
                return wf?.description || t('createSession.customHelp');
              })()}
            </small>
          </div>

          {/* Max Iterations (for non-simple workflows) */}
          {!selectedWorkflow.endsWith('-simple') && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.maxIterations')} <InfoTooltip text={t('createSession.maxIterationsHelp')} /></label>
                <NumberStepper value={formState.max_iterations ?? 50} onChange={v => setFormState(f => ({ ...f, max_iterations: v }))} min={1} max={500} step={5} />
              </div>
            </div>
          )}

          {/* Tool Preset */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">
              Tool Preset <InfoTooltip text="Select which Python tools and MCP servers are available to the agent. Default is determined by the role." />
            </label>
            <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={selectedPreset} onChange={e => setSelectedPreset(e.target.value)}>
              <option value="">Default (based on role)</option>
              {toolPresets.filter(p => p.is_template).length > 0 && (
                <optgroup label="Templates">
                  {toolPresets.filter(p => p.is_template).map(p => (
                    <option key={p.id} value={p.id}>{p.icon || '🔧'} {p.name}</option>
                  ))}
                </optgroup>
              )}
              {toolPresets.filter(p => !p.is_template).length > 0 && (
                <optgroup label="Custom">
                  {toolPresets.filter(p => !p.is_template).map(p => (
                    <option key={p.id} value={p.id}>{p.icon || '🔧'} {p.name}</option>
                  ))}
                </optgroup>
              )}
            </select>
            <small className="text-[0.75rem] text-[var(--text-muted)] mt-0.5">
              {(() => {
                if (!selectedPreset) return 'Automatically selects the best preset for the chosen role.';
                const p = toolPresets.find(tp => tp.id === selectedPreset);
                return p?.description || '';
              })()}
            </small>
          </div>

          {/* System Prompt */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.systemPrompt')} <InfoTooltip text={t('createSession.systemPromptHelp')} /></label>
            <textarea className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] resize-y" rows={4} placeholder={t('createSession.systemPromptPlaceholder')}
              value={formState.system_prompt || ''} onChange={e => setFormState(f => ({ ...f, system_prompt: e.target.value }))} />
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end items-center gap-3 py-3 md:py-4 px-4 md:px-6 border-t border-[var(--border-color)]">
          <button className="py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]" onClick={onClose}>{t('common.cancel')}</button>
          <button className="py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed" onClick={handleSubmit} disabled={submitting}>
            {submitting ? t('createSession.creating') : t('createSession.createSession')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
