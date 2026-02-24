'use client';

import { useState, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';

export default function CommandTab() {
  const { selectedSessionId, sessions, isExecuting, setIsExecuting, getSessionData, updateSessionData } = useAppStore();

  const session = sessions.find(s => s.session_id === selectedSessionId);
  const sessionData = selectedSessionId ? getSessionData(selectedSessionId) : null;

  const [skipPermissions, setSkipPermissions] = useState(true);

  const handleExecute = useCallback(async (autonomous: boolean) => {
    if (!selectedSessionId || !sessionData?.input?.trim()) return;
    setIsExecuting(true);
    updateSessionData(selectedSessionId, { status: 'running', statusText: 'Executing...', output: '' });

    try {
      if (autonomous) {
        const res = await agentApi.executeAutonomous(selectedSessionId, {
          prompt: sessionData.input,
          skip_permissions: skipPermissions,
        });
        updateSessionData(selectedSessionId, {
          output: res.final_output || res.error || 'No output',
          status: res.success ? 'success' : 'error',
          statusText: res.success
            ? `✅ Complete (${res.total_iterations} iterations, ${(res.total_duration_ms / 1000).toFixed(1)}s)`
            : `❌ ${res.error || 'Failed'}`,
        });
      } else {
        const res = await agentApi.execute(selectedSessionId, {
          prompt: sessionData.input,
          skip_permissions: skipPermissions,
        });
        updateSessionData(selectedSessionId, {
          output: res.output || res.error || 'No output',
          status: res.success ? 'success' : 'error',
          statusText: res.success
            ? `✅ Success${res.duration_ms ? ` (${(res.duration_ms / 1000).toFixed(1)}s)` : ''}`
            : `❌ ${res.error || 'Failed'}`,
        });
      }
    } catch (e: unknown) {
      updateSessionData(selectedSessionId, {
        output: e instanceof Error ? e.message : 'Request failed',
        status: 'error',
        statusText: '❌ Request failed',
      });
    } finally {
      setIsExecuting(false);
    }
  }, [selectedSessionId, sessionData?.input, skipPermissions, setIsExecuting, updateSessionData]);

  const handleStop = useCallback(async () => {
    if (!selectedSessionId) return;
    try {
      await agentApi.stopAutonomous(selectedSessionId);
      updateSessionData(selectedSessionId, { statusText: '⏹ Stopped' });
    } catch { /* ignore */ }
  }, [selectedSessionId, updateSessionData]);

  if (!selectedSessionId || !session) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center justify-center py-12 px-4">
          <h3 className="text-[1rem] font-medium text-[var(--text-secondary)] mb-2">Select a Session</h3>
          <p className="text-[0.8125rem] text-[var(--text-muted)]">Choose a session from the list to execute commands</p>
        </div>
      </div>
    );
  }

  const isManager = session.role === 'manager';

  return (
    <div className="flex flex-col h-full p-6 gap-5 overflow-auto">
      {/* Selected Session Info */}
      <div className="py-4 px-5 bg-[var(--bg-secondary)] rounded-[var(--border-radius)]"
           style={{ borderLeft: '3px solid var(--primary-color)' }}>
        <h4 className="flex items-center gap-2 text-[0.875rem] font-medium mb-1">
          {session.session_name || `Session ${session.session_id.substring(0, 8)}`}
          <span
            className="inline-flex items-center justify-center px-2 py-0.5 rounded text-[11px] font-semibold text-white"
            style={{
              background: isManager
                ? 'linear-gradient(135deg, #8b5cf6, #6366f1)'
                : 'linear-gradient(135deg, #10b981, #059669)',
            }}
          >
            {session.role}
          </span>
          <span
            className="inline-flex items-center px-2.5 py-1 rounded-full text-[0.75rem] font-medium ml-1"
            style={
              session.autonomous
                ? { background: 'linear-gradient(135deg, rgba(139, 92, 246, 0.2) 0%, rgba(99, 102, 241, 0.2) 100%)', color: '#a78bfa', border: '1px solid rgba(139, 92, 246, 0.3)' }
                : { background: 'rgba(100, 116, 139, 0.2)', color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }
            }
          >
            {session.autonomous ? 'Autonomous' : 'Single'}
          </span>
        </h4>
        <div className="flex gap-4 flex-wrap text-[0.8125rem] text-[var(--text-muted)]">
          <span>ID: {session.session_id.substring(0, 12)}</span>
          {session.model && <span>Model: {session.model}</span>}
          {session.max_turns && <span>Max turns: {session.max_turns}</span>}
        </div>
      </div>

      {/* Command Input Area */}
      <div className="flex flex-col gap-4">
        <textarea
          className="w-full p-4 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[var(--text-primary)] text-[0.875rem] font-[inherit] resize-y min-h-[120px] transition-[border-color] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)]"
          placeholder="Enter command or prompt..."
          value={sessionData?.input || ''}
          onChange={e => updateSessionData(selectedSessionId, { input: e.target.value })}
          onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) handleExecute(false); }}
        />
        <div className="flex items-center gap-6 flex-wrap">
          <label className="flex items-center gap-2 text-[0.8125rem] text-[var(--text-secondary)] cursor-pointer">
            <input type="checkbox" checked={skipPermissions} onChange={e => setSkipPermissions(e.target.checked)} />
            Skip permissions
          </label>
        </div>
        <div className="flex gap-2.5">
          <button
            className="py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={isExecuting || !sessionData?.input?.trim()}
            onClick={() => handleExecute(false)}
          >
            {isExecuting ? '⏳ Executing...' : '▶ Execute'}
          </button>
          {session.autonomous && (
            <button
              className="py-2 px-4 text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ background: 'linear-gradient(135deg, #8b5cf6, #6366f1)' }}
              disabled={isExecuting || !sessionData?.input?.trim()}
              onClick={() => handleExecute(true)}
            >
              🔄 Autonomous
            </button>
          )}
          {isExecuting && (
            <button
              className="py-2 px-4 bg-[var(--danger-color)] hover:brightness-110 text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none"
              onClick={handleStop}
            >
              ⏹ Stop
            </button>
          )}
        </div>
      </div>

      {/* Output Area */}
      <div className="flex-1 flex flex-col min-h-[200px]">
        <div className="flex justify-between items-center mb-3">
          <h3 className="text-[0.8125rem] font-medium text-[var(--text-secondary)] uppercase tracking-[0.05em]">Output</h3>
          {sessionData?.statusText && (
            <span className={`text-[0.75rem] ${sessionData.status === 'success' ? 'text-[var(--success-color)]' : sessionData.status === 'error' ? 'text-[var(--danger-color)]' : 'text-[var(--warning-color)]'}`}>
              {sessionData.statusText}
            </span>
          )}
        </div>
        <pre className="flex-1 p-5 bg-[var(--bg-secondary)] rounded-[var(--border-radius)] font-mono text-[0.8125rem] overflow-auto whitespace-pre-wrap break-words text-[var(--text-secondary)] leading-[1.6]">
          {sessionData?.output || 'No output yet'}
        </pre>
      </div>
    </div>
  );
}
