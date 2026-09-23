/**
 * The conversation — the thing every surface must agree about.
 *
 * A Geny session has two streams, and confusing them is what made the web,
 * the desktop app and the phone show three different conversations:
 *
 *  · The **room** is the conversation. Every message a person sends and every
 *    message an agent delivers — including the ones it starts by itself —
 *    is stored there, and that store is what the web has always rendered.
 *  · The **execute log** is the engine's record of a turn: its tool calls,
 *    its stages, its errors. It contains the answer too, which is exactly why
 *    it was tempting to render, and why rendering it produced a second
 *    conversation that nobody else could see.
 *
 * So: the room is the conversation, everywhere. The log stays what it is —
 * the material for "what did it DO", which is a different question and has
 * its own panel.
 *
 * Free of React and of any platform import; tested under `node:test`.
 */

import { openSocket, type ConnState, type SocketHandle } from './socket';
import { spoken, type Message, type MessageAttachment } from './transcript';

export type { ConnState };

/** A message as `/api/chat/rooms/{id}/messages` returns it. */
export interface RoomMessage {
  id: string;
  /** 'user' | 'agent' | 'system' */
  type?: string;
  content?: string;
  timestamp?: string;
  session_id?: string | null;
  session_name?: string | null;
  duration_ms?: number | null;
  meta?: Record<string, unknown> | null;
  attachments?: MessageAttachment[] | null;
  /** agent only: the reply with its emotion cues inline, for the voice. */
  spoken?: string | null;
  /** agent only: where it came from (`thinking_trigger`, …); absent = a reply. */
  source?: string | null;
}

/** Only what a screen can show: a file with no way to reach it is not one. */
function attachmentsOf(raw: RoomMessage): MessageAttachment[] | undefined {
  const list = (raw.attachments ?? []).filter((a) => a && (a.url || a.attachment_id));
  return list.length ? list : undefined;
}

/**
 * A stored turn that was really a failure.
 *
 * Anchored, single-paragraph, and the whole message: `Error: CLI '/usr/bin/
 * claude' exited with code 1`. Anything with a blank line in it is prose that
 * happens to start with the word, and prose is the agent talking.
 */
const FAILED_TURN = /^\s*Error:\s+\S[^]*$/;
const PROSE = /\n\s*\n/;

/**
 * One room message → the conversation.
 *
 * Idempotent by id: the socket replays from a cursor on every reconnect, and
 * a replayed message must land on itself rather than beside itself.
 */
export function foldRoomMessage(messages: Message[], raw: RoomMessage): Message[] {
  const key = `room:${raw.id}`;
  const at = messages.findIndex((m) => m.key === key);
  const ts = raw.timestamp;

  if (raw.type === 'user') {
    const text = String(raw.content ?? '');
    const next: Message = { key, role: 'user', text, ts };
    const files = attachmentsOf(raw);
    if (files) next.attachments = files;
    if (at >= 0) return replace(messages, at, next);
    // The server's copy of a message this screen already drew. Adopt its
    // identity rather than appending a twin — and only over a PENDING one,
    // so a user who really does send the same line twice gets two bubbles.
    const pending = messages.findIndex(
      (m) => m.role === 'user' && m.pending && m.text === text,
    );
    if (pending >= 0) return replace(messages, pending, next);
    return [...messages, next];
  }

  if (raw.type === 'agent') {
    // A turn that died, stored before the server learned to tell the
    // difference (it does now — see service/execution/agent_executor.py).
    // The whole message is the error and nothing else, which is why this can
    // recognise it without reading agent messages that merely discuss one:
    // a real answer about an error has a sentence around it.
    const body = String(raw.content ?? '');
    if (FAILED_TURN.test(body) && !PROSE.test(body)) {
      const next: Message = {
        key, role: 'notice', text: body.replace(/^\s*Error:\s*/, ''), ts,
      };
      return at >= 0 ? replace(messages, at, next) : [...messages, next];
    }

    const said = spoken(raw.content);
    const files = attachmentsOf(raw);
    // Silence is an answer the agent asked us not to deliver. A message whose
    // only content is a file it sent is not silence — dropping it lost every
    // file an agent delivered without a sentence around it.
    if (said.silent || (!said.text && !files)) return at >= 0 ? drop(messages, at) : messages;
    const next: Message = {
      key,
      role: 'assistant',
      text: said.text,
      ts,
      mood: said.mood,
      durationMs: raw.duration_ms ?? undefined,
    };
    if (files) next.attachments = files;
    if (raw.spoken) next.spoken = raw.spoken;
    return at >= 0 ? replace(messages, at, next) : [...messages, next];
  }

  // 'system' — the room's own bookkeeping ("1/1 sessions responded (7.1s)").
  // Worth having on screen, and NOT a failure: drawing it as one, which is
  // what happened when it was folded as a notice, told the user a turn had
  // failed every single time one succeeded. The web has always drawn these as
  // a quiet centred line; so does everything else now.
  const next: Message = { key, role: 'system', text: String(raw.content ?? ''), ts };
  if (!next.text) return messages;
  return at >= 0 ? replace(messages, at, next) : [...messages, next];
}

function replace(messages: Message[], at: number, next: Message): Message[] {
  const out = messages.slice();
  out[at] = next;
  return out;
}

function drop(messages: Message[], at: number): Message[] {
  const out = messages.slice();
  out.splice(at, 1);
  return out;
}

/** Fold a whole page of history, oldest first. */
export function foldRoom(raws: RoomMessage[]): Message[] {
  return raws.reduce<Message[]>((acc, raw) => foldRoomMessage(acc, raw), []);
}

/** The id to resume from: the newest room message this client has folded. */
export function lastRoomId(messages: Message[]): string | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].key.startsWith('room:')) return messages[i].key.slice(5);
  }
  return null;
}

// ── what the agent is doing, while it does it ────────────────────────

/** A log line as the room's `agent_progress` event carries it. */
export interface ProgressLog {
  level?: string;
  message?: string;
  tool_name?: string;
  tool_id?: string;
  input_preview?: string;
  result_preview?: string;
  duration_ms?: number;
  is_error?: boolean;
}

export interface ToolCall {
  key: string;
  name: string;
  input?: unknown;
  result?: string;
  ok?: boolean | null;
  durationMs?: number;
}

/**
 * TOOL / TOOL_RES log lines → one call each.
 *
 * Paired by `tool_id` where the server sent one, and otherwise by name onto
 * the most recent call still waiting — production carries both shapes,
 * because a batch summary arrives with neither an id nor a name.
 */
export function foldCalls(logs: ProgressLog[]): ToolCall[] {
  const calls: ToolCall[] = [];
  logs.forEach((log, i) => {
    if (log.level === 'TOOL') {
      calls.push({
        key: log.tool_id ?? `${i}:${log.tool_name ?? 'tool'}`,
        name: log.tool_name ?? 'tool',
        input: log.input_preview,
        ok: null,
      });
      return;
    }
    if (log.level !== 'TOOL_RES') return;
    const match = log.tool_id
      ? calls.find((c) => c.key === log.tool_id)
      : [...calls].reverse().find((c) =>
        c.ok === null && (!log.tool_name || c.name === log.tool_name));
    if (!match) return;
    match.ok = !log.is_error;
    match.result = log.result_preview;
    match.durationMs = log.duration_ms;
  });
  return calls;
}

// ── the socket ───────────────────────────────────────────────────────

export interface RoomAgentState {
  session_id?: string;
  session_name?: string;
  status?: string;
  recent_logs?: ProgressLog[];
}

export interface RoomEvents {
  onState?(state: ConnState): void;
  onMessage?(message: RoomMessage): void;
  /** Who is working, and on what. */
  onProgress?(agents: RoomAgentState[]): void;
  /** A broadcast finished — nothing is working any more. */
  onIdle?(): void;
  onError?(message: string): void;
}

export interface RoomOptions extends RoomEvents {
  /** `wss://host` — no trailing slash needed. */
  wsBase: string;
  roomId: string;
  token: string | null;
  /** The newest message already on screen, so a reconnect resumes from it. */
  after(): string | null;
  wsFactory?: (url: string, protocols?: string[]) => WebSocket;
  setTimeoutFn?: (fn: () => void, ms: number) => unknown;
  clearTimeoutFn?: (handle: unknown) => void;
  now?: () => number;
  log?(line: string): void;
}

export interface RoomHandle {
  resume(): void;
  close(): void;
  state(): ConnState;
}

export function connectRoom(opts: RoomOptions): RoomHandle {
  const url = `${opts.wsBase.replace(/\/+$/, '')}/ws/chat/rooms/${encodeURIComponent(opts.roomId)}`;

  const socket: SocketHandle = openSocket({
    url,
    token: opts.token,
    wsFactory: opts.wsFactory,
    setTimeoutFn: opts.setTimeoutFn,
    clearTimeoutFn: opts.clearTimeoutFn,
    now: opts.now,
    log: opts.log,
    onState: opts.onState,
    onError: opts.onError,
    // The cursor is read at connect time, not at setup time: after a minute
    // in a tunnel this asks for what was missed, not for the whole room.
    greeting: () => ({ type: 'subscribe', after: opts.after() }),
    onFrame(type, data) {
      switch (type) {
        case 'message':
          opts.onMessage?.(data as unknown as RoomMessage);
          return;
        case 'agent_progress': {
          const agents = (data.agents as RoomAgentState[] | undefined) ?? [];
          opts.onProgress?.(agents);
          return;
        }
        case 'broadcast_done':
          opts.onIdle?.();
          return;
        case 'error':
          opts.onError?.(String(data.error ?? 'unknown error'));
          return;
        default:
      }
    },
  });

  return {
    resume: socket.resume,
    close: socket.close,
    state: socket.state,
  };
}
