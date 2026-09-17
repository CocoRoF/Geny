/**
 * The conversation, the way an agent's conversation actually reads.
 *
 * An agent's turn is not two bubbles. It is: the question, then twenty tool
 * calls, then the answer — and the tool calls are the part a person scans
 * rather than reads. So they render as one line each, in the flow, with the
 * verdict on the right, and open only when someone wants to know what was in
 * them. That is the shape the terminal has, and it is the shape because it is
 * the one that survives forty tool calls between two sentences.
 *
 * Every row comes from the shared fold, so this file decides how a tool call
 * LOOKS and never what it was.
 */
import { useState, type ReactNode } from 'react'

import type { Message } from '../../../../../shared/chat/transcript'
import Markdown from './markdown'

type T = (key: string, vars?: Record<string, string | number>) => string

function Dot({ ok }: { ok?: boolean | null }): ReactNode {
  const cls = ok === false ? 'is-err' : ok === true ? 'is-ok' : 'is-pending'
  return <span className={`gy-tool-dot ${cls}`} />
}

function pretty(args?: string): string {
  if (!args) return ''
  try {
    return JSON.stringify(JSON.parse(args), null, 2)
  } catch {
    return args
  }
}

function ToolRow({ message, t }: { message: Message; t: T }): ReactNode {
  const [open, setOpen] = useState(false)
  const detail = pretty(message.args)
  const openable = Boolean(detail || message.result)
  return (
    <div className={`gy-tool ${open ? 'is-open' : ''}`}>
      <button
        type="button"
        className="gy-tool-head"
        disabled={!openable}
        onClick={() => setOpen((v) => !v)}
      >
        <Dot ok={message.ok} />
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
      {messages.map((message) => {
        if (message.role === 'activity') {
          return <ToolRow key={message.key} message={message} t={t} />
        }
        if (message.role === 'system') {
          // Nobody typed this: the agent was woken on a schedule. It belongs
          // in the flow (it is why the next answer exists) but not as a
          // message, because no one said it.
          return (
            <div key={message.key} className="gy-selfstart">
              <span>{t('chat.selfStarted', { reason: message.text })}</span>
            </div>
          )
        }
        if (message.role === 'notice') {
          return (
            <div key={message.key} className="gy-notice">
              <pre>{message.text}</pre>
            </div>
          )
        }
        if (message.role === 'user') {
          return (
            <div key={message.key} className={`gy-turn gy-turn--user ${message.pending ? 'is-pending' : ''}`}>
              <div className="gy-turn-mark">›</div>
              <div className="gy-turn-body">{message.text}</div>
            </div>
          )
        }
        return (
          <div key={message.key} className="gy-turn gy-turn--agent">
            <div className="gy-turn-body">
              <Markdown text={message.text} />
            </div>
          </div>
        )
      })}
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
