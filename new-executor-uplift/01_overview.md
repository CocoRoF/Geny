# 01. Overview — Goals · Principles · Scope

## 1. 본 분석의 목표

이전 cycle (executor_uplift / 20260425_*) 은 두 단계로 구성됐었음:

1. **Phase 1–9 backbone** — geny-executor 1.0 의 capability 를 전부 ship (executor 레포 측 작업)
2. **Cycle 1 + 2 + 3 of Geny adoption** — 그 위에 host 측 wiring + UI + audit fix

이제 두 단계 모두 끝났고, **functional baseline 은 prod 검증까지 완료**. 하지만 사용자가 명시한 비교 baseline 은 **claude-code-main 의 실제 표면 전체**. 이 분석은:

- claude-code 가 실제로 가진 **53개 capability** 를 inventory
- Geny 의 현 ship 상태와 1:1 매핑
- gap 을 severity + 의존성 + 영향도로 분류
- 향후 cycle 의 후보 묶음 권장

## 2. 설계 원칙 (executor_uplift §2 의 P1–P8 을 계승, 일부 갱신 + 신규 P0)

### P0 ★ — Layering principle (axiomatic, 가장 중요)

`geny-executor` = **built-in core (claude-code-main reference)** + **extension interface (ABC + register API)**. `Geny` = **service consuming geny-executor** (도메인 / REST 어댑터 / 웹 UI / 운영 인프라).

**파생 규칙:**
- claude-code-main 이 src/ 에 가진 표준 capability → 거의 모두 **geny-executor 의 EXEC-CORE** 또는 **EXEC-INTERFACE** 로
- Geny 측은 도메인 구현 (VTuber / character / preset / memory backend / web UI / FastAPI controller) 에 집중
- Geny 가 framework concern (tool 표준 라이브러리 / slash command 파서 / cron daemon) 을 자체 구현하는 것은 **anti-pattern**

상세 결정 트리 + 케이스별 분류표는 [`00_layering_principle.md`](00_layering_principle.md). 본 폴더의 모든 priority / design 은 본 원칙에서 파생되며, 충돌 시 본 원칙이 이김.

### P1 — claude-code parity 가 새 ground truth

이전 P1 은 "21-stage 재구성을 한 번의 major bump 로 흡수" 였고 그건 끝남. 새 P1 은 **claude-code-main 이 가진 모든 표면을 가져야 한다** — 단, P0 에 따라 **거의 모두 geny-executor 측에**. Geny 는 register / wire / UI / REST 에 집중.

다만 *일부 surface 는 도메인 (VTuber / 게임 / 캐릭터) 에서 의미 없을 수 있음*. 그런 항목은 "skip with rationale" 처리하고 표에 명시.

### P2 — Single source of truth (계승)

같은 정보를 두 레이어가 각자 저장하지 않음. claude-code 도 동일 원칙: settings.json 한 곳에서 user/project/local hierarchy 를 처리. Geny 는 현재 YAML 다중 source — 본 cycle 에서 settings.json 패턴으로 통일 검토.

### P3 — 확장 friction 최소화 (계승)

claude-code 는 "새 tool 추가" 가 1 파일 (`src/tools/<NewTool>/index.ts`) + 1 register 호출. Geny 는 `tools/built_in/<name>_tools.py` + `BUILT_IN_TOOL_CLASSES` 등록. 비슷한 수준이지만 **plugin 시스템** 은 claude-code 가 한 발 앞 — bundled plugin 디렉토리에서 자동 발견.

### P4 — 실행 품질 (계승)

ToolCapabilities + PartitionExecutor + PermissionGuard + HookRunner 가 이미 wired. 본 cycle 에서 추가는 **PLAN mode 의 acceptEdits / dontAsk variants** 정도.

### P5 — 관측 가능성 (계승, 강화)

claude-code 는 in-process EventBus + subprocess hooks 양쪽. Geny 는 subprocess hooks 만 — 본 cycle 에서 in-process 콜백 (registerHookEventHandler 등가) 추가 검토.

### P6 — 하위 호환성 (계승)

기존 21-stage / 5 scaffold / Phase 7 strategy flips 는 그대로. 신규 capability 는 모두 additive — 기존 worker_adaptive / vtuber preset 동작 0 회귀.

### P7 — geny-executor first (계승, 단 critical 갱신)

원래는 executor 가 모든 capability 의 single source. 하지만 claude-code 의 Task / Cron / Worktree / LSP 같은 *host-runtime-coupled* tool 들은 executor 보다 **Geny host 자체** 에서 직접 구현하는 게 나을 수도 있음. 사례별 판단 필요 — `04_design_sketches.md` 에서 항목별로.

### P8 — Rich built-in catalog (계승, **확장**)

이전 목표: 6 → 15+. 현재 13 ship. **새 목표: 13 → 35+** (claude-code 의 39 stable + 9 feature-gated 중 host 에 의미 있는 것 모두).

## 3. Scope (in / out)

### In scope (본 분석 대상)

- claude-code-main 의 모든 surface ↔ Geny 매핑
- Severity / 의존성 / 영향도 분류
- Top 5 priority 의 design sketch
- 권장 cycle 구조

### Out of scope (별도 cycle / 영구 제외)

- **Anthropic 내부 전용 기능** (USER_TYPE='ant' gated): coordinator mode / dream tasks / kairos webhooks 등 → 영구 제외 (라이센스 + 의도)
- **VS Code extension surface** (SSE-IDE transport / vscodeSdkMcp) → Geny 가 standalone web app 이라 의미 없음 → 영구 제외
- **CLI TTY rendering** (Ink components) → Geny 는 web UI 라 다른 UI 모델 → 영구 제외 (다만 progress hint / spinner 메타데이터는 web UI 에 적용 가능)
- **Frontend editor UI** (permission/hook/skill 편집) — 기존 `executor_uplift/20260425_2` G13 viewer 위에 editor 얹는 별도 cycle
- **Frontend test infra** (vitest + RTL) — 기존 audit 의 carve-out, 별도 infra cycle

### 본 분석이 *덮지 않는* 위험

운영 데이터 부족: cycle 1+2 가 prod 에 떴지만 운영 운영 일주일 미만. **운영 후 발견될 결함** 은 본 분석 범위 밖. audit cycle 을 다시 돌려야 catch.

## 4. 다음 문서

- [`02_capability_matrix.md`](02_capability_matrix.md) — 53-item 매트릭스
- [`03_priority_buckets.md`](03_priority_buckets.md) — P0–P3 분류 + 권장 cycle 묶음
- [`04_design_sketches.md`](04_design_sketches.md) — top 5 priority design
- [`05_appendix_inventory.md`](05_appendix_inventory.md) — claude-code-main 전체 surface (참조용)
