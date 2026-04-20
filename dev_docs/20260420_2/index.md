# Tool/MCP Integration Hardening — 2026-04-20 (cycle 2)

`geny-executor` 를 외부 도구/MCP 서버에 대해 **자유롭게 넣고 뺄 수 있는** 강력한
플러그-인 인터페이스로 만들고, Geny 가 실제 비즈니스 로직의 built-in tool 을
그 위에 붙였을 때 **자연스럽고 강력하게 호환**되도록 재설계하기 위한 작업
사이클이다.

## 동기 (Motivation)

현재 Geny 세션에서 `news_search` 와 같은 built-in tool 을 호출하면 LLM 이
`(parse error)` 문자열만 세 번 연속 돌려받고 포기하는 증상이 재현된다. 이
증상은 단일 버그가 아니라 **두 개의 tool 등록 경로가 분기** 되어 있고, **host
인터페이스가 입력 스키마 검증/구조적 오류 반환/MCP 수명주기를 보장하지 않는**
구조적 이슈의 외연이다.

## 폴더 구조

- [analysis/](analysis/index.md) — 현황 분석 (증상, host/consumer 인터페이스,
  manifest vs runtime 등록 분기, 취약점 카탈로그).
- [plan/](plan/index.md) — 분석 결과를 바탕으로 한 재설계 계획 (host 계약 강화,
  manifest 일원화, MCP 수명주기, 관측성, 롤아웃).
- [progress/](progress/index.md) — 본 사이클의 구현 PR 단위 기록 (현재는 계획
  수립 단계, 구현 착수 전).

## 범위 (In / Out)

**In scope**
- `geny-executor` 의 `tools.*` 서브패키지 (registry, composer, MCP manager,
  stage_binding, dispatch) 의 계약 재설계.
- Geny 의 `backend/service/langgraph/tool_bridge.py` 와
  `EnvironmentManifest.tools.adhoc|mcp_servers` 하이드레이션 경로 통합.
- `news_search` 및 동류 built-in tool 의 manifest-기반 세션에서의 동작 보장.
- `(parse error)` 라는 **logging-side 예외 삼키기 (swallower)** 제거 및
  structured error 로 대체.

**Out of scope**
- Frontend `SessionEnvironmentTab` / `PipelineCanvas` UI 추가 개편 (이미 PR #128,
  #129 에서 완료).
- Memory 서브시스템 재설계 (별도 사이클에서 다룸).
- Geny 비즈니스 도메인 tool 의 신규 추가 (기존 tool 의 동작 보장에 집중).

## 성공 기준 (Done)

1. `env_id` 기반 세션에서 `news_search` 를 호출했을 때 `(parse error)` 없이
   실제 JSON 결과가 LLM 에게 돌아간다.
2. `ToolsSnapshot` (adhoc/mcp_servers/allowlist/blocklist) 만으로 tool 이
   완전히 구성될 수 있고, 두 번째 "레거시 등록 경로" 가 제거되거나 명확히
   흡수된다.
3. 알 수 없는 tool 이름 호출 시 LLM 은 문자열이 아닌 **structured error**
   (code/message/details) 를 받는다.
4. MCP 서버가 manifest 에 선언되면 Stage 10 실행 전에 `connect + list_tools`
   가 보장되고, 실패는 세션 시작 시 명확히 터진다.
5. 모든 tool 실행 실패는 logger 에 stacktrace 가 남고, 어떤 경로로도 사용자
   가시 출력에 `(parse error)` 라는 문자열이 새지 않는다.

## 참조

- PR #128 — Session Environment pipeline canvas / detail / code modal
- PR #129 — Pipeline view theme alignment (light/dark 토큰)
- `geny-executor` source: `/home/geny-workspace/geny-executor`
- `Geny` backend tool bridge: `backend/service/langgraph/tool_bridge.py`
- `Geny` environment service: `backend/service/environment/service.py`

## 작업 원칙

- 본 사이클은 **분석 + 계획 단계** 이다. 실제 코드 수정은 별도 단계에서
  착수하며, 모든 구현 PR 은 `progress/` 에 기록한다.
- "추측" 금지. 모든 단정은 파일 경로/라인 번호로 뒷받침한다.
- **하위호환 shim / feature flag / 두 경로 병존 금지**. 장기 유지보수 비용과
  회귀 은닉 위험을 막기 위해, 새 구조로 전환하는 PR 이 legacy 경로를 함께
  제거한다. 회귀 발생 시엔 해당 PR 을 revert 한다.
