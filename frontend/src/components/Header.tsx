'use client';

import Image from 'next/image';
import { useAppStore } from '@/store/useAppStore';

export default function Header() {
  const { healthStatus, sessions } = useAppStore();

  const isHealthy = healthStatus === 'connected';

  return (
    <header className="flex justify-between items-center px-6 h-14 bg-[var(--bg-secondary)] border-b border-[var(--border-color)]">
      <div className="flex items-center gap-3">
        {/* <Image
          src="/geny_logo.png"
          alt="Geny"
          width={160}
          height={44}
          className="h-11 w-auto object-contain"
          priority
        /> */}
        <span className="text-[0.9rem] text-[var(--text-tertiary)] tracking-[0.08em] italic hidden sm:inline">
          Geny Execute, Not You
        </span>
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
