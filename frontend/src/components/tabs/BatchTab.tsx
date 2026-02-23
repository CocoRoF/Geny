'use client';

import { useState, useEffect } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { commandApi } from '@/lib/api';
import type { BatchCommandResponse, BatchResult } from '@/types';

export default function BatchTab() {
  const { sessions } = useAppStore();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [command, setCommand] = useState('');
  const [timeout, setTimeout_] = useState(600);
  const [parallel, setParallel] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<BatchCommandResponse | null>(null);

  const runningSessions = sessions.filter(s => s.status === 'running');

  useEffect(() => {
    setSelected(new Set(runningSessions.map(s => s.session_id)));
  }, [sessions.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const execute = async () => {
    if (selected.size === 0 || !command.trim()) return;
    setExecuting(true);
    setResult(null);
    try {
      const res = await commandApi.batch({
        session_ids: Array.from(selected),
        prompt: command.trim(),
        timeout,
        parallel,
        skip_permissions: true,
      });
      setResult(res);
    } catch (e: any) {
      setResult({ total_sessions: selected.size, successful: 0, failed: selected.size, total_duration_ms: 0, results: [{ session_id: '', success: false, error: e.message }] as any });
    } finally {
      setExecuting(false);
    }
  };

  const getSessionName = (id: string) => {
    const s = sessions.find(s => s.session_id === id);
    return s?.session_name || id.substring(0, 8);
  };

  return (
    <div className="flex flex-col gap-5 p-6 h-full overflow-auto">
      {/* Session Selection */}
      <div className="bg-[var(--bg-secondary)] p-5 rounded-[var(--border-radius)]">
        <label className="block mb-4 font-medium text-[0.875rem]">Target Sessions</label>
        <div className="grid gap-2 max-h-[160px] overflow-y-auto p-3 bg-[var(--bg-primary)] rounded-[var(--border-radius)]"
             style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))' }}>
          {runningSessions.length === 0 ? (
            <div className="empty-state"><p>No running sessions</p></div>
          ) : runningSessions.map(s => (
            <label key={s.session_id} className="flex items-center gap-2.5 py-2.5 px-3 bg-[var(--bg-secondary)] rounded-[var(--border-radius)] text-[0.8125rem] cursor-pointer transition-colors hover:bg-[var(--bg-tertiary)]">
              <input type="checkbox" checked={selected.has(s.session_id)} onChange={() => toggle(s.session_id)} />
              <span className="truncate">{s.session_name || s.session_id.substring(0, 8)}</span>
            </label>
          ))}
        </div>
        <div className="flex gap-2.5 mt-4">
          <button className="btn btn-sm" onClick={() => setSelected(new Set(runningSessions.map(s => s.session_id)))}>Select All</button>
          <button className="btn btn-sm" onClick={() => setSelected(new Set())}>Deselect All</button>
        </div>
      </div>

      {/* Command Input */}
      <div className="flex flex-col gap-4">
        <textarea
          className="w-full p-4 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[var(--text-primary)] text-[0.875rem] font-[inherit] resize-y transition-[border-color] focus:outline-none focus:border-[var(--primary-color)]"
          rows={4}
          placeholder="Enter command to execute on all selected sessions..."
          value={command}
          onChange={e => setCommand(e.target.value)}
        />
      </div>

      {/* Options */}
      <div className="flex gap-6 items-center">
        <label className="flex items-center gap-2 text-[0.8125rem] text-[var(--text-secondary)]">
          Timeout (s):
          <input type="number" className="w-20 px-2.5 py-1.5 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)]"
                 value={timeout} onChange={e => setTimeout_(Number(e.target.value))} />
        </label>
        <label className="flex items-center gap-2 text-[0.8125rem] text-[var(--text-secondary)] cursor-pointer">
          <input type="checkbox" checked={parallel} onChange={e => setParallel(e.target.checked)} />
          Parallel Execution
        </label>
        <button className="btn btn-primary" onClick={execute} disabled={executing || selected.size === 0 || !command.trim()}>
          {executing ? 'Executing...' : `Execute (${selected.size} sessions)`}
        </button>
      </div>

      {/* Results */}
      {result && (
        <div className="flex-1 overflow-auto bg-[var(--bg-secondary)] rounded-[var(--border-radius)] p-5">
          <div className="mb-5 p-4 bg-[var(--bg-tertiary)] rounded-[var(--border-radius)] text-[0.875rem]">
            <strong>Summary:</strong> {result.successful}/{result.total_sessions} successful | Total time: {result.total_duration_ms}ms
          </div>
          {result.results.map((r: BatchResult, idx: number) => (
            <div key={idx} className="p-4 mb-2.5 bg-[var(--bg-primary)] rounded-[var(--border-radius)]"
                 style={{ borderLeft: `3px solid ${r.success ? 'var(--success-color)' : 'var(--danger-color)'}` }}>
              <div className="flex justify-between mb-3 font-medium text-[0.875rem]">
                <span>{getSessionName(r.session_id)}</span>
                <span className={`text-[0.75rem] px-2 py-0.5 rounded ${r.success ? 'text-[var(--success-color)]' : 'text-[var(--danger-color)]'}`}>
                  {r.success ? '✓ Success' : '✗ Failed'}
                </span>
              </div>
              <pre className="font-mono text-[0.8125rem] bg-[var(--bg-secondary)] p-3 rounded-[var(--border-radius)] max-h-[120px] overflow-auto text-[var(--text-secondary)] whitespace-pre-wrap">
                {r.success ? (r.output || 'No output') : (r.error || 'Unknown error')}
              </pre>
              {r.duration_ms && <p className="text-[0.75rem] text-[var(--text-muted)] mt-2">Duration: {r.duration_ms}ms</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
