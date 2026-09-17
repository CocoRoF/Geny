'use client';

/**
 * /connector — the desktop connector's control panel (loaded in the control
 * window). Reuses the dashboard's proven control components, no porting:
 * session picker, avatar-model picker, and the full chat panel. A normal
 * browser can open it too (when logged in); inside the Electron connector it
 * also drives the floating overlay's session via window.connector (preload).
 *
 * Query: ?token (→localStorage), ?session (preselect).
 */

import { useEffect, useRef, useState, type SVGProps } from 'react';
import { RefreshCw, ExternalLink, Settings, Power } from 'lucide-react';
import { setToken } from '@/lib/authApi';
import { IconButton } from '@/components/common/layout';
import { useAppStore } from '@/store/useAppStore';
import { useVTuberStore } from '@/store/useVTuberStore';
import { useTheme, type Theme } from '@/lib/theme';
import VTuberChatPanel from '@/components/live2d/VTuberChatPanel';

// CRITICAL: this is the chat window, a SEPARATE renderer process from the avatar
// overlay. If TTS ran here too, audio would play twice (two AudioManagers). Voice
// (TTS/STT) and screen-scan live ONLY in the avatar window; here we force TTS off
// at module load (before any message can arrive) so chat is silent view+send.
useVTuberStore.setState({ ttsEnabled: false });

/** Resolve the connector's ?theme (dark|light|system) to a concrete theme. */
function resolveConnectorTheme(): Theme | null {
  if (typeof window === 'undefined') return null;
  const t = new URLSearchParams(window.location.search).get('theme');
  if (!t) return null; // plain browser → leave the user's own preference alone
  if (t === 'light' || t === 'dark') return t;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

// Apply the connector theme at module load too, so there's no dark→light flash
// before React mounts (the ThemeProvider FOUC script defaults to dark).
(() => {
  const resolved = resolveConnectorTheme();
  if (!resolved) return;
  try {
    localStorage.setItem('geny-theme-preference', resolved);
    const r = document.documentElement;
    r.classList.remove('light', 'dark');
    r.classList.add(resolved);
    r.style.colorScheme = resolved;
  } catch {
    /* ignore */
  }
})();

// ── icons (1.6 stroke, currentColor) ─────────────────────────────────────────
const ic = (p: SVGProps<SVGSVGElement>) => ({
  viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
  strokeWidth: 1.7, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, ...p,
});
const ChevronIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...ic(p)}><path d="m6 9 6 6 6-6" /></svg>
);
const MonitorIcon = (p: SVGProps<SVGSVGElement>) => (
  <svg {...ic(p)}><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></svg>
);
const TOOLBAR_SELECT =
  'appearance-none h-8 pl-2.5 pr-7 text-[0.78rem] rounded-lg bg-[var(--bg-tertiary)]/60 ' +
  'border border-[var(--border-color)] text-[var(--text-primary)] outline-none cursor-pointer ' +
  'min-w-[120px] max-w-[210px] transition-colors hover:border-[var(--border-subtle)] ' +
  'focus:border-[var(--primary-color)] focus:ring-2 focus:ring-[var(--primary-subtle)]';

export default function ConnectorPage() {
  const sessions = useAppStore((s) => s.sessions);
  const selectedSessionId = useAppStore((s) => s.selectedSessionId);
  const loadSessions = useAppStore((s) => s.loadSessions);
  const selectSession = useAppStore((s) => s.selectSession);

  const models = useVTuberStore((s) => s.models);
  const modelsLoaded = useVTuberStore((s) => s.modelsLoaded);
  const fetchModels = useVTuberStore((s) => s.fetchModels);
  const fetchAssignment = useVTuberStore((s) => s.fetchAssignment);
  const assignModel = useVTuberStore((s) => s.assignModel);
  const assignedModelName = useVTuberStore((s) => (selectedSessionId ? s.assignments[selectedSessionId] : undefined));

  const { setTheme } = useTheme();
  const [booted, setBooted] = useState(false);
  // Desktop-only controls depend on window.connector, which doesn't exist during
  // SSR. Reading it directly in render diverged SSR (false) from the connector's
  // client render (true) → a hydration mismatch (React #418) that blanked the
  // whole page INSIDE the connector (a plain browser has no window.connector, so
  // it never mismatched — which is why it only broke in the desktop app). Resolve
  // it after mount so SSR and the first client render agree.
  const [isDesktop, setIsDesktop] = useState(false);
  useEffect(() => {
    setIsDesktop(typeof window !== 'undefined' && !!window.connector);
  }, []);
  // The session the connector is bound to (?session = overlaySession). The
  // restore logic must always prefer THIS over "first VTuber" — otherwise a
  // restart can land on a different VTuber and overwrite overlaySession with it,
  // poisoning every future restart (and losing the bound model in the picker).
  const wantSessionRef = useRef<string | null>(null);

  // Pull the current assignment for the selected session so the model picker
  // shows what's actually bound (it was empty before). After this, the live
  // assignment stream (wired in fetchModels) keeps it in sync with the web +
  // overlay without polling.
  useEffect(() => {
    if (selectedSessionId) fetchAssignment(selectedSessionId);
  }, [selectedSessionId, fetchAssignment]);

  // Sync the connector's ?theme into the ThemeProvider store (module-load
  // already painted the class for no-flash; this keeps React state in sync).
  useEffect(() => {
    const resolved = resolveConnectorTheme();
    if (resolved) setTheme(resolved);
  }, [setTheme]);

  // token + initial data + session preselect (once).
  useEffect(() => {
    const qs = new URLSearchParams(window.location.search);
    const token = qs.get('token');
    if (token) setToken(token);
    const wantSession = qs.get('session');
    wantSessionRef.current = wantSession;

    (async () => {
      await loadSessions();
      if (!modelsLoaded) fetchModels();
      // Honour ?session only if it still exists — a stale/deleted id would
      // otherwise block the auto-select below. The correction effect heals it.
      if (wantSession && useAppStore.getState().sessions.some((s) => s.session_id === wantSession)) {
        pickSession(wantSession);
      }
      setBooted(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Land on a session and correct a stale selection, so the panel + overlay
  // self-heal onto one that exists. Prefer the BOUND session (?session =
  // overlaySession) over "the first one" — landing elsewhere would overwrite
  // overlaySession (pickSession syncs it) and lose the user's session across
  // restarts. A VTuber is preferred only because this window can also drive an
  // avatar; any session can be talked to.
  useEffect(() => {
    if (!booted) return;
    if (sessions.some((s) => s.session_id === selectedSessionId)) return;
    const want = wantSessionRef.current;
    const bound = want ? sessions.find((s) => s.session_id === want) : undefined;
    const target = bound ?? sessions.find((s) => s.role === 'vtuber') ?? sessions[0];
    if (target) pickSession(target.session_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [booted, sessions, selectedSessionId]);

  // Select a session AND sync the floating overlay to it (connector only).
  const pickSession = (id: string) => {
    selectSession(id);
    window.connector?.windowControl.setOverlaySession(id);
  };

  const current = sessions.find((s) => s.session_id === selectedSessionId);
  const isVTuber = current?.role === 'vtuber';
  const sid = selectedSessionId ?? '';
  // Every session has a conversation — the panel asks the server which room
  // it is and the server makes one if this session has never spoken. Waiting
  // for a `chat_room_id` on the session row meant only VTubers could be
  // talked to here, which is not what a room is for.
  const ready = Boolean(current);

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-[var(--bg-primary)] text-[var(--text-primary)]">
      {/* Toolbar — auto-height (min-h + flex-wrap) so it never clips when it
          wraps on a narrow window; one clean row at the default width. */}
      <header
        className="flex items-center gap-x-2.5 gap-y-2 px-3.5 py-2.5 min-h-[56px] shrink-0 flex-wrap border-b border-[var(--border-color)]"
        style={{ background: 'linear-gradient(180deg, var(--bg-secondary) 0%, var(--bg-primary) 140%)' }}
      >
        {/* session */}
        <div className="flex items-center gap-1.5">
          <span className="text-[0.62rem] font-semibold tracking-wider uppercase text-[var(--text-muted)]">세션</span>
          <div className="relative">
            <select className={TOOLBAR_SELECT} value={sid} onChange={(e) => pickSession(e.target.value)}>
              <option value="" disabled>세션 선택…</option>
              {sessions.map((s) => (
                <option key={s.session_id} value={s.session_id}>{s.session_name || s.session_id.slice(0, 8)}</option>
              ))}
            </select>
            <ChevronIcon className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--text-muted)]" />
          </div>
          <IconButton icon={RefreshCw} title="세션 목록 새로고침" onClick={() => loadSessions()} />
        </div>

        {/* model */}
        {isVTuber && (
          <div className="flex items-center gap-1.5">
            <span className="text-[0.62rem] font-semibold tracking-wider uppercase text-[var(--text-muted)]">모델</span>
            <div className="relative">
              <select
                className={TOOLBAR_SELECT}
                value={assignedModelName || ''}
                onChange={(e) => e.target.value && sid && assignModel(sid, e.target.value)}
              >
                <option value="" disabled>모델 선택…</option>
                {models.map((m) => (
                  <option key={m.name} value={m.name}>{m.display_name}</option>
                ))}
              </select>
              <ChevronIcon className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--text-muted)]" />
            </div>
          </div>
        )}

        <div className="flex items-center gap-2 ml-auto">
          {/* live status */}
          <span className="hidden sm:flex items-center gap-1.5 pr-1 text-[0.7rem] text-[var(--text-muted)]">
            <span className={`w-1.5 h-1.5 rounded-full ${ready ? 'bg-[var(--success-color)]' : 'bg-[var(--text-muted)]'}`}
              style={ready ? { boxShadow: '0 0 6px var(--success-color)' } : undefined} />
            {ready ? '연결됨' : '대기'}
          </span>
          {/* desktop-only controls */}
          {isDesktop && (
            <>
              <span className="w-px h-5 bg-[var(--border-color)] mx-0.5" aria-hidden />
              <IconButton icon={ExternalLink} title="브라우저에서 Geny 서버 열기" onClick={() => window.connector?.windowControl.openExternal(window.location.origin)} />
              <IconButton icon={Settings} title="설정 (서버 · 계정 · 테마)" onClick={() => window.connector?.windowControl.openSettings()} />
              <IconButton icon={Power} title="접속기 재시작" onClick={() => window.connector?.windowControl.restart()} />
            </>
          )}
        </div>
      </header>

      {/* Chat */}
      <div className="flex-1 min-h-0 bg-[var(--bg-secondary)]">
        {ready ? (
          <VTuberChatPanel sessionId={sid} />
        ) : (
          <div className="flex h-full items-center justify-center p-8">
            <div className="flex flex-col items-center gap-3 text-center max-w-[280px]">
              {!booted ? (
                <>
                  <div className="w-9 h-9 rounded-full border-[3px] border-[var(--bg-tertiary)] border-t-[var(--primary-color)] animate-spin" />
                  <div className="text-sm text-[var(--text-secondary)]">세션 불러오는 중…</div>
                </>
              ) : (
                <>
                  <div className="w-14 h-14 rounded-2xl grid place-items-center bg-[var(--bg-tertiary)]/50 border border-[var(--border-color)] text-[var(--text-muted)]">
                    <MonitorIcon className="w-7 h-7" />
                  </div>
                  <div className="text-sm font-semibold text-[var(--text-primary)]">
                    {sessions.length === 0 ? '세션이 없습니다' : '세션을 선택하세요'}
                  </div>
                  <div className="text-xs text-[var(--text-muted)] leading-relaxed">
                    {sessions.length === 0
                      ? '서버에서 세션을 만든 뒤 위의 ↻ 로 새로고침하세요.'
                      : '위 세션 메뉴에서 대화할 에이전트를 고르면 채팅이 열립니다.'}
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
