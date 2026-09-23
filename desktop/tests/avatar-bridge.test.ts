/**
 * The relay between the avatar window and every other window.
 *
 * The avatar window runs the server's page with the microphone and the screen
 * open; the chat and the chip ask it to switch voice, mic, hands-free and
 * screen observation, and read what it reports. Main relays both ways, and
 * this is the contract it relays by: what may be asked, what a report holds.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { MAX_SPEAK_CHARS, SWITCHES, cleanCommand, cleanState } from '../src/main/avatar-bridge'

test('every switch the avatar has can be set, with a boolean', () => {
  for (const key of SWITCHES) {
    assert.deepEqual(cleanCommand({ type: 'set', key, value: true }), { type: 'set', key, value: true })
    assert.deepEqual(cleanCommand({ type: 'set', key, value: false }), { type: 'set', key, value: false })
  }
})

test('a switch the avatar does not have is not forwarded', () => {
  assert.equal(cleanCommand({ type: 'set', key: 'camera', value: true }), null)
  assert.equal(cleanCommand({ type: 'set', key: '__proto__', value: true }), null)
})

test('a value that is not a boolean is not a switch', () => {
  assert.equal(cleanCommand({ type: 'set', key: 'tts', value: 'on' }), null)
  assert.equal(cleanCommand({ type: 'set', key: 'tts', value: 1 }), null)
  assert.equal(cleanCommand({ type: 'set', key: 'tts' }), null)
})

test('read-aloud carries trimmed text, and nothing when there is none', () => {
  assert.deepEqual(cleanCommand({ type: 'speak', text: '  [joy] 안녕  ' }), { type: 'speak', text: '[joy] 안녕' })
  assert.equal(cleanCommand({ type: 'speak', text: '   ' }), null)
  assert.equal(cleanCommand({ type: 'speak', text: 42 }), null)
})

test('read-aloud is capped — an answer, not a document', () => {
  const said = cleanCommand({ type: 'speak', text: 'a'.repeat(MAX_SPEAK_CHARS * 2) })
  assert.ok(said && said.type === 'speak')
  assert.equal(said.text.length, MAX_SPEAK_CHARS)
})

test('hush takes nothing; anything unnamed is dropped', () => {
  assert.deepEqual(cleanCommand({ type: 'hush', extra: 'x' }), { type: 'hush' })
  assert.equal(cleanCommand({ type: 'eval', code: 'x' }), null)
  assert.equal(cleanCommand(null), null)
  assert.equal(cleanCommand('hush'), null)
})

test('a report keeps only the fields it names, as booleans', () => {
  const s = cleanState({ sessionId: 's1', tts: true, stt: 'yes', screen: true, extra: 'x' })
  assert.deepEqual(s, {
    sessionId: 's1', tts: true, stt: false, realtime: false, captions: false,
    screen: true, ptt: false, speaking: false, listening: false,
  })
})

test('a report with no session says so; a non-report is none', () => {
  assert.equal(cleanState({ sessionId: '' })?.sessionId, null)
  assert.equal(cleanState({})?.sessionId, null)
  assert.equal(cleanState(null), null)
  assert.equal(cleanState('state'), null)
})
