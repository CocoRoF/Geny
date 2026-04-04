'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuthStore } from '@/store/useAuthStore';
import { useI18n } from '@/lib/i18n';
import { X, LogIn } from 'lucide-react';

interface LoginModalProps {
  onClose: () => void;
}

export default function LoginModal({ onClose }: LoginModalProps) {
  const { t } = useI18n();
  const { login } = useAuthStore();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const usernameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    usernameRef.current?.focus();
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!username.trim() || !password) return;
    setError('');
    setLoading(true);
    try {
      await login(username.trim(), password);
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('auth.loginFailed'));
      setLoading(false);
    }
  }, [username, password, login, onClose, t]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'Enter' && !loading) {
        e.preventDefault();
        handleSubmit();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose, handleSubmit, loading]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[400px] flex flex-col shadow-[var(--shadow-lg)]"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex justify-between items-center py-4 px-6 border-b border-[var(--border-color)]">
          <h3 className="text-[1rem] font-semibold text-[var(--text-primary)] flex items-center gap-2">
            <LogIn size={18} />
            {t('auth.loginTitle')}
          </h3>
          <button
            className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 flex flex-col gap-4">
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
              className="w-full px-3 py-2 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.8125rem] text-[var(--text-primary)] outline-none focus:border-[var(--primary-color)] transition-colors"
              placeholder={t('auth.usernamePlaceholder')}
              autoComplete="username"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">{t('auth.password')}</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full px-3 py-2 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.8125rem] text-[var(--text-primary)] outline-none focus:border-[var(--primary-color)] transition-colors"
              placeholder={t('auth.passwordPlaceholder')}
              autoComplete="current-password"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-[var(--border-color)]">
          <button
            className="px-4 py-2 text-[0.8125rem] font-medium rounded-md bg-transparent border border-[var(--border-color)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-colors"
            onClick={onClose}
            disabled={loading}
          >
            {t('common.cancel')}
          </button>
          <button
            className="px-4 py-2 text-[0.8125rem] font-medium rounded-md bg-[var(--primary-color)] border-none text-white hover:opacity-90 cursor-pointer transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={handleSubmit}
            disabled={loading || !username.trim() || !password}
          >
            {loading ? t('auth.loggingIn') : t('auth.login')}
          </button>
        </div>
      </div>
    </div>
  );
}
