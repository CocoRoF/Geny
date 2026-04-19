# 65. Phase 7-33 — Diff matrix JSON/Markdown export

## Scope

Phase 7-31 매트릭스 (`EnvironmentDiffMatrixModal`) 의 결과를 JSON /
Markdown 으로 다운로드. Phase 7-30 의 DiffModal export 패턴과 동일한
UX — Footer 버튼 두 개 (Export JSON / Export MD), 매트릭스가 모두
채워진 (`pending === 0`) 상태에서만 노출.

Markdown 은 GitHub PR 본문에 그대로 붙여넣을 수 있도록 index table +
symmetric matrix table + non-identical/errored pair drill-down 섹션
까지 포함.

## PR Link

- Branch: `feat/phase7-33-matrix-export`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/EnvironmentDiffMatrixModal.tsx` — 수정
- `Download` 아이콘 추가 import.
- `downloadBlob`, `collectPairs` 헬퍼 — cells 를 `{ env_id_a, env_id_b,
  name_a, name_b, ok, identical, summary, error }` 배열로 정규화.
- `exportable = stats.pending === 0 && stats.total > 0`.
- `exportMatrixJson()` — payload:
  `{ version, generated_at, envs:[{id,name}], summary:{pairs,ok,failed},
    pairs: [...] }`. 파일명: `env-diff-matrix-<N>-<STAMP>.json`.
- `exportMatrixMarkdown()` — 섹션:
  1. 메타 (환경 개수, pair 개수 / ok / failed, 생성 시각).
  2. Environments index table.
  3. Summary matrix table (symmetric; 대각선 `—`, 미완성 `…`, 에러
     `err`, 동일 `=`, 나머지 `+A/-R/~C`).
  4. Non-identical pairs 목록 (upper-triangle 의 비동일 pair 만).
  5. Errored pairs 목록 (있을 때만).
  파일명: `env-diff-matrix-<N>-<STAMP>.md`.
- Footer 에 exportable 조건부 "Export JSON" / "Export MD" 버튼 추가
  (Close 왼쪽). 미완성/부분 실패 상태에서는 버튼 미노출.

`frontend/src/lib/i18n/en.ts` / `ko.ts` — 수정
- `diffMatrix.exportJson`, `diffMatrix.exportMarkdown` 추가.

## Verification

- 3 개 선택 → 매트릭스 → 모든 cell 채워진 뒤 Footer 에 Export
  JSON/MD 등장.
- "Export JSON" 클릭 → `env-diff-matrix-3-<timestamp>.json` 다운로드.
  내용: envs 배열, summary, pairs (3 개) 각각 ok/identical/summary
  포함.
- "Export MD" 클릭 → 파일 열면:
  - Environments 테이블 (번호 / 이름 / id).
  - Summary matrix 테이블 (3×3, 대각선 `—`, 상·하단 대칭 요약).
  - "Non-identical pairs" 섹션 (다른 것만 bullet 으로).
- 한 pair 만 에러 → Errored pairs 섹션이 등장, 해당 pair cell 이
  matrix 테이블에서도 `err`.
- 완료 전에는 Export 버튼이 안 보임. 부분 에러 상태에서도 매트릭스가
  "완료" (pending=0) 면 export 가능.
- ko 로케일: "JSON 내보내기" / "MD 내보내기".

## Deviations

- Markdown 의 summary matrix 테이블은 GitHub 렌더링 기준으로 상/하단
  대칭을 모두 채웠다. UI 상에서는 하단을 60% opacity 로 흐리게 했지만
  plain markdown 에는 스타일이 없으므로 완전 복사.
- pair drill-down 은 upper-triangle 만 순회. `collectPairs()` 가
  이미 i<j 순이라 그대로 bullet.
- non-identical 과 errored 를 별도 섹션으로 분리. "동일한 pair" 는
  noise 라 생략 (필요하면 summary matrix 에서 `=` 로 확인).
- 파일명의 env 이름 slug 는 넣지 않음 (매트릭스는 N 개라 파일명이
  너무 길어진다). 대신 환경 index 가 md/json 안에 포함되어 역으로
  매칭 가능.
- Export 버튼은 `pending === 0` 일 때만 노출. "부분 로딩" 상태에서
  내보내면 `…` 가 섞여 의미가 없기 때문. 일부 실패는 export 허용.

## Follow-ups

- "Copy to clipboard" 옵션 — 다운로드 대신 markdown 을 바로 복사해
  PR 댓글에 붙여넣기.
- Summary matrix 의 셀 포맷을 `changed` 만 보여 주는 간소 모드
  (GitHub 에서 가독성 높음) 토글.
- diff-bulk 의 read cache (50 envs × 2 = 100 reads → 50 reads) —
  Phase 7-32 follow-up 로 이월.
