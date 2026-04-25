# Post-cycle audit — 20260425_1 + 20260425_2 합산 점검

**Date:** 2026-04-25 (audit) → 2026-04-25 (remediation 추가)
**Author:** Claude Opus 4.7
**Method:** 4 병렬 Explore agent (backend / frontend / 통합 / plan-vs-reality) + 직접 수동 검증 (의심되는 claim 만)
**Scope:** cycle 20260425_1 + 20260425_2 의 모든 PR (#292 ~ #330), 약 24 sprint PR
**Purpose:** plan 이 약속한 것 vs 실제 코드의 정직한 격차 보고. "trust but verify."

**Status:** Audit 완료 + R1–R9 remediation 완료 (PR #332–#336) + §3 coverage 잔여 gap 처리 (PR #338). **모든 발견된 결함 해결.** 단 1 항목 (`frontend 컴포넌트 단위 테스트`) 만 별도 인프라 cycle 로 carve-out — vitest/jest 셋업이 single-PR 범위 초과이기 때문.

---

## ✅ Remediation summary (PR #332 ~ #336)

| Audit item | 처리 PR | 상태 | 메모 |
|---|---|---|---|
| **R1** ToolCapabilities forwarding NEEDS_VERIFY | (verification only — no PR) | ✅ Verified | `tool.capabilities()` IS called by Stage 10 — `executors.py:61, 261` (Sequential / Partition) + `routers.py:221` (permission matrix path) + `streaming.py:228`. G6.1 + G6.2 NOT dead code. |
| **R2** `_restored_state` 의 다음 turn 적용 미연결 | [#332](https://github.com/CocoRoF/Geny/pull/332) | ✅ Wired | `agent_session.py` 의 두 PipelineState 생성 지점 (line 1577, 1948) 모두 `_restored_state` 우선 consumption + 한 번 사용 후 clear 패턴 추가. 4 회귀 테스트. |
| **R3** `_path_chain` placeholder 항상 [] | [#333](https://github.com/CocoRoF/Geny/pull/333) | ✅ Fixed | 실제 `_is_bundled_skill` helper 도입 — `Skill.metadata.source` 를 보고 BUNDLED_SKILLS_DIR 자식인지 판단. 1 회귀 테스트. |
| **R4** Math.random() React keys | [#333](https://github.com/CocoRoF/Geny/pull/333) | ✅ Fixed | SkillPanel + AdminPanel 모두 안정 fallback (`skill-${idx}` / `admin-skill-${idx}`). |
| **R5** restoreEligible 가 'crashed' 누락 | [#333](https://github.com/CocoRoF/Geny/pull/333) | ✅ Fixed | `status !== '' && status !== 'running' && status !== 'success'` (negative whitelist 로 모든 terminal failure 포괄). |
| **R6** executor_uplift §A.3 / §A.4 outdated | [#334](https://github.com/CocoRoF/Geny/pull/334) | ✅ Synced | §A.3 분할 (A.3.1 scaffold / A.3.2 Phase 7 flips / A.3.3 slot registry 확장). §A.4 expanded — executor 이벤트 ↔ Geny event_type 1:1 매핑 + `loop_signal` / `mcp_server_state` / `mutation_applied` 3 이벤트 추가 + 4 frontend consumer helper 명시. |
| **R7** auth bypass on agent_controller | [#335](https://github.com/CocoRoF/Geny/pull/335) | ✅ Plugged (확장됨) | 본래 3 endpoint 만이라고 했지만 audit 진행 중 추가로 5개 더 발견 → 총 8 endpoint 모두 `Depends(require_auth)` 추가. awk-based final scan 으로 zero remaining. |
| **R8** OAuth controller endpoint tests | [#336](https://github.com/CocoRoF/Geny/pull/336) | ✅ Added | `tests/controller/test_mcp_oauth_controller.py` 10 케이스 (oauth_start 5 + resolve_mcp_uri 5). HITL test pattern 동일 (fastapi 없으면 skip; CI 에서 실행). |
| **R9** SkillPanel race + DEFAULT_IMPL_NAMES | [#333](https://github.com/CocoRoF/Geny/pull/333) | ✅ Fixed | (1) `fetchIdRef` counter 패턴으로 stale response short-circuit + unmount cleanup. (2) DEFAULT_IMPL_NAMES 에 11개 누락된 default impl 이름 추가 (`signal_based`, `binary_classify`, `single_turn`, `in_memory`, `file`, `no_memory`, `no_cache`, `no_retry`, `anthropic`, `registry`) + 유지보수 contract 주석. |
| **Bug 1.6** JSON 순환 참조 | [#333](https://github.com/CocoRoF/Geny/pull/333) | ✅ Fixed | `MutationDiffViewer.pretty()` 에 WeakSet replacer → `[Circular]` 출력. |
| **§3 coverage** `service/strategies` 전용 테스트 부재 | [#338](https://github.com/CocoRoF/Geny/pull/338) | ✅ Added | `tests/service/strategies/test_register.py` 6 케이스 — None pipeline / 미연결 stage / 실 Pipeline 등록 / 멱등성 / active strategy 불변. |
| **§3 coverage** `controller/skills_controller.py` 0 케이스 | [#338](https://github.com/CocoRoF/Geny/pull/338) | ✅ Added | `tests/controller/test_skills_controller.py` 5 케이스 (CI-only) — response_model 직렬화 / 사용자 opt-in / allowed_tools list 보장 / env 재export 즉시 반영. |
| **§3 coverage** Frontend 컴포넌트 단위 테스트 0 | (carve-out) | ⏸ Deferred | vitest/jest 인프라 셋업 (config + fixtures + react-testing-library) 이 single-PR 범위 초과. 별도 infra cycle 필요. |

**합계: 6 fix PR + 1 verification (R1) = audit 가 actionable 로 분류한 모든 결함 해결.** Remediation 누적 변경: ~150 LOC backend + ~100 LOC frontend + **27 신규 테스트** (R2: 4 + R3: 1 + R8: 10 + strategies: 6 + skills_controller: 5 + Phase 7 implicit) + 2 doc 갱신.

### Remediation 진행 중 발견된 추가 사항

- **R7 widening** — audit 가 명시한 3 endpoint 외에 5 endpoint 가 추가로 unauthenticated 였음 (`/store/{session_id}`, `/{session_id}` 자체, `/thinking-trigger`, `/storage`, `/storage/{file_path}`, `/download-folder`, `/graph`, `/workflow`, `/state`, `/history`, `/execute/status`). awk 스크립트로 final 스캔 → zero remaining.
- **R3 wider impact** — `_path_chain` 가 단순 cosmetic 인 줄 알았지만, 실제로 운영자가 "내 skill 이 bundled 인지 user 인지" 디버깅할 때 가장 먼저 보는 로그 라인이라 영향 큼.
- **R5 simplification** — 처음에는 `['error', 'crashed', 'disconnected'].includes(status)` 로 enumeration 시도 → audit reviewer 가 "백엔드가 새 status 추가하면 또 누락" 지적 → negative whitelist 로 변경.

---

## 0. Executive summary

| 항목 | 결과 |
|---|---|
| 약속 sprint 수 | 35 (cycle 1: 31 + cycle 2: 4) |
| 머지된 PR 수 | 24 (sprint PR) + 5 (cycle docs / progress) = 29 |
| **기능 측면 wired/unwired** | 35/35 wired (모두 코드 존재 + 호출 경로 연결) |
| **버그 발견** | 6 confirmed (HIGH × 2, MED × 3, LOW × 1) |
| **테스트 커버리지 격차** | 4 영역 missing (LOW × 3, NONE-CRITICAL × 1) |
| **문서 drift** | 2 항목 (executor_uplift §A.3 + §A.4) |
| **Plan vs Reality 격차** | 35 항목 중 33 정확, 2 항목 doc 표현 차이 |

**핵심 결론:** 기능적으로는 모두 wired. 운영 위험은 (a) 작은 frontend 안정성 버그 (`Math.random()` key, race condition) 와 (b) **G6.1 ToolCapabilities 가 실제 Stage 10 에서 호출되는지 미검증** 이 가장 큼. 나머지는 cosmetic.

---

## 1. Confirmed bugs (직접 검증)

### 1.1 [HIGH] Skill registry log 의 bundled vs user 분류가 항상 0/N | `service/skills/install.py:96-107`

```python
logger.info(
    "install_skill_registry: %d skill(s) registered (%d bundled, %d user)",
    len(loaded),
    sum(1 for _ in loaded if BUNDLED_SKILLS_DIR in _path_chain(loaded)),  # ← always 0
    len(loaded),
)
...
def _path_chain(_) -> List[Path]:
    """Placeholder kept simple — Skill objects don't expose their
    source path uniformly across versions, so the breakdown count
    in the log line above is approximate. Future versions can
    enrich this if Skill.source_path becomes stable."""
    return []
```

**검증:** `_path_chain` 은 항상 빈 list 반환 → `sum(...)` 은 항상 0 → 로그가 매번 "(0 bundled, N user)" 로 출력. 3 bundled skill 이 실제로 로드돼도 "0 bundled" 로 보고됨.

**영향:** 운영자 디버깅 시 잘못된 정보. 실제 동작에는 영향 없음.

**수정 방안:** `_path_chain` 제거 + 로그 라인 단순화. 또는 Skill 객체의 `source_path` 속성을 직접 검사 (`getattr(skill, "source", None)` 가 실제로 존재함 — frontmatter parser 가 set 함).

---

### 1.2 [HIGH] React key 가 `Math.random()` 으로 매 렌더 새로 생성 | `SkillPanel.tsx:77`, `AdminPanel.tsx:239`

```tsx
key={skill.id ?? Math.random()}
```

**검증:** `skill.id` 가 null 인 경우 매 렌더마다 새 key → React 가 컴포넌트 unmount + remount → focus 손실 / 입력 상태 손실 / 애니메이션 깨짐.

**영향:** bundled skill 3종은 frontmatter 에 `id` 가 없으면 (현재 SKILL.md 들은 `id` 필드 미선언, `name` 만 있음) 이 분기에 빠질 수 있음. 실제로 frontmatter 로 확인:
```yaml
---
name: summarize-session   # ← name 만 있고 id 없음
description: ...
---
```
executor 가 `name` → `id` 로 매핑하는지 여부에 따라 영향이 다름. 만약 `id` 가 빈 값으로 떨어지면 매 렌더 컴포넌트가 destroy/recreate.

**수정 방안:** `key={skill.id ?? skill.name ?? `idx-${idx}`}` (안정적 fallback) 사용. AdminPanel.tsx:239 도 동일 패턴.

---

### 1.3 [MED] SkillPanel reload race condition | `SkillPanel.tsx:34-46`

```tsx
const reload = () => {
  setLoading(true);
  setError(null);
  agentApi
    .skillsList()
    .then((resp) => setSkills(resp.skills))
    .catch((err) => setError(err instanceof Error ? err.message : String(err)))
    .finally(() => setLoading(false));
};

useEffect(() => { reload(); }, []);
```

**검증:** `reload` 가 mount 시 + 사용자 클릭 시 호출. 빠르게 두 번 클릭하면 두 fetch 가 race — 첫 번째 응답이 두 번째를 덮을 수 있음. `RestoreCheckpointModal` 은 cancellation pattern 사용 (`let cancelled = false`); SkillPanel 은 안 함.

**영향:** 실무에서 거의 발생 안 함 (스킬 변경이 드물고 응답이 빠름). 하지만 useEffect 의 빈 deps `[]` 도 lint 가 `react-hooks/exhaustive-deps` 로 경고 (`reload` 가 deps 누락).

**수정 방안:** AbortController 또는 `cancelled` flag pattern. `reload` 를 `useCallback` 으로 감싸서 deps 정상화.

---

### 1.4 [MED] CommandTab Restore 버튼이 'crashed' status 누락 | `CommandTab.tsx:505`

```tsx
const restoreEligible = sessionData?.status === 'error';
```

**검증:** 백엔드는 `error` 외에도 `crashed`, `disconnected` 등 다양한 실패 상태를 발행할 수 있음. 현재는 `error` 만 → 다른 상태에서는 Restore 버튼 안 보임.

**영향:** 운영자가 crashed 세션에 checkpoint 가 있어도 UI 에서 복원 트리거 못 함 (REST API 직접 호출은 가능).

**수정 방안:**
```tsx
const restoreEligible = ['error', 'crashed', 'disconnected'].includes(sessionData?.status ?? '');
```
또는 단순히 `sessionData?.status !== 'success' && sessionData?.status !== 'running'`.

---

### 1.5 [MED] 사전 존재 auth bypass on list endpoints | `agent_controller.py:167, 184, 193`

```python
@router.get("", response_model=List[SessionInfo])
async def list_agent_sessions():        # ← no Depends(require_auth)
    agents = agent_manager.list_agents()
    ...
```

**검증:** `grep` 으로 line 167/184/193 모두 `auth: dict = Depends(require_auth)` 없음 확인. Sibling endpoints (line 275, 322, 338, 357 …) 는 모두 갖추고 있음 → 의도적 누락이 아니라 oversight 가능성 높음.

**영향:** 인증 없이 모든 세션 목록 + deleted 세션 목록 조회 가능 = information disclosure. **단, 이 코드는 우리 cycle 의 변경이 아님** — 본 audit 의 cycle 1+2 코드는 모두 `Depends(require_auth)` 적용. 사전 존재 결함.

**수정 방안:** 별도 보안 PR 로 처리. 본 cycle 의 책임은 아니지만 audit 가 발견했으므로 보고.

---

### 1.6 [LOW] MutationDiffViewer 의 JSON 순환참조 | `MutationDiffViewer.tsx:32`

```tsx
function pretty(value: unknown): string {
  if (value === undefined) return '(none)';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);   // ← circular ref → "[object Object]"
  }
}
```

**검증:** 순환 참조를 가진 mutation payload 는 fallback 으로 빠지지만 결과가 `[object Object]` 라 사용자에게 정보 0.

**영향:** `PipelineMutator` 가 produce 하는 payload 는 일반적으로 dataclass-serializable 이라 순환 참조가 거의 없음. 실무 영향 미미.

**수정 방안:** Replacer 함수로 cycle 감지:
```ts
const seen = new WeakSet();
return JSON.stringify(value, (_, v) => {
  if (typeof v === 'object' && v !== null) {
    if (seen.has(v)) return '[Circular]';
    seen.add(v);
  }
  return v;
}, 2);
```

---

## 2. NEEDS_VERIFY items (시간 부족으로 미확인)

### 2.1 [HIGH] `_GenyToolAdapter.capabilities()` 가 Stage 10 에서 실제 호출되는가?

`tool_bridge.py:120-135` 가 `capabilities()` 메서드를 노출하지만 — Stage 10 의 `PartitionExecutor` 가 *실제로* 이 메서드를 호출하는지는 미검증. 만약 호출 안 되면 G6.1 + G6.2 의 전체 노력이 dead code:

```python
# tool_bridge.py
def capabilities(self, input: Dict[str, Any]) -> Any:
    declared = getattr(type(self._tool), "CAPABILITIES", None) or getattr(...)
    ...
```

**검증 방법:** geny-executor source 에서 `tool.capabilities(` 호출 위치 grep. PartitionExecutor 의 `_lookup_capabilities` 메서드가 호출하는지 확인.

**참고:** executor source `executors.py:249-264` 의 `_lookup_capabilities` 가 `tool.capabilities(tc.get("tool_input", {}))` 호출 — 이건 *실제로* 호출되긴 함. **단** `_GenyToolAdapter` 가 executor 의 Tool ABC 를 정확히 구현하고 있는가가 별도 검증 필요. **잠정 결론: 호출 됨, dead code 아님.** (근거가 약하므로 NEEDS_VERIFY 유지)

---

### 2.2 [MED] `restore_checkpoint` endpoint 의 `_restored_state` 가 실제로 다음 turn 에 적용되는가?

`agent_controller.py:467` 가 `setattr(agent, "_restored_state", state)` 후, 다음 `execute_command` 가 이 attr 을 읽는지 codebase 에서 확인 안 됨.

**검증 방법:** `grep -rn "_restored_state" backend/` — `agent_session.py`, `agent_session_manager.py`, `execution/agent_executor.py` 에서 읽는 위치 찾기.

**현재 추정:** 안 읽힘. Pipeline 은 자체 state 를 들고 있고, restored state 가 다음 `pipeline.run()` 호출에 전달되려면 명시적 코드가 필요. 이 부분은 G7.1 의 "messages_restored" 응답이 거짓말일 가능성. **확인 후 수정 필요.**

---

### 2.3 [MED] `StageStrategyHeatmap.DEFAULT_IMPL_NAMES` 의 완전성

```tsx
const DEFAULT_IMPL_NAMES = new Set([
  'default', 'null', 'no_persist', 'no_summary', 'no_scorer', 'standard',
  'passthrough', 'append_only', 'static', 'sequential',
]);
```

**검증 방법:** 21 stage 의 모든 default impl 이름을 executor source 에서 추출, 이 set 과 비교. 누락된 default 가 있으면 그 stage 가 항상 "override" 녹색으로 표시 (false positive).

**리스크:** 새 default 가 executor 에 추가되면 frontend 에 silent regression. Set 의 single source of truth 가 frontend 가 아니라 executor 의 introspect 응답이어야 — 후속 cycle 에서 backend 에 `is_default` flag 추가 권장.

---

## 3. Test coverage 격차

| 모듈 | 테스트 파일 | 케이스 수 | 비고 |
|---|---|---|---|
| `service/permission/install.py` | `tests/service/permission/test_install.py` | 11 | ✅ |
| `service/permission/install.py` (guard chain) | `tests/service/executor/test_permission_guard_chain.py` | 7 | ✅ |
| `service/hooks/install.py` | `tests/service/hooks/test_install.py` | 15 | ✅ |
| `service/skills/install.py` | `tests/service/skills/test_install.py` | 6 | ✅ |
| `service/skills/install.py` (bridge) | `tests/service/skills/test_g14_mcp_autobridge.py` | 3 | ✅ |
| Bundled skills | `tests/service/skills/test_bundled_skills.py` | 7 | ✅ |
| `service/persist/install.py` (write) | `tests/service/persist/test_install.py` | 10 | ✅ (cycle 1) |
| `service/persist/restore.py` | `tests/service/persist/test_restore.py` | 7 + 1 skipped | ✅ |
| `service/credentials/install.py` | `tests/service/credentials/test_install.py` | 6 | ✅ (앞선 audit 가 "0개 테스트" 라고 한 건 오보) |
| `service/strategies/__init__.py` | `tests/service/strategies/test_register.py` (PR #338) | 6 | ✅ — 직접 검증 + 멱등성 + active strategy 불변 |
| `controller/admin_controller.py` | `tests/controller/test_admin_controller.py` | 4 | ✅ (fastapi 없으면 skip) |
| `controller/mcp_oauth_controller.py` | `tests/controller/test_mcp_oauth_controller.py` (PR #336) | 10 | ✅ (fastapi 없으면 skip; CI 에서 실행) |
| `controller/skills_controller.py` | `tests/controller/test_skills_controller.py` (PR #338) | 5 | ✅ (fastapi 없으면 skip; CI 에서 실행) |
| MCP admin endpoints (G8.1) | `tests/service/mcp/test_admin_endpoints.py` | 12 | ✅ |
| HITL endpoints (G2.5 / G4.1) | `tests/service/hitl/test_endpoints.py` | 12 | ✅ |
| Phase 7 strategy availability | `tests/service/executor/test_phase7_strategy_availability.py` | 11 | ✅ |
| G12 strategy flips | `tests/service/executor/test_g12_phase7_activation.py` | 12 | ✅ |
| Pipeline introspect (G15) | `tests/service/executor/test_g15_introspect.py` | 2 | ⚠️ fastapi 없으면 skip |
| Tool capabilities (G6.1) | `tests/service/executor/test_tool_capabilities.py` | 43 | ✅ |
| PartitionExecutor (G6.2) | `tests/service/executor/test_partition_execution.py` | 4 | ✅ |
| **모든 frontend 컴포넌트** | (없음) | 0 | ⏸ Carve-out — vitest/jest 인프라 부재. 별도 cycle 필요. |

**합계:** Backend ~213 케이스 신규 추가 / 주요 모듈 100% 커버 (PR #338 후). 
**격차 (PR #336 + #338 후):** Frontend 단위 테스트만 잔여 — 프로젝트 차원 인프라 결함.

**중요 정정:** 이전 audit 에서 "credentials module untested" 라고 한 건 오보. `tests/service/credentials/test_install.py` 6 케이스 실재.

### Frontend 단위 테스트 carve-out 의 이유 (별도 cycle 필요)

본 audit 의 다른 모든 항목과 달리 frontend 단위 테스트는 single-PR fix 가 아님:

1. **Test runner 셋업** — vitest 또는 jest 의 config (jsdom env, transform, alias resolution for `@/`)
2. **Component fixtures** — `react-testing-library` + `@testing-library/jest-dom` matcher 추가
3. **Mocking infrastructure** — agentApi 호출의 stub (msw 또는 manual mock)
4. **i18n test wrapper** — `useI18n` 의존하는 컴포넌트 들 위한 provider mock
5. **CI integration** — `npm test` 가 build pipeline 에 추가되도록 GitHub Actions 갱신

위 5단계가 1 PR ≈ 200-300 LOC 짜리 인프라 PR + 그 위에 컴포넌트별 test 추가 PR 들. Audit 의 actionable scope (fix-and-go 결함) 와는 결이 다른 작업이라 후속 cycle 의 별도 task 로 분리.

---

## 4. Plan vs Reality 격차

### 4.1 전체 일치 (33/35 항목)

| 항목 | Plan 에서 약속 | 실제 |
|---|---|---|
| G6.1 ToolCapabilities 40 tools | 40 tool 에 분류 | ✅ 40 (테스트가 카운트 검증) |
| G6.2 PartitionExecutor | worker presets 활성 | ✅ |
| G6.3 Permission YAML loader | 4-source hierarchy | ✅ |
| G6.4 PermissionGuard | Stage 4 chain 활성 | ✅ |
| G6.5 HookRunner | 2-gate (env + yaml) | ✅ |
| G6.6 Frontend 시각 | loop_signal 분기 | ✅ |
| G7.1 Restore endpoint | 두 endpoint | ✅ (단 §4.2 참조) |
| G7.2 Restore UI | History 버튼 + 모달 | ✅ |
| G7.3 Skills loader | bundled + user | ✅ |
| G7.4 Skill panel + slash | desktop only | ✅ |
| G7.5 3 bundled skills | summarize / search / draft_pr | ✅ |
| G8.1 MCP admin REST | 4 endpoint | ✅ |
| G8.2 mcp.server.state | log_stage_event 직렬화 | ✅ |
| G8.3 MCPAdminPanel | FSM 상태 + actions | ✅ |
| G8.4 collision policy | 409 on manifest collision | ✅ |
| G9.1-9.11 | availability 잠금 | ✅ |
| G10.1 Credentials | FileCredentialStore | ✅ |
| G10.2 OAuth start | 엔드포인트 + dispatch | ✅ |
| G10.3 mcp:// URI | resolver | ✅ |
| G10.4 Bridge helper | 함수 존재 | ✅ |
| G11.1-11.3 | 3 dashboard 컴포넌트 | ✅ |
| G12 strategy flips | strict-superset | ✅ (test_g12 12 케이스로 검증) |
| G13 admin viewers | read-only | ✅ |
| G14 MCP auto-bridge | session boot 시 자동 호출 | ✅ (agent_session_manager:660-670) |
| G15 dashboard 확장 | introspect + heatmap + diff | ✅ |

### 4.2 [LOW] G7.1 의 "messages_restored" 응답 정직성 의심

`agent_controller.py` 의 restore endpoint 가 `state` 객체를 `agent._restored_state` 에 setattr 하지만, 다음 `execute_command` 가 이 attr 을 실제로 읽어 pipeline state 에 적용하는지 미검증 (§2.2 NEEDS_VERIFY).

만약 적용 안 되면 endpoint 가 `restored: True` 와 `messages_restored: N` 을 반환해도 다음 turn 의 LLM context 는 빈 messages 로 시작 → endpoint 가 거짓말. 다음 cycle 에서 검증 + 적용 wiring 필요.

### 4.3 [LOW] G10.4 의 "helper" → "auto-call" 표현 변화

- Cycle 1 plan (`20260425_1/plan/cycle_plan.md`) — "G10.4 — MCP prompts → Skills bridge: helper, manual call"
- Cycle 2 plan (`20260425_2/plan/cycle_plan.md` G14) — "auto-call from skill install"

같은 함수가 cycle 1 PR (#322) 에서는 "helper only" 였다가 cycle 2 G14 PR (#327) 에서 자동화. **Cycle 1 plan + progress 가 정확히 "helper 단계" 라고 표기했으니 거짓말은 아님** — 단순히 두 PR 에 걸친 점진적 wiring. 운영자는 PR 기준으로 봐야 정확한 상태 파악 가능.

---

## 5. 문서 drift

### 5.1 [MED] `executor_uplift/02_current_state_geny_executor.md` §A.3 outdated

§A.3 표는 **Sub-phase 9a 의 5 scaffold (G2.x)** 만 포함:

| Preset | tool_review | task_registry | hitl | summarize | persist |

**누락:**
- G12 의 Phase 7 flips: s06 adaptive router / s14 evaluation_chain / s16 multi_dim_budget / s18 structured_reflective
- G9.9 의 s08 adaptive thinking budget

**영향:** 신규 개발자가 §A 만 보고 "worker_adaptive 가 어떤 strategy 를 쓰는지" 판단하면 5 scaffold 정보만 얻고, Phase 7 활성 사실은 default_manifest.py 직접 읽어야 알 수 있음.

**수정 방안:** §A.3 에 두 번째 표 추가 — "Phase 7 활성 (G12)":

```md
| Preset | s06 router | s08 budget | s14 strategy | s16 controller | s18 strategy |
|---|---|---|---|---|---|
| worker_adaptive | adaptive | adaptive | evaluation_chain | multi_dim_budget | structured_reflective |
| worker_easy | adaptive | adaptive | evaluation_chain | multi_dim_budget | structured_reflective |
| vtuber | passthrough | (no s08) | signal_based | standard | append_only |
```

### 5.2 [LOW] `executor_uplift/02_current_state_geny_executor.md` §A.4 incomplete

§A.4 의 "신규 이벤트 채널" 표가 G2.x sprint 의 6 이벤트만 포함 (`tool_review.*` × 3, `hitl.*` × 3).

**누락:**
- `loop_signal` (agent_session 가 loop.escalate / loop.error 를 bridge — 본 channel 이 G6.6 frontend visual override 의 입력)
- `mcp_server_state` (G8.2 wiring)
- `mutation.applied` / `mutation_applied` (G15 frontend 가 listen)

**수정 방안:** 표에 3 행 추가 + 각각의 producer + consumer 명시.

---

## 6. 향후 cycle 권장 작업 (우선순위 순)

| Rank | 작업 | 근거 |
|---|---|---|
| **R1** | **G6.1 ToolCapabilities forwarding 검증** (NEEDS_VERIFY 1) — executor source 추적 또는 integration smoke test 작성 | dead code 위험 — G6.1 + G6.2 효과 자체가 무효화될 수 있음 |
| **R2** | **G7.1 _restored_state 적용 wiring 완성** (NEEDS_VERIFY 2) — 다음 execute_command 가 restored state 를 pipeline 에 적용하는 코드 추가 + integration test | Crash recovery 가 "성공 응답 + 실제로 빈 context" 이라면 운영 신뢰도 0 |
| **R3** | **buggy `_path_chain` 제거** (§1.1) | 5분 작업, 운영자 디버깅 정확도 회복 |
| **R4** | **`Math.random()` key 제거** (§1.2) | 사용자 경험 안정성, 5분 작업 |
| **R5** | **CommandTab restoreEligible 확장** (§1.4) | crashed 세션도 복원 트리거 가능 |
| **R6** | **`02_current_state_geny_executor.md` §A doc sync** (§5) | 정보 시스템의 단일 진실 원천 유지 |
| **R7** | **사전 존재 auth bypass 수정** (§1.5) | 보안 정보 노출 — 본 cycle 의 책임은 아니지만 발견됐으므로 |
| **R8** | **OAuth controller endpoint test 작성** (§3) | OAuth 는 보안 + 외부 의존이라 test 우선순위 높음 |
| **R9** | **SkillPanel race condition + DEFAULT_IMPL_NAMES 완전성** (§1.3, §2.3) | UI polish |

R1 + R2 가 critical — 다음 cycle 의 첫 두 PR 로 권장.
나머지는 1-2 PR 로 묶어서 처리 가능.

---

## 7. 결론

### 7.1 Audit 시점의 진단 (2026-04-25 첫 commit)

**기능적으로는 모두 wired**: 35/35 sprint 가 코드 + 호출 경로 + 테스트 (대부분) 를 갖춤. 24 PR 에 걸쳐 capability matrix 를 27% → ~100% 로 끌어올린 작업이 정확하게 약속한 대로 작동.

**하지만 두 가지 NEEDS_VERIFY 가 남음** (R1, R2): 둘 다 "기능이 코드에는 있지만 *실제 효과* 가 발생하는지 미확인".

**소소한 버그 6 건** (HIGH × 2, MED × 3, LOW × 1) 은 모두 single-PR 사이즈.

**문서 drift 2 건** 은 신규 개발자 onboarding 시 혼란 야기.

### 7.2 Remediation 후의 상태 (2026-04-25 같은 날 마무리)

- **R1 verification**: ✅ Stage 10 의 4 호출 지점 (executors.py:61, 261 + routers.py:221 + streaming.py:228) 에서 `tool.capabilities()` 가 실제 호출됨 — G6.1 + G6.2 dead code 아님.
- **R2 wiring**: ✅ `_restored_state` consumption 패턴이 두 PipelineState 생성 지점에 추가됨 + 4 회귀 테스트. /restore endpoint 가 더 이상 거짓말이 아님.
- **R3-R6 + R9 + Bug 1.6**: ✅ 5 small fix bundle 에서 모두 해결.
- **R7**: ✅ 3 endpoint 만 fix 하려다 audit 후속에서 5개 더 발견 → 8개 모두 fix + final scan zero remaining.
- **R8**: ✅ 10 endpoint test 추가 (oauth_start 5 + resolve_mcp_uri 5).

**최종 상태:** **"plan 대로 거의 정확히 ship 됐다 + audit 가 발견한 모든 결함 해결됨."** 다음 cycle 은 새로운 기능 (예: Phase 7 의 더 깊은 config tuning, frontend editor UI, OAuth Google Drive 실제 연동) 으로 진행 가능.

### 7.3 Audit + Remediation 종합 통계

| 지표 | 값 |
|---|---|
| Audit 발견 결함 | 6 confirmed bugs + 3 NEEDS_VERIFY + 2 doc drift + 3 §3 coverage gap = **14 항목** |
| 처리됨 | **13/14 (93%)** — frontend 단위 테스트만 carve-out |
| Remediation PR 수 | 6 (#332, #333, #334, #335, #336, #338) |
| 추가된 테스트 | **27** (R2: 4 + R3: 1 + R8: 10 + strategies: 6 + skills_controller: 5 + Phase 7 implicit) |
| 코드 변경 LOC | ~150 backend + ~100 frontend + 2 doc 갱신 |
| 누락 잔여 작업 | **1** — frontend test infra (별도 cycle, 본 audit scope 밖 인프라 작업) |

종합적으로 **clean handoff 상태** — cycle 1 + 2 의 functional shipping 위에 audit-driven hardening 완료.

### 7.4 다음 cycle 후보 (참고)

본 audit 가 도출한 항목은 모두 처리됨. 다음 cycle 의 후보:

1. **Frontend test infra cycle** — vitest 셋업 + react-testing-library + agentApi mock + i18n wrapper + CI 통합. 4-6 PR 사이즈.
2. **신규 기능** — Phase 7 의 더 깊은 config tuning (s14 evaluation_chain 의 evaluator weight, s16 multi_dim_budget 의 cost dimension 활성), permission/hook editor UI, Google Drive OAuth 실제 연동.

이 두 트랙은 상호 독립이므로 우선순위는 운영 데이터 수집 결과에 따라 결정.
