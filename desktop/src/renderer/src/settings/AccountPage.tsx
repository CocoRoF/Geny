/**
 * Account — which server this app talks to, and who it is signed in as.
 *
 * While there is no account this is the page the app opens on, so it has to
 * work on its own: the address is saved as part of signing in (signing in
 * without pressing "check" first used to leave the address unsaved, and the
 * avatar never loaded), and the connection is checked as soon as the page
 * opens instead of waiting for a button nobody knew to press.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Icon } from '../chat/icons'
import {
  Button, ConfirmButton, Field, Group, Hint, Row, Status, TextInput, type T,
} from './kit'

const TOKEN_KEY = 'geny_auth_token'

type Tone = 'ok' | 'err' | 'busy' | 'idle'

/** Who the stored token says we are — for display only; the server decides. */
function whoIs(token: string | null | undefined): { id: string; name: string } | null {
  if (!token) return null
  try {
    const part = token.split('.')[1] ?? ''
    const json = decodeURIComponent(escape(atob(part.replace(/-/g, '+').replace(/_/g, '/'))))
    const claims = JSON.parse(json) as { sub?: string; display_name?: string }
    if (!claims.sub) return null
    return { id: claims.sub, name: claims.display_name || claims.sub }
  } catch {
    return null
  }
}

function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

export function AccountPage({ t, signedIn }: { t: T; signedIn: boolean }): ReactNode {
  const [saved, setSaved] = useState('')
  const [url, setUrl] = useState('')
  const [status, setStatus] = useState<{ tone: Tone; text: string }>({ tone: 'idle', text: '' })
  const [who, setWho] = useState<{ id: string; name: string } | null>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [loginMsg, setLoginMsg] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)
  const [pwCurrent, setPwCurrent] = useState('')
  const [pwNext, setPwNext] = useState('')
  const [pwMsg, setPwMsg] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)

  const dbg = (line: string): void => window.connector?.debug?.log(line)

  /** Ask the server about us — with our token, so "signed in" means this app. */
  const probe = useCallback(async (base: string) => {
    if (!base) {
      setStatus({ tone: 'idle', text: t('set.account.noServer') })
      return
    }
    setStatus({ tone: 'busy', text: t('status.connecting') })
    try {
      const token = await window.connector?.secureStore.get(TOKEN_KEY)
      const r = await fetch(`${base}/api/auth/status`,
        token ? { headers: { Authorization: `Bearer ${token}` } } : undefined)
      const j = await r.json()
      dbg(`probe HTTP ${r.status} token=${token ? 'yes' : 'no'} authed=${String(j?.is_authenticated)}`)
      if (token && !j.is_authenticated) {
        // A dead token: drop it, so the page asks to sign in instead of
        // claiming a session the server no longer honours.
        await window.connector?.secureStore.delete(TOKEN_KEY)
        window.connector?.windowControl.refresh()
      }
      setStatus({
        tone: 'ok',
        text: j.is_authenticated ? t('status.connectedAuthed')
          : j.has_users ? t('status.connectedLoginNeeded') : t('status.connectedSetupNeeded'),
      })
    } catch (e) {
      setStatus({ tone: 'err', text: t('status.connectFailed', { msg: (e as Error).message }) })
    }
  }, [t])

  useEffect(() => {
    void (async () => {
      const config = await window.connector?.serverConfig.get()
      const base = config?.serverUrl ?? ''
      setSaved(base)
      setUrl(base)
      setWho(whoIs(await window.connector?.secureStore.get(TOKEN_KEY)))
      void probe(base)
    })()
  }, [probe])

  /** Main's canonical form of what was typed (scheme added, slashes trimmed). */
  const saveUrl = async (): Promise<string> => {
    const next = await window.connector?.serverConfig.set({ serverUrl: url })
    const base = next?.serverUrl ?? url.trim().replace(/\/+$/, '')
    setSaved(base)
    setUrl(base)
    return base
  }

  const dirty = url.trim().replace(/\/+$/, '') !== saved

  const applyUrl = async (): Promise<void> => {
    const base = await saveUrl()
    void probe(base)
  }

  /** A different server while signed in: the account belongs to the old one. */
  const switchServer = async (): Promise<void> => {
    await window.connector?.secureStore.delete(TOKEN_KEY)
    await saveUrl()
    window.connector?.windowControl.refresh()
  }

  const login = async (): Promise<void> => {
    setBusy(true)
    setLoginMsg(null)
    const base = await saveUrl()
    try {
      const r = await fetch(`${base}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!r.ok) {
        let detail = t('status.loginFailedHttp', { code: r.status })
        try {
          const body = await r.json()
          if (typeof body?.detail === 'string') detail = body.detail
        } catch { /* the status is the message */ }
        setLoginMsg({ tone: 'err', text: detail })
        return
      }
      const j = await r.json()
      const stored = await window.connector?.secureStore.set(TOKEN_KEY, j.access_token)
      if (stored === false) {
        setLoginMsg({ tone: 'err', text: t('status.keychainUnavailable') })
        return
      }
      setPassword('')
      setLoginMsg({ tone: 'ok', text: t('status.loginOk', { username: j.username }) })
      // Reloads the avatar and this window on the new account.
      window.connector?.windowControl.refresh()
    } catch (e) {
      setLoginMsg({ tone: 'err', text: t('status.loginError', { msg: (e as Error).message }) })
    } finally {
      setBusy(false)
    }
  }

  const logout = async (): Promise<void> => {
    await window.connector?.secureStore.delete(TOKEN_KEY)
    window.connector?.windowControl.refresh()
  }

  // The current password is asked even with a token in hand: the token is
  // what a thief would have. The server signs every other device out and
  // hands back a fresh token so this one keeps working.
  const changePassword = async (): Promise<void> => {
    setBusy(true)
    setPwMsg(null)
    try {
      const token = await window.connector?.secureStore.get(TOKEN_KEY)
      const r = await fetch(`${saved}/api/auth/password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ current_password: pwCurrent, new_password: pwNext }),
      })
      if (!r.ok) {
        let detail = `HTTP ${r.status}`
        try {
          const body = await r.json()
          if (typeof body?.detail === 'string') detail = body.detail
        } catch { /* the status is the message */ }
        setPwMsg({ tone: 'err', text: t('account.passwordFailed', { msg: detail }) })
        return
      }
      const j = await r.json()
      await window.connector?.secureStore.set(TOKEN_KEY, j.access_token)
      setPwCurrent('')
      setPwNext('')
      setPwMsg({ tone: 'ok', text: t('account.passwordChanged') })
    } catch (e) {
      setPwMsg({ tone: 'err', text: t('account.passwordFailed', { msg: (e as Error).message }) })
    } finally {
      setBusy(false)
    }
  }

  const host = hostOf(saved || url)

  return (
    <>
      <Group title={t('set.account.server')}>
        <Row stacked label={t('account.serverUrlLabel')} hint={t('set.account.serverHint')}>
          <div className="set-inline">
            <TextInput mono value={url} spellCheck={false} placeholder="https://geny.example.com"
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && dirty && !signedIn) void applyUrl() }} />
            {dirty && (signedIn ? (
              <ConfirmButton label={t('set.account.saveUrl')} confirmLabel={t('set.account.switchServer')}
                cancelLabel={t('set.cancel')} warning={t('set.account.switchWarn')}
                onConfirm={switchServer} />
            ) : (
              <Button variant="primary" onClick={() => void applyUrl()}>{t('set.account.saveUrl')}</Button>
            ))}
          </div>
        </Row>
        <Row label={t('set.account.connection')}
          hint={status.text ? <Status tone={status.tone}>{status.text}</Status> : undefined}>
          <Button size="sm" icon={Icon.refresh} disabled={!saved || status.tone === 'busy'}
            onClick={() => void probe(saved)}>
            {t('account.checkConnection')}
          </Button>
        </Row>
        <Row label={t('set.account.web')} hint={t('set.account.webHint')}>
          <Button size="sm" icon={Icon.openOut} disabled={!saved}
            onClick={() => window.connector?.windowControl.openExternal(saved)}>
            {t('set.open')}
          </Button>
        </Row>
      </Group>

      {signedIn ? (
        <>
          <Group title={t('set.account.account')}>
            <Row
              label={
                <span className="set-who">
                  <span className="set-who-mark">{(who?.name ?? '?').slice(0, 1).toUpperCase()}</span>
                  <span>
                    <span className="set-who-name">{who?.name ?? t('set.account.signedIn')}</span>
                    {who && who.name !== who.id && <span className="set-who-id">{who.id}</span>}
                  </span>
                </span>
              }
              hint={t('set.account.signedInHint', { host })}>
              <ConfirmButton size="sm" icon={Icon.logout} label={t('account.logout')}
                confirmLabel={t('set.account.logoutConfirm')} cancelLabel={t('set.cancel')}
                onConfirm={logout} />
            </Row>
          </Group>

          <Group title={t('account.passwordChange')} hint={t('account.passwordHint')}>
            <div className="set-form">
              <Field label={t('account.passwordCurrent')} htmlFor="set-pw-cur">
                <TextInput id="set-pw-cur" type="password" value={pwCurrent} autoComplete="current-password"
                  onChange={(e) => setPwCurrent(e.target.value)} />
              </Field>
              <Field label={t('account.passwordNew')} htmlFor="set-pw-new">
                <TextInput id="set-pw-new" type="password" value={pwNext} autoComplete="new-password"
                  onChange={(e) => setPwNext(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !busy && pwCurrent && pwNext) void changePassword() }} />
              </Field>
              <div className="set-actions">
                <Button disabled={busy || !pwCurrent || !pwNext} onClick={() => void changePassword()}>
                  {t('account.passwordChange')}
                </Button>
                {pwMsg && <Hint tone={pwMsg.tone}>{pwMsg.text}</Hint>}
              </div>
            </div>
          </Group>
        </>
      ) : (
        <Group title={t('set.account.signIn')} hint={t('set.account.signInHint')}>
          <div className="set-form">
            <Field label={t('account.idLabel')} htmlFor="set-id">
              <TextInput id="set-id" value={username} autoComplete="username"
                onChange={(e) => setUsername(e.target.value)} />
            </Field>
            <Field label={t('account.passwordLabel')} htmlFor="set-pw">
              <TextInput id="set-pw" type="password" value={password} autoComplete="current-password"
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !busy && username && password && url.trim()) void login() }} />
            </Field>
            <div className="set-actions">
              <Button variant="primary" disabled={busy || !username || !password || !url.trim()}
                onClick={() => void login()}>
                {host ? t('account.loginToHost', { host }) : t('account.login')}
              </Button>
              {loginMsg && <Hint tone={loginMsg.tone}>{loginMsg.text}</Hint>}
            </div>
          </div>
        </Group>
      )}
    </>
  )
}
