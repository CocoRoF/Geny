/**
 * The avatar's tuning — volume, microphone, subtitles, screen observation —
 * as the pages that set it see it.
 *
 * It lives in the connector config (`overlayTuning`) and main pushes every
 * change to the avatar window, which applies it without a reload. The whole
 * object is written each time: main merges config shallowly, so a partial
 * write would drop the keys it left out.
 */
import { useCallback, useEffect, useState } from 'react'

import type { OverlayTuning } from '../../../preload/index'

/** The avatar's own defaults, so a slider starts where the avatar does. */
export const TUNING_DEFAULTS = {
  ttsVolume: 0.7,
  sttSensitivity: 0.04,
  sttSilenceMs: 1200,
  sttEchoCancellation: true,
  sttNoiseSuppression: true,
  sttAutoGain: true,
  screenIntervalMs: 180_000,
  screenSourceId: null as string | null,
  subtitlesEnabled: true,
  subtitleCharMs: 100,
  audioOutputLabel: '',
  audioInputLabel: '',
}

type Defaults = typeof TUNING_DEFAULTS

export function useTuning(): {
  get: <K extends keyof Defaults>(key: K) => Defaults[K]
  patch: (p: Partial<OverlayTuning>) => void
} {
  const [tuning, setTuning] = useState<OverlayTuning>({})

  useEffect(() => {
    void window.connector?.serverConfig.get().then((c) => setTuning(c.overlayTuning ?? {}))
  }, [])

  const patch = useCallback((p: Partial<OverlayTuning>) => {
    setTuning((prev) => {
      const next = { ...TUNING_DEFAULTS, ...prev, ...p }
      void window.connector?.serverConfig.set({ overlayTuning: next })
      return next
    })
  }, [])

  const get = useCallback(<K extends keyof Defaults>(key: K): Defaults[K] =>
    ((tuning as Record<string, unknown>)[key] ?? TUNING_DEFAULTS[key]) as Defaults[K], [tuning])

  return { get, patch }
}
