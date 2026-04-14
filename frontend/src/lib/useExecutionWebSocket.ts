/**
 * WebSocket hook for agent execution streaming.
 *
 * Replaces the two-step SSE pattern (POST /execute/start + GET /execute/events)
 * with a single persistent WebSocket connection.
 *
 * Protocol:
 *   Client -> {"type": "execute", "prompt": "...", ...}
 *   Client -> {"type": "stop"}
 *   Client -> {"type": "reconnect"}
 *   Server -> {"type": "log"|"status"|"result"|"heartbeat"|"error"|"done", "data": {...}}
 */

import { useRef, useCallback } from 'react';

export type WsEventType = 'log' | 'status' | 'result' | 'heartbeat' | 'error' | 'done';

export interface WsEvent {
  type: WsEventType;
  data: Record<string, unknown>;
}

export interface ExecuteOptions {
  prompt: string;
  timeout?: number | null;
  system_prompt?: string | null;
  max_turns?: number | null;
}

/**
 * Build the WebSocket URL for a given session.
 *
 * In production behind nginx, the browser connects to the same host
 * (nginx routes /ws/ to the backend).
 * In dev mode, connects directly to the backend port.
 */
function getWsUrl(sessionId: string): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl !== undefined && envUrl !== '') {
    // Explicit backend URL configured — convert http(s) to ws(s)
    const wsBase = envUrl.replace(/^http/, 'ws');
    return `${wsBase}/ws/execute/${sessionId}`;
  }

  // Production (reverse proxy) — use relative path through current host
  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';

    // Dev mode: direct backend connection
    const backendPort = process.env.NEXT_PUBLIC_BACKEND_PORT;
    if (backendPort) {
      return `${proto}//${window.location.hostname}:${backendPort}/ws/execute/${sessionId}`;
    }

    // Production: same host (nginx proxy)
    return `${proto}//${window.location.host}/ws/execute/${sessionId}`;
  }

  return `ws://localhost:8000/ws/execute/${sessionId}`;
}

export function useExecutionWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const sessionIdRef = useRef<string | null>(null);

  /**
   * Start a new execution over WebSocket.
   *
   * @param sessionId   Agent session to execute on
   * @param options     Execute options (prompt, timeout, etc.)
   * @param onEvent     Callback for each event from the server
   * @returns Promise that resolves when execution completes (done event received)
   */
  const execute = useCallback(
    (
      sessionId: string,
      options: ExecuteOptions,
      onEvent: (eventType: string, eventData: Record<string, unknown>) => void,
    ): Promise<void> => {
      return new Promise<void>((resolve, reject) => {
        // Close any existing connection
        if (wsRef.current) {
          wsRef.current.close();
          wsRef.current = null;
        }

        sessionIdRef.current = sessionId;
        const wsUrl = getWsUrl(sessionId);
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          ws.send(
            JSON.stringify({
              type: 'execute',
              prompt: options.prompt,
              timeout: options.timeout ?? null,
              system_prompt: options.system_prompt ?? null,
              max_turns: options.max_turns ?? null,
            }),
          );
        };

        ws.onmessage = (ev) => {
          try {
            const event: WsEvent = JSON.parse(ev.data);
            onEvent(event.type, event.data);
            if (event.type === 'done') {
              resolve();
            }
          } catch {
            // ignore unparseable messages
          }
        };

        ws.onerror = () => {
          onEvent('error', { error: 'WebSocket connection error' });
          wsRef.current = null;
          reject(new Error('WebSocket connection error'));
        };

        ws.onclose = (ev) => {
          wsRef.current = null;
          // If closed before done event, resolve anyway
          if (!ev.wasClean) {
            onEvent('error', { error: 'WebSocket connection lost' });
          }
          resolve();
        };
      });
    },
    [],
  );

  /**
   * Reconnect to an active execution.
   *
   * @param sessionId   Agent session to reconnect to
   * @param onEvent     Callback for each event from the server
   * @returns Object with close() method to stop the reconnection
   */
  const reconnect = useCallback(
    (
      sessionId: string,
      onEvent: (eventType: string, eventData: Record<string, unknown>) => void,
    ): { close: () => void } => {
      // Close any existing connection
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      sessionIdRef.current = sessionId;
      const wsUrl = getWsUrl(sessionId);
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'reconnect' }));
      };

      ws.onmessage = (ev) => {
        try {
          const event: WsEvent = JSON.parse(ev.data);
          onEvent(event.type, event.data);
        } catch {
          // ignore
        }
      };

      ws.onerror = () => {
        wsRef.current = null;
      };

      ws.onclose = () => {
        wsRef.current = null;
      };

      return {
        close: () => {
          ws.close();
          wsRef.current = null;
        },
      };
    },
    [],
  );

  /**
   * Send a stop signal to the current execution.
   */
  const stop = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }));
    }
  }, []);

  /**
   * Close the WebSocket connection.
   */
  const close = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    sessionIdRef.current = null;
  }, []);

  return { execute, reconnect, stop, close };
}
