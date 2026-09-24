/**
 * The parts every settings page is made of.
 *
 * Dex's settings grammar, so the two apps read as one product: a page is a
 * column of groups; a group is a small uppercase title over a bordered body;
 * a row is what a setting is called (and, under it, what it does) on the
 * left and the control on the right. A feature that is itself on or off is a
 * card — icon, title, description, switch — with its options underneath
 * while it is on. Everything saves the moment it changes; a button that does
 * something irreversible asks twice, in place.
 */
import {
  useCallback, useEffect, useId, useRef, useState,
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react'

import { Icon } from '../chat/icons'

export type T = (key: string, vars?: Record<string, string | number>) => string

// ── layout ───────────────────────────────────────────────────────────────

export function Group({
  title, hint, action, plain, children,
}: {
  title: ReactNode
  hint?: ReactNode
  /** A control beside the title (an add button, a refresh). */
  action?: ReactNode
  /** Children bring their own surfaces (cards, lists). */
  plain?: boolean
  children: ReactNode
}): ReactNode {
  return (
    <section className="set-group">
      <div className="set-group-head">
        <h3 className="set-group-title">{title}</h3>
        {action && <div className="set-group-action">{action}</div>}
      </div>
      {hint && <p className="set-group-hint">{hint}</p>}
      {plain ? children : <div className="set-group-body">{children}</div>}
    </section>
  )
}

export function Row({
  label, hint, children, stacked, disabled,
}: {
  label: ReactNode
  hint?: ReactNode
  children?: ReactNode
  /** The control takes the full width under the label (inputs, lists). */
  stacked?: boolean
  disabled?: boolean
}): ReactNode {
  return (
    <div className={`set-row ${stacked ? 'stacked' : ''} ${disabled ? 'disabled' : ''}`}>
      <div className="set-row-text">
        <div className="set-row-label">{label}</div>
        {hint && <div className="set-row-hint">{hint}</div>}
      </div>
      {children !== undefined && <div className="set-row-control">{children}</div>}
    </div>
  )
}

/** A feature that is on or off, with its options underneath while it is on. */
export function Card({
  icon, title, desc, control, children,
}: {
  icon: ReactNode
  title: ReactNode
  desc?: ReactNode
  control?: ReactNode
  children?: ReactNode
}): ReactNode {
  return (
    <div className="set-card">
      <div className="set-card-main">
        <span className="set-card-icon">{icon}</span>
        <div className="set-card-text">
          <div className="set-card-title">{title}</div>
          {desc && <div className="set-card-desc">{desc}</div>}
        </div>
        {control && <div className="set-card-control">{control}</div>}
      </div>
      {children && <div className="set-card-body">{children}</div>}
    </div>
  )
}

/** A label above a full-width input. */
export function Field({
  label, hint, children, htmlFor,
}: { label: ReactNode; hint?: ReactNode; children: ReactNode; htmlFor?: string }): ReactNode {
  return (
    <div className="set-field">
      <label className="set-field-label" htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && <div className="set-field-hint">{hint}</div>}
    </div>
  )
}

export function Hint({
  tone, children,
}: { tone?: 'ok' | 'warn' | 'err'; children: ReactNode }): ReactNode {
  return <p className={`set-hint ${tone ?? ''}`}>{children}</p>
}

/** A dot and what it means. Green has to mean it answered when asked. */
export function Status({
  tone, children,
}: { tone: 'ok' | 'err' | 'busy' | 'warn' | 'idle'; children: ReactNode }): ReactNode {
  return (
    <span className={`set-status ${tone}`}>
      <span className="set-status-dot" />
      <span className="set-status-text">{children}</span>
    </span>
  )
}

export function Empty({ children }: { children: ReactNode }): ReactNode {
  return <div className="set-empty">{children}</div>
}

// ── controls ─────────────────────────────────────────────────────────────

export function Switch({
  checked, onChange, disabled, label,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  disabled?: boolean
  label?: string
}): ReactNode {
  return (
    <label className="set-switch">
      <input type="checkbox" role="switch" aria-label={label} checked={checked} disabled={disabled}
        onChange={(e) => onChange(e.target.checked)} />
      <span className="set-switch-track" />
    </label>
  )
}

export interface Choice<V extends string> {
  value: V
  label: ReactNode
  icon?: ReactNode
}

export function Segmented<V extends string>({
  value, options, onChange, disabled, label,
}: {
  value: V
  options: Choice<V>[]
  onChange: (next: V) => void
  disabled?: boolean
  label?: string
}): ReactNode {
  return (
    <div className="set-seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value}
          className={value === o.value ? 'active' : ''} disabled={disabled}
          onClick={() => onChange(o.value)}>
          {o.icon}{o.label}
        </button>
      ))}
    </div>
  )
}

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

export function Button({
  variant = 'secondary', size, icon, children, className, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: 'sm'
  icon?: ReactNode
}): ReactNode {
  return (
    <button type="button" {...rest}
      className={`set-btn ${variant} ${size ?? ''} ${children == null || children === false ? 'icon-only' : ''} ${className ?? ''}`}>
      {icon}{children}
    </button>
  )
}

/**
 * A button that asks before it does something that cannot be undone: the
 * first press turns it red and says what will happen, the second does it.
 */
export function ConfirmButton({
  label, confirmLabel, cancelLabel, warning, onConfirm, disabled, size, icon,
}: {
  label: ReactNode
  confirmLabel: ReactNode
  cancelLabel: ReactNode
  warning?: ReactNode
  onConfirm: () => void | Promise<void>
  disabled?: boolean
  size?: 'sm'
  icon?: ReactNode
}): ReactNode {
  const [armed, setArmed] = useState(false)
  if (!armed) {
    return (
      <Button variant="secondary" size={size} icon={icon} disabled={disabled} onClick={() => setArmed(true)}>
        {label}
      </Button>
    )
  }
  return (
    <span className="set-confirm">
      {warning && <span className="set-confirm-warn">{warning}</span>}
      <Button variant="danger" size={size} disabled={disabled}
        onClick={() => { setArmed(false); void onConfirm() }}>
        {confirmLabel}
      </Button>
      <Button variant="ghost" size={size} onClick={() => setArmed(false)}>{cancelLabel}</Button>
    </span>
  )
}

export function TextInput({
  mono, className, ...rest
}: InputHTMLAttributes<HTMLInputElement> & { mono?: boolean }): ReactNode {
  return <input {...rest} className={`set-input ${mono ? 'mono' : ''} ${className ?? ''}`} />
}

export function Slider({
  value, min, max, step, onChange, format, disabled, label,
}: {
  value: number
  min: number
  max: number
  step: number
  onChange: (next: number) => void
  format: (v: number) => string
  disabled?: boolean
  label?: string
}): ReactNode {
  const pct = ((value - min) / (max - min)) * 100
  return (
    <div className="set-slider">
      <input type="range" min={min} max={max} step={step} value={value} disabled={disabled}
        aria-label={label}
        style={{ ['--fill' as string]: `${Math.max(0, Math.min(100, pct))}%` }}
        onChange={(e) => onChange(Number(e.target.value))} />
      <span className="set-slider-value">{format(value)}</span>
    </div>
  )
}

export interface Option<V extends string> {
  value: V
  label: string
  icon?: ReactNode
  /** A quieter second line or trailing note. */
  note?: string
}

/**
 * A dropdown drawn by the app. The OS one opens a white list over a dark
 * window on Windows and cannot show an icon or a note beside an option.
 */
export function Select<V extends string>({
  value, options, onChange, disabled, placeholder, label, wide,
}: {
  value: V
  options: Option<V>[]
  onChange: (next: V) => void
  disabled?: boolean
  placeholder?: string
  label?: string
  wide?: boolean
}): ReactNode {
  const [open, setOpen] = useState(false)
  const [hover, setHover] = useState(-1)
  const box = useRef<HTMLDivElement>(null)
  const listId = useId()
  const current = options.find((o) => o.value === value)

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent): void => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])

  useEffect(() => {
    if (open) setHover(Math.max(0, options.findIndex((o) => o.value === value)))
  }, [open, options, value])

  const pick = (v: V): void => {
    setOpen(false)
    if (v !== value) onChange(v)
  }

  const onKey = (e: ReactKeyboardEvent): void => {
    if (disabled) return
    if (!open && (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown')) {
      e.preventDefault()
      setOpen(true)
      return
    }
    if (!open) return
    if (e.key === 'Escape') { e.preventDefault(); setOpen(false) }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setHover((h) => Math.min(options.length - 1, h + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHover((h) => Math.max(0, h - 1)) }
    else if (e.key === 'Enter') {
      e.preventDefault()
      const o = options[hover]
      if (o) pick(o.value)
    }
  }

  return (
    <div className={`set-select ${wide ? 'wide' : ''} ${open ? 'open' : ''}`} ref={box}>
      <button type="button" className="set-select-trigger" disabled={disabled}
        aria-haspopup="listbox" aria-expanded={open} aria-controls={listId} aria-label={label}
        onClick={() => setOpen((v) => !v)} onKeyDown={onKey}>
        {current?.icon && <span className="set-select-icon">{current.icon}</span>}
        <span className={`set-select-label ${current ? '' : 'placeholder'}`}>
          {current?.label ?? placeholder ?? ''}
        </span>
        <span className="set-select-caret">{Icon.caretDown}</span>
      </button>
      {open && (
        <div className="set-select-pop" role="listbox" id={listId}>
          {options.map((o, i) => (
            <button key={o.value} type="button" role="option" aria-selected={o.value === value}
              className={`set-select-opt ${o.value === value ? 'selected' : ''} ${i === hover ? 'hover' : ''}`}
              onMouseEnter={() => setHover(i)} onClick={() => pick(o.value)}>
              {o.icon && <span className="set-select-icon">{o.icon}</span>}
              <span className="set-select-opt-label">{o.label}</span>
              {o.note && <span className="set-select-note">{o.note}</span>}
              {o.value === value && <span className="set-select-check">{Icon.check}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── feedback ─────────────────────────────────────────────────────────────

/** A message that shows for a moment after something was done. */
export function useFlash(ms = 1800): [string | null, (message: string) => void] {
  const [message, setMessage] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  const flash = useCallback((next: string) => {
    setMessage(next)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => setMessage(null), ms)
  }, [ms])
  return [message, flash]
}

// ── hotkeys ──────────────────────────────────────────────────────────────

function keyName(e: KeyboardEvent): string | null {
  const code = e.code
  if (code.startsWith('Key')) return code.slice(3)
  if (code.startsWith('Digit')) return code.slice(5)
  if (/^F\d{1,2}$/.test(code)) return code
  if (code.startsWith('Numpad')) {
    const n = code.slice(6)
    if (/^\d$/.test(n)) return 'num' + n
    const m: Record<string, string> = {
      Enter: 'Enter', Add: 'numadd', Subtract: 'numsub', Multiply: 'nummult', Divide: 'numdiv', Decimal: 'numdec',
    }
    return m[n] ?? null
  }
  const named: Record<string, string> = {
    Enter: 'Enter', Space: 'Space', Tab: 'Tab', Backspace: 'Backspace', Delete: 'Delete', Insert: 'Insert',
    ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left', ArrowRight: 'Right',
    Home: 'Home', End: 'End', PageUp: 'PageUp', PageDown: 'PageDown',
    Minus: '-', Equal: '=', BracketLeft: '[', BracketRight: ']', Backslash: '\\',
    Semicolon: ';', Quote: "'", Comma: ',', Period: '.', Slash: '/', Backquote: '`',
  }
  if (code in named) return named[code]
  if (e.key && e.key.length === 1) return e.key.toUpperCase()
  return null
}

/** Electron accelerator for a key press, or null while only modifiers are down
 *  (a global hotkey needs at least one modifier). */
export function keyEventToAccelerator(e: KeyboardEvent): string | null {
  const mods: string[] = []
  if (e.ctrlKey || e.metaKey) mods.push('CommandOrControl')
  if (e.altKey) mods.push('Alt')
  if (e.shiftKey) mods.push('Shift')
  const key = keyName(e)
  if (!key || mods.length === 0) return null
  return [...mods, key].join('+')
}

export function prettyAccel(acc: string): string[] {
  if (!acc) return []
  const mac = typeof navigator !== 'undefined' && /mac/i.test(navigator.platform)
  return acc.split('+').map((part) => {
    if (part === 'CommandOrControl') return mac ? '⌘' : 'Ctrl'
    if (part === 'Command') return '⌘'
    if (part === 'Control') return 'Ctrl'
    if (part === 'Alt') return mac ? '⌥' : 'Alt'
    if (part === 'Shift') return mac ? '⇧' : 'Shift'
    return part
  })
}

/** Click, press a combination, done. Esc cancels. */
export function HotkeyCapture({
  value, onCapture, t,
}: { value: string; onCapture: (acc: string) => void; t: T }): ReactNode {
  const [recording, setRecording] = useState(false)
  const start = (): void => {
    if (recording) return
    setRecording(true)
    window.connector?.hotkeys.pause?.() // free the registered combos while choosing
  }
  const stop = (): void => {
    setRecording(false)
    window.connector?.hotkeys.resume?.()
  }
  const onKeyDown = (e: ReactKeyboardEvent<HTMLButtonElement>): void => {
    if (!recording) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); start() }
      return
    }
    e.preventDefault()
    e.stopPropagation()
    if (e.key === 'Escape') { stop(); return }
    const acc = keyEventToAccelerator(e.nativeEvent)
    if (acc) { onCapture(acc); stop() }
  }
  const keys = prettyAccel(value)
  return (
    <button type="button" className={`set-hotkey ${recording ? 'recording' : ''}`}
      onClick={start} onKeyDown={onKeyDown} onBlur={stop}>
      {recording
        ? <span className="set-hotkey-wait">{t('set.hotkey.recording')}</span>
        : keys.length
          ? keys.map((k, i) => <kbd key={`${k}-${i}`}>{k}</kbd>)
          : <span className="set-hotkey-wait">{t('set.hotkey.idle')}</span>}
    </button>
  )
}
