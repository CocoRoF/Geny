'use client';

import { useAppStore } from '@/store/useAppStore';
import { twMerge } from 'tailwind-merge';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

const GLOBAL_TABS = [
  { id: 'main', label: 'Main' },
  { id: 'playground', label: 'Playground' },
  { id: 'workflows', label: 'Workflows' },
  { id: 'settings', label: 'Settings' },
];

const SESSION_TABS = [
  { id: 'info', label: 'Info' },
  { id: 'graph', label: 'Graph' },
  { id: 'command', label: 'Command' },
  { id: 'dashboard', label: 'Dashboard', managerOnly: true },
  { id: 'storage', label: 'Storage' },
  { id: 'logs', label: 'Logs' },
];

const TAB_BASE =
  'relative py-1.5 px-3.5 text-[0.8125rem] font-medium bg-transparent border-none rounded-[6px] cursor-pointer transition-all duration-150 whitespace-nowrap';

function TabButton({ id, label, active, onClick }: { id: string; label: string; active: boolean; onClick: () => void }) {
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
  const { activeTab, setActiveTab, selectedSessionId, sessions } = useAppStore();

  const selectedSession = sessions.find(s => s.session_id === selectedSessionId);
  const hasSession = !!selectedSessionId && !!selectedSession;
  const showDashboard = selectedSession?.role === 'manager';

  const sessionName = selectedSession?.session_name
    || selectedSessionId?.substring(0, 10)
    || '';

  return (
    <div className="flex items-center gap-0.5 h-11 px-4 bg-[var(--bg-secondary)] border-b border-[var(--border-color)] shrink-0">
      {/* ── Global Tabs ── */}
      <div className="flex items-center gap-0.5">
        {GLOBAL_TABS.map(tab => (
          <TabButton
            key={tab.id}
            id={tab.id}
            label={tab.label}
            active={activeTab === tab.id}
            onClick={() => setActiveTab(tab.id)}
          />
        ))}
      </div>

      {/* ── Session Tabs ── */}
      {hasSession && (
        <>
          <div className="w-px h-5 mx-2 bg-[var(--border-color)] shrink-0" />
          <div
            className="flex items-center gap-1.5 py-[3px] px-2.5 mr-1 text-[0.6875rem] font-semibold text-[var(--primary-color)] bg-[rgba(59,130,246,0.08)] border border-[rgba(59,130,246,0.18)] rounded-[10px] whitespace-nowrap max-w-[140px] overflow-hidden text-ellipsis shrink-0 tracking-[0.01em]"
            title={selectedSession?.session_id}
          >
            <span
              className={cn(
                'w-1.5 h-1.5 rounded-full shrink-0',
                selectedSession?.status === 'running'
                  ? 'bg-[var(--success-color)] shadow-[0_0_4px_var(--success-color)]'
                  : 'bg-[var(--text-muted)]',
              )}
            />
            {sessionName}
          </div>
          <div className="flex items-center gap-0.5">
            {SESSION_TABS.filter(tab => !tab.managerOnly || showDashboard).map(tab => (
              <TabButton
                key={tab.id}
                id={tab.id}
                label={tab.label}
                active={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
