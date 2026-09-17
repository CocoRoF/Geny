/**
 * What this machine is doing, for the status bar.
 *
 * An agent runs on the server, but the connector runs here — and when the
 * window is slow, the honest first question is whether it is the app, the
 * machine, or the network. A status bar that shows CPU and memory answers it
 * without opening a task manager.
 *
 * CPU is sampled as a DELTA between two readings of `os.cpus()`, because the
 * absolute numbers there are totals since boot: reading them once and dividing
 * gives the average load since the machine was switched on, which is a number
 * that never moves and looks like a bug.
 *
 * Everything here is cheap and best-effort. It samples on a timer, pushes to
 * whichever windows are open, and stops when none are.
 */
import { BrowserWindow } from 'electron'
import { cpus, freemem, totalmem, loadavg, platform } from 'node:os'

export interface SystemStats {
  /** 0-100, across all cores, over the last sample interval. */
  cpu: number
  /** Bytes. */
  memUsed: number
  memTotal: number
  /** This app's own resident memory, in bytes — the other half of "is it me". */
  appMem: number
  cores: number
  /** 1-minute load average; 0 on Windows, where the OS does not keep one. */
  load1: number
}

const INTERVAL_MS = 2_000

interface CpuSample { idle: number; total: number }

function sampleCpu(): CpuSample {
  let idle = 0
  let total = 0
  for (const cpu of cpus()) {
    for (const value of Object.values(cpu.times)) total += value
    idle += cpu.times.idle
  }
  return { idle, total }
}

let previous = sampleCpu()
let timer: ReturnType<typeof setInterval> | null = null

function read(): SystemStats {
  const next = sampleCpu()
  const idleDelta = next.idle - previous.idle
  const totalDelta = next.total - previous.total
  previous = next
  // A zero delta means two samples landed in the same tick; reporting 100%
  // busy there would be a lie, and 0% is the safer one.
  const cpu = totalDelta > 0
    ? Math.min(100, Math.max(0, Math.round((1 - idleDelta / totalDelta) * 100)))
    : 0
  const total = totalmem()
  return {
    cpu,
    memUsed: total - freemem(),
    memTotal: total,
    appMem: process.memoryUsage().rss,
    cores: cpus().length,
    load1: platform() === 'win32' ? 0 : Number(loadavg()[0].toFixed(2)),
  }
}

/** Start pushing `system:stats` to every open window. Idempotent. */
export function startSystemStats(): void {
  if (timer) return
  previous = sampleCpu()
  timer = setInterval(() => {
    const windows = BrowserWindow.getAllWindows().filter((w) => !w.isDestroyed())
    if (windows.length === 0) return
    const stats = read()
    for (const win of windows) {
      try {
        win.webContents.send('system:stats', stats)
      } catch {
        /* a window closing mid-send is not an error */
      }
    }
  }, INTERVAL_MS)
  // Never hold the process open for a status bar.
  timer.unref?.()
}

export function stopSystemStats(): void {
  if (timer) clearInterval(timer)
  timer = null
}

/** One reading, for a window that just opened and should not wait 2s. */
export function currentSystemStats(): SystemStats {
  return read()
}
