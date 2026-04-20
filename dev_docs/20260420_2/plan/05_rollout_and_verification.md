# 05 — Rollout and Verification (Phase E)

Phase A–D 가 완결된 뒤 단일 cutover PR 로 전환되며, 이 Phase 는 그 PR 을 머지
가능한 상태로 만들기 위한 **스모크 / 수용 기준 / 회귀 방지 절차** 를 정의한다.

## 전제

- `geny-executor` v0.22.0 이 태깅되어 있고, Phase A/B 의 계약/MCP 변경이 반영
  되어 있다.
- Geny 의 safe-refactor PR (`GenyToolProvider`, `build_default_manifest`,
  마이그레이션 스크립트) 이 이미 머지되어 dead code 로 존재한다.
- Cutover 를 수행하는 단일 PR 이 준비되어 있다 — 이 PR 은:
  - `pyproject.toml` 에서 `geny-executor>=0.22.0,<0.23.0` 으로 pin.
  - `AgentSession._build_pipeline` 의 legacy 블록 삭제.
  - `_format_tool_detail` swallower 제거 및 대체 formatter 적용.
  - 기존 env 에 `tools.external` 기본값을 주입하는 마이그레이션 스크립트 실행
    절차를 README / progress 로그에 명시.

## Cutover 절차

1. Cutover PR 로컬 체크아웃 → 단위/통합 테스트 pass 확인.
2. 마이그레이션 스크립트 dry-run (disk 의 env 문서들을 읽어 변경 예정 diff 만
   출력) → 예상 diff 수동 검토.
3. PR 머지.
4. 머지 직후 마이그레이션 스크립트 1 회 실행. 대상: `backend/data/environments/`
   하위의 모든 env 파일. 스크립트는 변경된 파일을 진행 로그로 남기고,
   변경이 0건이면 exit 0.
5. 스모크 시나리오 S-1 ~ S-7 수동 수행.
6. 수용 기준 확인 후 릴리스.

별도의 flag-on 단계나 dark-launch 윈도우는 없다. 문제가 발견되면 즉시 revert.

## 스모크 시나리오

### S-1. `news_search` E2E (env_id 세션)

1. env_id 를 가진 vtuber 세션 생성.
2. "오늘 날씨 관련 뉴스 찾아줘" 프롬프트.
3. tool 이벤트 스트림 확인:
   - `execute_start { name: "news_search" }` 1회.
   - `execute_ok { output_preview: JSON 문자열 시작 }` 1회.
4. LLM 응답에 실제 뉴스 제목/요약 포함.
5. 로그 grep `"parse error"` 0 건.

### S-2. `news_search` E2E (non-env_id 세션)

동일 절차, env_id 없음. `build_default_manifest` 경유의 파이프라인이 S-1 과
동일한 결과를 내야 한다.

### S-3. MCP 서버 추가/제거

1. manifest 에 MCP 서버 (예: filesystem) 추가 → env 저장.
2. 세션 생성 시 `mcp__filesystem__read_file` (prefix 강제) 가 tool 목록에
   나타나는지 확인.
3. 서버 중지 상태로 세션 생성 시도 → `MCPConnectionError` 로 즉시 실패.
4. manifest 에서 서버 제거 → 새 세션에 더 이상 해당 tool 없음.

### S-4. 알 수 없는 tool 호출

1. manifest 의 allowlist 에 없는 tool 을 LLM 이 가상으로 호출하게 유도
   (system prompt 조작).
2. tool_result 에 `ERROR unknown_tool: ...` 가 첫 줄로 도착.
3. LLM 이 이를 인식하고 다른 tool 로 우회하는지 확인.

### S-5. 잘못된 입력

1. 필수 파라미터가 누락된 채 tool 을 호출하도록 유도.
2. tool_result 에 `ERROR invalid_input: ...` 가 도착.
3. LLM 이 정정된 입력으로 재시도하는지 확인.

### S-6. Preset 경계

1. `ToolPresetDefinition` 에서 `news_search` 를 제외한 preset 으로 세션 생성.
2. LLM 이 `news_search` 호출 시 `unknown_tool` (또는 `access_denied`) 에러를
   받음.
3. UI 의 tool 목록에 `news_search` 가 숨겨졌는지 확인.

### S-7. `(parse error)` 회귀 방지

1. `session_logger.py` 와 `process_manager.py` 에 악성 tool_input
   (`{"k": object()}` 등) 을 주입하는 단위 테스트 추가.
2. 반환값이 `(parse error)` 로 시작하지 않는지 확인.

### S-8. 저장된 env 일괄 재실행

마이그레이션 스크립트 실행 후, 디스크에 남은 각 env 를 순회하며 "세션을
만들어 빈 프롬프트 1 회 + tool 하나를 유도하는 프롬프트 1 회" 를 돌린다.
MCP 서버 의존 env 는 서버가 기동된 상태에서 돌린다. 세션 생성 에러 0 건이
목표.

## 수용 기준 (release gate)

- [ ] 스모크 S-1 ~ S-8 전부 통과.
- [ ] 코드 검색 `rg "parse error" Geny geny-executor` 결과가 테스트 fixture
      외 0 건.
- [ ] `GENY_MANIFEST_ONLY_TOOLS` / `strict=False` 등 compat flag 관련 식별자가
      리포에 남아 있지 않다 (grep 확인).
- [ ] `AgentSession._build_pipeline` 가 단일 경로로 축소되어 있다
      (diff 리뷰).
- [ ] PR #128/#129 의 UI 에 실제 활성 tool 목록이 정확히 표시.

## 수동 QA 체크리스트

1. Vtuber preset + env_id 세션 → `news_search` 정상.
2. Worker preset + env_id 세션 → `news_search` 정상.
3. Worker preset + non-env_id (즉석 manifest) → `news_search` 정상.
4. MCP 서버 추가 후 세션 재생성 → tool 등장.
5. MCP 서버 URL 오타 → 세션 생성 단계에서 명확한 에러.
6. tool 이 의도적으로 `ToolFailure` 를 raise 하는 fake 구현 → structured error
   전달, stacktrace 는 로그에만.
7. Developer mode (`GENY_TOOL_DEBUG=true`) → UI 에 debug badge / stacktrace.
8. Production mode → UI 에 stacktrace 없음.
9. Frontend `CodeViewModal` 로 manifest JSON 확인 시 `tools.external` 필드가
   표시되고 마이그레이션 스크립트 실행 후 기본 provider 이름들이 채워져 있다.

## 되돌리기 체크포인트

- Cutover PR 에서 회귀 → 해당 PR 을 revert **하고 `pyproject.toml` 의 executor
  pin 도 이전 버전으로 원복**. safe-refactor PR 의 dead code 는 남아 있어도
  호출자가 없으므로 동작에 영향 없음.
- 마이그레이션 스크립트가 env 를 잘못 변경한 경우: 스크립트는 실행 전 파일을
  `.bak` 으로 복사하고 실행 후에도 보관. revert 시 `.bak` 를 원위치로 복구.
- host 측 회귀 → `geny-executor` 의 v0.22.0 태그 이전 버전으로 Geny 의 pin 을
  후퇴시키고, 이 경우 본 사이클의 변경 전체가 함께 롤백됨 (부분 복원은
  지원하지 않음).

## 운영 지표

- `execute_error` 이벤트의 **일일 카운트 / code 별 분포** 를 관찰 지표로.
- 세션 시작 실패율 (MCP 연결 실패 포함) — Phase B 도입 후 초기 증가는 정상
  (원래 숨겨져 있던 실패가 드러남).
- tool 관련 log 에 `(parse error)` 문자열이 나타나는지 알람.
