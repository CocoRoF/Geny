/**
 * General — how the app looks, starts, updates, and what to do when it
 * misbehaves.
 */
import { useEffect, useState, type ReactNode } from 'react'

import { Icon } from '../chat/icons'
import type { Lang } from '../i18n'
import {
  Button, Group, HotkeyCapture, Hint, Row, Segmented, Switch, useFlash, type T,
} from './kit'

type Theme = 'system' | 'light' | 'dark'

export function GeneralPage({ t, lang }: { t: T; lang: Lang }): ReactNode {
  const [theme, setTheme] = useState<Theme>('system')
  const [autoUpdate, setAutoUpdate] = useState(true)
  const [autoStart, setAutoStart] = useState(false)
  const [autoStartFailed, setAutoStartFailed] = useState(false)
  const [quickChat, setQuickChat] = useState('CommandOrControl+Shift+Enter')
  const [quickChatMsg, setQuickChatMsg] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)
  const [version, setVersion] = useState('')
  const [debugText, setDebugText] = useState('')
  const [updateNote, flashUpdate] = useFlash(4000)
  const [resetNote, flashReset] = useFlash()
  const [copyNote, flashCopy] = useFlash()

  useEffect(() => {
    void window.connector?.serverConfig.get().then((c) => setTheme((c.theme as Theme) ?? 'system'))
    void window.connector?.updater.getEnabled().then(setAutoUpdate)
    void window.connector?.autostart?.get().then(setAutoStart).catch(() => undefined)
    void window.connector?.hotkeys.getQuickChat?.().then((h) => { if (h) setQuickChat(h) })
    void window.connector?.appVersion?.().then(setVersion).catch(() => undefined)
  }, [])

  // Main re-themes the window chrome and tells every window; the shell
  // listens and re-stamps the page.
  const changeTheme = (next: Theme): void => {
    setTheme(next)
    void window.connector?.serverConfig.set({ theme: next })
  }

  const changeLang = (next: Lang): void => {
    void window.connector?.serverConfig.set({ lang: next })
  }

  const toggleAutoUpdate = async (next: boolean): Promise<void> => {
    setAutoUpdate(next)
    await window.connector?.updater.setEnabled(next)
  }

  const toggleAutoStart = async (next: boolean): Promise<void> => {
    setAutoStart(next)
    setAutoStartFailed(false)
    // Main can refuse (an AppImage run from a temporary mount): show what it
    // actually did, never a switch that is on while nothing was registered.
    const effective = await window.connector?.autostart?.set(next)
    if (typeof effective === 'boolean' && effective !== next) {
      setAutoStart(effective)
      if (next) setAutoStartFailed(true)
    }
  }

  const saveQuickChat = async (acc: string): Promise<void> => {
    setQuickChat(acc)
    const ok = await window.connector?.hotkeys.setQuickChat?.(acc)
    setQuickChatMsg(ok
      ? { tone: 'ok', text: t('set.hotkey.registered') }
      : { tone: 'err', text: t('set.hotkey.conflict') })
  }

  return (
    <>
      <Group title={t('set.general.look')}>
        <Row label={t('app.themeCard')} hint={t('set.general.themeHint')}>
          <Segmented<Theme> value={theme} onChange={changeTheme} label={t('app.themeCard')} options={[
            { value: 'system', label: t('app.themeSystem'), icon: Icon.display },
            { value: 'light', label: t('app.themeLight'), icon: Icon.sun },
            { value: 'dark', label: t('app.themeDark'), icon: Icon.moon },
          ]} />
        </Row>
        <Row label={t('app.langCard')} hint={t('set.general.langHint')}>
          <Segmented<Lang> value={lang} onChange={changeLang} label={t('app.langCard')} options={[
            { value: 'ko', label: '한국어' },
            { value: 'en', label: 'English' },
          ]} />
        </Row>
      </Group>

      <Group title={t('set.general.quickChat')}>
        <Row label={t('set.general.quickChatKey')}
          hint={quickChatMsg
            ? <span className={`set-inline-note ${quickChatMsg.tone}`}>{quickChatMsg.text}</span>
            : t('set.general.quickChatHint')}>
          <HotkeyCapture value={quickChat} onCapture={(acc) => void saveQuickChat(acc)} t={t} />
        </Row>
      </Group>

      <Group title={t('set.general.startup')}>
        <Row label={t('app.autostartToggle')}
          hint={autoStartFailed
            ? <span className="set-inline-note err">{t('app.autostartFailed')}</span>
            : t('set.general.autostartHint')}>
          <Switch checked={autoStart} onChange={(v) => void toggleAutoStart(v)} label={t('app.autostartToggle')} />
        </Row>
      </Group>

      <Group title={t('set.general.update')}>
        <Row label={t('app.updateToggle')} hint={autoUpdate ? t('app.updateHintOn') : t('app.updateHintOff')}>
          <Switch checked={autoUpdate} onChange={(v) => void toggleAutoUpdate(v)} label={t('app.updateToggle')} />
        </Row>
        <Row label={t('set.general.version', { v: version || '?' })}
          hint={updateNote ?? t('set.general.checkHint')}>
          <Button size="sm" icon={Icon.download} onClick={() => {
            window.connector?.updater.check()
            flashUpdate(t('set.general.checking'))
          }}>
            {t('set.general.check')}
          </Button>
        </Row>
      </Group>

      <Group title={t('set.general.trouble')}>
        <Row label={t('app.positionsReset')} hint={resetNote ?? t('set.general.positionsHint')}>
          <Button size="sm" icon={Icon.refresh} onClick={() => {
            window.connector?.windowControl.resetPositions?.()
            flashReset(t('app.positionsResetDone'))
          }}>
            {t('set.general.reset')}
          </Button>
        </Row>
        <Row label={t('set.general.restart')} hint={t('set.general.restartHint')}>
          <Button size="sm" icon={Icon.power} onClick={() => window.connector?.windowControl.restart()}>
            {t('set.general.restartNow')}
          </Button>
        </Row>
        <Row stacked label={t('app.debugCard')} hint={t('set.general.debugHint')}>
          <div className="set-actions">
            <Button size="sm" icon={Icon.refresh}
              onClick={async () => setDebugText((await window.connector?.debug?.get()) ?? '')}>
              {debugText ? t('app.debugRefresh') : t('set.general.debugLoad')}
            </Button>
            <Button size="sm" icon={Icon.copy} disabled={!debugText} onClick={async () => {
              try {
                await navigator.clipboard.writeText(debugText)
                flashCopy(t('app.debugCopied'))
              } catch { /* the text stays selectable below */ }
            }}>
              {copyNote ?? t('app.debugCopy')}
            </Button>
          </div>
          {debugText && <pre className="set-log">{debugText}</pre>}
        </Row>
      </Group>
      {!window.connector && <Hint tone="warn">{t('set.noBridge')}</Hint>}
    </>
  )
}
