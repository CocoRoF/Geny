/**
 * The avatar's own switches, reachable from every window.
 *
 * Voice out (TTS), voice in (STT), hands-free, captions and screen
 * observation all RUN in the avatar window — that is where the audio plays,
 * the microphone is open and the screen stream lives — so that window owns
 * their state. Until now it was also the only place they could be switched:
 * in its unlocked bar, which a locked avatar (the default) does not show.
 * The chat window the app replaced never had them either; people reached
 * them through the avatar, and the native chat and the locked chip left no
 * way at all.
 *
 * So the avatar PUBLISHES its state and ACCEPTS commands, and main relays:
 * any window can read the state and ask for a change, and the avatar decides.
 * This module is the relay's contract — what a state and a command may look
 * like — kept free of Electron so it can be tested.
 */

/** What the avatar is doing, as it reports it. */
export interface AvatarState {
  /** The session the avatar window is showing. */
  sessionId: string | null
  /** Voice out: replies are spoken. */
  tts: boolean
  /** Voice notes: the microphone listens and each utterance is shared. */
  stt: boolean
  /** Hands-free: talk, pause, and it answers — a real conversation turn. */
  realtime: boolean
  /** Live captions of what the microphone hears (hands-free only). */
  captions: boolean
  /** Screen observation: the avatar sees the screen. */
  screen: boolean
  /** Push-to-talk is open. */
  ptt: boolean
  /** The avatar is speaking right now. */
  speaking: boolean
  /** The microphone is hearing speech right now. */
  listening: boolean
}

export const SWITCHES = ['tts', 'stt', 'realtime', 'captions', 'screen', 'ptt'] as const
export type AvatarSwitch = (typeof SWITCHES)[number]

export type AvatarCommand =
  | { type: 'set'; key: AvatarSwitch; value: boolean }
  /** Say this in the avatar's voice (the chat's read-aloud). */
  | { type: 'speak'; text: string }
  /** Stop speaking. */
  | { type: 'hush' }

/** The longest text a read-aloud may carry — a long answer, not a document. */
export const MAX_SPEAK_CHARS = 8000

function bool(v: unknown): boolean {
  return v === true
}

/** A published state, or `null` when it is not one. Unknown keys are dropped. */
export function cleanState(raw: unknown): AvatarState | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  return {
    sessionId: typeof r.sessionId === 'string' && r.sessionId ? r.sessionId : null,
    tts: bool(r.tts),
    stt: bool(r.stt),
    realtime: bool(r.realtime),
    captions: bool(r.captions),
    screen: bool(r.screen),
    ptt: bool(r.ptt),
    speaking: bool(r.speaking),
    listening: bool(r.listening),
  }
}

/**
 * A command another window sent, or `null` when it is not one of the few the
 * avatar accepts. The relay never forwards anything it cannot name: the avatar
 * window runs the server's code with the microphone and the screen open, and a
 * renderer elsewhere does not get to invent new things to ask it.
 */
export function cleanCommand(raw: unknown): AvatarCommand | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  if (r.type === 'set') {
    const key = r.key
    if (typeof key !== 'string' || !(SWITCHES as readonly string[]).includes(key)) return null
    if (typeof r.value !== 'boolean') return null
    return { type: 'set', key: key as AvatarSwitch, value: r.value }
  }
  if (r.type === 'speak') {
    if (typeof r.text !== 'string') return null
    const text = r.text.trim().slice(0, MAX_SPEAK_CHARS)
    return text ? { type: 'speak', text } : null
  }
  if (r.type === 'hush') return { type: 'hush' }
  return null
}
