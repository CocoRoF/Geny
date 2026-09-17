/**
 * Launch the smoke app in a real Electron.
 *
 * It exists for one environment variable. `ELECTRON_RUN_AS_NODE=1` is set by
 * some shells and by every agent harness that embeds a node runtime, and with
 * it set the `electron` binary runs your file as a plain node script — where
 * `require('electron')` has no `app` on it and the smoke fails with a
 * TypeError that has nothing to do with the window. Deleting the variable for
 * the child is the whole job.
 */
import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const electron = createRequire(import.meta.url)('electron')

const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE

// `--live` swaps the app's entry point: same window, real server behind it.
// `--shot` writes a PNG of it, because a design cannot be reviewed by
// reading its stylesheet.
const args = [here, '--no-sandbox', ...process.argv.slice(2)]
if (process.argv.includes('--live')) env.GENY_SMOKE_ENTRY = 'live'
if (process.argv.includes('--shot')) env.GENY_SMOKE_ENTRY = 'shot'

const child = spawn(electron, args, { stdio: 'inherit', env })
child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)))
