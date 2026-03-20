'use client';

import { useState, useCallback } from 'react';
import { useMessengerStore } from '@/store/useMessengerStore';
import { useAppStore } from '@/store/useAppStore';
import { useI18n } from '@/lib/i18n';
import { X, Bot, Loader2, UserPlus } from 'lucide-react';

const getRoleColor = (role: string) => {
  switch (role) {
    case 'developer': return 'from-blue-500 to-cyan-500';
    case 'researcher': return 'from-amber-500 to-orange-500';
    case 'planner': return 'from-teal-500 to-emerald-500';
    default: return 'from-emerald-500 to-green-500';
  }
};

const getRoleBadgeBg = (role: string) => {
  switch (role) {
    case 'developer': return 'linear-gradient(135deg, #3b82f6, #06b6d4)';
    case 'researcher': return 'linear-gradient(135deg, #f59e0b, #ea580c)';
    case 'planner': return 'linear-gradient(135deg, #14b8a6, #10b981)';
    default: return 'linear-gradient(135deg, #10b981, #059669)';
  }
};

export default function InviteMemberModal() {
  const { setInviteModalOpen, getActiveRoom, addMembersToRoom } = useMessengerStore();
  const { sessions } = useAppStore();
  const { t } = useI18n();

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [inviting, setInviting] = useState(false);

  const room = getActiveRoom();
  const existingIds = new Set(room?.session_ids ?? []);
  const availableSessions = sessions.filter(s => !existingIds.has(s.session_id));

  const toggle = (sid: string) => {
    setSelectedIds(prev =>
      prev.includes(sid) ? prev.filter(id => id !== sid) : [...prev, sid],
    );
  };

  const selectAll = () => {
    if (selectedIds.length === availableSessions.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(availableSessions.map(s => s.session_id));
    }
  };

  const handleInvite = useCallback(async () => {
    if (selectedIds.length === 0 || inviting) return;
    setInviting(true);
    try {
      await addMembersToRoom(selectedIds);
      setInviteModalOpen(false);
    } catch {
      /* ignore */
    } finally {
      setInviting(false);
    }
  }, [selectedIds, inviting, addMembersToRoom, setInviteModalOpen]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={() => setInviteModalOpen(false)}
      />

      {/* Modal */}
      <div className="relative w-full max-w-lg bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-2xl shadow-2xl flex flex-col max-h-[85vh] animate-[scaleIn_200ms_ease-out]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-color)]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--primary-color)] to-blue-600 flex items-center justify-center">
              <UserPlus size={14} className="text-white" />
            </div>
            <div>
              <h2 className="text-[0.9375rem] font-bold text-[var(--text-primary)]">
                {t('messenger.inviteTitle')}
              </h2>
              <p className="text-[0.6875rem] text-[var(--text-muted)]">
                {t('messenger.inviteDesc')}
              </p>
            </div>
          </div>
          <button
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-all border-none bg-transparent cursor-pointer"
            onClick={() => setInviteModalOpen(false)}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4">
          {availableSessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-center">
              <div className="w-12 h-12 rounded-full bg-[var(--bg-tertiary)] flex items-center justify-center mb-3">
                <UserPlus size={20} className="text-[var(--text-muted)]" />
              </div>
              <p className="text-[0.8125rem] text-[var(--text-muted)]">
                {t('messenger.noNewSessions')}
              </p>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between mb-3">
                <label className="text-[0.75rem] font-semibold text-[var(--text-secondary)] uppercase tracking-wider">
                  {t('messenger.selectSessions')}
                </label>
                <button
                  className="text-[0.6875rem] text-[var(--primary-color)] hover:underline border-none bg-transparent cursor-pointer font-medium"
                  onClick={selectAll}
                >
                  {selectedIds.length === availableSessions.length ? t('messenger.deselectAll') : t('messenger.selectAll')}
                </button>
              </div>

              <div className="space-y-1">
                {availableSessions.map(s => {
                  const alive = s.status === 'running';
                  const selected = selectedIds.includes(s.session_id);
                  return (
                    <div
                      key={s.session_id}
                      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border cursor-pointer transition-all ${
                        selected
                          ? 'border-[var(--primary-color)] bg-[var(--primary-subtle)]'
                          : 'border-[var(--border-color)] bg-[var(--bg-primary)] hover:border-[var(--border-subtle)]'
                      } ${!alive ? 'opacity-50' : ''}`}
                      onClick={() => toggle(s.session_id)}
                    >
                      {/* Checkbox */}
                      <div
                        className={`w-[18px] h-[18px] rounded border-2 flex items-center justify-center transition-all shrink-0 ${
                          selected
                            ? 'border-[var(--primary-color)] bg-[var(--primary-color)]'
                            : 'border-[var(--border-subtle)]'
                        }`}
                      >
                        {selected && (
                          <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
                            <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        )}
                      </div>

                      {/* Avatar */}
                      <div
                        className={`w-8 h-8 rounded-full bg-gradient-to-br ${getRoleColor(s.role || 'worker')} flex items-center justify-center shrink-0`}
                      >
                        <Bot size={13} className="text-white" />
                      </div>

                      {/* Info */}
                      <div className="flex-1 min-w-0">
                        <span className="text-[0.8125rem] font-medium text-[var(--text-primary)] truncate block">
                          {s.session_name || s.session_id.substring(0, 8)}
                        </span>
                      </div>

                      {/* Role badge */}
                      <span
                        className="px-1.5 py-0.5 rounded text-[0.5625rem] font-bold text-white uppercase tracking-wider shrink-0"
                        style={{ background: getRoleBadgeBg(s.role || 'worker') }}
                      >
                        {s.role || 'worker'}
                      </span>

                      {/* Status dot */}
                      <span
                        className={`w-2 h-2 rounded-full shrink-0 ${
                          alive
                            ? 'bg-[var(--success-color)] shadow-[0_0_4px_var(--success-color)]'
                            : 'bg-gray-400'
                        }`}
                      />
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="shrink-0 px-5 py-4 border-t border-[var(--border-color)] flex items-center justify-between">
          <span className="text-[0.75rem] text-[var(--text-muted)]">
            {selectedIds.length > 0 && `${selectedIds.length} ${t('messenger.selected')}`}
          </span>
          <div className="flex items-center gap-2">
            <button
              className="px-4 py-2 rounded-lg text-[0.8125rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-all border-none bg-transparent cursor-pointer"
              onClick={() => setInviteModalOpen(false)}
            >
              {t('messenger.cancel')}
            </button>
            <button
              className="px-5 py-2 rounded-lg bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium cursor-pointer border-none transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-sm flex items-center gap-1.5"
              disabled={selectedIds.length === 0 || inviting}
              onClick={handleInvite}
            >
              {inviting && <Loader2 size={13} className="animate-spin" />}
              <UserPlus size={13} />
              {t('messenger.invite')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
