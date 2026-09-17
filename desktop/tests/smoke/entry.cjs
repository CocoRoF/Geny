/**
 * Which smoke to run. `GENY_SMOKE_ENTRY` is set by run.mjs:
 *   live → the same window against a real server
 *   shot → capture a PNG of it
 * anything else runs the offline check that CI uses.
 */
const which = process.env.GENY_SMOKE_ENTRY
require(which === 'live' ? './live.cjs' : which === 'shot' ? './shot.cjs' : './main.cjs')
