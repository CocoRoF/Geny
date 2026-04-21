# PR-X1-3 · `refactor/remove-system-prompt-sidedoors` — 진행 기록

**Date.** 2026-04-21
**Status.** Implemented, 30 persona cases + 95 langgraph cases pass (그 외 numpy 누락, fastapi 누락 등 environment 이슈는 관계 없음).

## 적용된 변경

### 1. `backend/service/langgraph/agent_session.py`
- `__init__(persona_provider=None)` kwarg 추가 + `self._persona_provider` 보관.
- `persona_provider` property 노출.
- `_build_pipeline`: provider 가 주입된 경우 `DynamicPersonaSystemBuilder` (session_meta = session_id/is_vtuber/role/owner_username, tail_blocks = DateTime/MemoryContext) 를 `system_builder` 로. None 일 때는 기존 `ComposablePromptBuilder` 유지 (테스트 호환).
- `self._system_prompt` 는 immutable initial seed 로만 남김. `get_session_info()` 의 `SessionInfo.system_prompt` 는 여전히 초기값 보고.

### 2. `backend/service/langgraph/agent_session_manager.py`
- `CharacterPersonaProvider` 인스턴스 1개를 manager 스코프로 생성 (`_persona_provider` + public property).
  - `characters_dir=backend/prompts/vtuber_characters`, defaults = `_DEFAULT_VTUBER_PROMPT`/`_DEFAULT_WORKER_PROMPT`/`_ADAPTIVE_PROMPT`.
- `create_agent_session`:
  - `provider.set_static_override(session_id, built_system_prompt)` 시드.
  - `AgentSession.create(..., persona_provider=self._persona_provider)` 주입.
- **SD3 제거** — sub-worker delegation ctx 주입을 `provider.append_context(session_id, vtuber_ctx)` 로 교체.
- `delete_session` (soft) 에 `provider.reset(session_id)` 추가 (restore 시 sessions.json 에서 재시드).

### 3. `backend/controller/vtuber_controller.py`
- **SD1 제거** — `_inject_character_prompt` 를 `manager.persona_provider.set_character(session_id, model_name)` 호출 한 줄로 축소.
- Dead code (`agent.process.*`) 완전 삭제. `Path` import / `_CHARACTERS_DIR` 상수 제거 (provider 가 소유).

### 4. `backend/controller/agent_controller.py`
- **SD2 제거** (PUT /system-prompt) — `agent._system_prompt = new_prompt` → `agent_manager.persona_provider.set_static_override(session_id, new_prompt)`.
- **SD4 제거** (restore main session) — `agent._system_prompt = stored` → provider override.
- **SD5 제거** (restore linked session) — `linked_agent._system_prompt = linked_stored` → provider override (by linked_id).

### 5. `backend/tests/service/persona/test_sidedoor_removed.py` (신규)
- `_system_prompt = ...` write 패턴이 backend/ 전체에서 0건 (tests/, AgentSession.__init__ self-assign 제외) 임을 regex 로 assert.
- Allowlist 의 `self._system_prompt = system_prompt` 라인이 여전히 존재하는지도 확인 (sanity guard).

## 테스트 결과

- `backend/tests/service/persona/` — **30 pass** (test_sidedoor_removed 2 case 포함).
- `backend/tests/service/langgraph/` — **95 pass** (기존 테스트 회귀 없음).
- `backend/tests/controller/` — **1 pass** (test_chat_broadcast_sanitize).
- `backend/tests/service/vtuber/` — fastapi 누락으로 **3 error** (environment 이슈, 변경과 무관).
- `backend/tests/service/memory/` — numpy 누락으로 collect 실패 (environment 이슈, 변경과 무관).

## 의도적 비움

- `agent.process.system_prompt = ...` 동기화 라인 (plan/01 에 "유지" 로 적혀 있었지만 실제 확인 결과 `AgentSession` 에 `.process` 속성이 없어 모든 호출이 `AttributeError` 로 dead code 였음 — try/except 가 삼켰었음). X1 에서 완전 제거.
- VTuber 용 CLI 프로세스 `process.system_prompt` 동기화는 Claude Code CLI 전용 채널이었는데, `AgentSession` 은 CLI 를 쓰지 않으므로 의미 없었음. 기록만 남김.

## 회귀 위험 평가

- **중.** legacy 경로에서 mid-session prompt 변경 반영이 *새로* 가능해졌다 (이전엔 `_build_pipeline` 이 1회 호출되어 변경 미반영이 기본). 기존 사용 패턴이 "변경해도 어차피 다음 세션까지 반영 안 됨" 을 전제했다면 동작이 달라 보일 수 있음.
- 검증 방법 — PR-X1-4 에서 e2e 시나리오 (세션 생성 → 캐릭터 교체 → prompt 재구성 → restore → override 재적용) 로 확인.
- feature flag 는 현재 **미도입**. `persona_provider` 인자를 `AgentSession(__init__)` 에 None 으로 주면 기존 `ComposablePromptBuilder` 경로가 발동하므로 manager 수준에서의 on/off 스위치는 필요 시 한 줄 추가로 구현 가능. 초기 1주 관측 후 plan/02 롤백 기준으로 판단.

## 다음 PR

**PR-X1-4 · `test/persona-e2e`** — AgentSession + manager + provider 통합 시나리오.
