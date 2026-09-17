/**
 * What the agent actually did — the ledger, not the conversation.
 *
 * The transcript answers "what did it say". This answers "what did it do to
 * my machine", which is a different question and the one that matters when
 * something is running unattended in a workspace: which files it touched and
 * by how many lines, which commands it ran and whether they worked, and which
 * calls failed.
 *
 * It is derived on the server from the session log, so it cannot claim
 * anything the log does not contain. Nothing here is editable; it is a record.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { agents, type ActivityEntry, type WorkspaceSummary } from '../server'

type T = (key: string, vars?: Record<string, string | number>) => string
type View = 'files' | 'commands' | 'log'

export function WorkPane({ sessionId, t }: { sessionId: string; t: T }): ReactNode {
  const [view, setView] = useState<View>('files')
  const [summary, setSummary] = useState<WorkspaceSummary | null>(null)
  const [entries, setEntries] = useState<ActivityEntry[]>([])
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [s, a] = await Promise.all([
        agents.summary(sessionId),
        agents.activity(sessionId, undefined, 200),
      ])
      setSummary(s)
      setEntries(a.entries)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [sessionId])

  useEffect(() => { void refresh() }, [refresh])
  // While a turn runs this is the only surface that changes; a stale ledger is
  // worse than no ledger, because it looks current.
  useEffect(() => {
    const timer = setInterval(() => { void refresh() }, 6_000)
    return () => clearInterval(timer)
  }, [refresh])

  return (
    <aside className="work-pane">
      <div className="work-tabs">
        {(['files', 'commands', 'log'] as View[]).map((v) => (
          <button key={v} type="button"
            className={`work-tab ${view === v ? 'active' : ''}`}
            onClick={() => setView(v)}>
            {t(`chat.ledger.${v}`)}
          </button>
        ))}
      </div>
      {error && <div className="side-error">{error}</div>}

      {view === 'files' && (
        <div className="work-body">
          {(summary?.files ?? []).map((file) => (
            <div key={file.path} className="work-row">
              <span className="work-path" title={file.path}>{file.path}</span>
              <span className="work-delta">
                {file.linesAdded > 0 && <span className="add">+{file.linesAdded}</span>}
                {file.linesRemoved > 0 && <span className="del">-{file.linesRemoved}</span>}
                {file.failed > 0 && <span className="err">!{file.failed}</span>}
              </span>
            </div>
          ))}
          {!summary?.files.length && <div className="work-empty">{t('chat.ledger.noFiles')}</div>}
        </div>
      )}

      {view === 'commands' && (
        <div className="work-body">
          {(summary?.commands ?? []).map((command) => (
            <div key={command.seq} className="work-row column">
              <code className={command.ok === false ? 'err' : ''}>$ {command.command}</code>
              {typeof command.durationMs === 'number' && (
                <span className="work-kind">{(command.durationMs / 1000).toFixed(1)}s</span>
              )}
            </div>
          ))}
          {!summary?.commands.length && <div className="work-empty">{t('chat.ledger.noCommands')}</div>}
        </div>
      )}

      {view === 'log' && (
        <div className="work-body">
          {entries.map((entry) => (
            <div key={entry.seq} className="work-row column">
              <span className="work-kind">
                {entry.role === 'trigger' ? t('chat.ledger.trigger') : entry.kind}
              </span>
              <span className="work-text">
                {entry.text ?? entry.command ?? entry.path ?? entry.detail ?? entry.tool ?? ''}
              </span>
            </div>
          ))}
          {entries.length === 0 && <div className="work-empty">{t('chat.ledger.noLog')}</div>}
        </div>
      )}
    </aside>
  )
}

export default WorkPane
