# PR-X3-6 · `feat/game-tools-basic` — 진행 기록

**Date.** 2026-04-21
**Status.** Implemented, 559/559 사이클 관련 pass (기존 500 + 신규 59).
`feed` / `play` / `gift` / `talk` 4 개 게임 도구 + `MutationBuffer` 를
도구에 노출하는 ContextVar 브리지 + `_pipeline_events_scoped` 헬퍼로
AgentSession 의 run_stream 반복을 감싸 자동 bind/reset.

## 범위

plan/02 §5 "게임 도구" 의 MVP 4 도구 구현 + 로더(ToolLoader) 등록.
stage-level pipeline 의 `state.shared[MUTATION_BUFFER_KEY]` 에 안전하게
mutation 을 push 하는 경로 완성. 본 PR 이후 pipeline 이 선택하는 어떤
stage 든 (executor 가 들고 오는 LLM/tool stage 포함) 자동으로 버퍼를
관찰할 수 있다.

쉐도우 모드 기본. `GENY_GAME_FEATURES` 가 off 면 provider 가 없으므로
`_pipeline_events_scoped` 는 bind 을 건너뛰고 도구들은 narrated-only 응답을
반환 (vitals 변화 없음).

## 핵심 설계 — ContextVar 브리지

**문제.** 실행기(geny-executor) 의 `BaseTool.run(**kwargs)` 는
`ToolContext` 에 `state` 필드가 없고, Geny 입장에서 executor 인터페이스를
바꾸는 건 별도 PR. 도구가 턴당 `MutationBuffer` 를 참조할 다른 경로가
필요했다.

**해법.** 모듈 수준 `contextvars.ContextVar` 를 제공하고, AgentSession 이
`pipeline.run_stream` 반복을 감싸는 동안 bind 을 건다. 도구는
`current_mutation_buffer()` 한 줄로 접근. try/finally 로 reset 이
정상 완료 / 예외 / early abandonment (aclose) 모두에서 보장된다.

## 적용된 변경

### 1. `backend/service/state/tool_context.py` (신규)

```python
_current_mutation_buffer: ContextVar[Optional[MutationBuffer]] = ContextVar(
    "geny_current_mutation_buffer", default=None,
)

def current_mutation_buffer() -> Optional[MutationBuffer]: ...
def bind_mutation_buffer(buf: MutationBuffer) -> Token: ...
def reset_mutation_buffer(token: Optional[Token]) -> None: ...
```

`reset_mutation_buffer(None)` 은 no-op — 호출측이 bind 을 하지 않은
경우에도 finally 에서 무조건 reset 을 호출할 수 있게 해서 분기 제거.

### 2. `backend/service/state/__init__.py` (수정)

`bind_mutation_buffer` / `current_mutation_buffer` /
`reset_mutation_buffer` re-export + `__all__` 등재.

### 3. `backend/service/game/tools/rules.py` (신규)

모든 도구 공통의 숫자 델타를 한 곳에 고정 — 네 도구가 서로 다른 파일에서
숫자를 베끼는 상황을 차단. 각 규칙은 `@dataclass(frozen=True)` 로
immutable, 모듈 레벨 dict (`FEED_RULES`, `PLAY_RULES`, `GIFT_RULES`) 가
single source of truth.

**핵심 sign 규칙 (vitals 반대 방향 주의):**

- `hunger` 는 0=sated, 100=starving → `feed` 는 **음수** delta.
- `energy` 는 0=exhausted, 100=peak → `play` 는 **음수** (에너지 소모).
- `stress` 는 0=calm, 100=extreme → `play.cuddle/fetch/game` 은 음수
  (스트레스 해소), `play.tease` 만 양수.
- `bond.*`, `mood.*` 는 일반적 방향 (양수 = 긍정).

`feed_rule_for` / `play_rule_for` / `gift_rule_for` 은 unknown kind 에
대해 안전한 기본값 (`snack` / `cuddle` / `flower`) 으로 폴백 —
LLM 이 스키마 밖 값을 넘겨도 crash 대신 narrated 응답.

### 4. 도구 구현 (신규)

각 도구는 동일한 shape:

```python
class FeedTool(BaseTool):
    name = "feed"
    parameters = {"type": "object", "properties": {...}, "required": []}

    def run(self, kind: str = "snack", **_: object) -> str:
        rule = feed_rule_for(kind)
        buf = current_mutation_buffer()
        if buf is None:
            return f"FEED_NARRATED_ONLY kind={kind} ... (state unavailable)"
        source = "tool:feed"
        if rule.hunger_delta != 0.0:
            buf.append(op="add", path="vitals.hunger", value=..., source=source)
        if rule.affection_delta != 0.0:
            buf.append(op="add", path="bond.affection", value=..., source=source)
        buf.append(op="append", path="recent_events", value=f"fed:{kind}", source=source)
        return f"FEED_OK kind={kind} pleasure={rule.pleasure}"
```

**도구별 mutation 경로:**

- `feed` → `vitals.hunger` (−), `bond.affection` (favorite 만 +),
  `recent_events: fed:{kind}`.
- `play` → `vitals.stress`, `vitals.energy` (−), `bond.affection`,
  `recent_events: played:{kind}`. `tease` 는 예외로 stress + / affection −.
- `gift` → `bond.affection`, `bond.trust`, `mood.joy`,
  `recent_events: gift:{kind}`. `letter` 가 trust 상승 최대.
- `talk` → `bond.familiarity` (`FAMILIARITY_DELTA=0.3` 고정),
  `recent_events: talk:{kind}[:{topic}]`. 알 수 없는 kind 는 `check_in` 로
  coerce.

모든 도구의 `MutationOp` 는 `"add"` (numeric delta) 또는 `"append"`
(recent_events 리스트).

**Narrated-only 모드.** buffer 가 없을 때 (classic mode + provider 미설치)
도구는 상태를 건드리지 않고 `"*_NARRATED_ONLY ..."` 응답만. 이것이
`GENY_GAME_FEATURES` off 에서 도구가 등록돼도 크리쳐 상태에 영향 없이
동작하는 안전장치.

### 5. `backend/service/game/tools/__init__.py` (신규)

4 개 도구 클래스 + 규칙 dataclass/dict 재수출.

### 6. `backend/tools/built_in/game_tools.py` (신규)

`ToolLoader` 가 `backend/tools/built_in/*_tools.py` 의 `module.TOOLS`
를 스캔해 등록. 본 모듈은 그 단일 책임만 (import → 인스턴스 4 개를
리스트로 노출):

```python
from service.game.tools import FeedTool, GiftTool, PlayTool, TalkTool
TOOLS = [FeedTool(), PlayTool(), GiftTool(), TalkTool()]
```

### 7. `backend/service/langgraph/agent_session.py` (수정)

**새 헬퍼 `_pipeline_events_scoped`:**

```python
async def _pipeline_events_scoped(
    self, input_text, state, hydrated,
) -> AsyncIterator[Any]:
    from service.state import (
        MUTATION_BUFFER_KEY, bind_mutation_buffer, reset_mutation_buffer,
    )
    token = None
    if hydrated:
        buf = state.shared.get(MUTATION_BUFFER_KEY)
        if buf is not None:
            token = bind_mutation_buffer(buf)
    try:
        async for event in self._pipeline.run_stream(input_text, state):
            yield event
    finally:
        reset_mutation_buffer(token)
```

`_invoke_pipeline` / `_astream_pipeline` 모두 `self._pipeline.run_stream`
직접 호출을 이 헬퍼로 교체. 양쪽에 동일한 bind/reset 의미가 적용되도록.

**import path 주의.** Production 은 `service.state` 경로로 진입하므로
헬퍼도 `from service.state import ...` — `backend.service.state` 로
적으면 Python 이 별도 모듈 객체로 취급해 ContextVar 인스턴스가 달라진다
(테스트에서 붙잡음, 아래 참조).

## 테스트 (신규 59)

### `backend/tests/service/state/test_tool_context.py` — 6

ContextVar 자체의 계약.

1. `test_default_is_none_without_any_bind` — import-time default.
2. `test_bind_returns_non_none_token_and_current_returns_buffer`.
3. `test_reset_returns_to_none` — 토큰 복귀.
4. `test_reset_tolerates_none_token` — no-op 시 no crash.
5. `test_bindings_are_task_scoped` — asyncio task 간 독립 (contextvars
   의 핵심 약속).
6. `test_nested_binds_restore_outer_on_reset` — 스택 복구.

### `backend/tests/service/game/tools/test_rules.py` — 11

규칙 테이블의 sign/크기 invariants. 예:

- 모든 `FeedRule.hunger_delta <= 0`.
- `play.cuddle/fetch/game.stress_delta < 0`, `play.tease.stress_delta > 0`.
- `gift.letter.trust_delta` 가 전체 gift 중 최댓값.

### `backend/tests/service/game/tools/_helpers.py` (신규)

```python
@contextmanager
def bound_buffer():
    buf = MutationBuffer()
    tok = bind_mutation_buffer(buf)
    try:
        yield buf
    finally:
        reset_mutation_buffer(tok)
```

**Fixture 가 아니라 context manager 인 이유.** pytest yielding fixture
는 fixture 바디와 테스트 바디를 별개 contextvars 컨텍스트에서 실행 —
fixture 안에서 `set` 한 ContextVar 는 테스트 바디에서 보이지 않는다.
`contextlib.contextmanager` 를 테스트 바디 **안에서** `with` 로 쓰면
동일 컨텍스트에서 bind/reset 되므로 안전.

### `test_feed_tool.py`, `test_play_tool.py`, `test_gift_tool.py`,
###  `test_talk_tool.py` — 각 6 ~ 7개 (총 29)

각 도구의 happy path / default kind / unknown kind / 소스 태그 / 타
버켓 불변성 / narrated-only 폴백 커버.

### `backend/tests/service/game/tools/test_game_tools_builtin.py` — 4

ToolLoader 진입점:

- `module.TOOLS` 가 list 이고 길이 4.
- name 집합 = `{feed, play, gift, talk}`.
- 클래스명 (not isinstance) 검사 — 모듈 중복 때문에 `isinstance` 는
  항상 False.
- 각 도구의 `.parameters` 가 JSON-schema object.

### `backend/tests/service/langgraph/test_agent_session_tool_context.py` — 6

AgentSession × ContextVar 의 end-to-end 계약.

1. `test_classic_mode_contextvar_stays_none` — provider 없으면 bind
   안 일어남.
2. `test_buffer_visible_during_pipeline_loop` — `current_mutation_buffer()`
   이 return 하는 객체 === `state.shared[MUTATION_BUFFER_KEY]` (same id).
3. `test_contextvar_resets_after_normal_completion` — 후속 작업에
   누수 없음.
4. `test_contextvar_resets_on_pipeline_exception` — stage exception 후
   reset 보장 (finally 의 핵심).
5. `test_astream_binds_and_resets_symmetrically` — stream 경로도 invoke
   와 동일.
6. `test_hydrate_failure_leaves_contextvar_none` — hydrate 가 raise 하면
   state.shared 에 buffer 설치 안 됨 → bind skip → 도구는 narrated-only.

## 테스트 결과

- `tests/service/state/` **151/151** (PR-X3-5 의 145 + tool_context 6).
- `tests/service/game/` **53/53** (신규, rules + 4 tools + loader).
- `tests/service/langgraph/` **127/127** (PR-X3-5 의 121 + tool_context 6).
- 사이클 관련 전체 **559/559 pass** (500 기존 + 59 신규).

(사이클 무관 실패 4 건: `environment/test_templates.py` 3,
`utils/test_text_sanitizer.py` 1 — 모두 `fastapi` / `numpy` missing
환경 문제, PR-X3-6 와 무관.)

## 디버깅 노트 — "FEED_NARRATED_ONLY" 16건 전체 탈락

초기 실행에서 도구 테스트가 전부 narrated-only 로 떨어졌다. 원인:
Python 이 `service.state` 와 `backend.service.state` 를 **서로 다른 모듈
객체** 로 로드 → 두 번째 객체의 ContextVar 인스턴스가 첫 번째와 완전히
다른 변수. 테스트 helper 가 `from backend.service.state import ...` 로
bind 하고 production 도구가 `from service.state import ...` 로 read 하면
서로 절대 안 맞음. 

수정: test helper 를 `from service.state import ...` 로 통일. 이후
AgentSession 쪽 `_pipeline_events_scoped` 도 같은 이유로 `service.state`
경로로 정렬 (초기 구현은 `backend.service.state` 였음, 통합 테스트에서
보정).

## 설계 결정

- **ContextVar vs ToolContext 확장.** `ToolContext` 에 `state` 필드를
  추가하면 executor 의 공개 인터페이스를 흔들게 된다. ContextVar 는
  Python 표준이고 asyncio task-scoped (동시 세션 상호 격리) 이며 도구
  서명을 건드리지 않음 → 옵트인. 대신 "현재 턴의 버퍼" 라는 전역적
  가정이 생기므로 bind/reset 이 반드시 try/finally 로 감싸져야 한다.
- **단일 헬퍼 (`_pipeline_events_scoped`) 를 invoke & stream 양쪽에서.**
  중복을 줄이고, 어느 한쪽이 확장돼도 bind 의미는 자동으로 공유.
- **`reset_mutation_buffer(None)` 을 허용.** 호출측이 bind 을 건너뛴
  경우에도 finally 에서 호출할 수 있어 분기 감소 → 실수 예방.
- **rules.py 를 별도 파일로.** 규칙 튜닝은 런타임 동작 튜닝과 자주
  같이 생긴다. LLM 튜닝 전 먼저 숫자 조정이 들어오는 곳 — 한 파일에
  몰아서 diff review 용이하게.
- **Unknown kind → 안전 폴백.** LLM 이 넘긴 enum 밖의 값은 crash 대신
  narrated 응답 또는 기본 규칙 적용. 도구의 로그에만 kind 원본이 남아
  관찰 가능.

## 의도적 비움

- **Tool 선택 로직 (어느 도구를 언제 쓸지).** 이건 prompt / stage /
  emitter 책임. 본 PR 은 도구를 "쓸 수 있게" 까지.
- **실제 stage 가 tool result 를 consume 하는 경로.** PR-X3-7 의
  affect-tag-emitter / PR-X3-8 의 mood-rel-vitals-blocks 에서 연결.
- **도구 결과를 user-facing 텍스트에 박는 formatter.** 현재는
  `"FEED_OK kind=snack pleasure=low"` 와 같은 디버깅 친화 포맷만.
  narration polish 는 emitter 쪽에서 한다.
- **도구별 cooldown / rate limit.** 초기 설계에서는 의도적으로 빠짐 —
  행동 경제를 도입하면 state 에 cooldown 카운터가 들어가야 하고,
  그 설계는 plan 상 X4 (Progression + Manifest) 의 범주.
- **persist-on-tool-error.** stage 에러 시 persist 는 이미 PR-X3-5 에서
  보장. 본 PR 에서 새 path 추가 없음.

## 다음 PR

PR-X3-7 `feat/affect-tag-emitter` — stage 의 LLM 출력에서 `<feel_*>`
태그를 추출해 mood delta 로 환산 + 동일 ContextVar 를 통해 동일 버퍼에
push. 도구와 emitter 가 같은 turn 에서 같은 버퍼를 보는 것이 자연스럽게
됨.
