/**
 * The avatar list, arranged the way a person picks from it.
 *
 * Free of React and of the bridge so it runs under `node:test`.
 */
import type { AvatarModel } from '../server'

export type AvatarRuntime = 'live2d' | 'mmd' | 'spine' | 'other'

export interface AvatarGroup {
  runtime: AvatarRuntime
  models: AvatarModel[]
}

const ORDER: AvatarRuntime[] = ['live2d', 'mmd', 'spine', 'other']

function runtimeOf(model: AvatarModel): AvatarRuntime {
  const r = (model.runtime || 'live2d').toLowerCase()
  return r === 'live2d' || r === 'mmd' || r === 'spine' ? r : 'other'
}

/**
 * Grouped by what kind of puppet it is (2D, 3D, …), groups in a fixed order,
 * and alphabetical inside a group — the registry's own order is install
 * order, which puts "Editor 12" above "Editor 2" and reads as random.
 */
export function groupAvatars(models: AvatarModel[]): AvatarGroup[] {
  const byRuntime = new Map<AvatarRuntime, AvatarModel[]>()
  for (const model of models) {
    const runtime = runtimeOf(model)
    const list = byRuntime.get(runtime) ?? []
    list.push(model)
    byRuntime.set(runtime, list)
  }
  const collator = new Intl.Collator(['ko', 'en'], { numeric: true, sensitivity: 'base' })
  // Brackets are presentation: compared as-is, "Chisa (Editor)" sorts AFTER
  // "Chisa (Editor 12)" because ')' comes after the digits — the original
  // export last, behind its own copies.
  const key = (m: AvatarModel): string =>
    (m.display_name || m.name).replace(/[()[\]]/g, ' ').replace(/\s+/g, ' ').trim()
  return ORDER.filter((r) => byRuntime.has(r)).map((runtime) => ({
    runtime,
    models: (byRuntime.get(runtime) ?? []).slice().sort((a, b) => collator.compare(key(a), key(b))),
  }))
}

/** What the button says: the worn avatar's name, or `null` for none. */
export function wornLabel(models: AvatarModel[], worn: string | null): string | null {
  if (!worn) return null
  const model = models.find((m) => m.name === worn)
  // Assigned to something the list does not (yet) have — say its name rather
  // than claiming there is no avatar.
  return model ? model.display_name || model.name : worn
}
