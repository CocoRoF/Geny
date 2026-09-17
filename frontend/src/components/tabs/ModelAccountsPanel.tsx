'use client';

/**
 * Settings › Models — every way this server can reach a model.
 *
 * The list IS the default route: the first enabled account answers, and the
 * rest are tried, in order, only when one cannot. That is why order is
 * editable here and not buried in a dialog — it is the most consequential
 * setting on the page and the cheapest to get wrong.
 *
 * The provider grid that used to sit under this is gone. It listed eight
 * backends with keys and health, none of which a session uses any more — a
 * session asks the accounts above. Keeping it would have left two places
 * claiming to say which model answers.
 *
 * Two things survived it, because they describe something real: document
 * embedding, which genuinely still uses one key per provider and is not what
 * a session talks to, and the version of the `claude` binary these accounts
 * spawn.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  Plus, Loader2, RefreshCw, Trash2, ChevronUp, ChevronDown, LogIn, LogOut,
  AlertCircle, CheckCircle2, ChevronRight, Download, Zap,
} from 'lucide-react';

import {
  llmAccountsApi,
  type AccountKind,
  type ClaudeAuthMethod,
  type ClaudeRunMode,
  type CliInfo,
  type KindInfo,
  type LlmAccount,
} from '@/lib/llmAccountsApi';
import { useI18n } from '@/lib/i18n';
import { SettingsCard, type CardStatusTone } from '@/components/settings/SettingsCard';
import AccountLoginModal from './AccountLoginModal';
import ClaudeCodeVersionCard from './ClaudeCodeVersionCard';
import { EmbeddingSettingsCard } from './EmbeddingSettingsCard';
import { llmBackendsApi, type ProviderHealth } from '@/lib/api';

const SUBSCRIPTION_KINDS = new Set<AccountKind>(['claude_code', 'codex']);

function toneOf(account: LlmAccount): CardStatusTone {
  if (!account.enabled) return 'neutral';
  if (account.status?.ok === true) return 'good';
  if (account.status?.ok === false) return 'bad';
  return 'warn';
}

// ── one account ──────────────────────────────────────────────────────

interface RowProps {
  account: LlmAccount;
  kinds: Record<string, KindInfo>;
  index: number;
  total: number;
  cli: CliInfo | null;
  onChanged: () => void;
  onLogin: (account: LlmAccount) => void;
  onMove: (id: string, delta: number) => void;
}

function AccountRow({ account, kinds, index, total, cli, onChanged, onLogin, onMove }: RowProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null);
  const [label, setLabel] = useState(account.label);
  const [baseUrl, setBaseUrl] = useState(account.baseUrl);
  const [secret, setSecret] = useState('');
  const [effort, setEffort] = useState(account.effort);
  const [authMethod, setAuthMethod] = useState<ClaudeAuthMethod>(account.claude?.authMethod ?? 'login');
  const [mode, setMode] = useState<ClaudeRunMode>(account.claude?.mode ?? 'token');

  const info = kinds[account.kind];
  const needsKey = info?.secret === 'api_key' || info?.secret === 'optional_key';

  const run = useCallback(async (key: string, work: () => Promise<void>) => {
    setBusy(key);
    setMessage(null);
    try {
      await work();
    } catch (e) {
      setMessage({ tone: 'bad', text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }, []);

  const save = () => run('save', async () => {
    await llmAccountsApi.update(account.id, {
      label,
      baseUrl,
      effort,
      ...(secret ? { secret } : {}),
      ...(account.kind === 'claude_code' ? { claude: { authMethod, mode } } : {}),
    });
    setSecret('');
    onChanged();
  });

  const toggle = () => run('toggle', async () => {
    await llmAccountsApi.update(account.id, { enabled: !account.enabled });
    onChanged();
  });

  const test = () => run('test', async () => {
    const result = await llmAccountsApi.test(account.id);
    setMessage(result.ok
      ? { tone: 'ok', text: t('settings.models.testOk', { ms: result.latencyMs }) }
      : { tone: 'bad', text: result.error || t('settings.models.testFail') });
    onChanged();
  });

  const remove = () => {
    if (!window.confirm(t('settings.models.removeConfirm', { label: account.label }))) return;
    void run('remove', async () => {
      await llmAccountsApi.remove(account.id);
      onChanged();
    });
  };

  const logout = () => run('logout', async () => {
    await llmAccountsApi.claudeLogout(account.id);
    onChanged();
  });

  const importCodex = () => run('import', async () => {
    try {
      await llmAccountsApi.codexImport(account.id);
      setMessage({ tone: 'ok', text: t('settings.models.codex.importOk') });
      onChanged();
    } catch {
      setMessage({ tone: 'bad', text: t('settings.models.codex.importMissing') });
    }
  });

  const discover = () => run('discover', async () => {
    await llmAccountsApi.discoverModels(account.id);
    onChanged();
  });

  const identity = account.identity ?? {};
  const who = identity.email || identity.plan || identity.organization || null;
  const position = index === 0
    ? t('settings.models.first')
    : t('settings.models.fallback', { index });

  return (
    <SettingsCard
      title={
        <span className="flex items-center gap-2">
          <span>{account.label}</span>
          <span className="text-[0.7rem] text-[var(--text-muted)]">{info?.short ?? account.kind}</span>
        </span>
      }
      meta={
        <span className="flex items-center gap-2 flex-wrap">
          <span>{account.enabled ? position : t('settings.models.disabled')}</span>
          {who && <span className="text-[var(--text-muted)]">· {who}</span>}
          {account.kind === 'claude_code' && account.claude?.mode === 'agent' && (
            <span className="text-amber-400">· {t('settings.models.claude.modeAgent')}</span>
          )}
        </span>
      }
      status={{ tone: toneOf(account), label: account.status?.detail || '' }}
      footer={
        <div className="flex items-center gap-1.5 flex-wrap">
          <button
            type="button"
            className="p-1.5 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] disabled:opacity-30"
            disabled={index === 0}
            onClick={() => onMove(account.id, -1)}
            aria-label={t('settings.models.moveUp')}
          >
            <ChevronUp size={14} />
          </button>
          <button
            type="button"
            className="p-1.5 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] disabled:opacity-30"
            disabled={index >= total - 1}
            onClick={() => onMove(account.id, 1)}
            aria-label={t('settings.models.moveDown')}
          >
            <ChevronDown size={14} />
          </button>
          <button
            type="button"
            className="text-[0.75rem] px-2.5 py-1.5 rounded border border-[var(--border-color)] hover:bg-[var(--bg-hover)]"
            onClick={toggle}
          >
            {account.enabled ? t('settings.models.disabled') : t('settings.models.enable')}
          </button>
          <button
            type="button"
            className="flex items-center gap-1.5 text-[0.75rem] px-2.5 py-1.5 rounded border border-[var(--border-color)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
            disabled={busy === 'test'}
            onClick={test}
          >
            {busy === 'test' ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
            {busy === 'test' ? t('settings.models.testing') : t('settings.models.test')}
          </button>
          {SUBSCRIPTION_KINDS.has(account.kind) && (
            <button
              type="button"
              className="flex items-center gap-1.5 text-[0.75rem] px-2.5 py-1.5 rounded border border-[var(--border-color)] hover:bg-[var(--bg-hover)]"
              onClick={() => onLogin(account)}
            >
              <LogIn size={12} />
              {account.kind === 'codex'
                ? t('settings.models.codex.login')
                : t('settings.models.claude.login')}
            </button>
          )}
          {account.kind === 'codex' && (
            <button
              type="button"
              className="flex items-center gap-1.5 text-[0.75rem] px-2.5 py-1.5 rounded border border-[var(--border-color)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
              disabled={busy === 'import'}
              onClick={importCodex}
            >
              <Download size={12} /> {t('settings.models.codex.importCli')}
            </button>
          )}
          {account.kind === 'claude_code' && (
            <button
              type="button"
              className="flex items-center gap-1.5 text-[0.75rem] px-2.5 py-1.5 rounded border border-[var(--border-color)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
              disabled={busy === 'logout'}
              onClick={logout}
            >
              <LogOut size={12} /> {t('settings.models.claude.logout')}
            </button>
          )}
          <button
            type="button"
            className="flex items-center gap-1 text-[0.75rem] px-2.5 py-1.5 rounded border border-[var(--border-color)] hover:bg-[var(--bg-hover)]"
            onClick={() => setOpen((v) => !v)}
          >
            <ChevronRight size={12} className={open ? 'rotate-90 transition-transform' : 'transition-transform'} />
            {t('settings.models.label')}
          </button>
          <button
            type="button"
            className="ml-auto p-1.5 rounded hover:bg-rose-500/10 text-rose-400 disabled:opacity-50"
            disabled={busy === 'remove'}
            onClick={remove}
            aria-label={t('settings.models.remove')}
          >
            <Trash2 size={14} />
          </button>
        </div>
      }
    >
      {message && (
        <p className={`flex items-start gap-1.5 text-[0.75rem] ${message.tone === 'ok' ? 'text-emerald-400' : 'text-rose-300'}`}>
          {message.tone === 'ok' ? <CheckCircle2 size={12} className="mt-0.5 shrink-0" /> : <AlertCircle size={12} className="mt-0.5 shrink-0" />}
          {message.text}
        </p>
      )}

      {account.kind === 'claude_code' && cli && !cli.found && (
        <p className="text-[0.75rem] text-amber-400">{t('settings.models.claude.cliMissing')}</p>
      )}

      {open && (
        <div className="flex flex-col gap-3 mt-2 pt-3 border-t border-[var(--border-color)]">
          <Field label={t('settings.models.label')}>
            <input
              className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem]"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </Field>

          {(info?.needsBaseUrl || account.baseUrl) && (
            <Field label={t('settings.models.baseUrl')}>
              <input
                className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem] font-mono"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={info?.defaultBaseUrl}
              />
            </Field>
          )}

          {needsKey && (
            <Field label={t('settings.models.secret')}>
              <input
                type="password"
                className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem] font-mono"
                value={secret}
                onChange={(e) => setSecret(e.target.value)}
                placeholder={account.hasSecret ? t('settings.models.secretKept') : ''}
              />
            </Field>
          )}

          {account.kind === 'claude_code' && (
            <>
              <Field label={t('settings.models.claude.method')}>
                <select
                  className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem]"
                  value={authMethod}
                  onChange={(e) => setAuthMethod(e.target.value as ClaudeAuthMethod)}
                >
                  <option value="login">{t('settings.models.claude.methodLogin')}</option>
                  <option value="token">{t('settings.models.claude.methodToken')}</option>
                  <option value="api_key">{t('settings.models.claude.methodApiKey')}</option>
                  <option value="system">{t('settings.models.claude.methodSystem')}</option>
                </select>
              </Field>
              {(authMethod === 'token' || authMethod === 'api_key') && (
                <Field label={t('settings.models.secret')}>
                  <input
                    type="password"
                    className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem] font-mono"
                    value={secret}
                    onChange={(e) => setSecret(e.target.value)}
                    placeholder={account.hasSecret ? t('settings.models.secretKept') : ''}
                  />
                </Field>
              )}
              <Field label={t('settings.models.claude.mode')}>
                <select
                  className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem]"
                  value={mode}
                  onChange={(e) => setMode(e.target.value as ClaudeRunMode)}
                >
                  <option value="token">{t('settings.models.claude.modeToken')}</option>
                  <option value="agent">{t('settings.models.claude.modeAgent')}</option>
                </select>
                <p className="text-[0.7rem] text-[var(--text-muted)] mt-1">
                  {mode === 'token'
                    ? t('settings.models.claude.modeTokenHint')
                    : t('settings.models.claude.modeAgentHint')}
                </p>
              </Field>
            </>
          )}

          <Field label={t('settings.models.effort')}>
            <select
              className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem]"
              value={effort}
              onChange={(e) => setEffort(e.target.value)}
            >
              <option value="">{t('settings.models.effortAuto')}</option>
              {['low', 'medium', 'high', 'xhigh', 'max'].map((level) => (
                <option key={level} value={level}>{level}</option>
              ))}
            </select>
          </Field>

          {account.modelChoices?.length > 0 && (
            <Field label={t('settings.models.models')}>
              <p className="text-[0.75rem] text-[var(--text-muted)]">
                {account.modelChoices.slice(0, 6).map((m) => m.label).join(' · ')}
                {account.modelChoices.length > 6 ? ' …' : ''}
              </p>
            </Field>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              className="px-3 py-2 rounded bg-[var(--primary-color)] text-white text-[0.8125rem] disabled:opacity-50"
              disabled={busy === 'save'}
              onClick={save}
            >
              {busy === 'save' ? t('settings.models.saving') : t('settings.models.save')}
            </button>
            {!SUBSCRIPTION_KINDS.has(account.kind) && (
              <button
                type="button"
                className="flex items-center gap-1.5 px-3 py-2 rounded border border-[var(--border-color)] text-[0.8125rem] hover:bg-[var(--bg-hover)] disabled:opacity-50"
                disabled={busy === 'discover'}
                onClick={discover}
              >
                {busy === 'discover' ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                {t('settings.models.discover')}
              </button>
            )}
          </div>
        </div>
      )}
    </SettingsCard>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[0.75rem] text-[var(--text-secondary)]">{label}</span>
      {children}
    </label>
  );
}

// ── add ──────────────────────────────────────────────────────────────

function AddAccount({
  kinds, onAdded,
}: {
  kinds: Record<string, KindInfo>;
  /** The account that was just created, so a subscription kind can go
   *  straight into signing in — adding one and then hunting for a button is
   *  how "there is no OAuth login" happens when there is. */
  onAdded: (account: LlmAccount) => void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<AccountKind>('claude_code');
  const [label, setLabel] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [secret, setSecret] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const info = kinds[kind];

  useEffect(() => { setBaseUrl(info?.defaultBaseUrl ?? ''); }, [info?.defaultBaseUrl]);

  const submit = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const created = await llmAccountsApi.create({
        kind,
        label: label || undefined,
        baseUrl: baseUrl || undefined,
        secret: secret || undefined,
      });
      setOpen(false);
      setLabel('');
      setSecret('');
      onAdded(created.account);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [kind, label, baseUrl, secret, onAdded]);

  if (!open) {
    return (
      <button
        type="button"
        className="flex items-center justify-center gap-2 w-full py-3 rounded-[var(--border-radius)] border border-dashed border-[var(--border-color)] text-[0.8125rem] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
        onClick={() => setOpen(true)}
      >
        <Plus size={14} /> {t('settings.models.add')}
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-[var(--border-radius)] border border-[var(--border-color)] p-4">
      <h4 className="text-[0.875rem] font-semibold">{t('settings.models.addTitle')}</h4>
      <Field label={t('settings.models.kind')}>
        <select
          className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem]"
          value={kind}
          onChange={(e) => setKind(e.target.value as AccountKind)}
        >
          {Object.entries(kinds).map(([id, k]) => (
            <option key={id} value={id}>{k.label}</option>
          ))}
        </select>
      </Field>
      {info?.hint && <p className="text-[0.75rem] text-[var(--text-muted)]">{info.hint}</p>}

      <Field label={t('settings.models.label')}>
        <input
          className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem]"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={info?.short}
        />
      </Field>

      {(info?.needsBaseUrl || info?.defaultBaseUrl) && (
        <Field label={t('settings.models.baseUrl')}>
          <input
            className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem] font-mono"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={info?.defaultBaseUrl}
          />
        </Field>
      )}

      {(info?.secret === 'api_key' || info?.secret === 'optional_key') && (
        <Field label={t('settings.models.secret')}>
          <input
            type="password"
            className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem] font-mono"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
          />
        </Field>
      )}

      {error && <p className="text-[0.75rem] text-rose-300">{error}</p>}

      <div className="flex items-center gap-2">
        <button
          type="button"
          className="px-3 py-2 rounded bg-[var(--primary-color)] text-white text-[0.8125rem] disabled:opacity-50"
          disabled={saving}
          onClick={() => void submit()}
        >
          {saving
            ? t('settings.models.saving')
            : SUBSCRIPTION_KINDS.has(kind)
              ? t('settings.models.addAndSignIn')
              : t('settings.models.save')}
        </button>
        <button
          type="button"
          className="px-3 py-2 rounded border border-[var(--border-color)] text-[0.8125rem] hover:bg-[var(--bg-hover)]"
          onClick={() => setOpen(false)}
        >
          {t('settings.models.cancel')}
        </button>
      </div>
    </div>
  );
}

// ── the panel ────────────────────────────────────────────────────────

export default function ModelAccountsPanel() {
  const { t } = useI18n();
  const [accounts, setAccounts] = useState<LlmAccount[]>([]);
  const [kinds, setKinds] = useState<Record<string, KindInfo>>({});
  const [cli, setCli] = useState<CliInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loginFor, setLoginFor] = useState<LlmAccount | null>(null);
  // Only for the embedding card's "is a key set" line — the grid it came
  // from is gone.
  const [health, setHealth] = useState<ProviderHealth[]>([]);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [listed, catalogue] = await Promise.all([
        llmAccountsApi.list(),
        llmAccountsApi.kinds(),
      ]);
      setAccounts(listed.accounts);
      setKinds(catalogue.kinds);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    llmBackendsApi.health().then((r) => setHealth(r.providers)).catch(() => setHealth([]));
  }, []);

  useEffect(() => {
    // Only meaningful once a Claude Code account exists — probing otherwise
    // puts a "no binary" warning in front of someone who never asked for one.
    if (!accounts.some((a) => a.kind === 'claude_code')) return;
    llmAccountsApi.cli().then(setCli).catch(() => setCli(null));
  }, [accounts]);

  const move = useCallback(async (id: string, delta: number) => {
    const order = accounts.map((a) => a.id);
    const from = order.indexOf(id);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= order.length) return;
    order.splice(to, 0, ...order.splice(from, 1));
    // Optimistic: the list IS the route, so it should reorder under the
    // cursor rather than after a round trip.
    setAccounts((prev) => order.map((aid) => prev.find((a) => a.id === aid)!).filter(Boolean));
    try {
      const res = await llmAccountsApi.reorder(order);
      setAccounts(res.accounts);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      void refresh();
    }
  }, [accounts, refresh]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <h3 className="text-[1.0625rem] font-semibold">{t('settings.models.title')}</h3>
          <p className="text-[0.8125rem] text-[var(--text-secondary)] mt-1 leading-relaxed">
            {t('settings.models.description')}
          </p>
        </div>
        <button
          type="button"
          className="shrink-0 p-2 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)]"
          onClick={() => void refresh()}
          aria-label={t('settings.models.discover')}
        >
          <RefreshCw size={14} />
        </button>
      </div>

      {error && (
        <p className="flex items-start gap-1.5 text-[0.8125rem] text-rose-300">
          <AlertCircle size={14} className="mt-0.5 shrink-0" /> {error}
        </p>
      )}

      {loading ? (
        <p className="flex items-center gap-2 text-[0.8125rem] text-[var(--text-muted)]">
          <Loader2 size={14} className="animate-spin" /> {t('settings.models.loading')}
        </p>
      ) : accounts.length === 0 ? (
        <div className="flex flex-col items-center gap-1 py-8">
          <p className="text-[0.8125rem] text-[var(--text-secondary)]">{t('settings.models.empty')}</p>
          <p className="text-[0.75rem] text-[var(--text-muted)]">{t('settings.models.emptyHint')}</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {accounts.map((account, index) => (
            <AccountRow
              key={account.id}
              account={account}
              kinds={kinds}
              index={index}
              total={accounts.length}
              cli={cli}
              onChanged={() => void refresh()}
              onLogin={setLoginFor}
              onMove={(id, delta) => void move(id, delta)}
            />
          ))}
        </div>
      )}

      <AddAccount
        kinds={kinds}
        onAdded={(account) => {
          void refresh();
          // A Claude or ChatGPT account is useless until it is signed in, and
          // the sign-in is the part people cannot find. Open it.
          if (SUBSCRIPTION_KINDS.has(account.kind)) setLoginFor(account);
        }}
      />

      {/* Not an account: one key per provider, used to embed documents. A
           session never touches it, which is exactly why it is down here and
           labelled. */}
      <EmbeddingSettingsCard providers={health} />

      {/* The binary the Claude Code accounts spawn. A CLI too old for a flag
           the client sends fails in a way that reads as an account problem. */}
      {accounts.some((a) => a.kind === 'claude_code') && <ClaudeCodeVersionCard />}

      {loginFor && (
        <AccountLoginModal
          account={loginFor}
          onClose={() => setLoginFor(null)}
          onDone={() => { void refresh(); }}
        />
      )}
    </div>
  );
}
