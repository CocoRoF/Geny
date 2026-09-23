/**
 * Which model is answering — and switching it without leaving the chat.
 *
 * A route is an ORDER, not a choice: the first account that can answer does,
 * and the rest are there for when it cannot. So this shows two things that
 * are easy to confuse and must not be: the account the session is POINTED at,
 * and the one that actually ANSWERED the last turn. When a fallback took over
 * they differ, and a header that only showed the first one would be telling
 * the user something untrue every time it mattered most.
 *
 * Picking an account here swaps the live session's credentials in place. The
 * conversation, its tools, its memory and its files all carry on — the next
 * turn simply leaves through a different door.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { accounts, agents, type AgentRoute, type LastRoute, type LlmAccount } from '../server'

type T = (key: string, vars?: Record<string, string | number>) => string

export function RouteBar({ sessionId, t }: { sessionId: string | null; t: T }): ReactNode {
  const [list, setList] = useState<LlmAccount[]>([])
  const [route, setRoute] = useState<AgentRoute | null>(null)
  const [last, setLast] = useState<LastRoute | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)

  const refresh = useCallback(async () => {
    try {
      const listed = await accounts.list()
      setList(listed.accounts)
      if (!sessionId) {
        setRoute(listed.defaultRoute)
        setLast(null)
        setError(null)
        return
      }
      const current = await agents.route(sessionId)
      setRoute(current.route ?? listed.defaultRoute)
      setLast(current.last_route ?? null)
      // A later success clears an earlier failure. It never did, so one 502
      // while the server restarted stayed in the header for good.
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [sessionId])

  useEffect(() => { void refresh() }, [refresh])

  // The answering account is only known after a turn, so re-read while the
  // window is open. Cheap, and it is the one fact in this bar that changes
  // without the user touching anything.
  useEffect(() => {
    if (!sessionId) return
    const timer = setInterval(() => { void refresh() }, 15_000)
    return () => clearInterval(timer)
  }, [sessionId, refresh])

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent): void => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])

  const choose = async (account: LlmAccount, model: string): Promise<void> => {
    if (!sessionId) return
    setBusy(true)
    setError(null)
    try {
      // The chosen account leads; everything else enabled stays behind it in
      // its configured order, so switching model never costs the failover.
      const rest = list
        .filter((a) => a.enabled && a.id !== account.id)
        .map((a) => ({ accountId: a.id }))
      await agents.setRoute(sessionId, {
        primary: { accountId: account.id, ...(model ? { model } : {}) },
        fallbacks: rest,
      })
      setOpen(false)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const primaryId = route?.primary?.accountId ?? ''
  const primary = list.find((a) => a.id === primaryId) ?? null
  const pointedAt = primary
    ? `${primary.label}${route?.primary?.model ? ` · ${route.primary.model}` : ''}`
    : t('chat.route.default')
  const answered = last?.label
    ? `${last.label}${last.model ? ` · ${last.model}` : ''}`
    : ''
  const divergent = Boolean(answered && last?.accountId && last.accountId !== primaryId)

  return (
    <div className="route" ref={box}>
      <button type="button" className="route-btn" onClick={() => setOpen((v) => !v)} disabled={!sessionId}>
        <span className={`route-dot ${divergent ? 'warn' : ''}`} />
        <span className="route-label">{pointedAt}</span>
        <span className="route-caret">⌄</span>
      </button>
      {divergent && (
        <span className="route-answered" title={t('chat.route.answeredHint')}>
          {t('chat.route.answered', { label: answered })}
        </span>
      )}
      {open && (
        <div className="route-menu">
          {list.filter((a) => a.enabled).length === 0 && (
            <div className="route-empty">{t('chat.route.none')}</div>
          )}
          {list.filter((a) => a.enabled).map((account) => (
            <div key={account.id} className="route-group">
              <div className="route-group-h">
                {account.label}
                {account.identity?.email ? <span> · {account.identity.email}</span> : null}
              </div>
              {(account.modelChoices.length
                ? account.modelChoices
                : [{ id: '', label: t('chat.route.serverDefault') }]
              ).map((choice) => {
                const active = account.id === primaryId &&
                  (choice.id ? route?.primary?.model === choice.id : !route?.primary?.model)
                return (
                  <button
                    key={`${account.id}:${choice.id}`}
                    type="button"
                    className={`route-item ${active ? 'active' : ''}`}
                    disabled={busy}
                    onClick={() => void choose(account, choice.id)}
                  >
                    <span>{choice.label}</span>
                    {active && <span className="route-check">✓</span>}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
      )}
      {error && <span className="route-answered">{error}</span>}
    </div>
  )
}

export default RouteBar
