'use client';

import { useState, useEffect } from 'react';
import { useAppStore } from '@/store/useAppStore';
import type { CreateAgentRequest } from '@/types';

interface Props { onClose: () => void; }

export default function CreateSessionModal({ onClose }: Props) {
  const { createSession, prompts, loadPrompts, loadPromptContent, sessions } = useAppStore();

  const [form, setForm] = useState<CreateAgentRequest>({
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

  useEffect(() => { loadPrompts(); }, [loadPrompts]);

  const managers = sessions.filter(s => s.role === 'manager');

  const handlePromptChange = async (name: string) => {
    setSelectedPrompt(name);
    if (name) {
      const content = await loadPromptContent(name);
      if (content) setForm(f => ({ ...f, system_prompt: content }));
    }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setError('');
    try {
      await createSession(form);
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create session');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: '480px' }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">Create New Session</h3>
          <button className="btn-close" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          {error && <div className="text-[0.8125rem] text-[var(--danger-color)] bg-[rgba(239,68,68,0.1)] p-2.5 rounded-[var(--border-radius)] mb-2">{error}</div>}

          <div className="form-group">
            <label>Session Name</label>
            <input
              placeholder="e.g. my-worker-1"
              value={form.session_name || ''} onChange={e => setForm(f => ({ ...f, session_name: e.target.value }))} />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="form-group">
              <label>Role</label>
              <select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}>
                <option value="worker">Worker</option>
                <option value="manager">Manager</option>
              </select>
            </div>
            <div className="form-group">
              <label>Model</label>
              <input placeholder="default" value={form.model || ''} onChange={e => setForm(f => ({ ...f, model: e.target.value }))} />
            </div>
          </div>

          {form.role === 'worker' && managers.length > 0 && (
            <div className="form-group">
              <label>Manager</label>
              <select value={form.manager_id || ''} onChange={e => setForm(f => ({ ...f, manager_id: e.target.value }))}>
                <option value="">None (standalone)</option>
                {managers.map(m => (
                  <option key={m.session_id} value={m.session_id}>
                    {m.session_name || m.session_id.substring(0, 12)}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="form-group">
            <label>Prompt Template</label>
            <select value={selectedPrompt} onChange={e => handlePromptChange(e.target.value)}>
              <option value="">Custom / None</option>
              {prompts.map(p => (
                <option key={p.name} value={p.name}>{p.name}</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="form-group">
              <label>Max Turns</label>
              <input type="number" value={form.max_turns ?? 25} onChange={e => setForm(f => ({ ...f, max_turns: parseInt(e.target.value) || 25 }))} />
            </div>
            <div className="form-group">
              <label>Timeout (s)</label>
              <input type="number" value={form.timeout ?? 300} onChange={e => setForm(f => ({ ...f, timeout: parseInt(e.target.value) || 300 }))} />
            </div>
          </div>

          <div className="flex items-center gap-2 py-1">
            <input type="checkbox" id="autonomous-check" checked={form.autonomous || false}
              onChange={e => setForm(f => ({ ...f, autonomous: e.target.checked }))} />
            <label htmlFor="autonomous-check" className="text-[0.8125rem] cursor-pointer text-[var(--text-secondary)]">Autonomous Mode</label>
          </div>

          {form.autonomous && (
            <div className="form-group">
              <label>Max Iterations</label>
              <input type="number" value={form.autonomous_max_iterations ?? 10} onChange={e => setForm(f => ({ ...f, autonomous_max_iterations: parseInt(e.target.value) || 10 }))} />
            </div>
          )}

          <div className="form-group">
            <label>System Prompt</label>
            <textarea rows={4} placeholder="Optional system prompt..."
              value={form.system_prompt || ''} onChange={e => setForm(f => ({ ...f, system_prompt: e.target.value }))} />
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? 'Creating...' : 'Create Session'}
          </button>
        </div>
      </div>
    </div>
  );
}
