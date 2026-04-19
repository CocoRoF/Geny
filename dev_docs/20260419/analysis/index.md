# Analysis Index

현재 Geny 레포가 어떻게 동작하는지 + v0.20.0 executor 와 어떻게 충돌/수렴하는지를
사실 기반으로 기록한다. 모든 항목은 실제 파일 경로를 참조한다.

## 문서

- [01_current_executor_integration.md](01_current_executor_integration.md) —
  Geny 가 현재 `geny-executor` 를 쓰는 위치와 방식 (`agent_session.py`,
  `tool_bridge.py`, 매니저 계층).
- [02_legacy_memory_subsystem.md](02_legacy_memory_subsystem.md) —
  `backend/service/memory/` 의 파일별 역할 + DB/FS 경계.
- [03_executor_api_delta.md](03_executor_api_delta.md) —
  `geny-executor` 0.8.3 → 0.20.0 공개 API/구조 델타.
- [04_environment_feature_map.md](04_environment_feature_map.md) —
  `geny-executor-web` v0.9.0 의 ENVIRONMENT 기능 목록과 Geny 대응 여부.
- [05_gap_summary.md](05_gap_summary.md) —
  위 네 문서를 좁힌 최종 갭 테이블 (무엇이 사라지고, 무엇이 새로 필요하고,
  무엇이 단순 치환되는가).

## 작업 원칙

- "추측" 금지. 확인되지 않은 동작은 "TBD"로 명시하고 근거 파일 경로와 함께 남긴다.
- 버전 번호는 항상 정확히 적는다 (예: 0.8.3 vs 0.10.0 vs 0.20.0).
- Geny 레거시와 executor v0.20.0 의 "용어 충돌" 을 반드시 표시한다
  (예: Geny 의 `session` ≠ executor 의 `Session`).
