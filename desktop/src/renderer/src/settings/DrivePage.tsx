/**
 * Drive — this computer's folder in the Geny cloud, and the folders linked
 * into it.
 *
 * One edge: this computer to the cloud. Agents reach shared files through
 * their own connection to the cloud (made on the web), not through a copy
 * per agent here — there used to be a toggle per agent on this page,
 * mirroring each one's workspace directly, which is an edge the model does
 * not have.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import type { SyncPairStatus } from '../../../preload/index'
import { Icon } from '../chat/icons'
import {
  Button, Card, ConfirmButton, Empty, Group, Hint, Row, Status, Switch, type T,
} from './kit'

type State = SyncPairStatus['state'] | 'session_gone'

function toneOf(state: State, connected: boolean): 'ok' | 'err' | 'busy' | 'warn' | 'idle' {
  if (state === 'error' || state === 'session_gone') return 'err'
  if (state === 'awaiting_confirmation') return 'warn'
  if (state === 'syncing') return 'busy'
  if (state === 'paused') return 'idle'
  return connected ? 'ok' : 'warn'
}

const RANK: Record<string, number> = { error: 5, session_gone: 5, awaiting_confirmation: 4, syncing: 3, paused: 2, idle: 1 }

export function DrivePage({ t }: { t: T }): ReactNode {
  const [root, setRoot] = useState('')
  const [cloud, setCloud] = useState(true)
  const [caps, setCaps] = useState<{ streaming: boolean; missing: string } | null>(null)
  const [native, setNative] = useState<{ running: boolean; mountpoint: string; supported: boolean } | null>(null)
  const [links, setLinks] = useState<Array<{ name: string; localPath: string; paused?: boolean }>>([])
  const [statuses, setStatuses] = useState<Record<string, SyncPairStatus>>({})
  const [folder, setFolder] = useState('')
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState<{ tone: 'ok' | 'err' | 'warn'; text: string } | null>(null)
  const [loaded, setLoaded] = useState(false)

  const refreshSync = useCallback(async () => {
    const res = await window.connector?.sync?.list().catch(() => null)
    if (!res) return
    setLinks(res.links ?? [])
    setStatuses(Object.fromEntries(res.statuses.map((s) => [s.id, s])))
  }, [])

  const refreshDrive = useCallback(async () => {
    const d = await window.connector?.drive?.get().catch(() => null)
    if (d) {
      setRoot(d.root)
      setCloud(d.cloudOptIn !== false)
      setCaps(d.capabilities ?? null)
    }
    void window.connector?.drive?.nativeStatus().then(setNative).catch(() => undefined)
  }, [])

  useEffect(() => {
    void Promise.all([refreshSync(), refreshDrive()]).finally(() => setLoaded(true))
    const off = window.connector?.sync?.onStatus((rows) => {
      setStatuses(Object.fromEntries(rows.map((s) => [s.id, s])))
    })
    return () => off?.()
  }, [refreshSync, refreshDrive])

  const changeRoot = async (): Promise<void> => {
    const picked = await window.connector?.drive?.pickRoot()
    if (!picked) return
    setBusy('root')
    setMsg(null)
    try {
      const r = await window.connector?.drive?.setRoot(picked)
      if (r?.ok) {
        setRoot(r.root ?? picked)
        setMsg({ tone: 'ok', text: t('drive.moved', { count: r.moved ?? 0 }) })
        await refreshDrive()
        await refreshSync()
      } else {
        setMsg({ tone: 'err', text: t('drive.moveFailed', { msg: r?.error ?? '?' }) })
      }
    } finally {
      setBusy('')
    }
  }

  const toggleCloud = async (next: boolean): Promise<void> => {
    setCloud(next)
    setBusy('cloud')
    try {
      await window.connector?.drive?.setCloud(next)
      await refreshDrive()
      await refreshSync()
    } finally {
      setBusy('')
    }
  }

  const toggleNative = async (next: boolean): Promise<void> => {
    const r = await window.connector?.drive?.nativeMount(next)
    if (r?.error) setMsg({ tone: 'err', text: r.error })
    await window.connector?.drive?.nativeStatus().then(setNative)
  }

  const addLink = async (): Promise<void> => {
    if (!folder) return
    const res = await window.connector?.sync?.addPair({ localPath: folder })
    if (res?.error === 'overlap') {
      setMsg({ tone: 'warn', text: t('sync.overlapError', { agent: String(res.conflictWith ?? '') }) })
      return
    }
    if (res?.error) {
      setMsg({ tone: 'err', text: res.error })
      return
    }
    setFolder('')
    setMsg(null)
    await refreshSync()
  }

  const cloudStatus = statuses.cloud
  const cloudState: State = cloudStatus?.state ?? 'idle'

  if (!loaded) return <Empty>{t('set.loading')}</Empty>

  return (
    <>
      {msg && <Hint tone={msg.tone}>{msg.text}</Hint>}

      <Card icon={Icon.cloud} title={t('drive.card')} desc={t('drive.hint')}
        control={<Switch checked={cloud} disabled={!!busy} onChange={(v) => void toggleCloud(v)} label={t('drive.cloudToggle')} />}>
        <Row stacked label={t('drive.rootLabel')} hint={t('drive.rootHint')}>
          <div className="set-inline">
            <span className="set-path" title={root}>{root || '—'}</span>
            <Button size="sm" icon={Icon.folder} disabled={busy === 'root'} onClick={() => void changeRoot()}>
              {busy === 'root' ? t('drive.moving') : t('drive.changeRoot')}
            </Button>
          </div>
        </Row>
        {cloud ? (
          <Row label={t('drive.cloudFolder')}
            hint={
              <>
                <Status tone={toneOf(cloudState, !!cloudStatus?.connected)}>{t(`sync.state.${cloudState}`)}</Status>
                {cloudStatus && (
                  <span className="set-muted"> · ↓{cloudStatus.counts.downloaded} ↑{cloudStatus.counts.uploaded}</span>
                )}
                {cloudStatus?.lastError && <span className="set-inline-note err">{cloudStatus.lastError}</span>}
              </>
            }>
            <Button size="sm" icon={Icon.folderOpen} onClick={() => void window.connector?.sync?.openFolder('cloud')}>
              {t('sync.openFolder')}
            </Button>
          </Row>
        ) : (
          <Row label={t('drive.cloudFolder')} hint={t('drive.cloudOff')} />
        )}
        {native?.supported && (
          <Row label={t('drive.nativeToggle')}
            hint={native.running ? `${t('drive.nativeAt')} ${native.mountpoint}` : t('set.drive.nativeHint')}>
            <Switch checked={native.running} disabled={!!busy} onChange={(v) => void toggleNative(v)}
              label={t('drive.nativeToggle')} />
          </Row>
        )}
        {caps && !caps.streaming && caps.missing && <Hint tone="warn">{caps.missing}</Hint>}
        {cloud && <Hint>{t('drive.cloudEdgeHint')}</Hint>}
      </Card>

      <Group title={t('sync.pairsCard')} hint={t('sync.pairsHint')} plain>
        {links.length === 0 ? (
          <div className="set-group-body"><Empty>{t('sync.empty')}</Empty></div>
        ) : (
          <div className="set-list">
            {links.map((link) => {
              // One row per link; the link fans out to an engine per
              // connected agent. Worst state wins, counts add up.
              const ids = Object.keys(statuses).filter((id) => id.startsWith('link:') && id.endsWith(`:${link.name}`))
              const rows = ids.map((id) => statuses[id]).filter(Boolean)
              const state: State = link.paused
                ? 'paused'
                : (rows.map((r) => r.state).sort((a, b) => (RANK[b] ?? 0) - (RANK[a] ?? 0))[0] ?? 'idle')
              const connected = rows.some((r) => r.connected)
              const down = rows.reduce((n, r) => n + r.counts.downloaded, 0)
              const up = rows.reduce((n, r) => n + r.counts.uploaded, 0)
              const conflicts = rows.reduce((n, r) => n + r.counts.conflicts, 0)
              const skipped = rows.reduce((n, r) => n + r.counts.skippedLarge, 0)
              const lastSync = rows.map((r) => r.lastSyncAt).filter(Boolean).sort().pop()
              const lastError = rows.map((r) => r.lastError).find(Boolean)
              const massId = ids.find((id) => statuses[id]?.pendingMassDelete)
              const mass = massId ? statuses[massId].pendingMassDelete : null
              return (
                <div key={link.name} className="set-item">
                  <div className="set-item-main">
                    <div className="set-item-title">
                      <Status tone={toneOf(state, connected)}>{link.name}</Status>
                      <span className="set-muted">{t(`sync.state.${state}`)}</span>
                    </div>
                    <div className="set-item-sub" title={link.localPath}>
                      <span className="set-mono">{link.localPath}</span>
                      <span className="set-muted"> → GenyDrive/{link.name}</span>
                    </div>
                    {rows.length > 0 && (
                      <div className="set-item-sub set-muted">
                        ↓{down} ↑{up}
                        {conflicts > 0 && ` · ${t('sync.conflicts', { count: conflicts })}`}
                        {skipped > 0 && ` · ${t('sync.skippedLarge', { count: skipped })}`}
                        {lastSync && ` · ${new Date(lastSync).toLocaleTimeString()}`}
                      </div>
                    )}
                    {lastError && <div className="set-item-sub"><span className="set-inline-note err">{lastError}</span></div>}
                    {mass && massId && (
                      <div className="set-warnbox">
                        <span>{t('sync.massDeleteWarn', { count: mass.count })}</span>
                        <span className="set-actions">
                          <Button size="sm" variant="danger"
                            onClick={() => void window.connector?.sync?.confirmMassDelete(massId, true).then(refreshSync)}>
                            {t('sync.massDeleteApply')}
                          </Button>
                          <Button size="sm"
                            onClick={() => void window.connector?.sync?.confirmMassDelete(massId, false).then(refreshSync)}>
                            {t('sync.massDeletePause')}
                          </Button>
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="set-item-actions">
                    <Button size="sm" variant="ghost" icon={Icon.folderOpen} title={t('sync.openFolder')}
                      aria-label={t('sync.openFolder')}
                      onClick={() => void window.connector?.sync?.openFolder(ids[0] ?? link.name)} />
                    <Button size="sm" variant="ghost" icon={Icon.sync} title={t('sync.syncNow')}
                      aria-label={t('sync.syncNow')}
                      onClick={() => ids.forEach((id) => void window.connector?.sync?.syncNow(id))} />
                    <Button size="sm" variant="ghost" icon={link.paused ? Icon.play : Icon.pause}
                      onClick={() => void window.connector?.sync?.setPaused(link.name, !link.paused).then(refreshSync)}>
                      {link.paused ? t('sync.resume') : t('sync.pause')}
                    </Button>
                    <ConfirmButton size="sm" label={t('sync.unlink')} confirmLabel={t('set.drive.unlinkConfirm')}
                      cancelLabel={t('set.cancel')} warning={t('sync.unlinkWarnCloud')}
                      onConfirm={async () => {
                        const r = await window.connector?.sync?.removePair(link.name)
                        const err = (r as { error?: string } | undefined)?.error
                        if (err) setMsg({ tone: 'err', text: err })
                        await refreshSync()
                        await refreshDrive()
                      }} />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Group>

      <Group title={t('sync.addCard')} hint={t('sync.safetyHint')}>
        <Row stacked label={t('sync.folderLabel')}>
          <div className="set-inline">
            <span className={`set-path ${folder ? '' : 'placeholder'}`} title={folder}>
              {folder || t('sync.folderPlaceholder')}
            </span>
            <Button size="sm" icon={Icon.folder}
              onClick={() => void window.connector?.sync?.pickFolder().then((p) => { if (p) setFolder(p) })}>
              {t('sync.browse')}
            </Button>
            <Button size="sm" variant="primary" disabled={!folder} onClick={() => void addLink()}>
              {t('sync.connect')}
            </Button>
          </div>
        </Row>
      </Group>
    </>
  )
}
