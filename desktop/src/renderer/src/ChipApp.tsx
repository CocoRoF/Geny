/**
 * ChipApp — the locked avatar's controls, in their own tiny window.
 *
 * A locked avatar must let clicks reach the desktop on every platform,
 * so the avatar window is input-transparent — and an input-transparent
 * window cannot host its own unlock button. The chip therefore lives in
 * a separate always-interactive window that follows the avatar.
 *
 * It is rendered by the CONNECTOR, not by the server's overlay page.
 * Loading that page here crashed the app outright (measured: creating the
 * window is harmless, loading the overlay bundle into it is fatal — a
 * second copy of the avatar runtime, WebGL context and drivers in a
 * 104×40 window). Three buttons do not need any of that, and a local
 * chip also works before login and costs no network.
 *
 * It also carries the avatar's switches — voice out, mic, talk, hands-free,
 * captions, screen observation. Locked is how the avatar sits almost all the
 * time, and until now those switches lived only in the UNLOCKED bar: turning
 * the voice off meant unlocking, finding the button, and locking again. The
 * avatar window still owns them (main relays; see main/avatar-bridge.ts), so
 * the chip shows what the avatar reports, never its own guess.
 */
import { useEffect, useRef, useState } from 'react'

import type { AvatarState, AvatarSwitch } from '../../preload/index'

const BAR: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 2,
  padding: '4px 6px',
  borderRadius: 999,
  background: 'rgba(18,18,22,0.82)',
  border: '1px solid rgba(255,255,255,0.10)',
  backdropFilter: 'blur(8px)',
  WebkitBackdropFilter: 'blur(8px)',
  cursor: 'move',
  userSelect: 'none',
}

const BTN: React.CSSProperties = {
  display: 'grid',
  placeItems: 'center',
  width: 28,
  height: 28,
  borderRadius: 999,
  border: 'none',
  background: 'transparent',
  color: 'rgba(255,255,255,0.86)',
  cursor: 'pointer',
  padding: 0,
}

const ON: React.CSSProperties = {
  background: 'rgba(124,156,255,0.30)',
  color: '#fff',
  boxShadow: 'inset 0 0 0 1px rgba(150,176,255,0.55)',
}

const SEP: React.CSSProperties = {
  width: 1,
  height: 16,
  margin: '0 3px',
  background: 'rgba(255,255,255,0.16)',
}

/** The avatar's switches, in the order the avatar's own bar has them. */
const SWITCHES: Array<{ key: AvatarSwitch; on: string; off: string; icon: React.ReactNode }> = [
  {
    key: 'tts', on: '음성 출력 끄기', off: '음성 출력 켜기 — 답을 아바타 목소리로 읽어 줍니다',
    icon: <><path d="M11 5 6 9H2v6h4l5 4V5z" /><path d="M15.5 8.5a5 5 0 0 1 0 7" /><path d="M19 5a10 10 0 0 1 0 14" /></>,
  },
  {
    key: 'stt', on: '음성 입력 끄기', off: '음성 입력 켜기 — 말한 내용을 대화에 공유합니다',
    icon: <><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 11a7 7 0 0 0 14 0" /><path d="M12 18v4" /></>,
  },
  {
    key: 'ptt', on: '말하기 끝 — 보냅니다', off: '말하기 — 누르고 말한 뒤 다시 누르면 보냅니다',
    icon: <><path d="M4 12a8 8 0 0 1 16 0" /><path d="M8 12a4 4 0 0 1 8 0" /><circle cx="12" cy="17" r="2.5" /></>,
  },
  {
    key: 'realtime', on: '핸즈프리 끄기', off: '핸즈프리 켜기 — 말하고 멈추면 바로 답합니다',
    icon: <><path d="M3 14v-2a9 9 0 0 1 18 0v2" /><rect x="3" y="14" width="4" height="6" rx="1.5" /><rect x="17" y="14" width="4" height="6" rx="1.5" /></>,
  },
  {
    key: 'captions', on: '자막 끄기', off: '자막 켜기 — 듣는 말을 실시간으로 보여 줍니다',
    icon: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M10 10.5a2 2 0 1 0 0 3" /><path d="M17 10.5a2 2 0 1 0 0 3" /></>,
  },
  {
    key: 'screen', on: '화면 관찰 끄기', off: '화면 관찰 켜기 — 아바타가 화면을 봅니다',
    icon: <><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></>,
  },
]

function Svg({ children }: { children: React.ReactNode }): React.ReactElement {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  )
}

export function ChipApp(): React.ReactElement {
  const ref = useRef<HTMLDivElement | null>(null)
  const [avatar, setAvatar] = useState<AvatarState | null>(null)

  useEffect(() => {
    let alive = true
    void window.connector?.avatar?.getState().then((s) => { if (alive) setAvatar(s) }, () => undefined)
    const off = window.connector?.avatar?.onState((s) => setAvatar(s))
    return () => {
      alive = false
      off?.()
    }
  }, [])

  // Main sizes and positions the window around whatever this renders, so
  // it has to be told the size — including when the theme/zoom changes it.
  useEffect(() => {
    const report = (): void => {
      const r = ref.current?.getBoundingClientRect()
      if (r && r.width > 0) {
        window.connector?.windowControl.chipSize(Math.ceil(r.width) + 2, Math.ceil(r.height) + 2)
      }
    }
    report()
    const t = setInterval(report, 1500)
    window.addEventListener('resize', report)
    return () => {
      clearInterval(t)
      window.removeEventListener('resize', report)
    }
  }, [])

  // Switches appear with the avatar (and captions with hands-free): resize at
  // once rather than clipping them until the next periodic report.
  useEffect(() => {
    const r = ref.current?.getBoundingClientRect()
    if (r && r.width > 0) {
      window.connector?.windowControl.chipSize(Math.ceil(r.width) + 2, Math.ceil(r.height) + 2)
    }
  }, [avatar?.realtime, avatar?.speaking, avatar === null])

  // Dragging the chip moves the AVATAR (main moves both) — the chip is the
  // avatar's handle while the avatar itself is passing clicks through.
  const onDrag = (e: React.MouseEvent): void => {
    if ((e.target as HTMLElement).closest('button')) return
    e.preventDefault()
    const onMove = (ev: MouseEvent): void =>
      window.connector?.windowControl.moveBy(ev.movementX, ev.movementY)
    const onUp = (): void => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      window.connector?.windowControl.moveEnd()
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  return (
    <div
      style={{ display: 'grid', placeItems: 'center', width: '100vw', height: '100vh', background: 'transparent' }}
    >
      <div ref={ref} style={BAR} onMouseDown={onDrag}>
        {avatar && SWITCHES.map(({ key, on, off, icon }) => {
          // Captions only mean something while hands-free is listening.
          if (key === 'captions' && !avatar.realtime) return null
          const active = avatar[key]
          return (
            <button key={key} style={active ? { ...BTN, ...ON } : BTN} title={active ? on : off}
              aria-pressed={active}
              onClick={() => window.connector?.avatar?.command({ type: 'set', key, value: !active })}>
              <Svg>{icon}</Svg>
            </button>
          )
        })}
        {avatar?.speaking && (
          <button style={BTN} title="그만 말하기"
            onClick={() => window.connector?.avatar?.command({ type: 'hush' })}>
            <Svg><rect x="6" y="6" width="12" height="12" rx="2" /></Svg>
          </button>
        )}
        {avatar && <span style={SEP} />}
        <button style={BTN} title="채팅 창 열기"
          onClick={() => window.connector?.windowControl.openControl()}>
          <Svg><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" /></Svg>
        </button>
        <button style={BTN} title="설정 창 열기"
          onClick={() => window.connector?.windowControl.openSettings()}>
          <Svg>
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </Svg>
        </button>
        <button style={BTN} title="잠금 해제 — 아바타를 옮기거나 크기를 바꿉니다"
          onClick={() => window.connector?.windowControl.setLocked(false)}>
          <Svg>
            <rect x="4" y="11" width="16" height="10" rx="2" />
            <path d="M8 11V7a4 4 0 0 1 8 0" />
          </Svg>
        </button>
      </div>
    </div>
  )
}
