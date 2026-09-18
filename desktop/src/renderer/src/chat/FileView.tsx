/**
 * A file the agent wrote, rendered as what it is.
 *
 * The rule: an agent's file is worth opening only if opening it tells you
 * something. A PNG has to be the picture, a PDF has to be the document, a
 * spreadsheet has to be the sheet, and source has to be readable — coloured,
 * numbered, and not wrapped unless you ask. Everything that is none of those
 * is still owed an honest answer about what it is, which is why a zip says
 * "archive, 4.1 MB" instead of a screen of mojibake.
 *
 * Three routes to the bytes, and the file's kind picks one:
 *
 *  · text   — the JSON reader (`workspace.read`), already decoded
 *  · bytes  — `workspace.rawWorkspace`, a blob URL for <img>/<video>/<embed>
 *  · pages  — `workspace.docPreview`, the server rendering pptx/docx/xlsx
 *             into SVG slides or PNG pages, cached on the source's mtime
 *
 * Blob URLs are revoked when the tab closes or the file changes; forgetting
 * that in a long session is how a chat window ends up holding a hundred
 * megabytes of images it is no longer showing.
 */
import hljs from 'highlight.js/lib/common'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { workspace } from '../server'
import { DRAWS_BYTES, kindOf, languageOf, type FileKind } from './file-kind'
import { Icon } from './icons'
import Markdown from './markdown'

type T = (key: string, vars?: Record<string, string | number>) => string

export interface FileViewProps {
  sessionId: string
  /** Workspace-relative. */
  path: string
  name: string
  content: string
  binary?: boolean
  /** The whole file's size, even when only its head arrived. */
  size?: number
  /** The server sent the head of a large file, not all of it. */
  truncated?: boolean
  t: T
}

/**
 * How many lines are drawn.
 *
 * One DOM node a line is what makes the numbers line up and the highlighting
 * land, and it is also what makes a 200,000-line log freeze the window for
 * half a minute. Nobody reads past this; the banner says what is being held
 * back so nobody wonders.
 */
const MAX_LINES = 20_000

function bytes(n?: number): string {
  if (typeof n !== 'number') return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`
  return `${(n / 1024 ** 3).toFixed(2)} GB`
}

/** A row per line, split on the delimiter the extension implies. Quoted
 *  fields are respected; a stray quote is shown rather than guessed at. */
function parseTable(content: string, tsv: boolean): string[][] {
  const delim = tsv ? '\t' : ','
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  for (let i = 0; i < content.length; i += 1) {
    const c = content[i]
    if (quoted) {
      if (c === '"' && content[i + 1] === '"') { cell += '"'; i += 1 }
      else if (c === '"') quoted = false
      else cell += c
      continue
    }
    if (c === '"') { quoted = true; continue }
    if (c === delim) { row.push(cell); cell = ''; continue }
    if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; continue }
    if (c !== '\r') cell += c
  }
  if (cell || row.length) { row.push(cell); rows.push(row) }
  return rows
}

/** Highlighted source, one <div> a line so the numbers line up. */
function Code({ text, language, wrap }: {
  text: string
  language: string
  wrap: boolean
}): ReactNode {
  const html = useMemo(() => {
    try {
      return language && hljs.getLanguage(language)
        ? hljs.highlight(text, { language, ignoreIllegals: true }).value
        : hljs.highlightAuto(text).value
    } catch {
      // Highlighting is decoration. A file that defeats it is still a file.
      return null
    }
  }, [text, language])

  const lines = useMemo(() => (html ?? '').split('\n'), [html])
  const plain = useMemo(() => text.split('\n'), [text])

  return (
    <div className={`fv-body fv-code hljs ${wrap ? 'wrap' : ''}`}>
      {(html === null ? plain : lines).map((line, i) => (
        <div className="fv-line" key={i}>
          <span className="fv-ln">{i + 1}</span>
          {html === null
            ? <span className="fv-text">{line || ' '}</span>
            : (
              // The only HTML in this app, and it is the highlighter's own
              // output over text it escaped itself — never the file's bytes.
              <span className="fv-text" dangerouslySetInnerHTML={{ __html: line || ' ' }} />
            )}
        </div>
      ))}
    </div>
  )
}

/** One Jupyter cell after another: source highlighted, output as text. */
function Notebook({ content }: { content: string }): ReactNode {
  const cells = useMemo(() => {
    try {
      const nb = JSON.parse(content) as {
        cells?: { cell_type?: string; source?: string[] | string; outputs?: unknown[] }[]
      }
      return nb.cells ?? []
    } catch {
      return null
    }
  }, [content])

  if (cells === null) return <Code text={content} language="json" wrap={false} />

  const textOf = (source?: string[] | string): string =>
    Array.isArray(source) ? source.join('') : (source ?? '')

  return (
    <div className="fv-body fv-nb">
      {cells.map((cell, i) => {
        const source = textOf(cell.source)
        if (cell.cell_type === 'markdown') {
          return <div className="fv-nb-md" key={i}><Markdown text={source} /></div>
        }
        const outputs = (cell.outputs ?? []).map((o) => {
          const out = o as { text?: string[] | string; data?: Record<string, unknown> }
          const plain = out.data?.['text/plain']
          return textOf(out.text) || textOf(plain as string[] | string)
        }).filter(Boolean)
        return (
          <div className="fv-nb-cell" key={i}>
            <div className="fv-nb-src">
              <Code text={source} language="python" wrap={false} />
            </div>
            {outputs.length > 0 && (
              <pre className="fv-nb-out">{outputs.join('\n')}</pre>
            )}
          </div>
        )
      })}
    </div>
  )
}

export function FileView({
  sessionId, path, name, content, binary, size, truncated, t,
}: FileViewProps): ReactNode {
  const [wrap, setWrap] = useState(false)
  const [fit, setFit] = useState(true)
  /**
   * PDFs: server-rendered pages by default, Chromium's own viewer on request.
   *
   * The native viewer is better when it works — text selection, search, real
   * zoom — and it does not always work: it is a plugin, and a plugin that is
   * unavailable paints a silent grey rectangle. Pages come from the same
   * renderer that handles docx and pptx, so the default is the one that
   * cannot fail, and the better one is a button away.
   */
  const [native, setNative] = useState(false)
  const [blob, setBlob] = useState<{ url: string; type: string } | null>(null)
  const [pages, setPages] = useState<{ urls: string[]; kind: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const owned = useRef<string[]>([])

  const kind: FileKind = useMemo(() => kindOf(name, binary), [name, binary])
  const language = useMemo(() => languageOf(name), [name])

  // Blob URLs are ours to free. A session spent opening images would
  // otherwise hold every one of them until the window closed.
  const release = (): void => {
    for (const url of owned.current) URL.revokeObjectURL(url)
    owned.current = []
  }

  useEffect(() => {
    let cancelled = false
    release()
    setBlob(null)
    setPages(null)
    setError(null)

    const wantsPages = kind === 'doc' || (kind === 'pdf' && !native)
    const wantsBytes = DRAWS_BYTES.has(kind) && !wantsPages
    if (!wantsBytes && !wantsPages) return () => { cancelled = true }

    setBusy(true)
    void (async () => {
      try {
        if (wantsPages) {
          const preview = await workspace.docPreview(sessionId, path)
          if (cancelled) return
          if (!preview.pages?.length) {
            setError(t('file.noPreview'))
            return
          }
          const urls: string[] = []
          for (const page of preview.pages) {
            const got = await workspace.raw(sessionId, page)
            if (cancelled) { URL.revokeObjectURL(got.url); return }
            owned.current.push(got.url)
            urls.push(got.url)
          }
          setPages({ urls, kind: preview.kind })
          return
        }
        const got = await workspace.rawWorkspace(sessionId, path)
        if (cancelled) { URL.revokeObjectURL(got.url); return }
        owned.current.push(got.url)
        setBlob(got)
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      } finally {
        if (!cancelled) setBusy(false)
      }
    })()

    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, path, kind, native])

  useEffect(() => release, [])

  const allLines = useMemo(() => content.split('\n'), [content])
  const lines = useMemo(
    () => (allLines.length > MAX_LINES ? allLines.slice(0, MAX_LINES) : allLines),
    [allLines],
  )
  const clipped = allLines.length > MAX_LINES
  const shownText = useMemo(
    () => (clipped ? lines.join('\n') : content),
    [clipped, lines, content],
  )
  const shown = size ?? (binary ? undefined : content.length)

  const meta = (): string => {
    const parts: string[] = [t(`file.kind.${kind}`)]
    if ((kind === 'doc' || kind === 'pdf') && pages) {
      parts.push(t('file.pages', { n: pages.urls.length }))
    }
    else if (!binary && (kind === 'code' || kind === 'text' || kind === 'markdown'
      || kind === 'json' || kind === 'table' || kind === 'svg')) {
      parts.push(t('file.lines', { n: allLines.length }))
    }
    if (typeof shown === 'number') parts.push(bytes(shown))
    return parts.join(' · ')
  }

  const textual = kind === 'code' || kind === 'text' || kind === 'json'

  return (
    <div className="fv">
      <div className="fv-head">
        <span className="fv-name" title={path}>{name}</span>
        <span className="fv-meta">{meta()}</span>
        {kind === 'image' && (
          <button type="button" className={`chat-hbtn ${fit ? 'on' : ''}`}
            onClick={() => setFit((v) => !v)}>
            {fit ? t('file.fit') : t('file.actual')}
          </button>
        )}
        {kind === 'pdf' && (
          <button type="button" className={`chat-hbtn ${native ? 'on' : ''}`}
            onClick={() => setNative((v) => !v)}>
            {native ? t('file.asPages') : t('file.asPdf')}
          </button>
        )}
        {textual && (
          <button type="button" className={`chat-hbtn ${wrap ? 'on' : ''}`}
            onClick={() => setWrap((v) => !v)}>
            {t('file.wrap')}
          </button>
        )}
      </div>

      {(truncated || clipped) && (
        <div className="fv-note">
          {truncated
            ? t('file.truncated', { shown: bytes(content.length), total: bytes(size) })
            : t('file.clipped', { n: MAX_LINES, total: allLines.length })}
        </div>
      )}

      {error && <div className="fv-empty">{error}</div>}
      {busy && !error && <div className="fv-empty">{t('explorer.loading')}</div>}

      {!error && kind === 'image' && blob && (
        <div className={`fv-body fv-canvas ${fit ? 'fit' : ''}`}>
          <img src={blob.url} alt={name} />
        </div>
      )}

      {!error && kind === 'svg' && blob && (
        <div className={`fv-body fv-canvas ${fit ? 'fit' : ''}`}>
          {/* An <img> renders SVG without running anything in it. */}
          <img src={blob.url} alt={name} />
        </div>
      )}

      {!error && kind === 'pdf' && native && blob && (
        <div className="fv-body fv-frame">
          <embed src={blob.url} type="application/pdf" />
        </div>
      )}

      {!error && (kind === 'doc' || kind === 'pdf') && pages && (
        <div className="fv-body fv-pages">
          {pages.urls.map((url, i) => (
            <img key={url} src={url} alt={t('file.page', { n: i + 1 })} />
          ))}
        </div>
      )}

      {!error && kind === 'audio' && blob && (
        <div className="fv-body fv-media"><audio src={blob.url} controls /></div>
      )}

      {!error && kind === 'video' && blob && (
        <div className="fv-body fv-media"><video src={blob.url} controls /></div>
      )}

      {!error && (kind === 'binary' || kind === 'archive') && !busy && (
        <div className="fv-empty">
          {t(kind === 'archive' ? 'file.archive' : 'file.binary')}
        </div>
      )}

      {!error && kind === 'markdown' && (
        <div className="fv-body fv-md"><Markdown text={content} /></div>
      )}

      {!error && kind === 'notebook' && <Notebook content={content} />}

      {!error && kind === 'table' && (
        <div className="fv-body">
          <table className="fv-table">
            <tbody>
              {parseTable(content, name.toLowerCase().endsWith('.tsv')).map((row, i) => (
                <tr key={i} className={i === 0 ? 'head' : ''}>
                  <td className="fv-ln">{i + 1}</td>
                  {row.map((cell, j) => <td key={j}>{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!error && (kind === 'code' || kind === 'json') && (
        <Code text={shownText} language={kind === 'json' ? 'json' : language} wrap={wrap} />
      )}

      {!error && kind === 'text' && (
        <div className={`fv-body fv-code ${wrap ? 'wrap' : ''}`}>
          {lines.map((line, i) => (
            <div className="fv-line" key={i}>
              <span className="fv-ln">{i + 1}</span>
              <span className="fv-text">{line || ' '}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default FileView
