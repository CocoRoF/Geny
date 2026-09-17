'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { useAuthStore } from '@/store/useAuthStore';
import { useI18n } from '@/lib/i18n';
import type { Locale } from '@/lib/i18n';
import { useTheme } from '@/lib/theme';
import { configApi, gaptApi } from '@/lib/api';
import { Menu, Sun, Moon, BookOpen, Sliders, LogIn, LogOut, KeyRound, Brain, Layers, Palette, Container } from 'lucide-react';
import Link from 'next/link';
import LoginModal from '@/components/auth/LoginModal';
import ChangePasswordModal from '@/components/auth/ChangePasswordModal';
import { Button } from '@/components/ui/button';

export default function Header() {
  const { healthStatus, sessions, setMobileSidebarOpen } = useAppStore();
  const { isAuthenticated, hasUsers, displayName, logout } = useAuthStore();
  const [showLogin, setShowLogin] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const { t, locale, setLocale } = useI18n();
  const { theme, setTheme } = useTheme();

  // GAPT detection — show the GAPT button only when the platform is reachable.
  const [gaptUrl, setGaptUrl] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const s = await gaptApi.status();
        if (alive) setGaptUrl(s.running ? s.ui_path : null);
      } catch {
        if (alive) setGaptUrl(null);
      }
    };
    check();
    const id = setInterval(check, 15000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  // Open GAPT with SSO bypass: open the tab synchronously (avoids popup
  // blocking), establish the GAPT session cookie via /api/gapt/sso, then point
  // the tab at the SPA. Falls back to opening GAPT directly (its own login) if
  // SSO fails or bypass is off.
  const openGapt = useCallback(async () => {
    // Open the tab synchronously (avoids popup blocking) WITHOUT `noopener` —
    // that flag makes window.open return null, which orphaned a blank tab and
    // navigated the current one instead. With a handle we navigate this exact tab.
    const tab = window.open('', '_blank');
    let url = gaptUrl || '/_gapt/app/';
    try {
      const r = await gaptApi.sso();
      if (r?.ui_path) url = r.ui_path;
    } catch {
      /* SSO failed → GAPT will show its own login */
    }
    if (tab && !tab.closed) {
      tab.location.replace(url);
      try { tab.opener = null; } catch { /* same-origin best-effort */ }
    } else {
      // Popup blocked → fall back to same-tab navigation (no orphan tab).
      window.location.href = url;
    }
  }, [gaptUrl]);

  const isHealthy = healthStatus === 'connected';

  const switchLocale = (lang: Locale) => {
    setLocale(lang);
    configApi.update('language', { language: lang }).catch(() => {});
  };

  /** Toggle theme: dark ↔ light */
  const toggleTheme = useCallback(() => {
    document.documentElement.classList.add('theme-transition');
    setTimeout(() => document.documentElement.classList.remove('theme-transition'), 400);
    setTheme(theme === 'dark' ? 'light' : 'dark');
  }, [theme, setTheme]);

  const themeIcon = theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />;
  const themeTitle = theme === 'dark' ? 'Switch to Light' : 'Switch to Dark';

  return (
    <header className="flex justify-between items-center px-3 md:px-6 h-12 md:h-14 bg-[hsl(var(--card))] border-b border-[hsl(var(--border))]">
      <div className="flex items-center gap-2 md:gap-3">
        {/* Mobile hamburger button */}
        <button
          className="flex md:hidden items-center justify-center w-10 h-10 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-colors duration-150"
          onClick={() => setMobileSidebarOpen(true)}
          aria-label="Open menu"
        >
          <Menu size={20} />
        </button>
        {/* Geny mascot — also the favicon + desktop app icon */}
        <img
          src="/geny_character.png"
          alt="Geny"
          width={32}
          height={32}
          className="w-7 h-7 md:w-8 md:h-8 shrink-0 object-contain select-none"
          draggable={false}
        />
        <span className="text-[0.9rem] text-[var(--text-tertiary)] tracking-[0.08em] italic hidden sm:inline">
          {t('header.subtitle')}
        </span>
      </div>
      <div className="flex items-center gap-1.5 md:gap-2.5">
        {/* ── Theme Toggle ── */}
        <button
          onClick={toggleTheme}
          className="flex items-center justify-center w-7 h-7 md:w-8 md:h-8 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150"
          title={themeTitle}
        >
          {themeIcon}
        </button>

        {/* ── Wiki Button — hidden on mobile ── */}
        <Link
          href="/wiki"
          className="hidden sm:flex items-center justify-center w-7 h-7 md:w-8 md:h-8 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150 no-underline"
          title={t('header.wiki')}
        >
          <BookOpen size={14} />
        </Link>

        {/* ── Voice Studio Button — hidden on mobile ── */}
        <Link
          href="/voice-studio"
          className="hidden sm:flex items-center justify-center w-7 h-7 md:w-8 md:h-8 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150 no-underline"
          title={t('header.voiceStudio')}
        >
          <Sliders size={14} />
        </Link>

        {/* ── Avatar Editor Button — opens the geny-avatar service in a
             new tab. /avatar-editor is nginx-proxied to a separate
             Next.js app (not an internal route), so use a plain <a>
             with target="_blank" instead of next/link. */}
        <a
          href="/avatar-editor/"
          target="_blank"
          rel="noopener noreferrer"
          className="hidden sm:flex items-center justify-center w-7 h-7 md:w-8 md:h-8 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150 no-underline"
          title="Avatar Editor — Spine/Cubism puppet 편집"
        >
          <Palette size={14} />
        </a>

        {/* ── Environment Management Page — hidden on mobile ── */}
        <Link
          href="/environments"
          className="hidden sm:flex items-center justify-center w-7 h-7 md:w-8 md:h-8 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150 no-underline"
          title={t('header.envManagement')}
        >
          <Layers size={14} />
        </Link>

        {/* Sandbox Tool Packs → moved into the environment editor; Sandbox Logs
            (snapshot activity/diff) → superseded by the in-app 작업(Tasks) tab.
            Both standalone header links are removed. */}

        {/* ── GAPT — shown only when the GAPT platform is detected.
             Establishes a GAPT browser session first (SSO bypass) so the SPA
             opens already-logged-in. The tab is opened synchronously to avoid
             popup blocking, then navigated once the session cookie is set. ── */}
        {gaptUrl && (
          <button
            type="button"
            onClick={openGapt}
            className="hidden sm:flex items-center justify-center gap-1 h-7 md:h-8 px-2 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150"
            title={t('header.gapt')}
          >
            <Container size={14} />
            <span className="text-[0.6875rem] font-semibold tracking-wide">GAPT</span>
          </button>
        )}

        {/* ── Language Toggle ── */}
        <div className="inline-flex items-stretch h-7 md:h-8 gap-0.5 p-0.5 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
          <button
            onClick={() => switchLocale('en')}
            className={`px-2 inline-flex items-center text-[0.6875rem] font-medium rounded transition-all duration-150 border-none cursor-pointer ${
              locale === 'en'
                ? 'bg-[var(--primary-color)] text-white shadow-sm'
                : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            ENG
          </button>
          <button
            onClick={() => switchLocale('ko')}
            className={`px-2 inline-flex items-center text-[0.6875rem] font-medium rounded transition-all duration-150 border-none cursor-pointer ${
              locale === 'ko'
                ? 'bg-[var(--primary-color)] text-white shadow-sm'
                : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            KOR
          </button>
        </div>

        {/* ── Memory (User Opsidian) Button — requires auth ── */}
        {isAuthenticated && (
          <Link
            href="/opsidian"
            className="hidden sm:flex items-center gap-1.5 h-7 md:h-8 px-2.5 text-[0.6875rem] font-medium rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150 no-underline"
            title={t('header.memory')}
          >
            <Brain size={13} />
            <span className="hidden md:inline">{t('header.memory')}</span>
          </Link>
        )}

        {/* ── Login / Logout Button ── */}
        {hasUsers && (
          isAuthenticated ? (
            <>
            <button
              onClick={() => setShowPassword(true)}
              className="hidden sm:flex items-center h-7 md:h-8 px-2 text-[0.6875rem] font-medium rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150"
              title={t('header.changePassword')}
            >
              <KeyRound size={13} />
            </button>
            <button
              onClick={() => logout()}
              className="hidden sm:flex items-center gap-1.5 h-7 md:h-8 px-2.5 text-[0.6875rem] font-medium rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150"
              title={t('header.logout')}
            >
              <LogOut size={13} />
              <span className="hidden md:inline">{displayName || t('header.logout')}</span>
            </button>
            </>
          ) : (
            <Button
              variant="gradient"
              size="sm"
              onClick={() => setShowLogin(true)}
              className="hidden sm:inline-flex items-center h-7 md:h-8 px-2.5 text-[0.6875rem]"
              title={t('header.login')}
            >
              <LogIn size={13} />
              <span className="hidden md:inline">{t('header.login')}</span>
            </Button>
          )
        )}

        {/* ── Session Status ── */}
        <div className="flex items-center gap-2 h-7 md:h-8 px-3 bg-[var(--bg-tertiary)] rounded-full text-[0.75rem] md:text-[0.8125rem]">
          <span
            className={`w-2 h-2 rounded-full shrink-0 ${
              isHealthy
                ? 'bg-[var(--success-color)]'
                : 'bg-[var(--danger-color)]'
            }`}
            style={isHealthy ? { boxShadow: '0 0 8px var(--success-color)' } : undefined}
          />
          <span className="text-[var(--text-secondary)]">
            {isHealthy ? t('header.sessions', { count: sessions.length }) : t('header.disconnected')}
          </span>
        </div>
      </div>

      {/* Login Modal */}
      {showLogin && <LoginModal onClose={() => setShowLogin(false)} />}
      {showPassword && <ChangePasswordModal onClose={() => setShowPassword(false)} />}
    </header>
  );
}
