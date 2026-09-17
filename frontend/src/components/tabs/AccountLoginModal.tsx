'use client';

/**
 * Signing a subscription in to a server you are not sitting at.
 *
 * Neither flow can finish inside a request, and neither can finish on the
 * server at all: Claude Code wants to open a browser and catch a localhost
 * callback, and Codex wants a code typed at auth.openai.com. The browser
 * that can do either is THIS one. So the server streams the flow out — a URL
 * or a device code, then every line the CLI prints — and this modal carries
 * the answer back.
 *
 * The stream replays what the job already emitted before going live, so
 * opening it a moment late does not lose the URL the whole flow hangs on.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  X, ExternalLink, Copy, Check, Loader2, AlertCircle, CheckCircle2,
} from 'lucide-react';

import { llmAccountsApi, type LlmAccount, type LoginEvent } from '@/lib/llmAccountsApi';
import { useI18n } from '@/lib/i18n';

interface Props {
  account: LlmAccount;
  /** Claude Code only — sign in with a Console account instead of a plan. */
  console?: boolean;
  onClose: () => void;
  onDone: (ok: boolean) => void;
}

type Phase = 'starting' | 'waiting' | 'done' | 'failed';

export default function AccountLoginModal({ account, console: consoleLogin = false, onClose, onDone }: Props) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<Phase>('starting');
  const [jobId, setJobId] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [device, setDevice] = useState<{ code: string; url: string; expiresAt: number } | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [copied, setCopied] = useState(false);
  const [sending, setSending] = useState(false);
  const outputRef = useRef<HTMLDivElement | null>(null);
  const startedRef = useRef(false);

  const isCodex = account.kind === 'codex';

  const handleEvent = useCallback((event: LoginEvent) => {
    if (event.type === 'line') {
      setLines((prev) => [...prev.slice(-400), event.text]);
      return;
    }
    if (event.type === 'url') {
      setUrl((prev) => prev ?? event.url);
      setPhase('waiting');
      return;
    }
    if (event.type === 'device') {
      setDevice({ code: event.userCode, url: event.verificationUrl, expiresAt: event.expiresAt });
      setPhase('waiting');
      return;
    }
    if (event.type === 'done') {
      setPhase(event.ok ? 'done' : 'failed');
      if (!event.ok) setError(event.error || null);
      onDone(event.ok);
    }
  }, [onDone]);

  // Start the job, then follow it. Started once per mount — a second start
  // would leave an orphaned `claude auth login` holding the account's
  // credential directory open.
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    let stop: (() => void) | null = null;
    (async () => {
      try {
        if (isCodex) {
          // The device flow hands back the code with the job — showing it
          // immediately rather than waiting for the stream's own `device`
          // frame is the difference between "here is your code" and a
          // spinner.
          const started = await llmAccountsApi.codexLogin(account.id);
          setJobId(started.jobId);
          setDevice({
            code: started.userCode,
            url: started.verificationUrl,
            expiresAt: started.expiresAt,
          });
          setPhase('waiting');
          stop = llmAccountsApi.loginEvents(started.jobId, handleEvent);
          return;
        }
        const started = await llmAccountsApi.claudeLogin(account.id, consoleLogin);
        setJobId(started.jobId);
        setPhase('waiting');
        stop = llmAccountsApi.loginEvents(started.jobId, handleEvent);
      } catch (e) {
        setPhase('failed');
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { stop?.(); };
  }, [account.id, consoleLogin, handleEvent, isCodex]);

  useEffect(() => {
    outputRef.current?.scrollTo({ top: outputRef.current.scrollHeight });
  }, [lines]);

  // The device code expires in fifteen minutes and the countdown is the
  // only sign of it, so it ticks rather than freezing at whatever it read
  // on the render that happened to create it.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!device) return;
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, [device]);

  const minutesLeft = useMemo(() => {
    if (!device) return null;
    return Math.max(0, Math.round((device.expiresAt - now) / 60000));
  }, [device, now]);

  const openLink = useCallback((href: string) => {
    window.open(href, '_blank', 'noopener,noreferrer');
  }, []);

  const copyLink = useCallback(async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — the link is on screen to copy by hand */
    }
  }, []);

  const submitCode = useCallback(async () => {
    if (!jobId || !code.trim()) return;
    setSending(true);
    try {
      await llmAccountsApi.sendLoginInput(jobId, code.trim());
      setCode('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }, [jobId, code]);

  const cancel = useCallback(async () => {
    if (jobId) {
      try { await llmAccountsApi.cancelLogin(jobId); } catch { /* already gone */ }
    }
    onClose();
  }, [jobId, onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={cancel}>
      <div
        className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[620px] mx-4 p-5 flex flex-col gap-4 max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center">
          <h3 className="text-[1rem] font-semibold">
            {t('settings.models.login.title', { label: account.label })}
          </h3>
          <button
            type="button"
            className="w-8 h-8 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)]"
            onClick={cancel}
            aria-label={t('settings.models.close')}
          >
            <X size={16} className="m-auto" />
          </button>
        </div>

        {phase === 'starting' && (
          <p className="flex items-center gap-2 text-[0.8125rem] text-[var(--text-secondary)]">
            <Loader2 size={14} className="animate-spin" />
            {t('settings.models.login.waiting')}
          </p>
        )}

        {device && phase === 'waiting' && (
          <div className="flex flex-col gap-2 rounded-[var(--border-radius)] border border-[var(--border-color)] p-4">
            <p className="text-[0.8125rem] text-[var(--text-secondary)]">
              {t('settings.models.login.deviceCode')}
            </p>
            <div className="font-mono text-[1.5rem] tracking-[0.2em] text-[var(--text-primary)]">
              {device.code}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="flex items-center gap-1.5 text-[0.75rem] px-2.5 py-1.5 rounded border border-[var(--border-color)] hover:bg-[var(--bg-hover)]"
                onClick={() => openLink(device.url)}
              >
                <ExternalLink size={12} /> {t('settings.models.login.openLink')}
              </button>
              {minutesLeft !== null && (
                <span className="text-[0.75rem] text-[var(--text-muted)]">
                  {t('settings.models.login.expires', { minutes: minutesLeft })}
                </span>
              )}
            </div>
          </div>
        )}

        {url && !device && (
          <div className="flex flex-col gap-2 rounded-[var(--border-radius)] border border-[var(--border-color)] p-4">
            <p className="text-[0.8125rem] text-[var(--text-secondary)]">
              {t('settings.models.login.openBrowser')}
            </p>
            <code className="block text-[0.72rem] break-all text-[var(--text-muted)] bg-[var(--bg-tertiary)] rounded p-2">
              {url}
            </code>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="flex items-center gap-1.5 text-[0.75rem] px-2.5 py-1.5 rounded border border-[var(--border-color)] hover:bg-[var(--bg-hover)]"
                onClick={() => openLink(url)}
              >
                <ExternalLink size={12} /> {t('settings.models.login.openLink')}
              </button>
              <button
                type="button"
                className="flex items-center gap-1.5 text-[0.75rem] px-2.5 py-1.5 rounded border border-[var(--border-color)] hover:bg-[var(--bg-hover)]"
                onClick={() => copyLink(url)}
              >
                {copied ? <Check size={12} /> : <Copy size={12} />} {t('settings.models.login.copyLink')}
              </button>
            </div>
          </div>
        )}

        {!isCodex && phase === 'waiting' && (
          <div className="flex flex-col gap-2">
            <label className="text-[0.75rem] text-[var(--text-secondary)]">
              {t('settings.models.login.pasteCode')}
            </label>
            <div className="flex gap-2">
              <input
                className="flex-1 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem] font-mono"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') void submitCode(); }}
                placeholder={t('settings.models.login.code')}
                autoFocus
              />
              <button
                type="button"
                className="px-3 py-2 rounded bg-[var(--primary-color)] text-white text-[0.8125rem] disabled:opacity-50"
                disabled={!code.trim() || sending}
                onClick={() => void submitCode()}
              >
                {sending ? <Loader2 size={14} className="animate-spin" /> : t('settings.models.login.submit')}
              </button>
            </div>
          </div>
        )}

        {lines.length > 0 && (
          <div className="flex flex-col gap-1 min-h-0">
            <span className="text-[0.7rem] uppercase tracking-wide text-[var(--text-muted)]">
              {t('settings.models.login.output')}
            </span>
            <div
              ref={outputRef}
              className="overflow-y-auto max-h-[180px] bg-[var(--bg-tertiary)] rounded p-2 font-mono text-[0.7rem] leading-relaxed text-[var(--text-secondary)] whitespace-pre-wrap"
            >
              {lines.join('\n')}
            </div>
          </div>
        )}

        {phase === 'done' && (
          <p className="flex items-center gap-2 text-[0.8125rem] text-emerald-400">
            <CheckCircle2 size={14} /> {t('settings.models.login.done')}
          </p>
        )}
        {phase === 'failed' && (
          <p className="flex items-start gap-2 text-[0.8125rem] text-rose-300">
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            {t('settings.models.login.failed', { error: error || '' })}
          </p>
        )}

        <div className="flex justify-end gap-2">
          {phase === 'waiting' ? (
            <button
              type="button"
              className="px-3 py-2 rounded border border-[var(--border-color)] text-[0.8125rem] hover:bg-[var(--bg-hover)]"
              onClick={cancel}
            >
              {t('settings.models.login.cancel')}
            </button>
          ) : (
            <button
              type="button"
              className="px-3 py-2 rounded border border-[var(--border-color)] text-[0.8125rem] hover:bg-[var(--bg-hover)]"
              onClick={onClose}
            >
              {t('settings.models.close')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
