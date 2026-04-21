# 분석 02 — Geny 통합 감사 : 파이프라인을 존중했는가, 우회했는가

**대상.** `/home/geny-workspace/Geny/backend`
**기준.** 16-STAGE 테제 준수도.
**질문.** "Geny 안에 `stage` 여야 할 logic 이 외부에 떠 있지는 않은가?
또는 `attach_runtime` 으로 풀 수 있는 일을 파이프라인 내부를 해체해서 풀지는 않았는가?"

---

## 0. 총평

**전반적으로 매우 깨끗하다.** Geny 는 executor 를 **라이브러리로** 쓴다. 파이프라인 실행 본체
는 손대지 않고, 다음 네 레이어로만 개입한다:

1. **Manifest 빌드 → `Pipeline.from_manifest_async`** — 선언적 파이프라인 생성.
2. **`attach_runtime(...)`** — 세션-스코프 객체 (memory_retriever / memory_strategy /
   memory_persistence / system_builder / tool_context / llm_client) 주입.
3. **PipelineMutator** — 세션 시작 직전 per-stage 모델 오버라이드.
4. **Background services** — curation, thinking_trigger, avatar_state_manager 를
   파이프라인 *외부* 비동기 루프로.

그러나 **3개의 "사이드도어(Side Door)"** 가 발견됨 — 분석 §5 참조.
어떤 것도 파이프라인을 우회하지는 않지만, `attach_runtime` 의 스코프를 살짝 벗어나 있으며,
다마고치 기획을 얹을 때 *확실히 문제가 될* 지점들이다.

---

## 1. 파이프라인 구축 경로 — "Manifest-first"

### 진입점 : `AgentSession._build_pipeline` (agent_session.py:736-971)

핵심 단정문 두 개:

- `prebuilt_pipeline is None` 이면 하드 에러 (agent_session.py:753-761). 즉
  **`AgentSession` 은 절대 파이프라인을 스스로 만들지 않는다.** `AgentSessionManager` 가
  `EnvironmentService.instantiate_pipeline()` → `Pipeline.from_manifest_async()` 로
  먼저 만들어서 넘겨야 한다.
- 모든 stage 구성·strategy 선택·모델 설정은 **manifest 쪽** 에 있다. Geny 코드가 stage 를
  `register_stage` 로 수동 등록하는 곳은 전체에 없다.

### 주입되는 런타임 (agent_session.py:927-960)

```python
attach_kwargs = {
    "system_builder": ComposablePromptBuilder([
        PersonaBlock(persona_text),
        DateTimeBlock(),
        MemoryContextBlock(),
    ]),
    "tool_context": ToolContext(session_id=..., working_dir=..., storage_path=...),
    "llm_client": llm_client,
}
if self._memory_manager is not None:
    attach_kwargs["memory_retriever"]   = GenyMemoryRetriever(...)
    attach_kwargs["memory_strategy"]    = GenyMemoryStrategy(..., resolver=...)
    attach_kwargs["memory_persistence"] = GenyPersistence(...)

self._pipeline = self._prebuilt_pipeline
self._pipeline.attach_runtime(**attach_kwargs)
```

- **executor 가 공식 허용하는 6개 키 중 6개 다 사용.** 이 형태가 Geny 통합의 중심이다.
- `ComposablePromptBuilder` 는 executor 가 제공한 기본 빌더 — 파일을 넘나들어 "어떻게 만들지"
  만 Geny 가 정함.

### 세션 별 모델 오버라이드 (agent_session.py:827-862)

```python
mem_model_name = (api_cfg.memory_model or "").strip() or api_cfg.anthropic_model
memory_cfg = ModelConfig(model=mem_model_name, max_tokens=..., ...)
mutator = PipelineMutator(self._prebuilt_pipeline)
mutator.set_stage_model(2, memory_cfg)    # s02 context
mutator.set_stage_model(15, memory_cfg)   # s15 memory
```

- cycle 20260421_4 의 성과. **설계 의도에 정확히 맞는 사용** — mutator 는 attach 전에
  작동 (파이프라인은 아직 실행 전이므로 잠기지 않음).
- 모델 라우팅의 책임이 manifest 가 아닌 런타임에 있다는 선택. 타당 — memory_model 은 사용자
  config 에 따라 달라지므로 manifest 에 고정하면 안 됨.

### 평가

**스테이지 수준에서는 티끌 없이 깨끗.** 17번째 stage 시도 없음, register_stage 수동 사용 없음,
파이프라인 내부 mutation during run 없음.

---

## 2. 메모리 — 파이프라인 안팎의 경계

Geny 메모리 시스템은 크게 두 덩어리:

### 2-1. 세션 내부 (파이프라인이 사용)

- **`SessionMemoryManager`** (memory/manager.py, 1218줄) — 실제 저장소 (파일, DB).
- **`GenyMemoryRetriever`** (executor 의 `MemoryRetriever` 구현) — `SessionMemoryManager`
  를 덮어 s02_context 의 retriever 슬롯에 꽂히는 *어댑터*.
- **`GenyMemoryStrategy`** — s15_memory 의 strategy 슬롯. LLM 기반 reflection 포함.
- **`GenyPersistence`** — s15_memory 의 persistence 슬롯. 긴 대화 영구 기록.

→ **이 셋은 executor 의 공식 슬롯 인터페이스의 구현체** — 파이프라인이 자연스럽게 호출.

### 2-2. 파이프라인 외부 (Background batch)

- **`CurationEngine`** (memory/curation_engine.py, 598줄) — 노트 큐레이션 5-stage 파이프라인
  (triage → analyze → transform → enrich → store). **executor 파이프라인과 무관** 한
  자체 파이프라인.
- **`CurationScheduler`** (memory/curation_scheduler.py) — 5분 주기 배치 트리거.
- **`CuratedKnowledgeManager`** (memory/curated_knowledge.py) — 큐레이션 결과물 저장 + 조회.
- **`VectorMemory`** (memory/vector_memory.py) — FAISS 벡터 인덱스.
- **`memory_llm.py`** — 이번 사이클에서 통일된 LLM 어댑터 (cycle 20260421_5).

### 경계 원칙

**큐레이션은 에이전트 실행이 아니다** — 주기적 배치 작업이므로 파이프라인 외부가 맞다.
에이전트가 실행 시 읽는 curated-knowledge *저장소* 를 큐레이션이 채우고, 에이전트의
s02_context retriever 가 그 저장소를 읽는다. **경계가 정확.**

### 잠재 위험

다마고치 설계에 "밤새 캐릭터가 혼자 생각해서 기억을 정리" 를 넣게 되면 — 이것은
curation 과 동일한 "세션 외부 LLM 호출" 이다. `memory_llm.py` 의 `build_memory_llm()`
가 이미 그 자리. 설계 충돌 없음.

---

## 3. VTuber / 감정 — **여기가 가장 흥미로운 회색지대**

### 3-1. executor 가 이미 제공하는 것

- `VTuberEmitter` (stages/s14_emit/artifact/default/emitters.py:59-105) — **키워드 기반**
  감정 추출. "기뻐", "😊", "awesome" 같은 단어 매칭.
- `TTSEmitter` (107-127) — `tts_callback(text)` 호출.
- 기본 preset 중 `geny_vtuber(api_key, model, persona, tools)` 존재.

### 3-2. Geny 가 자체 구현한 것

`backend/service/vtuber/` 전부:

| 파일 | 줄수 | 책임 | 파이프라인과 관계 |
|---|---|---|---|
| `emotion_extractor.py` | 163 | `[joy]`, `[sadness]` 등 **LLM-생성 브래킷 태그** 파싱 + Live2D expression index 매핑 | 파이프라인 **완료 후** 호출 (`_emit_avatar_state`) |
| `avatar_state_manager.py` | 159 | 세션별 Live2D 상태 저장 + WebSocket broadcast | 파이프라인 바깥 |
| `live2d_model_manager.py` | 151 | 캐릭터 모델 정의 / emotion_map 카탈로그 | 정적 |
| `thinking_trigger.py` | **886** | 유휴 감지 + `[THINKING_TRIGGER]` 메시지를 에이전트에 **자가 입력** | 파이프라인 바깥, 입력 생성자 |
| `delegation.py` | 150 | VTuber ↔ Sub-Worker 메시지 태그 프로토콜 | 파이프라인은 태그를 메시지로 수신 |
| `tts/` | n/a | TTS 합성 (Edge TTS) | 파이프라인 바깥 |

### 3-3. 왜 executor 의 VTuberEmitter 를 쓰지 않고 Geny 쪽에 따로 두었는가

**근본 이유.** Geny 의 감정 추출은
- LLM 이 **명시적으로** `[emotion_name]` 태그를 출력하게 프롬프트 쪽에서 강제 (페르소나),
- 태그를 정규식으로 뽑고,
- **모델별로 다른 `emotion_map`** (예: `{"joy": 3, "anger": 1}`) 로 Live2D expression index 매핑,
- Live2D model manager 의 mapping 과 동기화.

→ executor 의 키워드 기반 VTuberEmitter 는 이 요구를 전혀 못 채운다.
→ **둘은 의도가 다른 다른 알고리즘** — executor 것은 "LLM 이 감정 태그를 안 낼 때의 fallback",
Geny 것은 "LLM 이 명시 태그를 낼 때의 정식 처리".

### 3-4. 이 이중화가 문제인가

**당장은 아니다.** 두 가지는 공존할 수 있다:
- executor 기본 preset 의 `VTuberEmitter` 는 **자체 소비자용 fallback**.
- Geny 는 s14 의 `emitters` chain 에 `CallbackEmitter` 만 등록하고,
  그 callback 에서 `EmotionExtractor.extract()` 를 돌린다. 깨끗한 분리.

**그러나 다마고치 기획에서는 문제가 된다.** 이유:
1. "감정 태그" 가 대사 하나로 끝나지 않고 *관계값 변동* 을 일으켜야 한다면,
2. 그 변동이 다시 *다음 iteration의 retrieval / prompt* 에 반영돼야 한다면,
3. → 이것은 **파이프라인 내부에 피드백 루프가 필요** 하다는 뜻.

현재 `EmotionExtractor` 는 post-hoc 이고, 그 결과는 `avatar_state_manager` 에 저장될 뿐
다음 파이프라인 run 의 `state.shared["mood"]` 같은 곳으로 *다시 들어가지 않는다.*
→ **분석 03 §4 에서 "감정 피드백 슬롯" 이슈로 재방문**.

---

## 4. 실행 서비스 — 단일 진입점의 규율

### `backend/service/execution/agent_executor.py` — 철학선언

파일 상단 (5-20줄) 의 주석:
> **All agent execution goes through this single module. A chat-room
> broadcast is nothing more than N concurrent command executions.
> There is ONE execution path — never two.**

이 파일이 담당:

- 활성 실행 추적 (`_active_executions`)
- 세션 로깅 (`log_command` / `log_response`)
- 비용 영속화
- Auto-revival
- 이중 실행 방지
- 타임아웃
- 아바타 상태 후처리 (`_emit_avatar_state`)
- Sub-Worker → VTuber 자동 보고 (`_notify_linked_vtuber`)

### 평가

**올바른 자리.** 파이프라인 실행 전/후의 관리 업무 — 두 실행이 겹치면 안 된다, 비용을
세션 기록에 남겨야 한다, Live2D 아바타를 업데이트해야 한다 — 이것들은 "스테이지" 가 아니다.
세션 단위 거버넌스다.

**한 가지 관찰.** `_emit_avatar_state` 가 파이프라인 이벤트 구독이 아닌 *직접 호출* 로
연결되어 있다. 즉 executor 의 EventBus 를 쓰지 않는다. 나쁘지 않지만,
다마고치에서 "매 turn 마다 상태값 변동" 같은 tick 을 넣으려면 EventBus 기반 어플로치가
더 자연스러워진다 (→ 분석 04 §5).

---

## 5. 사이드도어 — 세 개의 `_system_prompt` 직접 수정

`grep _system_prompt` 결과, Geny 가 **객체 내부 attribute 를 외부에서 직접 mutate** 하는
지점 3곳 발견:

### 사이드도어 A — 캐릭터 프롬프트 주입

`controller/vtuber_controller.py:49-54`:

```python
if marker in (agent._system_prompt or ""):
    return
agent._system_prompt = (agent._system_prompt or "") + "\n\n" + char_prompt
if hasattr(agent, "process"):
    agent.process.system_prompt = agent._system_prompt
```

- 캐릭터 모델 선택 시, 해당 캐릭터의 프롬프트 파일 (`_CHARACTERS_DIR / {model_name}.md`)
  을 읽어 세션이 시작된 **후에** 덧붙인다.
- 세션 생성 시에는 아직 캐릭터를 몰랐다는 소리 — UX 플로우의 특성.

### 사이드도어 B — system prompt 재작성 API

`controller/agent_controller.py:304`:

```python
agent._system_prompt = new_prompt
```

- 사용자가 런타임에 프롬프트를 교체할 수 있도록 HTTP API 제공 (세션 메모리 UI / 디버깅).

### 사이드도어 C — VTuber 컨텍스트 append

`service/langgraph/agent_session_manager.py:673`:

```python
agent._system_prompt = (agent._system_prompt or "") + vtuber_ctx
```

- Sub-Worker 가 VTuber 에게 자기 존재를 알릴 때 VTuber 쪽 system_prompt 에 정보 삽입.

### 공통 문제

**세 경우 모두** `_system_prompt` 라는 private-ish attribute 를 외부에서 *문자열 수준으로*
편집한다. 이 문자열은 `AgentSession.__init__` 에서 한 번 `self._system_prompt = system_prompt`
로 저장되고 (agent_session.py:210), 이후 파이프라인 재구성 시 `system_prompt=...` 로
manifest build 에 사용되거나 (agent_session.py:1751), `_build_pipeline()` 안에서 persona 블록에
들어간다 (agent_session.py:807).

### 이것이 파이프라인 우회인가

**아니다.** 파이프라인은 *여전히* `PersonaBlock(persona_text)` 을 통해 s03_system stage 에서
이 문자열을 읽는다. 16-STAGE 경로를 벗어나지 않는다.

### 그러나 *약한 고리* 다

- `_system_prompt` 는 비공개 접두사. private-by-convention 규약을 Geny 가 스스로 어긴다.
- 문자열 연결이라는 저품질 합성 — A/B/C 의 순서가 바뀌면 결과도 바뀜.
- **리빌드 사이의 정합성** — 파이프라인이 이미 한 번 `attach_runtime()` 된 후 `_system_prompt`
  을 바꾸면, `PersonaBlock` 에 들어간 *인스턴스* 는 바뀌지 않는다 (캡처된 값).
  다시 `_build_pipeline()` 을 부르기 전까지 반영 안 됨.
- 다마고치에서 "관계값이 상승해서 캐릭터 말투가 친해짐" 같은 동적 페르소나 변경은
  **이 경로로는 부자연스럽다.**

### 개선 방향 (개념만 — 분석 04, 05 에서 구체화)

1. `PersonaBlock` 을 **late-bind** 하도록 — string 대신 `Callable[[state], str]` 을 받도록.
2. 또는 `attach_runtime` 가 수용하는 "persona_provider" slot 을 신설.
3. 문자열 concat 을 제거하고 **블록 리스트 수준에서** compose.

---

## 6. Tools — GenyToolProvider 의 깨끗한 통합

### 경로

`service/langgraph/tool_bridge.py` + `service/langgraph/geny_tool_provider.py`.

- executor 는 `AdhocToolProvider` 프로토콜을 제공 (tools 시스템).
- Geny 의 `GenyToolProvider` 가 이 프로토콜 구현 — `list_names()`, `get(name)`.
- `EnvironmentService.instantiate_pipeline()` 이 `adhoc_providers=[tool_provider]` 로
  넘겨 `Pipeline.from_manifest_async(adhoc_providers=...)` 에 전달.
- 툴 어댑터 (`_GenyToolAdapter`) 는 Geny 의 `BaseTool.run(**kwargs)` 을 executor 의
  `async Tool.execute(input, context)` 로 형상 변환.
- session_id 주입을 "툴이 받을 수 있는지" probing 으로 결정.

### 평가

**모범 사례.** executor 의 공식 확장 프로토콜 (`AdhocToolProvider`) 이 있고, Geny 는
거기에 맞춰서 어댑터를 구현했다. 파이프라인 내부 tool 처리 (s10_tool) 는 전혀 안 건드림.

**다마고치 대입 — tools 가 행동이 된다.** "먹이 주기 / 놀아주기 / 선물하기" 는 툴로 구현되면
자연스럽다 — 각각이 상태값을 올리는 사이드이펙트를 가진다. `GenyToolProvider` 에 등록하면
끝. 설계 충돌 없음.

---

## 7. Thinking Trigger — 886줄짜리 배경 자가 입력자

`service/vtuber/thinking_trigger.py` 의 규모는 놀랍다. 담당:

- 세션별 유휴 감지 (마지막 사용자 입력 후 N초).
- 주기적으로 `[THINKING_TRIGGER] <signal>` 메시지를 자가 생성 → 에이전트 input 으로 보내서
  "혼잣말" 을 유도.
- 긴 대기 구간의 로직 (화가 났을 때 더 길게 참는다, 뭔가 자극적인 새 정보가 들어오면 바로
  반응한다 등).

### 파이프라인과의 관계

**입력 생성자.** 파이프라인은 여기서 나온 메시지를 *정상 user 메시지로* 받아 통상 16-STAGE 를
돈다. 파이프라인 내부에 자체 타이머·트리거가 없고 — 외부에서 input 을 만들어 넣는 구조.

### 평가

**올바르다. 다만 다마고치 관점에서 핵심 요소.** 기획안의

- ① 책임감 (방치 페널티) — thinking_trigger 가 "방치 감지" 와 함께 "삐짐 상태 진입" 을
  트리거.
- ④ 감정 연결 (반응함/기억함) — 오랜만에 접속 시 "기다렸어" 메시지는 thinking_trigger
  로직의 확장.

→ **이 모듈은 이미 다마고치의 "생명체 심박" 역할을 할 모든 구조를 가지고 있다.**
수정/확장이 용이하도록 slot 화 정리가 필요할 뿐 (→ 분석 04 §6).

---

## 8. Manifest 별 파이프라인 구성 차이

`service/langgraph/default_manifest.py` 에서 sevral preset manifest:

### worker_adaptive (Sub-Worker 용)

- 16 stage 풀 파이프라인
- s08_think 포함 (내부 reasoning)
- s05_cache: aggressive_cache
- s12_evaluate: binary_classify (`[TASK_COMPLETE]` / `[CONTINUE]`)
- s13_loop: max_turns=30

### vtuber (VTuber 용)

- s08_think **제거** (다마고치 캐릭터에겐 내부 reasoning 이 오히려 지연)
- s05_cache: system_cache (더 작은 컨텍스트)
- s12_evaluate: signal_based (메시지 태그 기반)
- s13_loop: max_turns=10

### 평가

**manifest 가 역할별 다양성을 표현하는 정석 사례.** 스테이지 구성과 strategy 선택이 파일로
박혀 있어 버저닝 / diff / 복원 가능.

**다마고치 관점 의미.** 기획안의 각 게임 모드 (초기 새끼 / 성장기 / 성체) 를 *다른 manifest*
로 표현하면 자연스럽다:
- 새끼 단계: 단순 대사 생성, tool 제한, thinking_trigger 긴 간격.
- 성장 단계: tool 풀세트, 감정 태그 요구, 관계값 반영.
- 성체 단계: 사용자 컨텐츠 소비 (영상/음악), 복잡한 reflection.

---

## 9. 통합 판정 매트릭스

| 영역 | 상태 | 근거 |
|---|---|---|
| Pipeline 생성 경로 | ✅ Clean | Manifest + attach_runtime, 수동 register 없음 |
| 메모리 주입 (s02, s15) | ✅ Clean | executor 공식 슬롯 구현체 |
| 툴 주입 (s10) | ✅ Clean | AdhocToolProvider 프로토콜 사용 |
| 모델 라우팅 (per-stage) | ✅ Clean | PipelineMutator.set_stage_model |
| 큐레이션 (background) | ✅ Clean | 파이프라인 외부 배치 |
| Thinking trigger | ✅ Clean | 파이프라인 입력 생성자 |
| TTS / Live2D | ✅ Clean | post-pipeline emitter/hook |
| 감정 추출 | ⚠️ 이중화 | executor 기본 VTuberEmitter 와 Geny EmotionExtractor 공존 — 분리된 의도이므로 용납 가능 |
| `_system_prompt` 직접 수정 × 3곳 | ⚠️ 사이드도어 | 우회는 아니나 late-bind 인터페이스 부재 |
| 감정→다음-턴 피드백 | ❌ 부재 | 파이프라인 내부로 돌아오지 않음 |
| CreatureState (다마고치 상태값) | ❌ 부재 | 1급 타입 필드 없음, dict 관례에 의존해야 |

---

## 10. 다음 사이클이 건드려야 할 것들 (미리보기)

1. **`_system_prompt` 수정 3곳 → `PersonaProvider` 슬롯 혹은 `attach_runtime` 확장**
2. **감정 추출 결과 → `state.shared["mood"]` 로 피드백 가능한 공식 훅 만들기**
3. **"CreatureState" 의 자리 결정** — dict 관례 vs 새 슬롯 타입 vs PipelineState 1급 필드
4. **Manifest 별 모드 확립** — 새끼/성장/성체의 서로 다른 manifest 로 분리
5. **thinking_trigger 를 "생명체 tick" 인터페이스로 정리** (방치 페널티 / 접속 보상 / 랜덤
   이벤트 의 3종을 하나의 tick 엔진에서 공급)

이것들은 분석 03 과 04 에서 구체화된다.

---

## 부록 A — 검증된 파일 라인 인덱스

| 주장 | 파일 | 라인 |
|---|---|---|
| `AgentSession.__init__` 시 system_prompt 저장 | `service/langgraph/agent_session.py` | 210 |
| manifest 기반 파이프라인 강제 | `service/langgraph/agent_session.py` | 753-761 |
| memory_llm 관련 imports | `service/langgraph/agent_session.py` | 763-780 |
| attach_runtime 호출 | `service/langgraph/agent_session.py` | 927-960 |
| per-stage model 오버라이드 | `service/langgraph/agent_session.py` | 827-862 |
| 캐릭터 프롬프트 사이드도어 | `controller/vtuber_controller.py` | 49-54 |
| system_prompt 재작성 사이드도어 | `controller/agent_controller.py` | 304 |
| VTuber 컨텍스트 append 사이드도어 | `service/langgraph/agent_session_manager.py` | 673 |
| EmotionExtractor 전체 | `service/vtuber/emotion_extractor.py` | 1-163 |
| thinking_trigger 전체 | `service/vtuber/thinking_trigger.py` | 1-886 |
| avatar_state_manager 전체 | `service/vtuber/avatar_state_manager.py` | 1-159 |
| 큐레이션 엔진 | `service/memory/curation_engine.py` | 1-598 |
| SessionMemoryManager | `service/memory/manager.py` | 1-1218 |
| 단일 실행 경로 철학선언 | `service/execution/agent_executor.py` | 5-20 |
