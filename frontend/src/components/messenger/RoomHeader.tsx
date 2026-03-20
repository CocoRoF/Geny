'use client';

import { useMessengerStore } from '@/store/useMessengerStore';
import { useAppStore } from '@/store/useAppStore';
import { useI18n } from '@/lib/i18n';
import { Hash, Menu, Bot, UserPlus } from 'lucide-react';

const getRoleColor = (role: string) => {
  switch (role) {
    case 'developer': return 'from-blue-500 to-cyan-500';
    case 'researcher': return 'from-amber-500 to-orange-500';
    case 'planner': return 'from-teal-500 to-emerald-500';
    default: return 'from-emerald-500 to-green-500';
  }
};

export default function RoomHeader() {
  const { getActiveRoom, setMobileSidebarOpen, setSelectedMemberId, setInviteModalOpen } = useMessengerStore();
  const { sessions } = useAppStore();
  const { t } = useI18n();

  const room = getActiveRoom();
  if (!room) return null;

  const memberEntries = room.session_ids.map(sid => {
    const found = sessions.find(s => s.session_id === sid);
    return { sid, session: found ?? null };
  });

  const aliveCount = memberEntries.filter(e => e.session?.status === 'running').length;

  return (
    <div className="shrink-0 h-14 px-4 flex items-center justify-between bg-[var(--bg-secondary)] border-b border-[var(--border-color)]">
      {/* Left */}
      <div className="flex items-center gap-3 min-w-0">
        {/* Mobile menu button */}
        <button
          className="flex md:hidden items-center justify-center w-8 h-8 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-all border-none bg-transparent cursor-pointer"
          onClick={() => setMobileSidebarOpen(true)}
        >
          <Menu size={18} />
        </button>

        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--primary-color)] to-blue-600 flex items-center justify-center shadow-sm">
          <Hash size={14} className="text-white" />
        </div>
        <div className="min-w-0">
          <h2 className="text-[0.875rem] font-semibold text-[var(--text-primary)] truncate leading-tight">
            {room.name}
          </h2>
          <span className="text-[0.6875rem] text-[var(--text-muted)]">
            {room.session_ids.length} {t('messenger.members')}
          </span>
        </div>
      </div>

      {/* Right — Member avatars */}
      <div className="flex items-center gap-3">
        {/* Invite button */}
        <button
          className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--primary-color)] hover:bg-[var(--bg-hover)] transition-all border-none bg-transparent cursor-pointer"
          title={t('messenger.inviteMembers')}
          onClick={() => setInviteModalOpen(true)}
        >
          <UserPlus size={16} />
        </button>

        {/* Member avatar stack */}
        <div className="hidden sm:flex items-center -space-x-1.5">
          {memberEntries.slice(0, 5).map((entry) => {
            const s = entry.session;
            const isGone = !s;
            return (
              <button
                key={entry.sid}
                className={`w-7 h-7 rounded-full flex items-center justify-center border-2 border-[var(--bg-secondary)] shadow-sm cursor-pointer transition-transform hover:scale-110 hover:z-10 ${
                  isGone
                    ? 'bg-[var(--bg-tertiary)] opacity-50'
                    : `bg-gradient-to-br ${getRoleColor(s?.role || 'worker')}`
                }`}
                title={s?.session_name || entry.sid.substring(0, 8)}
                onClick={() => setSelectedMemberId(entry.sid)}
              >
                <Bot size={11} className={isGone ? 'text-[var(--text-muted)]' : 'text-white'} />
              </button>
            );
          })}
          {memberEntries.length > 5 && (
            <div className="w-7 h-7 rounded-full bg-[var(--bg-tertiary)] border-2 border-[var(--bg-secondary)] flex items-center justify-center text-[0.5625rem] font-semibold text-[var(--text-muted)]">
              +{memberEntries.length - 5}
            </div>
          )}
        </div>

        {/* Active status */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
          <span className={`w-1.5 h-1.5 rounded-full ${aliveCount > 0 ? 'bg-[var(--success-color)] shadow-[0_0_4px_var(--success-color)]' : 'bg-[var(--text-muted)]'}`} />
          <span className="text-[0.6875rem] text-[var(--text-secondary)]">
            {aliveCount} {t('messenger.online')}
          </span>
        </div>
      </div>
    </div>
  );
}
