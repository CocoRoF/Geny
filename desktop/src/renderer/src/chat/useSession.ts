/**
 * One session, live, in the connector's main window.
 *
 * The desktop version of the phone's `useLiveTurn`, over the same socket and
 * the same fold (`shared/chat/*`). It differs in two ways, and both come from
 * the fact that a desktop window is not a phone screen:
 *
 * · Opening a session loads its LOG first. A phone shows the turn it is in;
 *   a desktop window is where the work lives, and scrolling up to yesterday
 *   has to work. The log is the honest record, folded by the same function
 *   that folds the live stream, so the seam between "read from history" and
 *   "arrived just now" is invisible.
 * · Waking up is a window event, not an app-state one.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import { connectExecWs, type ConnState, type ExecWsHandle, type LogEntry }
  from '../../../../../shared/chat/exec-ws'
import { foldAll, foldEntry, pendingUserMessage, type Message }
  from '../../../../../shared/chat/transcript'
import { authToken, sessions, wsBase } from '../server'

export interface LiveSession {
  state: ConnState
  running: boolean
  messages: Message[]
  /** The log is still being read — the window shows a skeleton, not "empty". */
  loading: boolean
  error: string | null
  send(prompt: string): void
  stop(): void
  clearError(): void
}

export function useSession(sessionId: string | null): LiveSession {
  const [state, setState] = useState<ConnState>('connecting')
  const [running, setRunning] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const handle = useRef<ExecWsHandle | null>(null)
  const seq = useRef(0)

  useEffect(() => {
    handle.current?.close()
    handle.current = null
    setMessages([])
    setRunning(false)
    seq.current = 0
    if (!sessionId) {
      setState('closed')
      return
    }
    setLoading(true)

    let cancelled = false
    void (async () => {
      // History first, socket second. The other order shows the live turn and
      // then shoves it down the screen when the log lands.
      try {
        const log = await sessions.logs(sessionId)
        if (cancelled) return
        // The endpoint answers newest-first; a conversation reads the other way.
        setMessages(foldAll([...log.entries].reverse()))
        seq.current = log.entries.length
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      } finally {
        if (!cancelled) setLoading(false)
      }
      if (cancelled) return

      const [base, token] = await Promise.all([
        wsBase().catch(() => ''),
        authToken(),
      ])
      if (cancelled || !base) return
      handle.current = connectExecWs({
        wsBase: base,
        sessionId,
        token,
        onState: setState,
        onRunning: setRunning,
        onError: setError,
        onLog: (entry: LogEntry) => {
          seq.current += 1
          setMessages((prev) => foldEntry(prev, entry, seq.current))
        },
      })
    })()

    return () => {
      cancelled = true
      handle.current?.close()
      handle.current = null
    }
  }, [sessionId])

  // A laptop that slept has a socket the OS kept and the network dropped.
  // Both events mean the same thing: prove the connection, do not wait out a
  // backoff timer that was counting for a server outage.
  useEffect(() => {
    const wake = (): void => handle.current?.resume()
    window.addEventListener('focus', wake)
    window.addEventListener('online', wake)
    return () => {
      window.removeEventListener('focus', wake)
      window.removeEventListener('online', wake)
    }
  }, [])

  const send = useCallback((prompt: string) => {
    const text = prompt.trim()
    if (!text) return
    // Drawn immediately; the server's own echo replaces it in place.
    setMessages((prev) => [...prev, pendingUserMessage(text)])
    handle.current?.execute(text)
  }, [])

  return {
    state,
    running,
    messages,
    loading,
    error,
    send,
    stop: () => handle.current?.stop(),
    clearError: () => setError(null),
  }
}
