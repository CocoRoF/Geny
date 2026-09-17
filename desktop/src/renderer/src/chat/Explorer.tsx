/**
 * The agent's workspace, in the sidebar.
 *
 * An agent that works on a server leaves its work there, and until now the
 * only way to see any of it was to read the transcript and believe it. This
 * is the files themselves: the tree the agent actually wrote into, and the
 * contents of whichever one you open.
 *
 * Rooted at `workspace/`, not at the session directory. The rest of that
 * directory is the engine's own state — the memory vault, the transcripts,
 * the database — which is neither the agent's work nor anybody's business
 * here.
 *
 * It refreshes on a timer while a turn is running, because that is the whole
 * point: watching files appear as they are written.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { workspace, type StorageEntry } from '../server'
import { Icon } from './icons'

type T = (key: string, vars?: Record<string, string | number>) => string

function size(bytes?: number | null): string {
  if (typeof bytes !== 'number') return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

/** Directories first, then by name — the order every file tree uses. */
function ordered(entries: StorageEntry[]): StorageEntry[] {
  return [...entries].sort((a, b) =>
    a.is_dir === b.is_dir ? a.name.localeCompare(b.name) : a.is_dir ? -1 : 1)
}

export function Explorer({ sessionId, running, t, onOpen }: {
  sessionId: string | null
  /** A turn is in flight, so the tree is changing under us. */
  running: boolean
  t: T
  onOpen: (file: { path: string; name: string; content: string }) => void
}): ReactNode {
  const [path, setPath] = useState('')
  const [entries, setEntries] = useState<StorageEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async (next: string) => {
    if (!sessionId) return
    setBusy(true)
    try {
      const listed = await workspace.list(sessionId, next)
      setEntries(listed.files ?? [])
      setError(null)
    } catch (e) {
      setError((e as Error).message)
      setEntries([])
    } finally {
      setBusy(false)
    }
  }, [sessionId])

  useEffect(() => { setPath('') }, [sessionId])
  useEffect(() => { void load(path) }, [load, path])

  // While a turn runs the tree is being written into; that is the one time
  // this view is worth following rather than opening.
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => { void load(path) }, 4_000)
    return () => clearInterval(timer)
  }, [running, load, path])

  const open = async (entry: StorageEntry): Promise<void> => {
    if (entry.is_dir) {
      setPath(entry.path)
      return
    }
    if (!sessionId) return
    try {
      // The listing paths are relative to the session root, which is what the
      // read endpoint wants — passing the workspace-relative name would miss.
      const file = await workspace.read(sessionId, entry.path)
      onOpen({ path: entry.path, name: entry.name, content: file.content })
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const up = (): void => {
    const cut = path.lastIndexOf('/')
    setPath(cut > 0 ? path.slice(0, cut) : '')
  }

  if (!sessionId) {
    return <div className="side-empty">{t('explorer.noSession')}</div>
  }

  return (
    <>
      <div className="explorer-path">
        <button type="button" className="icon-btn" disabled={!path} onClick={up}
          title={t('explorer.up')}>↑</button>
        <span className="explorer-crumb" title={path || 'workspace'}>
          {path || 'workspace'}
        </span>
        <button type="button" className="icon-btn" onClick={() => void load(path)}
          title={t('chat.refresh')}>{Icon.refresh}</button>
      </div>

      <div className="agent-list">
        {error && <div className="side-error">{error}</div>}
        {!error && entries.length === 0 && (
          <div className="side-empty">{busy ? t('explorer.loading') : t('explorer.empty')}</div>
        )}
        {ordered(entries).map((entry) => (
          <button key={entry.path} type="button" className="explorer-row"
            onClick={() => void open(entry)}>
            <span className={`explorer-ico ${entry.is_dir ? 'dir' : ''}`}>
              {entry.is_dir ? Icon.folder : Icon.file}
            </span>
            <span className="explorer-name">{entry.name}</span>
            {!entry.is_dir && <span className="explorer-size">{size(entry.size)}</span>}
          </button>
        ))}
      </div>
    </>
  )
}

export default Explorer
