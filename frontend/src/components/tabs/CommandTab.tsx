'use client';

import { useState, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

export default function CommandTab() {
  const { selectedSessionId, sessions, isExecuting, setIsExecuting, getSessionData, updateSessionData } = useAppStore();
  const { t } = useI18n();

  const session = sessions.find(s => s.session_id === selectedSessionId);
  const sessionData = selectedSessionId ? getSessionData(selectedSessionId) : null;

  const [skipPermissions, setSkipPermissions] = useState(true);

  const handleExecute = useCallback(async () => {
    if (!selectedSessionId || !sessionData?.input?.trim()) return;
    setIsExecuting(true);
    updateSessionData(selectedSessionId, { status: 'running', statusText: t('commandTab.statusExecuting'), output: '' });

    try {
      // The session's graph determines the execution path automatically
      const res = await agentApi.execute(selectedSessionId, {
        prompt: sessionData.input,
        skip_permissions: skipPermissions,
      });
      updateSessionData(selectedSessionId, {
        output: res.output || res.error || t('common.noOutput'),
        status: res.success ? 'success' : 'error',
        statusText: res.success
          ? `✅ ${t('commandTab.statusSuccess')}${res.duration_ms ? ` (${(res.duration_ms / 1000).toFixed(1)}s)` : ''}`
          : `❌ ${res.error || t('commandTab.statusFailed')}`,
      });
    } catch (e: unknown) {
      updateSessionData(selectedSessionId, {
        output: e instanceof Error ? e.message : t('commandTab.requestFailed'),
        status: 'error',
        statusText: `❌ ${t('commandTab.requestFailed')}`,
      });
    } finally {
      setIsExecuting(false);
    }
  }, [selectedSessionId, sessionData?.input, skipPermissions, setIsExecuting, updateSessionData]);

  const handleStop = useCallback(async () => {
    if (!selectedSessionId) return;
    try {
      await agentApi.stop(selectedSessionId);
      updateSessionData(selectedSessionId, { statusText: `⏹ ${t('commandTab.statusStopped')}` });
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

  const isManager = session.role === 'manager';

  return (
    <div className="flex flex-col h-full p-6 gap-5 overflow-auto">
      {/* Selected Session Info */}
      <div className="py-4 px-5 bg-[var(--bg-secondary)] rounded-[var(--border-radius)]"
           style={{ borderLeft: '3px solid var(--primary-color)' }}>
        <h4 className="flex items-center gap-2 text-[0.875rem] font-medium mb-1">
          {session.session_name || t('sidebar.sessionFallback', { id: session.session_id.substring(0, 8) })}
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
            style={{ background: 'rgba(100, 116, 139, 0.2)', color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}
          >
            {session.graph_name || t('commandTab.single')}
          </span>
        </h4>
        <div className="flex gap-4 flex-wrap text-[0.8125rem] text-[var(--text-muted)]">
          <span>ID: {session.session_id.substring(0, 12)}</span>
          {session.model && <span>{t('commandTab.model')}: {session.model}</span>}
          {session.max_turns && <span>{t('commandTab.maxTurns')}: {session.max_turns}</span>}
        </div>
      </div>

      {/* Command Input Area */}
      <div className="flex flex-col gap-4">
        <textarea
          className="w-full p-4 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[var(--text-primary)] text-[0.875rem] font-[inherit] resize-y min-h-[120px] transition-[border-color] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)]"
          placeholder={t('commandTab.placeholder')}
          value={sessionData?.input || ''}
          onChange={e => updateSessionData(selectedSessionId, { input: e.target.value })}
          onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) handleExecute(); }}
        />
        <div className="flex items-center gap-6 flex-wrap">
          <label className="flex items-center gap-2 text-[0.8125rem] text-[var(--text-secondary)] cursor-pointer">
            <input type="checkbox" checked={skipPermissions} onChange={e => setSkipPermissions(e.target.checked)} />
            {t('commandTab.skipPermissions')}
          </label>
        </div>
        <div className="flex gap-2.5">
          <button
            className="py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={isExecuting || !sessionData?.input?.trim()}
            onClick={() => handleExecute()}
          >
            {isExecuting ? t('commandTab.executingBtn') : t('commandTab.executeBtn')}
          </button>
          {isExecuting && (
            <button
              className="py-2 px-4 bg-[var(--danger-color)] hover:brightness-110 text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none"
              onClick={handleStop}
            >
              {t('commandTab.stopBtn')}
            </button>
          )}
        </div>
      </div>

      {/* Output Area */}
      <div className="flex-1 flex flex-col min-h-[200px]">
        <div className="flex justify-between items-center mb-3">
          <h3 className="text-[0.8125rem] font-medium text-[var(--text-secondary)] uppercase tracking-[0.05em]">{t('commandTab.output')}</h3>
          {sessionData?.statusText && (
            <span className={`text-[0.75rem] ${sessionData.status === 'success' ? 'text-[var(--success-color)]' : sessionData.status === 'error' ? 'text-[var(--danger-color)]' : 'text-[var(--warning-color)]'}`}>
              {sessionData.statusText}
            </span>
          )}
        </div>
        <pre className="flex-1 p-5 bg-[var(--bg-secondary)] rounded-[var(--border-radius)] font-mono text-[0.8125rem] overflow-auto whitespace-pre-wrap break-words text-[var(--text-secondary)] leading-[1.6]">
          {sessionData?.output || t('common.noOutput')}
        </pre>
      </div>
    </div>
  );
}
