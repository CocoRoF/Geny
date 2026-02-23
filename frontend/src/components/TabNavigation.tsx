'use client';

import { useAppStore } from '@/store/useAppStore';

const TABS = [
  { id: 'playground', label: 'Playground' },
  { id: 'command', label: 'Command' },
  { id: 'dashboard', label: 'Dashboard', managerOnly: true },
  { id: 'logs', label: 'Logs' },
  { id: 'storage', label: 'Storage' },
  { id: 'batch', label: 'Batch' },
  { id: 'graph', label: 'Graph' },
  { id: 'info', label: 'Info' },
  { id: 'settings', label: 'Settings' },
];

export default function TabNavigation() {
  const { activeTab, setActiveTab, selectedSessionId, sessions } = useAppStore();

  const selectedSession = sessions.find(s => s.session_id === selectedSessionId);
  const showDashboard = selectedSession?.role === 'manager';

  return (
    <div className="flex items-center gap-0.5 h-12 px-5 bg-[var(--bg-secondary)] border-b border-[var(--border-color)]">
      {TABS.filter(tab => !tab.managerOnly || showDashboard).map(tab => (
        <button
          key={tab.id}
          className={`relative px-4 py-1.5 text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 bg-transparent border-none
            ${activeTab === tab.id
              ? 'text-[var(--text-primary)] bg-[var(--bg-tertiary)]'
              : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
            }`}
          onClick={() => setActiveTab(tab.id)}
        >
          {tab.label}
          {activeTab === tab.id && (
            <span
              className="absolute left-1/2 -translate-x-1/2 w-6 h-0.5 rounded-sm bg-[var(--primary-color)]"
              style={{ bottom: '-12px' }}
            />
          )}
        </button>
      ))}
    </div>
  );
}
