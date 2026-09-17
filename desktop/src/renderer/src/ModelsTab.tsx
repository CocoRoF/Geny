/**
 * Models — the server's model accounts, managed from the desktop.
 *
 * This is the better place for a subscription login than the web UI: both
 * flows end in a browser, and the browser is right here. The server streams
 * the flow out (a URL, or a device code), the app opens it in the user's real
 * browser, and the code comes back through the same stream's job.
 *
 * The list IS the default route — first enabled account answers, the rest are
 * tried only when one cannot — so order is editable in place.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { accounts, type AccountKind, type KindInfo, type LlmAccount } from './server'

type T = (key: string, vars?: Record<string, string | number>) => string

const SUBSCRIPTION: ReadonlySet<AccountKind> = new Set<AccountKind>(['claude_code', 'codex'])

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
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [newKind, setNewKind] = useState<AccountKind>('claude_code')
  const [newSecret, setNewSecret] = useState('')
  const [newBaseUrl, setNewBaseUrl] = useState('')
  const [login, setLogin] = useState<LoginState | null>(null)
  const stopStream = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [listed, catalogue] = await Promise.all([accounts.list(), accounts.kinds()])
      setList(listed.accounts)
      setKinds(catalogue.kinds)
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

  const move = (id: string, delta: number) => run(`move:${id}`, async () => {
    const order = list.map((a) => a.id)
    const from = order.indexOf(id)
    const to = from + delta
    if (from < 0 || to < 0 || to >= order.length) return
    order.splice(to, 0, ...order.splice(from, 1))
    const res = await accounts.reorder(order)
    setList(res.accounts)
  })

  const add = () => run('add', async () => {
    await accounts.create({
      kind: newKind,
      ...(newSecret ? { secret: newSecret } : {}),
      ...(newBaseUrl ? { baseUrl: newBaseUrl } : {}),
    })
    setNewSecret('')
    setNewBaseUrl('')
    setAdding(false)
    await refresh()
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

  const closeLogin = () => {
    stopStream.current?.()
    stopStream.current = null
    if (login?.jobId && login.phase === 'waiting') void accounts.cancelLogin(login.jobId).catch(() => undefined)
    setLogin(null)
    void refresh()
  }

  return (
    <>
      <section className="gy-card">
        <div className="gy-card-h">{t('models.title')}</div>
        <p className="gy-hint">{t('models.hint')}</p>
        {error && <p className="gy-hint" style={{ color: 'var(--gy-err, #f87171)' }}>{error}</p>}
        {note && <p className="gy-hint">{note}</p>}
      </section>

      {list.length === 0 ? (
        <section className="gy-card">
          <p className="gy-hint">{t('models.empty')}</p>
        </section>
      ) : (
        list.map((account, index) => (
          <section className="gy-card" key={account.id}>
            <div className="gy-card-h">
              {account.label}
              <span className="gy-hint" style={{ marginLeft: 8 }}>
                {kinds[account.kind]?.short ?? account.kind}
              </span>
            </div>
            <div className="gy-row">
              <span className={`gy-pill grow ${account.enabled ? (account.status?.ok === false ? 'is-err' : 'is-ok') : ''}`}>
                <span className="gy-dot" />
                <span className="gy-msg">
                  {!account.enabled
                    ? t('models.off')
                    : index === 0
                      ? t('models.answersFirst')
                      : t('models.fallback', { index })}
                  {account.identity?.email ? ` · ${account.identity.email}` : ''}
                </span>
              </span>
              <button className="gy-btn gy-btn--ghost gy-btn--sm" disabled={index === 0 || !!busy}
                onClick={() => void move(account.id, -1)}>↑</button>
              <button className="gy-btn gy-btn--ghost gy-btn--sm" disabled={index === list.length - 1 || !!busy}
                onClick={() => void move(account.id, 1)}>↓</button>
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
          </section>
        ))
      )}

      <section className="gy-card">
        {adding ? (
          <>
            <div className="gy-card-h">{t('models.addTitle')}</div>
            <label className="gy-field-label" htmlFor="gy-kind">{t('models.kind')}</label>
            <select id="gy-kind" className="gy-input" value={newKind}
              onChange={(e) => setNewKind(e.target.value as AccountKind)}>
              {Object.entries(kinds).map(([id, info]) => (
                <option key={id} value={id}>{info.label}</option>
              ))}
            </select>
            {kinds[newKind]?.hint && <p className="gy-hint">{kinds[newKind].hint}</p>}
            {(kinds[newKind]?.secret === 'api_key' || kinds[newKind]?.secret === 'optional_key') && (
              <>
                <div className="gy-spacer" />
                <label className="gy-field-label" htmlFor="gy-secret">{t('models.apiKey')}</label>
                <input id="gy-secret" className="gy-input mono" type="password" value={newSecret}
                  onChange={(e) => setNewSecret(e.target.value)} />
              </>
            )}
            {(kinds[newKind]?.needsBaseUrl || kinds[newKind]?.defaultBaseUrl) && (
              <>
                <div className="gy-spacer" />
                <label className="gy-field-label" htmlFor="gy-base">{t('models.address')}</label>
                <input id="gy-base" className="gy-input mono" value={newBaseUrl}
                  placeholder={kinds[newKind]?.defaultBaseUrl}
                  onChange={(e) => setNewBaseUrl(e.target.value)} />
              </>
            )}
            <div className="gy-spacer" />
            <div className="gy-row">
              <button className="gy-btn gy-btn--primary gy-btn--sm" disabled={!!busy} onClick={() => void add()}>
                {t('models.save')}
              </button>
              <button className="gy-btn gy-btn--ghost gy-btn--sm" onClick={() => setAdding(false)}>
                {t('models.cancel')}
              </button>
            </div>
          </>
        ) : (
          <button className="gy-btn gy-btn--ghost gy-btn--block gy-btn--sm" onClick={() => setAdding(true)}>
            {t('models.add')}
          </button>
        )}
      </section>

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
