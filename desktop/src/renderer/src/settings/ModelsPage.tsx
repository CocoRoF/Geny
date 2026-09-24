/**
 * Models — the server's model accounts, managed from the desktop.
 *
 * This is the better place for a subscription sign-in than the web page:
 * both flows end in a browser, and the browser is right here. The server
 * streams the flow (a URL, or a device code), the app opens it in the real
 * browser, and the code comes back through the same stream's job.
 *
 * Every provider is listed whether or not it has an account yet — a
 * provider that only appeared once it had one was a provider nobody could
 * find. The order of the enabled accounts IS the default route: the first
 * answers, the rest are tried only when one cannot.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { Icon } from '../chat/icons'
import { accounts, type AccountKind, type KindInfo, type LlmAccount } from '../server'
import {
  Button, Card, ConfirmButton, Empty, Field, Group, Hint, Status, Switch, TextInput, type T,
} from './kit'

const SUBSCRIPTION: ReadonlySet<AccountKind> = new Set<AccountKind>(['claude_code', 'codex'])

interface Family { id: string; label: string }

/** Green means it answered when asked, not that the row exists. */
function toneOf(account: LlmAccount): 'ok' | 'err' | 'idle' {
  if (!account.enabled) return 'idle'
  if (account.status?.ok === true) return 'ok'
  if (account.status?.ok === false) return 'err'
  return 'idle'
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

export function ModelsPage({ t }: { t: T }): ReactNode {
  const [list, setList] = useState<LlmAccount[]>([])
  const [kinds, setKinds] = useState<Record<string, KindInfo>>({})
  const [families, setFamilies] = useState<Family[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  /** A test result, beside the account it was about. */
  const [notes, setNotes] = useState<Record<string, { tone: 'ok' | 'err'; text: string }>>({})
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
    } finally {
      setLoaded(true)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => () => { stopStream.current?.() }, [])

  const run = useCallback(async (key: string, work: () => Promise<void>) => {
    setBusy(key)
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
    await refresh()
    if (SUBSCRIPTION.has(kind) && created.account) void startLogin(created.account)
  })

  const remove = (account: LlmAccount) => run(`remove:${account.id}`, async () => {
    await accounts.remove(account.id)
    await refresh()
  })

  const toggle = (account: LlmAccount) => run(`toggle:${account.id}`, async () => {
    await accounts.update(account.id, { enabled: !account.enabled })
    await refresh()
  })

  const test = (account: LlmAccount) => run(`test:${account.id}`, async () => {
    const result = await accounts.test(account.id)
    setNotes((prev) => ({
      ...prev,
      [account.id]: result.ok
        ? { tone: 'ok', text: t('set.models.testOk', { ms: result.latencyMs ?? 0 }) }
        : { tone: 'err', text: result.error || t('set.models.testFail') },
    }))
    await refresh()
  })

  const startLogin = (account: LlmAccount) => run(`login:${account.id}`, async () => {
    stopStream.current?.()
    setLogin({ account, jobId: null, url: null, device: null, lines: [], code: '', phase: 'starting', error: null })

    const follow = (jobId: string): void => {
      stopStream.current = accounts.events(jobId, (event) => {
        const type = String(event.type ?? '')
        setLogin((prev) => {
          if (!prev) return prev
          if (type === 'line') return { ...prev, lines: [...prev.lines.slice(-200), String(event.text ?? '')] }
          if (type === 'url') {
            const url = String(event.url ?? '')
            if (!prev.url) window.connector?.windowControl.openExternal(url)
            return { ...prev, url: prev.url ?? url, phase: 'waiting' }
          }
          if (type === 'device') {
            const url = String(event.verificationUrl ?? '')
            if (!prev.device) window.connector?.windowControl.openExternal(url)
            return { ...prev, phase: 'waiting', device: { code: String(event.userCode ?? ''), url } }
          }
          if (type === 'done') {
            void refresh()
            return { ...prev, phase: event.ok ? 'done' : 'failed', error: event.ok ? null : String(event.error ?? '') }
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

  const loginPanel = (l: LoginState): ReactNode => (
    <div className="set-login">
      <div className="set-login-title">{t('models.login.title', { label: l.account.label })}</div>
      {l.device ? (
        <>
          <p className="set-login-text">{t('models.login.deviceCode')}</p>
          <div className="set-login-code">{l.device.code}</div>
          <Button size="sm" icon={Icon.openOut}
            onClick={() => window.connector?.windowControl.openExternal(l.device!.url)}>
            {t('models.login.openAgain')}
          </Button>
        </>
      ) : l.url ? (
        <>
          <p className="set-login-text">{t('models.login.browserOpened')}</p>
          <Button size="sm" icon={Icon.openOut}
            onClick={() => window.connector?.windowControl.openExternal(l.url!)}>
            {t('models.login.openAgain')}
          </Button>
        </>
      ) : (
        <p className="set-login-text">{t('models.login.waiting')}</p>
      )}
      {l.account.kind !== 'codex' && l.phase === 'waiting' && (
        <Field label={t('models.login.pasteCode')} htmlFor="set-login-code">
          <div className="set-inline">
            <TextInput id="set-login-code" mono value={l.code}
              onChange={(e) => setLogin((prev) => prev && { ...prev, code: e.target.value })}
              onKeyDown={(e) => { if (e.key === 'Enter') void submitCode() }} />
            <Button variant="primary" disabled={!l.code.trim() || !!busy} onClick={() => void submitCode()}>
              {t('models.login.submit')}
            </Button>
          </div>
        </Field>
      )}
      {l.lines.length > 0 && <pre className="set-log small">{l.lines.join('\n')}</pre>}
      {l.phase === 'done' && <Hint tone="ok">{t('models.login.done')}</Hint>}
      {l.phase === 'failed' && <Hint tone="err">{t('models.login.failed', { error: l.error ?? '' })}</Hint>}
      <div className="set-actions">
        <Button size="sm" variant="ghost" onClick={closeLogin}>
          {l.phase === 'waiting' ? t('models.login.cancel') : t('models.login.close')}
        </Button>
      </div>
    </div>
  )

  if (!loaded) return <Empty>{t('set.loading')}</Empty>

  return (
    <>
      {error && <Hint tone="err">{error}</Hint>}

      <Group title={t('models.order')} hint={t('models.orderHint')}>
        {enabled.length === 0 ? (
          <div className="set-row"><div className="set-row-text">
            <div className="set-row-hint">{t('models.orderEmpty')}</div>
          </div></div>
        ) : enabled.map((account, index) => (
          <div className="set-row" key={account.id}>
            <div className="set-order">
              <span className="set-order-n">{index + 1}</span>
              <Status tone={toneOf(account)}>
                {account.label}
                {account.identity?.email && <span className="set-muted"> · {account.identity.email}</span>}
              </Status>
            </div>
            <div className="set-row-control">
              <Button size="sm" variant="ghost" icon={Icon.arrowUp} aria-label={t('set.models.up')}
                disabled={index === 0 || !!busy} onClick={() => void move(account.id, -1)} />
              <Button size="sm" variant="ghost" icon={Icon.arrowDown} aria-label={t('set.models.down')}
                disabled={index === enabled.length - 1 || !!busy} onClick={() => void move(account.id, 1)} />
            </div>
          </div>
        ))}
      </Group>

      {families.map((family) => (
        <Group key={family.id} title={family.label} plain>
          {kindsIn(family.id).map(([kind, info]) => {
            const mine = list.filter((a) => a.kind === kind)
            const sub = SUBSCRIPTION.has(kind)
            return (
              <Card key={kind} icon={sub ? Icon.user : Icon.key} title={
                <span className="set-card-title-row">
                  {info.label}
                  {mine.length > 0 && <span className="set-badge">{t('models.accountCount', { n: mine.length })}</span>}
                </span>
              } desc={info.hint}
                control={adding === kind ? undefined : (
                  <Button size="sm" icon={Icon.plus} onClick={() => openAdd(kind)}>
                    {sub ? t('set.models.addLogin') : t('set.models.add')}
                  </Button>
                )}>
                {(mine.length > 0 || adding === kind || login?.account.kind === kind) && (
                  <>
                    {mine.map((account) => (
                      <div key={account.id} className="set-acct">
                        <div className="set-acct-main">
                          <Status tone={toneOf(account)}>
                            {account.label}
                            {account.identity?.email && <span className="set-muted"> · {account.identity.email}</span>}
                            {!account.enabled && <span className="set-muted"> · {t('models.off')}</span>}
                          </Status>
                          {notes[account.id] && (
                            <span className={`set-inline-note ${notes[account.id].tone}`}>{notes[account.id].text}</span>
                          )}
                        </div>
                        <div className="set-acct-actions">
                          <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => void test(account)}>
                            {busy === `test:${account.id}` ? t('models.testing') : t('models.test')}
                          </Button>
                          {sub && (
                            <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => void startLogin(account)}>
                              {t('models.signIn')}
                            </Button>
                          )}
                          <ConfirmButton size="sm" icon={Icon.trash} label={t('models.remove')}
                            confirmLabel={t('set.models.removeConfirm')} cancelLabel={t('set.cancel')}
                            disabled={!!busy} onConfirm={() => remove(account)} />
                          <Switch checked={account.enabled} disabled={!!busy} label={t('set.models.enabled')}
                            onChange={() => void toggle(account)} />
                        </div>
                      </div>
                    ))}
                    {login && login.account.kind === kind && loginPanel(login)}
                    {adding === kind && (
                      <div className="set-form tight">
                        <Field label={t('models.label')} htmlFor={`set-label-${kind}`}>
                          <TextInput id={`set-label-${kind}`} value={newLabel} placeholder={info.short}
                            onChange={(e) => setNewLabel(e.target.value)} />
                        </Field>
                        {(info.secret === 'api_key' || info.secret === 'optional_key') && (
                          <Field label={t('models.apiKey')} htmlFor={`set-secret-${kind}`}>
                            <TextInput id={`set-secret-${kind}`} mono type="password" value={newSecret}
                              onChange={(e) => setNewSecret(e.target.value)} />
                          </Field>
                        )}
                        {(info.needsBaseUrl || info.defaultBaseUrl) && (
                          <Field label={t('models.address')} htmlFor={`set-base-${kind}`}>
                            <TextInput id={`set-base-${kind}`} mono value={newBaseUrl} placeholder={info.defaultBaseUrl}
                              onChange={(e) => setNewBaseUrl(e.target.value)} />
                          </Field>
                        )}
                        <div className="set-actions">
                          <Button variant="primary" disabled={!!busy} onClick={() => void add(kind)}>
                            {sub ? t('models.addAndSignIn') : t('models.save')}
                          </Button>
                          <Button variant="ghost" onClick={() => setAdding(null)}>{t('set.cancel')}</Button>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </Card>
            )
          })}
        </Group>
      ))}
    </>
  )
}
