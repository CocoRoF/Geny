/**
 * The avatar's voice and eyes, switched from the chat.
 *
 * Voice out, voice in, hands-free, captions, push-to-talk and screen
 * observation used to live only in the avatar window's unlocked bar — which a
 * locked avatar, the default, never shows — and the native chat had none of
 * them. They run in the avatar window (that is where the audio, the mic and
 * the screen stream are), so these buttons ASK it and show what it reports:
 * a switch here is never a guess about the other window.
 */
import type { ReactNode } from 'react'

import type { AvatarSwitch } from '../../../preload/index'
import { Icon } from './icons'
import type { AvatarControls } from './useAvatar'

type T = (key: string, vars?: Record<string, string | number>) => string

interface Switch {
  key: AvatarSwitch
  icon: ReactNode
}

const SWITCHES: Switch[] = [
  { key: 'tts', icon: Icon.volume },
  { key: 'stt', icon: Icon.mic },
  { key: 'ptt', icon: Icon.talk },
  { key: 'realtime', icon: Icon.headset },
  { key: 'captions', icon: Icon.captions },
  { key: 'screen', icon: Icon.eye },
]

export function VoiceBar({ avatar, t }: { avatar: AvatarControls; t: T }): ReactNode {
  const state = avatar.state
  const offline = !state
  return (
    <div className={`voice-bar ${offline ? 'offline' : ''}`}
      title={offline ? t('chat.voice.offline') : undefined}>
      {SWITCHES.map(({ key, icon }) => {
        // Captions only mean something while hands-free is listening.
        if (key === 'captions' && !state?.realtime) return null
        const on = !!state?.[key]
        return (
          <button
            key={key}
            type="button"
            className={`voice-btn ${on ? 'on' : ''}`}
            disabled={offline}
            aria-pressed={on}
            title={t(`chat.voice.${key}.hint`)}
            onClick={() => avatar.set(key, !on)}
          >
            {icon}
            <span>{t(`chat.voice.${key}`)}</span>
          </button>
        )
      })}
      {state?.speaking && (
        <button type="button" className="voice-live speaking" title={t('chat.voice.hush')}
          onClick={() => avatar.hush()}>
          <span className="voice-pulse" />{t('chat.voice.speaking')}
        </button>
      )}
      {!state?.speaking && state?.listening && (
        <span className="voice-live listening"><span className="voice-pulse" />{t('chat.voice.listening')}</span>
      )}
      {offline && <span className="voice-offline">{t('chat.voice.offlineShort')}</span>}
    </div>
  )
}

export default VoiceBar
