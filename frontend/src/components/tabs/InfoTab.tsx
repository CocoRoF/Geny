'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { useCreatureStateStore } from '@/store/useCreatureStateStore';
import { agentApi, personaPresetsApi } from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';
import { RotateCcw, Trash2, Pencil, Save, X, FileText, Eraser, Link2, Terminal, Brain, ExternalLink, Info, Power, Pin, PinOff, Drama, RefreshCw } from 'lucide-react';
import type { SessionInfo } from '@/types';
import type { PersonaPresetSummary } from '@/lib/api';
import ConfirmModal from '@/components/modals/ConfirmModal';
import { TabShell, EmptyState, ActionButton } from '@/components/common/layout';
import CreatureStatePanel from '@/components/info/CreatureStatePanel';

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
  const [thinkingTriggerEnabled, setThinkingTriggerEnabled] = useState<boolean | null>(null);
  const [thinkingTriggerInfo, setThinkingTriggerInfo] = useState<{ consecutive_triggers: number; current_threshold_seconds: number } | null>(null);
  const [thinkingTriggerLoading, setThinkingTriggerLoading] = useState(false);
  const [thinkingTriggerMsg, setThinkingTriggerMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  // Sub-tab navigation: VTuber / Status
  type SubTab = 'vtuber' | 'status';
  const [subTab, setSubTab] = useState<SubTab>('vtuber');

  // Reset sub-tab when switching session
  useEffect(() => { setSubTab('vtuber'); }, [selectedSessionId]);

  // Mirror creature_state into the shared store so the VTuberTab
  // status badge stays in sync with whatever InfoTab last fetched.
  const setCreatureSnapshot = useCreatureStateStore((s) => s.setSnapshot);
  // Also *read* the live snapshot from the store so this tab
  // re-renders the moment another consumer (chat WS handler,
  // VTuberTab badge) refreshes it after a turn lands. Without
  // this subscription the Status sub-tab stayed pinned to the
  // value captured by the initial fetchDetail() and never moved.
  const liveSnapshot = useCreatureStateStore((s) =>
    selectedSessionId ? s.states[selectedSessionId] : null,
  );
  const fetchCreatureState = useCreatureStateStore((s) => s.fetch);

  // Refresh the live creature snapshot whenever the user switches
  // *into* the Status sub-tab. The store is otherwise only refreshed
  // by chat panels (after each assistant turn) or the VTuberTab badge
  // (on mount), so opening Status on a long-idle session would show
  // stale data without this nudge.
  useEffect(() => {
    if (subTab !== 'status' || !selectedSessionId) return;
    void fetchCreatureState(selectedSessionId);
  }, [subTab, selectedSessionId, fetchCreatureState]);

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
      if (result?.session_id) {
        setCreatureSnapshot(result.session_id, result.creature_state ?? null);
      }
    } catch (e: any) {
      setError(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [selectedSessionId, setCreatureSnapshot]);

  useEffect(() => { fetchDetail(); }, [fetchDetail]);

  // Wake Up — lazily re-hydrate a dormant session (idle after a backend
  // restart) BEFORE chatting. Chatting also wakes a session, but that path
  // races the first turn (broken message order / stale game params); an
  // explicit resume restores the pipeline + persisted creature/emotion state
  // cleanly, then refreshes this view.
  const [waking, setWaking] = useState(false);
  const handleWakeUp = useCallback(async () => {
    if (!selectedSessionId) return;
    setWaking(true);
    setError('');
    try {
      await agentApi.resume(selectedSessionId);
      await fetchDetail();
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setWaking(false);
    }
  }, [selectedSessionId, fetchDetail]);

  // Persona — until now this was a property of the ENVIRONMENT alone, so
  // giving one session a different character meant building it another
  // environment, and changing one meant editing an environment every
  // session on it shares.
  const [presets, setPresets] = useState<PersonaPresetSummary[]>([]);
  const [personaBusy, setPersonaBusy] = useState(false);
  const [personaNote, setPersonaNote] = useState('');

  useEffect(() => {
    let cancelled = false;
    personaPresetsApi
      .list()
      .then((r) => { if (!cancelled) setPresets(r.presets || []); })
      .catch(() => { if (!cancelled) setPresets([]); });
    return () => { cancelled = true; };
  }, []);

  const handlePersonaChange = useCallback(async (value: string) => {
    if (!selectedSessionId) return;
    setPersonaBusy(true);
    setError('');
    setPersonaNote('');
    try {
      const r = await agentApi.setPersona(selectedSessionId, value || null);
      // Say WHICH of the two things happened. "Saved" alone leaves the
      // operator wondering whether the agent is already using it.
      setPersonaNote(
        r.applied_now
          ? (t('info.personaAppliedNow') ?? '적용했습니다.')
          : r.live
            ? (t('info.personaAfterTurn') ?? '저장했습니다 — 진행 중인 턴이 끝나면 반영됩니다.')
            : (t('info.personaOnWake') ?? '저장했습니다 — 세션이 깨어날 때 반영됩니다.'),
      );
      await fetchDetail();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPersonaBusy(false);
    }
  }, [selectedSessionId, fetchDetail, t]);

  const [restarting, setRestarting] = useState(false);
  const handleRestart = useCallback(async () => {
    if (!selectedSessionId) return;
    setRestarting(true);
    setError('');
    setPersonaNote('');
    try {
      const r = await agentApi.restart(selectedSessionId);
      setPersonaNote(
        r.restarted
          ? (t('info.restarted') ?? '세션을 다시 시작했습니다.')
          : (t('info.restartDormant') ?? '휴면 상태라 다음 접근에 새로 구성됩니다.'),
      );
      await fetchDetail();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRestarting(false);
    }
  }, [selectedSessionId, fetchDetail, t]);

  // Keep awake — pin THIS session so the host never reclaims it for being
  // quiet. Persisted server-side, so it survives the eviction (and the
  // restart) it exists to prevent; `null` hands the session back to the
  // host policy in Settings → Session Lifecycle.
  const [pinning, setPinning] = useState(false);
  const handleToggleAlwaysOn = useCallback(async () => {
    if (!selectedSessionId || !data) return;
    setPinning(true);
    setError('');
    try {
      // Three states, two clicks: pinned ⇄ released. "Follow the host"
      // is the state a session STARTS in, not one worth a third click.
      await agentApi.setAlwaysOn(selectedSessionId, data.always_on ? null : true);
      await fetchDetail();
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setPinning(false);
    }
  }, [selectedSessionId, data, fetchDetail]);

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
      <TabShell title={t('info.sessionDetails')} icon={Info}>
        <EmptyState
          title={t('info.selectSession')}
          description={t('info.selectSessionDesc')}
        />
      </TabShell>
    );
  }

  if (loading) return (
    <TabShell title={t('info.sessionDetails')} icon={Info}>
      <EmptyState title={t('common.loading')} />
    </TabShell>
  );
  if (error) return (
    <TabShell title={t('info.sessionDetails')} icon={Info} error={error}>
      <EmptyState title={t('info.sessionDetails')} description={error} />
    </TabShell>
  );
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

  type InfoField = { label: string; value: string | number; onClick?: () => void };
  const fields: InfoField[] = [
    { label: t('info.fields.sessionId'), value: data.session_id },
    { label: t('info.fields.name'), value: data.session_name || t('info.unnamed') },
    { label: t('info.fields.status'), value: isDeleted ? t('info.deleted') : (data.status || t('info.unknown')) },
    {
      label: t('info.fields.model'),
      // Provider-qualified: "openai · gpt-5.2" — the env's Stage-6 provider is
      // what actually serves the session, so never show a bare claude-* default
      // for a non-Anthropic environment.
      value: data.model
        ? data.model_provider
          ? `${data.model_provider} · ${data.model}`
          : data.model
        : t('info.default'),
    },
    { label: t('info.fields.role'), value: data.role || t('info.worker') },
    // For env-backed sessions graph_name is the redundant "env:<id>" — the
    // 환경 row below already carries that (with the readable name). Keep the
    // row only for legacy/preset graphs where it says something real.
    ...(data.graph_name && !data.graph_name.startsWith('env:')
      ? [{ label: t('info.fields.graphName'), value: data.graph_name }]
      : []),
    { label: t('info.fields.workflowId'), value: data.workflow_id || '—' },
    { label: t('info.fields.maxTurns'), value: data.max_turns ?? '—' },
    { label: t('info.fields.timeout'), value: data.timeout ? `${data.timeout}s` : '—' },
    { label: t('info.fields.maxIterations'), value: data.max_iterations ?? '—' },
    { label: t('info.fields.storagePath'), value: data.storage_path || '—' },
    { label: t('info.fields.created'), value: data.created_at ? formatTimestamp(data.created_at) : '—' },
    { label: t('info.fields.pid'), value: data.pid || '—' },
    { label: t('info.fields.pod'), value: data.pod_name || '—' },
    { label: t('info.fields.totalCost'), value: data.total_cost != null && data.total_cost > 0 ? `$${data.total_cost.toFixed(6)}` : '$0.000000' },
    {
      label: t('info.fields.environment'),
      // Human name first; the id stays reachable through the drawer link.
      value: data.env_name || data.env_id || t('info.environmentNone'),
      onClick: data.env_id ? () => undefined : undefined,
    },
    { label: t('info.fields.memoryProvider'), value: formatMemoryConfig(data.memory_config) },
    ...(data.session_type ? [{ label: t('info.fields.sessionType'), value: data.session_type }] : []),
    ...(data.linked_session_id ? [{ label: t('info.fields.linkedSession'), value: data.linked_session_id }] : []),
    // chat_room_id stays in the API (the chat panel + connector broadcast run
    // on it) but is plumbing, not session metadata — dropped from this view.
    ...(isDeleted ? [{ label: t('info.fields.deletedAt'), value: data.deleted_at ? formatTimestamp(data.deleted_at) : '—' }] : []),
  ];

  return (
    <TabShell
      title={data.session_name || t('info.sessionDetails')}
      icon={Info}
      actions={
        <div className="flex items-center gap-2">
          {!isDeleted && (
            <ActionButton
              icon={data.always_on ? Pin : PinOff}
              spinIcon={pinning}
              onClick={handleToggleAlwaysOn}
              disabled={pinning}
              title={
                data.always_on
                  ? (t('info.keepAwakeOnHint') ?? '')
                  : (t('info.keepAwakeOffHint') ?? '')
              }
            >
              {data.always_on
                ? (t('info.keepAwakeOn') ?? 'Always on')
                : (t('info.keepAwakeOff') ?? 'Keep awake')}
            </ActionButton>
          )}
          {!isDeleted && (data.status === 'stopped' || data.status === 'idle' || !data.status) && (
            <ActionButton
              icon={Power}
              spinIcon={waking}
              onClick={handleWakeUp}
              disabled={waking}
            >
              {waking ? (t('info.wakingUp') ?? 'Waking…') : (t('info.wakeUp') ?? 'Wake Up')}
            </ActionButton>
          )}
          <span className="text-[11px] font-semibold py-[3px] px-2.5 rounded-[12px] uppercase tracking-[0.5px]"
                style={getStatusBadgeStyle()}>
            {isDeleted ? t('info.deleted') : (data.status || t('info.unknown'))}
          </span>
        </div>
      }
    >
    <div className="p-3 md:p-5 overflow-y-auto h-full">
      {/* Sub-tab navigation: VTuber / Status */}
      <div className="flex items-center gap-1 mb-4 border-b border-[var(--border-color)]">
        {([
          { id: 'vtuber' as const, label: t('info.subTabs.vtuber') },
          { id: 'status' as const, label: t('info.subTabs.status') },
        ]).map((tab) => {
          const active = subTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setSubTab(tab.id)}
              className={cn(
                'px-3 py-1.5 text-[12px] font-semibold rounded-t-md border-b-2 transition-colors duration-150 cursor-pointer',
                active
                  ? 'text-[var(--primary-color)] border-[var(--primary-color)] bg-[var(--bg-secondary)]'
                  : 'text-[var(--text-muted)] border-transparent hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]',
              )}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* ── Persona ──
          A persona used to be a property of the ENVIRONMENT alone: the only
          way to give one session a different character was to build it
          another environment, and the only way to change one was to edit an
          environment every session on it shares. This panel is the session's
          own answer, and it SAYS which one is in force — a persona resolved
          from somewhere else is exactly what cannot be deduced from here. */}
      {subTab === 'vtuber' && !isDeleted && (
        <div className="mb-4 pb-4 border-b border-[var(--border-color)]">
          <div className="flex items-center gap-1.5 mb-2">
            <Drama size={14} className="text-[var(--text-muted)]" />
            <span className="text-[12px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">
              {t('info.persona.title') ?? '페르소나'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={data.persona_preset_id ?? ''}
              disabled={personaBusy}
              onChange={(e) => void handlePersonaChange(e.target.value)}
              aria-label={t('info.persona.title') ?? '페르소나'}
              className="flex-1 min-w-0 h-8 px-2 rounded-md border border-[var(--border-color)] bg-[var(--bg-secondary)] text-[12.5px] text-[var(--text-primary)] disabled:opacity-60"
            >
              <option value="">
                {t('info.persona.followEnv') ?? '환경 설정을 따름'}
              </option>
              {presets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}{p.mbti ? ` · ${p.mbti}` : ''}
                </option>
              ))}
            </select>
            <ActionButton
              icon={RefreshCw}
              spinIcon={restarting}
              disabled={restarting}
              onClick={handleRestart}
              title={t('info.persona.restartHint') ?? '지금 세션을 다시 구성합니다. 대화와 기억은 그대로입니다.'}
            >
              {t('info.persona.restart') ?? '다시 시작'}
            </ActionButton>
          </div>
          <p className="mt-1.5 text-[11.5px] text-[var(--text-muted)] leading-relaxed">
            {data.persona_source === 'session'
              ? `${t('info.persona.fromSession') ?? '이 세션 전용'}: ${data.persona_name || data.effective_persona_preset_id}`
              : data.persona_source === 'environment'
                ? `${t('info.persona.fromEnv') ?? '환경에서 상속'}: ${data.persona_name || data.effective_persona_preset_id}`
                : (t('info.persona.none') ?? '적용된 페르소나가 없습니다.')}
          </p>
          {personaNote && (
            <p className="mt-1 text-[11.5px] text-[var(--success-color)]">{personaNote}</p>
          )}
        </div>
      )}

      {/* ── Thinking Trigger Toggle (VTuber sessions only) ── */}
      {subTab === 'vtuber' && !isDeleted && data.session_type === 'vtuber' && thinkingTriggerEnabled !== null && (
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

      {/* ── Tamagotchi Creature State (X7) ─── */}
      {/* Prefer the live snapshot from useCreatureStateStore so chat
          turns and badge refreshes propagate here without re-fetching
          the whole agent payload. Fall back to data.creature_state for
          the very first render before the store has been populated. */}
      {subTab === 'status' && !isDeleted && (liveSnapshot ?? data.creature_state) && (
        <CreatureStatePanel snapshot={liveSnapshot ?? data.creature_state} t={t} />
      )}
      {subTab === 'status' && !isDeleted && !(liveSnapshot ?? data.creature_state) && (
        <div className="text-[12px] text-[var(--text-muted)] italic py-3">
          {t('common.noData') ?? '—'}
        </div>
      )}

      {/* Fields Grid */}
      {subTab === 'vtuber' && (
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
        {fields.map(f => (
          <div key={f.label} className="flex flex-col gap-0.5 py-2 px-3 bg-[var(--bg-secondary)] rounded-lg border border-[var(--border-color)]">
            <span className="text-[10px] font-semibold uppercase tracking-[0.5px] text-[var(--text-muted)]">{f.label}</span>
            {f.onClick ? (
              <button
                type="button"
                onClick={f.onClick}
                className="inline-flex items-center gap-1 text-[13px] text-[var(--primary-color)] hover:underline break-all text-left cursor-pointer"
                style={{ fontFamily: "'SF Mono', 'Fira Code', monospace" }}
              >
                <span>{String(f.value)}</span>
                <ExternalLink size={11} className="shrink-0 opacity-70" />
              </button>
            ) : (
              <span className="text-[13px] text-[var(--text-primary)] break-all" style={{ fontFamily: "'SF Mono', 'Fira Code', monospace" }}>{String(f.value)}</span>
            )}
          </div>
        ))}
      </div>
      )}

      {/* System Prompt Section */}
      {subTab === 'vtuber' && !isDeleted && (
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
      {subTab === 'vtuber' && isDeleted && (
        <div className="flex gap-2 mt-4 pt-4 border-t border-[var(--border-color)]">
          <ActionButton variant="secondary" icon={RotateCcw} onClick={() => restoreSession(data.session_id)}>
            {t('info.restoreSession')}
          </ActionButton>
          <ActionButton variant="danger" icon={Trash2} onClick={() => setShowPermanentDeleteModal(true)}>
            {t('info.permanentDelete')}
          </ActionButton>
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
    </TabShell>
  );
}
