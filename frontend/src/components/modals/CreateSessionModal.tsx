'use client';

import { useState, useEffect } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import NumberStepper from '@/components/ui/NumberStepper';
import type { CreateAgentRequest, SessionInfo } from '@/types';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

const selectArrow: React.CSSProperties = {
  backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")",
  backgroundRepeat: 'no-repeat',
  backgroundPosition: 'right 12px center',
};

interface Props { onClose: () => void; }

const MODEL_OPTIONS = [
  { value: '', label: 'Default' },
  { value: 'claude-opus-4-20250514', label: 'Claude Opus 4' },
  { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
  { value: 'claude-opus-4-0603', label: 'Claude Opus 4.5' },
  { value: 'claude-opus-4-20260115', label: 'Claude Opus 4.6' },
  { value: 'claude-sonnet-4-20260115', label: 'Claude Sonnet 4.5' },
];

export default function CreateSessionModal({ onClose }: Props) {
  const { createSession, prompts, loadPrompts, loadPromptContent } = useAppStore();

  const [formState, setFormState] = useState<CreateAgentRequest>({
    session_name: '',
    role: 'worker',
    model: '',
    max_turns: 25,
    timeout: 300,
    autonomous: false,
    autonomous_max_iterations: 10,
    manager_id: '',
    system_prompt: '',
  });
  const [selectedPrompt, setSelectedPrompt] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [availableManagers, setAvailableManagers] = useState<SessionInfo[]>([]);

  useEffect(() => { loadPrompts(); }, [loadPrompts]);

  useEffect(() => {
    if (formState.role === 'worker') {
      agentApi.listManagers().then(setAvailableManagers).catch(() => setAvailableManagers([]));
    }
  }, [formState.role]);

  const handlePromptChange = async (name: string) => {
    setSelectedPrompt(name);
    if (name) {
      const content = await loadPromptContent(name);
      if (content) setFormState(f => ({ ...f, system_prompt: content }));
    }
  };

  const handleRoleChange = (role: string) => {
    setFormState(f => ({ ...f, role, manager_id: role === 'manager' ? '' : f.manager_id }));
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setError('');
    try {
      await createSession(formState);
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create session');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[480px] max-h-[85vh] flex flex-col shadow-[var(--shadow-lg)]" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex justify-between items-center py-4 px-6 border-b border-[var(--border-color)]">
          <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">Create New Session</h3>
          <button className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer text-lg" onClick={onClose}>×</button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-4">
          {error && <div className="text-[0.8125rem] text-[var(--danger-color)] bg-[rgba(239,68,68,0.1)] p-2.5 rounded-[6px] mb-2">{error}</div>}

          {/* Session Name */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">Session Name</label>
            <input
              className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)]"
              placeholder="e.g. my-worker-1"
              value={formState.session_name || ''} onChange={e => setFormState(f => ({ ...f, session_name: e.target.value }))} />
          </div>

          {/* Role + Model */}
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">Role</label>
              <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={formState.role} onChange={e => handleRoleChange(e.target.value)}>
                <option value="worker">Worker</option>
                <option value="manager">Manager</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">Model</label>
              <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={formState.model || ''} onChange={e => setFormState(f => ({ ...f, model: e.target.value }))}>
                {MODEL_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Manager selection */}
          {formState.role === 'worker' && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">Manager Session</label>
              <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={formState.manager_id || ''} onChange={e => setFormState(f => ({ ...f, manager_id: e.target.value }))}>
                <option value="">None (Standalone)</option>
                {availableManagers.map(m => {
                  const statusIcon = m.status === 'running' ? '🟢' : '⚪';
                  return (
                    <option key={m.session_id} value={m.session_id} disabled={m.status !== 'running'}>
                      {statusIcon} {m.session_name || m.session_id.substring(0, 12)}
                    </option>
                  );
                })}
              </select>
              <small className="text-[0.75rem] text-[var(--text-muted)] mt-0.5">Select a manager to control this worker</small>
            </div>
          )}

          {/* Prompt Template */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">Prompt Template</label>
            <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={selectedPrompt} onChange={e => handlePromptChange(e.target.value)}>
              <option value="">Custom / None</option>
              {prompts.map(p => (
                <option key={p.name} value={p.name}>{p.name}</option>
              ))}
            </select>
          </div>

          {/* Max Turns + Timeout */}
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">Max Turns</label>
              <NumberStepper value={formState.max_turns ?? 25} onChange={v => setFormState(f => ({ ...f, max_turns: v }))} min={1} max={500} step={5} />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">Timeout (s)</label>
              <NumberStepper value={formState.timeout ?? 300} onChange={v => setFormState(f => ({ ...f, timeout: v }))} min={10} max={7200} step={30} />
            </div>
          </div>

          {/* Autonomous Mode */}
          <div className="flex items-center justify-between py-2 mb-1">
            <span className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">Autonomous Mode</span>
            <button
              type="button"
              role="switch"
              aria-checked={formState.autonomous || false}
              className={cn(
                'relative w-[42px] h-6 rounded-xl cursor-pointer transition-all duration-200 p-0 shrink-0 border',
                formState.autonomous
                  ? 'bg-[var(--primary-color)] border-[var(--primary-color)]'
                  : 'bg-[var(--bg-tertiary)] border-[var(--border-color)]',
              )}
              onClick={() => setFormState(f => ({ ...f, autonomous: !f.autonomous }))}
            >
              <span className={cn(
                'absolute top-0.5 left-0.5 w-[18px] h-[18px] rounded-full bg-white transition-transform duration-200 pointer-events-none',
                formState.autonomous && 'translate-x-[18px]',
              )} />
            </button>
          </div>

          {formState.autonomous && (
            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">Max Iterations</label>
                <NumberStepper value={formState.autonomous_max_iterations ?? 10} onChange={v => setFormState(f => ({ ...f, autonomous_max_iterations: v }))} min={1} max={500} step={5} />
              </div>
            </div>
          )}

          {/* System Prompt */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">System Prompt</label>
            <textarea className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] resize-y" rows={4} placeholder="Optional system prompt..."
              value={formState.system_prompt || ''} onChange={e => setFormState(f => ({ ...f, system_prompt: e.target.value }))} />
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end items-center gap-3 py-4 px-6 border-t border-[var(--border-color)]">
          <button className="py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]" onClick={onClose}>Cancel</button>
          <button className="py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed" onClick={handleSubmit} disabled={submitting}>
            {submitting ? 'Creating...' : 'Create Session'}
          </button>
        </div>
      </div>
    </div>
  );
}
