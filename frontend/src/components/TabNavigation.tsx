'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';
import { useIsMobile } from '@/lib/useIsMobile';
import { ChevronDown, ExternalLink } from 'lucide-react';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

// Consolidated tab strip:
//   - `library` (global) hosts pipeline-DESIGN sub-tabs: env catalog,
//     tool sets, permission rules, hooks, skills, mcp server defs.
//     Operates on system-wide files (settings.json, mcp/custom/, ...).
//   - `sessionEnvironment` (session) hosts per-session sub-tabs:
//     manifest of bound env, currently-loaded tools, workspace stack.
//
// Critical: global ID is `library`, NOT `environment`. The old
// `environment` ID was always the session-scoped tab and we keep that
// meaning via setActiveTab back-compat redirect — colliding ids would
// bounce the operator to the wrong scope (which is exactly what the
// previous PR did).
//
// Playground / Playground2D are intentionally omitted — code path
// kept; UI surface hidden until they become first-class again.
// Cycle 20260427_2 — visual 21-stage env builder relocated to its own
// /environments page (header nav button), no longer a tab here.
// Cycle 20260429 Phase 6 — `library` was the prototype for env+host
// CRUD; its sub-tabs (hooks/skills/permissions/mcpServers/toolSets)
// moved to /environments?tab=... top-level tabs (#553). The Header
// component owns the entry point to /environments via its dedicated
// link button, so nothing in this strip points to it anymore.
// 클라우드 sits between them by design: it is the storage layer the
// whole product now hangs on, not a per-session detail.
const GLOBAL_TAB_IDS = ['main', 'cloud', 'settings'] as const;
// SESSION_TAB_DEFS:
//   - ``id`` — pairs with ``activeTab`` so the strip highlights the
//     right entry.
//   - ``accent`` (optional) — primary-coloured rendering for the
//     command tab.
//   - ``external`` (optional) — when set, the entry behaves like a
//     "shortcut" instead of an in-app tab. Clicking it opens
//     ``external(sessionId)`` in a new browser tab and *does not*
//     change ``activeTab``. The current memory view is provided by
//     the dedicated Opsidian app (``/opsidian``); there's no
//     separate in-Geny memory tab any more — keeping it as a
//     shortcut preserves the user's muscle memory while routing
//     them straight to the canonical UI. Cycle 20260503_3.
// command / vtuber are the SAME slot — the session's primary surface, styled
// identically (accent). A general agent shows only `command`; a VTuber agent
// shows only `vtuber`. The rest follow in a fixed order:
// Tasks · Hooks · Canvas · Storage · Memory · Logs.
const SESSION_TAB_DEFS = [
  { id: 'command', accent: true },
  { id: 'vtuber', accent: true },
  { id: 'tasks' },     // PR-D.3.1 — BackgroundTaskRunner viewer (runtime state, stays separate)
  { id: 'hooks' },     // user automations — agent-created (HookCreate); replaces the old Cron tab
  { id: 'canvas' },    // session files-workspace browser + live document preview (workspace-canvas P4)
  { id: 'storage' },
  {
    id: 'memory',
    external: (sessionId: string | null) =>
      sessionId
        ? `/opsidian?sessionId=${encodeURIComponent(sessionId)}`
        : '/opsidian',
  },
  { id: 'logs' },
] as const;

type SessionTabDef = (typeof SESSION_TAB_DEFS)[number];

const TAB_BASE =
  'relative py-1.5 px-3 text-[0.8125rem] font-medium bg-transparent border-none rounded-md cursor-pointer transition-colors duration-150 whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]';

function TabButton({
  id,
  label,
  active,
  onClick,
  accent,
  external,
}: {
  id: string;
  label: string;
  active: boolean;
  onClick: () => void;
  accent?: boolean;
  external?: boolean;
}) {
  if (accent) {
    return (
      <button
        key={id}
        className={cn(
          TAB_BASE,
          'mr-0.5 font-semibold',
          active
            ? 'text-[hsl(var(--primary-foreground))] bg-[hsl(var(--primary))]'
            : 'text-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)] hover:bg-[hsl(var(--primary)/0.16)]',
        )}
        onClick={onClick}
      >
        {label}
        {active && (
          <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-5 h-0.5 rounded-sm bg-[hsl(var(--primary))]" />
        )}
      </button>
    );
  }
  return (
    <button
      key={id}
      className={cn(
        TAB_BASE,
        external
          ? 'inline-flex items-center gap-1 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))]'
          : active
            ? 'text-[hsl(var(--foreground))] bg-[hsl(var(--accent))]'
            : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))]',
      )}
      onClick={onClick}
      title={external ? `${label} — opens in a new tab` : undefined}
    >
      {label}
      {external && <ExternalLink size={11} className="opacity-70" />}
      {!external && active && (
        <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-5 h-0.5 rounded-sm bg-[hsl(var(--primary))]" />
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
  sessionTabs: {
    id: string;
    accent?: boolean;
    /** Resolved URL — when present, the entry is a "shortcut"
     * that opens in a new browser tab instead of switching the
     * in-app activeTab. */
    external?: string;
  }[];
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
        >          {sessionTabs.map(tab => {
            const handleClick = () => {
              if (tab.external) {
                if (typeof window !== 'undefined') {
                  window.open(tab.external, '_blank', 'noopener,noreferrer');
                }
                setOpen(false);
                return;
              }
              onSelect(tab.id);
              setOpen(false);
            };
            return (
              <button
                key={tab.id}
                className={cn(
                  'w-full text-left px-3 py-2 text-[0.75rem] font-medium border-none cursor-pointer transition-colors flex items-center justify-between gap-2',
                  // External tabs never highlight as "active" — they
                  // never become the in-app activeTab.
                  !tab.external && activeTab === tab.id
                    ? 'text-[var(--primary-color)] bg-[hsl(var(--primary)/0.1)]'
                    : 'text-[var(--text-secondary)] bg-transparent hover:bg-[var(--bg-hover)]',
                )}
                onClick={handleClick}
              >
                <span>{t(`tabs.${tab.id}`)}</span>
                {tab.external && <ExternalLink size={11} className="opacity-70" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function TabNavigation() {
  const { activeTab, setActiveTab, selectedSessionId, sessions } = useAppStore();
  const { t } = useI18n();
  const isMobile = useIsMobile();

  const selectedSession = sessions.find(s => s.session_id === selectedSessionId);
  const hasSession = !!selectedSessionId && !!selectedSession;

  const sessionName = selectedSession?.session_name
    || selectedSessionId?.substring(0, 10)
    || '';

  // command vs vtuber = the SAME primary slot, split by agent type. A VTuber
  // agent gets only the VTuber tab; every other agent gets only Command. The
  // rest of the session tabs are always visible.
  const isVtuber = selectedSession?.role === 'vtuber';
  const visibleGlobalTabs = GLOBAL_TAB_IDS;
  const visibleSessionTabs = SESSION_TAB_DEFS.filter((tab) => {
    if (tab.id === 'command') return !isVtuber;
    if (tab.id === 'vtuber') return isVtuber;
    return true;
  });

  // Keep activeTab off the hidden primary slot: a VTuber session must never
  // sit on `command` (hidden) and vice-versa — redirect to the visible one.
  useEffect(() => {
    if (!hasSession) return;
    if (isVtuber && activeTab === 'command') setActiveTab('vtuber');
    else if (!isVtuber && activeTab === 'vtuber') setActiveTab('command');
  }, [hasSession, isVtuber, activeTab, setActiveTab]);

  // Click handler for session tabs. Tabs with an ``external`` marker
  // open the resolved URL in a new browser tab and *do not* toggle
  // ``activeTab`` — keeps the user's current in-app view stable
  // while routing them to the canonical Opsidian UI for memory.
  const handleSessionTabClick = useCallback(
    (tab: SessionTabDef) => {
      if ('external' in tab && typeof tab.external === 'function') {
        const href = tab.external(selectedSessionId ?? null);
        if (typeof window !== 'undefined') {
          window.open(href, '_blank', 'noopener,noreferrer');
        }
        return;
      }
      setActiveTab(tab.id);
    },
    [selectedSessionId, setActiveTab],
  );

  return (
    <div className="flex items-center gap-0.5 h-11 px-2 md:px-4 bg-[hsl(var(--card))] border-b border-[hsl(var(--border))] shrink-0 overflow-x-auto overflow-y-hidden scrollbar-hide">
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
                ...visibleSessionTabs.map(tab => ({
                  id: tab.id,
                  accent: 'accent' in tab ? tab.accent : undefined,
                  external: 'external' in tab && typeof tab.external === 'function'
                    ? tab.external(selectedSessionId ?? null)
                    : undefined,
                })),
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
                    ? 'text-white bg-[var(--primary-color)] border-[var(--primary-color)] shadow-[0_0_10px_hsl(var(--primary)/0.3)]'
                    : 'text-[var(--primary-color)] bg-[hsl(var(--primary)/0.08)] border-[hsl(var(--primary)/0.18)] hover:bg-[hsl(var(--primary)/0.16)]',
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
              {visibleSessionTabs.map(tab => {
                const isExternal = 'external' in tab && typeof tab.external === 'function';
                return (
                  <TabButton
                    key={tab.id}
                    id={tab.id}
                    label={t(`tabs.${tab.id}`)}
                    // External tabs never report "active" — they
                    // are shortcuts, not in-app views.
                    active={!isExternal && activeTab === tab.id}
                    onClick={() => handleSessionTabClick(tab)}
                    accent={'accent' in tab && tab.accent}
                    external={isExternal}
                  />
                );
              })}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
