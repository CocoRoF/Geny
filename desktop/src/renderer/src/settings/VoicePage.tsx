/**
 * Voice — how the avatar speaks and listens.
 *
 * Everything here is applied by the avatar window the moment it changes
 * (main pushes the config to it); nothing waits for a restart. The switches
 * themselves — voice on, mic on, hands-free — are in the chat and on the
 * avatar's chip, where they are used; this page is how they behave.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Icon } from '../chat/icons'
import {
  Button, Group, HotkeyCapture, Row, Select, Slider, Switch, type Option, type T,
} from './kit'
import { useTuning } from './useTuning'

/**
 * The OS's audio devices, by LABEL: a deviceId is not portable to the avatar
 * window's origin. Labels need a media grant, so the mic is opened and
 * released once; the list refreshes when a device arrives late (VoiceMeeter).
 */
function useDevices(kind: 'audiooutput' | 'audioinput'): [{ id: string; label: string }[], () => void] {
  const [devices, setDevices] = useState<{ id: string; label: string }[]>([])
  const refresh = useCallback(async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true })
      s.getTracks().forEach((track) => track.stop())
    } catch { /* denied: the list still comes, maybe without names */ }
    try {
      const all = await navigator.mediaDevices.enumerateDevices()
      setDevices(all
        .filter((d) => d.kind === kind && d.deviceId)
        .map((d) => ({ id: d.deviceId, label: d.label || d.deviceId })))
    } catch {
      setDevices([])
    }
  }, [kind])
  useEffect(() => {
    void refresh()
    const md = navigator.mediaDevices
    const onChange = (): void => { void refresh() }
    md?.addEventListener?.('devicechange', onChange)
    return () => md?.removeEventListener?.('devicechange', onChange)
  }, [refresh])
  return [devices, () => void refresh()]
}

function DeviceSelect({
  kind, value, onChange, t,
}: {
  kind: 'audiooutput' | 'audioinput'
  value: string
  onChange: (label: string) => void
  t: T
}): ReactNode {
  const [devices, refresh] = useDevices(kind)
  const options: Option<string>[] = [
    { value: '', label: t('voice.deviceDefault') },
    ...devices.map((d) => ({ value: d.label, label: d.label })),
  ]
  // A device that is not plugged in right now stays chosen, and says so.
  if (value && !devices.some((d) => d.label === value)) {
    options.push({ value, label: value, note: t('set.voice.deviceAway') })
  }
  return (
    <div className="set-inline">
      <Select value={value} options={options} onChange={onChange} wide
        label={kind === 'audiooutput' ? t('voice.outputDevice') : t('voice.inputDevice')} />
      <Button variant="ghost" icon={Icon.refresh} aria-label={t('voice.deviceRefresh')}
        title={t('voice.deviceRefresh')} onClick={refresh} />
    </div>
  )
}

export function VoicePage({ t }: { t: T }): ReactNode {
  const { get, patch } = useTuning()
  const [ptt, setPtt] = useState('CommandOrControl+Shift+Space')
  const [pttMsg, setPttMsg] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)

  useEffect(() => {
    void window.connector?.hotkeys.getPushToTalk().then((h) => { if (h) setPtt(h) })
  }, [])

  const savePtt = async (acc: string): Promise<void> => {
    setPtt(acc)
    const ok = await window.connector?.hotkeys.setPushToTalk(acc)
    setPttMsg(ok
      ? { tone: 'ok', text: t('set.hotkey.registered') }
      : { tone: 'err', text: t('set.hotkey.conflict') })
  }

  const subtitles = get('subtitlesEnabled')

  return (
    <>
      <Group title={t('set.voice.talk')}>
        <Row label={t('set.voice.pttKey')}
          hint={pttMsg
            ? <span className={`set-inline-note ${pttMsg.tone}`}>{pttMsg.text}</span>
            : t('set.voice.pttHint')}>
          <HotkeyCapture value={ptt} onCapture={(acc) => void savePtt(acc)} t={t} />
        </Row>
      </Group>

      <Group title={t('set.voice.out')}>
        <Row label={t('voice.volume')} hint={t('set.voice.volumeHint')}>
          <Slider value={get('ttsVolume')} min={0} max={1} step={0.05} label={t('voice.volume')}
            format={(v) => `${Math.round(v * 100)}%`} onChange={(v) => patch({ ttsVolume: v })} />
        </Row>
        <Row stacked label={t('voice.outputDevice')} hint={t('set.voice.outputHint')}>
          <DeviceSelect kind="audiooutput" value={get('audioOutputLabel')} t={t}
            onChange={(v) => patch({ audioOutputLabel: v })} />
        </Row>
      </Group>

      <Group title={t('set.voice.in')}>
        <Row stacked label={t('voice.inputDevice')} hint={t('set.voice.inputHint')}>
          <DeviceSelect kind="audioinput" value={get('audioInputLabel')} t={t}
            onChange={(v) => patch({ audioInputLabel: v })} />
        </Row>
        <Row label={t('set.voice.sensitivity')} hint={t('set.voice.sensitivityHint')}>
          <Slider value={get('sttSensitivity')} min={0.01} max={0.1} step={0.005} label={t('set.voice.sensitivity')}
            format={(v) => v.toFixed(3)} onChange={(v) => patch({ sttSensitivity: v })} />
        </Row>
        <Row label={t('voice.sttSilence')} hint={t('set.voice.silenceHint')}>
          <Slider value={get('sttSilenceMs')} min={400} max={3000} step={100} label={t('voice.sttSilence')}
            format={(v) => `${(v / 1000).toFixed(1)}s`} onChange={(v) => patch({ sttSilenceMs: v })} />
        </Row>
        <Row label={t('voice.echoCancellation')} hint={t('set.voice.echoHint')}>
          <Switch checked={get('sttEchoCancellation')} label={t('voice.echoCancellation')}
            onChange={(v) => patch({ sttEchoCancellation: v })} />
        </Row>
        <Row label={t('voice.noiseSuppression')} hint={t('set.voice.noiseHint')}>
          <Switch checked={get('sttNoiseSuppression')} label={t('voice.noiseSuppression')}
            onChange={(v) => patch({ sttNoiseSuppression: v })} />
        </Row>
        <Row label={t('voice.autoGain')} hint={t('set.voice.gainHint')}>
          <Switch checked={get('sttAutoGain')} label={t('voice.autoGain')}
            onChange={(v) => patch({ sttAutoGain: v })} />
        </Row>
      </Group>

      <Group title={t('set.voice.subtitles')}>
        <Row label={t('voice.subtitlesToggle')} hint={t('set.voice.subtitlesHint')}>
          <Switch checked={subtitles} label={t('voice.subtitlesToggle')}
            onChange={(v) => patch({ subtitlesEnabled: v })} />
        </Row>
        <Row label={t('voice.subtitleSpeed')} hint={t('set.voice.speedHint')} disabled={!subtitles}>
          <Slider value={get('subtitleCharMs')} min={30} max={300} step={10} disabled={!subtitles}
            label={t('voice.subtitleSpeed')}
            format={(v) => t('voice.subtitleSpeedDisplay', { sec: (v / 1000).toFixed(2) })}
            onChange={(v) => patch({ subtitleCharMs: v })} />
        </Row>
      </Group>
    </>
  )
}
