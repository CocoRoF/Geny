/**
 * The connector's test runner.
 *
 * Every file here passed when it was written and was then only ever run by
 * hand, one `npx tsx` at a time — which is the same as not running them. A
 * suite nothing invokes reports nothing when it breaks.
 *
 * `sync-prod-e2e.ts` is deliberately absent: it talks to the production
 * server and needs credentials, so it stays a manual tool.
 *
 * `shared/chat/` is included from outside this package on purpose: the chat
 * core belongs to both the connector and the phone, and a break in it has to
 * fail whichever one you are working on — not only the other.
 *
 * Run: npm test
 */
import { spawnSync } from 'node:child_process'
import { readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const MANUAL = new Set(['sync-prod-e2e.ts', 'run-all.ts'])

const files = readdirSync(here)
  .filter((f) => (f.endsWith('.test.ts') || f.endsWith('.probe.ts')) && !MANUAL.has(f))
  .sort()
  .map((f) => join(here, f))

const sharedDir = join(here, '..', '..', 'shared', 'chat')
const shared = readdirSync(sharedDir)
  .filter((f) => f.endsWith('.test.ts'))
  .sort()
  .map((f) => join(sharedDir, f))

if (files.length === 0) {
  console.error('no test files found — the glob or the directory moved')
  process.exit(1)
}

let failed = 0
// The shared suites are `node:test` files; the connector's own are scripts
// that throw. `tsx --test` runs the first kind, plain `tsx` the second.
for (const f of files) {
  const r = spawnSync('npx', ['tsx', f], { stdio: 'inherit' })
  if (r.status !== 0) {
    failed++
    console.error(`\n✗ ${f} exited ${r.status}`)
  }
}
if (shared.length > 0) {
  const r = spawnSync('npx', ['tsx', '--test', ...shared], { stdio: 'inherit' })
  if (r.status !== 0) {
    failed++
    console.error(`\n✗ shared/chat exited ${r.status}`)
  }
}

const total = files.length + (shared.length > 0 ? 1 : 0)
console.log(`\n${total - failed}/${total} suites passed`)
process.exit(failed === 0 ? 0 : 1)
