# Plan Index

`analysis/` 에서 도출된 갭을 메우기 위한 단계별 계획. 각 계획 문서는 구체적인
PR 단위로 분해 가능하도록 작성한다.

## 문서

- [00_strategy.md](00_strategy.md) — 전체 마이그레이션 전략 / 위험 / 되돌리기 정책.
- [01_dependency_bump.md](01_dependency_bump.md) — `pyproject.toml` +
  주변 고정 (`geny-executor>=0.20.0`, `[postgres]` extra 등).
- [02_executor_rewire.md](02_executor_rewire.md) — `agent_session.py` /
  `tool_bridge.py` / 매니저 계층을 v0.20.0 파이프라인 API 로 재배선.
- [03_memory_migration.md](03_memory_migration.md) — 레거시
  `backend/service/memory/*` → `MemoryProvider` 로의 이전 전략. 데이터 보존 /
  기존 SQL 스키마와 executor SQL 프로바이더의 공존 방안 포함.
- [04_environment_integration.md](04_environment_integration.md) —
  ENVIRONMENT 매니페스트 / 프리셋 / 리졸버 컴포넌트의 Geny 이식 경로.
- [05_api_surface_decisions.md](05_api_surface_decisions.md) — 컨트롤러 /
  라우터 / WS 계층에서 유지할 것 vs 재설계할 것의 선을 긋는다.
- [06_rollout_and_verification.md](06_rollout_and_verification.md) — 단계별
  스모크 / 수용 기준 / 수동 QA 체크리스트.

## 작업 원칙

- 각 계획 문서는 "왜 이 순서인가" 와 "실패 시 되돌리기 경로" 를 반드시 포함.
- 구현 단계에 들어가면 `progress/` 에 PR 단위 기록을 남기고 여기 `plan/` 문서에
  "구현 링크" 를 덧붙인다.
