/**
 * The agent's workspace, in the sidebar.
 *
 * An agent that works on a server leaves its work there, and the only way to
 * see any of it was to read the transcript and believe it.
 *
 * Two things about the endpoint decide how this is written, and getting
 * either wrong is what made the first version show `docs` twice and then say
 * "File not found" on everything it opened:
 *
 *  · `GET …/storage?scope=workspace` is RECURSIVE — one call returns every
 *    file at every depth, each path relative to `workspace/`. So this fetches
 *    once and builds the tree itself; it never asks for a subdirectory.
 *  · `GET …/storage/{path}` is NOT scoped — it resolves from the session
 *    root. A path from the listing has to be read back with `workspace/` in
 *    front of it.
 *
 * It refreshes while a turn is running, which is the point: watching files
 * appear as they are written.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { workspace, type StorageEntry } from '../server'
import { Icon } from './icons'

type T = (key: string, vars?: Record<string, string | number>) => string

export interface OpenedFile {
  /** Workspace-relative, as the listing gives it. */
  path: string
  name: string
  content: string
}

function size(bytes?: number | null): string {
  if (typeof bytes !== 'number') return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

interface Row {
  name: string
  path: string
  isDir: boolean
  size?: number | null
}

/**
 * The flat recursive listing → the immediate children of `prefix`.
 *
 * Directories are inferred from the paths as well as taken from the rows: a
 * listing can omit an intermediate directory, and a child whose parent is
 * missing would otherwise be invisible at every level.
 */
function childrenOf(entries: StorageEntry[], prefix: string): Row[] {
  const base = prefix ? `${prefix}/` : ''
  const dirs = new Map<string, Row>()
  const files: Row[] = []

  for (const entry of entries) {
    const path = entry.path.replace(/^\/+/, '')
    if (!path.startsWith(base)) continue
    const rest = path.slice(base.length)
    if (!rest) continue
    const cut = rest.indexOf('/')
    if (cut >= 0) {
      const name = rest.slice(0, cut)
      const dirPath = `${base}${name}`
      if (!dirs.has(dirPath)) dirs.set(dirPath, { name, path: dirPath, isDir: true })
      continue
    }
    if (entry.is_dir) {
      if (!dirs.has(path)) dirs.set(path, { name: rest, path, isDir: true })
    } else {
      files.push({ name: rest, path, isDir: false, size: entry.size })
    }
  }

  const byName = (a: Row, b: Row): number => a.name.localeCompare(b.name)
  return [...[...dirs.values()].sort(byName), ...files.sort(byName)]
}

export function Explorer({ sessionId, running, t, onOpen }: {
  sessionId: string | null
  /** A turn is in flight, so the tree is changing under us. */
  running: boolean
  t: T
  onOpen: (file: OpenedFile) => void
}): ReactNode {
  const [prefix, setPrefix] = useState('')
  const [entries, setEntries] = useState<StorageEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (!sessionId) return
    setBusy(true)
    try {
      const listed = await workspace.list(sessionId)
      setEntries(listed.files ?? [])
      setError(null)
    } catch (e) {
      setError((e as Error).message)
      setEntries([])
    } finally {
      setBusy(false)
    }
  }, [sessionId])

  useEffect(() => { setPrefix('') }, [sessionId])
  useEffect(() => { void load() }, [load])

  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => { void load() }, 4_000)
    return () => clearInterval(timer)
  }, [running, load])

  const rows = useMemo(() => childrenOf(entries, prefix), [entries, prefix])

  const open = async (row: Row): Promise<void> => {
    if (row.isDir) {
      setPrefix(row.path)
      return
    }
    if (!sessionId) return
    try {
      const file = await workspace.read(sessionId, row.path)
      onOpen({ path: row.path, name: row.name, content: file.content })
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const up = (): void => {
    const cut = prefix.lastIndexOf('/')
    setPrefix(cut > 0 ? prefix.slice(0, cut) : '')
  }

  if (!sessionId) {
    return <div className="side-empty">{t('explorer.noSession')}</div>
  }

  return (
    <>
      <div className="explorer-path">
        <button type="button" className="icon-btn" disabled={!prefix} onClick={up}
          title={t('explorer.up')}>↑</button>
        <span className="explorer-crumb" title={prefix || 'workspace'}>
          {prefix || 'workspace'}
        </span>
        <button type="button" className="icon-btn" onClick={() => void load()}
          title={t('chat.refresh')}>{Icon.refresh}</button>
      </div>

      <div className="agent-list">
        {error && <div className="side-error">{error}</div>}
        {!error && rows.length === 0 && (
          <div className="side-empty">{busy ? t('explorer.loading') : t('explorer.empty')}</div>
        )}
        {rows.map((row) => (
          <button key={row.path} type="button" className="explorer-row"
            onClick={() => void open(row)}>
            <span className={`explorer-ico ${row.isDir ? 'dir' : ''}`}>
              {row.isDir ? Icon.folder : Icon.file}
            </span>
            <span className="explorer-name">{row.name}</span>
            {!row.isDir && <span className="explorer-size">{size(row.size)}</span>}
          </button>
        ))}
      </div>
    </>
  )
}

export default Explorer
