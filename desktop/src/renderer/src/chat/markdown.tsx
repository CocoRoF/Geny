/**
 * Just enough markdown for an agent's answer.
 *
 * What an agent writes is mostly prose with code in it: fenced blocks, paths
 * and identifiers in backticks, numbered steps. Those four things, rendered
 * properly, are the difference between reading an answer and decoding one —
 * and they are also the whole list, which is why this is fifty lines instead
 * of a dependency.
 *
 * Nothing here interprets HTML: every value reaches the DOM as a text node,
 * so a model that writes `<script>` renders those characters and nothing
 * happens. That is a deliberate property of the renderer, not an accident of
 * the current implementation — do not add `dangerouslySetInnerHTML`.
 */
import type { ReactNode } from 'react'

/** `code`, **bold**, *italic*, and bare URLs, in one pass. */
function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\n]+\*)|(https?:\/\/[^\s)]+)/g
  let last = 0
  let key = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index))
    if (m[1]) out.push(<code key={`${keyBase}c${key++}`}>{m[1].slice(1, -1)}</code>)
    else if (m[2]) out.push(<b key={`${keyBase}b${key++}`}>{m[2].slice(2, -2)}</b>)
    else if (m[3]) out.push(<i key={`${keyBase}i${key++}`}>{m[3].slice(1, -1)}</i>)
    else if (m[4]) {
      const href = m[4]
      out.push(
        <a key={`${keyBase}a${key++}`} href={href}
          onClick={(e) => { e.preventDefault(); window.connector?.windowControl.openExternal(href) }}>
          {href}
        </a>,
      )
    }
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

interface Block {
  kind: 'p' | 'code' | 'h' | 'ul' | 'ol' | 'quote'
  lines: string[]
  lang?: string
  level?: number
}

function parse(source: string): Block[] {
  const blocks: Block[] = []
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const fence = /^\s*```(\S*)\s*$/.exec(line)
    if (fence) {
      const body: string[] = []
      i += 1
      // An unterminated fence runs to the end: a streaming answer is opened
      // before it is closed, and half a code block still has to render.
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) {
        body.push(lines[i])
        i += 1
      }
      i += 1
      blocks.push({ kind: 'code', lines: body, lang: fence[1] || '' })
      continue
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      blocks.push({ kind: 'h', lines: [heading[2]], level: heading[1].length })
      i += 1
      continue
    }
    if (/^\s*>\s?/.test(line)) {
      const body: string[] = []
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        body.push(lines[i].replace(/^\s*>\s?/, ''))
        i += 1
      }
      blocks.push({ kind: 'quote', lines: body })
      continue
    }
    if (/^\s*([-*·]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line)
      const body: string[] = []
      while (i < lines.length && /^\s*([-*·]|\d+[.)])\s+/.test(lines[i])) {
        body.push(lines[i].replace(/^\s*([-*·]|\d+[.)])\s+/, ''))
        i += 1
      }
      blocks.push({ kind: ordered ? 'ol' : 'ul', lines: body })
      continue
    }
    if (!line.trim()) {
      i += 1
      continue
    }
    const body: string[] = []
    while (
      i < lines.length && lines[i].trim() &&
      !/^\s*```/.test(lines[i]) && !/^#{1,4}\s/.test(lines[i]) &&
      !/^\s*([-*·]|\d+[.)])\s+/.test(lines[i]) && !/^\s*>/.test(lines[i])
    ) {
      body.push(lines[i])
      i += 1
    }
    blocks.push({ kind: 'p', lines: body })
  }
  return blocks
}

export function Markdown({ text }: { text: string }): ReactNode {
  const blocks = parse(text)
  return (
    <div className="md">
      {blocks.map((block, index) => {
        const key = `b${index}`
        if (block.kind === 'code') {
          return (
            <pre key={key} className="md-code">
              {block.lang && <span className="md-lang">{block.lang}</span>}
              <code>{block.lines.join('\n')}</code>
            </pre>
          )
        }
        if (block.kind === 'h') {
          const Tag = (`h${Math.min(4, block.level ?? 2)}`) as 'h1' | 'h2' | 'h3' | 'h4'
          return <Tag key={key}>{inline(block.lines[0], key)}</Tag>
        }
        if (block.kind === 'ul' || block.kind === 'ol') {
          const items = block.lines.map((li, n) => <li key={`${key}i${n}`}>{inline(li, `${key}i${n}`)}</li>)
          return block.kind === 'ol' ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>
        }
        if (block.kind === 'quote') {
          return <blockquote key={key}>{inline(block.lines.join(' '), key)}</blockquote>
        }
        return <p key={key}>{inline(block.lines.join('\n'), key)}</p>
      })}
    </div>
  )
}

export default Markdown
