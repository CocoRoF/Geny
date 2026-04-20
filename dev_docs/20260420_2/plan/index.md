# Plan Index — Tool/MCP Integration Hardening

`analysis/` 의 갭·취약점을 메우기 위한 단계별 재설계. 각 문서는 구체적 PR
단위로 분해 가능하도록 작성하며, 변경이 `geny-executor` 와 `Geny` 중 어느
레포에 들어가는지를 **섹션별로 명시** 한다.

## 문서

- [00_strategy.md](00_strategy.md) — 전체 전략, 우선순위, 호환성/롤백 정책,
  두 레포의 배포 순서.
- [01_unified_tool_surface.md](01_unified_tool_surface.md) — Geny built-in tool
  을 manifest 기반 파이프라인에 주입하는 **단일 경로** 설계. `adhoc_providers`
  라는 register-time hook 을 executor host 에 도입하고, Geny 의 `tool_bridge`
  를 manifest 레벨 provider 로 승격하며 **같은 PR 에서 legacy 경로를 삭제**.
- [02_host_contract_hardening.md](02_host_contract_hardening.md) — Tool ABC
  주위의 계약 강화: 입력 스키마 validation, structured error 반환, MCP tool
  네임스페이스 (prefix), unknown-tool 실패의 에러 코드화.
- [03_mcp_lifecycle_and_discovery.md](03_mcp_lifecycle_and_discovery.md) —
  MCPManager 가 manifest 로드 시점에 `connect_all + list_tools` 를 수행하도록
  수명주기 재정의. 실패는 세션 시작 시 터지고 stage 10 런타임에는 전파되지
  않게 한다.
- [04_observability_and_error_surface.md](04_observability_and_error_surface.md) —
  `_format_tool_detail` 의 `"(parse error)"` swallower 제거, tool
  input/output 의 안전한 log-formatter, session logger 와 process manager 의
  중복 정의 통합, structured error 를 UI 에 표현하기.
- [05_rollout_and_verification.md](05_rollout_and_verification.md) —
  단계별 스모크, 수용 기준, 두 레포의 버전 bump 순서, 수동 QA 체크리스트
  (`news_search`, MCP 서버 추가/제거, allowlist/blocklist 경계 케이스).

## 작업 원칙

- 각 plan 문서는 "왜 이 순서인가" 와 "되돌리기 경로" 를 포함한다.
- **하위호환 shim / feature flag / 두 경로 병존은 도입하지 않는다**. `geny-executor`
  는 본 사이클에서 breaking minor bump (v0.22.0) 로 발표되고, Geny 는 같은 cutover
  PR 에서 legacy 경로를 제거하며 새 버전을 pin 한다. 회귀 시엔 revert.
- 구현 단계 진입 시 `progress/` 에 PR 단위 기록을 남기고, 본 plan 문서 본문에
  "구현 링크" 를 덧붙인다.
