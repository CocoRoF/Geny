/**
 * The window's top bar, drawn by the app.
 *
 * The OS title bar and the "Geny · 편집 · 보기" menu row are gone; this is
 * the strip you drag the window by. On Windows and Linux the OS paints only
 * its three buttons over the right end (main keeps their colours equal to
 * this bar's); on macOS the traffic lights sit at the left, so the bar
 * starts after them.
 */
import type { ReactNode } from 'react'

export function TitleBar({ context }: { context: string | null }): ReactNode {
  const mac = window.connector?.platform === 'darwin'
  return (
    <header className={`titlebar ${mac ? 'mac' : ''}`}>
      <span className="titlebar-app">Geny</span>
      {context && (
        <>
          <span className="titlebar-sep" />
          <span className="titlebar-context" title={context}>{context}</span>
        </>
      )}
    </header>
  )
}

export default TitleBar
