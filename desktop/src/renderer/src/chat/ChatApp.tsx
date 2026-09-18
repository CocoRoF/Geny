/**
 * The connector's main window: a session, and the work in it.
 *
 * The shell is XGen Dex's — activity bar, sidebar, work, status bar — because
 * Geny and Dex are the same company's desktop apps and were drifting into two
 * different-looking products. The conversation is bubbles under an agent
 * mark; what the agent DID is its own timeline rather than something mixed
 * into what it said.
 *
 * This replaced a browser frame. The window used to load the server's
 * `/connector` page — a web app, in a window, pretending to be an app — and
 * every question a person has here ("which model answered", "what did it just
 * run", "what did it change on disk") was one that page had no room for.
 *
 * Nothing here decides what the agent does. It is the server's session, the
 * server's route, the server's log; this window is where you can see them.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

import genyIcon from '../assets/geny_character.png'
import { makeT, type Lang } from '../i18n'
import {
  agents, environments, sessions as sessionApi,
  type AgentSummary, type EnvironmentSummary,
} from '../server'
import Explorer, { type OpenedFile } from './Explorer'
import FileView from './FileView'
import { Icon } from './icons'
import RouteBar from './RouteBar'
import SystemMonitorFooter from './SystemMonitorFooter'
import Transcript from './Transcript'
import WorkPane from './WorkPane'
import { useSession } from './useSession'

const LAST_SESSION_KEY = 'geny.chat.lastSession'

/**
 * A dropped socket is not a dropped turn: the server keeps working whether or
 * not this window is listening. Saying "disconnected" over a turn that is
 * still running teaches people to distrust a screen that was right.
 */
function lampFor(state: string, running: boolean, t: (k: string) => string):
{ tone: 'ok' | 'busy' | 'offline'; label: string } {
  if (state === 'connected') {
    return running
      ? { tone: 'busy', label: t('chat.state.working') }
      : { tone: 'ok', label: t('chat.state.ready') }
  }
  if (state === 'unauthorized') return { tone: 'offline', label: t('chat.state.signedOut') }
  if (state === 'offline') return { tone: 'offline', label: t('chat.state.offline') }
  return { tone: 'busy', label: t('chat.state.reconnecting') }
}

export function ChatApp(): ReactNode {
  const [lang, setLang] = useState<Lang>('ko')
  const t = useMemo(() => makeT(lang), [lang])

  const [list, setList] = useState<AgentSummary[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [envs, setEnvs] = useState<EnvironmentSummary[]>([])
  const [showWork, setShowWork] = useState(false)
  /** Which sidebar view, or none. The activity bar switches it, and clicking
   *  the view you are already in closes the sidebar — the VS Code idiom. */
  const [side, setSide] = useState<'sessions' | 'files' | null>('sessions')
  /** The tab strip: the conversation is always the first tab, and every file
   *  the explorer opens becomes another. Dex's idiom, and the reason a file
   *  is worth opening at all — you can leave it open while you keep talking. */
  const [files, setFiles] = useState<OpenedFile[]>([])
  const [tab, setTab] = useState<string>('chat')

  const openFile = useCallback((file: OpenedFile) => {
    setFiles((prev) => {
      // Keyed by agent AND path: two agents can both have `artifacts/report.md`
      // and they are not the same file.
      const at = prev.findIndex((f) => f.key === file.key)
      if (at < 0) return [...prev, file]
      // Reopening a file re-reads it: the agent has probably written to it
      // since, which is the reason anyone reopens one.
      const next = prev.slice()
      next[at] = file
      return next
    })
    setTab(file.key)
  }, [])

  const closeFile = useCallback((key: string) => {
    setFiles((prev) => prev.filter((f) => f.key !== key))
    setTab((current) => (current === key ? 'chat' : current))
  }, [])
  const [draft, setDraft] = useState('')
  const scroller = useRef<HTMLDivElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)
  const pinned = useRef(true)

  const live = useSession(sessionId)

  // ── theme + language ────────────────────────────────────────────────
  // Theme is an attribute on <html>, not a class on a wrapper: a window that
  // themes itself through a wrapper cannot theme its own scrollbars or the
  // page behind it.
  useEffect(() => {
    const apply = (mode?: string): void => {
      const root = document.documentElement
      if (mode === 'dark' || mode === 'light') root.dataset.theme = mode
      else delete root.dataset.theme
    }
    void (async () => {
      const config = await window.connector?.serverConfig.get()
      apply(config?.theme)
      const fallback = (await window.connector?.appDefaultLang?.().catch(() => 'ko' as Lang)) ?? 'ko'
      setLang((config?.lang as Lang) ?? fallback)
    })()
    const off = window.connector?.serverConfig.onChange((config) => {
      apply(config?.theme)
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
  const sendLive = live.send
  useEffect(() => {
    const off = window.connector?.messaging.onQuickSend((payload) => {
      const text = (typeof payload === 'string' ? payload : payload?.text ?? '').trim()
      if (text) sendLive(text)
    })
    return () => { off?.() }
    // `live` is a fresh object every render; depending on it would resubscribe
    // on every keystroke.
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
    // it back, so a long message would leave a tall empty box behind.
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
  // Running sessions get their own group at the top. They are then left OUT
  // of the list below it: showing the same session twice, in two identical
  // rows, reads as a duplicate rather than as a shortcut.
  const running = list.filter((s) => s.status === 'running')
  const idle = list.filter((s) => s.status !== 'running')
  const lamp = lampFor(live.state, live.running, t)

  const sessionRow = (session: AgentSummary): ReactNode => (
    <button
      key={session.session_id}
      type="button"
      className={`agent-item ${session.session_id === sessionId ? 'active' : ''}`}
      onClick={() => setSessionId(session.session_id)}
    >
      <span className={`agent-dot ${session.status === 'running' ? 'run' : ''}`} />
      <span className="agent-text">
        <span className="agent-name">
          {session.session_name || session.session_id.slice(0, 8)}
        </span>
        <span className="agent-meta">
          {session.env_name || t('chat.untitledEnv')}
          {session.last_route?.label ? ` · ${session.last_route.label}` : ''}
        </span>
      </span>
    </button>
  )

  return (
    <div className="workspace">
      <nav className="activity-bar">
        <span className="ab-logo"><img src={genyIcon} alt="Geny" draggable={false} /></span>
        <div className="ab-top">
          <button type="button" className={`ab-btn ${side === 'sessions' ? 'active' : ''}`}
            title={t('chat.sessions')}
            onClick={() => setSide((v) => (v === 'sessions' ? null : 'sessions'))}>
            {side === 'sessions' && <span className="ab-ind" />}
            {Icon.chat}
          </button>
          <button type="button" className={`ab-btn ${side === 'files' ? 'active' : ''}`}
            title={t('explorer.title')}
            onClick={() => setSide((v) => (v === 'files' ? null : 'files'))}>
            {side === 'files' && <span className="ab-ind" />}
            {Icon.files}
          </button>
          <button type="button" className={`ab-btn ${showWork ? 'active' : ''}`}
            title={t('chat.activity')} onClick={() => setShowWork((v) => !v)}>
            {Icon.activity}
          </button>
        </div>
        <div className="ab-bottom">
          <button type="button" className="ab-btn" title={t('chat.openSettings')}
            onClick={() => window.connector?.windowControl.openSettings()}>
            {Icon.settings}
          </button>
        </div>
      </nav>

      <aside className={`sidebar ${side ? '' : 'hidden'}`}>
        <div className="sidebar-title">
          <span className="sidebar-title-text">
            {side === 'files' ? t('explorer.title') : t('chat.sessions')}
          </span>
          {side === 'sessions' && (
            <span style={{ display: 'flex', gap: 2 }}>
              <button type="button" className="icon-btn" title={t('chat.refresh')}
                onClick={() => void refreshList()}>{Icon.refresh}</button>
              <button type="button" className="icon-btn" title={t('chat.newSession')}
                onClick={() => void openCreate()}>{Icon.plus}</button>
            </span>
          )}
        </div>

        {side === 'files' ? (
          <Explorer sessions={list} sessionId={sessionId} running={live.running}
            t={t} onOpen={openFile} />
        ) : (
          <>
            {running.length > 0 && (
              <div className="side-live">
                <div className="side-live-h">{t('chat.liveNow')}</div>
                {running.map(sessionRow)}
              </div>
            )}
            <div className="agent-list">
              {listError && <div className="side-error">{listError}</div>}
              {idle.map(sessionRow)}
              {list.length === 0 && !listError && (
                <div className="side-empty">{t('chat.noSessions')}</div>
              )}
            </div>
          </>
        )}
      </aside>

      <main className="main-pane">
        {/* Always here, even with nothing open but the conversation. The strip
            is where you are, not a thing that appears once you have two of
            them — a window whose top bar comes and goes moves everything
            below it by 38px and makes the app feel unreliable. The chat is
            the first tab and cannot be closed; files open beside it. */}
        <div className="tab-strip">
          <div className="tab-strip-scroll">
            <button type="button"
              className={`tab-item ${tab === 'chat' ? 'active' : ''}`}
              onClick={() => setTab('chat')}>
              <span className="tab-icon">{Icon.chat}</span>
              <span className="tab-label" title={current?.session_name || t('chat.tabChat')}>
                {current?.session_name || t('chat.tabChat')}
              </span>
            </button>
            {files.map((file) => (
              <button key={file.key} type="button"
                className={`tab-item ${tab === file.key ? 'active' : ''}`}
                onClick={() => setTab(file.key)}>
                <span className="tab-icon">{Icon.file}</span>
                <span className="tab-label" title={file.path}>{file.name}</span>
                <span className="tab-close" role="button" aria-label={t('explorer.close')}
                  onClick={(e) => { e.stopPropagation(); closeFile(file.key) }}>
                  {Icon.close}
                </span>
              </button>
            ))}
          </div>
        </div>

        {tab !== 'chat' && (() => {
          const file = files.find((f) => f.key === tab)
          return file ? <FileView sessionId={file.sessionId} name={file.name}
            path={file.path} content={file.content} binary={file.binary}
            size={file.size} t={t} /> : null
        })()}

        <div className="chat" hidden={tab !== 'chat'}>
          <header className="chat-header">
            <div className="chat-title">
              <span className="agent-mark">G</span>
              <div className="chat-title-text">
                <strong>{current?.session_name || t('chat.untitled')}</strong>
                <span className="agent-meta">
                  {current?.env_name || t('chat.untitledEnv')}
                  {current ? ` · ${lamp.label}` : ''}
                </span>
              </div>
            </div>
            <div className="chat-header-actions">
              <RouteBar sessionId={sessionId} t={t} />
              <button type="button" className={`chat-hbtn ${showWork ? 'on' : ''}`}
                onClick={() => setShowWork((v) => !v)}>
                {Icon.eye} {t('chat.activity')}
              </button>
            </div>
          </header>

          {live.error && (
            <div className="chat-banner" role="button" tabIndex={0} onClick={live.clearError}
              onKeyDown={(e) => { if (e.key === 'Enter') live.clearError() }}>
              {live.error}
            </div>
          )}

          <div className="chat-body">
            <div className="chat-column">
              <div className="chat-log" ref={scroller} onScroll={onScroll}>
                <Transcript messages={live.messages} calls={live.calls}
                  running={live.running} loading={live.loading} t={t} />
              </div>

              <footer className="chat-input">
                <div className="composer">
                  <textarea
                    ref={composer}
                    className="composer-input"
                    value={draft}
                    placeholder={sessionId ? t('chat.placeholder') : t('chat.placeholderNoSession')}
                    disabled={!sessionId}
                    rows={1}
                    onChange={(e) => {
                      setDraft(e.target.value)
                      const el = e.target
                      el.style.height = 'auto'
                      el.style.height = `${Math.min(150, el.scrollHeight)}px`
                    }}
                    onKeyDown={onKey}
                  />
                  {live.running ? (
                    <button type="button" className="composer-send stop" onClick={live.stop}
                      title={t('chat.stop')}>
                      {Icon.stop}
                    </button>
                  ) : (
                    <button type="button" className="composer-send"
                      disabled={!draft.trim() || !sessionId} onClick={send} title={t('chat.send')}>
                      {Icon.send}
                    </button>
                  )}
                </div>
                <div className="kbd-hint">
                  <kbd>Enter</kbd> {t('chat.kbdSend')} · <kbd>Shift + Enter</kbd> {t('chat.kbdNewline')}
                  <span className="spacer" />
                  {live.running ? <><kbd>Esc</kbd> {t('chat.kbdStop')}</> : null}
                </div>
              </footer>
            </div>

            {showWork && sessionId && <WorkPane sessionId={sessionId} t={t} />}
          </div>
        </div>
      </main>

      <SystemMonitorFooter t={t} state={lamp} />

      {creating && (
        <div className="modal-backdrop" role="dialog">
          <div className="modal-card">
            <div className="modal-title">{t('chat.newSession')}</div>
            <p className="modal-hint">{t('chat.newSessionHint')}</p>
            <div className="modal-list">
              <button type="button" className="route-item" onClick={() => void startSession('')}>
                {t('chat.envDefault')}
              </button>
              {envs.map((env) => (
                <button key={env.id} type="button" className="route-item"
                  onClick={() => void startSession(env.id)}>
                  {env.name}
                </button>
              ))}
            </div>
            <div className="gy-spacer" />
            <button type="button" className="chat-hbtn" style={{ width: '100%' }}
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
