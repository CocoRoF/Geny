# PR3 — `session_name` ↔ `character_display_name` 분리

**Date.** 2026-04-22
**Status.** 계획 (PR2 와 같은 마일스톤 권장)
**Touches.**
[`backend/service/prompt/sections.py`](../../../backend/service/prompt/sections.py),
[`backend/service/claude_manager/models.py`](../../../backend/service/claude_manager/models.py),
[`backend/service/langgraph/agent_session_manager.py`](../../../backend/service/langgraph/agent_session_manager.py),
[`backend/controller/agent_controller.py`](../../../backend/controller/agent_controller.py),
(옵션) frontend 캐릭터 생성 폼.

## 1. 문제

[`SectionLibrary.identity`](../../../backend/service/prompt/sections.py)
는 `session_name` 이 주어지면 무조건 다음 한 줄을 박는다:

```
Your name is "{session_name}".
```

`session_name` 은 사용자가 캐릭터 생성 폼에 친 임의 문자열이다 (`"ertsdfg"`,
`"my_test"`, `"vtuber_2026_04_21_v3"` 등). 이게 1인칭 이름으로 시스템 프롬프트
에 박히면 LLM 은 *반드시* 그걸 자기 이름으로 흡수한다. 사용자가 보고한:

> "저는 ertsdfg라고 해요."

는 정확히 이 한 줄의 결과다.

## 2. 설계

원칙 E ([index §"설계 철학"](../index.md#설계-철학-이번-사이클의-헌법)) —
**이름은 데이터로 관리한다**.

### 두 필드의 역할

| 필드 | 출처 | 역할 | 시스템 프롬프트 노출 |
|---|---|---|---|
| `session_name` | 사용자가 폼에 친 임의 문자열 | 운영용 식별자 (UI 라벨, 로그 grep) | **노출하지 않음** (또는 "internal handle, not your name" 으로 약화) |
| `character_display_name` | 사용자가 *캐릭터 이름* 으로 명시한 값 (없을 수 있음) | 작품적 이름 — 이 캐릭터가 어떤 이름으로 답해야 하는가 | 있으면 명시; 없으면 라인 자체 생략 |

### identity 섹션 변경

```python
@staticmethod
def identity(
    agent_name: str = "Great Agent",
    role: str = "worker",
    agent_id: Optional[str] = None,
    session_name: Optional[str] = None,
    character_display_name: Optional[str] = None,
) -> PromptSection:
    """Agent identity section.

    Naming policy (원칙 E):
    - `character_display_name` is the authoritative in-character name.
      When set, it is presented as "Your character name is X."
    - `session_name` is an operational handle (e.g. user-typed slug).
      When `character_display_name` is unset, we deliberately do NOT
      expose the session name as a name. We expose it as "Session
      handle: X" with a note that it is not the persona's name.
    - When neither is set, no name lines are emitted; the persona is
      anonymous until the user gives it a name (handled by the
      first-encounter overlay in PR2).
    """
    identity_line = SectionLibrary._ROLE_IDENTITY.get(
        role, f"You are a Geny agent (role: {role})."
    )
    parts = [identity_line]

    if character_display_name:
        parts.append(f'Your character name is "{character_display_name}".')
    elif session_name:
        # Expose only as a handle, with an explicit disclaimer so the
        # model does not adopt it as its own name.
        parts.append(
            f'Session handle: "{session_name}" '
            "(internal identifier; this is NOT your character name)."
        )

    if agent_id:
        parts.append(f"Agent ID: {agent_id}")

    return PromptSection(
        name="identity",
        content=" ".join(parts),
        priority=10,
        modes={PromptMode.FULL, PromptMode.MINIMAL},
    )
```

### `CreateSessionRequest` 신규 필드

[`service/claude_manager/models.py`](../../../backend/service/claude_manager/models.py):

```python
class CreateSessionRequest(BaseModel):
    ...
    character_display_name: Optional[str] = Field(
        default=None,
        description=(
            "In-character display name for VTuber sessions. When unset, "
            "the persona is anonymous and will (per first-encounter "
            "guidance) ask the user how to be addressed. Ignored for "
            "non-VTuber roles."
        ),
    )
```

### `_build_system_prompt` 호출부

[`agent_session_manager._build_system_prompt`](../../../backend/service/langgraph/agent_session_manager.py)
에서 `build_agent_prompt(...)` 호출 시 `character_display_name=request.character_display_name`
전달. 다른 인자는 변경 없음.

### 컨트롤러 / 폼

[`agent_controller.py`](../../../backend/controller/agent_controller.py) 의
세션 생성 엔드포인트가 요청 본문에서 `character_display_name` 을 그대로
포워딩. 별도 검증은 불필요 (Pydantic 이 처리).

frontend 폼은 §5 의 사용자 의사결정에 따라 별도 PR 또는 본 PR 에 포함.

## 3. 변경 항목 체크리스트

- [ ] `service/prompt/sections.py` — `SectionLibrary.identity` 시그니처
  확장 + 본문 §2 코드.
- [ ] `service/prompt/sections.py::build_agent_prompt` 시그니처에
  `character_display_name: Optional[str] = None` 추가, identity 호출 시 전달.
- [ ] `service/claude_manager/models.py::CreateSessionRequest` 필드 추가.
- [ ] `service/langgraph/agent_session_manager.py::_build_system_prompt`
  - 인자에 `character_display_name` 받기 (또는 `request` 에서 직접 추출).
  - `build_agent_prompt(..., character_display_name=...)` 로 포워딩.
- [ ] `controller/agent_controller.py` — 세션 생성 핸들러가 요청 본문의
  `character_display_name` 을 `CreateSessionRequest` 에 전달하는지 확인 (
  Pydantic 자동 매핑이라면 변경 없음).
- [ ] (옵션) frontend 캐릭터 생성 폼 — "표시 이름" 텍스트 필드 추가, 비워두
  면 backend 가 None 으로 받음.

## 4. 회귀 / 단위 테스트

- [ ] `tests/service/prompt/test_sections.py` (또는 신규)
  - `test_identity_omits_name_when_both_fields_unset` — session_name=None,
    character_display_name=None → identity 출력에 "name" 단어 미포함.
  - `test_identity_uses_character_display_name_when_set` —
    character_display_name="루나" → `'Your character name is "루나".'` 포함.
  - `test_identity_session_handle_includes_disclaimer` —
    session_name="ertsdfg", character_display_name=None → `Session handle:
    "ertsdfg"` 포함 + `NOT your character name` 디스클레이머 포함.
  - `test_identity_prefers_display_name_over_handle` — 둘 다 설정 시
    display_name 만 출력, handle 라인 미포함.
- [ ] `tests/service/langgraph/test_agent_session_manager.py`
  - `test_build_system_prompt_forwards_character_display_name` — 요청에
    필드 설정 시 시스템 프롬프트에 `Your character name is` 라인 등장.
- [ ] 통합: PR2 의 first-encounter overlay + PR3 의 익명 인격 조합이
  사이클 매트릭스 R2 (`session_name="ertsdfg"` 가 응답에 안 나옴) 의 *구조적*
  차단을 만든다.

## 5. 사용자 의사결정 항목

- frontend 폼 변경을 본 PR 에 포함할지, backend-only 로 가고 frontend 는
  후속 PR 로 분리할지.
- 이름이 없을 때 LLM 의 디폴트 행동: (a) "이름이 없어요" 명시 / (b) 회피 /
  (c) 호칭을 묻고 기다림 — first-encounter overlay (PR2) 의 "Simply say
  you do not have a settled name yet" 문구가 (a) 와 (c) 의 중간을 의도. 더
  강한 선호가 있으면 overlay 문구를 PR2 작업 전에 조정.

## 6. 위험 / 완화

| 위험 | 완화 |
|---|---|
| 기존 운영 중 세션이 `character_display_name` 없이 만들어진 상태로 재시작됨 | None-safe path 가 디폴트. 기존 세션은 "익명 인격" 으로 자연 fallback. |
| `session_name` 에 의존하는 다른 코드 경로 (UI 라벨, 로그) 영향 | 본 PR 은 *프롬프트 노출* 만 변경. session_name 자체는 그대로. |
| LLM 이 `Session handle: "ertsdfg"` 라인의 디스클레이머를 무시하고 그래도 ertsdfg 를 자기 이름으로 사용 | 모델 안정성 의존. 회귀 테스트 R2 가 LLM 출력을 직접 검증 — fail 시 다음 옵션 (handle 라인 자체 미노출) 으로 한 번 더 약화. |
