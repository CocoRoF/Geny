'use client';

import { useAppStore } from '@/store/useAppStore';

export default function Header() {
  const { healthStatus, sessions } = useAppStore();

  const isHealthy = healthStatus === 'connected';

  return (
    <header className="flex justify-between items-center px-6 h-14 bg-[var(--bg-secondary)] border-b border-[var(--border-color)]">
      <div className="flex items-center gap-3">
        <h1 className="text-[1.125rem] font-semibold text-[var(--text-primary)] tracking-tight">
          Claude Control
        </h1>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-[var(--bg-tertiary)] rounded-full text-[0.8125rem]">
          <span
            className={`w-2 h-2 rounded-full shrink-0 ${
              isHealthy
                ? 'bg-[var(--success-color)]'
                : 'bg-[var(--danger-color)]'
            }`}
            style={isHealthy ? { boxShadow: '0 0 8px var(--success-color)' } : undefined}
          />
          <span className="text-[var(--text-secondary)]">
            {isHealthy ? `${sessions.length} sessions` : 'Disconnected'}
          </span>
        </div>
      </div>
    </header>
  );
}
