# 62. Phase 7-30 — Markdown diff export + Auto-suffix conflict resolver

## Scope

Phase 7-28 (JSON diff export) 과 Phase 7-29 (이름 충돌 경고) 에 바로
이어지는 UX polish 두 가지를 묶은 번들.

1. **Markdown diff export** — DiffModal 의 JSON 옆에 "Export MD" 버튼.
   JSON 은 기계 파싱 용도, Markdown 은 리뷰 노트/PR 설명에 바로
   붙여넣기 좋은 human-readable 포맷.
2. **Auto-suffix conflict resolver** — Phase 7-29 의 충돌 경고 배너에
   "Auto-suffix" 버튼. 눌리면 단일 경로는 `name` → `name (2)` /
   `name (3)` 등 첫 번째 비어 있는 슬롯으로, 번들 경로는 충돌하는
   모든 entry 를 순차적으로 자동 suffix.

둘 다 백엔드 변경 없음. 프론트 두 파일 + i18n 두 파일.

## PR Link

- Branch: `feat/phase7-30-md-export-autosuffix`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/EnvironmentDiffModal.tsx` — 수정
- 기존 exportDiff 의 `URL.createObjectURL` / `a.download` 반복 로직을
  `downloadBlob(body, mime, filename)` 헬퍼로 추출.
- `exportDiffMarkdown()` 추가 — `# Environment diff` 헤더, Left/Right/
  Generated/Summary 메타, Added/Removed/Changed 섹션을 각각 markdown
  bullet 또는 before/after fenced code block 으로 내보냄.
- Footer 에 "Export MD" 버튼 추가 (JSON 버튼 오른쪽).

`frontend/src/components/modals/ImportEnvironmentModal.tsx` — 수정
- `pickUniqueName(base, taken)` 헬퍼 — taken (lowercase) Set 을 참고
  해서 `base` → `base (2)` → `base (3)` … 순으로 첫 번째 자리를 찾음.
- `suggestSingleName()` — 단일 경로. `nameOverride` 또는 원본 이름을
  base 로 sugggestion 계산 후 `nameOverride` 업데이트.
- `autoSuffixBundle()` — 번들 경로. 충돌 없는 entries 의 이름을 먼저
  taken 에 포함시키고, 충돌 entry 만 하나씩 pickUniqueName.
- 단일/번들 각각의 conflict banner 안에 "Auto-suffix" 버튼 노출.

`frontend/src/lib/i18n/en.ts` / `ko.ts` — 수정
- 신규 키: `diff.exportMarkdown`, `importEnvironment.autoSuffix`.

## Verification

### Markdown export

- 두 env 비교 후 "Export MD" 클릭 → 다운로드 된 `.md` 파일이 열리며
  Added/Removed/Changed 섹션이 markdown 포맷으로 렌더.
- Changed entry 는 path 를 `###` heading 으로 쓰고 Before/After 를
  fenced code block 으로 표시.
- 차이가 하나도 없을 때는 `_No differences._` 로 출력.
- 파일명은 `env-diff-<LEFT>__<RIGHT>-<STAMP>.md` 형태.
- ko 로케일에서는 버튼 라벨이 "MD 내보내기".

### Auto-suffix

- 기존 env 이름이 `My Env` 인 상태에서 동일한 이름 번들 entry →
  conflict banner 노출 + Auto-suffix 버튼 클릭 → 해당 entry 의 입력
  칸이 `My Env (2)` 로 채워지고 배지 사라짐.
- 번들에 `My Env` 가 두 번 들어 있으면 Auto-suffix 는 각각 `My Env (2)`,
  `My Env (3)` 을 제안 (같은 suffix 로 collapse 되지 않음).
- 이미 `My Env (2)` 도 기존에 존재하면 Auto-suffix 는 `My Env (3)` 부터
  시도.
- 단일 경로에서는 충돌 banner 안의 Auto-suffix 버튼이 nameOverride
  를 바로 채움 → banner 가 사라지면서 Import 진행 가능.
- Auto-suffix 로 1000 까지 찾지 못한 edge 에서는 `name (copy)` 로
  fallback (실사용 상 발생 없음).

## Deviations

- Markdown 의 Before/After 블록은 언어 지정이 없는 fenced code
  block. JSON/YAML 등 특정 언어로 하이라이트하고 싶지만 현재 값은
  원시 `formatValue` 출력이라 일관된 언어 태그를 줄 수 없다.
- Auto-suffix 가 1000 회를 시도하고 실패하면 `base (copy)` 로 fallback.
  env 이름이 1000 개 이상 겹치는 건 실사용 상 없음.
- Auto-suffix 는 bundle 에서 override 로 "이미 수동으로 고쳐 둔"
  이름들도 taken 집합에 포함시켜서 같은 이름을 두 번 제안하지 않음.
  단, 원본이 충돌하지 않는 entry 의 경우 사용자가 override 를 비워
  두면 해당 원본 이름이 taken 에 추가됨 (의도).
- i18n 키 `autoSuffix` 는 import 모달 네임스페이스에 추가. diff
  모달의 export 는 별도 네임스페이스 (diff) 라 공유하지 않음.

## Follow-ups

- Markdown export 에 diff summary 를 상단 badge / shields 형식으로
  (GitHub PR 에서 잘 보이는 포맷).
- Auto-suffix 알고리즘을 "이름 뒤 숫자 추출 후 증가" (e.g. `My Env 3`
  → `My Env 4`) 도 지원하도록. 현재는 항상 `(N)` 포맷.
- Phase 7-23 의 multi-diff matrix (세 env 이상 동시 비교) — 이번에도
  이월.
