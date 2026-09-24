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
  user: (
    <Svg size={16}>
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </Svg>
  ),
  sliders: (
    <Svg size={16}>
      <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6" />
    </Svg>
  ),
  cpu: (
    <Svg size={16}>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <rect x="9" y="9" width="6" height="6" />
      <path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3" />
    </Svg>
  ),
  pointer: (
    <Svg size={16}>
      <path d="m4 4 7.07 17 2.51-7.39L21 11.07z" />
    </Svg>
  ),
  cloud: (
    <Svg size={16}>
      <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />
    </Svg>
  ),
  plug: (
    <Svg size={16}>
      <path d="M12 22v-5M9 8V2M15 8V2M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z" />
    </Svg>
  ),
  keyboard: (
    <Svg size={16}>
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8" />
    </Svg>
  ),
  info: (
    <Svg size={16}>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4M12 8h.01" />
    </Svg>
  ),
  sun: (
    <Svg size={14}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </Svg>
  ),
  moon: (
    <Svg size={14}>
      <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />
    </Svg>
  ),
  display: (
    <Svg size={14}>
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </Svg>
  ),
  appWindow: (
    <Svg size={14}>
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="M2 8h20M6 6h.01M9 6h.01" />
    </Svg>
  ),
  caretDown: (
    <Svg size={14}>
      <path d="m6 9 6 6 6-6" />
    </Svg>
  ),
  arrowUp: (
    <Svg size={14}>
      <path d="m18 15-6-6-6 6" />
    </Svg>
  ),
  arrowDown: (
    <Svg size={14}>
      <path d="m6 9 6 6 6-6" />
    </Svg>
  ),
  trash: (
    <Svg size={14}>
      <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </Svg>
  ),
  logout: (
    <Svg size={14}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
    </Svg>
  ),
  power: (
    <Svg size={14}>
      <path d="M12 2v10M18.4 6.6a9 9 0 1 1-12.77.04" />
    </Svg>
  ),
  copy: (
    <Svg size={14}>
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </Svg>
  ),
  download: (
    <Svg size={14}>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
    </Svg>
  ),
  key: (
    <Svg size={16}>
      <circle cx="7.5" cy="15.5" r="5.5" />
      <path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3" />
    </Svg>
  ),
  pause: (
    <Svg size={14}>
      <rect x="6" y="4" width="4" height="16" rx="1" />
      <rect x="14" y="4" width="4" height="16" rx="1" />
    </Svg>
  ),
  play: (
    <Svg size={14}>
      <path d="m6 3 14 9-14 9V3z" />
    </Svg>
  ),
  sync: (
    <Svg size={14}>
      <path d="M21 12a9 9 0 0 1-15 6.7L3 16M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M3 21v-5h5" />
    </Svg>
  ),
  openOut: (
    <Svg size={15}>
      <path d="M15 3h6v6" />
      <path d="M10 14 21 3" />
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    </Svg>
  ),
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
