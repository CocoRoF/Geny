/**
 * Vault loading, one question at a time.
 *
 * Opening the Opsidian tab used to cost the whole vault: the full index
 * (every note's metadata AND its first paragraph — 3.2s and 4.8 MB of
 * bodies parsed on the production vault) plus the whole knowledge graph
 * (5,384 nodes, 4.3 MB of JSON), before the operator had asked to see
 * anything at all.
 *
 * Nothing on that first screen needs any of it. A sidebar needs counts.
 * A category needs its days. A day needs its notes' titles. A note needs
 * its body — and only then. Each step below fetches exactly its own step
 * and nothing beyond, so cost tracks what was actually opened:
 *
 *   openVault        counts per category + per day     1.2 ms
 *   loadCategoryDays one category's day buckets        1.1 ms
 *   loadDay          one day's notes, metadata only    4.0 ms / 38 KB
 *   (readFile)       one note's body                   unchanged
 *
 * `ensureFullIndex` is the deliberate exception: the tag map and
 * backlinks are whole-vault questions, so the panels that ask them pay
 * for the full index — once, on demand, instead of on every open.
 */

import { memoryApi } from '@/lib/api';
import { useOpsidianStore } from '@/store/useOpsidianStore';
import type { MemoryDayNote, MemoryFileInfo } from '@/types';

/** Time-series categories: their notes are read by date, so the sidebar
 *  expands them one day at a time rather than as one flat list. */
export const DATE_GROUPED_CATEGORIES = new Set([
  'daily',
  'observations',
  'executions',
  'dms',
]);

/** Catalogue row → the store's file shape.
 *
 * The catalogue has no bodies, tags or links — those live in the note
 * itself and arrive with `readFile`. The empty arrays are honest: they
 * say "not loaded", and every consumer already treats them as such.
 */
function toFileInfo(n: MemoryDayNote): MemoryFileInfo {
  return {
    filename: n.filename,
    node_id: n.id,
    title: n.title || n.filename,
    category: n.category || 'root',
    tags: [],
    importance: n.pinned ? 'critical' : 'medium',
    created: n.updated_at || '',
    modified: n.updated_at || '',
    source: '',
    char_count: n.char_count || 0,
    links_to: [],
    linked_from: [],
    summary: null,
  };
}

function indexByFilename(notes: MemoryDayNote[]): Record<string, MemoryFileInfo> {
  const out: Record<string, MemoryFileInfo> = {};
  for (const n of notes) out[n.filename] = toFileInfo(n);
  return out;
}

// ── opening a note ───────────────────────────────────────────────────
//
// "Show me this note" was written out five times — the sidebar, the tab
// strip, search, the conversation list, a wikilink — and three of the
// five forgot to switch to the editor. So clicking a note in the sidebar
// while the graph was open re-seeded the graph and never showed the note:
// the click did something, just not the thing it said.
//
// One function, because five copies proved the invariant cannot live in
// five heads: choosing a note IS asking to read it.

/** Guards against a slow response overwriting a newer selection: click A
 *  then B quickly and A's body must not land in B's editor. */
let openSeq = 0;

export async function openNote(
  sessionId: string | null,
  filename: string,
): Promise<void> {
  const store = useOpsidianStore.getState();
  const seq = ++openSeq;

  store.openFile(filename);      // selection + tab
  store.setViewMode('editor');   // the part three call sites kept forgetting

  if (!sessionId) return;
  try {
    const detail = await memoryApi.readFile(sessionId, filename);
    if (seq !== openSeq) return; // a newer click already won
    store.setFileDetail(detail);
  } catch (e) {
    if (seq !== openSeq) return;
    console.error(`Failed to read ${filename}:`, e);
  }
}

/** Step 1 — counts only. What the sidebar renders before anything is
 *  expanded. */
export async function openVault(sessionId: string): Promise<void> {
  const store = useOpsidianStore.getState();
  const [overview, cats, totals] = await Promise.all([
    memoryApi.getOverview(sessionId),
    memoryApi.listCategories(sessionId),
    // 136 bytes against the index's megabytes: enough for the stats panels
    // to show the vault's real size instead of zeros.
    memoryApi.getStats(sessionId).catch(() => null),
  ]);
  store.setOverview(overview);
  store.setCategories(cats.categories || []);
  if (totals) {
    store.setVaultTotals({
      total_files: Number(totals.total_files) || 0,
      total_chars: Number((totals as { total_chars?: number }).total_chars) || 0,
      categories: totals.categories || {},
    });
  }
}

/** Step 2 — one category's day buckets (date-grouped categories), or its
 *  notes (everything else, which is small by nature). */
export async function loadCategory(
  sessionId: string,
  category: string,
): Promise<void> {
  const store = useOpsidianStore.getState();
  if (DATE_GROUPED_CATEGORIES.has(category)) {
    if (store.daysByCategory[category]) return; // already known
    const overview = await memoryApi.getOverview(sessionId, { kind: category });
    store.setCategoryDays(category, overview.days);
    return;
  }
  const key = `cat:${category}`;
  if (store.loadedDays[key]) return;
  const res = await memoryApi.listFiles(sessionId, { category, limit: 500 });
  const merged: Record<string, MemoryFileInfo> = {};
  for (const f of res.files || []) {
    merged[f.filename] = {
      filename: f.filename,
      title: f.title || f.filename,
      category: f.category || category,
      tags: f.tags || [],
      importance: f.importance || 'medium',
      created: f.created || f.modified || '',
      modified: f.modified || '',
      source: f.source || '',
      char_count: f.char_count || 0,
      links_to: f.links_to || [],
      linked_from: f.linked_from || [],
      summary: f.first_paragraph ?? null,
    } as MemoryFileInfo;
  }
  store.mergeFiles(merged);
  store.markDayLoaded(key);
}

/** Step 3 — one day's notes. Still metadata only; bodies wait for a
 *  click on an actual note. */
export async function loadDay(
  sessionId: string,
  category: string,
  day: string,
): Promise<void> {
  const store = useOpsidianStore.getState();
  const key = `${category}/${day}`;
  if (store.loadedDays[key]) return;
  const res = await memoryApi.getDay(sessionId, day, {
    kind: category,
    limit: 500,
  });
  store.mergeFiles(indexByFilename(res.notes || []));
  store.markDayLoaded(key);
}

/** The whole-vault index — tag map and backlinks. Fetched on demand,
 *  once per session, by the panels that genuinely need a global answer. */
export async function ensureFullIndex(sessionId: string): Promise<void> {
  const store = useOpsidianStore.getState();
  if (store.fullIndexLoaded) return;
  const res = await memoryApi.getIndex(sessionId);
  store.setMemoryIndex(res.index);
  store.setMemoryStats(res.stats);
  store.mergeFiles(res.index.files);
  store.setFullIndexLoaded(true);
}

/** The index stores `importance` as a ranking WEIGHT (REAL, default 1.0);
 *  the UI colours by a LABEL. Only a genuine label survives — anything
 *  numeric, null, or unexpected becomes the neutral one, because a weight
 *  is not a quieter way of saying "high". */
function importanceLabel(raw: unknown, pinned?: boolean): string {
  if (typeof raw === 'string') {
    const label = raw.toLowerCase();
    if (label === 'critical' || label === 'high' || label === 'medium' || label === 'low') {
      return label;
    }
  }
  return pinned ? 'critical' : 'medium';
}

/**
 * The graph around a seed, at the scale a screen is read at.
 *
 * `/memory/graph` answers a different question — the whole vault, as a
 * 4.3 MB download — and is kept for small vaults. This asks for a
 * neighbourhood and reports when it had to stop, so opening the tab
 * costs a subgraph rather than an archive (3.3 ms / 139 KB measured).
 *
 * Seed order: the selected note if there is one, otherwise the newest
 * day the catalogue knows about. With no seed at all it renders empty
 * rather than falling back to the whole vault — the download must never
 * be what happens by default.
 *
 * Returns `truncated` so the caller can say so in the UI.
 */
export async function loadGraphAround(
  sessionId: string,
  opts: { node?: string; day?: string; depth?: number; maxNodes?: number } = {},
): Promise<{ truncated: boolean; count: number }> {
  const store = useOpsidianStore.getState();
  let { node, day } = opts;
  if (!node && !day) {
    node = store.selectedFile ?? undefined;
    if (!node) day = store.overview?.days?.[0]?.day;
  }
  if (!node && !day) {
    // Nothing to centre on — that is a finished answer, not a pending one.
    store.setGraphData([], []);
    store.setGraphTruncated(false);
    store.setGraphStatus('ready');
    return { truncated: false, count: 0 };
  }
  store.setGraphStatus('loading');

  // The sidebar and the editor speak FILENAMES; the index speaks ids of
  // the form `<scope>/<category>/<filename>` — a shape that includes the
  // scope, which the browser has no way to know. Building one here
  // produced `<category>/<filename>`, matched nothing, and left the graph
  // empty for exactly as long as a note was selected.
  //
  // So: use the id the catalogue already handed us, and when we do not
  // have one (a note opened from search, a wikilink, the digest), let the
  // server resolve the filename. Either way the client never invents it.
  const info = node ? store.files[node] : undefined;
  const seedIds = info?.node_id ? [info.node_id] : undefined;
  const seedFile = node && !seedIds ? node : undefined;

  const res = await memoryApi.getGraphAround(sessionId, {
    node: seedIds,
    file: seedFile,
    day,
    depth: opts.depth ?? 1,
    maxNodes: opts.maxNodes ?? 300,
  });

  const nodes = (res.nodes || []).map((n) => ({
    id: n.id,
    label: n.title || n.id.split('/').pop() || n.id,
    category: n.kind || 'root',
    // `importance` in the INDEX is a ranking weight (a REAL, default 1.0),
    // not the 'critical' | 'high' | 'medium' | 'low' label the graph colours
    // by — and Geny never writes a label there at all. Passing the number
    // through crashed the whole graph tab on `.toLowerCase()`. The index
    // cannot answer this question, so say so with a neutral label rather
    // than dressing a weight up as one.
    importance: importanceLabel(n.importance_label ?? n.importance, n.pinned),
    charCount: n.text_len,
  }));
  const edges = (res.edges || []).map((e) => ({
    source: e.src,
    target: e.dst,
    type: (e.type as 'wikilink' | 'tag' | 'backlink' | 'semantic') || 'wikilink',
    weight: e.w,
  }));
  store.setGraphData(nodes, edges);
  store.setGraphTruncated(!!res.truncated);
  store.setGraphStatus('ready');
  return { truncated: !!res.truncated, count: nodes.length };
}

/** Drop everything cached for the previous session. */
export function resetVault(): void {
  const store = useOpsidianStore.getState();
  store.setOverview(null);
  store.setFiles({});
  store.setMemoryIndex(null);
  store.setFullIndexLoaded(false);
  store.setGraphData([], []);
  store.setGraphStatus('idle');
  store.setGraphTruncated(false);
  useOpsidianStore.setState({ daysByCategory: {}, loadedDays: {} });
}
