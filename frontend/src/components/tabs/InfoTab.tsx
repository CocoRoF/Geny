'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';
import { RotateCcw, Trash2, Pencil, Save, X, FileText, Eraser } from 'lucide-react';
import type { SessionInfo } from '@/types';

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

  const fields = [
    { label: t('info.fields.sessionId'), value: data.session_id },
    { label: t('info.fields.name'), value: data.session_name || t('info.unnamed') },
    { label: t('info.fields.status'), value: isDeleted ? t('info.deleted') : (data.status || t('info.unknown')) },
    { label: t('info.fields.model'), value: data.model || t('info.default') },
    { label: t('info.fields.role'), value: data.role || t('info.worker') },
    { label: t('info.fields.graphName'), value: data.graph_name || '—' },
    { label: t('info.fields.workflowId'), value: data.workflow_id || '—' },
    { label: t('info.fields.toolPreset'), value: data.tool_preset_name || data.tool_preset_id || '—' },
    { label: t('info.fields.maxTurns'), value: data.max_turns ?? '—' },
    { label: t('info.fields.timeout'), value: data.timeout ? `${data.timeout}s` : '—' },
    { label: t('info.fields.maxIterations'), value: data.max_iterations ?? '—' },
    { label: t('info.fields.storagePath'), value: data.storage_path || '—' },
    { label: t('info.fields.created'), value: data.created_at ? formatTimestamp(data.created_at) : '—' },
    { label: t('info.fields.pid'), value: data.pid || '—' },
    { label: t('info.fields.pod'), value: data.pod_name || '—' },
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

      {/* Actions for deleted */}
      {isDeleted && (
        <div className="flex gap-2 mt-4 pt-4 border-t border-[var(--border-color)]">
          <button className={cn("py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed", "!py-1.5 !px-3 text-[0.75rem] inline-flex items-center gap-1.5")} onClick={() => restoreSession(data.session_id)}><RotateCcw size={12} /> {t('info.restoreSession')}</button>
          <button className={cn("py-2 px-4 bg-[var(--danger-color)] hover:brightness-110 text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed", "!py-1.5 !px-3 text-[0.75rem] inline-flex items-center gap-1.5")} onClick={() => permanentDeleteSession(data.session_id)}><Trash2 size={12} /> {t('info.permanentDelete')}</button>
        </div>
      )}
    </div>
  );
}
