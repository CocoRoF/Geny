/**
 * The conversation, the way an agent's conversation actually reads.
 *
 * An agent's turn is not two bubbles. It is: the question, then twenty tool
 * calls, then the answer — and the tool calls are the part a person scans
 * rather than reads. So they render one line each, in the flow, joined by a
 * rail so a run of them reads as a single sequence instead of twenty
 * interruptions; the verdict sits on the rail and the cost at the right edge.
 * They open only when someone wants to know what was in them.
 *
 * What a person wrote gets a surface, because finding it again is the most
 * common reason anyone scrolls back. What the model wrote gets none: it is
 * the page.
 *
 * Every row comes from the shared fold, so this file decides how a tool call
 * LOOKS and never what it was.
 */
import { Fragment, useState, type ReactNode } from 'react'

import type { Message } from '../../../../../shared/chat/transcript'
import Markdown from './markdown'

type T = (key: string, vars?: Record<string, string | number>) => string

/** `2026-09-17T21:37:02` → `21:37`. Anything unparseable shows nothing.
 *  Always 24h: a timestamp beside a message is glanced at, and "오후 09:37"
 *  is three words where two digits would do. */
function clock(ts?: string): string {
  if (!ts) return ''
  const at = new Date(ts)
  if (Number.isNaN(at.getTime())) return ''
  return at.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

function pretty(args?: string): string {
  if (!args) return ''
  try {
    return JSON.stringify(JSON.parse(args), null, 2)
  } catch {
    // A truncated preview is not valid JSON; showing it raw beats showing
    // nothing, and it is still the honest content of the call.
    return args
  }
}

function ToolRow({ message, t }: { message: Message; t: T }): ReactNode {
  const [open, setOpen] = useState(false)
  const detail = pretty(message.args)
  const openable = Boolean(detail || message.result)
  const tone = message.ok === false ? 'is-err' : message.ok === true ? 'is-ok' : 'is-pending'
  return (
    <div className="gy-tool">
      <button
        type="button"
        className="gy-tool-head"
        disabled={!openable}
        onClick={() => setOpen((v) => !v)}
      >
        <span className={`gy-tool-dot ${tone}`} />
        <span className="gy-tool-name">{message.tool}</span>
        <span className="gy-tool-text">{message.text}</span>
        {typeof message.durationMs === 'number' && message.durationMs > 0 && (
          <span className="gy-tool-ms">{(message.durationMs / 1000).toFixed(1)}s</span>
        )}
        {openable && <span className="gy-tool-caret">{open ? '⌃' : '⌄'}</span>}
      </button>
      {open && (
        <div className="gy-tool-body">
          {detail && (
            <>
              <div className="gy-tool-label">{t('chat.tool.input')}</div>
              <pre>{detail}</pre>
            </>
          )}
          {message.result && (
            <>
              <div className="gy-tool-label">{t('chat.tool.output')}</div>
              <pre>{message.result}</pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function Row({ message, t }: { message: Message; t: T }): ReactNode {
  if (message.role === 'system') {
    // Nobody typed this: the agent was woken on a schedule. It belongs in the
    // flow (it is why the next answer exists) but not as a message, because
    // no one said it.
    return (
      <div className="gy-selfstart">
        <span>{t('chat.selfStarted', { reason: message.text })}</span>
      </div>
    )
  }

  if (message.role === 'notice') {
    return (
      <div className="gy-notice">
        <div className="gy-notice-h">{t('chat.failed')}</div>
        <pre>{message.text}</pre>
      </div>
    )
  }

  if (message.role === 'user') {
    return (
      <article className={`gy-turn gy-turn--user ${message.pending ? 'is-pending' : ''}`}>
        <div className="gy-turn-meta">
          <span className="gy-turn-who">{t('chat.you')}</span>
          {clock(message.ts) && <time className="gy-turn-time">{clock(message.ts)}</time>}
        </div>
        <div className="gy-turn-body">{message.text}</div>
      </article>
    )
  }

  return (
    <article className="gy-turn gy-turn--agent">
      <div className="gy-turn-meta">
        <span className="gy-turn-avatar">G</span>
        <span className="gy-turn-who">Geny</span>
        {clock(message.ts) && <time className="gy-turn-time">{clock(message.ts)}</time>}
      </div>
      <div className="gy-turn-body">
        <Markdown text={message.text} />
      </div>
    </article>
  )
}

/**
 * Consecutive tool calls become one group, so the rail behind them is
 * continuous. Splitting them per-row would draw twenty two-pixel stubs.
 */
function group(messages: Message[]): Message[][] {
  const out: Message[][] = []
  for (const message of messages) {
    const last = out[out.length - 1]
    const isTool = message.role === 'activity'
    const lastIsTool = last && last[0].role === 'activity'
    if (isTool && lastIsTool) last.push(message)
    else out.push([message])
  }
  return out
}

export function Transcript({
  messages, running, loading, t,
}: {
  messages: Message[]
  running: boolean
  loading: boolean
  t: T
}): ReactNode {
  if (loading && messages.length === 0) {
    return <div className="gy-chat-empty">{t('chat.loading')}</div>
  }
  if (messages.length === 0) {
    return (
      <div className="gy-chat-empty">
        <p className="gy-chat-empty-title">{t('chat.empty.title')}</p>
        <p>{t('chat.empty.hint')}</p>
      </div>
    )
  }
  return (
    <>
      {group(messages).map((run) =>
        run[0].role === 'activity' ? (
          <div className="gy-steps" key={run[0].key}>
            {run.map((message) => <ToolRow key={message.key} message={message} t={t} />)}
          </div>
        ) : (
          <Fragment key={run[0].key}>
            <Row message={run[0]} t={t} />
          </Fragment>
        ),
      )}
      {running && (
        <div className="gy-working">
          <span className="gy-working-dot" />
          {t('chat.working')}
        </div>
      )}
    </>
  )
}

export default Transcript
