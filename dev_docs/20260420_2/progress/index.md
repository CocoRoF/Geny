# Progress Index — Tool/MCP Integration Hardening

본 사이클의 구현 PR 단위 기록. 현재 단계는 **분석 + 계획** 이며, 아직 구현에
착수하지 않았다. 구현이 시작되면 각 PR 별로 이 폴더에 `NN_<slug>.md` 를
추가한다.

## 기록 규약

- 파일명: `NN_<slug>.md` (`NN` 은 2자리 순번, 슬러그는 snake_case).
- 본문 머리말: 대응하는 `plan/XX.md` 링크, PR 번호/URL, 브랜치.
- 본문: 변경 요지 / 실제 diff 영역 / 수동 검증 결과 / 후속 TODO.
- 어느 레포의 변경인지 (Geny / geny-executor) 를 맨 위에 표시.

## 현재 상태

- [ ] Phase A — Host 계약 강화 (plan/02)
- [ ] Phase B — MCP 수명주기 (plan/03)
- [ ] Phase C — 단일 tool surface (plan/01)
- [ ] Phase D — 관측성 / logging swallower 제거 (plan/04)
- [ ] Phase E — 롤아웃 / 회귀 방지 (plan/05)

## 인덱스

> 구현 시작 시 이 아래에 PR 단위 항목을 추가.
