/**
 * The icon set, drawn rather than imported.
 *
 * A 2MB icon package for fourteen glyphs is a poor trade in an app that
 * already ships a 2MB font. These are the Lucide shapes Dex uses, at the
 * same 1.8 stroke, so the two apps' chrome matches.
 */
import type { ReactNode } from 'react'

function Svg({ children, size = 18 }: { children: ReactNode; size?: number }): ReactNode {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  )
}

export const Icon = {
  paperclip: (
    <Svg size={16}>
      <path d="m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" />
    </Svg>
  ),
  monitor: (
    <Svg size={16}>
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8" />
      <path d="M12 17v4" />
    </Svg>
  ),
  volume: (
    <Svg size={15}>
      <path d="M11 5 6 9H2v6h4l5 4V5z" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M19 5a10 10 0 0 1 0 14" />
    </Svg>
  ),
  mic: (
    <Svg size={15}>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M19 10v1a7 7 0 0 1-14 0v-1" />
      <path d="M12 18v4" />
    </Svg>
  ),
  headset: (
    <Svg size={15}>
      <path d="M3 14v-3a9 9 0 0 1 18 0v3" />
      <path d="M21 16a2 2 0 0 1-2 2h-1v-6h1a2 2 0 0 1 2 2z" />
      <path d="M3 16a2 2 0 0 0 2 2h1v-6H5a2 2 0 0 0-2 2z" />
    </Svg>
  ),
  captions: (
    <Svg size={15}>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M7 15h4" />
      <path d="M15 15h2" />
      <path d="M7 11h2" />
      <path d="M13 11h4" />
    </Svg>
  ),
  talk: (
    <Svg size={15}>
      <circle cx="12" cy="12" r="9" />
      <rect x="10" y="7" width="4" height="7" rx="2" />
      <path d="M8.5 12.5a3.5 3.5 0 0 0 7 0" />
    </Svg>
  ),
  avatar: (
    <Svg size={15}>
      <circle cx="12" cy="12" r="9" />
      <path d="M8.5 14.5a4.5 4.5 0 0 0 7 0" />
      <path d="M9 9.5h.01" />
      <path d="M15 9.5h.01" />
    </Svg>
  ),
  chat: (
    <Svg>
      <path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.6 8.6 0 0 1-3.8-.9L3 21l1.9-5.1A8.4 8.4 0 0 1 12 3.1a8.4 8.4 0 0 1 9 8.4z" />
    </Svg>
  ),
  activity: (
    <Svg>
      <path d="M3 12h4l3 8 4-16 3 8h4" />
    </Svg>
  ),
  settings: (
    <Svg>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </Svg>
  ),
  plus: (
    <Svg size={16}>
      <path d="M12 5v14M5 12h14" />
    </Svg>
  ),
  refresh: (
    <Svg size={16}>
      <path d="M21 12a9 9 0 1 1-2.6-6.4" />
      <path d="M21 3v6h-6" />
    </Svg>
  ),
  send: (
    <Svg size={17}>
      <path d="m22 2-7 20-4-9-9-4 20-7z" />
    </Svg>
  ),
  stop: (
    <Svg size={15}>
      <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none" />
    </Svg>
  ),
  eye: (
    <Svg size={16}>
      <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z" />
      <circle cx="12" cy="12" r="3" />
    </Svg>
  ),
  check: (
    <Svg size={12}>
      <path d="m20 6-11 11-5-5" />
    </Svg>
  ),
  alert: (
    <Svg size={14}>
      <path d="M12 9v4M12 17h.01" />
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
    </Svg>
  ),
  chevron: (
    <Svg size={12}>
      <path d="m9 18 6-6-6-6" />
    </Svg>
  ),
  bot: (
    <Svg size={14}>
      <rect x="4" y="8" width="16" height="12" rx="2" />
      <path d="M12 8V4M9 13h.01M15 13h.01M9.5 17h5" />
    </Svg>
  ),
  folderOpen: (
    <Svg size={14}>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1" />
      <path d="M3 9h18l-2 9a2 2 0 0 1-2 1.6H6.6A2 2 0 0 1 4.6 18z" />
    </Svg>
  ),
  folder: (
    <Svg size={14}>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </Svg>
  ),
  files: (
    <Svg>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </Svg>
  ),
  close: (
    <Svg size={14}>
      <path d="M18 6 6 18M6 6l12 12" />
    </Svg>
  ),
  // ── tool kinds ──
  terminal: (
    <Svg size={14}>
      <path d="m4 17 6-6-6-6M12 19h8" />
    </Svg>
  ),
  file: (
    <Svg size={14}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </Svg>
  ),
  edit: (
    <Svg size={14}>
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
      <path d="M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4z" />
    </Svg>
  ),
  search: (
    <Svg size={14}>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </Svg>
  ),
  web: (
    <Svg size={14}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18z" />
    </Svg>
  ),
  tool: (
    <Svg size={14}>
      <path d="M14.7 6.3a4 4 0 0 1 5 5L21 12l-9 9-3-3 9-9z" />
      <path d="m3 21 4-4" />
    </Svg>
  ),
  package: (
    <Svg size={14}>
      <path d="m12 2 9 5v10l-9 5-9-5V7z" />
      <path d="m3 7 9 5 9-5M12 12v10" />
    </Svg>
  ),
  list: (
    <Svg size={14}>
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
    </Svg>
  ),
}

/**
 * Which badge a tool wears. The name is all we get, and the point is only to
 * make a run of twenty calls scannable by colour before it is readable by
 * name — so an unknown tool gets the neutral badge rather than a guess.
 */
export function toolKind(name?: string): keyof typeof KIND_ICON {
  const n = (name ?? '').toLowerCase()
  if (/bash|shell|terminal|exec|run|command/.test(n)) return 'terminal'
  if (/edit|write|create|patch|apply/.test(n)) return 'edit'
  if (/read|cat|view|file|ls|glob/.test(n)) return 'file'
  if (/search|grep|find|lookup/.test(n)) return 'search'
  if (/web|fetch|http|browser|url/.test(n)) return 'web'
  if (n.startsWith('mcp__')) return 'external'
  return 'tool'
}

/** The badges the shared tool model names. */
export const KIND_ICON: Record<string, ReactNode> = {
  terminal: Icon.terminal,
  package: Icon.package,
  file: Icon.file,
  edit: Icon.edit,
  search: Icon.search,
  web: Icon.web,
  list: Icon.list,
  external: Icon.tool,
  tool: Icon.tool,
}
