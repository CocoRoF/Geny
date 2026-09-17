/**
 * The bar along the bottom: this machine, and this connection.
 *
 * The same footer Dex has, for the same reason. The agent runs on the server
 * but the app runs here, so when the window feels slow the first honest
 * question is whether it is this machine — and opening a task manager is a
 * bad way to answer it.
 *
 * Numbers are monospace and tabular so they stop jittering as they change,
 * and each meter is a meter rather than a chart: the question is "is it
 * busy", not "how busy, exactly, over the last minute".
 */
import { useEffect, useState, type ReactNode } from 'react'

import type { SystemStats } from '../../../preload/index'

type T = (key: string, vars?: Record<string, string | number>) => string

const GIB = 1024 ** 3

function Metric({ label, value, usage, title }: {
  label: string
  value: string
  usage: number | null
  title: string
}): ReactNode {
  return (
    <div className="system-metric" title={title}>
      <span className="system-metric-label">{label}</span>
      <span className="system-metric-value">{value}</span>
      <span className="system-meter" aria-hidden>
        <span style={{ width: `${usage ?? 0}%` }} />
      </span>
    </div>
  )
}

export function SystemMonitorFooter({ t, state }: {
  t: T
  /** The connection lamp, which is the one fact that belongs beside these. */
  state?: { tone: 'ok' | 'busy' | 'offline'; label: string }
}): ReactNode {
  const [stats, setStats] = useState<SystemStats | null>(null)
  const [version, setVersion] = useState('')

  useEffect(() => {
    // Pull the first reading rather than wait for it: a window that just
    // opened should not show blanks for two seconds.
    void window.connector?.system.get().then(setStats).catch(() => undefined)
    const off = window.connector?.system.onChange(setStats)
    void window.connector?.appVersion().then(setVersion).catch(() => undefined)
    return () => { off?.() }
  }, [])

  const memPercent = stats && stats.memTotal > 0
    ? Math.round((stats.memUsed / stats.memTotal) * 100)
    : 0
  const ram = stats
    ? `${(stats.memUsed / GIB).toFixed(1)}/${(stats.memTotal / GIB).toFixed(0)} GB`
    : '—'
  const app = stats ? `${Math.round(stats.appMem / 1024 ** 2)} MB` : '—'

  return (
    <footer className="system-monitor-footer" aria-label={t('status.aria')}>
      <div className={`system-monitor-state ${state?.tone === 'ok' ? '' : state?.tone ?? ''}`}>
        <span className="system-live-dot" aria-hidden />
        <span>{state?.label ?? t('status.system')}</span>
      </div>
      <Metric label="CPU" value={stats ? `${stats.cpu}%` : '—'} usage={stats?.cpu ?? null}
        title={t('status.cores', { n: stats?.cores ?? 0 })} />
      <Metric label="RAM" value={`${t('status.total')} ${ram} · ${t('status.app')} ${app}`}
        usage={memPercent} title={t('status.appMem')} />
      {stats && stats.load1 > 0 && (
        <div className="system-metric" title={t('status.load')}>
          <span className="system-metric-label">LOAD</span>
          <span className="system-metric-value">{stats.load1.toFixed(2)}</span>
        </div>
      )}
      {version && (
        <div className="system-metric">
          <span className="system-metric-value">v{version}</span>
        </div>
      )}
    </footer>
  )
}

export default SystemMonitorFooter
