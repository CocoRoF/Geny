# Analysis 01 — X1 진입 전 사이드도어 실사 (2026-04-21 기준)

**상위 사이클.** `dev_docs/20260421_6/plan/03_structural_completions.md §2`, `plan/05 §1`.
**목적.** Plan 03 이 예측한 `_system_prompt` 사이드도어 3곳이 *오늘 시점의 코드* 에
어떻게 남아 있는지 재확인. 착수 전 누락을 막기 위함.

---

## 0. 결론 (한줄)

Plan 03 이 예측한 것보다 **많다.** write-site 는 3곳이 아니라 **5곳**. X1 의 PR-X1-3 는
5 사이트를 모두 철거하도록 범위를 확장해야 한다.

---

## 1. Write-site 전수조사

`grep -rn "_system_prompt" backend/ --include="*.py"` 결과를 기반으로, **`agent.*_system_prompt = ...`**
쓰기 패턴만 추출:

| # | 파일 | 라인 | 맥락 | 의도 |
|---|---|---|---|---|
| SD1 | `backend/controller/vtuber_controller.py` | 52, 54 | `_inject_character_prompt` 가 character prompt append + process 에도 동기화 | Live2D 모델 assign 시 per-model persona 주입 |
| SD2 | `backend/controller/agent_controller.py` | 304 | `PUT /system-prompt` 엔드포인트 직접 덮어씀 | 유저의 prompt 재설정 API |
| SD3 | `backend/service/langgraph/agent_session_manager.py` | 673 | 세션 생성 직후 VTuber sub-worker 컨텍스트 append | Sub-worker delegation 안내문 주입 |
| **SD4** | `backend/controller/agent_controller.py` | **482** | `restore_session` — 저장된 system_prompt 복원 | 삭제→복원 라이프사이클에서 prev prompt 이어붙임 |
| **SD5** | `backend/controller/agent_controller.py` | **520** | 같은 `restore_session` 의 cascade restore for linked session | 동일 패턴, linked agent 에 대해 |

### 1.1. Read-site (정상)

| 파일 | 라인 | 맥락 |
|---|---|---|
| `service/langgraph/agent_session.py` | 210 | `__init__` 파라미터 보관 |
| `service/langgraph/agent_session.py` | 807 | `_build_pipeline` 시 prompt text 추출 (**X1 제거 대상**: `_system_prompt` 직접 참조를 PersonaProvider 호출로 대체해야 함) |
| `service/langgraph/agent_session.py` | 1751 | 직렬화 (get_session_info 등) |
| `service/langgraph/agent_session_manager.py` | 191, 262, 420 | `_build_system_prompt` 메서드 (초기 prompt 조립, 정상 경로) |
| `controller/agent_controller.py` | 456, 483, 500, 519, 521 | restore 경로 (SD4/SD5 의 read-side) |

### 1.2. 분류

- **SD1, SD2, SD3** — plan/03 예측과 일치. "런타임 중 prompt 교체" 요구 → PersonaProvider
  로 흡수.
- **SD4, SD5** — 새로 발견. "세션 삭제 → 복원 시 이전 prompt 재주입" 요구. 이것도 PersonaProvider
  로 흡수 가능 (복원 시점에 `persona_provider.set_static_override(stored)` 호출).

---

## 2. 현재 prompt 조립 경로

`agent_session.py:_build_pipeline` 807-816:

```python
system_prompt = self._system_prompt or ""
if is_vtuber:
    persona_text = system_prompt or _DEFAULT_VTUBER_PROMPT
else:
    persona_text = (
        (system_prompt or _DEFAULT_WORKER_PROMPT)
        + "\n\n" + _ADAPTIVE_PROMPT
    )
```

그리고 927-934:

```python
attach_kwargs = {
    "system_builder": ComposablePromptBuilder(blocks=[
        PersonaBlock(persona_text),
        DateTimeBlock(),
        MemoryContextBlock(),
    ]),
    ...
}
```

### 2.1. `_build_pipeline` 는 세션 시작 시 **1회만** 호출

현재 attach_runtime 은 *한 번* 호출되고 `system_builder` 는 고정된 blocks 로 생성. 이후
`_system_prompt` 변경이 반영되지 않음 → 이것이 사이드도어들이 생긴 이유.

**X1 의 핵심 아이디어.** `ComposablePromptBuilder` 를 *정적 blocks 를 품은 것* 에서
**`DynamicPersonaSystemBuilder` (매 턴 resolve)** 로 교체. 그러면 `_system_prompt` 재할당
없이도 persona 갱신 가능.

---

## 3. ComposablePromptBuilder / PromptBlock 임포트 경로

`service/langgraph/agent_session.py` 상단:

```python
from geny_executor.stages.s03_system.artifact.default.builders import (
    ComposablePromptBuilder,
    DateTimeBlock,
    MemoryContextBlock,
    PersonaBlock,
)
```

→ 이 클래스들은 **executor 소유**. Geny 는 소비자. X1 은 executor 를 건드리지 않고,
Geny 내부에 `DynamicPersonaSystemBuilder` 를 만들어 `SystemBuilderStrategy` 를 구현,
`ComposablePromptBuilder` 는 *내부에서 블록 합성 수단으로만* 사용.

---

## 4. Plan 03 vs 실측 Diff

| 항목 | Plan 03 예측 | 실측 | 조치 |
|---|---|---|---|
| 사이드도어 수 | 3 | 5 | 범위 확장 (PR-X1-3 에 SD4/SD5 추가) |
| vtuber_controller 경로 | `backend/service/vtuber/vtuber_controller.py` | `backend/controller/vtuber_controller.py` | 파일 경로 수정 |
| ComposablePromptBuilder 소유 | Geny? executor? 불명 → executor 확인 | executor 에 있음 | 재사용 가능, 신규 생성 불필요 |
| PersonaBlock 로드 | 신규? 기존? | 기존 (executor) | 재사용 |
| restore 경로의 존재 | 언급 없음 | SD4/SD5 존재 | PersonaProvider 에 `set_static_override` 추가 |
| agent_session_manager._build_system_prompt | 언급 없음 | 존재 (초기 조립) | 유지 — PersonaProvider 가 이것을 *정적 초기값* 으로 받음 |

---

## 5. Side-door 외 이슈

- **`agent.process.system_prompt = ...`** (vtuber_controller.py:54) — ClaudeCode 프로세스의
  CLI 인자를 동기화. `_system_prompt` 와 별도의 채널. X1 범위에서 같이 정리:
  `persona_provider.set_static_override` 호출 시 (옵션으로) process 동기화도 트리거하는 훅 제공.
  단, process 는 Claude Code CLI 서브프로세스에서 `--append-system-prompt` 인자로만 쓰이고,
  이것은 Claude Code *자체의* system prompt 이며 LangGraph pipeline 의 s03 system 과 직접
  관련 없음. X1 에서는 건드리지 않고 그대로 두는 것이 안전 (별도 이슈).

- **`_DEFAULT_VTUBER_PROMPT`, `_DEFAULT_WORKER_PROMPT`, `_ADAPTIVE_PROMPT`** — 파일 상단
  상수. X1 에서 유지. PersonaProvider 가 이들을 "기본 persona_text" 로 참조.

---

## 6. 재검증 결론

- Plan 03 의 구조 (PersonaProvider + DynamicPersonaSystemBuilder) 는 **그대로 유효**.
- PR 범위만 확장: SD4, SD5 를 포함해 총 5 사이트 철거.
- 파일 경로 수정: `backend/controller/` (service 아님).
- X1 의 목표는 "매 턴 persona resolve 가 가능한 파이프라인" + "모든 write-site 철거".
- 릴리즈 / 의존성 / 스키마 변경 없음.

Plan 01 (`dev_docs/20260421_7/plan/01_x1_execution_plan.md`) 에서 PR 단위 실행 계획 확정.
