/**
 * Client-side manifest diff — mirrors the shape and semantics of
 * `EnvironmentService.diff` in `backend/service/environment/service.py`
 * so ImportManifestModal can preview "current vs incoming" without
 * needing a round-trip to `/api/environments/diff` (which compares two
 * *stored* envs by id, not an id vs a pasted blob).
 *
 * Path convention: dict keys via `.key`, list items via `[i]` — matches
 * the backend format and `EnvironmentDiffResult` field names used by
 * `EnvironmentDiffModal`.
 */

export interface ManifestDiffChange {
  path: string;
  before: unknown;
  after: unknown;
}

export interface ManifestDiffSummary {
  added: string[];
  removed: string[];
  changed: ManifestDiffChange[];
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function walk(
  old: unknown,
  next: unknown,
  prefix: string,
  out: ManifestDiffSummary,
): void {
  if (isPlainObject(old) && isPlainObject(next)) {
    const keys = Array.from(new Set([...Object.keys(old), ...Object.keys(next)])).sort();
    for (const k of keys) {
      const path = prefix ? `${prefix}.${k}` : k;
      if (!(k in old)) {
        out.added.push(path);
      } else if (!(k in next)) {
        out.removed.push(path);
      } else {
        walk(old[k], next[k], path, out);
      }
    }
    return;
  }
  if (Array.isArray(old) && Array.isArray(next)) {
    const len = Math.max(old.length, next.length);
    for (let i = 0; i < len; i++) {
      const path = `${prefix}[${i}]`;
      if (i >= old.length) {
        out.added.push(path);
      } else if (i >= next.length) {
        out.removed.push(path);
      } else {
        walk(old[i], next[i], path, out);
      }
    }
    return;
  }
  if (!shallowEqual(old, next)) {
    out.changed.push({ path: prefix || '(root)', before: old, after: next });
  }
}

function shallowEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a === null || b === null) return a === b;
  if (typeof a !== typeof b) return false;
  if (typeof a !== 'object') return false;
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}

export function diffManifests(
  current: unknown,
  incoming: unknown,
): ManifestDiffSummary {
  const out: ManifestDiffSummary = { added: [], removed: [], changed: [] };
  walk(current ?? {}, incoming ?? {}, '', out);
  return out;
}
