'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';
import { RotateCcw, Trash2, Pencil, Save, X, FileText, Eraser, Link2, Terminal, Brain } from 'lucide-react';
import type { SessionInfo } from '@/types';
import ConfirmModal from '@/components/modals/ConfirmModal';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

function formatTimestamp(ts: string) {
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

export default function InfoTab() {
  const { selectedSessionId, sessions, restoreSession, permanentDeleteSession } = useAppStore();
  const { t } = useI18n();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [editingPrompt, setEditingPrompt] = useState(false);
  const [promptDraft, setPromptDraft] = useState('');
  const [savingPrompt, setSavingPrompt] = useState(false);
  const [promptMsg, setPromptMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [showPermanentDeleteModal, setShowPermanentDeleteModal] = useState(false);
  const [cliData, setCliData] = useState<any>(null);
  const [cliLoading, setCliLoading] = useState(false);
  const [editingCliPrompt, setEditingCliPrompt] = useState(false);
  const [cliPromptDraft, setCliPromptDraft] = useState('');
  const [savingCliPrompt, setSavingCliPrompt] = useState(false);
  const [cliPromptMsg, setCliPromptMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [thinkingTriggerEnabled, setThinkingTriggerEnabled] = useState<boolean | null>(null);
  const [thinkingTriggerInfo, setThinkingTriggerInfo] = useState<{ consecutive_triggers: number; current_threshold_seconds: number } | null>(null);
  const [thinkingTriggerLoading, setThinkingTriggerLoading] = useState(false);
  const [thinkingTriggerMsg, setThinkingTriggerMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const fetchDetail = useCallback(async () => {
    if (!selectedSessionId) { setData(null); return; }
    setLoading(true);
    setError('');
    try {
      let result: any;
      try {
        result = await agentApi.get(selectedSessionId);
        result._source = 'live';
      } catch {
        result = await agentApi.getStore(selectedSessionId);
        result._source = 'store';
      }
      setData(result);
    } catch (e: any) {
      setError(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [selectedSessionId]);

  useEffect(() => { fetchDetail(); }, [fetchDetail]);

  // Fetch linked CLI session data when main session is VTuber type
  useEffect(() => {
    if (!data?.linked_session_id || data?.session_type !== 'vtuber') {
      setCliData(null);
      return;
    }
    let cancelled = false;
    setCliLoading(true);
    (async () => {
      try {
        let result: any;
        try {
          result = await agentApi.get(data.linked_session_id);
        } catch {
          result = await agentApi.getStore(data.linked_session_id);
        }
        if (!cancelled) setCliData(result);
      } catch {
        if (!cancelled) setCliData(null);
      } finally {
        if (!cancelled) setCliLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [data?.linked_session_id, data?.session_type]);

  // Fetch thinking trigger status for VTuber sessions
  useEffect(() => {
    if (!data?.session_id || data?.session_type !== 'vtuber') {
      setThinkingTriggerEnabled(null);
      setThinkingTriggerInfo(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const result = await agentApi.getThinkingTrigger(data.session_id);
        if (!cancelled) {
          setThinkingTriggerEnabled(result.enabled);
          setThinkingTriggerInfo({
            consecutive_triggers: result.consecutive_triggers,
            current_threshold_seconds: result.current_threshold_seconds,
          });
        }
      } catch {
        if (!cancelled) setThinkingTriggerEnabled(null);
      }
    })();
    return () => { cancelled = true; };
  }, [data?.session_id, data?.session_type]);

  if (!selectedSessionId) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center justify-center py-12 px-4">
          <h3 className="text-[1rem] font-medium text-[var(--text-secondary)] mb-2">{t('info.selectSession')}</h3>
          <p className="text-[0.8125rem] text-[var(--text-muted)]">{t('info.selectSessionDesc')}</p>
        </div>
      </div>
    );
  }

  if (loading) return <div className="flex items-center justify-center h-full text-[var(--text-muted)]">{t('common.loading')}</div>;
  if (error) return <div className="flex items-center justify-center h-full text-[var(--danger-color)] text-[0.875rem]">{error}</div>;
  if (!data) return null;

  const isDeleted = data.is_deleted === true;

  const getStatusBadgeStyle = (): React.CSSProperties => {
    if (isDeleted) return { background: 'rgba(239, 68, 68, 0.15)', color: 'var(--danger-color)' };
    if (data.status === 'running') return { background: 'rgba(16, 185, 129, 0.15)', color: 'var(--success-color)' };
    if (data.status === 'idle') return { background: 'rgba(245, 158, 11, 0.15)', color: 'var(--warning-color)' };
    if (data.status === 'error') return { background: 'rgba(239, 68, 68, 0.15)', color: 'var(--danger-color)' };
    if (data.status === 'starting') return { background: 'rgba(59, 130, 246, 0.15)', color: 'var(--primary-color)' };
    return { background: 'rgba(107, 114, 128, 0.15)', color: 'var(--text-muted)' };
  };

  const formatMemoryConfig = (cfg: Record<string, unknown> | null | undefined): string => {
    if (!cfg || typeof cfg !== 'object') return t('info.memoryProviderDefault');
    const provider = typeof cfg.provider === 'string' ? cfg.provider : '';
    if (!provider) return t('info.memoryProviderDefault');
    if (provider === 'disabled') return t('info.memoryProviderDisabled');
    const parts: string[] = [provider];
    if (provider === 'file' && typeof cfg.root === 'string' && cfg.root) parts.push(cfg.root);
    if (provider === 'sql') {
      if (typeof cfg.dialect === 'string' && cfg.dialect) parts[0] = `sql (${cfg.dialect})`;
      if (typeof cfg.dsn === 'string' && cfg.dsn) parts.push(cfg.dsn);
    }
    if (typeof cfg.scope === 'string' && cfg.scope) parts.push(`scope=${cfg.scope}`);
    return parts.join(' · ');
  };

  const fields = [
    { label: t('info.fields.sessionId'), value: data.session_id },
    { label: t('info.fields.name'), value: data.session_name || t('info.unnamed') },
    { label: t('info.fields.status'), value: isDeleted ? t('info.deleted') : (data.status || t('info.unknown')) },
    { label: t('info.fields.model'), value: data.model || t('info.default') },
    { label: t('info.fields.role'), value: data.role || t('info.worker') },
    { label: t('info.fields.graphName'), value: data.graph_name || '—' },
    { label: t('info.fields.workflowId'), value: data.workflow_id || '—' },
    { label: t('info.fields.maxTurns'), value: data.max_turns ?? '—' },
    { label: t('info.fields.timeout'), value: data.timeout ? `${data.timeout}s` : '—' },
    { label: t('info.fields.maxIterations'), value: data.max_iterations ?? '—' },
    { label: t('info.fields.storagePath'), value: data.storage_path || '—' },
    { label: t('info.fields.created'), value: data.created_at ? formatTimestamp(data.created_at) : '—' },
    { label: t('info.fields.pid'), value: data.pid || '—' },
    { label: t('info.fields.pod'), value: data.pod_name || '—' },
    { label: t('info.fields.totalCost'), value: data.total_cost != null && data.total_cost > 0 ? `$${data.total_cost.toFixed(6)}` : '$0.000000' },
    { label: t('info.fields.environment'), value: data.env_id || t('info.environmentNone') },
    { label: t('info.fields.memoryProvider'), value: formatMemoryConfig(data.memory_config) },
    ...(data.session_type ? [{ label: t('info.fields.sessionType'), value: data.session_type }] : []),
    ...(data.linked_session_id ? [{ label: t('info.fields.linkedSession'), value: data.linked_session_id }] : []),
    ...(data.chat_room_id ? [{ label: t('info.fields.chatRoom'), value: data.chat_room_id }] : []),
    ...(isDeleted ? [{ label: t('info.fields.deletedAt'), value: data.deleted_at ? formatTimestamp(data.deleted_at) : '—' }] : []),
  ];

  return (
    <div className="p-3 md:p-5 overflow-y-auto h-full bg-[var(--bg-primary)]">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h4 className="text-[16px] font-semibold text-[var(--text-primary)] m-0">{data.session_name || t('info.sessionDetails')}</h4>
        <span className="text-[11px] font-semibold py-[3px] px-2.5 rounded-[12px] uppercase tracking-[0.5px]"
              style={getStatusBadgeStyle()}>
          {isDeleted ? t('info.deleted') : (data.status || t('info.unknown'))}
        </span>
      </div>

      {/* ── Thinking Trigger Toggle (VTuber sessions only) ── */}
      {!isDeleted && data.session_type === 'vtuber' && thinkingTriggerEnabled !== null && (
        <div className="mb-4 pb-4 border-b border-[var(--border-color)]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Brain size={14} className="text-[var(--text-muted)]" />
              <span className="text-[12px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">{t('info.thinkingTrigger.title')}</span>
            </div>
            <button
              disabled={thinkingTriggerLoading}
              className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-200 focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              style={{ background: thinkingTriggerEnabled ? 'var(--success-color)' : 'var(--bg-tertiary)' }}
              onClick={async () => {
                setThinkingTriggerLoading(true);
                setThinkingTriggerMsg(null);
                try {
                  const newVal = !thinkingTriggerEnabled;
                  const result = await agentApi.updateThinkingTrigger(data.session_id, newVal);
                  setThinkingTriggerEnabled(result.enabled);
                  setThinkingTriggerMsg({
                    type: 'ok',
                    text: result.enabled ? t('info.thinkingTrigger.turnedOn') : t('info.thinkingTrigger.turnedOff'),
                  });
                } catch {
                  setThinkingTriggerMsg({ type: 'err', text: t('info.thinkingTrigger.error') });
                } finally {
                  setThinkingTriggerLoading(false);
                }
              }}
            >
              <span
                className="inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform duration-200"
                style={{ transform: thinkingTriggerEnabled ? 'translateX(17px)' : 'translateX(3px)' }}
              />
            </button>
          </div>
          <p className="text-[11px] text-[var(--text-muted)] mt-1.5">{t('info.thinkingTrigger.description')}</p>
          {thinkingTriggerInfo && thinkingTriggerInfo.consecutive_triggers > 0 && (
            <p className="text-[10px] text-[var(--text-muted)] mt-1">
              {t('info.thinkingTrigger.adaptiveInfo', {
                threshold: String(thinkingTriggerInfo.current_threshold_seconds),
                count: String(thinkingTriggerInfo.consecutive_triggers),
              })}
            </p>
          )}
          {thinkingTriggerMsg && (
            <div className={`text-[11px] mt-1.5 ${thinkingTriggerMsg.type === 'ok' ? 'text-[var(--success-color)]' : 'text-[var(--danger-color)]'}`}>
              {thinkingTriggerMsg.text}
            </div>
          )}
        </div>
      )}

      {/* Fields Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
        {fields.map(f => (
          <div key={f.label} className="flex flex-col gap-0.5 py-2 px-3 bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)]">
            <span className="text-[10px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">{f.label}</span>
            <span className="text-[13px] text-[var(--text-primary)] break-all" style={{ fontFamily: "'SF Mono', 'Fira Code', monospace" }}>{String(f.value)}</span>
          </div>
        ))}
      </div>

      {/* System Prompt Section */}
      {!isDeleted && (
        <div className="mt-4 pt-4 border-t border-[var(--border-color)]">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1.5">
              <FileText size={14} className="text-[var(--text-muted)]" />
              <span className="text-[12px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">{t('info.systemPrompt.title')}</span>
              {data.system_prompt && !editingPrompt && (
                <span className="text-[10px] text-[var(--text-muted)] ml-1">({t('info.systemPrompt.chars', { count: String(data.system_prompt.length) })})</span>
              )}
            </div>
            {!editingPrompt ? (
              <button
                className="inline-flex items-center gap-1 py-1 px-2.5 text-[11px] font-medium rounded-md bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] border border-[var(--border-color)] transition-all duration-150 cursor-pointer"
                onClick={() => { setPromptDraft(data.system_prompt || ''); setEditingPrompt(true); setPromptMsg(null); }}
              >
                <Pencil size={11} /> {t('info.systemPrompt.edit')}
              </button>
            ) : (
              <div className="flex gap-1.5">
                <button
                  className="inline-flex items-center gap-1 py-1 px-2.5 text-[11px] font-medium rounded-md bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] border border-[var(--border-color)] transition-all duration-150 cursor-pointer"
                  onClick={() => { setPromptDraft(''); }}
                  title={t('info.systemPrompt.clear')}
                >
                  <Eraser size={11} /> {t('info.systemPrompt.clear')}
                </button>
                <button
                  disabled={savingPrompt}
                  className="inline-flex items-center gap-1 py-1 px-2.5 text-[11px] font-medium rounded-md bg-[var(--primary-color)] text-white hover:bg-[var(--primary-hover)] border-none transition-all duration-150 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  onClick={async () => {
                    setSavingPrompt(true);
                    setPromptMsg(null);
                    try {
                      const val = promptDraft.trim() || null;
                      await agentApi.updateSystemPrompt(data.session_id, val);
                      setData((prev: any) => ({ ...prev, system_prompt: val }));
                      setEditingPrompt(false);
                      setPromptMsg({ type: 'ok', text: t('info.systemPrompt.saveSuccess') });
                    } catch (e: any) {
                      setPromptMsg({ type: 'err', text: t('info.systemPrompt.saveError') });
                    } finally {
                      setSavingPrompt(false);
                    }
                  }}
                >
                  <Save size={11} /> {t('info.systemPrompt.save')}
                </button>
                <button
                  className="inline-flex items-center gap-1 py-1 px-2.5 text-[11px] font-medium rounded-md bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] border border-[var(--border-color)] transition-all duration-150 cursor-pointer"
                  onClick={() => { setEditingPrompt(false); setPromptMsg(null); }}
                >
                  <X size={11} /> {t('info.systemPrompt.cancel')}
                </button>
              </div>
            )}
          </div>

          {promptMsg && (
            <div className={`text-[11px] mb-2 ${promptMsg.type === 'ok' ? 'text-[var(--success-color)]' : 'text-[var(--danger-color)]'}`}>
              {promptMsg.text}
            </div>
          )}

          {editingPrompt ? (
            <textarea
              className="w-full min-h-[120px] p-3 text-[12px] leading-relaxed rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-primary)] resize-y focus:outline-none focus:border-[var(--primary-color)] transition-colors"
              style={{ fontFamily: "'SF Mono', 'Fira Code', monospace" }}
              value={promptDraft}
              onChange={e => setPromptDraft(e.target.value)}
              placeholder={t('info.systemPrompt.placeholder')}
              autoFocus
            />
          ) : (
            <div className="p-3 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-color)] min-h-[40px]">
              {data.system_prompt ? (
                <pre className="text-[12px] leading-relaxed text-[var(--text-primary)] whitespace-pre-wrap break-words m-0" style={{ fontFamily: "'SF Mono', 'Fira Code', monospace" }}>
                  {data.system_prompt}
                </pre>
              ) : (
                <span className="text-[12px] text-[var(--text-muted)] italic">{t('info.systemPrompt.empty')}</span>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Linked CLI Agent Section (VTuber sessions only) ── */}
      {!isDeleted && data.session_type === 'vtuber' && data.linked_session_id && (
        <div className="mt-4 pt-4 border-t border-[var(--border-color)]">
          <div className="flex items-center gap-1.5 mb-3">
            <Link2 size={14} className="text-[var(--text-muted)]" />
            <span className="text-[12px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">{t('info.cliAgent.title')}</span>
            {cliData && (
              <span
                className="text-[10px] font-semibold py-[2px] px-2 rounded-[10px] uppercase ml-1"
                style={
                  cliData.status === 'running'
                    ? { background: 'rgba(16, 185, 129, 0.15)', color: 'var(--success-color)' }
                    : { background: 'rgba(107, 114, 128, 0.15)', color: 'var(--text-muted)' }
                }
              >
                {cliData.status || 'unknown'}
              </span>
            )}
          </div>

          {cliLoading ? (
            <div className="text-[12px] text-[var(--text-muted)] py-3">{t('common.loading')}</div>
          ) : cliData ? (
            <>
              {/* CLI Session Info Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 mb-3">
                {[
                  { label: t('info.cliAgent.sessionId'), value: cliData.session_id },
                  { label: t('info.cliAgent.name'), value: cliData.session_name || t('info.unnamed') },
                  { label: t('info.cliAgent.model'), value: cliData.model || t('info.default') },
                  { label: t('info.cliAgent.role'), value: cliData.role || 'worker' },
                  { label: t('info.cliAgent.graphName'), value: cliData.graph_name || '—' },
                  { label: t('info.cliAgent.workflowId'), value: cliData.workflow_id || '—' },
                  { label: t('info.cliAgent.toolPreset'), value: cliData.tool_preset_id || t('info.default') },
                  { label: t('info.cliAgent.totalCost'), value: cliData.total_cost != null && cliData.total_cost > 0 ? `$${cliData.total_cost.toFixed(6)}` : '$0.000000' },
                ].map(f => (
                  <div key={f.label} className="flex flex-col gap-0.5 py-2 px-3 bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)]">
                    <span className="text-[10px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">{f.label}</span>
                    <span className="text-[13px] text-[var(--text-primary)] break-all" style={{ fontFamily: "'SF Mono', 'Fira Code', monospace" }}>{String(f.value)}</span>
                  </div>
                ))}
              </div>

              {/* CLI System Prompt Section */}
              <div className="mt-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-1.5">
                    <Terminal size={14} className="text-[var(--text-muted)]" />
                    <span className="text-[12px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">{t('info.cliAgent.systemPrompt')}</span>
                    {cliData.system_prompt && !editingCliPrompt && (
                      <span className="text-[10px] text-[var(--text-muted)] ml-1">({t('info.systemPrompt.chars', { count: String(cliData.system_prompt.length) })})</span>
                    )}
                  </div>
                  {!editingCliPrompt ? (
                    <button
                      className="inline-flex items-center gap-1 py-1 px-2.5 text-[11px] font-medium rounded-md bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] border border-[var(--border-color)] transition-all duration-150 cursor-pointer"
                      onClick={() => { setCliPromptDraft(cliData.system_prompt || ''); setEditingCliPrompt(true); setCliPromptMsg(null); }}
                    >
                      <Pencil size={11} /> {t('info.systemPrompt.edit')}
                    </button>
                  ) : (
                    <div className="flex gap-1.5">
                      <button
                        className="inline-flex items-center gap-1 py-1 px-2.5 text-[11px] font-medium rounded-md bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] border border-[var(--border-color)] transition-all duration-150 cursor-pointer"
                        onClick={() => { setCliPromptDraft(''); }}
                      >
                        <Eraser size={11} /> {t('info.systemPrompt.clear')}
                      </button>
                      <button
                        disabled={savingCliPrompt}
                        className="inline-flex items-center gap-1 py-1 px-2.5 text-[11px] font-medium rounded-md bg-[var(--primary-color)] text-white hover:bg-[var(--primary-hover)] border-none transition-all duration-150 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                        onClick={async () => {
                          setSavingCliPrompt(true);
                          setCliPromptMsg(null);
                          try {
                            const val = cliPromptDraft.trim() || null;
                            await agentApi.updateSystemPrompt(cliData.session_id, val);
                            setCliData((prev: any) => ({ ...prev, system_prompt: val }));
                            setEditingCliPrompt(false);
                            setCliPromptMsg({ type: 'ok', text: t('info.systemPrompt.saveSuccess') });
                          } catch {
                            setCliPromptMsg({ type: 'err', text: t('info.systemPrompt.saveError') });
                          } finally {
                            setSavingCliPrompt(false);
                          }
                        }}
                      >
                        <Save size={11} /> {t('info.systemPrompt.save')}
                      </button>
                      <button
                        className="inline-flex items-center gap-1 py-1 px-2.5 text-[11px] font-medium rounded-md bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] border border-[var(--border-color)] transition-all duration-150 cursor-pointer"
                        onClick={() => { setEditingCliPrompt(false); setCliPromptMsg(null); }}
                      >
                        <X size={11} /> {t('info.systemPrompt.cancel')}
                      </button>
                    </div>
                  )}
                </div>

                {cliPromptMsg && (
                  <div className={`text-[11px] mb-2 ${cliPromptMsg.type === 'ok' ? 'text-[var(--success-color)]' : 'text-[var(--danger-color)]'}`}>
                    {cliPromptMsg.text}
                  </div>
                )}

                {editingCliPrompt ? (
                  <textarea
                    className="w-full min-h-[120px] p-3 text-[12px] leading-relaxed rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[var(--text-primary)] resize-y focus:outline-none focus:border-[var(--primary-color)] transition-colors"
                    style={{ fontFamily: "'SF Mono', 'Fira Code', monospace" }}
                    value={cliPromptDraft}
                    onChange={e => setCliPromptDraft(e.target.value)}
                    placeholder={t('info.cliAgent.promptPlaceholder')}
                    autoFocus
                  />
                ) : (
                  <div className="p-3 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-color)] min-h-[40px]">
                    {cliData.system_prompt ? (
                      <pre className="text-[12px] leading-relaxed text-[var(--text-primary)] whitespace-pre-wrap break-words m-0" style={{ fontFamily: "'SF Mono', 'Fira Code', monospace" }}>
                        {cliData.system_prompt}
                      </pre>
                    ) : (
                      <span className="text-[12px] text-[var(--text-muted)] italic">{t('info.cliAgent.noPrompt')}</span>
                    )}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="text-[12px] text-[var(--text-muted)] italic py-3">{t('info.cliAgent.notFound')}</div>
          )}
        </div>
      )}

      {/* Actions for deleted */}
      {isDeleted && (
        <div className="flex gap-2 mt-4 pt-4 border-t border-[var(--border-color)]">
          <button className={cn("py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed", "!py-1.5 !px-3 text-[0.75rem] inline-flex items-center gap-1.5")} onClick={() => restoreSession(data.session_id)}><RotateCcw size={12} /> {t('info.restoreSession')}</button>
          <button className={cn("py-2 px-4 bg-[var(--danger-color)] hover:brightness-110 text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed", "!py-1.5 !px-3 text-[0.75rem] inline-flex items-center gap-1.5")} onClick={() => setShowPermanentDeleteModal(true)}><Trash2 size={12} /> {t('info.permanentDelete')}</button>
        </div>
      )}
      {showPermanentDeleteModal && data && (
        <ConfirmModal
          title={t('confirmModal.permanentDeleteTitle')}
          message={<>{t('confirmModal.permanentDeleteConfirm')}<strong className="text-[var(--text-primary)]">{data.session_name || data.session_id.substring(0, 12)}</strong>?</>}
          note={t('confirmModal.permanentDeleteNote')}
          onConfirm={() => permanentDeleteSession(data.session_id)}
          onClose={() => setShowPermanentDeleteModal(false)}
        />
      )}
    </div>
  );
}
