# new-executor-uplift — claude-code parity 분석 (layer-aware)

**Date:** 2026-04-25 (revised — layering principle 적용)
**Status:** Analysis only — no plan / no PRs (caller decides cycle scope)
**Purpose:** 직전 cycle (executor_uplift / 20260425_*) 으로 capability matrix 27% → ~85% 달성. 본 분석은 *남은 ~15%* 를 `claude-code-main` 의 실제 surface 와 1:1 비교하고, **2-layer 아키텍처 (geny-executor framework + Geny service)** 관점에서 priority + 양 repo PR 분포를 도출.

---

## ⭐ 핵심 axiom — Layering principle

> `geny-executor` = **built-in core (claude-code-main reference) + extension interface (ABC + register API)**.
> `Geny` = **service consuming geny-executor** (도메인 / REST 어댑터 / 웹 UI / 운영 인프라).

**파생 규칙:**
- claude-code-main 의 framework 표준 capability → 거의 모두 **geny-executor 측** PR
- Geny 측은 **register / wire / REST 어댑터 / 웹 UI / 도메인 backend** 에 집중
- Geny 가 framework concern (tool 표준 라이브러리 / slash command 파서 / cron daemon) 을 자체 구현하면 **anti-pattern**

상세 결정 트리 + 케이스별 분류는 [`00_layering_principle.md`](00_layering_principle.md). 본 폴더의 모든 priority / design 은 본 원칙에서 파생.

---

## 폴더 구조

```
new-executor-uplift/
├── index.md                         ← 이 파일
├── 00_layering_principle.md         ★ NEW — 2-layer 아키텍처 axiom (가장 중요)
├── 01_overview.md                   ← 목표 + 원칙 (P0 layering 추가, P7 갱신)
├── 02_capability_matrix.md          ← claude-code vs Geny 53-item 표 + Layer 컬럼
├── 03_priority_buckets.md           ← P0/P1/P2/P3 + (executor / Geny) 양 repo PR 분포
├── 04_design_sketches.md            ← 각 priority 의 (executor-side / interface / service-side) 3 단 design
└── 05_appendix_inventory.md         ← claude-code-main 전체 surface inventory (참조용)
```

---

## 한 눈에 보는 결과

### Status (53 항목)

| 분류 | Count | 상태 |
|---|---|---|
| **SHIPPED** | 21 | 동등 또는 우월 |
| **PARTIAL** | 21 | 부분 구현 |
| **MISSING** | 9 (3 OUT_OF_SCOPE 제외) | 등가 0 |
| **OUT_OF_SCOPE** | 3 | XAA / SSE-IDE / Anthropic-internal |
| **합계** | **53** | |

### Layer 분포

| Layer | 항목 수 | 의미 |
|---|---|---|
| **EXEC-CORE** (built-in) | ~32 | claude-code 의 framework 표준 → geny-executor 측 PR |
| **EXEC-INTERFACE** (ABC + register API) | ~8 | ABC 추가 / register API 노출 → executor 측 PR |
| **SERVICE** | ~8 | REST / 웹 UI / 도메인 backend / 운영 → Geny 측 PR |
| **BOTH** | ~5 | 양 repo 동시 작업 |
| **OUT_OF_SCOPE** | 3 | — |

### PR 무게중심 (P0+P1, 50 PR)

| Repo | PR 수 | % |
|---|---|---|
| **geny-executor** (1.1 + 1.2 minor 두 차례) | 31 | 62% |
| **Geny** (executor minor 채택 후) | 19 | 38% |

→ **다음 cycle 의 무게중심은 geny-executor 레포로 이동**. Geny 측 작업은 register / wire / UI / REST 에 집중.

---

## 가장 큰 격차 3개 (모두 framework concern)

| # | 항목 | 작업 위치 | PR 수 |
|---|---|---|---|
| 1 | **Task lifecycle 부재** | executor (5) + Geny (5) | 10 |
| 2 | **Slash commands 부재** | executor (4) + Geny (2) | 6 |
| 3 | **Tool catalog 26개 부족** (HIGH/MED 14) | executor (7) + Geny (2) | 9 |

---

## 권장 cycle 구조 (cross-repo)

```
Cycle A — new-executor-uplift / 20260426_1 (executor 1.1 → Geny adopt)
  geny-executor PR    [19] ──→ release 1.1.0
                              ──→ Geny pyproject 1.1.x bump
  Geny PR             [12]  
  합계: 31 PR

Cycle B — new-executor-uplift / 20260427_1 (executor 1.2 → Geny adopt)
  geny-executor PR    [11] ──→ release 1.2.0
                              ──→ Geny pyproject 1.2.x bump
  Geny PR             [8]  
  합계: 19 PR

Cycle C — audit + carve-outs (양 repo 동시)
```

---

## 다음 행동

본 분석은 *report*. 사용자가 cycle 시작 시점에 [`04_design_sketches.md`](04_design_sketches.md) 를 plan baseline 으로 사용 권장.

**시작 권장 순서:**
1. [`00_layering_principle.md`](00_layering_principle.md) — axiom 의 합의
2. [`01_overview.md`](01_overview.md) — 목표 + scope 의 동의
3. [`02_capability_matrix.md`](02_capability_matrix.md) — 항목별 layer 의 검증
4. [`03_priority_buckets.md`](03_priority_buckets.md) — P0 묶음의 cycle 동의
5. [`04_design_sketches.md`](04_design_sketches.md) — 첫 cycle 의 PR 분해 baseline
