# Cycle 20260422_4 — X5F · 외부 플러그인 인터페이스 일반화

**사이클 시작.** 2026-04-22 (X6F Ship 종료 직후).
**선행.** 20260422_2 (X6 infra), 20260422_3 (X6F activation),
plan/05 §5 (X5 — Plugin Protocol & Registry).
**문제 제기.** plan/05 §5.3 / 20260422_2 cycle_close §다음 사이클 에서
조건부 이월된 PR-X5-4 / X5-5 (executor `attach_runtime(session_runtime=...)`
kwarg + Geny 채택) 를, **외부 플러그인 인터페이스의 일반화 가능성**
관점에서 활성화.

## 목표

X1~X6F 사이클을 통해 Geny 는 자체 stage / emitter / state 를 위해
`state.shared[KEY]` 같은 stringly-typed 딕셔너리 패턴에 의존해 왔다.
단일 host 환경에서는 충분하지만, 외부 플러그인이 본격적으로 들어오면:

- key namespacing collision (`mood.*` vs. 다른 plugin 의 같은 key)
- IDE 자동완성 / 정적 타입 체크 부재
- 어느 plugin 이 어느 key 를 owner 인지 불명확

세 문제가 일제히 표면화. 본 사이클은 executor 에 **plugin-oriented
session-scoped 객체 carrier slot** (`session_runtime`) 을 *공식
attach 접점*으로 추가하고, Geny 가 첫 채택자가 된다.

executor 측 계약은 의도적으로 **`Any`** — Protocol 을 강제하지 않는다.
"executor 는 게임을 모른다" 불변식 (plan/05 §8 §1) 을 유지하면서,
host / plugin 사이의 attribute 협의는 docstring 가이드라인 수준으로
열어둠.

## 범위 정책

| PR | 리포 | 브랜치 | 상태 |
|---|---|---|---|
| PR-X5F-1 | `geny-executor` | `feat/attach-runtime-session-runtime-kwarg` | **Ship** — kwarg + state slot + 9 tests (PR #47) |
| PR-X5F-R | `geny-executor` | `chore/release-0.30.0` | **Ship** — 0.30.0 PyPI 릴리즈 (PR #48) |
| PR-X5F-2 | `Geny` | `chore/pin-executor-0.30.0` | **Ship** — `requirements.txt` 0.30.0 으로 이동 + 검증 |
| PR-X5F-3 | `Geny` | `feat/agent-session-uses-session-runtime` | **Ship** — `attach_runtime(session_runtime=...)` 채택 + 대표 1~2곳 stage 마이그레이션 |
| PR-X5F-4 | `Geny` | `docs/cycle-20260422_4-close` | **Ship** — 사이클 종료 doc |

**의도적 비범위.**

- **`state.shared[KEY]` 일괄 치환.** PR-X5F-3 는 *대표 채택 지점만*
  이전. shared-dict 관용은 *공존*. 점진적 마이그레이션이 안전 — 한
  PR 에 해당 stage / emitter / consumer 까지 묶으면 "한 PR = 한 방향"
  위반.
- **Plugin Registry / GenyPlugin Protocol 본격 작동.** plan/05 §5.1
  의 PR-X5-1 ~ PR-X5-3 은 이미 이전 사이클에 Ship 됨 (task #220 /
  #221 / #222). 본 사이클은 **registry 가 사용할 attach 접점**을 마련
  하는 *마지막 인프라 조각*.
- **Plugin 두 번째 사례 추가.** Tamagotchi 외 두 번째 plugin 을 추가
  하지 않음 — 본 사이클은 *접점 자체*의 정착에 집중. 두 번째 plugin
  이 추가될 때 schema collision 이슈가 실증될 것.

## 불변식 (plan/05 §8 + 이전 사이클 상속)

- **executor 는 게임을 모른다.** ✅ executor 쪽은 `session_runtime: Any`.
  Tamagotchi / `CreatureState` / `Mood` 어떤 도메인 어휘도 import 하지
  않음.
- **Pure additive — executor.** ✅ 신규 kwarg 1개 + state field 1개,
  기본값 `None`. 기존 host 무영향. 682 unit tests 전부 변경 없이 통과.
- **Pure additive — Geny.** ✅ PR-X5F-3 는 *기존* shared-dict 경로를
  *삭제하지 않음*. 두 경로 공존, 점진적 마이그레이션.
- **Mutation 4 op.** ✅ 본 사이클은 mutation 무관.
- **Side-door 재생 금지.** ✅ `session_runtime` 은 *공식* attach
  접점 (executor docstring 에 정식 문서화). shared-dict 보다 *격이 더
  높은* 표면.
- **Stage 는 Provider 를 직접 잡지 않는다.** ✅ stage 가 Provider 를
  직접 instantiate 하지 않음. host 가 `session_runtime` 을 미리
  꽂아 두면, stage 는 `getattr(state.session_runtime, "...", None)`
  로 *읽을 뿐*.

## PyPI 의존 흐름

PR-X5F-1 / X5F-R 머지 후 0.30.0 PyPI 업로드는 user 액션. 업로드
완료 (2026-04-22 확인) 후에야 Geny PR-X5F-2 진입 가능 — 자동화 없는
구간.

## 산출 문서

- `progress/pr1_executor_session_runtime_kwarg.md` (executor PR #47/#48 회고)
- `progress/pr2_pin_executor_030.md`
- `progress/pr3_agent_session_uses_session_runtime.md`
- `progress/cycle_close.md`
