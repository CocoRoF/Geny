/**
 * Models — the server's model accounts, managed from the desktop.
 *
 * This is the better place for a subscription login than the web UI: both
 * flows end in a browser, and the browser is right here. The server streams
 * the flow out (a URL, or a device code), the app opens it in the user's real
 * browser, and the code comes back through the same stream's job.
 *
 * Every provider is listed whether or not it has an account: the two
 * subscriptions you sign into, the API keys you paste, the endpoints you host
 * yourself — each with its own add button, each taking as many accounts as
 * you want. A provider that only appeared after you had already added an
 * account to it was a provider nobody could find; that is how a server with a
 * working ChatGPT login reads as a server without one.
 *
 * The order of the accounts IS the default route — the first enabled one
 * answers, the rest are tried only when one cannot — so it is editable at the
 * top, where it can be read at a glance.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { accounts, type AccountKind, type KindInfo, type LlmAccount } from './server'

type T = (key: string, vars?: Record<string, string | number>) => string

const SUBSCRIPTION: ReadonlySet<AccountKind> = new Set<AccountKind>(['claude_code', 'codex'])

interface Family { id: string; label: string }

/**
 * A status colour is a claim. Green has to mean "this answered when we asked
 * it", not "this row exists" — a page where every account is green says
 * nothing, and says it loudly.
 */
function tone(account: LlmAccount): string {
  if (account.status?.ok === true) return 'is-ok'
  if (account.status?.ok === false) return 'is-err'
  return ''
}

interface LoginState {
  account: LlmAccount
  jobId: string | null
  url: string | null
  device: { code: string; url: string } | null
  lines: string[]
  code: string
  phase: 'starting' | 'waiting' | 'done' | 'failed'
  error: string | null
}

export function ModelsTab({ t }: { t: T }): ReactNode {
  const [list, setList] = useState<LlmAccount[]>([])
  const [kinds, setKinds] = useState<Record<string, KindInfo>>({})
  const [families, setFamilies] = useState<Family[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  /** Which provider's add form is open, if any. */
  const [adding, setAdding] = useState<AccountKind | null>(null)
  const [newLabel, setNewLabel] = useState('')
  const [newSecret, setNewSecret] = useState('')
  const [newBaseUrl, setNewBaseUrl] = useState('')
  const [login, setLogin] = useState<LoginState | null>(null)
  const stopStream = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [listed, catalogue] = await Promise.all([accounts.list(), accounts.kinds()])
      setList(listed.accounts)
      setKinds(catalogue.kinds)
      setFamilies(catalogue.families ?? [])
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => () => { stopStream.current?.() }, [])

  const run = useCallback(async (key: string, work: () => Promise<void>) => {
    setBusy(key)
    setNote(null)
    setError(null)
    try {
      await work()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }, [])

  const enabled = list.filter((a) => a.enabled)

  const move = (id: string, delta: number) => run(`move:${id}`, async () => {
    // The arrows move within the ENABLED accounts; stepping over a disabled
    // one looks like the button did nothing.
    const order = list.map((a) => a.id)
    const ids = enabled.map((a) => a.id)
    const at = ids.indexOf(id)
    const neighbour = ids[at + delta]
    if (at < 0 || !neighbour) return
    const from = order.indexOf(id)
    const to = order.indexOf(neighbour)
    order.splice(to, 0, ...order.splice(from, 1))
    const res = await accounts.reorder(order)
    setList(res.accounts)
  })

  const openAdd = (kind: AccountKind): void => {
    setAdding(kind)
    setNewLabel('')
    setNewSecret('')
    setNewBaseUrl(kinds[kind]?.defaultBaseUrl ?? '')
  }

  const add = (kind: AccountKind) => run('add', async () => {
    const created = await accounts.create({
      kind,
      ...(newLabel ? { label: newLabel } : {}),
      ...(newSecret ? { secret: newSecret } : {}),
      ...(newBaseUrl ? { baseUrl: newBaseUrl } : {}),
    })
    setAdding(null)
    setNewLabel('')
    setNewSecret('')
    setNewBaseUrl('')
    await refresh()
    // A subscription account does nothing until it is signed in, and the
    // sign-in is the part people cannot find. Go straight there.
    if (SUBSCRIPTION.has(kind) && created.account) void startLogin(created.account)
  })

  const remove = (account: LlmAccount) => run(`remove:${account.id}`, async () => {
    if (!window.confirm(t('models.removeConfirm', { label: account.label }))) return
    await accounts.remove(account.id)
    await refresh()
  })

  const toggle = (account: LlmAccount) => run(`toggle:${account.id}`, async () => {
    await accounts.update(account.id, { enabled: !account.enabled })
    await refresh()
  })

  const test = (account: LlmAccount) => run(`test:${account.id}`, async () => {
    const result = await accounts.test(account.id)
    setNote(result.ok
      ? t('models.testOk', { label: account.label, ms: result.latencyMs })
      : t('models.testFail', { label: account.label, error: result.error ?? '' }))
    await refresh()
  })

  const startLogin = (account: LlmAccount) => run(`login:${account.id}`, async () => {
    stopStream.current?.()
    setLogin({
      account, jobId: null, url: null, device: null,
      lines: [], code: '', phase: 'starting', error: null,
    })

    const follow = (jobId: string): void => {
      stopStream.current = accounts.events(jobId, (event) => {
        const type = String(event.type ?? '')
        setLogin((prev) => {
          if (!prev) return prev
          if (type === 'line') {
            return { ...prev, lines: [...prev.lines.slice(-200), String(event.text ?? '')] }
          }
          if (type === 'url') {
            const url = String(event.url ?? '')
            // The browser that can finish this is the user's, and it is right
            // here — so open it rather than printing a link to copy.
            if (!prev.url) window.connector?.windowControl.openExternal(url)
            return { ...prev, url: prev.url ?? url, phase: 'waiting' }
          }
          if (type === 'device') {
            const url = String(event.verificationUrl ?? '')
            if (!prev.device) window.connector?.windowControl.openExternal(url)
            return {
              ...prev, phase: 'waiting',
              device: { code: String(event.userCode ?? ''), url },
            }
          }
          if (type === 'done') {
            void refresh()
            return {
              ...prev,
              phase: event.ok ? 'done' : 'failed',
              error: event.ok ? null : String(event.error ?? ''),
            }
          }
          return prev
        })
      })
    }

    if (account.kind === 'codex') {
      const started = await accounts.codexLogin(account.id)
      window.connector?.windowControl.openExternal(started.verificationUrl)
      setLogin((prev) => prev && {
        ...prev, jobId: started.jobId, phase: 'waiting',
        device: { code: started.userCode, url: started.verificationUrl },
      })
      follow(started.jobId)
      return
    }
    const started = await accounts.claudeLogin(account.id)
    setLogin((prev) => prev && { ...prev, jobId: started.jobId, phase: 'waiting' })
    follow(started.jobId)
  })

  const submitCode = () => run('code', async () => {
    if (!login?.jobId || !login.code.trim()) return
    await accounts.sendLoginInput(login.jobId, login.code.trim())
    setLogin((prev) => prev && { ...prev, code: '' })
  })

  const closeLogin = (): void => {
    stopStream.current?.()
    stopStream.current = null
    if (login?.jobId && login.phase === 'waiting') void accounts.cancelLogin(login.jobId).catch(() => undefined)
    setLogin(null)
    void refresh()
  }

  const kindsIn = (family: string): [AccountKind, KindInfo][] =>
    Object.entries(kinds).filter(([, info]) => info.family === family) as [AccountKind, KindInfo][]

  return (
    <>
      <section className="gy-card">
        <div className="gy-card-h">{t('models.title')}</div>
        <p className="gy-hint">{t('models.hint')}</p>
        {error && <p className="gy-hint" style={{ color: 'var(--gy-err)' }}>{error}</p>}
        {note && <p className="gy-hint">{note}</p>}
      </section>

      {/* the route, as an order */}
      <section className="gy-card">
        <div className="gy-card-h">{t('models.order')}</div>
        <p className="gy-hint">{t('models.orderHint')}</p>
        {enabled.length === 0 ? (
          <p className="gy-hint">{t('models.orderEmpty')}</p>
        ) : (
          enabled.map((account, index) => (
            <div className="gy-row" key={account.id}>
              <span className={`gy-pill grow ${tone(account)}`}>
                <span className="gy-dot" />
                <span className="gy-msg">
                  {index + 1}. {account.label}
                  {account.identity?.email ? ` · ${account.identity.email}` : ''}
                </span>
              </span>
              <button className="gy-btn gy-btn--ghost gy-btn--sm" disabled={index === 0 || !!busy}
                onClick={() => void move(account.id, -1)}>↑</button>
              <button className="gy-btn gy-btn--ghost gy-btn--sm"
                disabled={index === enabled.length - 1 || !!busy}
                onClick={() => void move(account.id, 1)}>↓</button>
            </div>
          ))
        )}
      </section>

      {families.map((family) => (
        <div key={family.id}>
          <div className="gy-family">{family.label}</div>
          {kindsIn(family.id).map(([kind, info]) => {
            const mine = list.filter((a) => a.kind === kind)
            return (
              <section className="gy-card" key={kind}>
                <div className="gy-card-title">
                  <span>{info.label}</span>
                  {mine.length > 0 && (
                    <span className="gy-card-note">
                      {t('models.accountCount', { n: mine.length })}
                    </span>
                  )}
                </div>
                {info.hint && <p className="gy-hint">{info.hint}</p>}

                {mine.map((account) => (
                  <div key={account.id}>
                    <div className="gy-spacer" />
                    <div className="gy-row">
                      <span className={`gy-pill grow ${account.enabled ? tone(account) : ''}`}>
                        <span className="gy-dot" />
                        <span className="gy-msg">
                          {account.label}
                          {account.identity?.email ? ` · ${account.identity.email}` : ''}
                          {!account.enabled ? ` · ${t('models.off')}` : ''}
                        </span>
                      </span>
                    </div>
                    <div className="gy-spacer" />
                    <div className="gy-row">
                      <button className="gy-btn gy-btn--ghost gy-btn--sm" disabled={!!busy}
                        onClick={() => void toggle(account)}>
                        {account.enabled ? t('models.turnOff') : t('models.turnOn')}
                      </button>
                      <button className="gy-btn gy-btn--ghost gy-btn--sm" disabled={!!busy}
                        onClick={() => void test(account)}>
                        {busy === `test:${account.id}` ? t('models.testing') : t('models.test')}
                      </button>
                      {SUBSCRIPTION.has(account.kind) && (
                        <button className="gy-btn gy-btn--primary gy-btn--sm" disabled={!!busy}
                          onClick={() => void startLogin(account)}>
                          {t('models.signIn')}
                        </button>
                      )}
                      <button className="gy-btn gy-btn--danger gy-btn--sm" disabled={!!busy}
                        onClick={() => void remove(account)}>
                        {t('models.remove')}
                      </button>
                    </div>
                  </div>
                ))}

                <div className="gy-spacer" />
                {adding === kind ? (
                  <>
                    <label className="gy-field-label" htmlFor={`gy-label-${kind}`}>{t('models.label')}</label>
                    <input id={`gy-label-${kind}`} className="gy-input" value={newLabel}
                      placeholder={info.short}
                      onChange={(e) => setNewLabel(e.target.value)} />
                    {(info.secret === 'api_key' || info.secret === 'optional_key') && (
                      <>
                        <div className="gy-spacer" />
                        <label className="gy-field-label" htmlFor={`gy-secret-${kind}`}>{t('models.apiKey')}</label>
                        <input id={`gy-secret-${kind}`} className="gy-input mono" type="password" value={newSecret}
                          onChange={(e) => setNewSecret(e.target.value)} />
                      </>
                    )}
                    {(info.needsBaseUrl || info.defaultBaseUrl) && (
                      <>
                        <div className="gy-spacer" />
                        <label className="gy-field-label" htmlFor={`gy-base-${kind}`}>{t('models.address')}</label>
                        <input id={`gy-base-${kind}`} className="gy-input mono" value={newBaseUrl}
                          placeholder={info.defaultBaseUrl}
                          onChange={(e) => setNewBaseUrl(e.target.value)} />
                      </>
                    )}
                    <div className="gy-spacer" />
                    <div className="gy-row">
                      <button className="gy-btn gy-btn--primary gy-btn--sm" disabled={!!busy}
                        onClick={() => void add(kind)}>
                        {SUBSCRIPTION.has(kind) ? t('models.addAndSignIn') : t('models.save')}
                      </button>
                      <button className="gy-btn gy-btn--ghost gy-btn--sm" onClick={() => setAdding(null)}>
                        {t('models.cancel')}
                      </button>
                    </div>
                  </>
                ) : (
                  <button className="gy-btn gy-btn--ghost gy-btn--block gy-btn--sm"
                    onClick={() => openAdd(kind)}>
                    {SUBSCRIPTION.has(kind) ? t('models.addLogin') : t('models.addKey')}
                  </button>
                )}
              </section>
            )
          })}
        </div>
      ))}

      {login && (
        <section className="gy-card">
          <div className="gy-card-h">{t('models.login.title', { label: login.account.label })}</div>
          {login.device ? (
            <>
              <p className="gy-hint">{t('models.login.deviceCode')}</p>
              <div className="gy-input mono" style={{ letterSpacing: '0.2em', textAlign: 'center' }}>
                {login.device.code}
              </div>
              <div className="gy-spacer" />
              <button className="gy-btn gy-btn--ghost gy-btn--block gy-btn--sm"
                onClick={() => window.connector?.windowControl.openExternal(login.device!.url)}>
                {t('models.login.openAgain')}
              </button>
            </>
          ) : login.url ? (
            <>
              <p className="gy-hint">{t('models.login.browserOpened')}</p>
              <button className="gy-btn gy-btn--ghost gy-btn--block gy-btn--sm"
                onClick={() => window.connector?.windowControl.openExternal(login.url!)}>
                {t('models.login.openAgain')}
              </button>
            </>
          ) : (
            <p className="gy-hint">{t('models.login.waiting')}</p>
          )}

          {login.account.kind !== 'codex' && login.phase === 'waiting' && (
            <>
              <div className="gy-spacer" />
              <label className="gy-field-label" htmlFor="gy-code">{t('models.login.pasteCode')}</label>
              <div className="gy-row">
                <input id="gy-code" className="gy-input mono grow" value={login.code}
                  onChange={(e) => setLogin((prev) => prev && { ...prev, code: e.target.value })}
                  onKeyDown={(e) => { if (e.key === 'Enter') void submitCode() }} />
                <button className="gy-btn gy-btn--primary gy-btn--sm"
                  disabled={!login.code.trim() || !!busy} onClick={() => void submitCode()}>
                  {t('models.login.submit')}
                </button>
              </div>
            </>
          )}

          {login.lines.length > 0 && (
            <>
              <div className="gy-spacer" />
              <pre className="gy-input mono" style={{ maxHeight: 160, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                {login.lines.join('\n')}
              </pre>
            </>
          )}

          {login.phase === 'done' && <p className="gy-hint">{t('models.login.done')}</p>}
          {login.phase === 'failed' && (
            <p className="gy-hint">{t('models.login.failed', { error: login.error ?? '' })}</p>
          )}

          <div className="gy-spacer" />
          <button className="gy-btn gy-btn--ghost gy-btn--block gy-btn--sm" onClick={closeLogin}>
            {login.phase === 'waiting' ? t('models.login.cancel') : t('models.login.close')}
          </button>
        </section>
      )}
    </>
  )
}

export default ModelsTab
