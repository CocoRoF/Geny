/**
 * The connector's main window: a session, and the work in it.
 *
 * This replaced a browser frame. The control window used to load the server's
 * `/connector` page — a web app, in a window, pretending to be an app — and
 * every question a user has here ("which model answered", "what did it just
 * run", "what did it change on disk") was an answer that page did not have
 * room for.
 *
 * The layout is the one that fits an agent: sessions on the left because a
 * session is a place you go back to; the conversation in the middle with the
 * tool calls in the flow rather than hidden behind a tab; and the record of
 * what actually happened on the right, one keystroke away, because with an
 * agent working in your files that is the question that matters.
 *
 * Nothing here decides what the agent does. It is the server's session, the
 * server's route, the server's log — this window is where you can see them.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

import { makeT, type Lang } from '../i18n'
import {
  agents, environments, sessions as sessionApi,
  type AgentSummary, type EnvironmentSummary,
} from '../server'
import ActivityPanel from './ActivityPanel'
import RouteBar from './RouteBar'
import Transcript from './Transcript'
import { useSession } from './useSession'

const LAST_SESSION_KEY = 'geny.chat.lastSession'

function StateLamp({ state, running, t }: {
  state: string; running: boolean
  t: (k: string, v?: Record<string, string | number>) => string
}): ReactNode {
  // A dropped socket is not a dropped turn: the server keeps working whether
  // or not this window is listening. Saying "disconnected" over a turn that
  // is still running teaches the user to distrust a screen that was right.
  const tone =
    state === 'connected' ? 'is-ok'
    : state === 'unauthorized' ? 'is-err'
    : state === 'offline' ? 'is-err'
    : 'is-warn'
  const label =
    state === 'connected' ? (running ? t('chat.state.working') : t('chat.state.ready'))
    : state === 'unauthorized' ? t('chat.state.signedOut')
    : state === 'offline' ? t('chat.state.offline')
    : t('chat.state.reconnecting')
  return (
    <span className={`gy-lamp ${tone}`}>
      <span className="gy-lamp-dot" />
      {label}
    </span>
  )
}

export function ChatApp(): ReactNode {
  const [lang, setLang] = useState<Lang>('ko')
  const [light, setLight] = useState(false)
  const t = useMemo(() => makeT(lang), [lang])

  const [list, setList] = useState<AgentSummary[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [envs, setEnvs] = useState<EnvironmentSummary[]>([])
  const [showActivity, setShowActivity] = useState(false)
  const [draft, setDraft] = useState('')
  const scroller = useRef<HTMLDivElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)
  const pinned = useRef(true)

  const live = useSession(sessionId)

  // ── theme + language, from the connector's own config ───────────────
  useEffect(() => {
    void (async () => {
      const config = await window.connector?.serverConfig.get()
      const mode = config?.theme ?? 'system'
      const sysDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      setLight(mode === 'light' || (mode === 'system' && !sysDark))
      const fallback = (await window.connector?.appDefaultLang?.().catch(() => 'ko' as Lang)) ?? 'ko'
      setLang((config?.lang as Lang) ?? fallback)
    })()
    const off = window.connector?.serverConfig.onChange((config) => {
      const mode = config?.theme ?? 'system'
      const sysDark = window.matchMedia('(prefers-color-scheme: dark)').matches
      setLight(mode === 'light' || (mode === 'system' && !sysDark))
      if (config?.lang) setLang(config.lang)
    })
    return () => { off?.() }
  }, [])

  // ── the session list ────────────────────────────────────────────────
  const refreshList = useCallback(async () => {
    try {
      const listed = await agents.list()
      setList(listed)
      setListError(null)
      setSessionId((current) => {
        if (current && listed.some((s) => s.session_id === current)) return current
        const remembered = window.localStorage.getItem(LAST_SESSION_KEY)
        if (remembered && listed.some((s) => s.session_id === remembered)) return remembered
        return listed[0]?.session_id ?? null
      })
    } catch (e) {
      setListError((e as Error).message)
    }
  }, [])

  useEffect(() => { void refreshList() }, [refreshList])
  useEffect(() => {
    const timer = setInterval(() => { void refreshList() }, 20_000)
    return () => clearInterval(timer)
  }, [refreshList])

  useEffect(() => {
    if (!sessionId) return
    window.localStorage.setItem(LAST_SESSION_KEY, sessionId)
    // Opening a session means wanting to type in it.
    composer.current?.focus()
  }, [sessionId])

  // ── the quick-chat bar delivers here ────────────────────────────────
  // It used to relay into the web page's send box. Now it lands in the same
  // place a typed message does, so a hotkey message and a typed one are the
  // same event and cannot behave differently.
  const sendLive = live.send
  useEffect(() => {
    const off = window.connector?.messaging.onQuickSend((payload) => {
      const text = (typeof payload === 'string' ? payload : payload?.text ?? '').trim()
      if (text) sendLive(text)
    })
    return () => { off?.() }
    // `live` itself is a fresh object every render; depending on it would
    // resubscribe on every keystroke.
  }, [sendLive])

  // ── scrolling ───────────────────────────────────────────────────────
  // Follow the answer, unless the user scrolled up to read something. Yanking
  // someone back to the bottom mid-sentence is worse than a stale view.
  useEffect(() => {
    if (!pinned.current) return
    const el = scroller.current
    if (el) el.scrollTop = el.scrollHeight
  }, [live.messages, live.running])

  const onScroll = (): void => {
    const el = scroller.current
    if (!el) return
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  const send = (): void => {
    const text = draft.trim()
    if (!text || !sessionId) return
    live.send(text)
    setDraft('')
    // The box grew to fit what was typed; clearing the value does not shrink
    // it back, so a long message leaves a tall empty box behind.
    if (composer.current) composer.current.style.height = 'auto'
    composer.current?.focus()
    pinned.current = true
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      send()
    }
    if (e.key === 'Escape' && live.running) {
      e.preventDefault()
      live.stop()
    }
  }

  const startSession = async (envId: string): Promise<void> => {
    try {
      const created = await sessionApi.create({
        session_name: t('chat.newSessionName', { n: list.length + 1 }),
        ...(envId ? { env_id: envId } : {}),
      })
      setCreating(false)
      await refreshList()
      setSessionId(created.session_id)
    } catch (e) {
      setListError((e as Error).message)
    }
  }

  const openCreate = async (): Promise<void> => {
    setCreating(true)
    try {
      const listed = await environments.list()
      setEnvs(listed.environments ?? [])
    } catch {
      setEnvs([])
    }
  }

  const current = list.find((s) => s.session_id === sessionId) ?? null

  return (
    <div className={`gy gy-chat ${light ? 'gy--light' : ''}`}>
      <aside className="gy-rail">
        <div className="gy-rail-h">
          <span>{t('chat.sessions')}</span>
          <button type="button" className="gy-rail-new" title={t('chat.newSession')}
            onClick={() => void openCreate()}>+</button>
        </div>
        {listError && <div className="gy-rail-err">{listError}</div>}
        <div className="gy-rail-list">
          {list.map((session) => (
            <button
              key={session.session_id}
              type="button"
              className={`gy-rail-item ${session.session_id === sessionId ? 'is-active' : ''}`}
              onClick={() => setSessionId(session.session_id)}
            >
              <span className={`gy-rail-dot ${session.status === 'running' ? 'is-run' : ''}`} />
              <span className="gy-rail-name">
                {session.session_name || session.session_id.slice(0, 8)}
              </span>
              {session.env_name && <span className="gy-rail-env">{session.env_name}</span>}
            </button>
          ))}
          {list.length === 0 && !listError && (
            <div className="gy-rail-empty">{t('chat.noSessions')}</div>
          )}
        </div>
        <button type="button" className="gy-rail-foot" onClick={() => window.connector?.windowControl.openSettings()}>
          {t('chat.openSettings')}
        </button>
      </aside>

      <main className="gy-main">
        <header className="gy-chat-head">
          <div className="gy-chat-title">
            {current?.session_name || t('chat.untitled')}
            {current?.env_name && <span className="gy-chat-env">{current.env_name}</span>}
          </div>
          <RouteBar sessionId={sessionId} t={t} />
          <StateLamp state={live.state} running={live.running} t={t} />
          <button
            type="button"
            className={`gy-chat-toggle ${showActivity ? 'is-active' : ''}`}
            onClick={() => setShowActivity((v) => !v)}
          >
            {t('chat.activity')}
          </button>
        </header>

        {live.error && (
          <div className="gy-chat-error" onClick={live.clearError} role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter') live.clearError() }}>
            {live.error}
          </div>
        )}

        <div className="gy-chat-body">
          <div className="gy-chat-scroll" ref={scroller} onScroll={onScroll}>
            <div className="gy-chat-thread">
              <Transcript messages={live.messages} running={live.running} loading={live.loading} t={t} />
            </div>
          </div>
          {showActivity && sessionId && <ActivityPanel sessionId={sessionId} t={t} />}
        </div>

        <footer className="gy-composer">
          <textarea
            ref={composer}
            className="gy-composer-input"
            value={draft}
            placeholder={sessionId ? t('chat.placeholder') : t('chat.placeholderNoSession')}
            disabled={!sessionId}
            rows={1}
            onChange={(e) => {
              setDraft(e.target.value)
              const el = e.target
              el.style.height = 'auto'
              el.style.height = `${Math.min(220, el.scrollHeight)}px`
            }}
            onKeyDown={onKey}
          />
          {live.running ? (
            <button type="button" className="gy-composer-btn is-stop" onClick={live.stop}>
              {t('chat.stop')}
            </button>
          ) : (
            <button type="button" className="gy-composer-btn" disabled={!draft.trim() || !sessionId}
              onClick={send}>
              {t('chat.send')}
            </button>
          )}
        </footer>
        <div className="gy-composer-hint">{t('chat.composerHint')}</div>
      </main>

      {creating && (
        <div className="gy-modal" role="dialog">
          <div className="gy-modal-card">
            <div className="gy-card-h">{t('chat.newSession')}</div>
            <p className="gy-hint">{t('chat.newSessionHint')}</p>
            <div className="gy-modal-list">
              <button type="button" className="gy-route-item" onClick={() => void startSession('')}>
                {t('chat.envDefault')}
              </button>
              {envs.map((env) => (
                <button key={env.id} type="button" className="gy-route-item"
                  onClick={() => void startSession(env.id)}>
                  {env.name}
                </button>
              ))}
            </div>
            <div className="gy-spacer" />
            <button type="button" className="gy-btn gy-btn--ghost gy-btn--block gy-btn--sm"
              onClick={() => setCreating(false)}>
              {t('chat.cancel')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default ChatApp
