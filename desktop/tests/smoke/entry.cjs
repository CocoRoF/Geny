/**
 * Which smoke to run. `GENY_SMOKE_ENTRY=live` (set by run.mjs --live) points
 * the same window at a real server; anything else runs the offline one that
 * CI uses.
 */
require(process.env.GENY_SMOKE_ENTRY === 'live' ? './live.cjs' : './main.cjs')
