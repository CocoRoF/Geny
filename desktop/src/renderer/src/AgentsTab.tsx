/**
 * Agents — the cockpit for work running on the server.
 *
 * The point of a server-side agent is that you are not watching it. So this
 * tab answers the two questions that replaces: which model is it using (and
 * change it, without ending the conversation), and what has it actually done
 * — each file written, each command and how it exited, each failure.
 *
 * The activity list is derived from the server's session log, so it is the
 * same record the web UI reads and it survives a restart.
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import {
  accounts, agents,
  type ActivityEntry, type AgentRoute, type AgentSummary,
  type LastRoute, type LlmAccount, type WorkspaceSummary,
} from './server'

type T = (key: string, vars?: Record<string, string | number>) => string

type View = 'activity' | 'summary'

function when(ts?: string): string {
  if (!ts) return ''
  const at = new Date(ts)
  return Number.isNaN(at.getTime()) ? '' : at.toLocaleTimeString()
}

function ActivityRow({ entry, t }: { entry: ActivityEntry; t: T }): ReactNode {
  const failed = entry.kind === 'error'
  const tone = failed ? 'is-err' : entry.ok === true ? 'is-ok' : ''

  let line: string
  if (entry.kind === 'file' || entry.failedKind === 'file') {
    const delta = [
      entry.linesAdded ? `+${entry.linesAdded}` : '',
      entry.linesRemoved ? `-${entry.linesRemoved}` : '',
    ].filter(Boolean).join(' ')
    line = `${entry.operation ?? 'write'} ${entry.path ?? ''}${delta ? `  ${delta}` : ''}`
  } else if (entry.kind === 'command' || entry.failedKind === 'command') {
    line = `$ ${entry.command ?? ''}`
  } else if (entry.kind === 'read') {
    line = `read ${entry.path ?? ''}`
  } else if (entry.kind === 'turn') {
    line = `${entry.role === 'user' ? '›' : '‹'} ${(entry.text ?? '').slice(0, 160)}`
  } else if (entry.kind === 'route') {
    line = t('agents.routeUsed', { label: entry.label ?? '', model: entry.model ?? '' })
  } else {
    line = `${entry.tool ?? ''} ${entry.detail ?? ''}`.trim()
  }

  return (
    <div className="gy-kv" style={{ alignItems: 'flex-start' }}>
      <span className="gy-hint" style={{ minWidth: 62 }}>{when(entry.ts)}</span>
      <span className={`gy-pill ${tone}`} style={{ flex: 1, minWidth: 0 }}>
        <span className="gy-msg" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {line}
          {entry.durationMs ? `  (${entry.durationMs}ms)` : ''}
          {failed && entry.error ? `\n${entry.error}` : ''}
          {entry.kind === 'command' && entry.output ? `\n${entry.output}` : ''}
        </span>
      </span>
    </div>
  )
}

export function AgentsTab({ t }: { t: T }): ReactNode {
  const [list, setList] = useState<AgentSummary[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [route, setRoute] = useState<AgentRoute | null>(null)
  const [lastRoute, setLastRoute] = useState<LastRoute | null>(null)
  const [available, setAvailable] = useState<LlmAccount[]>([])
  const [activity, setActivity] = useState<ActivityEntry[]>([])
  const [summary, setSummary] = useState<WorkspaceSummary | null>(null)
  const [view, setView] = useState<View>('activity')
  const [filter, setFilter] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [follow, setFollow] = useState(true)

  const loadAgents = useCallback(async () => {
    try {
      const rows = await agents.list()
      setList(rows)
      setError(null)
      setSelected((prev) => prev ?? rows[0]?.session_id ?? null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  useEffect(() => { void loadAgents() }, [loadAgents])
  useEffect(() => {
    accounts.list().then((r) => setAvailable(r.accounts.filter((a) => a.enabled))).catch(() => undefined)
  }, [])

  const loadDetail = useCallback(async () => {
    if (!selected) return
    try {
      const [state, act] = await Promise.all([
        agents.route(selected),
        agents.activity(selected, filter || undefined),
      ])
      setRoute(state.route)
      setLastRoute(state.last_route)
      setActivity(act.entries)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [selected, filter])

  useEffect(() => { void loadDetail() }, [loadDetail])

  // The record is the whole point of running an agent you are not watching,
  // so it refreshes on its own while this tab is open.
  useEffect(() => {
    if (!follow || !selected || view !== 'activity') return
    const timer = window.setInterval(() => { void loadDetail() }, 4000)
    return () => window.clearInterval(timer)
  }, [follow, selected, view, loadDetail])

  useEffect(() => {
    if (view !== 'summary' || !selected) return
    agents.summary(selected).then(setSummary).catch((e) => setError((e as Error).message))
  }, [view, selected])

  const current = useMemo(
    () => list.find((a) => a.session_id === selected) ?? null,
    [list, selected],
  )

  const accountById = useMemo(
    () => new Map(available.map((a) => [a.id, a])),
    [available],
  )

  const switchModel = useCallback(async (accountId: string, model: string) => {
    if (!selected) return
    setBusy(true)
    setNote(null)
    try {
      // Every other account stays a fallback, in the order the server keeps
      // them — changing model should not also remove the safety net.
      const next: AgentRoute = {
        primary: { accountId, model },
        fallbacks: available
          .filter((a) => a.id !== accountId)
          .map((a) => ({ accountId: a.id, model: a.modelChoices[0]?.id })),
      }
      const result = await agents.setRoute(selected, next)
      setRoute(next)
      setNote(result.applies === 'immediately'
        ? t('agents.switchedNow', { label: accountById.get(accountId)?.label ?? '', model })
        : t('agents.switchedNext', { label: accountById.get(accountId)?.label ?? '', model }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [selected, available, accountById, t])

  const primary = route?.primary ?? null
  const primaryAccount = primary ? accountById.get(primary.accountId) : undefined

  return (
    <>
      <section className="gy-card">
        <div className="gy-card-h">{t('agents.title')}</div>
        <p className="gy-hint">{t('agents.hint')}</p>
        <div className="gy-spacer" />
        <div className="gy-row">
          <select className="gy-input grow" value={selected ?? ''}
            onChange={(e) => { setSelected(e.target.value || null); setSummary(null) }}>
            <option value="">{t('agents.pick')}</option>
            {list.map((a) => (
              <option key={a.session_id} value={a.session_id}>
                {(a.session_name || a.session_id.slice(0, 8))} · {a.status}
              </option>
            ))}
          </select>
          <button className="gy-btn gy-btn--ghost gy-btn--sm" onClick={() => void loadAgents()}>
            {t('agents.refresh')}
          </button>
        </div>
        {error && <p className="gy-hint" style={{ color: 'var(--gy-err, #f87171)' }}>{error}</p>}
      </section>

      {current && (
        <section className="gy-card">
          <div className="gy-card-h">{t('agents.modelCard')}</div>
          <div className="gy-row">
            <span className="gy-pill grow">
              <span className="gy-dot" />
              <span className="gy-msg">
                {primaryAccount
                  ? `${primaryAccount.label} · ${primary?.model ?? ''}`
                  : t('agents.noAccount')}
              </span>
            </span>
          </div>
          {lastRoute?.label && (
            <p className="gy-hint">
              {t('agents.answeredBy', { label: lastRoute.label, model: lastRoute.model ?? '' })}
              {lastRoute.failedOver ? ` · ${t('agents.failedOver')}` : ''}
            </p>
          )}
          <div className="gy-spacer" />
          <select className="gy-input" value={primary ? `${primary.accountId}:${primary.model}` : ''}
            disabled={busy || available.length === 0}
            onChange={(e) => {
              const [accountId, ...rest] = e.target.value.split(':')
              if (accountId) void switchModel(accountId, rest.join(':'))
            }}>
            <option value="">{t('agents.pickModel')}</option>
            {available.map((account) => (
              <optgroup key={account.id} label={account.label}>
                {account.modelChoices.map((choice) => (
                  <option key={`${account.id}:${choice.id}`} value={`${account.id}:${choice.id}`}>
                    {choice.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <p className="gy-hint">{t('agents.keepsConversation')}</p>
          {note && <p className="gy-hint">{note}</p>}
        </section>
      )}

      {current && (
        <section className="gy-card">
          <div className="gy-card-h">{t('agents.activityCard')}</div>
          <div className="gy-row">
            <button className={`gy-btn gy-btn--sm ${view === 'activity' ? 'gy-btn--primary' : 'gy-btn--ghost'}`}
              onClick={() => setView('activity')}>{t('agents.viewActivity')}</button>
            <button className={`gy-btn gy-btn--sm ${view === 'summary' ? 'gy-btn--primary' : 'gy-btn--ghost'}`}
              onClick={() => setView('summary')}>{t('agents.viewSummary')}</button>
          </div>

          {view === 'activity' ? (
            <>
              <div className="gy-spacer" />
              <div className="gy-row">
                <select className="gy-input grow" value={filter} onChange={(e) => setFilter(e.target.value)}>
                  <option value="">{t('agents.filterAll')}</option>
                  <option value="file">{t('agents.filterFiles')}</option>
                  <option value="command">{t('agents.filterCommands')}</option>
                  <option value="error">{t('agents.filterErrors')}</option>
                  <option value="turn">{t('agents.filterTurns')}</option>
                </select>
                <label className="gy-toggle-line">
                  <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
                  <span>{t('agents.follow')}</span>
                </label>
              </div>
              <div className="gy-spacer" />
              {activity.length === 0 ? (
                <p className="gy-hint">{t('agents.nothingYet')}</p>
              ) : (
                <div style={{ maxHeight: 340, overflow: 'auto', display: 'grid', gap: 6 }}>
                  {activity.map((entry) => (
                    <ActivityRow key={entry.seq} entry={entry} t={t} />
                  ))}
                </div>
              )}
            </>
          ) : summary ? (
            <>
              <div className="gy-spacer" />
              <p className="gy-hint">
                {t('agents.summaryLine', {
                  files: summary.files.length,
                  commands: summary.commands.length,
                  failures: summary.failures.length,
                  turns: summary.turns,
                })}
              </p>
              {summary.files.map((file) => (
                <div className="gy-kv" key={file.path}>
                  <span className="gy-msg" style={{ wordBreak: 'break-all' }}>{file.path}</span>
                  <span className="gy-hint">
                    {file.operations.join('/')} · +{file.linesAdded} -{file.linesRemoved}
                  </span>
                </div>
              ))}
              {summary.failures.length > 0 && (
                <>
                  <div className="gy-spacer" />
                  <div className="gy-card-h">{t('agents.failures')}</div>
                  {summary.failures.map((failure) => (
                    <p className="gy-hint" key={failure.seq}>
                      {failure.tool}: {failure.error}
                    </p>
                  ))}
                </>
              )}
            </>
          ) : (
            <p className="gy-hint">{t('agents.loading')}</p>
          )}
        </section>
      )}
    </>
  )
}

export default AgentsTab
