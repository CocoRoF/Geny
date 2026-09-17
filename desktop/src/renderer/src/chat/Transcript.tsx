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

import type { ToolCall } from '../../../../../shared/chat/room'
import type { Message } from '../../../../../shared/chat/transcript'
import { describeTool, resultView, type ResultView } from '../../../../../shared/chat/tool-view'
import { Icon, KIND_ICON } from './icons'
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

/** A tool's result, drawn by its shape rather than dumped as text. */
function Result({ view }: { view: ResultView }): ReactNode {
  if (view.table) {
    return (
      <div className="ptl-table-wrap">
        <table className="ptl-table">
          <thead>
            <tr>{view.table.columns.map((c) => <th key={c}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {view.table.rows.map((row, i) => (
              <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>
            ))}
          </tbody>
        </table>
        {view.table.more > 0 && <div className="ptl-table-more">외 {view.table.more}건</div>}
      </div>
    )
  }
  if (view.title || view.fields.length || view.flags.length) {
    return (
      <div className="ptl-result">
        {view.title && <div className="ptl-result-title">{view.title}</div>}
        {(view.fields.length > 0 || view.flags.length > 0) && (
          <div className="ptl-result-meta">
            {view.fields.map(([k, v]) => (
              <span key={k}><i>{k}</i> {v}</span>
            ))}
            {view.flags.map(([k, v]) => (
              <span key={k} className={v ? 'yes' : 'no'}>{v ? '✓' : '✗'} {k}</span>
            ))}
          </div>
        )}
      </div>
    )
  }
  return view.line ? <div className="ptl-preview">{view.line}</div> : null
}

/**
 * One tool call.
 *
 * What it SAYS it did comes from the shared model, so the app and the web
 * page describe a call identically and neither recognises a vendor by name.
 * Under the summary sits the result in the shape it actually has — a table
 * for a list, a card for a named object, the first line otherwise — because
 * the useful half of a tool call is usually what came back.
 */
function ToolRow({ call, t }: { call: ToolCall; t: T }): ReactNode {
  const [open, setOpen] = useState(false)
  const { icon, text } = describeTool(call.name, call.input)
  const view = resultView(call.result)
  const detail = pretty(typeof call.input === 'string' ? call.input : JSON.stringify(call.input))
  const openable = Boolean(detail || call.result)
  const running = call.ok === null || call.ok === undefined
  const failed = call.ok === false
  const dur = seconds(call.durationMs)
  const slow = (call.durationMs ?? 0) > 5000
  return (
    <div
      className={[
        'ptl-tool', `ptl-kind-${icon}`,
        running ? 'run' : '', failed ? 'err' : '', open ? 'open' : '',
      ].filter(Boolean).join(' ')}
    >
      <button type="button" className="ptl-tool-head" disabled={!openable}
        onClick={() => setOpen((v) => !v)}>
        <span className="ptl-ico">{KIND_ICON[icon] ?? Icon.tool}</span>
        <span className="ptl-sum">
          {text}
          {view && <span className="ptl-sum-result"><Result view={view} /></span>}
        </span>
        {dur && (
          <span className={`ptl-dur ${failed ? 'err' : slow ? 'slow' : ''}`}>{dur}</span>
        )}
      </button>
      {open && (
        <div className="ptl-body">
          {detail && (
            <>
              <div className="ptl-label">{t('chat.tool.input')}</div>
              <pre>{detail}</pre>
            </>
          )}
          {call.result && (
            <>
              <div className="ptl-label">{t('chat.tool.output')}</div>
              <pre>{call.result}</pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * What the agent is doing, as Dex's process timeline.
 *
 * A pill while it is closed — 작업 과정 · 도구 4회 · 실패 1 · 2.9초 — and a rail
 * of numbered nodes when open, each carrying its own verdict with its tool
 * card beside it. It opens itself while a turn runs, because that is when
 * someone is watching, and closes when the answer arrives.
 *
 * The calls come from the ROOM's progress feed, which is the same source the
 * web page reads. That is deliberate: a timeline built from somewhere else
 * would disagree with the web about what just happened.
 */
function Steps({ calls, live, t }: { calls: ToolCall[]; live: boolean; t: T }): ReactNode {
  const [manual, setManual] = useState<boolean | null>(null)
  const open = manual ?? live
  const failed = calls.filter((c) => c.ok === false).length
  const total = calls.reduce((sum, c) => sum + (c.durationMs ?? 0), 0)

  const summary = [
    t('chat.steps.tools', { n: calls.length }),
    failed ? t('chat.steps.failed', { n: failed }) : '',
    seconds(total),
  ].filter(Boolean).join(' · ')

  return (
    <div className={`ptl ${live ? 'live' : 'done'} ${failed ? 'err' : ''}`}>
      <button type="button" className="ptl-head-toggle" aria-expanded={open}
        onClick={() => setManual(!open)}>
        <span className="ptl-pulse">{live ? '' : failed ? Icon.alert : Icon.check}</span>
        <span className="ptl-head-label">
          {live ? t('chat.steps.running') : t('chat.steps.title')}
        </span>
        <span className="ptl-head-sub">{summary}</span>
        <span className="ptl-chevron" aria-hidden>{open ? '▾' : '▸'}</span>
      </button>

      {live && <div className="ptl-progress" aria-hidden />}

      {open && (
        <div className="ptl-steps">
          {calls.map((call, index) => {
            const running = call.ok === null || call.ok === undefined
            const phase = running ? 'run' : call.ok === false ? 'err' : 'ok'
            return (
              <div className={`ptl-step ${phase}`} key={call.key}>
                <span className="ptl-node">
                  {phase === 'ok' ? Icon.check : phase === 'err' ? '!' : index + 1}
                </span>
                <div className="ptl-title">{call.name}</div>
                <div className="ptl-tools">
                  <ToolRow call={call} t={t} />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function Row({ message, t }: { message: Message; t: T }): ReactNode {
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

export function Transcript({
  messages, calls, running, loading, t,
}: {
  messages: Message[]
  calls: ToolCall[]
  running: boolean
  loading: boolean
  t: T
}): ReactNode {
  if (loading && messages.length === 0) {
    return <div className="chat-empty">{t('chat.loading')}</div>
  }
  if (messages.length === 0 && calls.length === 0) {
    return (
      <div className="chat-empty">
        <strong>{t('chat.empty.title')}</strong>
        {t('chat.empty.hint')}
      </div>
    )
  }
  return (
    <>
      {messages.map((message) => <Row key={message.key} message={message} t={t} />)}
      {calls.length > 0 && (
        <div className="msg-row">
          <span className="msg-avatar assistant">G</span>
          <div className="msg-col" style={{ maxWidth: 'calc(100% - 44px)', width: '100%' }}>
            <Steps calls={calls} live={running} t={t} />
          </div>
        </div>
      )}
      {running && calls.length === 0 && (
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
