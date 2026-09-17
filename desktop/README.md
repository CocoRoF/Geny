# Geny Connector (desktop)

The desktop app for Geny. Two surfaces, one process:

- **The workspace** — sessions on the left, the conversation in the middle with
  each tool call as a line you can open, and the ledger of what the agent
  actually did to your files on the right. The model picker in the header
  switches the live session's route mid-conversation, and says when a fallback
  answered instead of the account you pointed at.
- **The avatar** — an always-on-top, click-through overlay that renders the live
  VTuber at the bottom of your desktop, with a quick-chat bar on a global hotkey.

The Geny **server** stays the brain (agent pipeline, memory, TTS/STT synthesis,
avatar state). This app is where you watch it work and tell it what to do.

The workspace used to be the server's `/connector` web page in a frame. It is
the connector's own renderer now, over the same execute socket the phone uses —
`shared/chat/` holds the socket and the log→conversation fold, and both apps
import it, so the desktop cannot drift from the phone about what happened.

## Download & run (git-clonable)

```bash
git clone https://github.com/CocoRoF/Geny.git
cd Geny/desktop
npm install            # pulls electron + electron-vite + react
npm run dev            # launches the workspace + the avatar overlay
```

The overlay floats at the bottom-right; **drag the glowing handle** to move it,
**double-click** it to toggle the workspace. In the settings window enter
your Geny **server URL**, click **연결 확인**, then **로그인** — the account JWT is
stored in the OS keychain (Keychain / Credential Manager / libsecret) and used as
`Authorization: Bearer` for the (now-authenticated) server API.

Set a default server without the UI:

```bash
GENY_SERVER_URL=https://gapt.example.com npm run dev
```

## Build installers

```bash
npm run dist:linux     # AppImage + deb
npm run dist:win       # NSIS
npm run dist:mac       # dmg   (ad-hoc signed — see build/afterPack.cjs)
```

### macOS Gatekeeper

The mac build is **ad-hoc signed** (`build/afterPack.cjs`), not notarized — so it
runs on Apple Silicon (no "손상됨 / damaged" hard block) but the first launch shows
the "확인되지 않은 개발자" prompt: **right-click → Open**, or System Settings →
Privacy & Security → **Open Anyway**. If a download is still blocked as *damaged*
(e.g. an older unsigned build), strip the quarantine flag (always works):

```bash
xattr -dr com.apple.quarantine "/Applications/Geny.app"
```

To ship with **no** prompt, set an Apple Developer ID (`CSC_LINK` +
`CSC_KEY_PASSWORD`) and notarization secrets (`APPLE_ID`,
`APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`) in CI — the afterPack ad-hoc pass
then no-ops and electron-builder signs + notarizes for real.

## Architecture

```
src/main/index.ts      Electron main: overlay (transparent/frameless/always-on-top/
                       click-through) + control window, single renderer process,
                       config JSON, keychain IPC.
src/preload/index.ts   contextBridge → window.connector (serverConfig, secureStore,
                       windowControl). The renderer NEVER imports electron directly,
                       so a Tauri backend could swap in behind the same shape.
src/renderer/          React 19 app; ?window= selects the tree:
                         control   → chat/ChatApp (the workspace, main window)
                         settings  → ControlApp (server, account, models, MCP…)
                         overlay   → the avatar (loads the server's /overlay)
                         quickchat → the floating hotkey input
                         chip      → the locked avatar's tiny control
../shared/chat/        The socket + the fold, shared with mobile/. Both test
                       runners run its tests.
```

### Reusing the browser renderer

`electron.vite.config.ts` aliases `@geny → ../frontend/src`, so the avatar
surface can import the existing canvases, the audio engine and the stores
directly. The workspace deliberately does NOT: it is native React over the
server's REST + WS, because a chat window that is a web page in a frame cannot
answer the questions you have while an agent is working.

### Tests

    npm test     typecheck-adjacent suites + the shared chat core
    npm run smoke   opens the real window headless and checks it painted

`npm run smoke -- --live` (via `node tests/smoke/run.mjs --live`) points that
same window at a real server with a real token; `--send` also sends a message
and waits for the answer. Manual — it needs a server and a secret.

## Connector API v1 (server contract)

The connector speaks the **existing** Geny endpoints (no new protocol):

- WS `/ws/execute/{id}`, `/ws/vtuber/agents/{id}/state`, `/ws/chat/rooms/{id}`
  — JWT carried via the `Sec-WebSocket-Protocol: geny-auth,<jwt>` subprotocol
  (browsers) or the `Authorization` header (desktop).
- REST `POST /api/chat/rooms/{room}/broadcast`, `POST /api/tts/.../speak/chunks`,
  `POST /api/vtuber/screen-observation/upload`.

All of these were authenticated in **Phase 1a** (PR #875). The desktop sends the
keychain JWT as a Bearer header.
