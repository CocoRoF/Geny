/**
 * The bar along the bottom: this machine, and this connection.
 *
 * The agent runs on the server, but the app runs here — so when the window
 * feels slow the first honest question is whether it is this machine, and
 * opening a task manager to answer it is a bad answer. CPU and memory live in
 * the corner of the window instead, next to the one connection fact that
 * belongs beside them.
 *
 * Numbers are monospace so they stop jittering as they change, and the meter
 * is a meter rather than a chart because the question is "is it busy", not
 * "how busy, exactly, over the last minute".
 */
import { useEffect, useState, type ReactNode } from 'react'

import type { SystemStats } from '../../../preload/index'

type T = (key: string, vars?: Record<string, string | number>) => string

function gigabytes(bytes: number): string {
  return (bytes / 1024 ** 3).toFixed(1)
}

function megabytes(bytes: number): string {
  return Math.round(bytes / 1024 ** 2).toString()
}

function heat(percent: number): string {
  if (percent >= 85) return 'is-hot'
  if (percent >= 60) return 'is-warn'
  return ''
}

export function StatusBar({ t, left }: { t: T; left?: ReactNode }): ReactNode {
  const [stats, setStats] = useState<SystemStats | null>(null)
  const [version, setVersion] = useState('')

  useEffect(() => {
    // The first reading is pulled rather than waited for: a window that just
    // opened should not show blanks for two seconds.
    void window.connector?.system.get().then(setStats).catch(() => undefined)
    const off = window.connector?.system.onChange(setStats)
    void window.connector?.appVersion().then(setVersion).catch(() => undefined)
    return () => { off?.() }
  }, [])

  const memPercent = stats && stats.memTotal > 0
    ? Math.round((stats.memUsed / stats.memTotal) * 100)
    : 0

  return (
    <footer className="gy-statusbar">
      {left}
      {stats && (
        <>
          <span className="gy-stat" title={t('status.cores', { n: stats.cores })}>
            <span className="gy-stat-k">CPU</span>
            <span className={`gy-meter ${heat(stats.cpu)}`}>
              <i style={{ width: `${stats.cpu}%` }} />
            </span>
            <span className="gy-stat-v">{stats.cpu}%</span>
          </span>

          <span className="gy-stat">
            <span className="gy-stat-k">RAM</span>
            <span className={`gy-meter ${heat(memPercent)}`}>
              <i style={{ width: `${memPercent}%` }} />
            </span>
            <span className="gy-stat-v">
              {gigabytes(stats.memUsed)} / {gigabytes(stats.memTotal)} GB
            </span>
          </span>

          <span className="gy-stat" title={t('status.appMem')}>
            <span className="gy-stat-k">{t('status.app')}</span>
            <span className="gy-stat-v">{megabytes(stats.appMem)} MB</span>
          </span>
        </>
      )}
      {version && (
        <span className="gy-stat gy-stat--right">
          <span className="gy-stat-v">v{version}</span>
        </span>
      )}
    </footer>
  )
}

export default StatusBar
