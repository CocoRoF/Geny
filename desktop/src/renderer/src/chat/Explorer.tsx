/**
 * Every agent's workspace, in one tree.
 *
 * An agent that works on a server leaves its work there, and the only way to
 * see any of it was to read the transcript and believe it. Dex's shape, which
 * this follows: each agent is a root you can open, its folders open in place,
 * and a file opens as a tab you can leave open while you keep talking. The
 * first version showed only the session you happened to be chatting with —
 * which is exactly the thing you don't need, because that agent is telling
 * you what it wrote. The files you want to check are usually the OTHER
 * agent's.
 *
 * Two things about the endpoint decide how this is written, and getting
 * either wrong is what made the first version show `docs` twice and then say
 * "File not found" on everything it opened:
 *
 *  · `GET …/storage?scope=workspace` is RECURSIVE — one call returns every
 *    file at every depth, each path relative to `workspace/`. So this fetches
 *    once per agent and builds the tree itself; it never asks for a
 *    subdirectory.
 *  · `GET …/storage/{path}` is NOT scoped — it resolves from the session
 *    root. A path from the listing has to be read back with `workspace/` in
 *    front of it.
 *
 * Listings are fetched when an agent is first opened and kept, so opening a
 * folder costs nothing. The agent that is mid-turn refreshes on a timer,
 * which is the point: watching files appear as they are written.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { workspace, type AgentSummary, type StorageEntry } from '../server'
import { kindOf, NEEDS_BYTES } from './file-kind'
import { Icon } from './icons'

type T = (key: string, vars?: Record<string, string | number>) => string

export interface OpenedFile {
  /** Unique across agents: two of them can hold the same path. */
  key: string
  sessionId: string
  /** Workspace-relative, as the listing gives it. */
  path: string
  name: string
  /** Empty when the bytes are not text — the viewer fetches those itself. */
  content: string
  binary?: boolean
  size?: number
}

export const fileKey = (sessionId: string, path: string): string => `${sessionId}:${path}`

function size(bytes?: number | null): string {
  if (typeof bytes !== 'number') return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

interface Node {
  name: string
  path: string
  isDir: boolean
  size?: number | null
  children: Node[]
}

/**
 * The flat recursive listing → a tree.
 *
 * Directories are inferred from the paths as well as taken from the rows: a
 * listing can omit an intermediate directory, and a child whose parent is
 * missing would otherwise be invisible at every level.
 */
function buildTree(entries: StorageEntry[]): Node[] {
  const root: Node = { name: '', path: '', isDir: true, children: [] }

  const dirAt = (segments: string[]): Node => {
    let node = root
    let path = ''
    for (const segment of segments) {
      path = path ? `${path}/${segment}` : segment
      let next = node.children.find((c) => c.isDir && c.name === segment)
      if (!next) {
        next = { name: segment, path, isDir: true, children: [] }
        node.children.push(next)
      }
      node = next
    }
    return node
  }

  for (const entry of entries) {
    const path = (entry.path ?? '').replace(/^\/+/, '')
    if (!path) continue
    const segments = path.split('/')
    if (entry.is_dir) {
      dirAt(segments)
      continue
    }
    const parent = dirAt(segments.slice(0, -1))
    const name = segments[segments.length - 1]
    if (!parent.children.some((c) => !c.isDir && c.name === name)) {
      parent.children.push({ name, path, isDir: false, size: entry.size, children: [] })
    }
  }

  const sort = (node: Node): void => {
    node.children.sort((a, b) => (
      a.isDir === b.isDir ? a.name.localeCompare(b.name) : (a.isDir ? -1 : 1)
    ))
    node.children.forEach(sort)
  }
  sort(root)
  return root.children
}

interface Listing {
  entries: StorageEntry[]
  error?: string
  loading: boolean
}

export function Explorer({ sessions, sessionId, running, t, onOpen }: {
  /** Every agent, because the files worth checking are usually not the ones
   *  belonging to the agent you are talking to. */
  sessions: AgentSummary[]
  /** The one being talked to, opened by default. */
  sessionId: string | null
  /** A turn is in flight on it, so its tree is changing under us. */
  running: boolean
  t: T
  onOpen: (file: OpenedFile) => void
}): ReactNode {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [dirs, setDirs] = useState<Record<string, boolean>>({})
  const [listings, setListings] = useState<Record<string, Listing>>({})
  const [error, setError] = useState<string | null>(null)
  const loading = useRef<Set<string>>(new Set())

  const load = useCallback(async (sid: string): Promise<void> => {
    if (loading.current.has(sid)) return
    loading.current.add(sid)
    setListings((prev) => ({ ...prev, [sid]: { entries: prev[sid]?.entries ?? [], loading: true } }))
    try {
      const listed = await workspace.list(sid)
      setListings((prev) => ({ ...prev, [sid]: { entries: listed.files ?? [], loading: false } }))
    } catch (e) {
      setListings((prev) => ({
        ...prev,
        [sid]: { entries: prev[sid]?.entries ?? [], loading: false, error: (e as Error).message },
      }))
    } finally {
      loading.current.delete(sid)
    }
  }, [])

  // The agent being talked to is the one you are most likely to want, so it
  // opens itself — once. Collapsing it afterwards has to stick.
  const opened = useRef<string | null>(null)
  useEffect(() => {
    if (!sessionId || opened.current === sessionId) return
    opened.current = sessionId
    setOpen((prev) => ({ ...prev, [sessionId]: true }))
    void load(sessionId)
  }, [sessionId, load])

  // While a turn runs, its files are being written. Only that agent's tree is
  // re-read, and only while it is open — the others cannot be changing.
  useEffect(() => {
    if (!running || !sessionId || !open[sessionId]) return
    const timer = setInterval(() => { void load(sessionId) }, 4_000)
    return () => clearInterval(timer)
  }, [running, sessionId, open, load])

  const toggleAgent = (sid: string): void => {
    setOpen((prev) => {
      const next = !prev[sid]
      if (next && !listings[sid]) void load(sid)
      return { ...prev, [sid]: next }
    })
  }

  const openPath = async (sid: string, node: Node): Promise<void> => {
    const open = (content: string, binary: boolean, size?: number): void => {
      onOpen({
        key: fileKey(sid, node.path),
        sessionId: sid,
        path: node.path,
        name: node.name,
        content,
        binary,
        size: size ?? node.size ?? undefined,
      })
      setError(null)
    }
    // Anything that is not text is opened on its listed size alone — asking
    // the text reader for a 2 MB PNG only to be told it is not text is a
    // round trip that answers nothing.
    if (NEEDS_BYTES.has(kindOf(node.name))) {
      open('', true)
      return
    }
    try {
      const file = await workspace.read(sid, node.path)
      open(file.content, Boolean(file.binary), file.size)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const trees = useMemo(() => {
    const out: Record<string, Node[]> = {}
    for (const [sid, listing] of Object.entries(listings)) {
      out[sid] = buildTree(listing.entries)
    }
    return out
  }, [listings])

  const rows = (sid: string, nodes: Node[], depth: number): ReactNode[] =>
    nodes.flatMap((node) => {
      const key = fileKey(sid, node.path)
      const indent = { paddingLeft: 10 + depth * 13 }
      if (!node.isDir) {
        return [(
          <button key={key} type="button" className="explorer-row" style={indent}
            onClick={() => void openPath(sid, node)} title={node.path}>
            <span className="explorer-ico">{Icon.file}</span>
            <span className="explorer-name">{node.name}</span>
            <span className="explorer-size">{size(node.size)}</span>
          </button>
        )]
      }
      const isOpen = dirs[key]
      return [
        (
          <button key={key} type="button" className="explorer-row" style={indent}
            onClick={() => setDirs((prev) => ({ ...prev, [key]: !prev[key] }))}
            title={node.path}>
            <span className={`explorer-twisty ${isOpen ? 'open' : ''}`}>{Icon.chevron}</span>
            <span className="explorer-ico dir">{isOpen ? Icon.folderOpen : Icon.folder}</span>
            <span className="explorer-name">{node.name}</span>
          </button>
        ),
        ...(isOpen ? rows(sid, node.children, depth + 1) : []),
      ]
    })

  if (sessions.length === 0) {
    return <div className="side-empty">{t('explorer.noSession')}</div>
  }

  return (
    <div className="agent-list explorer">
      {error && <div className="side-error">{error}</div>}
      {sessions.map((session) => {
        const sid = session.session_id
        const isOpen = Boolean(open[sid])
        const listing = listings[sid]
        const tree = trees[sid] ?? []
        return (
          <div key={sid} className="explorer-agent">
            <button type="button"
              className={`explorer-row agent ${sid === sessionId ? 'current' : ''}`}
              onClick={() => toggleAgent(sid)}>
              <span className={`explorer-twisty ${isOpen ? 'open' : ''}`}>{Icon.chevron}</span>
              <span className="explorer-ico agent">{Icon.bot}</span>
              <span className="explorer-name">
                {session.session_name || sid.slice(0, 8)}
              </span>
              {/* Where the files are. Everything an agent writes lives on the
                  server, and saying so is the difference between "your files"
                  and "a machine's files you are looking at". */}
              <span className="explorer-badge">{t('explorer.onServer')}</span>
            </button>

            {isOpen && (
              <>
                {listing?.error && <div className="side-error">{listing.error}</div>}
                {!listing?.error && tree.length === 0 && (
                  <div className="explorer-note">
                    {listing?.loading ? t('explorer.loading') : t('explorer.empty')}
                  </div>
                )}
                {rows(sid, tree, 1)}
              </>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default Explorer
