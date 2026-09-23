/**
 * The avatar's switches, as this window sees them.
 *
 * The avatar window owns voice, microphone and screen (see
 * main/avatar-bridge.ts); this hook reads what it last said and sends it
 * requests. `state` is null while no avatar page is up — logged out, still
 * loading, or crashed — and every control built on it says so rather than
 * pretending to switch something that is not there.
 */
import { useCallback, useEffect, useState } from 'react'

import type { AvatarState, AvatarSwitch } from '../../../preload/index'

export interface AvatarControls {
  state: AvatarState | null
  set(key: AvatarSwitch, value: boolean): void
  speak(text: string): void
  hush(): void
}

export function useAvatar(): AvatarControls {
  const [state, setState] = useState<AvatarState | null>(null)

  useEffect(() => {
    let alive = true
    void window.connector?.avatar?.getState().then((s) => { if (alive) setState(s) })
    const off = window.connector?.avatar?.onState((s) => setState(s))
    return () => {
      alive = false
      off?.()
    }
  }, [])

  const set = useCallback((key: AvatarSwitch, value: boolean) => {
    window.connector?.avatar?.command({ type: 'set', key, value })
  }, [])
  const speak = useCallback((text: string) => {
    if (text.trim()) window.connector?.avatar?.command({ type: 'speak', text })
  }, [])
  const hush = useCallback(() => window.connector?.avatar?.command({ type: 'hush' }), [])

  return { state, set, speak, hush }
}
