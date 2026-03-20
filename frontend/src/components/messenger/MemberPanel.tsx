'use client';

import { useMessengerStore } from '@/store/useMessengerStore';
import { useAppStore } from '@/store/useAppStore';
import { useI18n } from '@/lib/i18n';
import { X, Bot, Circle, Cpu, Clock, Layers, AlertTriangle } from 'lucide-react';

const getRoleColor = (role: string) => {
  switch (role) {
    case 'developer': return 'from-blue-500 to-cyan-500';
    case 'researcher': return 'from-amber-500 to-orange-500';
    case 'planner': return 'from-teal-500 to-emerald-500';
    default: return 'from-emerald-500 to-green-500';
  }
};

const getStatusDot = (status: string) => {
  switch (status) {
    case 'running': return 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]';
    case 'idle': return 'bg-amber-400';
    case 'error': return 'bg-red-500';
    default: return 'bg-gray-400';
  }
};

const getStatusLabel = (status: string) => {
  switch (status) {
    case 'running': return 'Running';
    case 'idle': return 'Idle';
    case 'stopped': return 'Stopped';
    case 'error': return 'Error';
    default: return status;
  }
};

export default function MemberPanel() {
  const { selectedMemberId, setMemberPanelOpen, messages } = useMessengerStore();
  const { sessions } = useAppStore();
  const { t } = useI18n();

  if (!selectedMemberId) return null;

  const session = sessions.find(s => s.session_id === selectedMemberId);

  // Fallback info from chat messages if session is gone
  const fallbackMsg = !session
    ? messages.find(m => m.session_id === selectedMemberId)
    : null;

  const displayName = session?.session_name
    || fallbackMsg?.session_name
    || selectedMemberId.substring(0, 8);

  const displayRole = session?.role || fallbackMsg?.role || 'worker';
  const isDeleted = !session;
  const status = session?.status || 'stopped';

  const infoItems = session ? [
    { icon: Cpu, label: t('messenger.memberPanel.model'), value: session.model },
    { icon: Layers, label: t('messenger.memberPanel.graph'), value: session.graph_name },
    { icon: Clock, label: t('messenger.memberPanel.created'), value: session.created_at ? new Date(session.created_at).toLocaleDateString() : null },
  ].filter(item => item.value) : [];

  return (
    <div className="hidden lg:flex w-[clamp(240px,_14.6vw,_360px)] shrink-0 flex-col h-full bg-[var(--bg-secondary)] border-l border-[var(--border-color)] animate-[slideInRight_200ms_ease-out]">
      {/* Header */}
      <div className="shrink-0 h-14 px-4 flex items-center justify-between border-b border-[var(--border-color)]">
        <span className="text-[0.8125rem] font-semibold text-[var(--text-primary)]">
          {t('messenger.memberPanel.title')}
        </span>
        <button
          onClick={() => setMemberPanelOpen(false)}
          className="w-7 h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-all border-none bg-transparent cursor-pointer"
        >
          <X size={14} />
        </button>
      </div>

      {/* Profile */}
      <div className="flex-1 overflow-y-auto">
        {/* Avatar + Identity card */}
        <div className="px-5 pt-6 pb-5 border-b border-[var(--border-color)]">
          <div className="flex flex-col items-center">
            <div className="relative mb-3">
              <div className={`w-[72px] h-[72px] rounded-2xl flex items-center justify-center shadow-lg ${
                isDeleted
                  ? 'bg-[var(--bg-tertiary)]'
                  : `bg-gradient-to-br ${getRoleColor(displayRole)}`
              }`}>
                <Bot size={30} className={isDeleted ? 'text-[var(--text-muted)]' : 'text-white'} />
              </div>
              {/* Status dot */}
              <span className={`absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 rounded-full border-[2.5px] border-[var(--bg-secondary)] ${
                isDeleted ? 'bg-gray-400' : getStatusDot(status)
              }`} />
            </div>

            <h3 className="text-[0.9375rem] font-bold text-[var(--text-primary)] text-center leading-tight">
              {displayName}
            </h3>

            {/* Role as subtitle */}
            <span className={`mt-1 text-[0.75rem] font-medium capitalize ${
              isDeleted ? 'text-[var(--text-muted)]' : 'text-[var(--text-secondary)]'
            }`}>
              {displayRole}
            </span>

            {/* Status pill */}
            <span className="inline-flex items-center gap-1.5 mt-2 px-2.5 py-[3px] rounded-full bg-[var(--bg-primary)] border border-[var(--border-color)]">
              <Circle size={6} className={`fill-current ${
                isDeleted ? 'text-gray-400' : status === 'running' ? 'text-green-500' : status === 'error' ? 'text-red-500' : status === 'idle' ? 'text-amber-400' : 'text-gray-400'
              }`} />
              <span className="text-[0.6875rem] text-[var(--text-secondary)]">
                {isDeleted ? t('messenger.memberPanel.deleted') : getStatusLabel(status)}
              </span>
            </span>
          </div>
        </div>

        {/* Deleted banner */}
        {isDeleted && (
          <div className="mx-4 mt-4 flex items-start gap-2.5 p-3 rounded-lg bg-[rgba(245,158,11,0.08)] border border-[rgba(245,158,11,0.2)]">
            <AlertTriangle size={14} className="text-amber-500 shrink-0 mt-0.5" />
            <p className="text-[0.75rem] text-[var(--text-secondary)] leading-relaxed">
              {t('messenger.memberPanel.deletedDesc')}
            </p>
          </div>
        )}

        {/* Details */}
        {infoItems.length > 0 && (
          <div className="px-5 py-4 space-y-3.5">
            {infoItems.map((item, i) => (
              <div key={i} className="flex items-start gap-2.5">
                <item.icon size={13} className="text-[var(--text-muted)] shrink-0 mt-[2px]" />
                <div className="min-w-0">
                  <span className="text-[0.6875rem] text-[var(--text-muted)] block leading-tight">
                    {item.label}
                  </span>
                  <span className="text-[0.8125rem] text-[var(--text-primary)] break-all leading-snug">
                    {item.value}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Session ID */}
        <div className="mx-5 mt-1 pt-4 pb-5 border-t border-[var(--border-color)]">
          <span className="text-[0.625rem] text-[var(--text-muted)] uppercase tracking-wider font-medium">
            Session ID
          </span>
          <p className="text-[0.6875rem] text-[var(--text-muted)] mt-1 font-mono break-all select-all leading-relaxed">
            {selectedMemberId}
          </p>
        </div>
      </div>
    </div>
  );
}
