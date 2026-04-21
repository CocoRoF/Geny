# PR-X1-4 · `test/persona-e2e` — 진행 기록

**Date.** 2026-04-21
**Status.** Implemented, 36 persona cases pass (기존 30 + e2e 6).

## 목적

PR-X1-3 회귀 위험 평가에서 지목한 "mid-session prompt 변경이 실제로 반영되는지" 시나리오 단위로 검증. `AgentSessionManager` + `AgentSession` + `CharacterPersonaProvider` + `DynamicPersonaSystemBuilder` 의 상호작용을 manager 의 contract 만 흉내내서 (실제 pipeline 은 API key/env/DB 의존이 크므로) 재현한다.

## 추가된 파일

`backend/tests/service/persona/test_persona_lifecycle.py` — 6 시나리오.

### Fixtures

- `chars_dir` (tmp): `catgirl.md`, `robot.md`, `default.md` 각각 `## Character Personality` 헤더 + 1 줄 body.
- `provider`: `CharacterPersonaProvider(characters_dir=…, default_vtuber_prompt="VTUBER_DEFAULT", default_worker_prompt="WORKER_DEFAULT", adaptive_prompt="ADAPTIVE_TAIL")`.

### Helpers

- `_builder_for(provider, session_id, *, is_vtuber)` — `AgentSession._build_pipeline` 의 wiring 을 그대로 재현 (`session_meta={session_id, is_vtuber, role, owner_username=None}`, `tail_blocks=[DateTimeBlock(), MemoryContextBlock()]`).
- `_simulate_create(provider, sid, initial_prompt)` — manager 의 `create_agent_session` 내 seed 단계 (`provider.set_static_override(session_id, built_prompt)`) 를 단독 호출.

### 시나리오

1. **`test_vtuber_session_lifecycle`** — create → character 교체 → PUT /system-prompt 로 override → soft-delete (reset) → restore 까지 5 턴. 각 턴마다 `builder.build(PipelineState())` 를 호출해 결과 문자열을 확인.
   - 캐릭터 append 는 override 와 독립 상태라 override 후에도 유지됨.
   - reset 은 provider 상태를 완전히 비워 role default 로 복귀.
   - restore 시 manager 는 sessions.json 의 built_prompt 로 재시드하고, 이후 custom override 를 별도 재스테이징 (캐릭터는 sessions.json 에 없으므로 복구되지 않음 — legacy 동작과 동일).

2. **`test_sub_worker_context_injection_on_vtuber`** — VTuber + sub-worker 페어링 시 manager 가 `provider.append_context(session_id, vtuber_ctx)` (SD3 대체) 로 "## Sub-Worker Agent ..." 섹션을 추가. 같은 텍스트로 다시 호출해도 중복되지 않는 idempotence 도 확인.

3. **`test_session_isolation_and_cascade_restore`** — VTuber 와 linked worker 가 서로 다른 override 를 가질 때 provider 상태가 session_id 로 격리되는지. Soft-delete → cascade restore (agent_controller 의 SD4 + SD5 시나리오) 까지 확인. 각 턴에서 VTuber 는 ADAPTIVE tail 이 없고 worker 는 있어야 한다.

4. **`test_character_swap_between_turns`** — `set_character("catgirl")` → 다음 턴에 catgirl → `set_character("robot")` → 다음 턴에 robot only (catgirl 흔적 없음). DynamicPersonaSystemBuilder 의 per-turn resolve 가 즉시 반영됨을 확인.

5. **`test_empty_static_override_falls_back_to_role_default`** — `set_static_override(sid, None)` 을 worker 세션에 호출 시 `_WORKER_DEFAULT` + ADAPTIVE tail 로 복귀.

6. **`test_cache_key_changes_with_mutations`** — 기본 → override → character → context 4 단계 flag 변화에서 각 단계의 `cache_key` 가 서로 다름을 확인 (prompt-cache 계층이 persona 변경을 감지하는 메커니즘). cache_key 는 **flag presence** 만 추적하므로 이미 set 된 flag 를 content 만 바꾸며 다시 set 하는 건 key 변화를 일으키지 않음 — 이 의도(content-oblivious cache bust)를 docstring 에 명시.

## 테스트 결과

- `backend/tests/service/persona/` — **36 pass** (30 기존 + 6 신규).
- 다른 경로는 PR-X1-3 에서와 동일한 environment 이슈 (fastapi/numpy 누락) 외엔 건드리지 않음.

## 설계 메모

- **왜 sync helper 인가** — `DynamicPersonaSystemBuilder.build` 는 sync 이므로 (PromptBuilder 규약) 이벤트 루프 없이 그대로 호출. `PipelineState()` 기본 인스턴스만으로 충분 (persona 는 state 에 의존하지 않음).
- **왜 실제 Pipeline 을 띄우지 않는가** — SystemStage/프롬프트-캐시/LLM wiring 을 전부 띄우면 테스트 대상(provider + builder 계약) 외 수많은 의존성이 엮여 의미 있는 보호 범위가 오히려 좁아짐. manager 가 "create 시 override 시드 → 호출 시 provider 에 mutate → 매 턴 builder.build" 한다는 *계약* 만 명시적으로 재현해 대상 경계를 유지.
- **character.md 는 왜 tmp_path?** — repo 의 `backend/prompts/vtuber_characters/` 실물을 테스트에서 직접 참조하면 캐릭터 목록 변경 시 테스트가 부러짐. 미니 fixture 로 독립성 확보.

## 잔여

- X1 cycle (`CharacterPersonaProvider + DynamicPersonaSystemBuilder + 5 SD 제거`) 이 이 PR merge 로 종결.
- 다음 cycle: **X2 — `SessionLifecycleBus` + `TickEngine`** (plan: `dev_docs/20260421_6/plan/05_cycle_and_pr_breakdown.md` 의 6 PR 분해).
