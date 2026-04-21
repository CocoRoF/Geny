# Plan 01 — X1 실행 계획 (PersonaProvider & 사이드도어 철거)

**상위 설계.** `dev_docs/20260421_6/plan/03_structural_completions.md §2`,
`plan/05 §1`.
**본 문서 책임.** 오늘 시점 코드 (`analysis/01_x1_sidedoor_recheck.md` 검증 결과) 를 기준으로
**구체적인 파일 수준 PR 계획** 을 확정.

**핵심 수정점 (상위 plan 대비).**
- 사이드도어 5곳 (SD1~SD5). `controller/agent_controller.py:482, 520` 의 restore 경로 포함.
- 파일 경로는 `backend/controller/` (service 아님).
- `_DEFAULT_*_PROMPT`, `_ADAPTIVE_PROMPT` 는 유지.
- `agent.process.system_prompt` (Claude Code CLI) 는 이번 PR 범위 밖.

---

## 1. 모듈 배치 (최종)

```
backend/service/persona/
├─ __init__.py              # public API re-export
├─ provider.py              # Protocol PersonaProvider, dataclass PersonaResolution
├─ dynamic_builder.py       # DynamicPersonaSystemBuilder (SystemBuilderStrategy)
├─ character_provider.py    # CharacterPersonaProvider (default impl)
└─ blocks.py                # MoodBlock / RelationshipBlock / VitalsBlock / ProgressionBlock
                             # — X1 에서는 no-op stub. X3/X4 에서 실구현.
```

테스트 (기존 `backend/tests/service/` 컨벤션 준수 — 소스 트리 미러링):

```
backend/tests/service/persona/
├─ __init__.py
├─ test_provider_protocol.py         # Protocol 동작 (fake impl)
├─ test_dynamic_builder.py           # 매 턴 resolve 가 반영되는지
├─ test_character_provider.py        # default + override 동작
├─ test_sidedoor_removed.py          # grep _system_prompt = 금지
└─ test_blocks_stub.py               # no-op block → prompt 영향 없음
```

---

## 2. PR 분해 (최종, 4 PR)

### PR-X1-1 · `feat/persona-provider-skeleton`

**목적.** Protocol / Resolution / DynamicBuilder 뼈대. 기존 경로 변경 없음 (opt-in).

**파일.**
- `backend/service/persona/__init__.py` (신규)
- `backend/service/persona/provider.py` (신규) — `PersonaProvider` Protocol, `PersonaResolution` dataclass
- `backend/service/persona/dynamic_builder.py` (신규) — `DynamicPersonaSystemBuilder` 구현
- `backend/service/persona/blocks.py` (신규) — no-op stub blocks
- `backend/tests/service/persona/__init__.py` (신규)
- `backend/tests/service/persona/test_provider_protocol.py` (신규)
- `backend/tests/service/persona/test_dynamic_builder.py` (신규)
- `backend/tests/service/persona/test_blocks_stub.py` (신규)

**테스트.** Fake PersonaProvider 가 턴마다 다른 PersonaResolution 을 반환할 때, DynamicPersonaSystemBuilder.build 가 이를 매 턴 반영하는지.

**구현 결정 (plan 보강).** `PersonaProvider.resolve` 는 **동기** 함수로 한다. 근거:
`geny_executor.stages.s03_system.interface.PromptBuilder.build` 가 동기이고
`SystemStage.execute` 는 `self._builder.build(state)` 를 await 없이 호출한다.
async 경계를 우회하려면 event-loop 해킹이 필요해지는데, persona resolve 는
기본적으로 in-memory 조회 (CreatureState 는 `SessionRuntimeRegistry` 가 pipeline.run
*전에* state.shared 로 hydrate) + 캐싱된 character markdown 만 쓰므로 sync 로 충분.

**회귀 위험.** 0 (경로 미사용).

---

### PR-X1-2 · `feat/character-persona-provider`

**목적.** `CharacterPersonaProvider` 실구현 — `_DEFAULT_VTUBER_PROMPT`/`_DEFAULT_WORKER_PROMPT`/`_ADAPTIVE_PROMPT` 및 VTuber 캐릭터 MD 파일을 소비.

**파일.**
- `backend/service/persona/character_provider.py` (신규) — `CharacterPersonaProvider`
- `backend/tests/persona/test_character_provider.py` (신규)

**인터페이스 핵심.**

```python
class CharacterPersonaProvider(PersonaProvider):
    def __init__(self, *, characters_dir: Path, default_vtuber_prompt: str,
                 default_worker_prompt: str, adaptive_prompt: str):
        self._characters_dir = characters_dir
        self._default_vtuber = default_vtuber_prompt
        self._default_worker = default_worker_prompt
        self._adaptive = adaptive_prompt
        self._static_override: dict[str, str] = {}   # session_id → persona text
        self._character_append: dict[str, str] = {}  # session_id → character markdown

    def set_static_override(self, session_id: str, text: Optional[str]) -> None: ...
    def set_character(self, session_id: str, character_name: str) -> None: ...
    def append_context(self, session_id: str, text: str) -> None: ...   # SD3 대체용
    def reset(self, session_id: str) -> None: ...

    async def resolve(self, state, *, session_meta) -> PersonaResolution: ...
```

**회귀 위험.** 0 (아직 운영 경로 아님).

---

### PR-X1-3 · `refactor/remove-system-prompt-sidedoors`

**목적.** 5 사이드도어 모두 철거 + AgentSession 이 PersonaProvider 를 사용하도록 교체.

**파일.**
- `backend/service/langgraph/agent_session.py` (수정)
  - `_build_pipeline` 에서 `ComposablePromptBuilder(...)` 를 `DynamicPersonaSystemBuilder(persona_provider, ...)` 로 교체.
  - `__init__` 에 `persona_provider: PersonaProvider` 파라미터 추가. 호출자가 주입.
- `backend/service/langgraph/agent_session_manager.py` (수정)
  - SD3 제거 — `agent._system_prompt = (agent._system_prompt or "") + vtuber_ctx` 를
    `agent._persona_provider.append_context(session_id, vtuber_ctx)` 로 대체.
  - 세션 생성 시 `CharacterPersonaProvider` 를 생성해 `AgentSession` 에 주입.
  - 생성한 `PersonaProvider` 를 manager 에도 보관 (controller 가 접근 가능하도록).
- `backend/controller/vtuber_controller.py` (수정)
  - SD1 제거 — `_inject_character_prompt` 를 `persona_provider.set_character(session_id, model_name)` 호출로 대체.
  - `agent.process.system_prompt = ...` 동기화 코드는 그대로 유지 (별도 채널).
- `backend/controller/agent_controller.py` (수정)
  - SD2 제거 — `agent._system_prompt = new_prompt` 를
    `persona_provider.set_static_override(session_id, new_prompt)` 로 대체. record update 는 유지.
  - SD4, SD5 제거 — restore 경로의 `agent._system_prompt = stored` 를 동일하게
    `set_static_override` 호출로 대체.
- `backend/service/langgraph/agent_session.py:807` — `system_prompt = self._system_prompt or ""`
  라인은 유지 (read-side; 호환을 위해 DynamicBuilder 로의 초기 값 시드로 쓰임).
  단 `_system_prompt` 는 *불변의 초기값* 이 됨. 세션 중간 갱신은 모두 PersonaProvider 경유.

**테스트.**
- `backend/tests/service/persona/test_sidedoor_removed.py` — 쓰기 패턴이 코드에 0건 (test 자체 + provider 자체 제외) 임을 assert.
- 기존 `tests/vtuber/*`, `tests/controller/test_agent_controller.py` 가 회귀 없이 통과.

**회귀 위험.** **중.** 기존 runtime 동작과의 동등성 확인 필수. 실패 시 백아웃:
- feature flag `GENY_PERSONA_V2` (default=false 로 시작, 안정화 후 true 로 기본값 변경).
  X1 내에서는 default=true 로 두되, ENV 로 끌 수 있게 유지.

---

### PR-X1-4 · `test/persona-e2e`

**목적.** e2e 시나리오 테스트. 세션 생성 → 캐릭터 교체 → prompt 재구성 → session restore → static override 유지.

**파일.**
- `backend/tests/service/persona/test_persona_lifecycle.py` (신규)

**시나리오.**
1. VTuber 세션 생성 → 첫 턴 state.system 에 `_DEFAULT_VTUBER_PROMPT` 반영.
2. `PUT /vtuber/agents/{sid}/model` 로 model=catgirl 지정 → 다음 턴 state.system 에 catgirl persona 반영.
3. `PUT /agents/{sid}/system-prompt` 로 custom prompt 설정 → 그 다음 턴에 static override 우선.
4. 세션 삭제 → 복원 → static override 가 persist 되어 다음 턴에 재반영.

**회귀 위험.** 0 (테스트만).

---

## 3. 롤아웃 · 릴리즈

- **Executor.** 수정 없음. v0.29.0 유지.
- **Geny.** 4 PR 연속 merge. 각 PR 는 독립 merge 가능하도록 구성.
- **feature flag.** `GENY_PERSONA_V2=true` default. `=false` 시 legacy 경로 (현재 PR 대상
  사이드도어) 동작. X1 완료 직후엔 양방향 유지, 2주 뒤 legacy 코드 제거 PR (별도).

---

## 4. KPI

- `grep 'agent\._system_prompt = ' backend/` 결과 0건 (tests 제외, persona/dynamic_builder 시드 제외).
- `backend/tests/service/persona/*` 전부 pass.
- 기존 VTuber / controller 회귀 테스트 전부 pass.
- Prompt cache hit rate 변화 ±5% 이내 (staging 관측, 필수는 아님).

---

## 5. 착수 순서

```
PR-X1-1 (skeleton)        → merge
PR-X1-2 (character impl)  → merge
PR-X1-3 (sidedoor 철거)   → merge
PR-X1-4 (e2e 테스트)      → merge
```

각 PR 는 merge 직후 `progress/prN_*.md` 기록.
