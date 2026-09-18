/**
 * What a file IS decides how it is shown, and getting that wrong is visible
 * in one glance: a PNG as mojibake, a Python file as undifferentiated grey.
 *
 * The cases here are the ones with an actual decision in them — everything
 * else is a table lookup and the table is the source, not this.
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  DRAWS_BYTES, kindOf, languageOf, NEEDS_BYTES,
} from '../src/renderer/src/chat/file-kind'

test('the common shapes land in the right pane', () => {
  assert.equal(kindOf('chart.png'), 'image')
  assert.equal(kindOf('report.pdf'), 'pdf')
  assert.equal(kindOf('deck.pptx'), 'doc')
  assert.equal(kindOf('rows.csv'), 'table')
  assert.equal(kindOf('config.json'), 'json')
  assert.equal(kindOf('notes.md'), 'markdown')
  assert.equal(kindOf('run.py'), 'code')
  assert.equal(kindOf('analysis.ipynb'), 'notebook')
  assert.equal(kindOf('bundle.zip'), 'archive')
  assert.equal(kindOf('model.bin'), 'binary')
  assert.equal(kindOf('output.txt'), 'text')
})

test('a file with no extension is text, and the famous ones are known', () => {
  assert.equal(kindOf('LICENSE'), 'text')
  assert.equal(kindOf('Dockerfile'), 'code')
  assert.equal(kindOf('Makefile'), 'code')
  assert.equal(kindOf('.gitignore'), 'code')
  assert.equal(kindOf('notes'), 'text')
})

test('the binary flag downgrades text, and never a picture', () => {
  // A .py full of NUL bytes is not Python; a .png the server managed to
  // decode is still a PNG.
  assert.equal(kindOf('weird.py', true), 'binary')
  assert.equal(kindOf('notes.txt', true), 'binary')
  assert.equal(kindOf('chart.png', true), 'image')
  assert.equal(kindOf('report.pdf', true), 'pdf')
})

test('the highlighter is asked for a language it actually has', () => {
  assert.equal(languageOf('a.ts'), 'typescript')
  assert.equal(languageOf('a.tsx'), 'typescript')
  assert.equal(languageOf('run.py'), 'python')
  assert.equal(languageOf('deploy.sh'), 'bash')
  assert.equal(languageOf('index.html'), 'xml')
  assert.equal(languageOf('main.go'), 'go')
  assert.equal(languageOf('Dockerfile'), 'dockerfile')
  assert.equal(languageOf('values.yml'), 'yaml')
})

test('only the kinds that have no text are fetched as bytes', () => {
  for (const kind of ['image', 'pdf', 'audio', 'video', 'binary', 'archive'] as const) {
    assert.ok(NEEDS_BYTES.has(kind), `${kind} has no text to read`)
  }
  for (const kind of ['code', 'text', 'markdown', 'json', 'table', 'notebook'] as const) {
    assert.ok(!NEEDS_BYTES.has(kind), `${kind} is read as text`)
  }
})

test('an unknown extension is still shown, as text', () => {
  // The alternative is a viewer that shrugs at `.rpt`, which is worse than
  // showing the lines.
  assert.equal(kindOf('weekly.rpt'), 'text')
  assert.equal(kindOf('data.xyz'), 'text')
})

test('nothing is downloaded for a file that cannot be drawn', () => {
  // A 4 GB checkpoint is "binary, 4 GB" — fetching it to say so is the kind
  // of thing an app does once before you stop trusting it.
  for (const kind of ['binary', 'archive'] as const) {
    assert.ok(NEEDS_BYTES.has(kind), 'not text')
    assert.ok(!DRAWS_BYTES.has(kind), 'and not worth a download either')
  }
  for (const kind of ['image', 'svg', 'pdf', 'audio', 'video'] as const) {
    assert.ok(DRAWS_BYTES.has(kind), `${kind} is drawn from its bytes`)
  }
})
