/**
 * Files in the conversation — the ones you send, and the ones on messages.
 *
 * The chat this window replaced (the server's page) let you attach images and
 * documents by button, paste and drop, and drew every file on every message.
 * The native chat did none of it: a text box, and a conversation in which a
 * picture someone sent simply was not there. This is that, again.
 *
 * Files upload as soon as they are added — the way the web chat does it — so
 * sending is instant and a failure shows on the chip it belongs to, not as a
 * send that silently lost half its message.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import type { MessageAttachment } from '../../../../../shared/chat/transcript'
import { fileUrl, uploads, type OutgoingAttachment, type UploadedFile } from '../server'
import { Icon } from './icons'

type T = (key: string, vars?: Record<string, string | number>) => string

/** The same limit and the same file types the web chat takes. */
export const MAX_ATTACHMENTS = 8
export const ATTACH_ACCEPT =
  'image/*,audio/*,.pdf,.docx,.xlsx,.pptx,.csv,.md,.txt,.json,.zip,.wav,.mp3,.m4a,.ogg,.webm,.flac'

export interface PendingFile {
  id: string
  name: string
  kind: 'image' | 'audio' | 'file'
  /** Local preview for an image while (and after) it uploads. */
  preview?: string
  uploaded?: UploadedFile
  error?: string
}

function kindOf(mime: string): PendingFile['kind'] {
  if (mime.startsWith('image/')) return 'image'
  if (mime.startsWith('audio/')) return 'audio'
  return 'file'
}

let seq = 0

/** The composer's pending files: add (uploads at once), remove, take on send. */
export function usePendingFiles(t: T): {
  files: PendingFile[]
  uploading: boolean
  notice: string | null
  add(list: File[]): void
  remove(id: string): void
  take(): OutgoingAttachment[]
} {
  const [files, setFiles] = useState<PendingFile[]>([])
  const [notice, setNotice] = useState<string | null>(null)
  const filesRef = useRef(files)
  filesRef.current = files

  // Previews are object URLs; they are released with the chip.
  useEffect(() => () => {
    for (const f of filesRef.current) if (f.preview) URL.revokeObjectURL(f.preview)
  }, [])

  const add = useCallback((list: File[]) => {
    setNotice(null)
    const room = MAX_ATTACHMENTS - filesRef.current.length
    if (room <= 0) {
      setNotice(t('chat.attach.limit', { n: MAX_ATTACHMENTS }))
      return
    }
    const accepted = list.slice(0, room)
    if (accepted.length < list.length) setNotice(t('chat.attach.limit', { n: MAX_ATTACHMENTS }))
    const fresh: Array<PendingFile & { file: File }> = accepted.map((file) => {
      seq += 1
      const kind = kindOf(file.type || '')
      return {
        id: `f${Date.now()}-${seq}`,
        name: file.name || (kind === 'image' ? 'image.png' : 'file'),
        kind,
        preview: kind === 'image' ? URL.createObjectURL(file) : undefined,
        file,
      }
    })
    setFiles((prev) => [...prev, ...fresh.map(({ file: _f, ...rest }) => rest)])
    for (const item of fresh) {
      void uploads.send([item.file]).then(
        (done) => {
          setFiles((prev) => prev.map((f) =>
            f.id === item.id ? { ...f, uploaded: done[0], error: done[0] ? undefined : t('chat.attach.failed') } : f))
        },
        (e: Error) => {
          setFiles((prev) => prev.map((f) => (f.id === item.id ? { ...f, error: e.message } : f)))
        },
      )
    }
  }, [t])

  const remove = useCallback((id: string) => {
    setFiles((prev) => {
      const gone = prev.find((f) => f.id === id)
      if (gone?.preview) URL.revokeObjectURL(gone.preview)
      return prev.filter((f) => f.id !== id)
    })
    setNotice(null)
  }, [])

  /** What was uploaded, as message attachments; the composer is emptied. */
  const take = useCallback((): OutgoingAttachment[] => {
    const out = filesRef.current
      .filter((f) => f.uploaded)
      .map((f) => {
        const u = f.uploaded as UploadedFile
        return {
          kind: u.kind, name: u.name, mime_type: u.mime_type, size: u.size,
          sha256: u.sha256, attachment_id: u.attachment_id, url: u.url,
        }
      })
    for (const f of filesRef.current) if (f.preview) URL.revokeObjectURL(f.preview)
    setFiles([])
    setNotice(null)
    return out
  }, [])

  const uploading = files.some((f) => !f.uploaded && !f.error)
  return { files, uploading, notice, add, remove, take }
}

/** The chips above the composer. */
export function PendingChips({
  files, notice, onRemove, t,
}: {
  files: PendingFile[]
  notice: string | null
  onRemove: (id: string) => void
  t: T
}): ReactNode {
  if (files.length === 0 && !notice) return null
  return (
    <div className="attach-pending">
      {files.map((f) => (
        <span key={f.id} className={`attach-chip ${f.error ? 'error' : ''}`} title={f.error ?? f.name}>
          {f.preview ? <img src={f.preview} alt="" draggable={false} /> : <span className="attach-chip-icon">{Icon.file}</span>}
          <span className="attach-chip-name">{f.name}</span>
          {!f.uploaded && !f.error && <span className="attach-chip-busy">{t('chat.attach.uploading')}</span>}
          <button type="button" className="attach-chip-x" aria-label={t('chat.attach.remove')}
            onClick={() => onRemove(f.id)}>{Icon.close}</button>
        </span>
      ))}
      {notice && <span className="attach-notice">{notice}</span>}
    </div>
  )
}

/** A server file drawn as an image, fetched with the token when it needs one. */
function ServerImage({ path, name }: { path: string; name?: string }): ReactNode {
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let revoke: (() => void) | undefined
    let alive = true
    fileUrl(path).then(
      (r) => {
        if (alive) setSrc(r.url)
        else r.revoke?.()
        revoke = r.revoke
      },
      () => { if (alive) setFailed(true) },
    )
    return () => {
      alive = false
      revoke?.()
    }
  }, [path])
  if (failed) return <span className="attach-missing">{name || path.split('/').pop()}</span>
  if (!src) return <span className="attach-img loading" />
  return (
    <button type="button" className="attach-img" title={name} onClick={() => void openFile(path, name)}>
      <img src={src} alt={name ?? ''} draggable={false} />
    </button>
  )
}

/** Opens (or saves) a file a message carries. */
async function openFile(path: string, name?: string): Promise<void> {
  const r = await fileUrl(path)
  if (!r.revoke) {
    window.connector?.windowControl.openExternal(r.url)
    return
  }
  // A protected file: save it through the browser's download, which the app
  // turns into a native save dialog.
  const a = document.createElement('a')
  a.href = r.url
  a.download = name || path.split('/').pop() || 'file'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => r.revoke?.(), 30_000)
}

/** The files on a message in the transcript. */
export function MessageFiles({ files }: { files?: MessageAttachment[] }): ReactNode {
  if (!files || files.length === 0) return null
  return (
    <div className="msg-files">
      {files.map((f, i) => {
        const path = f.url || ''
        const key = `${f.attachment_id ?? path}:${i}`
        if (!path) return null
        if ((f.kind === 'image' || (f.mime_type ?? '').startsWith('image/'))) {
          return <ServerImage key={key} path={path} name={f.name} />
        }
        return (
          <button key={key} type="button" className="msg-file" onClick={() => void openFile(path, f.name)}>
            <span className="msg-file-icon">{Icon.file}</span>
            <span className="msg-file-name">{f.name || path.split('/').pop()}</span>
            {typeof f.size === 'number' && <span className="msg-file-size">{humanSize(f.size)}</span>}
          </button>
        )
      })}
    </div>
  )
}

function humanSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/** Base64 → File, for the screen picture the chat attaches. */
export function base64ToFile(data: string, mime: string, name: string): File {
  const bin = atob(data)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i)
  return new File([bytes], name, { type: mime })
}
