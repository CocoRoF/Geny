# Progress Index — Tool/MCP Integration Hardening

본 사이클의 구현 PR 단위 기록. 구현 진행 중 — 각 PR 별로 이 폴더에
`NN_<slug>.md` 를 추가한다.

## 기록 규약

- 파일명: `NN_<slug>.md` (`NN` 은 2자리 순번, 슬러그는 snake_case).
- 본문 머리말: 대응하는 `plan/XX.md` 링크, PR 번호/URL, 브랜치.
- 본문: 변경 요지 / 실제 diff 영역 / 수동 검증 결과 / 후속 TODO.
- 어느 레포의 변경인지 (Geny / geny-executor) 를 맨 위에 표시.

## 현재 상태

- [x] Phase A — Host 계약 강화 (plan/02) — PR1 `#22`, PR2 `#23`.
- [x] Phase B — MCP 수명주기 (plan/03) — PR3 `#24`.
- [ ] Phase C — 단일 tool surface (plan/01) — host PR4 `#25` 완료,
  릴리즈 PR5 `#26` + tag `v0.22.0` 완료, Geny safe-refactor PR6
  `#135` 완료, **env_id cutover PR8 `#139` 완료**. 남은 작업:
  non-env_id `_build_pipeline` 통합 (별도 사이클).
- [ ] Phase D — 관측성 / logging swallower 제거 (plan/04) — PR7
  `#137` 완료 (§B). §C–E 는 별도 사이클로 분리.
- [ ] Phase E — 롤아웃 / 회귀 방지 (plan/05) — Phase C 종료 후 수동
  QA 진행.

## 인덱스

- [01 — Host 구조화 에러 + 입력 검증 (PR1, Phase A)](01_host_structured_errors.md)
  — geny-executor `feat/tool-structured-errors`.
- [02 — MCP 도구 네임스페이스 prefix (PR2, Phase A)](02_mcp_namespace_prefix.md)
  — geny-executor `feat/mcp-namespace-prefix`.
- [03 — MCP 수명주기 하드닝 (PR3, Phase B)](03_mcp_lifecycle.md)
  — geny-executor `feat/mcp-lifecycle`.
- [04 — AdhocToolProvider + external 필드 (PR4, Phase C host)](04_adhoc_tool_provider.md)
  — geny-executor `feat/adhoc-tool-provider`.
- [05 — geny-executor v0.22.0 릴리즈 (PR5)](05_release_v0_22_0.md)
  — geny-executor `release/v0.22.0` + tag `v0.22.0`.
- [06 — Geny safe-refactor dead code (PR6, Phase C 준비)](06_safe_refactor_dead_code.md)
  — Geny `feat/geny-tool-provider-dead-code`.
- [07 — Geny logging swallower 제거 (PR7, Phase D §B)](07_logging_swallower_removal.md)
  — Geny `feat/tool-detail-formatter`.
- [08 — Geny cutover, env_id half (PR8, Phase C)](08_cutover_env_pipeline.md)
  — Geny `feat/cutover-v0220-env-pipeline`.
