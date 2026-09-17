/**
 * One session's conversation, live.
 *
 * The conversation is the ROOM. This window used to fold the session's
 * execute log instead, which looked right on its own and meant the app, the
 * web page and the phone each showed a different conversation — messages
 * typed here never reached the web, and messages the web sent never reached
 * here. The room is the store every surface shares; the log is the engine's
 * record and answers a different question ("what did it DO"), which is the
 * work pane's job.
 *
 * Two streams, therefore, and they are not the same thing:
 *
 *  · the room socket — the conversation, and who is working
 *  · the execute socket — nothing here. The room's `agent_progress` carries
 *    the tool calls, which is what the web has always used, and using the
 *    same source is the whole point of this file.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

import {
  connectRoom, foldCalls, foldRoom, foldRoomMessage, lastRoomId,
  type ConnState, type RoomHandle, type ToolCall,
} from '../../../../../shared/chat/room'
import { pendingUserMessage, type Message } from '../../../../../shared/chat/transcript'
import { authToken, rooms, wsBase, type ChatRoom } from '../server'

export interface LiveSession {
  state: ConnState
  /** A turn is running somewhere in this room. */
  running: boolean
  messages: Message[]
  /** What the agent is doing right now, from the room's progress feed. */
  calls: ToolCall[]
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
  const [calls, setCalls] = useState<ToolCall[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const room = useRef<ChatRoom | null>(null)
  const handle = useRef<RoomHandle | null>(null)
  /** Read at connect time by the socket's greeting, so it resumes from here. */
  const cursor = useRef<string | null>(null)

  useEffect(() => {
    handle.current?.close()
    handle.current = null
    room.current = null
    cursor.current = null
    setMessages([])
    setCalls([])
    setRunning(false)
    if (!sessionId) {
      setState('closed')
      return
    }
    setLoading(true)

    let cancelled = false
    void (async () => {
      try {
        // The server decides which room this session talks in, and makes one
        // if it never has. Deciding it here is what let this app, the web
        // page and the phone each pick a different room.
        const found = await rooms.forSession(sessionId)
        if (cancelled) return
        room.current = found
        const history = await rooms.messages(found.id)
        if (cancelled) return
        const folded = foldRoom(history.messages ?? [])
        setMessages(folded)
        cursor.current = lastRoomId(folded)
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      } finally {
        if (!cancelled) setLoading(false)
      }
      if (cancelled || !room.current) return

      const [base, token] = await Promise.all([wsBase().catch(() => ''), authToken()])
      if (cancelled || !base) return
      handle.current = connectRoom({
        wsBase: base,
        roomId: room.current.id,
        token,
        after: () => cursor.current,
        onState: setState,
        onError: setError,
        onMessage: (raw) => {
          setMessages((prev) => {
            const next = foldRoomMessage(prev, raw)
            cursor.current = lastRoomId(next)
            return next
          })
        },
        onProgress: (agents) => {
          const mine = agents.filter((a) => !sessionId || a.session_id === sessionId)
          const busy = mine.some((a) => a.status === 'executing' || a.status === 'pending')
          setRunning(busy || agents.some((a) => a.status === 'executing'))
          const logs = mine.flatMap((a) => a.recent_logs ?? [])
          setCalls(foldCalls(logs))
        },
        onIdle: () => {
          setRunning(false)
          setCalls([])
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
  // Both events mean the same thing: prove the connection rather than wait
  // out a backoff that was counting for a server outage.
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
    if (!text || !sessionId) return
    // Drawn immediately; the room's own copy replaces it in place.
    setMessages((prev) => [...prev, pendingUserMessage(text)])
    setRunning(true)
    void (async () => {
      try {
        if (!room.current) {
          // The room lookup failed earlier (server was down, say). Ask again
          // rather than dropping what the user just typed.
          room.current = await rooms.forSession(sessionId)
        }
        if (!room.current) {
          setError('이 세션의 대화방을 찾지 못했습니다')
          setRunning(false)
          return
        }
        await rooms.send(room.current.id, text)
      } catch (e) {
        setError((e as Error).message)
        setRunning(false)
      }
    })()
  }, [sessionId])

  return {
    state,
    running,
    messages,
    calls,
    loading,
    error,
    send,
    stop: () => {
      // Stopping is a session-level act, not a room one.
      if (sessionId) void import('../server').then(({ agents }) => agents.stop(sessionId))
    },
    clearError: () => setError(null),
  }
}
