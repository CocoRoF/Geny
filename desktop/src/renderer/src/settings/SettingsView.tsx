/**
 * Settings, as a tab of the main window.
 *
 * It was a separate window: a 640px column of cards that opened beside the
 * app, over it or behind it, whose tab row wrapped onto two lines. It is a
 * tab now, the way Dex does it — the gear opens it (and closes it again),
 * sections run along the top, and one column of groups sits under them.
 * Every control saves as it changes; there is no save button to forget.
 */
import { useEffect, useRef, type ReactNode } from 'react'

import { Icon } from '../chat/icons'
import type { Lang } from '../i18n'
import { AccountPage } from './AccountPage'
import { ControlPage } from './ControlPage'
import { DrivePage } from './DrivePage'
import { GeneralPage } from './GeneralPage'
import { Button, Empty, type T } from './kit'
import { McpPage } from './McpPage'
import { ModelsPage } from './ModelsPage'
import { ScreenPage } from './ScreenPage'
import { VoicePage } from './VoicePage'

export type Section = 'account' | 'general' | 'models' | 'voice' | 'screen' | 'control' | 'drive' | 'mcp'

export const SECTIONS: { id: Section; icon: ReactNode; label: string; needsAccount?: boolean }[] = [
  { id: 'account', icon: Icon.user, label: 'set.tab.account' },
  { id: 'general', icon: Icon.sliders, label: 'set.tab.general' },
  { id: 'models', icon: Icon.cpu, label: 'set.tab.models', needsAccount: true },
  { id: 'voice', icon: Icon.mic, label: 'set.tab.voice' },
  { id: 'screen', icon: Icon.eye, label: 'set.tab.screen' },
  { id: 'control', icon: Icon.pointer, label: 'set.tab.control' },
  { id: 'drive', icon: Icon.cloud, label: 'set.tab.drive', needsAccount: true },
  { id: 'mcp', icon: Icon.plug, label: 'set.tab.mcp' },
]

/** Old names (the tray, the web overlay, saved links) for today's sections. */
export function sectionOf(raw: string | null | undefined): Section | null {
  if (!raw) return null
  const aliases: Record<string, Section> = { app: 'general', workspace: 'drive', agents: 'models' }
  const id = (aliases[raw] ?? raw) as Section
  return SECTIONS.some((s) => s.id === id) ? id : null
}

export function SettingsView({
  t, lang, section, onSection, signedIn,
}: {
  t: T
  lang: Lang
  section: Section
  onSection: (next: Section) => void
  signedIn: boolean
}): ReactNode {
  const scroller = useRef<HTMLDivElement>(null)
  // A section starts at its top, not wherever the last one was scrolled to.
  useEffect(() => { scroller.current?.scrollTo({ top: 0 }) }, [section])

  const meta = SECTIONS.find((s) => s.id === section) ?? SECTIONS[0]
  const locked = meta.needsAccount && !signedIn

  const page = (): ReactNode => {
    if (locked) {
      return (
        <Empty>
          <span>{t('set.needsAccount')}</span>
          <Button variant="primary" size="sm" icon={Icon.user} onClick={() => onSection('account')}>
            {t('set.toAccount')}
          </Button>
        </Empty>
      )
    }
    switch (section) {
      case 'account': return <AccountPage t={t} signedIn={signedIn} />
      case 'general': return <GeneralPage t={t} lang={lang} />
      case 'models': return <ModelsPage t={t} />
      case 'voice': return <VoicePage t={t} />
      case 'screen': return <ScreenPage t={t} />
      case 'control': return <ControlPage t={t} />
      case 'drive': return <DrivePage t={t} />
      case 'mcp': return <McpPage t={t} />
    }
  }

  return (
    <div className="set-page" ref={scroller}>
      <div className="set-page-inner">
        <nav className="set-tabs" role="tablist" aria-label={t('set.title')}>
          {SECTIONS.map((s) => (
            <button key={s.id} type="button" role="tab" aria-selected={section === s.id}
              className={`set-tab ${section === s.id ? 'active' : ''}`}
              onClick={() => onSection(s.id)}>
              <span className="set-tab-icon">{s.icon}</span>
              {t(s.label)}
            </button>
          ))}
        </nav>
        <header className="set-head">
          <h2>{t(meta.label)}</h2>
          <p>{t(`set.desc.${meta.id}`)}</p>
        </header>
        <div className="set-panel" key={section}>{page()}</div>
      </div>
    </div>
  )
}
