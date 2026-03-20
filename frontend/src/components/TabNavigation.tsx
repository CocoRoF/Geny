'use client';

import { useAppStore } from '@/store/useAppStore';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

const GLOBAL_TAB_IDS = ['main', 'playground', 'workflows', 'sharedFolder', 'settings'] as const;
const SESSION_TAB_DEFS = [
  { id: 'command', accent: true },
  { id: 'graph' },
  { id: 'storage' },
  { id: 'sessionTools' },
  { id: 'logs' },
] as const;

// Tabs hidden in Normal mode
const DEV_ONLY_GLOBAL = new Set(['workflows', 'settings']);
const DEV_ONLY_SESSION = new Set(['logs', 'graph']);

const TAB_BASE =
  'relative py-1.5 px-3.5 text-[0.8125rem] font-medium bg-transparent border-none rounded-[6px] cursor-pointer transition-all duration-150 whitespace-nowrap';

function TabButton({ id, label, active, onClick, accent }: { id: string; label: string; active: boolean; onClick: () => void; accent?: boolean }) {
  if (accent) {
    return (
      <button
        key={id}
        className={cn(
          TAB_BASE,
          'mr-0.5 font-semibold',
          active
            ? 'text-white bg-[var(--primary-color)] shadow-[0_0_8px_rgba(59,130,246,0.3)]'
            : 'text-[var(--primary-color)] bg-[rgba(59,130,246,0.08)] hover:bg-[rgba(59,130,246,0.18)]',
        )}
        onClick={onClick}
      >
        {label}
        {active && (
          <span className="absolute -bottom-[9px] left-1/2 -translate-x-1/2 w-5 h-0.5 rounded-sm bg-[var(--primary-color)]" />
        )}
      </button>
    );
  }
  return (
    <button
      key={id}
      className={cn(
        TAB_BASE,
        active
          ? 'text-[var(--text-primary)] bg-[var(--bg-tertiary)]'
          : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]',
      )}
      onClick={onClick}
    >
      {label}
      {active && (
        <span className="absolute -bottom-[9px] left-1/2 -translate-x-1/2 w-5 h-0.5 rounded-sm bg-[var(--primary-color)]" />
      )}
    </button>
  );
}

export default function TabNavigation() {
  const { activeTab, setActiveTab, selectedSessionId, sessions, devMode } = useAppStore();
  const { t } = useI18n();

  const selectedSession = sessions.find(s => s.session_id === selectedSessionId);
  const hasSession = !!selectedSessionId && !!selectedSession;

  const sessionName = selectedSession?.session_name
    || selectedSessionId?.substring(0, 10)
    || '';

  return (
    <div className="flex items-center gap-0.5 h-11 px-2 md:px-4 bg-[var(--bg-secondary)] border-b border-[var(--border-color)] shrink-0 overflow-x-auto scrollbar-hide">
      {/* ── Global Tabs ── */}
      <div className="flex items-center gap-0.5 shrink-0">
        {GLOBAL_TAB_IDS
          .filter(id => devMode || !DEV_ONLY_GLOBAL.has(id))
          .map(id => (
          <TabButton
            key={id}
            id={id}
            label={t(`tabs.${id}`)}
            active={activeTab === id}
            onClick={() => setActiveTab(id)}
          />
        ))}
      </div>

      {/* ── Session Tabs ── */}
      {hasSession && (
        <>
          <div className="w-px h-5 mx-2 bg-[var(--border-color)] shrink-0" />
          <button
            className={cn(
              'flex items-center gap-1.5 py-[3px] px-2.5 mr-1 text-[0.6875rem] font-semibold rounded-[10px] whitespace-nowrap max-w-[140px] overflow-hidden text-ellipsis shrink-0 tracking-[0.01em] border cursor-pointer transition-all duration-150',
              activeTab === 'info'
                ? 'text-white bg-[var(--primary-color)] border-[var(--primary-color)] shadow-[0_0_8px_rgba(59,130,246,0.25)]'
                : 'text-[var(--primary-color)] bg-[rgba(59,130,246,0.08)] border-[rgba(59,130,246,0.18)] hover:bg-[rgba(59,130,246,0.16)]',
            )}
            title={selectedSession?.session_id}
            onClick={() => setActiveTab('info')}
          >
            <span
              className={cn(
                'w-1.5 h-1.5 rounded-full shrink-0',
                selectedSession?.status === 'running'
                  ? 'bg-[var(--success-color)] shadow-[0_0_4px_var(--success-color)]'
                  : activeTab === 'info' ? 'bg-white/60' : 'bg-[var(--text-muted)]',
              )}
            />
            {sessionName}
          </button>
          <div className="flex items-center gap-0.5">
            {SESSION_TAB_DEFS
              .filter(tab => devMode || !DEV_ONLY_SESSION.has(tab.id))
              .map(tab => (
              <TabButton
                key={tab.id}
                id={tab.id}
                label={t(`tabs.${tab.id}`)}
                active={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
                accent={'accent' in tab && tab.accent}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
