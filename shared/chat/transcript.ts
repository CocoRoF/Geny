/**
 * Log entries → a conversation.
 *
 * The execute socket streams the session's log, not a chat. The log is the
 * honest record (it is what the server actually wrote), and everything the
 * phone shows is folded out of it here — so a message on the phone can never
 * claim something the server did not log.
 *
 * Three kinds reach the screen:
 *
 * · `user` / `assistant` — the turn itself.
 * · `activity` — a tool the agent used, one line. Collapsed by default,
 *   because on a phone the answer is what matters and forty tool lines
 *   between two sentences is not a conversation.
 * · `notice` — an error worth interrupting for.
 *
 * Folding is INCREMENTAL and idempotent: the same entry arriving twice (a
 * reconnect replays the turn from its start) must not produce a second
 * bubble. Entries carry no id, so identity is (level, timestamp, message) —
 * enough in practice, and a duplicate bubble is a worse failure than a
 * merged one.
 *
 * Pure — no React, no platform. Tested under `node:test`.
 */

export type MessageRole =
  | 'user'
  | 'assistant'
  | 'activity'
  | 'notice'
  | 'system'
  /**
   * The answer being typed, before the tools it leads into.
   *
   * The engine streams the model's text as it arrives, and in an agent turn
   * that text comes in bursts: a sentence saying what it is about to do, then
   * the tool calls that do it, then the next sentence. Held here until a tool
   * claims it as that step's title — which is what makes the timeline read
   * like a plan rather than a list of commands.
   *
   * Never rendered on its own. A renderer that meets one skips it: it is a
   * buffer, and the turn's final answer arrives separately as `assistant`.
   */
  | 'draft';

export interface Message {
  key: string;
  role: MessageRole;
  text: string;
  ts?: string;
  /** activity only: what it did, and whether it worked. */
  tool?: string;
  ok?: boolean | null;
  /**
   * activity only, and only useful where there is room to open it: the call's
   * own record. The phone shows the one line above and nothing else; the
   * desktop expands the row. The fold is shared, so both read the same fields
   * rather than each deciding separately what a tool call was.
   */
  toolId?: string;
  args?: string;
  result?: string;
  durationMs?: number;
  /** assistant only: the mood tag the answer carried, if any. */
  mood?: string;
  /** activity only: what the agent said it was doing when it called this. */
  step?: string;
  /**
   * `system` only: what woke the agent, when nobody typed anything. Kept
   * short — the trigger's full text is prompt engineering, not conversation.
   */
  /**
   * Shown before the server confirmed it — the user's own message, echoed
   * locally so the app answers the keyboard instantly. The server logs the
   * same message a moment later with its own timestamp; without this flag the
   * two look like different messages and every turn shows the question twice.
   */
  pending?: boolean;
  /** Files that came with the message — what the user attached, or what the
   *  agent delivered. The web has always drawn these; a surface that ignores
   *  them shows a file-only message as nothing at all. */
  attachments?: MessageAttachment[];
  /** assistant only: the answer with its emotion cues still inline
   *  (`[joy:0.6] 좋아!`) — what a voice reads it with. `text` has them removed. */
  spoken?: string;
}

/** A file on a message, as the room stores it (see backend `BroadcastAttachment`). */
export interface MessageAttachment {
  /** image | audio | file */
  kind?: string;
  name?: string;
  mime_type?: string;
  size?: number;
  attachment_id?: string;
  /** `/static/uploads/...` (served without auth) or an `/api/...` path. */
  url?: string;
}

export interface LogLike {
  timestamp?: string;
  level?: string;
  message?: string;
  metadata?: Record<string, unknown> | string;
}

function meta(entry: LogLike): Record<string, unknown> {
  const raw = entry.metadata;
  if (raw && typeof raw === 'object') return raw as Record<string, unknown>;
  if (typeof raw === 'string' && raw) {
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {};
    } catch {
      return {};
    }
  }
  return {};
}

/**
 * The server writes the user's message as `PROMPT: <text>`. That prefix is
 * the log's, not the user's — and while it was carried through, the echo
 * never matched the message already on screen, so every single thing anyone
 * sent appeared twice: once pending, once confirmed.
 */
export function promptText(message: unknown): string {
  return String(message ?? '').replace(/^PROMPT:\s*/, '');
}

/**
 * The log's own words for "the turn finished". Like ``PROMPT:`` these belong
 * to the log line and not to what was said — left on, the answer on screen
 * reads ``SUCCESS: Error: CLI exited with code 1``, which is both prefixes
 * lying at once.
 */
export function answerText(message: unknown): string {
  return String(message ?? '').replace(/^(SUCCESS|FAILED):\s*/, '');
}

/**
 * The agent looked and decided there was nothing worth saying.
 *
 * `[SILENT]` is a contract, not a word: `service/hooks_runtime/delivery.py`
 * skips delivery entirely when an answer starts with it. A screen that shows
 * it anyway fills a conversation with bubbles reading "[SILENT]" — which is
 * the opposite of what the tag asked for.
 */
const SILENT = /^\s*\[SILENT\]/i;

/**
 * `[calm:0.4]`, `[curious]` — the mood the avatar should wear while it
 * speaks. A direction to the renderer, not something anybody said, so it
 * comes off the front of the line and is carried beside it.
 */
const MOOD = /^\s*\[([a-z_]+)(?::\s*(-?[0-9]+(?:\.[0-9]+)?))?\]\s*/i;

/**
 * The same direction, dropped mid-sentence — which the model does, often.
 *
 * Only the form that carries a numeric strength is stripped away from the
 * start of a message, because that form cannot be anything else. A bare
 * `[something]` in the middle of a line is far more likely to be prose, a
 * footnote marker or a markdown link, and eating it would be the worse bug.
 * This mirrors the server's rule in `service/utils/text_sanitizer.py`, which
 * is what makes the two agree on what a person is meant to read.
 */
const INLINE_MOOD = /\[\s*[a-z][a-z_]{1,19}\s*:\s*-?[0-9]+(?:\.[0-9]+)?\s*\][^\S\n]*/gi;

export interface Spoken {
  text: string;
  mood?: string;
  silent: boolean;
}

/** Split an answer into what was said and how it was meant to sound. */
export function spoken(message: unknown): Spoken {
  let text = answerText(message);
  let mood: string | undefined;
  const tag = MOOD.exec(text);
  if (tag) {
    mood = tag[1].toLowerCase();
    text = text.slice(tag[0].length);
  }
  if (SILENT.test(text)) return { text: '', mood, silent: true };
  text = text.replace(INLINE_MOOD, '');
  return { text: text.trim(), mood, silent: false };
}

/** A turn the agent started by itself, not one anybody asked for. */
const TRIGGER = /^\[(THINKING_TRIGGER|autonomous_signal)[:\]]/;

function keyOf(entry: LogLike, index: number): string {
  return `${entry.level ?? '?'}:${entry.timestamp ?? index}:${(entry.message ?? '').slice(0, 48)}`;
}

/** One line describing a tool call, short enough for a phone. */
export function describeTool(entry: LogLike): { tool: string; text: string } {
  const m = meta(entry);
  const tool = String(m.tool_name ?? 'tool');
  const change = m.file_changes as Record<string, unknown> | undefined;
  const command = m.command_data as Record<string, unknown> | undefined;
  const read = m.file_read as Record<string, unknown> | undefined;
  if (change?.file_path) {
    const added = Number(change.lines_added ?? 0);
    const removed = Number(change.lines_removed ?? 0);
    const delta = [added ? `+${added}` : '', removed ? `-${removed}` : ''].filter(Boolean).join(' ');
    return { tool, text: `${change.operation ?? 'write'} ${change.file_path}${delta ? `  ${delta}` : ''}` };
  }
  if (command?.command) return { tool, text: `$ ${command.command}` };
  if (read?.file_path) return { tool, text: `read ${read.file_path}` };
  return { tool, text: String(m.detail ?? tool) };
}

/**
 * Fold one entry into the conversation.
 *
 * Returns the list to render. The input list is never mutated — the caller
 * holds it in state and replaces it, so React sees a new array exactly when
 * something changed and not otherwise.
 */
export function foldEntry(messages: Message[], entry: LogLike, index = 0): Message[] {
  // eslint-disable-next-line no-param-reassign -- the RESPONSE branch drops a trailing draft
  const level = String(entry.level ?? '');
  const key = keyOf(entry, index);
  if (messages.some((m) => m.key === key)) return messages;  // replayed

  const m = meta(entry);
  const ts = entry.timestamp;

  if (level === 'COMMAND') {
    const text = promptText(entry.message);

    // Not everything the agent is given was typed by someone: a scheduled
    // thought arrives down the same channel. It is not a message — nobody
    // said it — and it is not worth a rule across the conversation either.
    // What the agent then SAID is the whole of what belongs on screen; that
    // the clock asked rather than a person is in the ledger, which is where
    // a record belongs.
    if (TRIGGER.test(text)) return messages;

    // The server's echo of a message this screen already drew. Adopt the
    // server's identity rather than appending a twin — and match only against
    // a PENDING one, so a user who really does send the same line twice gets
    // two bubbles.
    const pendingIndex = messages.findIndex((m) => m.role === 'user' && m.pending && m.text === text);
    if (pendingIndex >= 0) {
      const next = messages.slice();
      next[pendingIndex] = { key, role: 'user', text, ts };
      return next;
    }
    return [...messages, { key, role: 'user', text, ts }];
  }
  if (level === 'RESPONSE') {
    // Whatever was mid-sentence is finished by the answer itself.
    const tail = messages[messages.length - 1];
    if (tail && tail.role === 'draft') messages = messages.slice(0, -1);
    // The log knows whether the turn succeeded; a failed one is not something
    // the agent said, it is something that went wrong. `success` is written
    // by the server, so believe it over the prefix when both are present.
    const failed = m.success === false || /^FAILED:/.test(String(entry.message ?? ''));
    if (failed) {
      return [...messages, { key, role: 'notice', text: answerText(entry.message), ts }];
    }
    const said = spoken(entry.message);
    // Silence is an answer the agent asked us not to deliver. Nothing on
    // screen is the correct rendering of it.
    if (said.silent || !said.text) return messages;
    return [...messages, { key, role: 'assistant', text: said.text, ts, mood: said.mood }];
  }
  // The model's text as it arrives. It is a buffer, not a message: the tool
  // that follows takes it as its step title, and if none does, the turn's
  // final answer carries the same words anyway.
  if (level === 'STREAM' && m.type === 'text_delta') {
    const delta = String(entry.message ?? '');
    if (!delta) return messages;
    const tail = messages[messages.length - 1];
    if (tail && tail.role === 'draft') {
      const next = messages.slice();
      next[next.length - 1] = { ...tail, text: tail.text + delta };
      return next;
    }
    return [...messages, { key, role: 'draft', text: delta, ts }];
  }

  if (level === 'TOOL') {
    const { tool, text } = describeTool(entry);
    const args = typeof m.input_preview === 'string' ? m.input_preview : undefined;
    const toolId = typeof m.tool_id === 'string' ? m.tool_id : undefined;
    // A draft in front of a tool call is what the agent said it was about to
    // do. It becomes this step's title and stops being a message.
    const tail = messages[messages.length - 1];
    const rest = tail && tail.role === 'draft' ? messages.slice(0, -1) : messages;
    const step = tail && tail.role === 'draft' ? tail.text.trim() : undefined;
    return [...rest, { key, role: 'activity', text, tool, ts, ok: null, args, toolId, step }];
  }
  if (level === 'TOOL_RES') {
    // The verdict belongs to the call that is already on screen: "ran a
    // command" and "ran a command that failed" are different claims, and the
    // second one should not arrive as a separate line.
    const toolId = typeof m.tool_id === 'string' ? m.tool_id : undefined;
    const failed = Boolean(m.is_error);
    const preview = typeof m.result_preview === 'string' ? m.result_preview : undefined;
    const durationMs = typeof m.duration_ms === 'number' ? m.duration_ms : undefined;
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const candidate = messages[i];
      if (candidate.role !== 'activity') continue;
      // The id is the real answer to "which call is this the result of".
      // Falling back to the name + "still open" is what the phone had, and it
      // is right whenever two calls to the same tool are not in flight at once.
      const sameCall = toolId && candidate.toolId
        ? candidate.toolId === toolId
        : candidate.ok === null && candidate.tool === String(m.tool_name ?? candidate.tool);
      if (!sameCall) continue;
      const next = messages.slice();
      next[i] = { ...candidate, ok: !failed, result: preview, durationMs };
      if (failed) {
        next.splice(i + 1, 0, {
          key: `${key}:err`,
          role: 'notice',
          text: String(m.result_preview ?? '실패했습니다'),
          ts,
        });
      }
      return next;
    }
    if (failed) {
      return [...messages, { key, role: 'notice', text: String(m.result_preview ?? '실패했습니다'), ts }];
    }
    return messages;
  }
  if (level === 'ERROR') {
    return [...messages, { key, role: 'notice', text: String(entry.message ?? '오류'), ts }];
  }
  // Everything else is engine detail. Not dropped because it is unimportant —
  // dropped because it answers a question this screen is not asking, and the
  // full record is a tap away in the web UI.
  return messages;
}

/** The user's message, on screen before the server has heard it. */
export function pendingUserMessage(text: string, attachments?: MessageAttachment[]): Message {
  const message: Message = {
    key: `pending:${Date.now()}:${text.slice(0, 48)}`, role: 'user', text, pending: true,
  };
  if (attachments && attachments.length) message.attachments = attachments;
  return message;
}

export function foldAll(entries: LogLike[]): Message[] {
  return entries.reduce<Message[]>((acc, entry, index) => foldEntry(acc, entry, index), []);
}

/** The turn's text so far — what a phone shows while the answer streams. */
export function latestAssistantText(messages: Message[]): string {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === 'assistant') return messages[i].text;
  }
  return '';
}
