/**
 * Local control — whether the agent may act on this computer, and how far.
 *
 * Off by default. Main enforces every one of these itself (capture and
 * actuation are gated natively, not by the server's say-so), so what this
 * page shows is exactly what the agent can do.
 */
import { useEffect, useState, type ReactNode } from 'react'

import type { ComputerUseConfig, ConsentMode } from '../../../preload/index'
import { Icon } from '../chat/icons'
import { Card, Row, Segmented, Switch, type T } from './kit'

type Cap = 'screen' | 'input' | 'apps' | 'clipboard' | 'browser'

const CAPS: { key: Cap; label: string; hint: string }[] = [
  { key: 'screen', label: 'control.capScreen', hint: 'set.control.screenHint' },
  { key: 'input', label: 'control.capInput', hint: 'set.control.inputHint' },
  { key: 'apps', label: 'control.capApps', hint: 'set.control.appsHint' },
  { key: 'clipboard', label: 'control.capClipboard', hint: 'set.control.clipboardHint' },
  { key: 'browser', label: 'control.capBrowser', hint: 'set.control.browserHint' },
]

export function ControlPage({ t }: { t: T }): ReactNode {
  const [config, setConfig] = useState<ComputerUseConfig>({})

  useEffect(() => {
    void window.connector?.serverConfig.get().then((c) => setConfig(c.computerUse ?? {}))
  }, [])

  // The whole object each time: main merges config shallowly.
  const patch = (p: Partial<ComputerUseConfig>): void => {
    setConfig((prev) => {
      const next = { ...prev, ...p }
      void window.connector?.serverConfig.set({ computerUse: next })
      return next
    })
  }

  const on = config.enabled === true
  // Mirrors main's gate: a capability is on while the master is on and it
  // has not been turned off itself.
  const cap = (k: Cap): boolean => on && config[k] !== false
  const consent = config.consentMode ?? 'ask'

  return (
    <Card icon={Icon.pointer} title={t('control.card')} desc={t('set.control.desc')}
      control={<Switch checked={on} onChange={(v) => patch({ enabled: v })} label={t('control.masterToggle')} />}>
      {on && (
        <>
          {CAPS.map((c) => (
            <Row key={c.key} label={t(c.label)} hint={t(c.hint)}>
              <Switch checked={cap(c.key)} onChange={(v) => patch({ [c.key]: v })} label={t(c.label)} />
            </Row>
          ))}
          <Row label={t('control.consentTitle')} hint={t(`set.control.consent.${consent}`)}>
            <Segmented<ConsentMode> value={consent} label={t('control.consentTitle')}
              onChange={(v) => patch({ consentMode: v })} options={[
                { value: 'ask', label: t('control.consentAsk') },
                { value: 'session', label: t('control.consentSession') },
                { value: 'auto', label: t('control.consentAuto') },
              ]} />
          </Row>
        </>
      )}
    </Card>
  )
}
