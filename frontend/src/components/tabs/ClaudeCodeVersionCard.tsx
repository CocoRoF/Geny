'use client';

/**
 * The Claude Code CLI on this server: which version, and updating it.
 *
 * Lives next to the Claude Code accounts because that is the only thing it
 * affects — those accounts spawn this binary, and a CLI too old for a flag
 * the client sends is a failure that looks like an account problem. It
 * survived the removal of the provider grid for that reason; nothing else in
 * that panel described something a session actually uses.
 */

import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, ArrowUpCircle, RotateCcw } from 'lucide-react';

import { llmBackendsApi, type ClaudeCodeVersionStatus } from '@/lib/api';
import { IconButton, ActionButton } from '@/components/common/layout';
import { useI18n } from '@/lib/i18n';
import { SettingsCard } from '@/components/settings/SettingsCard';

export function ClaudeCodeVersionCard() {
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

export default ClaudeCodeVersionCard;
