# Geny Mobile

서버의 에이전트와 대화하는 Android / iOS 앱. **채팅과 설정만** 있다 —
아바타·음성·워크스페이스는 데스크톱 접속기와 웹의 몫이고, 폰은 "물어보고
답을 읽는" 한 가지를 잘 하면 된다.

## 왜 연결이 이 앱의 전부인가

턴은 **세션**의 것이지 이 소켓의 것이 아니다. 서버는 백그라운드로 돌리고
아무도 듣지 않아도 계속 간다 — 그래서 화면이 꺼질 때마다 소켓이 죽는 폰에서는
**연결이 곧 대화가 아니다.** 여기 있는 규칙은 전부 그 사실 하나에서 나온다:

| 상황 | 하는 일 | 안 하면 생기는 일 |
|---|---|---|
| 소켓이 끊김 | 오류를 그리지 않는다. 턴은 돌고 있다 | 잘 돌아가는 턴 위에 빨간 글씨 — 화면을 믿지 않게 된다 |
| 다시 붙음 | 매번 `reconnect` 를 보낸다. 서버가 그 턴을 **처음부터** 다시 흘려준다 | 터널에서 나온 폰이 답의 꼬리만 받는다 |
| 소켓이 죽었는데 안 죽은 척 | 유휴 `ping` + 침묵 70초면 강제 재연결 | 캐리어 NAT 가 끊은 줄 모르고 영원히 스피너 |
| 앱이 다시 앞으로 옴 | `resume()` — 백오프를 건너뛴다 | 폰을 켰는데 서버 장애용 타이머를 기다린다 |
| 토큰 거부(4401) | 재시도를 멈추고 로그인으로 보낸다 | 죽은 토큰으로 서버를 영원히 두드린다 |

`src/lib/exec-ws.ts` 가 그 규칙이고, `test/exec-ws.test.ts` 가 그 규칙을 고정한다
(가짜 소켓 + 가짜 시계, 실제 네트워크 없음).

## 구조

| 층 | 파일 | 비고 |
|---|---|---|
| 턴 스트림 | `src/lib/exec-ws.ts` | `/ws/execute/{session_id}` — 토큰은 `geny-auth` 서브프로토콜로 (URL 에 넣으면 프록시 로그에 남는다) |
| 로그 → 대화 | `src/lib/transcript.ts` | 서버 로그가 정본. 말풍선은 전부 거기서 접어 만든다 |
| REST | `src/lib/server.ts` | 네이티브 fetch — 브라우저가 아니라 CORS 가 없다 |
| 저장 | `src/lib/store.ts` | 토큰은 OS 키스토어, 나머지는 AsyncStorage |
| 화면 | `src/screens/` | 대화 / 설정 둘 |

## 개발

```
npm install
npm test        # 순수 로직 (node:test) — 41개
npm run typecheck
npm start       # expo dev server
```

APK 로컬 빌드: `npm run apk` (debug 키 서명). JDK 21 + Android SDK 35 필요.

## 네이티브 프로젝트

`android/`, `ios/` 는 `expo prebuild` 산출물을 **커밋**해 둔 것이다 — CI 는
재생성 없이 그대로 빌드한다. `prebuild` 가 표현할 수 없는 두 가지(package.json
에서 파생한 버전, CI 시크릿 기반 릴리스 서명)는 `scripts/patch-android.mjs` 가
멱등하게 다시 넣는다. `npm run prebuild` 에 엮여 있으니 손으로 기억할 필요는
없고, CI 가 "패치가 no-op 인가"를 검사한다.

cleartext 허용과 `allowBackup=false` 는 `app.json` 에 있다 — 손으로 매니페스트를
고치면 다음 prebuild 에 조용히 사라진다.

## 릴리스

`mobile-v*` 태그를 밀면 `.github/workflows/mobile-release.yml` 이 APK 와
**무서명** IPA 를 만들어 릴리스에 붙인다. Apple 배포 서명에는 개발자 계정이
필요하고 이 저장소에는 없다.

⚠ 안드로이드 서명 키는 릴리스마다 **같아야** 한다 (다르면 기존 설치 위에
업데이트가 거부되고 사용자가 지우고 다시 깔아야 한다 — 서버 주소·토큰·세션이
전부 날아간다). 키는 저장소 시크릿 `ANDROID_KEYSTORE_B64` 에 둔다.
