/**
 * Screen — what the avatar looks at while screen observation is on.
 *
 * The switch is in the chat and on the chip; this is how often it looks and
 * at which screen or window.
 */
import { useEffect, useState, type ReactNode } from 'react'

import { Icon } from '../chat/icons'
import { Group, Hint, Row, Segmented, Select, type Option, type T } from './kit'
import { useTuning } from './useTuning'

type Source = { id: string; name: string; display_id: string }

const INTERVALS = [
  { ms: 60_000, key: 'app.interval1m' },
  { ms: 180_000, key: 'app.interval3m' },
  { ms: 300_000, key: 'app.interval5m' },
  { ms: 600_000, key: 'app.interval10m' },
]

export function ScreenPage({ t }: { t: T }): ReactNode {
  const { get, patch } = useTuning()
  const [sources, setSources] = useState<Source[] | null>(null)

  useEffect(() => {
    void window.connector?.capture?.listSources?.()
      .then((s) => setSources(s ?? []))
      .catch(() => setSources([]))
  }, [])

  const interval = String(get('screenIntervalMs'))
  const chosen = get('screenSourceId') ?? ''
  const options: Option<string>[] = [
    { value: '', label: t('app.captureAuto'), icon: Icon.display },
    ...(sources ?? []).map((s) => ({
      value: s.id,
      label: s.name || s.id,
      icon: s.id.startsWith('screen:') ? Icon.display : Icon.appWindow,
      note: s.id.startsWith('screen:') ? t('set.screen.kindScreen') : t('set.screen.kindWindow'),
    })),
  ]
  // A window that has since closed stays chosen until something else is.
  if (chosen && sources && !sources.some((s) => s.id === chosen)) {
    options.push({ value: chosen, label: t('set.screen.gone'), icon: Icon.appWindow })
  }

  return (
    <>
      <Group title={t('set.screen.watch')} hint={t('set.screen.watchHint')}>
        <Row label={t('app.captureInterval')} hint={t('set.screen.intervalHint')}>
          <Segmented<string> value={interval} label={t('app.captureInterval')}
            onChange={(v) => patch({ screenIntervalMs: Number(v) })}
            options={INTERVALS.map((o) => ({ value: String(o.ms), label: t(o.key) }))} />
        </Row>
        <Row stacked label={t('app.captureSource')} hint={t('app.captureHint')}>
          {sources === null
            ? <Hint>{t('app.captureLoading')}</Hint>
            : sources.length === 0
              ? <Hint tone="warn">{t('set.screen.noSources')}</Hint>
              : <Select value={chosen} options={options} wide label={t('app.captureSource')}
                  onChange={(v) => patch({ screenSourceId: v || null })} />}
        </Row>
      </Group>
    </>
  )
}
