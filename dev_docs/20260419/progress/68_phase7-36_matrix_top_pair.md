# 68. Phase 7-36 — 매트릭스 "Most different pair" 하이라이트

## Scope

Phase 7-31/32/34 follow-up 로 계속 남아 있던 항목: N 이 커질수록
매트릭스에서 "가장 많이 다른 pair" 를 시각적으로 찾기 어려움. 10
envs = 45 셀, 모든 upper triangle 을 스캔해 수치를 비교해야 한다.
이 phase 는 `added + removed + changed` 합이 최대인 upper-triangle
셀을 찾아 ring + tint 로 강조하고, 헤더에 클릭 가능한 "Most
different" 배지를 노출한다.

## PR Link

- Branch: `feat/phase7-36-matrix-top-pair`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/EnvironmentDiffMatrixModal.tsx` — 수정
- `topPair` / `topPairLabel` useMemo 추가 — ok 상태 pair 중 score
  가 가장 큰 upper-triangle cell key. 모든 pair 가 identical (score
  0) 이면 `null` — 그 경우 하이라이트 안 함.
- `renderCell` 의 upper-triangle 분기에서 `isTop` 일 때 버튼에
  primary tint (`rgba(59,130,246,0.12)` 배경, primary 컬러 텍스트,
  inset ring) 추가. tooltip 도 `diffMatrix.topPairTooltip` 으로 교체.
- 헤더 subtitle 아래에 `topPairLabel` 이 있을 때 inline-flex 버튼
  형태의 배지 노출. 클릭 시 `setPair({left, right})` 로 기존
  EnvironmentDiffModal drill-down.
- 매트릭스 Markdown meta block 에 `- **Most different:** A ↔ B (N
  changes)` 라인 추가 (있을 때).
- JSON payload 에 `top_pair: { env_id_a, env_id_b, name_a, name_b,
  score } | null` 필드 추가. 없으면 `null`.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `diffMatrix.topPairBadge` — "Most different: {left} ↔ {right} ·
  {score} changes" / "가장 많이 다름: {left} ↔ {right} · 변경 {score}".
- `diffMatrix.topPairTooltip` — cell 에 hover 시 문구.

## Verification

- 3 개 env, 모두 다름: 매트릭스 완성 후 가장 큰 diff cell 이 파란
  ring + tint, 헤더에 "Most different: A ↔ B · 12 changes" 배지.
  배지 클릭하면 DiffModal 열림.
- 3 개 env, 모두 identical: 배지 미노출, cell 에 ring 없음. 기존
  `=` 초록 스타일 유지.
- 부분 에러 (1 쌍만 err): ok 셀 중에서 top 을 선택. err 셀은 score
  비교 대상에서 제외.
- 동률 (여러 pair 가 같은 최대 score): 첫 발견 pair 만 선택 — 안정적
  tie-breaking 은 불필요하고 markdown 에도 1 개만 명시.
- Markdown export 메타에 "Most different" 줄이 들어가는지.
- JSON export `top_pair` 필드가 { env_id_a, env_id_b, name_a, name_b,
  score } 로 직렬화. 없으면 `null`.
- ko 로케일: "가장 많이 다름: …"

## Deviations

- Score metric 은 `added + removed + changed` 의 단순 합. Added/Removed
  에 가중치를 주는 방안도 있었지만 (예: removed 는 호환성 파괴) —
  manifest 의미 정의 없이 임의 가중치는 오해를 부를 수 있어 선형
  합으로 유지.
- 동률 셀은 현재 "첫 upper-triangle 발견" 기준. `i,j` 가 작은 쌍이
  선택된다. 사용자에게 "top 이 하나뿐이 아닐 수 있다" 는 정보가
  필요하면 후속 phase 에서 별도 표기.
- 하이라이트는 상단 삼각형에만 적용. 하단은 이미 opacity-60 으로
  dim 되어 있으므로 동일 pair 를 두 번 강조하면 시각적 충돌이 큼.
- 헤더 배지를 Download/Copy 와 같은 footer 에 두지 않은 이유 —
  "상시 정보" 이기 때문. Footer 는 "완료 후 액션" 컨테이너라 성격이
  다르다.
- `top_pair` 를 JSON 의 `summary` 에 중첩하지 않고 top-level 필드로
  뺐다. 기존 `summary` 는 counts 만이라 의미적으로 혼재하지 않는
  편이 좋다.

## Follow-ups

- "Most similar pair" (score 최솟값, identical 제외) — 중복 제거나
  마이그레이션 후보 발견에 유용.
- 동률 케이스 표시: "2 pairs tied at 12 changes — showing A ↔ B".
- 하이라이트된 cell 에 keyboard focus (Tab 진입 시 첫 타깃) — a11y.
- Metric 가중치 (added/removed 를 changed 보다 크게) 토글 — 의미론
  바뀌므로 사용자 설정 필요.
