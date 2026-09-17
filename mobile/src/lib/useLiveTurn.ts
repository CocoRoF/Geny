/**
 * The chat screen's connection, as a hook.
 *
 * Holds one socket for as long as the screen is on a session, and wakes it on
 * the two events a phone actually has: coming back to the foreground, and the
 * network returning. Both call `resume()`, which skips the backoff — a user
 * who just unlocked their phone should not wait out a timer that was counting
 * for a server outage.
 */
import { useEffect, useRef, useState } from 'react';
import { AppState, type AppStateStatus } from 'react-native';
import * as Network from 'expo-network';

import { connectExecWs, type ConnState, type ExecWsHandle, type LogEntry } from './exec-ws';
import { foldEntry, pendingUserMessage, type Message } from './transcript';

export interface LiveTurn {
  state: ConnState;
  running: boolean;
  messages: Message[];
  error: string | null;
  send(prompt: string): void;
  stop(): void;
  clearError(): void;
}

export function useLiveTurn(
  wsBase: string,
  sessionId: string | null,
  token: string | null,
): LiveTurn {
  const [state, setState] = useState<ConnState>('connecting');
  const [running, setRunning] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState<string | null>(null);
  const handleRef = useRef<ExecWsHandle | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    if (!sessionId || !wsBase) {
      handleRef.current?.close();
      handleRef.current = null;
      return;
    }
    setMessages([]);
    seq.current = 0;

    const handle = connectExecWs({
      wsBase,
      sessionId,
      token,
      onState: setState,
      onRunning: setRunning,
      onError: setError,
      onLog: (entry: LogEntry) => {
        seq.current += 1;
        setMessages((prev) => foldEntry(prev, entry, seq.current));
      },
    });
    handleRef.current = handle;
    return () => {
      handle.close();
      handleRef.current = null;
    };
  }, [wsBase, sessionId, token]);

  // Foreground. The socket usually died while the screen was off; even when it
  // did not, it may be a half-open one that the OS kept and the network
  // dropped — `resume()` makes it prove otherwise.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next: AppStateStatus) => {
      if (next === 'active') handleRef.current?.resume();
    });
    return () => sub.remove();
  }, []);

  // Network. `expo-network` has no event stream on every platform, so this
  // polls — cheaply, and only while the screen is mounted. Coming back onto
  // wifi should not cost the user a wait.
  useEffect(() => {
    let cancelled = false;
    let wasOnline = true;
    const timer = setInterval(async () => {
      try {
        const status = await Network.getNetworkStateAsync();
        const online = Boolean(status.isConnected && status.isInternetReachable !== false);
        if (cancelled) return;
        if (online && !wasOnline) handleRef.current?.resume();
        wasOnline = online;
      } catch {
        /* the probe itself failing is not information */
      }
    }, 5_000);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  return {
    state,
    running,
    messages,
    error,
    send: (prompt: string) => {
      const text = prompt.trim();
      if (!text) return;
      // Show it immediately. The server echoes it back as a COMMAND log with
      // its own timestamp, and the fold adopts that one in place — waiting for
      // the round trip makes the app feel broken on a slow connection, and
      // appending both makes it look like the message was sent twice.
      setMessages((prev) => [...prev, pendingUserMessage(text)]);
      handleRef.current?.execute(text);
    },
    stop: () => handleRef.current?.stop(),
    clearError: () => setError(null),
  };
}
