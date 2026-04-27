'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { useAuthStore } from '@/store/useAuthStore';
import { useI18n } from '@/lib/i18n';
import type { Locale } from '@/lib/i18n';
import { useTheme } from '@/lib/theme';
import { configApi } from '@/lib/api';
import { Menu, Sun, Moon, Code2, User, BookOpen, Mic, AudioLines, LogIn, LogOut, Brain, Layers } from 'lucide-react';
import Link from 'next/link';
import LoginModal from '@/components/auth/LoginModal';

export default function Header() {
  const { healthStatus, sessions, setMobileSidebarOpen, devMode, toggleDevMode, hydrateDevMode } = useAppStore();
  const { isAuthenticated, hasUsers, displayName, logout } = useAuthStore();
  const [showLogin, setShowLogin] = useState(false);

  useEffect(() => { hydrateDevMode(); }, [hydrateDevMode]);

  // TTS Studio URL (GPT-SoVITS WebUI)
  const [ttsStudioUrl, setTtsStudioUrl] = useState<string>('/tts-studio/');
  useEffect(() => {
    if (process.env.NEXT_PUBLIC_API_URL !== undefined) return;
    const port = process.env.NEXT_PUBLIC_GPT_SOVITS_WEBUI_PORT || '9874';
    setTtsStudioUrl(`${window.location.protocol}//${window.location.hostname}:${port}`);
  }, []);
  const { t, locale, setLocale } = useI18n();
  const { theme, setTheme } = useTheme();

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

  const devModeIcon = devMode ? <User size={14} /> : <Code2 size={14} />;
  const devModeTitle = devMode ? t('header.normalMode') : t('header.devMode');

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

        {/* ── Dev / Normal Mode Toggle — hidden on mobile, requires auth ── */}
        {isAuthenticated && (
          <button
            onClick={toggleDevMode}
            className="hidden sm:flex items-center justify-center w-7 h-7 md:w-8 md:h-8 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150"
            title={devModeTitle}
          >
            {devModeIcon}
          </button>
        )}

        {/* ── Wiki Button — hidden on mobile ── */}
        <Link
          href="/wiki"
          className="hidden sm:flex items-center justify-center w-8 h-8 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150 no-underline"
          title={t('header.wiki')}
        >
          <BookOpen size={14} />
        </Link>

        {/* ── TTS Studio Button — hidden on mobile ── */}
        <a
          href={ttsStudioUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="hidden sm:flex items-center justify-center w-8 h-8 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150 no-underline"
          title={t('header.ttsStudio')}
        >
          <Mic size={14} />
        </a>

        {/* ── TTS Voice Button — hidden on mobile ── */}
        <Link
          href="/tts-voice"
          className="hidden sm:flex items-center justify-center w-8 h-8 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150 no-underline"
          title={t('header.ttsVoice')}
        >
          <AudioLines size={14} />
        </Link>

        {/* ── Environment Management Page — hidden on mobile, dev only ── */}
        {devMode && (
          <Link
            href="/environments"
            className="hidden sm:flex items-center justify-center w-8 h-8 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150 no-underline"
            title={t('header.envManagement')}
          >
            <Layers size={14} />
          </Link>
        )}

        {/* ── Language Toggle ── */}
        <div className="inline-flex items-center gap-0.5 p-0.5 rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)]">
          <button
            onClick={() => switchLocale('en')}
            className={`px-2 py-1 text-[0.6875rem] font-medium rounded transition-all duration-150 border-none cursor-pointer ${
              locale === 'en'
                ? 'bg-[var(--primary-color)] text-white shadow-sm'
                : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            ENG
          </button>
          <button
            onClick={() => switchLocale('ko')}
            className={`px-2 py-1 text-[0.6875rem] font-medium rounded transition-all duration-150 border-none cursor-pointer ${
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
            className="hidden sm:flex items-center gap-1.5 px-2.5 py-1.5 text-[0.6875rem] font-medium rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150 no-underline"
            title={t('header.memory')}
          >
            <Brain size={13} />
            <span className="hidden md:inline">{t('header.memory')}</span>
          </Link>
        )}

        {/* ── Login / Logout Button ── */}
        {hasUsers && (
          isAuthenticated ? (
            <button
              onClick={() => {
                logout();
                // Reset to normal mode so dev-only tabs disappear
                if (devMode) toggleDevMode();
              }}
              className="hidden sm:flex items-center gap-1.5 px-2.5 py-1.5 text-[0.6875rem] font-medium rounded-md bg-[var(--bg-tertiary)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-all duration-150"
              title={t('header.logout')}
            >
              <LogOut size={13} />
              <span className="hidden md:inline">{displayName || t('header.logout')}</span>
            </button>
          ) : (
            <button
              onClick={() => setShowLogin(true)}
              className="hidden sm:flex items-center gap-1.5 px-2.5 py-1.5 text-[0.6875rem] font-medium rounded-md bg-[var(--primary-color)] border-none text-white hover:opacity-90 cursor-pointer transition-opacity"
              title={t('header.login')}
            >
              <LogIn size={13} />
              <span className="hidden md:inline">{t('header.login')}</span>
            </button>
          )
        )}

        {/* ── Session Status ── */}
        <div className="flex items-center gap-2 px-3 py-1.5 bg-[var(--bg-tertiary)] rounded-full text-[0.75rem] md:text-[0.8125rem]">
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
    </header>
  );
}
