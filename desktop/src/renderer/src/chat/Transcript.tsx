/**
 * The conversation, as Dex renders one.
 *
 * Bubbles, because that is what a conversation is: what a person said on the
 * right in brand colour, what the agent said on the left under its mark.
 *
 * What the agent DID is a separate question from what it said, so it is not
 * in the bubble. A run of tool calls collapses to one pill — "작업 8단계 ·
 * 12.4초" — and opens into a card of colour-badged rows, each with its
 * duration and its own input and output. That way twenty calls between two
 * sentences cost one line of the conversation instead of twenty.
 *
 * Every row comes from the shared fold, so this file decides how a tool call
 * LOOKS and never what it was.
 */
import { useState, type ReactNode } from 'react'

import type { Message } from '../../../../../shared/chat/transcript'
import { Icon, KIND_ICON, toolKind } from './icons'
import Markdown from './markdown'

type T = (key: string, vars?: Record<string, string | number>) => string

/** `2026-09-17T21:37:02` → `21:37`. Anything unparseable shows nothing. */
function clock(ts?: string): string {
  if (!ts) return ''
  const at = new Date(ts)
  if (Number.isNaN(at.getTime())) return ''
  return at.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

function seconds(ms?: number): string {
  if (typeof ms !== 'number' || ms <= 0) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}초` : `${ms}ms`
}

function pretty(args?: string): string {
  if (!args) return ''
  try {
    return JSON.stringify(JSON.parse(args), null, 2)
  } catch {
    // A truncated preview is not valid JSON; the raw text is still the honest
    // content of the call.
    return args
  }
}

function ToolRow({ message, t }: { message: Message; t: T }): ReactNode {
  const [open, setOpen] = useState(false)
  const detail = pretty(message.args)
  const openable = Boolean(detail || message.result)
  const kind = toolKind(message.tool)
  const running = message.ok === null || message.ok === undefined
  const failed = message.ok === false
  const dur = seconds(message.durationMs)
  return (
    <div
      className={[
        'ptl-tool',
        `ptl-kind-${kind}`,
        running ? 'run' : '',
        failed ? 'err' : '',
        open ? 'open' : '',
      ].filter(Boolean).join(' ')}
    >
      <button type="button" className="ptl-tool-head" disabled={!openable}
        onClick={() => setOpen((v) => !v)}>
        <span className="ptl-ico">{KIND_ICON[kind]}</span>
        <span className="ptl-sum">
          <strong>{message.tool}</strong>
          {message.text ? `  ${message.text}` : ''}
        </span>
        {dur && <span className={`ptl-dur ${failed ? 'err' : (message.durationMs ?? 0) > 5000 ? 'slow' : ''}`}>{dur}</span>}
      </button>
      {open && (
        <div className="ptl-body">
          {detail && (
            <>
              <div className="ptl-label">{t('chat.tool.input')}</div>
              <pre>{detail}</pre>
            </>
          )}
          {message.result && (
            <>
              <div className="ptl-label">{t('chat.tool.output')}</div>
              <pre>{message.result}</pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

/** A run of tool calls, as one collapsible step. */
function Steps({ run, t }: { run: Message[]; t: T }): ReactNode {
  const live = run.some((m) => m.ok === null || m.ok === undefined)
  const failed = run.some((m) => m.ok === false)
  // Open while it is happening — that is when someone is watching — and
  // closed once it is done, when the answer is what matters.
  const [open, setOpen] = useState(live)
  const total = run.reduce((sum, m) => sum + (m.durationMs ?? 0), 0)
  return (
    <div className={`ptl ${live ? 'live' : ''} ${failed ? 'err' : ''}`}>
      <button type="button" className="ptl-head-toggle" onClick={() => setOpen((v) => !v)}>
        <span className="ptl-pulse">{live ? '' : failed ? Icon.alert : Icon.check}</span>
        <span className="ptl-head-label">
          {live ? t('chat.steps.running') : t('chat.steps.done', { n: run.length })}
        </span>
        <span className="ptl-head-sub">
          {live ? t('chat.steps.count', { n: run.length }) : seconds(total)}
        </span>
        <span className="ptl-chevron">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="ptl-tools">
          {run.map((message) => <ToolRow key={message.key} message={message} t={t} />)}
        </div>
      )}
    </div>
  )
}

function Row({ message, t }: { message: Message; t: T }): ReactNode {
  if (message.role === 'system') {
    // Nobody typed this: the agent woke on a schedule. In the flow, because
    // it is why the next answer exists; not a bubble, because no one said it.
    return <div className="trigger-row">{t('chat.selfStarted', { reason: message.text })}</div>
  }

  if (message.role === 'notice') {
    return (
      <div className="msg-row">
        <span className="msg-avatar assistant">G</span>
        <div className="msg-col">
          <div className="bubble assistant error">
            <div className="chat-error-head">{Icon.alert} {t('chat.failed')}</div>
            <pre className="chat-error-body">{message.text}</pre>
          </div>
        </div>
      </div>
    )
  }

  if (message.role === 'user') {
    return (
      <div className="msg-row user">
        <span className="msg-avatar user">{t('chat.you')}</span>
        <div className="msg-col">
          <div className={`bubble user ${message.pending ? 'pending' : ''}`}>{message.text}</div>
          {clock(message.ts) && <span className="msg-time">{clock(message.ts)}</span>}
        </div>
      </div>
    )
  }

  return (
    <div className="msg-row">
      <span className="msg-avatar assistant">G</span>
      <div className="msg-col">
        <div className="bubble assistant">
          <Markdown text={message.text} />
        </div>
        {clock(message.ts) && <span className="msg-time">{clock(message.ts)}</span>}
      </div>
    </div>
  )
}

/**
 * Consecutive tool calls become one step.
 *
 * A failed call produces two things in the fold: the call marked failed, and
 * a notice carrying its output — the phone needs the second because it shows
 * no output. Here the row already carries it, so that notice is dropped
 * rather than allowed to split the run in half and say the same thing twice.
 * Only that exact notice: anything else (a failed turn, an engine error) is
 * still a message of its own.
 */
function group(messages: Message[]): Message[][] {
  const out: Message[][] = []
  for (const message of messages) {
    const last = out[out.length - 1]
    const lastIsTools = last && last[0].role === 'activity'

    if (message.role === 'activity' && lastIsTools) {
      last.push(message)
      continue
    }
    if (message.role === 'notice' && lastIsTools) {
      const failed = last[last.length - 1]
      if (failed.ok === false && failed.result && message.text === failed.result) continue
    }
    out.push([message])
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
    return <div className="chat-empty">{t('chat.loading')}</div>
  }
  if (messages.length === 0) {
    return (
      <div className="chat-empty">
        <strong>{t('chat.empty.title')}</strong>
        {t('chat.empty.hint')}
      </div>
    )
  }
  return (
    <>
      {group(messages).map((run) =>
        run[0].role === 'activity' ? (
          <div className="msg-row" key={run[0].key}>
            <span className="msg-avatar assistant">G</span>
            <div className="msg-col" style={{ maxWidth: 'calc(100% - 44px)', width: '100%' }}>
              <Steps run={run} t={t} />
            </div>
          </div>
        ) : (
          <Row key={run[0].key} message={run[0]} t={t} />
        ),
      )}
      {running && (
        <div className="msg-row">
          <span className="msg-avatar assistant">G</span>
          <div className="msg-col">
            <div className="ptl live">
              <span className="ptl-head-toggle" style={{ cursor: 'default' }}>
                <span className="ptl-pulse" />
                <span className="ptl-head-label">{t('chat.working')}</span>
              </span>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export default Transcript
