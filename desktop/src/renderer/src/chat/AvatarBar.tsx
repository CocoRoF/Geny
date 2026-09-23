/**
 * Which avatar this VTuber wears — and changing it without leaving the chat.
 *
 * The window this app replaced (the server's `/connector` page) had a model
 * picker in its header; the native chat dropped it, which left no way to
 * change a VTuber's avatar from the app at all. This is that picker, beside
 * the route picker it belongs with.
 *
 * Choosing here assigns on the server. The avatar window is subscribed to
 * assignments, so it swaps puppets the moment the server says so — nothing in
 * this file talks to the avatar window directly. The same stream keeps this
 * button honest when the avatar is changed from the web page or the phone.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'

import { avatars, serverUrl, type AvatarModel } from '../server'
import { groupAvatars, wornLabel } from './avatar-groups'
import { Icon } from './icons'

type T = (key: string, vars?: Record<string, string | number>) => string

export function AvatarBar({ sessionId, t }: { sessionId: string | null; t: T }): ReactNode {
  const [models, setModels] = useState<AvatarModel[]>([])
  const [worn, setWorn] = useState<string | null>(null)
  const [thumbs, setThumbs] = useState<Record<string, string>>({})
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const box = useRef<HTMLDivElement>(null)

  const refresh = useCallback(async () => {
    if (!sessionId) return
    try {
      const [listed, current] = await Promise.all([avatars.list(), avatars.of(sessionId)])
      setModels(listed.models ?? [])
      setWorn(current.model?.name ?? null)
      // A later success clears an earlier failure. Leaving it up is how a
      // 502 from one server restart stays on screen for the rest of the day.
      setError(null)
      const entries = await Promise.all(
        (listed.models ?? [])
          .filter((m) => m.thumbnail)
          .map(async (m) => [m.name, await serverUrl(m.thumbnail as string)] as const),
      )
      setThumbs(Object.fromEntries(entries))
    } catch (e) {
      setError((e as Error).message)
    }
  }, [sessionId])

  useEffect(() => {
    setWorn(null)
    void refresh()
  }, [refresh])

  // Follow assignments made anywhere. The stream ends when the server
  // restarts; it is re-opened then (with a short backoff), and the refresh on
  // reconnect catches whatever changed while it was down.
  useEffect(() => {
    if (!sessionId) return
    let stop: (() => void) | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    let closed = false
    const connect = (): void => {
      stop = avatars.follow(
        (sid, name) => {
          if (sid === sessionId) setWorn(name)
        },
        () => {
          if (closed) return
          timer = setTimeout(() => {
            if (closed) return
            void refresh()
            connect()
          }, 5_000)
        },
      )
    }
    connect()
    return () => {
      closed = true
      stop?.()
      if (timer) clearTimeout(timer)
    }
  }, [sessionId, refresh])

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent): void => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])

  const choose = async (name: string | null): Promise<void> => {
    if (!sessionId) return
    if (name === worn) {
      setOpen(false)
      return
    }
    setBusy(true)
    setError(null)
    try {
      if (name) await avatars.assign(sessionId, name)
      else await avatars.clear(sessionId)
      setWorn(name)
      setOpen(false)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const label = wornLabel(models, worn) ?? t('chat.avatar.none')
  const groups = groupAvatars(models)

  return (
    <div className="route" ref={box}>
      <button
        type="button"
        className="route-btn"
        title={t('chat.avatar.hint')}
        disabled={!sessionId}
        onClick={() => {
          setOpen((v) => !v)
          if (!open) void refresh() // a model installed since the last look
        }}
      >
        <span className="avatar-btn-icon">{Icon.avatar}</span>
        <span className="route-label">{label}</span>
        <span className="route-caret">⌄</span>
      </button>
      {open && (
        <div className="route-menu avatar-menu">
          {models.length === 0 && <div className="route-empty">{t('chat.avatar.empty')}</div>}
          {groups.map((group) => (
            <div key={group.runtime} className="route-group">
              <div className="route-group-h">{t(`chat.avatar.kind.${group.runtime}`)}</div>
              {group.models.map((model) => {
                const active = model.name === worn
                return (
                  <button
                    key={model.name}
                    type="button"
                    className={`route-item avatar-item ${active ? 'active' : ''}`}
                    disabled={busy}
                    onClick={() => void choose(model.name)}
                  >
                    <span className="avatar-item-main">
                      {thumbs[model.name] ? (
                        <img className="avatar-thumb" src={thumbs[model.name]} alt="" draggable={false} />
                      ) : (
                        <span className="avatar-thumb placeholder">{Icon.avatar}</span>
                      )}
                      <span className="avatar-item-name">{model.display_name || model.name}</span>
                    </span>
                    {active && <span className="route-check">✓</span>}
                  </button>
                )
              })}
            </div>
          ))}
          {worn && (
            <div className="route-group">
              <button type="button" className="route-item" disabled={busy} onClick={() => void choose(null)}>
                <span>{t('chat.avatar.clear')}</span>
              </button>
            </div>
          )}
        </div>
      )}
      {error && <span className="route-answered">{error}</span>}
    </div>
  )
}

export default AvatarBar
