/**
 * The chat screen's connection, as a hook.
 *
 * The conversation is the ROOM — the same store the desktop app and the web
 * page read and write. This used to fold the session's execute log, which
 * gave the phone a conversation of its own: what was typed here never showed
 * up on the web, and what the web sent never showed up here. Same room, same
 * cursor, same fold, everywhere.
 *
 * Holds one socket for as long as the screen is on a session, and wakes it on
 * the two events a phone actually has: coming back to the foreground, and the
 * network returning. Both call `resume()`, which skips the backoff — a user
 * who just unlocked their phone should not wait out a timer that was counting
 * for a server outage.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, type AppStateStatus } from 'react-native';
import * as Network from 'expo-network';

import {
  connectRoom, foldCalls, foldRoom, foldRoomMessage, lastRoomId,
  type ConnState, type RoomHandle, type ToolCall,
} from '../../../shared/chat/room';
import { pendingUserMessage, type Message } from '../../../shared/chat/transcript';
import {
  agents, rooms, toWsBase, type ChatRoom, type Credentials,
} from './server';

export interface LiveTurn {
  state: ConnState;
  /** A turn is running in this room. Not the same fact as being connected. */
  running: boolean;
  messages: Message[];
  /** What the agent is doing right now, from the room's own progress feed. */
  calls: ToolCall[];
  loading: boolean;
  error: string | null;
  send(prompt: string): void;
  stop(): void;
  clearError(): void;
}

export function useLiveTurn(
  baseUrl: string,
  sessionId: string | null,
  token: string | null,
): LiveTurn {
  const [state, setState] = useState<ConnState>('connecting');
  const [running, setRunning] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [calls, setCalls] = useState<ToolCall[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const handle = useRef<RoomHandle | null>(null);
  const room = useRef<ChatRoom | null>(null);
  /** Read by the greeting at connect time, so a reconnect resumes from here. */
  const cursor = useRef<string | null>(null);

  // Rebuilt only when the two things it is made of change — a fresh object per
  // render would restart the socket on every keystroke.
  const creds: Credentials = useMemo(() => ({ baseUrl, token }), [baseUrl, token]);

  useEffect(() => {
    handle.current?.close();
    handle.current = null;
    room.current = null;
    cursor.current = null;
    setMessages([]);
    setCalls([]);
    setRunning(false);
    if (!sessionId || !baseUrl || !token) {
      setState('closed');
      return;
    }
    setLoading(true);

    let cancelled = false;
    void (async () => {
      try {
        // The server decides which room this session talks in, and makes one
        // if it never has — the same answer it gives the laptop and the web.
        const found = await rooms.forSession(creds, sessionId);
        if (cancelled) return;
        room.current = found;
        const history = await rooms.messages(creds, found.id);
        if (cancelled) return;
        const folded = foldRoom(history.messages ?? []);
        setMessages(folded);
        cursor.current = lastRoomId(folded);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
      if (cancelled || !room.current) return;

      handle.current = connectRoom({
        wsBase: toWsBase(baseUrl),
        roomId: room.current.id,
        token,
        after: () => cursor.current,
        onState: setState,
        onError: setError,
        onMessage: (raw) => {
          setMessages((prev) => {
            const next = foldRoomMessage(prev, raw);
            cursor.current = lastRoomId(next);
            return next;
          });
        },
        onProgress: (list) => {
          const mine = list.filter((a) => a.session_id === sessionId);
          setRunning(mine.some((a) => a.status === 'executing' || a.status === 'pending'));
          setCalls(foldCalls(mine.flatMap((a) => a.recent_logs ?? [])));
        },
        onIdle: () => { setRunning(false); setCalls([]); },
      });
    })();

    return () => {
      cancelled = true;
      handle.current?.close();
      handle.current = null;
    };
  }, [creds, baseUrl, token, sessionId]);

  // Foreground. The socket usually died while the screen was off; even when
  // it did not, it may be a half-open one the OS kept and the network
  // dropped — `resume()` makes it prove otherwise.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (next === 'active') handle.current?.resume();
    });
    return () => sub.remove();
  }, []);

  // Network. `expo-network` has no event stream on every platform, so this
  // polls — cheaply, and only while the screen is mounted.
  useEffect(() => {
    let cancelled = false;
    let wasOnline = true;
    const timer = setInterval(() => {
      void Network.getNetworkStateAsync()
        .then((status) => {
          const online = Boolean(status.isConnected && status.isInternetReachable !== false);
          if (cancelled) return;
          if (online && !wasOnline) handle.current?.resume();
          wasOnline = online;
        })
        .catch(() => undefined); // the probe itself failing is not information
    }, 5_000);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  const send = useCallback((prompt: string) => {
    const text = prompt.trim();
    if (!text || !sessionId) return;
    // Drawn immediately; the room's own copy replaces it in place.
    setMessages((prev) => [...prev, pendingUserMessage(text)]);
    setRunning(true);
    void (async () => {
      try {
        if (!room.current) {
          // The lookup failed earlier (no signal, say). Ask again rather than
          // dropping what the user just typed.
          room.current = await rooms.forSession(creds, sessionId);
        }
        if (!room.current) {
          setError('이 세션의 대화방을 찾지 못했습니다');
          setRunning(false);
          return;
        }
        await rooms.send(creds, room.current.id, text);
      } catch (e) {
        setError((e as Error).message);
        setRunning(false);
      }
    })();
  }, [creds, sessionId]);

  const stop = useCallback(() => {
    // Stopping is a session-level act, not a room one.
    if (!sessionId) return;
    void agents.stop(creds, sessionId).catch((e) => setError((e as Error).message));
  }, [creds, sessionId]);

  return {
    state, running, messages, calls, loading, error,
    send, stop, clearError: () => setError(null),
  };
}
