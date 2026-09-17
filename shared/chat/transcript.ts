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

export type MessageRole = 'user' | 'assistant' | 'activity' | 'notice';

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
  /**
   * Shown before the server confirmed it — the user's own message, echoed
   * locally so the app answers the keyboard instantly. The server logs the
   * same message a moment later with its own timestamp; without this flag the
   * two look like different messages and every turn shows the question twice.
   */
  pending?: boolean;
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
  const level = String(entry.level ?? '');
  const key = keyOf(entry, index);
  if (messages.some((m) => m.key === key)) return messages;  // replayed

  const m = meta(entry);
  const ts = entry.timestamp;

  if (level === 'COMMAND') {
    const text = String(entry.message ?? '');
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
    return [...messages, { key, role: 'assistant', text: String(entry.message ?? ''), ts }];
  }
  if (level === 'TOOL') {
    const { tool, text } = describeTool(entry);
    const args = typeof m.input_preview === 'string' ? m.input_preview : undefined;
    const toolId = typeof m.tool_id === 'string' ? m.tool_id : undefined;
    return [...messages, { key, role: 'activity', text, tool, ts, ok: null, args, toolId }];
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
export function pendingUserMessage(text: string): Message {
  return { key: `pending:${Date.now()}:${text.slice(0, 48)}`, role: 'user', text, pending: true };
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
