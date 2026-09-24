import React from 'react'
import ReactDOM from 'react-dom/client'
import { OverlayApp } from './OverlayApp'
import { ChatApp } from './chat/ChatApp'
import { QuickChatApp } from './QuickChatApp'
import { ChipApp } from './ChipApp'
import './styles.css'

// One renderer build serves the local windows; ?window=overlay → avatar
// placeholder, ?window=control → the chat workspace (the app's main window),
// ?window=quickchat → the floating Spotlight-style input bar,
// ?window=chip → the locked avatar's tiny control window.
const kind = window.connector?.windowKind ?? 'overlay'

const root =
  kind === 'overlay' ? <OverlayApp />
  : kind === 'quickchat' ? <QuickChatApp />
  : kind === 'chip' ? <ChipApp />
  : <ChatApp />  // control (settings is a tab of it)

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>{root}</React.StrictMode>,
)
