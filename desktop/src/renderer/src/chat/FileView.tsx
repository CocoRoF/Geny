/**
 * A file the agent wrote, rendered as what it is.
 *
 * Dex's viewer handles images, PDFs and office documents too; Geny's read
 * endpoint returns decoded text and nothing else, so this covers what that
 * gives honestly rather than pretending:
 *
 *  · markdown → rendered, because a report the agent wrote is meant to be
 *    read and not decoded
 *  · csv / tsv → a table, for the same reason
 *  · anything else → the text, with line numbers and a wrap toggle
 *  · bytes that are not text → said plainly, not drawn as mojibake
 */
import { useMemo, useState, type ReactNode } from 'react'

import Markdown from './markdown'

type T = (key: string, vars?: Record<string, string | number>) => string

type Kind = 'markdown' | 'table' | 'text' | 'binary'

function kindOf(name: string, content: string): Kind {
  // A replacement character in the first kilobyte means the server decoded
  // bytes that were not text.
  if (content.slice(0, 1024).includes('�')) return 'binary'
  const ext = name.slice(name.lastIndexOf('.') + 1).toLowerCase()
  if (ext === 'md' || ext === 'markdown') return 'markdown'
  if (ext === 'csv' || ext === 'tsv') return 'table'
  return 'text'
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

export function FileView({ name, path, content, t }: {
  name: string
  path: string
  content: string
  t: T
}): ReactNode {
  const [wrap, setWrap] = useState(false)
  const kind = useMemo(() => kindOf(name, content), [name, content])
  const lines = useMemo(() => content.split('\n'), [content])

  return (
    <div className="fv">
      <div className="fv-head">
        <span className="fv-name" title={path}>{name}</span>
        <span className="fv-meta">
          {t('file.lines', { n: lines.length })} · {t('file.bytes', { n: content.length })}
        </span>
        {kind === 'text' && (
          <button type="button" className={`chat-hbtn ${wrap ? 'on' : ''}`}
            onClick={() => setWrap((v) => !v)}>
            {t('file.wrap')}
          </button>
        )}
      </div>

      {kind === 'binary' && <div className="fv-empty">{t('file.binary')}</div>}

      {kind === 'markdown' && (
        <div className="fv-body fv-md"><Markdown text={content} /></div>
      )}

      {kind === 'table' && (
        <div className="fv-body">
          <table className="fv-table">
            <tbody>
              {parseTable(content, name.toLowerCase().endsWith('.tsv')).map((row, i) => (
                <tr key={i}>
                  <td className="fv-ln">{i + 1}</td>
                  {row.map((cell, j) => <td key={j}>{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {kind === 'text' && (
        <div className={`fv-body fv-code ${wrap ? 'wrap' : ''}`}>
          {lines.map((line, i) => (
            <div className="fv-line" key={i}>
              <span className="fv-ln">{i + 1}</span>
              <span className="fv-text">{line || ' '}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default FileView
