'use client';

/**
 * Rotating the one account's password.
 *
 * The current password is asked for even though this window already holds a
 * valid token: the token is what a thief would have, and it is what the
 * rotation exists to revoke.
 *
 * Every other device is signed out by this, and the modal says so before the
 * button rather than after — a rotation that surprises the user into
 * re-pairing their connector is a worse outcome than one they chose.
 */

import { useCallback, useState } from 'react';
import { X, Loader2, AlertCircle, CheckCircle2 } from 'lucide-react';

import { authApi, setToken } from '@/lib/authApi';
import { useI18n } from '@/lib/i18n';

export default function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = useCallback(async () => {
    if (next !== confirm) {
      setError(t('header.password.mismatch'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await authApi.changePassword({
        current_password: current,
        new_password: next,
      });
      // The server revoked every token including the one this window was
      // using; the fresh one keeps this session alive.
      setToken(result.access_token);
      setDone(true);
      setCurrent('');
      setNext('');
      setConfirm('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [current, next, confirm, t]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[420px] mx-4 p-5 flex flex-col gap-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center">
          <h3 className="text-[1rem] font-semibold">{t('header.password.title')}</h3>
          <button
            type="button"
            className="w-8 h-8 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)]"
            onClick={onClose}
            aria-label={t('header.password.cancel')}
          >
            <X size={16} className="m-auto" />
          </button>
        </div>

        {done ? (
          <p className="flex items-start gap-2 text-[0.8125rem] text-emerald-400">
            <CheckCircle2 size={14} className="mt-0.5 shrink-0" /> {t('header.password.done')}
          </p>
        ) : (
          <>
            <label className="flex flex-col gap-1">
              <span className="text-[0.75rem] text-[var(--text-secondary)]">{t('header.password.current')}</span>
              <input
                type="password"
                autoComplete="current-password"
                className="bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem]"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                autoFocus
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[0.75rem] text-[var(--text-secondary)]">{t('header.password.next')}</span>
              <input
                type="password"
                autoComplete="new-password"
                className="bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem]"
                value={next}
                onChange={(e) => setNext(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[0.75rem] text-[var(--text-secondary)]">{t('header.password.confirm')}</span>
              <input
                type="password"
                autoComplete="new-password"
                className="bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem]"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') void submit(); }}
              />
            </label>

            <p className="text-[0.7rem] text-[var(--text-muted)]">{t('header.password.hint')}</p>

            {error && (
              <p className="flex items-start gap-1.5 text-[0.75rem] text-rose-300">
                <AlertCircle size={12} className="mt-0.5 shrink-0" /> {error}
              </p>
            )}
          </>
        )}

        <div className="flex justify-end gap-2">
          {!done && (
            <button
              type="button"
              className="px-3 py-2 rounded bg-[var(--primary-color)] text-white text-[0.8125rem] disabled:opacity-50"
              disabled={busy || !current || !next || !confirm}
              onClick={() => void submit()}
            >
              {busy ? (
                <span className="flex items-center gap-1.5">
                  <Loader2 size={12} className="animate-spin" /> {t('header.password.saving')}
                </span>
              ) : t('header.password.submit')}
            </button>
          )}
          <button
            type="button"
            className="px-3 py-2 rounded border border-[var(--border-color)] text-[0.8125rem] hover:bg-[var(--bg-hover)]"
            onClick={onClose}
          >
            {done ? t('header.password.cancel') : t('header.password.cancel')}
          </button>
        </div>
      </div>
    </div>
  );
}
