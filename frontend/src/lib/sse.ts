/**
 * Unified SSE Manager — shared reconnection logic, event parsing,
 * and lifecycle management for all SSE subscriptions (Chat, Command, VTuber).
 */

export interface SSESubscribeConfig {
  /** Full URL to the SSE endpoint. */
  url: string | (() => string);
  /** Event name → handler map. Each handler receives parsed JSON data. */
  events: Record<string, (data: unknown) => void>;
  /** Reconnect behaviour. */
  reconnect?: {
    maxAttempts?: number;   // default: Infinity
    delay?: number;         // default: 3000ms
    resetOnSuccess?: boolean; // default: true — reset attempt counter on successful event
  };
  /** Called when connection state changes. */
  onConnectionChange?: (connected: boolean) => void;
  /** Called when the stream emits a terminal event (e.g. 'done'). */
  onDone?: () => void;
  /** Event names that signal stream completion. Default: ['done'] */
  doneEvents?: string[];
}

export interface SSESubscription {
  /** Close the subscription and stop reconnecting. */
  close: () => void;
  /** Whether the subscription is still active. */
  isActive: () => boolean;
}

/**
 * Subscribe to an SSE endpoint with automatic reconnection.
 *
 * Replaces the per-feature SSE boilerplate in agentApi, chatApi, and vtuberApi.
 *
 * @example
 * const sub = sseSubscribe({
 *   url: `${backendUrl}/api/chat/rooms/${roomId}/events?after=${after}`,
 *   events: {
 *     message: (data) => addMessage(data),
 *     heartbeat: () => {},
 *   },
 *   reconnect: { maxAttempts: Infinity, delay: 3000 },
 * });
 *
 * // Later:
 * sub.close();
 */
export function sseSubscribe(config: SSESubscribeConfig): SSESubscription {
  const {
    events,
    reconnect: reconnectConfig,
    onConnectionChange,
    onDone,
  } = config;

  const maxAttempts = reconnectConfig?.maxAttempts ?? Infinity;
  const delay = reconnectConfig?.delay ?? 3_000;
  const resetOnSuccess = reconnectConfig?.resetOnSuccess ?? true;
  const doneEvents = new Set(config.doneEvents ?? ['done']);

  let evtSource: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;
  let attempts = 0;

  const resolveUrl = (): string =>
    typeof config.url === 'function' ? config.url() : config.url;

  const cleanup = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    evtSource?.close();
    evtSource = null;
  };

  const scheduleReconnect = () => {
    if (closed || reconnectTimer) return;
    if (attempts >= maxAttempts) {
      closed = true;
      onConnectionChange?.(false);
      return;
    }
    attempts++;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  };

  const connect = () => {
    if (closed) return;

    const url = resolveUrl();
    evtSource = new EventSource(url);

    // Register event listeners
    for (const [eventName, handler] of Object.entries(events)) {
      evtSource.addEventListener(eventName, (e) => {
        if (resetOnSuccess) attempts = 0;
        try {
          const data = (e as MessageEvent).data
            ? JSON.parse((e as MessageEvent).data)
            : {};
          handler(data);
        } catch { /* skip malformed event data */ }
      });
    }

    // Done events — close cleanly
    for (const doneEvent of doneEvents) {
      if (!(doneEvent in events)) {
        evtSource.addEventListener(doneEvent, () => {
          closed = true;
          cleanup();
          onDone?.();
        });
      }
    }

    // Connection opened
    evtSource.onopen = () => {
      onConnectionChange?.(true);
    };

    // Connection error — reconnect
    evtSource.onerror = () => {
      if (closed) return;
      onConnectionChange?.(false);
      evtSource?.close();
      evtSource = null;
      scheduleReconnect();
    };
  };

  connect();

  return {
    close: () => {
      closed = true;
      cleanup();
    },
    isActive: () => !closed,
  };
}
