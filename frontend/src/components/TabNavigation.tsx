'use client';

import { useState, useRef, useEffect } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { useAuthStore } from '@/store/useAuthStore';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';
import { useIsMobile } from '@/lib/useIsMobile';
import { ChevronDown } from 'lucide-react';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

const GLOBAL_TAB_IDS = ['main', 'playground', 'workflows', 'toolSets', 'sharedFolder', 'settings'] as const;
const SESSION_TAB_DEFS = [
  { id: 'command', accent: true },
  { id: 'vtuber' },
  { id: 'graph' },
  { id: 'memory' },
  { id: 'storage' },
  { id: 'sessionTools' },
  { id: 'logs' },
] as const;

// Tabs hidden in Normal mode
const DEV_ONLY_GLOBAL = new Set(['workflows', 'toolSets', 'settings']);
// 'logs' is intentionally NOT in this set — it must be visible in User mode too (e.g. mobile)
const DEV_ONLY_SESSION = new Set(['graph']);

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

/** Mobile dropdown for session tabs */
function MobileSessionTabDropdown({
  activeTab,
  sessionName,
  sessionStatus,
  sessionTabs,
  t,
  onSelect,
}: {
  activeTab: string;
  sessionName: string;
  sessionStatus?: string;
  sessionTabs: { id: string; accent?: boolean }[];
  t: (key: string) => string;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  // Close on outside click/touch
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent | TouchEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    document.addEventListener('touchstart', handler);
    return () => {
      document.removeEventListener('mousedown', handler);
      document.removeEventListener('touchstart', handler);
    };
  }, [open]);

  const toggle = () => {
    if (!open && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 4, left: rect.left });
    }
    setOpen(!open);
  };

  const isSessionTab = sessionTabs.some(tab => tab.id === activeTab);
  const activeLabel = isSessionTab ? t(`tabs.${activeTab}`) : t('tabs.command');

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        ref={btnRef}
        className={cn(
          'flex items-center gap-1.5 py-1 px-2.5 rounded-md text-[0.75rem] font-semibold border cursor-pointer transition-all',
          'text-white bg-[var(--primary-color)] border-[var(--primary-color)]',
        )}
        onClick={toggle}
      >
        <span
          className={cn(
            'w-1.5 h-1.5 rounded-full shrink-0',
            sessionStatus === 'running'
              ? 'bg-[var(--success-color)] shadow-[0_0_4px_var(--success-color)]'
              : 'bg-white/60',
          )}
        />
        <span className="max-w-[80px] truncate">{sessionName}</span>
        <span className="opacity-70">·</span>
        <span>{activeLabel}</span>
        <ChevronDown size={12} className={cn('transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div
          className="fixed z-50 min-w-[140px] py-1 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg shadow-lg"
          style={{ top: pos.top, left: pos.left }}
        >          {sessionTabs.map(tab => (
            <button
              key={tab.id}
              className={cn(
                'w-full text-left px-3 py-2 text-[0.75rem] font-medium border-none cursor-pointer transition-colors',
                activeTab === tab.id
                  ? 'text-[var(--primary-color)] bg-[rgba(59,130,246,0.1)]'
                  : 'text-[var(--text-secondary)] bg-transparent hover:bg-[var(--bg-hover)]',
              )}
              onClick={() => { onSelect(tab.id); setOpen(false); }}
            >
              {t(`tabs.${tab.id}`)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function TabNavigation() {
  const { activeTab, setActiveTab, selectedSessionId, sessions, devMode } = useAppStore();
  const { isAuthenticated, hasUsers } = useAuthStore();
  const { t } = useI18n();
  const isMobile = useIsMobile();

  const selectedSession = sessions.find(s => s.session_id === selectedSessionId);
  const hasSession = !!selectedSessionId && !!selectedSession;

  const sessionName = selectedSession?.session_name
    || selectedSessionId?.substring(0, 10)
    || '';

  // Dev-only tabs require both devMode AND authentication (when auth is set up)
  const canShowDevTabs = devMode && (!hasUsers || isAuthenticated);
  const visibleGlobalTabs = GLOBAL_TAB_IDS.filter(id => canShowDevTabs || !DEV_ONLY_GLOBAL.has(id));
  const visibleSessionTabs = SESSION_TAB_DEFS.filter(tab => canShowDevTabs || !DEV_ONLY_SESSION.has(tab.id));

  return (
    <div className="flex items-center gap-0.5 h-11 px-2 md:px-4 bg-[var(--bg-secondary)] border-b border-[var(--border-color)] shrink-0 overflow-x-auto scrollbar-hide">
      {/* ── Global Tabs ── */}
      <div className="flex items-center gap-0.5 shrink-0">
        {visibleGlobalTabs.map(id => (
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

          {isMobile ? (
            /* Mobile: single dropdown combining session name + all session tabs */
            <MobileSessionTabDropdown
              activeTab={activeTab}
              sessionName={sessionName}
              sessionStatus={selectedSession?.status}
              sessionTabs={[
                { id: 'info' },
                ...visibleSessionTabs.map(t => ({ id: t.id, accent: 'accent' in t ? t.accent : undefined })),
              ]}
              t={t}
              onSelect={setActiveTab}
            />
          ) : (
            <>
              {/* Session name badge */}
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
              {visibleSessionTabs.map(tab => (
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
        </>
      )}
    </div>
  );
}
