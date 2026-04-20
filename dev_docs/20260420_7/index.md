# Cycle 20260420_7 — VTuber↔Sub-Worker 연결 신뢰성 + 파일 생성 기능

**상태.** Open.
**트리거.** 2026-04-21 15:17 UTC 라이브 로그 — VTuber가 연결된
Sub-Worker를 사용하지 못하고 "Sub-Worker Agent"라는 이름의 새 세션을
생성해 엉뚱한 곳으로 DM을 보냈으며, Sub-Worker는 요청받은
`test.txt`를 끝내 만들지 못했다.

## 문제 요약

```
15:17:04  VTuber(b14d61f2) 생성 → 정상 링크된 Sub-Worker(6e224bb4) 자동 생성
15:17:12  채팅방(36397e97) 생성, 링크 저장됨
15:17:37  VTuber가 geny_session_create(name="Sub-Worker Agent",
          role=developer) 실행 → 새 세션 5e2edaab 생성
15:17:37  VTuber가 geny_send_direct_message(target=5e2edaab, ...) 실행
          → 진짜 Sub-Worker 6e224bb4 대신 엉뚱한 5e2edaab가 수신
15:17:41  5e2edaab는 memory_write로 projects/vtuber-agent-self-
          introduction-task.md만 남기고 test.txt 생성 없이 응답 절단
```

두 층의 결함이 겹친다:

1. **발견성(discovery) 층** — 에이전트에 이미 `_linked_session_id`가
   세팅되어 있음에도, LLM은 그 UUID를 프롬프트 본문에서 복사해
   `target_session_id` 인자에 채워 넣어야 한다. 실패 지점 하나만 있으면
   모든 위임이 망가진다.
2. **능력(capability) 층** — geny-executor는 `Write`/`Read`/`Edit`
   /`Bash`/`Glob`/`Grep`를 이미 출하하고 있으나 manifest 경로가 이들
   을 자동 등록하지 않는다. Geny 쪽에도 파일 쓰기 도구가 없으므로
   Sub-Worker는 그나마 가장 가까운 `memory_write`로 도망친다. 프레임
   워크가 "인터페이스만" 주고 "기본 도구"를 소비자가 재구현하게
   만든 구조적 결함.

## 폴더 구조

```
20260420_7/
├── index.md                                     — 본 파일
├── analysis/
│   ├── 01_linked_counterpart_discovery.md       — VTuber↔Sub 발견 결함
│   └── 02_file_creation_gap.md                  — 파일 생성 도구 부재
├── plan/
│   ├── 01_counterpart_message_tool.md           — 대칭형 내장 도구 설계
│   └── 02_file_write_tool.md                    — 파일 쓰기 도구 추가
└── progress/
    └── (PR 병합 후 작성)
```

## 완료 기준

1. VTuber가 `target_session_id` 없이도 연결된 Sub-Worker에게 메시지를
   보낼 수 있는 내장 도구가 존재한다.
2. Sub-Worker도 동일한 로직(자기 쪽 `_linked_session_id`를 해석)으로
   연결된 VTuber에게 응답할 수 있다 — 두 역할 모두 같은 도구를 쓴다.
3. geny-executor가 `manifest.tools.built_in`을 소비해 프레임워크
   출하 도구(`Write` 등)를 자동 등록한다. Geny의 Sub-Worker는 별도
   구현 없이 `storage_path` 하위에 파일을 만들 수 있다.
4. 회귀 테스트가 (a) 연결된 상대 해석, (b) 링크 없을 때의 안전한 실패,
   (c) 샌드박스 경로 이탈 차단, (d) executor 내장 도구 자동 등록,
   (e) test.txt 실제 생성을 커버한다.
5. 라이브 스모크: "test.txt 파일 만들어줘" 요청 시 Sub-Worker가
   실제로 파일을 만들고 VTuber가 성공을 사용자에게 전달한다.

## 20260420_6와의 관계

Cycle 6는 *도구 경로*를 고쳤다 (`_probe_session_id_support`가 올바른
시그니처를 검사하도록). Cycle 7은 *도구 면(surface)*을 고친다 — LLM이
실수할 수 있는 자리 자체를 제거하고, 실제로 필요한 능력을 추가한다.
