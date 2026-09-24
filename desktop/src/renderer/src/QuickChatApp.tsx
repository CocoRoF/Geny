import { useCallback, useEffect, useRef, useState } from 'react'

import type { AvatarState } from '../../preload/index'
import { ATTACH_ACCEPT, PendingChips, base64ToFile, usePendingFiles } from './chat/attachments'
import { Icon } from './chat/icons'
import { makeT, type Lang } from './i18n'
import { agents, rooms } from './server'

// ─────────────────────────────────────────────────────────────────────────────
// Quick chat — the floating bar the global hotkey summons (default
// Cmd/Ctrl+Shift+Enter), for talking to the avatar's VTuber without leaving
// whatever is on screen: a game, a document, a call.
//
// It talks to the VTuber the AVATAR is showing and sends from here, through
// the same room endpoint the chat and the web use; the avatar hears the reply
// on its own subscription and speaks it. It used to hand the text to the chat
// window instead, which sent it to whichever session that window happened to
// have open, dropped the pictures, and reported success before anything had
// been sent.
//
// The window itself is PERMANENT: main keeps a transparent, top-most window
// alive at all times (like the avatar, so it layers above a full-screen game).
// What appears and disappears is the card. The card is always dark and
// opaque: it floats over anything at all, and a see-through card over a light
// page is text nobody can read.
// ─────────────────────────────────────────────────────────────────────────────

type Phase = 'idle' | 'sending' | 'sent' | 'error'

interface Target {
  sessionId: string
  name: string
}

/** The VTuber the avatar is showing — what the avatar reports, else the one
 *  it was last told to show. */
async function resolveTarget(): Promise<Target | null> {
  const state: AvatarState | null =
    (await window.connector?.avatar?.getState().catch(() => null)) ?? null
  let sessionId = state?.sessionId ?? null
  if (!sessionId) {
    const config = await window.connector?.serverConfig.get().catch(() => null)
    sessionId = (config as { overlaySession?: string } | null)?.overlaySession ?? null
  }
  if (!sessionId) return null
  const list = await agents.list().catch(() => [])
  const agent = list.find((a) => a.session_id === sessionId)
  return { sessionId, name: agent?.session_name || '' }
}

export function QuickChatApp() {
  const [visible, setVisible] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [text, setText] = useState('')
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState('')
  const [lang, setLang] = useState<Lang>('ko')
  const [target, setTarget] = useState<Target | null>(null)
  const [targetKnown, setTargetKnown] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const t = makeT(lang)
  const pending = usePendingFiles(t)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Always dark: the shared parts drawn inside the card (the file chips) take
  // their colours from the dark tokens, not from whatever the app theme is.
  useEffect(() => {
    document.documentElement.dataset.theme = 'dark'
  }, [])

  const refresh = useCallback(() => {
    void window.connector?.serverConfig.get().then(async (c) => {
      const osLang = (await window.connector?.appDefaultLang?.().catch(() => 'ko' as Lang)) ?? 'ko'
      setLang(c.lang ?? osLang)
    }).catch(() => undefined)
    void resolveTarget().then((found) => {
      setTarget(found)
      setTargetKnown(true)
    })
  }, [])

  const focusInput = useCallback(() => {
    const el = inputRef.current
    if (!el) return
    el.focus()
    el.select()
  }, [])

  // Summoned: paint, find out who it is going to, focus. What was typed and
  // not sent is still there — clicking away by accident loses nothing, and
  // it is selected, so typing replaces it.
  useEffect(() => {
    refresh()
    const offOpen = window.connector?.quickChat?.onOpened?.(() => {
      if (closeTimer.current) clearTimeout(closeTimer.current)
      setPhase('idle')
      setError('')
      setVisible(true)
      refresh()
      setTimeout(focusInput, 20)
    })
    const offDismiss = window.connector?.quickChat?.onDismissed?.(() => setVisible(false))
    return () => { offOpen?.(); offDismiss?.() }
  }, [refresh, focusInput])

  // The avatar switching VTubers retargets the bar; its voice shows here too.
  useEffect(() => {
    let last: string | null = null
    return window.connector?.avatar?.onState((s) => {
      setSpeaking(!!s?.speaking)
      const sid = s?.sessionId ?? null
      if (sid !== last) {
        last = sid
        if (sid) void resolveTarget().then(setTarget)
      }
    })
  }, [])

  // Main grabs OS focus a tick after the summon; put the caret in the box.
  useEffect(() => {
    const onWinFocus = () => { if (visible) focusInput() }
    window.addEventListener('focus', onWinFocus)
    return () => window.removeEventListener('focus', onWinFocus)
  }, [visible, focusInput])

  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`
  }, [text, visible])

  // The window follows the card, so the page itself never scrolls.
  useEffect(() => {
    if (!visible) return
    const el = cardRef.current
    if (!el) return
    const report = () => {
      const h = Math.ceil(el.getBoundingClientRect().height) + 28 // root padding
      window.connector?.quickChat?.resize?.(h)
    }
    report()
    const ro = new ResizeObserver(report)
    ro.observe(el)
    return () => ro.disconnect()
  }, [visible])

  const addFiles = useCallback((files: File[]) => {
    if (files.length === 0) return
    setPhase('idle')
    setError('')
    pending.add(files)
    setTimeout(focusInput, 0)
  }, [pending, focusInput])

  const onPaste = (e: React.ClipboardEvent) => {
    const files = Array.from(e.clipboardData?.files ?? [])
    if (files.length === 0) return // plain text pastes as usual
    e.preventDefault()
    addFiles(files)
  }

  // The screen as it is — without this bar in the picture: the card steps
  // out of the way for the capture and comes back with it attached.
  const attachScreen = async () => {
    if (capturing) return
    setCapturing(true)
    await new Promise((r) => setTimeout(r, 140))
    try {
      const shot = await window.connector?.screenGrab?.()
      if (shot) {
        const stamp = new Date().toTimeString().slice(0, 8).replace(/:/g, '')
        addFiles([base64ToFile(shot.data, shot.mime_type, `screen-${stamp}.jpg`)])
      }
    } catch (e) {
      setPhase('error')
      setError((e as Error).message)
    } finally {
      setCapturing(false)
    }
  }

  const ready = pending.files.some((f) => f.uploaded)
  const canSend = !!target && phase !== 'sending' && !pending.uploading && (!!text.trim() || ready)

  const submit = async () => {
    if (!canSend || !target) return
    setPhase('sending')
    setError('')
    try {
      const room = await rooms.forSession(target.sessionId)
      await rooms.send(room.id, text.trim(), pending.peek())
      // Cleared only once it is sent: a failure keeps the text and the files.
      pending.clear()
      setText('')
      setPhase('sent')
      closeTimer.current = setTimeout(() => window.connector?.quickChat?.close(), 650)
    } catch (e) {
      setPhase('error')
      setError((e as Error).message || t('qc.sendFailed'))
      setTimeout(focusInput, 0)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      setVisible(false)
      window.connector?.quickChat?.close()
    } else if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      // isComposing: Enter that confirms a Korean/Japanese syllable is not a send.
      e.preventDefault()
      void submit()
    }
  }

  if (!visible) return <div className="qc-root" />

  const to = target
    ? (target.name ? t('qc.to', { name: target.name }) : t('qc.toUnnamed'))
    : null

  return (
    <div className="qc-root">
      <div className={`qc-card ${capturing ? 'capturing' : ''}`} ref={cardRef}>
        <div className="qc-head">
          <span className={`qc-target ${target ? '' : 'none'}`}>
            <span className={`qc-dot ${speaking ? 'speaking' : ''}`} />
            {to ?? (targetKnown ? t('qc.noTarget') : t('qc.finding'))}
          </span>
          {speaking && <span className="qc-speaking">{t('chat.voice.speaking')}</span>}
        </div>

        <div
          className="qc-bar"
          onDragOver={(e) => {
            if (Array.from(e.dataTransfer.types).includes('Files')) e.preventDefault()
          }}
          onDrop={(e) => {
            const files = Array.from(e.dataTransfer.files ?? [])
            if (files.length === 0) return
            e.preventDefault()
            addFiles(files)
          }}
        >
          <textarea
            ref={inputRef}
            className="qc-input"
            value={text}
            rows={1}
            placeholder={target ? t('qc.placeholder') : ''}
            disabled={targetKnown && !target}
            onChange={(e) => {
              setText(e.target.value)
              if (phase === 'error' || phase === 'sent') setPhase('idle')
            }}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            spellCheck={false}
            autoFocus
          />
          <button type="button" className={`qc-send ${phase === 'sending' ? 'busy' : ''}`}
            onClick={() => void submit()} disabled={!canSend}
            title={pending.uploading ? t('chat.attach.waiting') : t('qc.sendAria')}
            aria-label={t('qc.sendAria')}>
            {phase === 'sending' ? <span className="qc-spin" /> : Icon.send}
          </button>
        </div>

        <PendingChips files={pending.files} notice={pending.notice} onRemove={pending.remove} t={t} />

        <div className="qc-foot">
          <button type="button" className="qc-tool" disabled={!target}
            title={t('chat.attach.button')} onClick={() => fileInput.current?.click()}>
            {Icon.paperclip}
          </button>
          <button type="button" className="qc-tool" disabled={!target || capturing}
            title={t('chat.attach.screenHint')} onClick={() => void attachScreen()}>
            {Icon.monitor}
          </button>
          <input ref={fileInput} type="file" multiple accept={ATTACH_ACCEPT} hidden
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []))
              e.target.value = ''
            }} />
          {phase === 'error' ? (
            <span className="qc-hint qc-err">{error}</span>
          ) : phase === 'sent' ? (
            <span className="qc-hint qc-ok">{t('qc.sent')}</span>
          ) : (
            <span className="qc-hint">
              <kbd>Enter</kbd> {t('qc.footSend')}
              <span className="qc-sep" /><kbd>Shift</kbd><kbd>Enter</kbd> {t('qc.footNewline')}
              <span className="qc-sep" /><kbd>Esc</kbd> {t('qc.footClose')}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
