'use client';

import { useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { Play, Square, Loader2, Terminal, Zap, Wrench } from 'lucide-react';

export default function CommandTab() {
  const { selectedSessionId, sessions, isExecuting, setIsExecuting, getSessionData, updateSessionData } = useAppStore();
  const { t } = useI18n();

  const session = sessions.find(s => s.session_id === selectedSessionId);
  const sessionData = selectedSessionId ? getSessionData(selectedSessionId) : null;

  const handleExecute = useCallback(async () => {
    if (!selectedSessionId || !sessionData?.input?.trim()) return;
    setIsExecuting(true);
    updateSessionData(selectedSessionId, { status: 'running', statusText: t('commandTab.statusExecuting'), output: '' });

    try {
      // The session's graph determines the execution path automatically
      const res = await agentApi.execute(selectedSessionId, {
        prompt: sessionData.input,
      });
      updateSessionData(selectedSessionId, {
        output: res.output || res.error || t('common.noOutput'),
        status: res.success ? 'success' : 'error',
        statusText: res.success
          ? `${t('commandTab.statusSuccess')}${res.duration_ms ? ` (${(res.duration_ms / 1000).toFixed(1)}s)` : ''}`
          : `${res.error || t('commandTab.statusFailed')}`,
      });
    } catch (e: unknown) {
      updateSessionData(selectedSessionId, {
        output: e instanceof Error ? e.message : t('commandTab.requestFailed'),
        status: 'error',
        statusText: `${t('commandTab.requestFailed')}`,
      });
    } finally {
      setIsExecuting(false);
    }
  }, [selectedSessionId, sessionData?.input, setIsExecuting, updateSessionData]);

  const handleStop = useCallback(async () => {
    if (!selectedSessionId) return;
    try {
      await agentApi.stop(selectedSessionId);
      updateSessionData(selectedSessionId, { statusText: `${t('commandTab.statusStopped')}` });
    } catch { /* ignore */ }
  }, [selectedSessionId, updateSessionData]);

  if (!selectedSessionId || !session) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center justify-center py-12 px-4">
          <h3 className="text-[1rem] font-medium text-[var(--text-secondary)] mb-2">{t('commandTab.selectSession')}</h3>
          <p className="text-[0.8125rem] text-[var(--text-muted)]">{t('commandTab.selectSessionDesc')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-auto">
      {/* Session Header Bar */}
      <div className="shrink-0 px-6 py-4 bg-gradient-to-r from-[rgba(59,130,246,0.06)] to-transparent border-b border-[var(--border-color)]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Icon spanning both rows */}
            <div className="w-10 h-10 rounded-lg bg-[var(--primary-color)] flex items-center justify-center shadow-[0_0_12px_rgba(59,130,246,0.25)] shrink-0">
              <Terminal size={18} className="text-white" />
            </div>
            {/* Right side: 2 rows */}
            <div className="flex flex-col gap-1">
              {/* Row 1: Session Name */}
              <span className="text-[0.9375rem] font-semibold text-[var(--text-primary)] leading-tight">
                {session.session_name || t('sidebar.sessionFallback', { id: session.session_id.substring(0, 8) })}
              </span>
              {/* Row 2: Role + Graph + Tool Preset + Max Turns */}
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className="inline-flex items-center justify-center px-2 py-0.5 rounded text-[10px] font-bold text-white uppercase tracking-wider"
                  style={{
                    background: 'linear-gradient(135deg, #10b981, #059669)',
                  }}
                >
                  {session.role}
                </span>
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[0.6875rem] bg-[rgba(100,116,139,0.12)] border border-[var(--border-color)] text-[var(--text-muted)]">
                  <Zap size={10} />
                  {session.graph_name || t('commandTab.single')}
                </span>
                {session.tool_preset_name && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[0.6875rem] bg-[rgba(100,116,139,0.12)] border border-[var(--border-color)] text-[var(--text-muted)]">
                    <Wrench size={10} />
                    {session.tool_preset_name}
                  </span>
                )}
                {session.max_turns && <span className="text-[0.6875rem] text-[var(--text-muted)]">{t('commandTab.maxTurns')}: {session.max_turns}</span>}
              </div>
            </div>
          </div>
          {/* Status badge */}
          {sessionData?.statusText && (
            <div className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[0.75rem] font-medium ${
              sessionData.status === 'success' ? 'bg-[rgba(16,185,129,0.1)] text-[var(--success-color)] border border-[rgba(16,185,129,0.2)]'
                : sessionData.status === 'error' ? 'bg-[rgba(239,68,68,0.1)] text-[var(--danger-color)] border border-[rgba(239,68,68,0.2)]'
                : 'bg-[rgba(245,158,11,0.1)] text-[var(--warning-color)] border border-[rgba(245,158,11,0.2)]'
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${
                sessionData.status === 'success' ? 'bg-[var(--success-color)]'
                  : sessionData.status === 'error' ? 'bg-[var(--danger-color)]'
                  : 'bg-[var(--warning-color)] animate-pulse'
              }`} />
              {sessionData.statusText}
            </div>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex flex-col flex-1 p-6 gap-5 min-h-0">
        {/* Command Input Area */}
        <div className="flex flex-col gap-3 shrink-0">
          <div className="relative">
            <textarea
              className="w-full p-4 pr-[140px] bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-xl text-[var(--text-primary)] text-[0.875rem] font-[inherit] resize-y min-h-[120px] transition-all placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)]"
              placeholder={t('commandTab.placeholder')}
              value={sessionData?.input || ''}
              onChange={e => updateSessionData(selectedSessionId, { input: e.target.value })}
              onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) handleExecute(); }}
            />
            {/* Inline action buttons */}
            <div className="absolute bottom-3 right-3 flex items-center gap-2">
              {isExecuting && (
                <button
                  className="h-9 px-3.5 bg-[var(--danger-color)] hover:brightness-110 text-white text-[0.8125rem] font-medium rounded-lg cursor-pointer transition-all duration-150 border-none inline-flex items-center gap-1.5 shadow-md"
                  onClick={handleStop}
                >
                  <Square size={13} /> {t('commandTab.stopBtn')}
                </button>
              )}
              <button
                className="h-9 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-semibold rounded-lg cursor-pointer transition-all duration-150 border-none disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center gap-1.5 shadow-[0_2px_8px_rgba(59,130,246,0.3)] hover:shadow-[0_4px_12px_rgba(59,130,246,0.4)]"
                disabled={isExecuting || !sessionData?.input?.trim()}
                onClick={() => handleExecute()}
              >
                {isExecuting ? <><Loader2 size={14} className="animate-spin" /> {t('commandTab.executingBtn')}</> : <><Play size={14} /> {t('commandTab.executeBtn')}</>}
              </button>
            </div>
          </div>
          <div className="text-[0.6875rem] text-[var(--text-muted)] pl-1">
            Ctrl + Enter
          </div>
        </div>

        {/* Output Area */}
        <div className="flex-1 flex flex-col min-h-[200px]">
          <div className="flex justify-between items-center mb-2">
            <h3 className="text-[0.75rem] font-semibold text-[var(--text-muted)] uppercase tracking-[0.08em] inline-flex items-center gap-1.5">
              <Terminal size={12} />
              {t('commandTab.output')}
            </h3>
          </div>
          <pre className="flex-1 p-5 bg-[var(--bg-secondary)] rounded-xl border border-[var(--border-color)] font-mono text-[0.8125rem] overflow-auto whitespace-pre-wrap break-words text-[var(--text-secondary)] leading-[1.7]">
            {sessionData?.output || t('common.noOutput')}
          </pre>
        </div>
      </div>
    </div>
  );
}
