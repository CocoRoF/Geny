/**
 * What a file IS, so the viewer can show it as that.
 *
 * Extension first, because it is what the agent and the user both think in,
 * and the server's own `binary` flag as the tiebreak: a `.log` full of bytes
 * is not text just because `.log` usually is.
 *
 * The list is long on purpose. "It opened as a wall of mojibake" and "it said
 * it could not show this" are both failures; the only good answer for a file
 * an agent wrote is to render it as what it is.
 */

export type FileKind =
  | 'image'      // png, jpg, webp, … — the bytes, drawn
  | 'svg'        // drawn too, but it is also text you may want to read
  | 'pdf'        // Chromium's viewer
  | 'doc'        // pptx / docx / xlsx — rendered to pages by the server
  | 'audio'
  | 'video'
  | 'markdown'
  | 'table'      // csv / tsv
  | 'json'       // pretty-printed and coloured
  | 'notebook'   // .ipynb — cells, not raw JSON
  | 'code'       // highlighted, with line numbers
  | 'text'       // line numbers, no guessing
  | 'archive'    // zip, tar — nothing to draw, say what it is
  | 'binary'

const EXT: Record<string, FileKind> = {}
const put = (kind: FileKind, exts: string): void => {
  for (const e of exts.split(' ')) EXT[e] = kind
}

put('image', 'png jpg jpeg gif webp bmp ico avif apng tif tiff heic heif')
put('svg', 'svg')
put('pdf', 'pdf')
put('doc', 'pptx docx xlsx ppt doc xls odt ods odp')
put('audio', 'mp3 wav ogg oga flac m4a aac opus')
put('video', 'mp4 webm mov mkv avi m4v')
put('markdown', 'md markdown mdx rst adoc')
put('table', 'csv tsv')
put('json', 'json jsonl ndjson geojson map')
put('notebook', 'ipynb')
put('archive', 'zip tar gz tgz bz2 xz 7z rar jar war whl deb rpm dmg iso')
put('binary', 'exe dll so dylib bin dat db sqlite sqlite3 pyc pyo class o a lib wasm woff woff2 ttf otf eot pkl npy npz safetensors pt pth onnx')

// Everything below is text the highlighter knows how to colour.
put('code',
  'ts tsx js jsx mjs cjs py pyi rb go rs java kt kts swift c h cpp cc cxx hpp hh '
  + 'cs php pl pm lua r jl scala clj cljs cljc edn ex exs erl hrl hs elm dart '
  + 'sh bash zsh fish ps1 psm1 bat cmd sql graphql gql proto thrift '
  + 'html htm xml xhtml vue svelte astro css scss sass less styl '
  + 'yml yaml toml ini cfg conf env properties gradle groovy tf tfvars hcl '
  + 'dockerfile containerfile makefile mk cmake nim zig v cr f90 f95 m mm asm s '
  + 'vim el lisp scm rkt pas pp ml mli fs fsx fsi sml tex bib sty cls patch diff')

/** Files that have no extension but are always the same thing. */
const BY_NAME: Record<string, FileKind> = {
  dockerfile: 'code',
  containerfile: 'code',
  makefile: 'code',
  cmakelists: 'code',
  'gemfile': 'code',
  'rakefile': 'code',
  'procfile': 'code',
  'jenkinsfile': 'code',
  '.gitignore': 'code',
  '.dockerignore': 'code',
  '.env': 'code',
  '.editorconfig': 'code',
  license: 'text',
  readme: 'markdown',
}

/** The highlighter's name for this extension, when it differs. */
const LANGUAGE: Record<string, string> = {
  ts: 'typescript', tsx: 'typescript', mts: 'typescript', cts: 'typescript',
  js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript',
  py: 'python', pyi: 'python', rb: 'ruby', rs: 'rust', kt: 'kotlin', kts: 'kotlin',
  h: 'c', hpp: 'cpp', hh: 'cpp', cc: 'cpp', cxx: 'cpp', 'c++': 'cpp',
  cs: 'csharp', pl: 'perl', pm: 'perl', ex: 'elixir', exs: 'elixir',
  erl: 'erlang', hrl: 'erlang', hs: 'haskell', clj: 'clojure', cljs: 'clojure',
  cljc: 'clojure', edn: 'clojure', jl: 'julia', m: 'matlab', mm: 'objectivec',
  sh: 'bash', zsh: 'bash', fish: 'bash', ps1: 'powershell', psm1: 'powershell',
  bat: 'dos', cmd: 'dos', htm: 'xml', html: 'xml', xhtml: 'xml', vue: 'xml',
  svelte: 'xml', astro: 'xml', yml: 'yaml', cfg: 'ini', conf: 'ini',
  env: 'bash', properties: 'ini', toml: 'ini', gradle: 'groovy',
  tf: 'hcl', tfvars: 'hcl', dockerfile: 'dockerfile', containerfile: 'dockerfile',
  makefile: 'makefile', mk: 'makefile', patch: 'diff', gql: 'graphql',
  scss: 'scss', sass: 'scss', less: 'less', styl: 'less', tex: 'latex',
  sty: 'latex', cls: 'latex', bib: 'latex', s: 'x86asm', asm: 'x86asm',
}

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : ''
}

/**
 * What to render this as.
 *
 * `binaryFlag` is the server saying the bytes are not text in this encoding.
 * It only ever downgrades: a `.py` full of NUL bytes is not Python, but a
 * `.png` the server happened to decode is still a PNG.
 */
export function kindOf(name: string, binaryFlag = false): FileKind {
  const lower = name.toLowerCase()
  const ext = extensionOf(lower)
  const declared = EXT[ext]
    ?? BY_NAME[lower]
    ?? BY_NAME[lower.split('.')[0]]
    ?? (ext ? undefined : 'text')

  if (declared && declared !== 'code' && declared !== 'text') return declared
  if (binaryFlag) return 'binary'
  return declared ?? 'text'
}

/** The highlighter's language id, or '' to let it guess. */
export function languageOf(name: string): string {
  const lower = name.toLowerCase()
  const ext = extensionOf(lower)
  return LANGUAGE[ext] ?? LANGUAGE[lower] ?? (ext || '')
}

/**
 * Not text. The explorer skips the text reader for these — asking it for a
 * 2 MB PNG, or a 400 MB model file, only to be told it is not text is a round
 * trip that answers nothing.
 */
export const NEEDS_BYTES: ReadonlySet<FileKind> = new Set<FileKind>([
  'image', 'pdf', 'audio', 'video', 'doc', 'binary', 'archive',
])

/**
 * The viewer can actually DRAW these, so it fetches the bytes.
 *
 * `binary` and `archive` are deliberately absent: there is nothing to draw,
 * and downloading a 4 GB checkpoint to display "4 GB" is the kind of thing an
 * app does once before you stop trusting it.
 */
export const DRAWS_BYTES: ReadonlySet<FileKind> = new Set<FileKind>([
  'image', 'svg', 'pdf', 'audio', 'video',
])
