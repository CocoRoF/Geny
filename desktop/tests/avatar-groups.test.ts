/**
 * The chat's avatar picker: how the list is arranged and what the button says.
 *
 * The native chat shipped without any way to change a VTuber's avatar — the
 * page it replaced had one in its header. The picker is back; this pins the
 * part of it that is logic rather than layout.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { groupAvatars, wornLabel } from '../src/renderer/src/chat/avatar-groups'

const m = (name: string, display: string, runtime?: string) => ({ name, display_name: display, runtime })

test('grouped by kind, in a fixed order, whatever order the registry has', () => {
  const groups = groupAvatars([
    m('c', 'Chisa', 'mmd'), m('h', 'Hiyori', 'live2d'), m('s', 'Spineboy', 'spine'), m('x', 'X', 'weird'),
  ])
  assert.deepEqual(groups.map((g) => g.runtime), ['live2d', 'mmd', 'spine', 'other'])
})

test('a registry entry without a runtime is Live2D (pre-v2 registries)', () => {
  assert.equal(groupAvatars([m('old', 'Old')])[0].runtime, 'live2d')
})

test('numbers sort as numbers — "Editor 12" does not come before "Editor 2"', () => {
  const [group] = groupAvatars([
    m('a', 'Chisa (Editor 12)', 'mmd'), m('b', 'Chisa (Editor 2)', 'mmd'), m('c', 'Chisa (Editor)', 'mmd'),
  ])
  assert.deepEqual(group.models.map((x) => x.display_name),
    ['Chisa (Editor)', 'Chisa (Editor 2)', 'Chisa (Editor 12)'])
})

test('the button names the worn avatar, or says there is none', () => {
  const models = [m('c', 'Chisa', 'mmd')]
  assert.equal(wornLabel(models, 'c'), 'Chisa')
  assert.equal(wornLabel(models, null), null)
})

test('an assignment the list does not have yet is named, not hidden', () => {
  assert.equal(wornLabel([], 'new_model'), 'new_model')
})
