# PR4 — Worker 페르소나 제거 + 이중 `vtuber.md` 주입 정리

**Date.** 2026-04-22
**Status.** 계획 (PR1~PR3 머지 후)
**Touches.**
[`backend/service/persona/character_provider.py`](../../../backend/service/persona/character_provider.py),
[`backend/service/persona/dynamic_builder.py`](../../../backend/service/persona/dynamic_builder.py),
[`backend/service/prompt/sections.py`](../../../backend/service/prompt/sections.py)
(`build_agent_prompt` 분기),
[`backend/service/langgraph/agent_session_manager.py`](../../../backend/service/langgraph/agent_session_manager.py)
(중복 안내 블록 제거),
[`backend/main.py`](../../../backend/main.py) 또는 부트스트랩 (PersonaProvider
조립부).

## 1. 두 가지 통증을 한 PR 에서 정리하는 이유

원칙 B (**VTuber 는 페르소나, Worker 는 도구**) 와 원칙 C (**두 합성 경로의
책임 분리**) 는 같은 코드 영역을 만진다. 분리해서 머지하면 중간 상태에서
시스템 프롬프트가 *더* 깨진다 (vtuber.md 가 0회 또는 3회 등장하는 회귀).
한 PR 로 묶어 invariant 를 동시에 회복한다.

## 2. 통증 A — `vtuber.md` 가 두 번 들어간다

### 현 상태

세션 생성 시점:
1. [`agent_session_manager._build_system_prompt`](../../../backend/service/langgraph/agent_session_manager.py)
   가 `build_agent_prompt(role="vtuber", ...)` 호출.
2. `build_agent_prompt` 가 `PromptTemplateLoader().load_role_template("vtuber")`
   로 `prompts/vtuber.md` 본문을 읽어 `role_protocol` 섹션에 박음.
3. 결과 = AgentSession 의 `_system_prompt` 에 박제.

매 턴:
1. `DynamicPersonaSystemBuilder.build(state)` →
   `CharacterPersonaProvider.resolve()`.
2. provider 의 `default_vtuber_prompt` 가 `prompts/vtuber.md` 를 또 읽음.
3. `PersonaBlock(persona_text)` 로 다시 박힘.

→ VTuber 세션의 시스템 프롬프트에 `vtuber.md` 본문이 **2회** 등장. 토큰
낭비 + 두 곳을 따로 갱신하다 발생하는 드리프트 위험.

### 변경

`build_agent_prompt` 의 `role == "vtuber"` 분기에서 **role_protocol 로딩을
스킵**. Worker 와 다른 역할은 그대로 (worker.md 는 A 경로 전담, B 경로 (
PersonaProvider) 가 worker 를 안 거치게 됨 → §3 통증 B 에서 보장).

```python
# build_agent_prompt 내부
if role == "worker":
    pass  # 기존: worker.md 를 통한 role_protocol 주입
elif role == "vtuber":
    # vtuber.md 는 PersonaProvider (B 경로) 가 단독 책임진다 (cycle 20260422_6 PR4).
    # A 경로에서 vtuber.md 를 들여놓으면 시스템 프롬프트에 본문이 두 번 등장.
    pass
else:
    builder.add_section(SectionLibrary.role_protocol(role))
    loader = PromptTemplateLoader()
    md_template = loader.load_role_template(role)
    if md_template:
        builder.override_section("role_protocol", md_template)
```

## 3. 통증 B — Worker 가 페르소나·라이브 상태를 받고 있다

### 현 상태

[`CharacterPersonaProvider.resolve`](../../../backend/service/persona/character_provider.py):

```python
def resolve(self, state, *, session_meta):
    is_vtuber = bool(session_meta.get("is_vtuber", False))
    base = self._static_override.get(session_id) or (
        self._default_vtuber if is_vtuber else self._default_worker
    )
    parts = [base]
    if not is_vtuber:
        parts.append(self._adaptive)
    ...
    blocks: list[PromptBlock] = [PersonaBlock(persona_text)]
    blocks.extend(self._live_blocks)   # ← Worker 도 받음!
    ...
```

→ Worker 세션도:
- `default_worker_prompt` (= `worker.md` 본문) 를 받음 (A 경로의 `worker.md`
  와 *중복* — vtuber 만큼은 아니지만 worker 도 이중 주입).
- `adaptive` 본문을 받음.
- `MoodBlock` / `VitalsBlock` / `RelationshipBlock` / `ProgressionBlock` /
  `AcclimationBlock` (PR2) 까지 다 받음 — Worker 는 사용자와 대화하지
  않으므로 이 블록들은 **단 한 토큰의 가치도 없다**.

### 변경 — Worker 는 PersonaProvider 를 거치지 않는다

원칙 B 에 따라 Worker 의 시스템 프롬프트는 다음으로 끝낸다:

```
identity (Geny Worker) + geny_platform + workspace + datetime
+ bootstrap_context + worker.md (A 경로) + (있다면) Sub-Worker / VTuber
페어 안내
```

라이브 상태 블록·캐릭터·페르소나 일체 *없음*.

#### 구현 옵션 평가

| 옵션 | 장점 | 단점 |
|---|---|---|
| **(α) PersonaProvider 가 `is_vtuber=False` 일 때 빈 PersonaResolution 반환** | 변경 최소 (provider 1개 함수) | DynamicPersonaSystemBuilder 가 여전히 호출됨 — 매 턴 빈 빌드 비용 |
| **(β) DynamicPersonaSystemBuilder 자체를 VTuber 세션에만 attach** | 토큰·CPU 모두 0 | 파이프라인 빌드 분기 필요 (manifest 단계) |
| **(γ) NullPersonaProvider 를 새로 만들고 Worker 세션에 주입** | 의도 명시적 | 신규 클래스 추가, 부트스트랩 변경 |

**채택: (α) + (β) 의 하이브리드**.
- (α): `CharacterPersonaProvider.resolve` 가 `is_vtuber=False` 일 때
  `PersonaResolution(persona_blocks=[], cache_key="W_NO_PERSONA")` 반환.
  → Worker 세션이 어떤 경로로든 provider 에 닿아도 안전.
- (β): 가능하면 manifest 의 `system` 단계에서 VTuber 세션만
  `DynamicPersonaSystemBuilder` 를 부착하고, Worker 세션은
  `ComposablePromptBuilder` (정적) 으로 바로 직행. 이 부분은 manifest 단계
  코드 (`stage_manifest.py`, `default_manifest.py`) 의 builder selection 위치
  를 확인 후 결정 — manifest 분기가 명확하지 않으면 (α) 만으로도 충분.

#### 코드 스케치 (α)

```python
def resolve(self, state, *, session_meta):
    session_id = str(session_meta.get("session_id", ""))
    is_vtuber = bool(session_meta.get("is_vtuber", False))

    if not is_vtuber:
        # 원칙 B (cycle 20260422_6): Worker 는 페르소나 / 캐릭터 / 라이브
        # 상태를 받지 않는다. worker.md 는 A 경로 (build_agent_prompt) 가
        # 책임진다. 여기서는 빈 블록만 반환한다.
        return PersonaResolution(
            persona_blocks=[],
            cache_key="W_NO_PERSONA",
        )

    # ── 이하 기존 VTuber 분기 ──
    base = self._static_override.get(session_id) or self._default_vtuber
    ...
```

`default_worker_prompt` / `adaptive` 인자는 **호환을 위해 시그니처에 남기되,
사용하지 않는다** (제거하면 외부 부트스트랩 호출이 깨짐). 다음 사이클에서
인자 자체를 제거하는 cleanup 가능.

## 4. 통증 C — 위임 안내 블록의 단일 출처화

### 현 상태

`agent_session_manager` 에 `## Sub-Worker Agent` / `## Paired VTuber Agent`
블록을 **두 군데** 에서 박는다:

1. [`_build_system_prompt`](../../../backend/service/langgraph/agent_session_manager.py)
   L406 부근 — 재구성(warm restart) 경로에서 직접 prompt 문자열에 append.
2. `create_agent_session` L847 부근 — 새 VTuber 생성 후 `prompt + vtuber_ctx`
   로 한 번 더 + `self._persona_provider.append_context(session_id, vtuber_ctx)`
   로 또 한 번.

→ 새 VTuber 세션은 위임 안내가 *최대 2회* 등장 가능.

### 변경

**단일 출처: `PersonaProvider.append_context` 만 사용.**

- `_build_system_prompt` L406 의 하드코딩 텍스트 + 직접 append 삭제. 대신
  세션 reconstruct 시 `persona_provider.append_context(session_id, vtuber_ctx)`
  호출 (idempotent — 이미 append 되어 있으면 no-op, 기존 구현이 이미 그렇게
  되어 있음).
- `create_agent_session` L847 의 `prompt + vtuber_ctx` 줄 삭제. `append_context`
  호출은 그대로 유지.
- `## Paired VTuber Agent` 블록도 동일 정책: A 경로의 직접 append 제거,
  PersonaProvider 가 단독 책임. (Sub-Worker 는 §3 의 원칙 B 에 따라 PersonaProvider
  를 사용하지 않음 → 별도 처리 필요. **결정**: Sub-Worker 의 경우 worker.md
  하단에 `## Paired VTuber Agent` 섹션을 정적으로 두고, A 경로의
  `extra_system_prompt` 로 한 번만 주입한다. 즉 Sub-Worker 안내 블록은 A
  경로 전담, VTuber 안내 블록은 B 경로 전담.)

### 결과

| 세션 종류 | `vtuber.md` | `worker.md` | `## Sub-Worker Agent` | `## Paired VTuber Agent` |
|---|---|---|---|---|
| VTuber | 1회 (B) | 0회 | 1회 (B, append_context) | 0회 |
| Sub-Worker | 0회 | 1회 (A) | 0회 | 1회 (A) |
| 일반 Worker | 0회 | 1회 (A) | 0회 | 0회 |

이 표가 사이클 매트릭스 R4·R5·R6 의 정의가 된다.

## 5. 변경 항목 체크리스트

- [ ] `service/prompt/sections.py::build_agent_prompt`
  - `role == "vtuber"` 분기 추가 (role_protocol 로딩 스킵).
  - 한 줄 주석으로 "PersonaProvider 가 책임짐 (cycle 20260422_6 PR4)" 명시.
- [ ] `service/persona/character_provider.py::resolve`
  - `is_vtuber=False` 분기 → 빈 `PersonaResolution` 반환.
  - cache_key 마커 `W_NO_PERSONA`.
- [ ] (선택) manifest 단계에서 Worker 세션이 `DynamicPersonaSystemBuilder` 를
  거치지 않도록 분기 — 검토 후 결정.
- [ ] `service/langgraph/agent_session_manager.py`
  - `_build_system_prompt` 의 두 군데 (L406 부근, L847 부근) 직접 append 코드
    제거.
  - VTuber 안내 블록은 `persona_provider.append_context(...)` 만 호출.
  - Sub-Worker 안내 블록은 `worker.md` 의 정적 섹션으로 이전 (§4 결정).
- [ ] `prompts/worker.md`
  - 하단에 `## Paired VTuber Agent` 섹션 추가 (현재 코드의 하드코딩 텍스트
    내용을 그대로 옮김).
- [ ] PROMPTS.md / PROMPTS_KO.md — 시스템 프롬프트 합성 다이어그램 갱신.

## 6. 회귀 / 단위 테스트

- [ ] `tests/service/persona/test_character_provider.py`
  - `test_resolve_returns_empty_for_worker` — `is_vtuber=False` → blocks=[].
  - `test_resolve_keeps_vtuber_path_intact` — 기존 VTuber 경로 회귀.
- [ ] `tests/service/langgraph/test_agent_session_manager.py` (또는 신설)
  - `test_vtuber_system_prompt_contains_vtuber_md_exactly_once` — 빌드된
    VTuber 시스템 프롬프트에서 `vtuber.md` 첫 단락 첫 30자가 정확히 1회
    등장.
  - `test_worker_system_prompt_contains_no_persona_blocks` — `[Mood]`,
    `[Vitals]`, `[Bond`, `[StageObservation]`, `[Acclimation]` 모두 0회.
  - `test_vtuber_system_prompt_contains_subworker_block_once` — `## Sub-Worker
    Agent` 헤더가 1회.
- [ ] `tests/integration/test_progression_e2e.py`
  - Worker 세션 시나리오를 추가 (있다면), live_blocks 출력 미포함 검증.
- [ ] **토큰 회귀** (사이클 매트릭스 R8): Worker 세션의 시스템 프롬프트
  토큰 수 측정 — X7 머지 직전 baseline 대비 ≥ 30% 감소 확인. 측정은
  `test_worker_system_prompt_token_budget` 단위 테스트 + 사이클 close 시
  diff 표 첨부.

## 7. 위험 / 완화

| 위험 | 완화 |
|---|---|
| (α) 만으로 부족하면 Worker 도 빈 PersonaBlock(`""`) 1개를 받음 — `ComposablePromptBuilder` 가 빈 문자열을 어떻게 다루는지 확인 필요 | `ComposablePromptBuilder` 는 빈 fragment 를 drop 함 (existing behaviour, blocks.py 모듈 docstring 에 명시). 안전. |
| `default_worker_prompt` / `adaptive` 인자가 더 이상 사용되지 않음 — dead code | 본 PR 에서는 시그니처 유지 (외부 호출 깨지지 않게). 다음 사이클에서 제거. |
| 위임 안내 블록 단일화 후, 기존 운영 세션의 reconstruct 시 안내 블록이 빠짐 | reconstruct 경로에서 `append_context` 호출 (idempotent) 보장 — §4 의 `_build_system_prompt` 변경 항목에 명시. |
| Sub-Worker 의 `## Paired VTuber Agent` 가 `worker.md` 정적 섹션으로 이동하면, **일반 Worker 도** 그 섹션을 받게 됨 | 두 가지 처리 가능: (a) `worker.md` 의 해당 섹션을 "When you are a paired Sub-Worker (linked_session_id is set), …" 조건문으로 시작 — 일반 Worker 가 봐도 무시되도록. (b) `worker.md` 와 별도로 `worker_paired.md` 를 두고 A 경로에서 `session_type=="sub"` 일 때만 로드. **본 PR 채택: (a)** — 파일 분리는 토큰 절약 효과가 미미함. |
| 회귀 테스트가 충분치 않으면 vtuber.md 가 0회 등장하는 invariant 위반 가능 | 위 §6 의 `test_vtuber_system_prompt_contains_vtuber_md_exactly_once` 가 정확히 이 회귀를 잡음. CI 필수. |

## 8. 사이클 매트릭스 기여

본 PR 이 직접 보장하는 매트릭스 항목:
- **R4** (vtuber.md 정확히 1회).
- **R5** (Worker 시스템 프롬프트에 페르소나·라이브 상태 0회).
- **R6** (Sub-Worker 위임 안내 정확히 1회).
- **R8** (Worker 시스템 프롬프트 토큰 ≥ 30% 감소).
