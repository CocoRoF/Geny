/**
 * LLM Backends panel — Phase H polish.
 *
 * Single edit surface for the 6 executor providers. Cards are clickable
 * tiles with a status badge + auth-method chip + dynamic detail line.
 * All static strings flow through ``useI18n``; the dynamic detail / install
 * help strings come from the backend as ``detail_code`` + ``detail_params``
 * which we render through the same i18n bundle (English ``detail`` string
 * is a fallback for codes the frontend doesn't yet recognise).
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Loader2, RefreshCw,
  ExternalLink, ArrowUpCircle, RotateCcw,
} from 'lucide-react';

import { llmBackendsApi, syncApi, type ProviderHealth, type ClaudeCodeVersionStatus } from '@/lib/api';
import { IconButton, ActionButton } from '@/components/common/layout';
import { useI18n } from '@/lib/i18n';
import { SettingsCard, type CardStatusTone } from '@/components/settings/SettingsCard';
import { EmbeddingSettingsCard } from '@/components/tabs/EmbeddingSettingsCard';
import ClaudeCodeAuthModal from './ClaudeCodeAuthModal';
import ApiBackendModal from './ApiBackendModal';
import LocalBackendModal, { type LocalProviderId } from './LocalBackendModal';
import { PROVIDERS } from '@/lib/modelCatalog';

const API_PROVIDERS = new Set(['anthropic', 'openai', 'google', 'vllm']);
const LOCAL_PROVIDERS = new Set<string>(['ollama', 'lmstudio', 'custom']);


function renderDetail(
  provider: ProviderHealth,
  t: (key: string, vars?: Record<string, string | number>) => string,
): string {
  if (provider.detail_code) {
    const key = `settings.llmBackends.detail.${provider.detail_code}`;
    const rendered = t(key, provider.detail_params ?? {});
    // ``t`` returns the key itself when missing — fall back to server English.
    if (rendered !== key) return rendered;
  }
  return provider.detail || '—';
}


function renderInstallHelp(
  provider: ProviderHealth,
  t: (key: string) => string,
): string | null {
  if (provider.install_help_code) {
    const key = `settings.llmBackends.installHelp.${provider.install_help_code}`;
    const rendered = t(key);
    if (rendered !== key) return rendered;
  }
  return provider.install_help || null;
}


function ProviderCard({
  provider,
  onRecheck,
  recheckLoading,
  onOpenSettings,
}: {
  provider: ProviderHealth;
  onRecheck: (id: string) => Promise<void>;
  recheckLoading: string | null;
  onOpenSettings: (providerId: string) => void;
}) {
  const { t } = useI18n();
  const isCli = provider.kind === 'cli';
  const recheckTarget =
    provider.provider === 'claude_code_cli' ? 'claude_code_cli'
    : null;
  const recheckActive = recheckLoading === recheckTarget;

  let tone: CardStatusTone;
  let badgeLabel: string;
  if (provider.available && provider.auth_ok) {
    tone = 'good';
    badgeLabel = t('settings.llmBackends.badge.ready');
  } else if (provider.detail_code === 'api.key_rejected') {
    // Cloud API key the provider itself rejected (401) — distinct from
    // CLI "login required" AND from unreachable local backends.
    tone = 'bad';
    badgeLabel = t('settings.llmBackends.badge.keyRejected');
  } else if (provider.auth_ok === false) {
    tone = 'warn';
    badgeLabel = t('settings.llmBackends.badge.loginRequired');
  } else if (!provider.available) {
    tone = 'bad';
    badgeLabel = t('settings.llmBackends.badge.notConfigured');
  } else {
    tone = 'neutral';
    badgeLabel = t('settings.llmBackends.badge.idle');
  }

  const detail = renderDetail(provider, t);
  const installHelp = renderInstallHelp(provider, (k) => t(k));
  const authMethodKey = provider.auth_method
    ? `settings.llmBackends.authMethod.${provider.auth_method}`
    : null;

  return (
    <SettingsCard
      onClick={() => onOpenSettings(provider.provider)}
      ariaLabel={t('settings.llmBackends.cardAriaLabel', { label: provider.label })}
      title={provider.label}
      meta={
        <>
          <span className="font-mono">{provider.provider}</span>
          <span className="opacity-50">·</span>
          <span className="uppercase tracking-wide">{isCli ? 'CLI' : 'API'}</span>
        </>
      }
      status={{ tone, label: badgeLabel }}
      footer={
        <>
          {authMethodKey && (
            <span className="text-[0.7rem] text-[var(--text-tertiary)]">
              {t('settings.llmBackends.auth')}:{' '}
              <span className="text-[var(--text-secondary)]">{t(authMethodKey)}</span>
            </span>
          )}
          {provider.binary_version && (
            <span className="text-[0.7rem] text-[var(--text-tertiary)] font-mono">
              {provider.binary_version}
            </span>
          )}
          {recheckTarget && (
            <button
              type="button"
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-[var(--border-color)] text-[0.7rem] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] disabled:opacity-50"
              onClick={(e) => { e.stopPropagation(); onRecheck(recheckTarget); }}
              disabled={recheckActive}
              aria-label={t('settings.llmBackends.reCheck')}
            >
              {recheckActive
                ? <Loader2 className="w-3 h-3 animate-spin" />
                : <RefreshCw className="w-3 h-3" />}
              {t('settings.llmBackends.reCheck')}
            </button>
          )}
          {provider.provider === 'claude_code_cli' && (
            <a
              href="https://docs.anthropic.com/claude/code"
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 text-[0.7rem] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:underline"
            >
              {t('settings.llmBackends.docs')} <ExternalLink className="w-3 h-3" />
            </a>
          )}
          {installHelp && (
            <span className="basis-full text-[0.72rem] text-[var(--text-tertiary)] bg-[var(--bg-tertiary)] rounded-md px-2 py-1.5 leading-relaxed">
              {installHelp}
            </span>
          )}
        </>
      }
    >
      {detail}
    </SettingsCard>
  );
}


export default function LLMBackendsPanel({ embedded = false }: { embedded?: boolean } = {}) {
  return <LLMBackendsPanelInner embedded={embedded} />;
}

// ── Claude Code CLI version manager (keep-latest + rollback) ─────────
function ClaudeCodeVersionCard() {
  const { t } = useI18n();
  const [st, setSt] = useState<ClaudeCodeVersionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'' | 'update' | 'rollback'>('');
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setSt(await llmBackendsApi.claudeCodeVersion());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const doUpdate = async () => {
    setBusy('update'); setErr(null);
    try { setSt(await llmBackendsApi.claudeCodeUpdate('latest')); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(''); }
  };
  const doRollback = async () => {
    setBusy('rollback'); setErr(null);
    try { setSt(await llmBackendsApi.claudeCodeRollback()); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(''); }
  };

  const upToDate = st && st.current && st.latest && st.current === st.latest;

  return (
    <SettingsCard
      title={t('llmBackendsPanel.versionTitle')}
      meta={st?.current ? <span className="font-mono">v{st.current}</span> : t('llmBackendsPanel.notInstalled')}
      status={
        st
          ? {
              tone: upToDate ? 'good' : st.update_available ? 'warn' : 'neutral',
              label: loading ? '…' : upToDate ? t('llmBackendsPanel.latest') : st.update_available ? t('llmBackendsPanel.updateAvailable') : t('llmBackendsPanel.check'),
            }
          : undefined
      }
      footer={
        <>
          <IconButton
            icon={RefreshCw}
            title={t('llmBackendsPanel.refresh')}
            spin={loading}
            onClick={refresh}
            disabled={loading || !!busy}
          />
          <ActionButton
            type="button"
            icon={ArrowUpCircle}
            spinIcon={busy === 'update'}
            onClick={doUpdate}
            disabled={!!busy || loading || !!upToDate}
          >
            {t('llmBackendsPanel.updateToLatest')}
          </ActionButton>
          <ActionButton
            type="button"
            icon={RotateCcw}
            spinIcon={busy === 'rollback'}
            onClick={doRollback}
            disabled={!!busy || loading || !st?.can_rollback}
            title={st?.previous ? t('llmBackendsPanel.rollbackTitle', { version: st.previous }) : t('llmBackendsPanel.rollbackUnavailable')}
          >
            {st?.previous ? t('llmBackendsPanel.rollbackTo', { version: st.previous }) : t('llmBackendsPanel.rollback')}
          </ActionButton>
          {err && (
            <span className="basis-full text-[0.72rem] text-[var(--danger-color)] bg-[var(--bg-tertiary)] rounded-md px-2 py-1.5 break-all">
              {err}
            </span>
          )}
        </>
      }
    >
      {st?.current
        ? upToDate
          ? t('llmBackendsPanel.upToDate')
          : st.latest
            ? t('llmBackendsPanel.newVersionAvailable', { version: st.latest })
            : t('llmBackendsPanel.latestUnknown')
        : t('llmBackendsPanel.cliNotInstalled')}
      {st?.pinned && (
        <span className="text-[var(--text-tertiary)]"> · {t('llmBackendsPanel.pinned', { version: st.pinned === 'latest' ? t('llmBackendsPanel.latest') : `v${st.pinned}` })}</span>
      )}
    </SettingsCard>
  );
}

function LLMBackendsPanelInner({ embedded }: { embedded: boolean }) {
  const { t } = useI18n();
  const [providers, setProviders] = useState<ProviderHealth[]>([]);
  const [loading, setLoading] = useState(false);
  // Cross-service key sync (Geny → GAPT + avatar)
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const handleSyncKeys = useCallback(async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const r = await syncApi.providerKeysNow();
      const parts: string[] = [];
      for (const [k, v] of Object.entries(r.results || {})) {
        if (v && typeof v === 'object') {
          parts.push(`${k.replace(/_API_KEY|_API_TOKEN|_KEY/g, '')}: ${Object.entries(v).map(([t, s]) => `${t}=${s}`).join(', ')}`);
        }
      }
      setSyncMsg(parts.length ? parts.join(' · ') : t('llmBackendsPanel.syncNoKeys'));
    } catch (e: any) {
      setSyncMsg(t('llmBackendsPanel.syncFailed', { error: e?.message || e }));
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncMsg(null), 8000);
    }
  }, [t]);
  const [recheckLoading, setRecheckLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openProvider, setOpenProvider] = useState<string | null>(null);

  const fetchHealth = useCallback(async (revalidate = false) => {
    setLoading(true);
    setError(null);
    try {
      const res = await llmBackendsApi.health(revalidate);
      setProviders(res.providers);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchHealth(); }, [fetchHealth]);

  const handleRecheck = useCallback(
    async (provider: string) => {
      // Only ``claude_code_cli`` has a per-provider recheck endpoint
      // today; API providers re-fetch the full health card instead
      // (with a forced key re-probe).
      if (provider !== 'claude_code_cli') {
        await fetchHealth(true);
        return;
      }
      setRecheckLoading(provider);
      try {
        const res = await llmBackendsApi.recheckClaudeCode();
        setProviders((prev) =>
          prev.map((p) => (p.provider === res.provider ? res : p)),
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setRecheckLoading(null);
      }
    },
    [fetchHealth],
  );

  const providerLabelById = useMemo(() => {
    const m: Record<string, string> = {};
    providers.forEach((p) => { m[p.provider] = p.label; });
    return m;
  }, [providers]);

  return (
    <div className="flex flex-col gap-4">
      {/* Header. Hidden when this panel sits inside the Models page — that
           page already said what this section is, and repeating it there
           reads as two settings rather than one. */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          {!embedded && (
            <>
              <h3 className="text-[1.0625rem] font-semibold">{t('settings.llmBackends.title')}</h3>
              <p className="text-[0.8125rem] text-[var(--text-secondary)] mt-1 leading-relaxed">
                {t('settings.llmBackends.description', {
                  count: providers.length || PROVIDERS.length,
                })}
              </p>
            </>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {/* Push Geny's provider keys to connected sister services (GAPT + avatar).
               Auto-syncs on key change; this is a manual re-push. */}
          <ActionButton
            icon={RefreshCw}
            spinIcon={syncing}
            onClick={handleSyncKeys}
            disabled={syncing}
            title={t('llmBackendsPanel.syncKeysTitle')}
          >
            {t('llmBackendsPanel.syncKeys')}
          </ActionButton>
          <IconButton
            icon={RefreshCw}
            title={t('settings.llmBackends.refreshAll')}
            spin={loading}
            onClick={() => fetchHealth(true)}
            disabled={loading}
          />
        </div>
      </div>
      {syncMsg && (
        <div className="rounded border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[0.75rem] text-[var(--text-secondary)] px-3 py-2">
          {syncMsg}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded border border-rose-500/30 bg-rose-500/10 text-rose-300 text-[0.8125rem] p-3">
          {error}
        </div>
      )}

      {/* Loading */}
      {providers.length === 0 && loading && (
        <div className="text-[var(--text-tertiary)] text-[0.8125rem]">
          {t('settings.llmBackends.loading')}
        </div>
      )}

      {/* Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {providers.map((p) => (
          <ProviderCard
            key={p.provider}
            provider={p}
            onRecheck={handleRecheck}
            recheckLoading={recheckLoading}
            onOpenSettings={(id) => setOpenProvider(id)}
          />
        ))}
        {/* Common embedding setting — which provider/model embeds
             knowledge documents. Key comes from the cards above. */}
        {providers.length > 0 && (
          <EmbeddingSettingsCard providers={providers} />
        )}
      </div>

      {/* Claude Code CLI version management */}
      <ClaudeCodeVersionCard />

      {/* Modals */}
      {openProvider === 'claude_code_cli' && (
        <ClaudeCodeAuthModal
          onClose={() => setOpenProvider(null)}
          onChange={() => fetchHealth()}
        />
      )}

      {openProvider && API_PROVIDERS.has(openProvider) && (
        <ApiBackendModal
          providerId={openProvider as 'anthropic' | 'openai' | 'google' | 'vllm'}
          providerLabel={providerLabelById[openProvider] || openProvider}
          onClose={() => setOpenProvider(null)}
          onChange={() => fetchHealth()}
        />
      )}

      {openProvider && LOCAL_PROVIDERS.has(openProvider) && (
        <LocalBackendModal
          providerId={openProvider as LocalProviderId}
          providerLabel={providerLabelById[openProvider] || openProvider}
          onClose={() => setOpenProvider(null)}
          onChange={() => fetchHealth()}
        />
      )}
    </div>
  );
}
