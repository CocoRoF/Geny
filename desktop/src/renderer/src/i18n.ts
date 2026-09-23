// ─────────────────────────────────────────────────────────────────────────────
// i18n — ko/en message catalog + a tiny translator for the settings UI.
//
// Every user-facing string in the renderer settings surface (ControlApp.tsx)
// lives here keyed by a dotted name; the native chrome (tray/menu/dialogs) has
// its own small ko/en map in main/index.ts. Keep the two consistent: 접속기 =
// connector, 세션 = session, 아바타 = avatar, 오버레이 = overlay, 화면 캡처 =
// screen capture, 로컬 컴퓨터 제어 = Local Computer Use.
// ─────────────────────────────────────────────────────────────────────────────

export type Lang = 'ko' | 'en'

type Entry = { ko: string; en: string }

export const messages: Record<string, Entry> = {
  // ── header + tabs ──
  'app.subtitle': { ko: 'VTuber 데스크톱 접속기', en: 'VTuber desktop connector' },
  'tab.account': { ko: '계정', en: 'Account' },
  'account.passwordChange': { ko: '비밀번호 변경', en: 'Change password' },
  'account.passwordCurrent': { ko: '지금 비밀번호', en: 'Current password' },
  'account.passwordNew': { ko: '새 비밀번호', en: 'New password' },
  'account.passwordHint': {
    ko: '바꾸면 다른 기기는 모두 로그아웃됩니다. 이 접속기는 그대로 유지됩니다.',
    en: 'Changing it signs every other device out. This connector stays signed in.',
  },
  'account.passwordChanged': { ko: '비밀번호를 바꿨습니다 — 다른 기기는 로그아웃됐습니다', en: 'Password changed — every other device has been signed out' },
  'account.passwordFailed': { ko: '비밀번호 변경 실패 — {msg}', en: 'Could not change the password — {msg}' },
  'tab.models': { ko: '모델', en: 'Models' },
  'tab.agents': { ko: '에이전트', en: 'Agents' },
  'tab.voice': { ko: '음성', en: 'Voice' },
  'tab.control': { ko: '제어', en: 'Control' },
  'tab.mcp': { ko: 'MCP', en: 'MCP' },
  'tab.workspace': { ko: 'Workspace', en: 'Workspace' },
  'tab.app': { ko: '앱', en: 'App' },

  // ── hotkey capture (shared) ──
  'hotkey.recording': { ko: '키 조합을 누르세요…  (Esc 취소)', en: 'Press a key combination…  (Esc to cancel)' },
  'hotkey.idle': { ko: '클릭한 뒤 키 조합을 누르세요', en: 'Click, then press a key combination' },
  'hotkey.registered': { ko: '✓ 단축키가 등록되었습니다', en: '✓ Hotkey registered' },
  'hotkey.conflict': { ko: '✗ 다른 앱과 충돌 — 다른 조합을 시도하세요', en: '✗ Conflicts with another app — try a different combination' },

  // ── status messages (account) ──
  'status.initial': { ko: '연결 상태를 확인하세요', en: 'Check the connection status' },
  'status.connecting': { ko: '서버에 연결하는 중…', en: 'Connecting to the server…' },
  'status.connectedAuthed': { ko: '연결됨 · 로그인 상태', en: 'Connected · Signed in' },
  'status.connectedLoginNeeded': { ko: '연결됨 · 로그인 필요', en: 'Connected · Sign-in required' },
  'status.connectedSetupNeeded': { ko: '연결됨 · 초기 설정 필요', en: 'Connected · Initial setup required' },
  'status.connectFailed': { ko: '연결 실패 — {msg}', en: 'Connection failed — {msg}' },
  'status.loggingIn': { ko: '로그인하는 중…', en: 'Signing in…' },
  'status.loginFailedHttp': { ko: '로그인 실패 — HTTP {code}', en: 'Sign-in failed — HTTP {code}' },
  'status.loginOk': { ko: '{username} 님으로 로그인됨 — 아바타를 불러옵니다', en: 'Signed in as {username} — loading the avatar' },
  'status.keychainUnavailable': { ko: '로그인은 성공했지만 토큰을 저장하지 못했습니다 (보안 저장소 쓰기 실패). 디스크 상태를 확인하고 다시 시도하세요.', en: 'Login succeeded but the token could not be saved (secure-store write failed). Check disk space/permissions and retry.' },
  'status.loginError': { ko: '오류 — {msg}', en: 'Error — {msg}' },
  'status.loggedOut': { ko: '로그아웃되었습니다', en: 'Signed out' },

  // ── account tab ──
  'account.serverCard': { ko: '서버 연결', en: 'Server connection' },
  'account.serverUrlLabel': { ko: '서버 주소', en: 'Server URL' },
  'account.checkConnection': { ko: '연결 확인', en: 'Check connection' },
  'account.openInBrowser': { ko: '브라우저에서 Geny 서버 열기', en: 'Open Geny server in browser' },
  'account.accountCard': { ko: '계정', en: 'Account' },
  'account.loggedIn': { ko: '로그인됨 · 토큰이 키체인에 안전하게 저장됨', en: 'Signed in · Token securely stored in the keychain' },
  'account.logout': { ko: '로그아웃', en: 'Sign out' },
  'account.idLabel': { ko: '아이디', en: 'Username' },
  'account.passwordLabel': { ko: '비밀번호', en: 'Password' },
  'account.loginToHost': { ko: '{host} 에 로그인', en: 'Sign in to {host}' },
  'account.login': { ko: '로그인', en: 'Sign in' },

  // ── voice tab: push-to-talk ──
  'voice.pttCard': { ko: '푸시투토크 단축키', en: 'Push-to-talk hotkey' },
  'voice.pttHint': {
    ko: '탭하면 마이크가 켜지고, 다시 탭하면 꺼지거나 아바타의 말을 끊습니다. 아래를 클릭한 뒤 원하는 키 조합을 누르세요.',
    en: 'Tap to turn the mic on; tap again to turn it off or interrupt the avatar. Click below, then press the key combination you want.',
  },

  // ── voice tab: TTS ──
  'voice.ttsCard': { ko: 'TTS · 음성 출력', en: 'TTS · Voice output' },
  'voice.volume': { ko: '볼륨', en: 'Volume' },
  'voice.volumeHint': { ko: '아바타 창의 음성 출력 볼륨입니다.', en: 'The voice output volume of the avatar window.' },

  // ── voice tab: audio devices (sound driver in/out) ──
  'voice.deviceCard': { ko: '오디오 장치 (출력 · 입력)', en: 'Audio devices (output · input)' },
  'voice.outputDevice': { ko: '출력 (TTS 스피커)', en: 'Output (TTS speaker)' },
  'voice.inputDevice': { ko: '입력 (마이크)', en: 'Input (microphone)' },
  'voice.deviceDefault': { ko: '시스템 기본값', en: 'System default' },
  'voice.deviceOffline': { ko: ' (오프라인)', en: ' (offline)' },
  'voice.deviceRefresh': { ko: '장치 목록 새로고침', en: 'Refresh device list' },
  'voice.deviceHint': {
    ko: '선택한 장치는 이름으로 기억되고, 재접속하거나 장치가 늦게 켜질 때(예: VoiceMeeter가 나중에 시작) 자동으로 다시 연결됩니다. 목록이 비어 있으면 마이크 권한을 허용한 뒤 새로고침하세요.',
    en: 'The chosen device is remembered by name and re-applied automatically on reconnect or when it appears late (e.g. VoiceMeeter starting after Geny). If the list is empty, allow mic permission then refresh.',
  },

  // ── voice tab: subtitles ──
  'voice.subtitlesCard': { ko: '대사창 (자막)', en: 'Dialogue box (subtitles)' },
  'voice.subtitlesToggle': { ko: '아바타 하단에 대사 표시', en: 'Show dialogue at the bottom of the avatar' },
  'voice.subtitleSpeed': { ko: '글자 출력 속도', en: 'Character reveal speed' },
  'voice.subtitleSpeedDisplay': { ko: '{sec}초/글자', en: '{sec}s/char' },
  'voice.subtitleHint': {
    ko: '대사가 한 글자씩 흘러나오는 속도입니다(기본 0.10초/글자 — 왼쪽=빠름, 오른쪽=느림). 화면 캡처·자동 대화 트리거로 한 번에 온 발화도 이 속도로 앞에서부터 타이핑됩니다. 길어지면 위에서부터 잘리고, 다 흐른 뒤 약 3초 후 사라집니다(음성 켜져 있으면 음성이 끝난 뒤).',
    en: 'How fast the dialogue reveals one character at a time (default 0.10s/char — left = faster, right = slower). Utterances that arrive all at once from a screen-capture or auto-conversation trigger are also typed out from the start at this pace. Longer text is trimmed from the top and disappears about 3 seconds after it finishes (or after the voice ends, if voice is on).',
  },

  // ── voice tab: STT ──
  'voice.sttCard': { ko: 'STT · 음성 입력', en: 'STT · Voice input' },
  'voice.sttSensitivity': { ko: '민감도 (낮을수록 더 민감)', en: 'Sensitivity (lower is more sensitive)' },
  'voice.sttSilence': { ko: '발화 종료 대기', en: 'End-of-speech wait' },
  'voice.soundCorrection': { ko: '사운드 보정', en: 'Sound processing' },
  'voice.echoCancellation': { ko: '에코 제거', en: 'Echo cancellation' },
  'voice.noiseSuppression': { ko: '노이즈 억제', en: 'Noise suppression' },
  'voice.autoGain': { ko: '자동 게인', en: 'Auto gain' },

  // ── control tab: Local Computer Use ──
  'control.card': { ko: '로컬 컴퓨터 제어', en: 'Local Computer Use' },
  'control.hint': {
    ko: '이 접속기가 프록시가 되어, 서버에 떠 있는 Geny 에이전트가 내 컴퓨터를 보고 조작할 수 있게 합니다. 실행은 항상 이 컴퓨터에서 아래 동의에 따라 이뤄집니다(서버는 중계만 함). 접속기가 꺼지면 안전하게 차단됩니다. 에이전트가 실제로 쓰려면 해당 환경에서도 이 기능을 켜야 합니다.',
    en: 'This connector acts as a proxy so the Geny agent running on the server can see and operate your computer. Actions always run on this computer according to the consent settings below (the server only relays). It is safely blocked when the connector is off. To actually use it, the agent must also enable this feature in its environment.',
  },
  'control.masterToggle': { ko: '로컬 컴퓨터 제어 허용 (마스터)', en: 'Allow Local Computer Use (master)' },
  'control.capScreen': { ko: '화면 보기 (캡처·창 목록, 읽기 전용)', en: 'View screen (capture · window list, read-only)' },
  'control.capInput': { ko: '입력 조작 (타이핑·키·클릭)', en: 'Input control (type · keys · click)' },
  'control.capApps': { ko: '앱 제어 (열기·컨트롤 조작·Office 문서)', en: 'App control (open · drive controls · Office documents)' },
  'control.capClipboard': { ko: '클립보드 쓰기', en: 'Write clipboard' },
  'control.capBrowser': { ko: '브라우저 조작 (전용 Chrome/Edge 자동화 창)', en: 'Browser control (dedicated Chrome/Edge automation window)' },
  'control.consentTitle': { ko: '조작 동의 방식', en: 'Consent mode' },
  'control.consentAsk': { ko: '항상 확인', en: 'Always ask' },
  'control.consentSession': { ko: '이 세션 동안 허용', en: 'Allow for this session' },
  'control.consentAuto': { ko: '자동 허용', en: 'Auto-allow' },
  'control.consentHint': {
    ko: '화면 보기는 읽기 전용이라 확인 없이 즉시 동작합니다. 타이핑·클릭·앱 열기·클립보드는 위 설정을 따릅니다. {ask}이 가장 안전하며, 확인 창에서 “이 세션 동안 허용”을 누르면 그 동작은 접속기를 끌 때까지 다시 묻지 않습니다. {auto}은 매우 위험하니 신뢰하는 작업에만 쓰세요.',
    en: 'Viewing the screen is read-only and runs immediately without a prompt. Typing, clicking, opening apps, and clipboard follow the setting above. {ask} is the safest; pressing “Allow for this session” in a prompt stops asking for that action until you turn the connector off. {auto} is very dangerous — use it only for trusted tasks.',
  },
  'control.consentHint.ask': { ko: '항상 확인', en: 'Always ask' },
  'control.consentHint.auto': { ko: '자동 허용', en: 'Auto-allow' },

  // ── mcp tab ──
  'mcp.serversCard': { ko: '로컬 MCP 서버', en: 'Local MCP servers' },
  'mcp.serversHint': {
    ko: '내 컴퓨터에서 도는 MCP 서버를 등록하면, 이 접속기가 통로가 되어 서버의 Geny 에이전트가 그 도구를 사용할 수 있습니다(로컬 파일·앱·DB 등). 등록한 서버는 이 컴퓨터에만 저장되고, 서버에는 도구 목록만 전달됩니다.',
    en: 'Register an MCP server running on your computer, and this connector becomes the channel through which the Geny agent on the server can use its tools (local files, apps, databases, etc.). Registered servers are stored only on this computer; only the tool list is sent to the server.',
  },
  'mcp.empty': { ko: '등록된 MCP 서버가 없습니다.', en: 'No MCP servers registered.' },
  'mcp.test': { ko: '테스트', en: 'Test' },
  'mcp.remove': { ko: '삭제', en: 'Remove' },

  // ── Workspace sync ──
  'drive.card': { ko: 'Geny 드라이브', en: 'Geny Drive' },
  'drive.hint': { ko: '연결한 에이전트마다 드라이브 안에 폴더가 하나씩 생기고, 서버 작업공간과 실시간으로 동기화됩니다. 여러 에이전트를 동시에 연결할 수 있어요.', en: 'Each connected agent gets its own folder inside the drive, synced live with its server workspace. Connect as many agents as you like.' },
  'drive.cloudToggle': { ko: 'Geny 클라우드 사용', en: 'Use Geny Cloud' },
  'drive.cloudOff': { ko: '클라우드를 껐습니다. 다시 켜면 내려받기 없이 이어서 동기화됩니다.', en: 'Cloud is off. Turning it back on resumes without re-downloading.' },
  'drive.cloudFolder': { ko: 'Geny 클라우드', en: 'Geny Cloud' },
  'drive.cloudEdgeHint': { ko: '이 컴퓨터는 클라우드 한 곳과만 동기화합니다. 에이전트는 웹의 [클라우드] 탭에서 클라우드에 연결하세요.', en: 'This computer syncs with the cloud only. Connect agents to the cloud from the web [Cloud] tab.' },
  'drive.nativeToggle': { ko: '가상 드라이브 (실시간 스트리밍, 베타)', en: 'Virtual drive (live streaming, beta)' },
  'drive.nativeAt': { ko: '마운트 위치:', en: 'Mounted at:' },
  'drive.rootLabel': { ko: '드라이브 위치', en: 'Drive location' },
  'drive.rootHint': { ko: '위치를 바꾸면 연결된 폴더가 모두 새 위치로 이동합니다 (다시 내려받지 않습니다).', en: 'Changing the location MOVES every connected folder there — nothing is re-downloaded.' },
  'drive.changeRoot': { ko: '위치 변경…', en: 'Change…' },
  'drive.moving': { ko: '이동 중…', en: 'Moving…' },
  'drive.moved': { ko: '드라이브를 옮겼습니다 (폴더 {count}개).', en: 'Drive moved ({count} folder(s)).' },
  'drive.moveFailed': { ko: '이동 실패 — {msg}', en: 'Move failed — {msg}' },
  'sync.unlinkWarnCloud': { ko: '연결을 해제하면 이 폴더가 클라우드에서 제거되어, 클라우드에 연결된 모든 에이전트가 더 이상 접근할 수 없습니다. 내 컴퓨터의 원본 폴더는 그대로입니다. 계속할까요?', en: 'Unlinking removes this folder from the cloud, so every agent connected to the cloud loses access. Your own folder on this computer is untouched. Continue?' },
  'sync.pairsCard': { ko: '폴더 연결', en: 'Linked Folders' },
  'sync.pairsHint': { ko: '폴더는 GenyDrive에 연결됩니다. 드라이브에 연결된 모든 에이전트가 그 폴더를 저장소 하위 폴더로 공유하고, GenyDrive 루트에는 바로가기가 생깁니다.', en: 'Folders link to GenyDrive itself. Every agent connected to the drive shares the folder as a workspace subfolder, and a shortcut appears at the GenyDrive root.' }, 
  'sync.empty': { ko: '아직 연결된 폴더가 없습니다.', en: 'No folders linked yet.' },
  'sync.addCard': { ko: '새 연결 — 폴더를 GenyDrive에', en: 'New link — folder into GenyDrive' },
  'sync.agentLabel': { ko: '에이전트', en: 'Agent' },
  'sync.folderLabel': { ko: '로컬 폴더', en: 'Local folder' },
  'sync.folderPlaceholder': { ko: '동기화할 폴더를 선택하세요', en: 'Choose a folder to sync' },
  'sync.browse': { ko: '폴더 선택…', en: 'Browse…' },
  'sync.connect': { ko: '연결', en: 'Connect' },
  'sync.unlink': { ko: '해제', en: 'Unlink' },
  'sync.pause': { ko: '일시정지', en: 'Pause' },
  'sync.resume': { ko: '재개', en: 'Resume' },
  'sync.syncNow': { ko: '지금 동기화', en: 'Sync now' },
  'sync.openFolder': { ko: '폴더 열기', en: 'Open folder' },
  'sync.conflicts': { ko: '충돌 {count}건 보존됨', en: '{count} conflicts preserved' },
  'sync.skippedLarge': { ko: '대용량 {count}개 제외', en: '{count} large files skipped' },
  'sync.state.idle': { ko: '동기화됨', en: 'Synced' },
  'sync.state.syncing': { ko: '동기화 중…', en: 'Syncing…' },
  'sync.state.paused': { ko: '일시정지됨', en: 'Paused' },
  'sync.state.offline': { ko: '오프라인 (재연결 대기)', en: 'Offline (reconnecting)' },
  'sync.state.error': { ko: '오류', en: 'Error' },
  'sync.state.awaiting_confirmation': { ko: '확인 필요', en: 'Needs confirmation' },
  'sync.state.session_gone': { ko: '세션 삭제됨', en: 'Session deleted' },
  'sync.massDeleteWarn': { ko: '서버에서 {count}개 항목이 삭제되었습니다. 이 PC에도 삭제를 적용할까요?', en: '{count} entries were deleted on the server. Apply the deletion on this PC too?' },
  'sync.massDeleteApply': { ko: '삭제 적용', en: 'Apply deletion' },
  'sync.massDeletePause': { ko: '동기화 일시정지', en: 'Pause sync' },
  'sync.overlapError': { ko: '이 폴더는 이미 다른 연결({agent})과 겹칩니다. 같은 폴더(또는 상위/하위 폴더)를 두 에이전트에 연결할 수 없습니다.', en: 'This folder overlaps an existing pairing ({agent}). The same folder (or a parent/child of it) cannot feed two agents.' },
  'sync.safetyHint': { ko: '충돌 시 데이터는 절대 사라지지 않습니다 — 서버 버전이 원래 이름을 유지하고, 이 PC의 버전은 \'(충돌-PC이름 시각)\' 사본으로 보존됩니다. node_modules 등 라이브러리 폴더는 자동 제외되며, 파일당 500MiB까지 동기화됩니다.', en: 'Conflicts never lose data — the server version keeps the name and the local version is preserved as a \'(conflict)\' copy. Library folders like node_modules are excluded automatically; files sync up to 500MiB each.' },
  'mcp.testing': { ko: '테스트 중…', en: 'Testing…' },
  'mcp.testOk': { ko: '연결됨 · 도구 {count}개', en: 'Connected · {count} tools' },
  'mcp.testFail': { ko: '실패: {error}', en: 'Failed: {error}' },
  'mcp.testFailUnknown': { ko: '알 수 없음', en: 'unknown' },
  'mcp.addCard': { ko: '서버 추가', en: 'Add server' },
  'mcp.namePlaceholder': { ko: '이름 (예: filesystem)', en: 'Name (e.g. filesystem)' },
  'mcp.commandPlaceholder': {
    ko: '명령 (예: npx -y @modelcontextprotocol/server-filesystem /path)',
    en: 'Command (e.g. npx -y @modelcontextprotocol/server-filesystem /path)',
  },
  'mcp.urlPlaceholder': { ko: 'URL (예: http://localhost:3000/mcp)', en: 'URL (e.g. http://localhost:3000/mcp)' },
  'mcp.add': { ko: '추가', en: 'Add' },
  'mcp.addHint': {
    ko: 'stdio는 로컬에서 명령으로 실행되는 MCP 서버, http는 이미 떠 있는 MCP 엔드포인트입니다. 저장하면 연결된 서버의 각 도구가 에이전트에게 {name} 형태의 개별 도구로 바로 나타납니다 — 별도 탐색 없이 즉시 사용됩니다.',
    en: 'stdio is an MCP server launched locally by a command; http is an already-running MCP endpoint. Once saved, each tool on a connected server appears to the agent as an individual {name} tool — usable immediately, no discovery step.',
  },
  'mcp.master': { ko: '로컬 MCP 사용', en: 'Enable local MCP' },
  'mcp.masterOffHint': {
    ko: '꺼져 있는 동안 에이전트에게 로컬 MCP 도구가 보이지 않습니다. 서버 설정은 그대로 보존됩니다.',
    en: 'While off, no local MCP tools are visible to the agent. Server configs are kept.',
  },
  'mcp.summary': { ko: '연결 {servers}개 서버 · 도구 {tools}개', en: '{servers} connected · {tools} tools' },
  'mcp.rowConnected': { ko: '연결됨', en: 'connected' },
  'mcp.rowIdle': { ko: '대기', en: 'idle' },
  'mcp.rowDisabled': { ko: '꺼짐', en: 'off' },
  'mcp.rowTools': { ko: '도구 {count}개', en: '{count} tools' },
  'mcp.edit': { ko: '편집', en: 'Edit' },
  'mcp.editCard': { ko: '서버 편집: {name}', en: 'Edit server: {name}' },
  'mcp.envLabel': { ko: '환경변수 (줄마다 KEY=VALUE)', en: 'Environment (KEY=VALUE per line)' },
  'mcp.envPlaceholder': { ko: 'API_KEY=xxxx', en: 'API_KEY=xxxx' },
  'mcp.headersLabel': { ko: '헤더 (줄마다 Key: Value)', en: 'Headers (Key: Value per line)' },
  'mcp.headersPlaceholder': { ko: 'Authorization: Bearer xxxx', en: 'Authorization: Bearer xxxx' },
  'mcp.save': { ko: '저장', en: 'Save' },
  'mcp.cancel': { ko: '취소', en: 'Cancel' },
  'mcp.testOkNames': { ko: '연결됨 · 도구 {count}개: {names}', en: 'Connected · {count} tools: {names}' },

  // ── app tab: quick chat ──
  'app.quickChatCard': { ko: '빠른 채팅 단축키', en: 'Quick chat hotkey' },
  'app.quickChatHint': {
    ko: '어디서든 이 단축키를 누르면 입력창이 떠오르고, 메시지를 입력해 현재 VTuber에게 바로 보냅니다. 아래를 클릭한 뒤 원하는 키 조합을 누르세요. 자주 안 쓰는 조합을 권장합니다(기본: Cmd/Ctrl+Shift+Enter).',
    en: 'Press this hotkey from anywhere to bring up an input bar and send a message straight to the current VTuber. Click below, then press the key combination you want. An uncommon combination is recommended (default: Cmd/Ctrl+Shift+Enter).',
  },

  // ── app tab: screen capture ──
  'app.captureCard': { ko: '화면 캡처 관찰', en: 'Screen capture observation' },
  'app.captureInterval': { ko: '캡처 주기', en: 'Capture interval' },
  'app.captureSource': { ko: '볼 화면/창', en: 'Screen/window to view' },
  'app.captureAuto': { ko: '자동 (첫 번째 화면)', en: 'Automatic (first screen)' },
  'app.captureLoading': { ko: '화면 목록을 불러오는 중…', en: 'Loading the screen list…' },
  'app.captureHint': { ko: '캡처는 16:9 · 약 1600×900으로 축소되어 업로드됩니다.', en: 'Captures are downscaled to 16:9 · about 1600×900 before upload.' },
  'app.interval1m': { ko: '1분', en: '1 min' },
  'app.interval3m': { ko: '3분', en: '3 min' },
  'app.interval5m': { ko: '5분', en: '5 min' },
  'app.interval10m': { ko: '10분', en: '10 min' },

  // ── app tab: theme ──
  'app.themeCard': { ko: '화면 테마', en: 'Theme' },
  'app.themeSystem': { ko: '시스템', en: 'System' },
  'app.themeDark': { ko: '다크', en: 'Dark' },
  'app.themeLight': { ko: '라이트', en: 'Light' },
  'app.themeHint': {
    ko: '설정·채팅 창에 함께 적용됩니다. ‘시스템’은 OS 설정을 따릅니다.',
    en: 'Applies to the settings and chat windows. “System” follows the OS setting.',
  },

  // ── app tab: language ──
  'app.langCard': { ko: '언어', en: 'Language' },
  'app.langKo': { ko: '한국어', en: '한국어' },
  'app.langEn': { ko: 'English', en: 'English' },
  'app.langHint': {
    ko: '설정 창의 표시 언어입니다.',
    en: 'The display language of the settings window.',
  },

  // ── app tab: auto-update ──
  'app.updateCard': { ko: '자동 업데이트', en: 'Auto-update' },
  'app.updateToggle': { ko: '자동 업데이트', en: 'Auto-update' },
  'app.updateHintOn': { ko: '새 버전을 자동으로 내려받아 재시작 시 설치합니다.', en: 'Automatically downloads new versions and installs them on restart.' },
  'app.updateHintOff': { ko: '자동 설치는 끄고, 새 버전이 있으면 알림만 띄웁니다.', en: 'Auto-install is off; only notifies when a new version is available.' },
  'app.updateCheckNow': { ko: '최신버전 다운로드', en: 'Download latest version' },

  // ── app tab: launch on system startup ──
  'app.autostartCard': { ko: '시작 프로그램', en: 'Startup' },
  'app.autostartToggle': { ko: '시스템 시작 시 자동 실행', en: 'Launch on system startup' },
  'app.autostartHint': { ko: '컴퓨터에 로그인하면 Geny 접속기가 자동으로 실행됩니다.', en: 'Geny connector launches automatically when you log in to your computer.' },
  'app.autostartFailed': { ko: '자동 실행을 등록하지 못했습니다. AppImage를 임시 폴더가 아닌 고정된 위치(예: 홈 폴더)에 두고 실행한 뒤 다시 켜 보세요.', en: 'Could not register autostart. If you run the AppImage, move it to a permanent location (e.g. your home folder), launch it from there, then try again.' },
  'app.debugCard': { ko: '디버그 로그', en: 'Debug log' },
  'app.debugHint': { ko: '로그인·아바타·연결 문제를 진단하는 내부 로그입니다. 문제가 나면 [새로고침] 후 [복사]해서 전달해 주세요. 토큰 등 비밀 값은 기록되지 않습니다.', en: 'Internal log for diagnosing login/avatar/connection issues. On a problem, press Refresh then Copy and share it. Secrets are never logged.' },
  'app.debugRefresh': { ko: '새로고침', en: 'Refresh' },
  'app.debugCopy': { ko: '복사', en: 'Copy' },
  'app.debugCopied': { ko: '복사됨 ✓', en: 'Copied ✓' },

  // ── app tab: window/avatar positions ──
  'app.positionsCard': { ko: '창 · 아바타 위치', en: 'Window · Avatar positions' },
  'app.positionsHint': {
    ko: '아바타·채팅·설정 창의 위치/크기와 아바타 확대·이동을 기본값으로 되돌립니다. 멀티모니터나 배율(100%/150%) 변경으로 창이 화면 밖으로 나가거나 깨졌을 때 사용하세요.',
    en: 'Resets the position/size of the avatar, chat, and settings windows and the avatar zoom/pan to defaults. Use this when a multi-monitor or scaling (100%/150%) change pushes a window off-screen or breaks it.',
  },
  'app.positionsReset': { ko: '창 · 아바타 위치 초기화', en: 'Reset window · avatar positions' },
  'app.positionsResetDone': { ko: '✓ 기본 위치로 되돌렸습니다', en: '✓ Reset to default positions' },

  // ── app tab: about ──
  'app.aboutCard': { ko: '정보', en: 'About' },
  'app.version': { ko: '버전', en: 'Version' },
  'app.server': { ko: '서버', en: 'Server' },
  'app.restart': { ko: '접속기 재시작', en: 'Restart connector' },

  // ── overlay window (logged-out placeholder + dock handle) ──
  'overlay.loginHint': {
    ko: '로그인하면 여기에 아바타가 떠요 — 트레이 아이콘 → 설정/채팅 열기',
    en: 'Sign in and the avatar appears here — tray icon → open settings/chat',
  },
  'overlay.handleTitle': { ko: '드래그: 이동 · 더블클릭: 설정 열기', en: 'Drag: move · Double-click: open settings' },

  // ── quick-chat bar ──
  'qc.placeholder': { ko: '현재 VTuber에게 보낼 메시지…', en: 'Message to send to the current VTuber…' },
  'qc.sendAria': { ko: '전송', en: 'Send' },
  'qc.sendFailed': { ko: '전송 실패', en: 'Failed to send' },
  'qc.sent': { ko: '✓ 전송됨 — VTuber가 답합니다', en: '✓ Sent — the VTuber will reply' },
  'qc.sending': { ko: '전송 중…', en: 'Sending…' },
  'qc.footSend': { ko: '전송', en: 'send' },
  'qc.footNewline': { ko: '줄바꿈', en: 'newline' },

  // ── models: the accounts this server can reach a model with ──
  'models.title': { ko: '모델 계정', en: 'Model accounts' },
  'models.hint': {
    ko: '서버가 모델에 닿는 모든 경로입니다. 맨 위 계정이 답하고, 그 계정이 답할 수 없을 때만 아래 계정을 차례로 씁니다.',
    en: 'Every way the server can reach a model. The top account answers; the rest are tried only when one cannot.',
  },
  'models.empty': { ko: '계정이 없습니다. 하나 추가하면 서버가 답하기 시작합니다.', en: 'No accounts yet. Add one and the server can start answering.' },
  'models.answersFirst': { ko: '먼저 답합니다', en: 'Answers first' },
  'models.fallback': { ko: '예비 {index}', en: 'Fallback {index}' },
  'models.off': { ko: '꺼짐', en: 'Off' },
  'models.turnOn': { ko: '켜기', en: 'Turn on' },
  'models.turnOff': { ko: '끄기', en: 'Turn off' },
  'models.test': { ko: '테스트', en: 'Test' },
  'models.testing': { ko: '테스트 중…', en: 'Testing…' },
  'models.testOk': { ko: '{label} — {ms}ms 만에 답했습니다', en: '{label} — answered in {ms}ms' },
  'models.testFail': { ko: '{label} — 답하지 못했습니다: {error}', en: '{label} — could not answer: {error}' },
  'models.signIn': { ko: '로그인', en: 'Sign in' },
  'models.remove': { ko: '삭제', en: 'Remove' },
  'models.removeConfirm': { ko: '{label} 계정을 삭제할까요? 저장된 로그인과 키도 함께 지워집니다.', en: 'Remove {label}? Its stored login and key are deleted with it.' },
  'models.add': { ko: '계정 추가', en: 'Add account' },
  'models.addTitle': { ko: '모델 계정 추가', en: 'Add a model account' },
  'models.kind': { ko: '종류', en: 'Kind' },
  'models.apiKey': { ko: 'API 키', en: 'API key' },
  'models.address': { ko: '주소', en: 'Address' },
  'models.save': { ko: '저장', en: 'Save' },
  'models.cancel': { ko: '취소', en: 'Cancel' },
  'models.login.title': { ko: '로그인 — {label}', en: 'Signing in — {label}' },
  'models.login.waiting': { ko: '서버에서 로그인을 시작하는 중…', en: 'Starting the sign-in on the server…' },
  'models.login.browserOpened': { ko: '브라우저를 열었습니다. 로그인을 마치고 나온 코드를 아래에 붙여넣으세요.', en: 'The browser is open. Finish signing in, then paste the code it gives you below.' },
  'models.login.deviceCode': { ko: '열린 페이지에 이 코드를 넣으세요.', en: 'Enter this code on the page that opened.' },
  'models.login.openAgain': { ko: '다시 열기', en: 'Open again' },
  'models.login.pasteCode': { ko: '코드', en: 'Code' },
  'models.login.submit': { ko: '입력', en: 'Submit' },
  'models.login.done': { ko: '로그인했습니다.', en: 'Signed in.' },
  'models.login.failed': { ko: '로그인 실패 — {error}', en: 'Sign-in failed — {error}' },
  'models.login.cancel': { ko: '로그인 취소', en: 'Cancel sign-in' },
  'models.login.close': { ko: '닫기', en: 'Close' },

  // ── agents: work running on the server, and the record of it ──
  'agents.title': { ko: '에이전트', en: 'Agents' },
  'agents.hint': {
    ko: '서버에서 도는 에이전트입니다. 보고 있지 않아도 되도록, 무엇을 했는지 그대로 남깁니다 — 고친 파일, 실행한 명령과 결과, 실패한 것.',
    en: 'Agents running on the server. You are not watching them, so the record is exact: every file changed, every command and how it exited, everything that failed.',
  },
  'agents.pick': { ko: '에이전트 고르기', en: 'Pick an agent' },
  'agents.refresh': { ko: '새로고침', en: 'Refresh' },
  'agents.modelCard': { ko: '이 에이전트의 모델', en: "This agent's model" },
  'agents.noAccount': { ko: '연결된 계정 없음', en: 'No account' },
  'agents.pickModel': { ko: '모델 바꾸기…', en: 'Change model…' },
  'agents.keepsConversation': {
    ko: '대화는 그대로 이어집니다 — 도구도, 기억도, 권한도 바뀌지 않습니다.',
    en: 'The conversation continues — tools, memory and permissions are unchanged.',
  },
  'agents.switchedNow': { ko: '{label} · {model} 로 바꿨습니다', en: 'Now on {label} · {model}' },
  'agents.switchedNext': { ko: '다음 실행부터 {label} · {model} 을 씁니다', en: 'Next run uses {label} · {model}' },
  'agents.answeredBy': { ko: '지난 턴은 {label} · {model} 가 답했습니다', en: 'Last turn answered by {label} · {model}' },
  'agents.failedOver': { ko: '넘어감', en: 'failed over' },
  'agents.activityCard': { ko: '한 일', en: 'What it did' },
  'agents.viewActivity': { ko: '기록', en: 'Activity' },
  'agents.viewSummary': { ko: '요약', en: 'Summary' },
  'agents.filterAll': { ko: '전부', en: 'Everything' },
  'agents.filterFiles': { ko: '파일', en: 'Files' },
  'agents.filterCommands': { ko: '명령', en: 'Commands' },
  'agents.filterErrors': { ko: '실패', en: 'Failures' },
  'agents.filterTurns': { ko: '대화', en: 'Turns' },
  'agents.follow': { ko: '따라가기', en: 'Follow' },
  'agents.nothingYet': { ko: '아직 기록이 없습니다.', en: 'Nothing recorded yet.' },
  'agents.loading': { ko: '불러오는 중…', en: 'Loading…' },
  'agents.routeUsed': { ko: '{label} · {model} 가 답함', en: 'answered by {label} · {model}' },
  'agents.summaryLine': {
    ko: '파일 {files}개 · 명령 {commands}개 · 실패 {failures}개 · 대화 {turns}턴',
    en: '{files} files · {commands} commands · {failures} failures · {turns} turns',
  },
  'agents.failures': { ko: '실패', en: 'Failures' },

  'qc.footClose': { ko: '닫기', en: 'close' },
  'qc.footPaste': { ko: '이미지 붙여넣기 가능', en: 'paste images' },
  'qc.tooManyImages': { ko: '이미지는 최대 4장까지 첨부할 수 있어요', en: 'Up to 4 images per message' },
  'qc.imageTooLarge': { ko: '이미지가 너무 큽니다 (10MB 이하)', en: 'Image too large (max 10 MB)' },
  'qc.removeImage': { ko: '이미지 제거', en: 'Remove image' },

  // ── models tab additions ──
  'models.order': { ko: '응답 순서', en: 'Answering order' },
  'models.orderHint': {
    ko: '위에 있는 계정이 먼저 답합니다. 그 계정이 답할 수 없을 때만 다음으로 넘어갑니다.',
    en: 'The account at the top answers. The next is tried only when it cannot.',
  },
  'models.orderEmpty': { ko: '켜 둔 계정이 없습니다', en: 'No account is switched on' },
  'models.accountCount': { ko: '{n}개', en: '{n}' },
  'models.addLogin': { ko: '로그인 추가', en: 'Add a login' },
  'models.addKey': { ko: '계정 추가', en: 'Add an account' },
  'models.addAndSignIn': { ko: '추가하고 로그인', en: 'Add and sign in' },
  'models.label': { ko: '이름', en: 'Name' },

  // ── the chat window ──
  'chat.sessions': { ko: '세션', en: 'Sessions' },
  'chat.newSession': { ko: '새 세션', en: 'New session' },
  'chat.newSessionHint': {
    ko: '어느 환경으로 시작할지 고르세요. 모델은 환경이 아니라 위쪽 모델 선택이 정합니다.',
    en: 'Pick the environment to start in. The model is chosen in the header, not by the environment.',
  },
  'chat.creating': { ko: '만드는 중…', en: 'Creating…' },
  'chat.newSessionName': { ko: '세션 {n}', en: 'Session {n}' },
  'chat.envDefault': { ko: '기본 환경', en: 'Default environment' },
  'chat.noSessions': { ko: '아직 세션이 없습니다', en: 'No sessions yet' },
  'chat.untitled': { ko: '세션을 고르세요', en: 'Pick a session' },
  'chat.openSettings': { ko: '설정 열기', en: 'Open settings' },
  'chat.activity': { ko: '작업 기록', en: 'Activity' },
  'chat.cancel': { ko: '취소', en: 'Cancel' },
  'chat.send': { ko: '보내기', en: 'Send' },
  'chat.stop': { ko: '중단', en: 'Stop' },
  'chat.working': { ko: '작업 중…', en: 'Working…' },
  'chat.loading': { ko: '지난 대화를 읽는 중…', en: 'Reading the conversation…' },
  'chat.placeholder': { ko: '무엇을 시킬까요?', en: 'What should it do?' },
  'chat.placeholderNoSession': { ko: '먼저 세션을 고르세요', en: 'Pick a session first' },
  'chat.composerHint': {
    ko: 'Enter 로 보내고 Shift+Enter 로 줄을 바꿉니다. 작업 중 Esc 는 중단입니다.',
    en: 'Enter sends, Shift+Enter makes a new line. Esc stops a running turn.',
  },
  'chat.empty.title': { ko: '아직 아무 말도 오가지 않았습니다', en: 'Nothing has been said yet' },
  'chat.empty.hint': {
    ko: '이 세션은 서버에서 계속 살아 있습니다 — 창을 닫아도 하던 일은 이어집니다.',
    en: 'This session lives on the server — closing the window does not stop the work.',
  },
  'chat.tabChat': { ko: '대화', en: 'Chat' },
  'file.lines': { ko: '{n}줄', en: '{n} lines' },
  'file.bytes': { ko: '{n}자', en: '{n} chars' },
  'file.pages': { ko: '{n}쪽', en: '{n} pages' },
  'file.page': { ko: '{n}쪽', en: 'page {n}' },
  'file.wrap': { ko: '줄바꿈', en: 'Wrap' },
  'file.fit': { ko: '맞춤', en: 'Fit' },
  'file.actual': { ko: '원본 크기', en: 'Actual size' },
  'file.binary': { ko: '미리 볼 수 없는 형식입니다', en: 'Nothing to show for this format' },
  'file.archive': { ko: '압축 파일입니다', en: 'An archive' },
  'file.asPdf': { ko: '원본으로 보기', en: 'Open as PDF' },
  'file.asPages': { ko: '페이지로 보기', en: 'Show pages' },
  'file.truncated': { ko: '앞부분 {shown}만 표시합니다 (전체 {total})', en: 'Showing the first {shown} of {total}' },
  'file.clipped': { ko: '{total}줄 중 앞 {n}줄만 표시합니다', en: 'Showing the first {n} of {total} lines' },
  'file.noPreview': { ko: '이 문서는 미리 보기를 만들지 못했습니다', en: 'No preview could be made' },
  'file.kind.image': { ko: '이미지', en: 'image' },
  'file.kind.svg': { ko: '벡터 이미지', en: 'vector image' },
  'file.kind.pdf': { ko: 'PDF', en: 'PDF' },
  'file.kind.doc': { ko: '문서', en: 'document' },
  'file.kind.audio': { ko: '오디오', en: 'audio' },
  'file.kind.video': { ko: '비디오', en: 'video' },
  'file.kind.markdown': { ko: '마크다운', en: 'markdown' },
  'file.kind.table': { ko: '표', en: 'table' },
  'file.kind.json': { ko: 'JSON', en: 'JSON' },
  'file.kind.notebook': { ko: '노트북', en: 'notebook' },
  'file.kind.code': { ko: '코드', en: 'code' },
  'file.kind.text': { ko: '텍스트', en: 'text' },
  'file.kind.archive': { ko: '압축', en: 'archive' },
  'file.kind.binary': { ko: '바이너리', en: 'binary' },
  'explorer.title': { ko: '탐색기', en: 'Explorer' },
  'explorer.noSession': { ko: '에이전트가 없습니다', en: 'No agents yet' },
  'explorer.empty': { ko: '비어 있음', en: 'Empty' },
  'explorer.loading': { ko: '읽는 중…', en: 'Reading…' },
  'explorer.onServer': { ko: '서버', en: 'server' },
  'explorer.up': { ko: '상위 폴더', en: 'Up' },
  'explorer.close': { ko: '닫기', en: 'Close' },
  'chat.liveNow': { ko: '진행 중인 대화', en: 'Running now' },
  'chat.refresh': { ko: '새로고침', en: 'Refresh' },
  'chat.untitledEnv': { ko: '환경 없음', en: 'No environment' },
  'chat.kbdSend': { ko: '전송', en: 'send' },
  'chat.kbdNewline': { ko: '줄바꿈', en: 'new line' },
  'chat.kbdStop': { ko: '중단', en: 'stop' },
  'chat.steps.title': { ko: '작업 과정', en: 'What it did' },
  'chat.steps.tools': { ko: '도구 {n}회', en: '{n} tools' },
  'chat.steps.failed': { ko: '실패 {n}', en: '{n} failed' },
  'chat.selfStartedTimes': {
    ko: '스스로 시작한 턴 {n}회 · {reason}',
    en: 'Started on its own, {n} times · {reason}',
  },
  'chat.steps.running': { ko: '작업 중', en: 'Working' },
  'chat.steps.done': { ko: '작업 {n}단계', en: '{n} steps' },
  'chat.steps.count': { ko: '{n}개', en: '{n}' },
  'status.system': { ko: '시스템', en: 'System' },
  'status.aria': { ko: '시스템 리소스 사용량', en: 'System resource usage' },
  'status.total': { ko: '전체', en: 'Total' },
  'status.load': { ko: '1분 평균 부하', en: 'One-minute load average' },
  'chat.you': { ko: '나', en: 'You' },
  'chat.failed': { ko: '실패', en: 'Failed' },
  'status.app': { ko: '앱', en: 'App' },
  'status.appMem': { ko: '접속기가 쓰는 메모리', en: 'Memory this connector is using' },
  'status.cores': { ko: '코어 {n}개', en: '{n} cores' },
  'chat.selfStarted': {
    ko: '스스로 시작한 턴 · {reason}',
    en: 'Started on its own · {reason}',
  },
  'chat.tool.input': { ko: '넣은 값', en: 'Input' },
  'chat.tool.output': { ko: '돌려받은 값', en: 'Output' },
  'chat.state.ready': { ko: '연결됨', en: 'Connected' },
  'chat.state.working': { ko: '실행 중', en: 'Running' },
  'chat.state.reconnecting': { ko: '다시 연결하는 중', en: 'Reconnecting' },
  'chat.state.offline': { ko: '연결 끊김', en: 'Disconnected' },
  'chat.state.signedOut': { ko: '로그인 필요', en: 'Sign in required' },
  'chat.avatar.hint': { ko: '이 VTuber의 아바타를 바꿉니다. 아바타 창에 바로 반영됩니다', en: "Change this VTuber's avatar. The avatar window switches right away" },
  'chat.avatar.none': { ko: '아바타 없음', en: 'No avatar' },
  'chat.avatar.clear': { ko: '아바타 해제', en: 'Remove avatar' },
  'chat.avatar.empty': { ko: '설치된 아바타가 없습니다. 아바타 에디터에서 만든 뒤 내보내세요', en: 'No avatars installed. Make one in the avatar editor and export it' },
  'chat.avatar.kind.live2d': { ko: 'Live2D', en: 'Live2D' },
  'chat.avatar.kind.mmd': { ko: '3D (MMD)', en: '3D (MMD)' },
  'chat.avatar.kind.spine': { ko: 'Spine', en: 'Spine' },
  'chat.avatar.kind.other': { ko: '기타', en: 'Other' },
  'chat.route.default': { ko: '기본 순서대로', en: 'Default order' },
  'chat.route.serverDefault': { ko: '서버가 정한 모델', en: "The server's model" },
  'chat.route.none': { ko: '쓸 수 있는 계정이 없습니다 — 설정에서 추가하세요', en: 'No usable account — add one in settings' },
  'chat.route.answered': { ko: '지난 턴은 {label}', en: 'Last turn: {label}' },
  'chat.route.answeredHint': {
    ko: '앞 계정이 답할 수 없어 다음 계정이 대신했습니다',
    en: 'The first account could not answer, so the next one did',
  },
  'chat.ledger.files': { ko: '파일', en: 'Files' },
  'chat.ledger.commands': { ko: '명령', en: 'Commands' },
  'chat.ledger.log': { ko: '전체', en: 'All' },
  'chat.ledger.trigger': { ko: '스스로', en: 'self' },
  'chat.ledger.noFiles': { ko: '아직 건드린 파일이 없습니다', en: 'No files touched yet' },
  'chat.ledger.noCommands': { ko: '아직 실행한 명령이 없습니다', en: 'No commands run yet' },
  'chat.ledger.noLog': { ko: '아직 기록이 없습니다', en: 'Nothing recorded yet' },
}

/**
 * Build a translator for `lang`. `t('a.key', { name: 'x' })` returns the string
 * for the language, interpolating `{name}` tokens, and falls back to the key if
 * the key is unknown (so a missing translation is visible, not silently blank).
 */
export function makeT(lang: Lang) {
  return (key: string, vars?: Record<string, string | number>): string => {
    const entry = messages[key]
    let s = entry ? entry[lang] : key
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        s = s.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v))
      }
    }
    return s
  }
}
