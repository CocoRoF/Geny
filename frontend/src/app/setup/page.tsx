'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/useAuthStore';
import { useI18n } from '@/lib/i18n';
import { ShieldCheck } from 'lucide-react';

export default function SetupPage() {
  const router = useRouter();
  const { t } = useI18n();
  const { hasUsers, setup, checkAuth, initialized } = useAuthStore();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const usernameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  // If users already exist, redirect to home immediately
  useEffect(() => {
    if (initialized && hasUsers) {
      router.replace('/');
    }
  }, [initialized, hasUsers, router]);

  useEffect(() => {
    usernameRef.current?.focus();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!username.trim()) {
      setError(t('auth.usernameRequired'));
      return;
    }
    if (password.length < 4) {
      setError(t('auth.passwordTooShort'));
      return;
    }
    if (password !== confirmPassword) {
      setError(t('auth.passwordMismatch'));
      return;
    }

    setLoading(true);
    try {
      await setup(username.trim(), password, displayName.trim() || undefined);
      router.replace('/');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('auth.setupFailed'));
      setLoading(false);
    }
  };

  // Show nothing until we know whether users exist
  if (!initialized) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[var(--bg-primary)]">
        <div className="text-[var(--text-muted)] text-sm">{t('common.loading')}</div>
      </div>
    );
  }

  // Users already exist — should redirect, but show message just in case
  if (hasUsers) {
    return null;
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-[var(--bg-primary)]">
      <div className="w-full max-w-[440px] mx-4">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-[var(--primary-color)] mb-4">
            <ShieldCheck size={32} className="text-white" />
          </div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)] mb-2">{t('auth.setupTitle')}</h1>
          <p className="text-[0.875rem] text-[var(--text-secondary)]">{t('auth.setupDescription')}</p>
        </div>

        {/* Form Card */}
        <form
          onSubmit={handleSubmit}
          className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg p-6 flex flex-col gap-4 shadow-[var(--shadow-lg)]"
        >
          {error && (
            <div className="px-3 py-2 rounded-md bg-[rgba(239,68,68,0.1)] border border-[rgba(239,68,68,0.3)] text-[0.8125rem] text-[var(--danger-color)]">
              {error}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">{t('auth.username')}</label>
            <input
              ref={usernameRef}
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              className="w-full px-3 py-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.875rem] text-[var(--text-primary)] outline-none focus:border-[var(--primary-color)] transition-colors"
              placeholder={t('auth.usernamePlaceholder')}
              autoComplete="username"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">{t('auth.displayName')}</label>
            <input
              type="text"
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
              className="w-full px-3 py-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.875rem] text-[var(--text-primary)] outline-none focus:border-[var(--primary-color)] transition-colors"
              placeholder={t('auth.displayNamePlaceholder')}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">{t('auth.password')}</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full px-3 py-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.875rem] text-[var(--text-primary)] outline-none focus:border-[var(--primary-color)] transition-colors"
              placeholder={t('auth.passwordPlaceholder')}
              autoComplete="new-password"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">{t('auth.confirmPassword')}</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              className="w-full px-3 py-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.875rem] text-[var(--text-primary)] outline-none focus:border-[var(--primary-color)] transition-colors"
              placeholder={t('auth.confirmPasswordPlaceholder')}
              autoComplete="new-password"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full mt-2 px-4 py-2.5 text-[0.875rem] font-semibold rounded-md bg-[var(--primary-color)] border-none text-white hover:opacity-90 cursor-pointer transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? t('auth.creatingAccount') : t('auth.createAccount')}
          </button>
        </form>

        <p className="text-center text-[0.75rem] text-[var(--text-muted)] mt-4">
          {t('auth.setupNote')}
        </p>
      </div>
    </div>
  );
}
