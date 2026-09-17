'use client';

/**
 * Change which model answers, from where you are talking to it.
 *
 * The switch is cheap on purpose: the pipeline names one provider, so the
 * server swaps the session's credentials in place and the next turn simply
 * goes elsewhere. Nothing else moves — the history, the tools, the memory,
 * the hooks and the permission policy are the same ones a second ago. That
 * is worth saying in the menu, because everywhere else in this kind of
 * software "change the model" means "start over".
 *
 * It also shows who ACTUALLY answered the last turn, which is a different
 * fact from what is selected: they diverge exactly when a hop failed over,
 * and that is the moment someone wants to know.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Loader2, AlertCircle, CornerDownRight } from 'lucide-react';

import {
  llmAccountsApi,
  sessionRouteApi,
  modelChoicesFor,
  type AgentRoute,
  type LastRoute,
  type LlmAccount,
} from '@/lib/llmAccountsApi';
import { useI18n } from '@/lib/i18n';

interface Props {
  sessionId: string;
  /** Rendered small, for a dense session header. */
  compact?: boolean;
}

export default function ModelSwitcher({ sessionId, compact = true }: Props) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [accounts, setAccounts] = useState<LlmAccount[]>([]);
  const [route, setRoute] = useState<AgentRoute | null>(null);
  const [lastRoute, setLastRoute] = useState<LastRoute | null>(null);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      const [listed, state] = await Promise.all([
        llmAccountsApi.list(),
        sessionRouteApi.get(sessionId),
      ]);
      setAccounts(listed.accounts.filter((a) => a.enabled));
      setRoute(state.route ?? listed.defaultRoute);
      setLastRoute(state.last_route);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [sessionId]);

  useEffect(() => { void load(); }, [load]);

  // Re-read when the menu opens: a turn may have failed over since, and the
  // whole point of the "answered by" line is that it is current.
  useEffect(() => { if (open) void load(); }, [open, load]);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const accountById = useMemo(
    () => new Map(accounts.map((a) => [a.id, a])),
    [accounts],
  );

  const primary = route?.primary ?? null;
  const primaryAccount = primary ? accountById.get(primary.accountId) : undefined;
  const currentLabel = primaryAccount
    ? `${primaryAccount.label} · ${primary?.model || ''}`
    : t('settings.models.switcher.none');

  const choose = useCallback(async (accountId: string, model: string) => {
    setSwitching(true);
    setError(null);
    try {
      // Everything else stays a fallback, in the order the user arranged the
      // accounts — switching model should not also quietly drop the safety
      // net underneath it.
      const fallbacks = accounts
        .filter((a) => a.id !== accountId)
        .map((a) => ({ accountId: a.id, model: modelChoicesFor(a)[0]?.id }));
      const next: AgentRoute = { primary: { accountId, model }, fallbacks };
      await sessionRouteApi.set(sessionId, next);
      setRoute(next);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSwitching(false);
    }
  }, [accounts, sessionId]);

  const answered = lastRoute?.label && lastRoute?.model
    ? t('settings.models.switcher.answeredBy', { label: lastRoute.label, model: lastRoute.model })
    : null;

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        className={`inline-flex items-center gap-1.5 rounded-full border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] transition-colors ${
          compact ? 'px-2 py-1 text-[0.6875rem]' : 'px-3 py-1.5 text-[0.8125rem]'
        }`}
        onClick={() => setOpen((v) => !v)}
        title={answered ?? undefined}
      >
        {switching ? <Loader2 size={11} className="animate-spin" /> : null}
        <span className="max-w-[160px] truncate">{currentLabel}</span>
        {lastRoute?.failedOver && (
          <CornerDownRight size={10} className="text-amber-400 shrink-0" />
        )}
        <ChevronDown size={11} className="shrink-0" />
      </button>

      {open && (
        <div className="absolute right-0 top-[calc(100%+6px)] z-40 w-[300px] max-h-[420px] overflow-y-auto rounded-lg border border-[var(--border-color)] bg-[var(--bg-secondary)] shadow-lg p-2">
          {accounts.length === 0 ? (
            <div className="px-2 py-3">
              <p className="text-[0.75rem] text-[var(--text-secondary)]">
                {t('settings.models.switcher.none')}
              </p>
              <p className="text-[0.7rem] text-[var(--text-muted)] mt-1">
                {t('settings.models.switcher.noneHint')}
              </p>
            </div>
          ) : (
            accounts.map((account) => (
              <div key={account.id} className="mb-1.5 last:mb-0">
                <div className="px-2 py-1 text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                  {account.label}
                </div>
                {modelChoicesFor(account).map((choice) => {
                  const active = primary?.accountId === account.id && primary?.model === choice.id;
                  return (
                    <button
                      key={`${account.id}:${choice.id}`}
                      type="button"
                      className={`w-full text-left px-2 py-1.5 rounded text-[0.75rem] transition-colors ${
                        active
                          ? 'bg-[rgba(59,130,246,0.12)] text-[var(--primary-color)]'
                          : 'hover:bg-[var(--bg-hover)] text-[var(--text-secondary)]'
                      }`}
                      disabled={switching}
                      onClick={() => void choose(account.id, choice.id)}
                    >
                      <span className="block truncate">{choice.label}</span>
                      {choice.hint && (
                        <span className="block text-[0.65rem] text-[var(--text-muted)] truncate">
                          {choice.hint}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            ))
          )}

          {error && (
            <p className="flex items-start gap-1 px-2 py-1.5 text-[0.7rem] text-rose-300">
              <AlertCircle size={11} className="mt-0.5 shrink-0" /> {error}
            </p>
          )}

          {accounts.length > 0 && (
            <div className="border-t border-[var(--border-color)] mt-1.5 pt-1.5 px-2 flex flex-col gap-1">
              {answered && (
                <p className="text-[0.7rem] text-[var(--text-muted)]">
                  {answered}
                  {lastRoute?.failedOver && (
                    <span className="text-amber-400">
                      {' · '}
                      {t('settings.models.switcher.failedOver', { label: lastRoute.label ?? '' })}
                    </span>
                  )}
                </p>
              )}
              <p className="text-[0.7rem] text-[var(--text-muted)]">
                {t('settings.models.switcher.keepsConversation')}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
