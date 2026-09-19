'use client';

/**
 * Settings › Models — every way this server can reach a model.
 *
 * The list IS the default route: the first enabled account answers, and the
 * rest are tried, in order, only when one cannot. That is why order is
 * editable here and not buried in a dialog — it is the most consequential
 * setting on the page and the cheapest to get wrong.
 *
 * Every provider is on this page whether or not you have set it up: Claude
 * Code and ChatGPT under "sign in", the API keys under theirs, the endpoints
 * you host yourself under theirs — each with its own add button and as many
 * accounts as you want. A provider used to appear only after you had already
 * added an account to it, hidden until then inside one dropdown in one form,
 * which is how a server with a working Codex login reads as a server without
 * one.
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
  type CliInfo,
  type KindFamily,
  type EndpointCapabilities,
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

/** Clients that take an endpoint declaration — the OpenAI-compatible family
 *  and vLLM. Everywhere else the vendor answers the question itself and
 *  there is nothing to ask. Mirrors CAPABILITY_AWARE_PROVIDERS on the
 *  server; the server is the one that enforces it. */
const DECLARES_ITS_ENDPOINT = new Set(['custom', 'local', 'ollama', 'lmstudio', 'vllm']);

/** The flags worth a switch, in the order they matter. */
const CAPABILITY_FLAGS: (keyof EndpointCapabilities)[] = [
  'supports_vision',
  'supports_tools',
];

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
  const [capabilities, setCapabilities] = useState<EndpointCapabilities>(account.capabilities ?? {});

  const info = kinds[account.kind];
  const needsKey = info?.secret === 'api_key' || info?.secret === 'optional_key';
  // The kind's declaration is what the account inherits when it says nothing,
  // so the switch shows that as its starting position rather than "off".
  const declared = { ...(account.kindCapabilities ?? {}), ...capabilities };
  const showsCapabilities = DECLARES_ITS_ENDPOINT.has(info?.engineProvider ?? '');

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
      ...(showsCapabilities ? { capabilities } : {}),
      ...(account.kind === 'claude_code' ? { claude: { authMethod } } : {}),
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
            </>
          )}

          {showsCapabilities && (
            <Field label={t('settings.models.capabilities')}>
              <p className="text-[0.75rem] text-[var(--text-muted)] mb-1.5">
                {t('settings.models.capabilitiesHint')}
              </p>
              <div className="flex flex-col gap-1.5">
                {CAPABILITY_FLAGS.map((flag) => (
                  <label key={flag} className="flex items-center gap-2 text-[0.8125rem]">
                    <input
                      type="checkbox"
                      checked={Boolean(declared[flag])}
                      onChange={(e) => setCapabilities((prev) => ({ ...prev, [flag]: e.target.checked }))}
                    />
                    {t(`settings.models.capability.${flag}`)}
                  </label>
                ))}
              </div>
            </Field>
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

/** The long tail of OpenAI-compatible vendors, one click away.
 *
 *  Every provider stays on this page whether or not it is set up — a server
 *  with a working Codex login must not read as a server without one. That
 *  holds at nine providers and stops holding at twenty-one, where the five
 *  anyone uses sit under a screen of empty sections. Folded is not hidden:
 *  the count is on the button, and a vendor you have an account on never
 *  gets folded in the first place. */
function MoreProviders({ count, children }: { count: number; children: React.ReactNode }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <section className="flex flex-col gap-4">
      <button
        type="button"
        className="self-start flex items-center gap-1.5 text-[0.75rem] px-2.5 py-1.5 rounded border border-[var(--border-color)] hover:bg-[var(--bg-hover)]"
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronRight size={12} className={open ? 'rotate-90 transition-transform' : 'transition-transform'} />
        {t('settings.models.moreProviders', { n: count })}
      </button>
      {open && children}
    </section>
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

// ── adding one to a specific provider ────────────────────────────────

function AddToKind({
  kind, info, onAdded, onCancel,
}: {
  kind: AccountKind;
  info: KindInfo;
  onAdded: (account: LlmAccount) => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const [label, setLabel] = useState('');
  const [baseUrl, setBaseUrl] = useState(info.defaultBaseUrl ?? '');
  const [secret, setSecret] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const needsKey = info.secret === 'api_key' || info.secret === 'optional_key';
  const wantsBaseUrl = info.needsBaseUrl || Boolean(info.defaultBaseUrl);

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
      onAdded(created.account);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [kind, label, baseUrl, secret, onAdded]);

  return (
    <div className="flex flex-col gap-3 rounded-[var(--border-radius)] border border-[var(--primary-color)]/40 bg-[var(--bg-tertiary)]/40 p-4">
      <Field label={t('settings.models.label')}>
        <input
          className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem]"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder={info.short}
          autoFocus
        />
      </Field>

      {wantsBaseUrl && (
        <Field label={t('settings.models.baseUrl')}>
          <input
            className="w-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded px-3 py-2 text-[0.8125rem] font-mono"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={info.defaultBaseUrl}
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
          onClick={onCancel}
        >
          {t('settings.models.cancel')}
        </button>
      </div>
    </div>
  );
}

// ── one provider, and every account on it ────────────────────────────
//
// Each provider is on the page whether or not it has an account, with its own
// add button. That is the whole point of this layout: a provider you have not
// set up yet used to be invisible — one entry in a dropdown inside a form you
// had to know to open — which is why "Codex has no OAuth login" was a
// reasonable thing to conclude about a server that has had it all along.

function ProviderGroup({
  kind, info, accounts, kinds, cli, order, onChanged, onLogin, onMove,
}: {
  kind: AccountKind;
  info: KindInfo;
  accounts: LlmAccount[];
  kinds: Record<string, KindInfo>;
  cli: CliInfo | null;
  /** Every account id in route order, so a row can show its own position. */
  order: string[];
  onChanged: () => void;
  onLogin: (account: LlmAccount) => void;
  onMove: (id: string, delta: number) => void;
}) {
  const { t } = useI18n();
  const [adding, setAdding] = useState(false);

  return (
    <section className="flex flex-col gap-2.5">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-[0.875rem] font-semibold flex items-center gap-2">
            {info.label}
            {accounts.length > 0 && (
              <span className="text-[0.7rem] font-normal text-[var(--text-muted)]">
                {t('settings.models.accountCount', { n: accounts.length })}
              </span>
            )}
          </h4>
          {info.hint && (
            <p className="text-[0.75rem] text-[var(--text-muted)] mt-0.5 leading-relaxed">{info.hint}</p>
          )}
        </div>
        <button
          type="button"
          className="shrink-0 flex items-center gap-1.5 text-[0.75rem] px-2.5 py-1.5 rounded border border-[var(--border-color)] hover:bg-[var(--bg-hover)]"
          onClick={() => setAdding((v) => !v)}
        >
          <Plus size={12} />
          {SUBSCRIPTION_KINDS.has(kind)
            ? t('settings.models.addLogin')
            : t('settings.models.addKey')}
        </button>
      </header>

      {accounts.map((account) => (
        <AccountRow
          key={account.id}
          account={account}
          kinds={kinds}
          index={order.indexOf(account.id)}
          total={order.length}
          cli={cli}
          onChanged={onChanged}
          onLogin={onLogin}
          onMove={onMove}
        />
      ))}

      {adding && (
        <AddToKind
          kind={kind}
          info={info}
          onCancel={() => setAdding(false)}
          onAdded={(account) => {
            setAdding(false);
            onChanged();
            // A subscription account is useless until it is signed in, and
            // the sign-in is the part people cannot find. Open it.
            if (SUBSCRIPTION_KINDS.has(account.kind)) onLogin(account);
          }}
        />
      )}
    </section>
  );
}

// ── the route, as an order ───────────────────────────────────────────

function RouteOrder({
  accounts, kinds, onMove,
}: {
  accounts: LlmAccount[];
  kinds: Record<string, KindInfo>;
  onMove: (id: string, delta: number) => void;
}) {
  const { t } = useI18n();
  const enabled = accounts.filter((a) => a.enabled);
  return (
    <div className="rounded-[var(--border-radius)] border border-[var(--border-color)] p-4 flex flex-col gap-2">
      <div>
        <h4 className="text-[0.875rem] font-semibold">{t('settings.models.order')}</h4>
        <p className="text-[0.75rem] text-[var(--text-muted)] mt-0.5 leading-relaxed">
          {t('settings.models.orderHint')}
        </p>
      </div>
      {enabled.length === 0 ? (
        <p className="text-[0.8125rem] text-[var(--text-secondary)]">{t('settings.models.orderEmpty')}</p>
      ) : (
        <ol className="flex flex-col gap-1">
          {enabled.map((account, index) => (
            <li key={account.id} className="flex items-center gap-2 text-[0.8125rem]">
              <span className="w-5 text-[var(--text-muted)] tabular-nums">{index + 1}.</span>
              <span
                className={
                  account.status?.ok === false
                    ? 'w-1.5 h-1.5 rounded-full bg-rose-400 shrink-0'
                    : 'w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0'
                }
              />
              <span className="truncate">{account.label}</span>
              <span className="text-[0.7rem] text-[var(--text-muted)] truncate">
                {kinds[account.kind]?.short ?? account.kind}
                {account.identity?.email ? ` · ${account.identity.email}` : ''}
              </span>
              <span className="ml-auto flex items-center">
                <button
                  type="button"
                  className="p-1 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] disabled:opacity-30"
                  disabled={index === 0}
                  onClick={() => onMove(account.id, -1)}
                  aria-label={t('settings.models.moveUp')}
                >
                  <ChevronUp size={13} />
                </button>
                <button
                  type="button"
                  className="p-1 rounded hover:bg-[var(--bg-hover)] text-[var(--text-muted)] disabled:opacity-30"
                  disabled={index >= enabled.length - 1}
                  onClick={() => onMove(account.id, 1)}
                  aria-label={t('settings.models.moveDown')}
                >
                  <ChevronDown size={13} />
                </button>
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ── the panel ────────────────────────────────────────────────────────

export default function ModelAccountsPanel() {
  const { t } = useI18n();
  const [accounts, setAccounts] = useState<LlmAccount[]>([]);
  const [kinds, setKinds] = useState<Record<string, KindInfo>>({});
  const [families, setFamilies] = useState<{ id: KindFamily; label: string }[]>([]);
  const [cli, setCli] = useState<CliInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loginFor, setLoginFor] = useState<LlmAccount | null>(null);
  // Only for the embedding card's "is a key set" line — the provider grid it
  // came from is gone.
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
      setFamilies(catalogue.families ?? []);
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
    // Order is over ALL accounts (that is what the server stores), but the
    // arrows move within the enabled ones — stepping over a disabled account
    // would look like the button did nothing.
    const order = accounts.map((a) => a.id);
    const enabled = accounts.filter((a) => a.enabled).map((a) => a.id);
    const at = enabled.indexOf(id);
    const neighbour = enabled[at + delta];
    if (at < 0 || !neighbour) return;
    const from = order.indexOf(id);
    const to = order.indexOf(neighbour);
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

  const order = accounts.map((a) => a.id);

  return (
    <div className="flex flex-col gap-5">
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
      ) : (
        <>
          <RouteOrder accounts={accounts} kinds={kinds} onMove={(id, d) => void move(id, d)} />

          {families.map((family) => {
            const entries = Object.entries(kinds)
              .filter(([, info]) => info.family === family.id) as [AccountKind, KindInfo][];
            if (entries.length === 0) return null;
            const group = (kind: AccountKind, info: KindInfo) => (
              <ProviderGroup
                key={kind}
                kind={kind}
                info={info}
                kinds={kinds}
                accounts={accounts.filter((a) => a.kind === kind)}
                cli={cli}
                order={order}
                onChanged={() => void refresh()}
                onLogin={setLoginFor}
                onMove={(id, d) => void move(id, d)}
              />
            );
            // A vendor you have an account on is never folded away, however
            // long its tail — the list IS the route, and a hop you cannot
            // see is a hop you cannot reorder.
            const isOpen = ([kind, info]: [AccountKind, KindInfo]) =>
              info.primary !== false || accounts.some((a) => a.kind === kind);
            const shown = entries.filter(isOpen);
            const folded = entries.filter((e) => !isOpen(e));
            return (
              <div key={family.id} className="flex flex-col gap-4">
                <h4 className="text-[0.7rem] font-semibold uppercase tracking-[0.08em] text-[var(--text-muted)] border-b border-[var(--border-color)] pb-1.5">
                  {family.label}
                </h4>
                {shown.map(([kind, info]) => group(kind, info))}
                {folded.length > 0 && (
                  <MoreProviders count={folded.length}>
                    {folded.map(([kind, info]) => group(kind, info))}
                  </MoreProviders>
                )}
              </div>
            );
          })}
        </>
      )}

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
