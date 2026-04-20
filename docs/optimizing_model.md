# Auxiliary Model Optimization — Deep Analysis Report

**Date**: 2026-04-01
**Scope**: Memory, ThinkingTrigger, Classification 등 보조 작업에 경량 모델 적용 가능성 심층 분석

---

## 1. Executive Summary

현재 시스템은 **모든 워크플로우 노드가 하나의 동일한 모델**(`ExecutionContext.model`)을 사용한다.
VTuber 워크플로우의 경우 분류, 사고, 응답, 메모리 반성 등 **용도와 난이도가 매우 다른 작업**들이
동일한 고가 모델(Sonnet 4.6)로 처리되고 있다.

**결론: 보조 모델(Auxiliary Model) 도입이 기술적으로 가능하며, 구현 난이도가 낮다.**

- `langchain-anthropic` 패키지가 이미 의존성에 포함됨 (미사용 상태)
- `ChatAnthropic` 인스턴스를 `ExecutionContext`에 추가하면 런타임에 모델 분기 가능
- 노드별 `config`에 `use_auxiliary_model: bool` 파라미터 추가로 세밀한 제어 가능
- Config 시스템에 `auxiliary_model` 설정 1개 추가로 UI에서 관리 가능

---

## 2. 현재 아키텍처 분석

### 2.1 모델 흐름 (현재)

```
AgentSession.initialize()
    │
    ├─ ClaudeCLIChatModel(model_name="claude-sonnet-4-6")
    │       └─ ClaudeProcess (CLI subprocess per execution)
    │
    └─ _build_graph()
            └─ ExecutionContext(model=self._model)   ← 단일 모델
                    │
                    ├─ memory_inject.execute(state, context, config)
                    │       └─ context.resilient_structured_invoke()  ← 같은 모델
                    │
                    ├─ vtuber_classify.execute(state, context, config)
                    │       └─ context.resilient_invoke()             ← 같은 모델
                    │
                    ├─ vtuber_respond.execute(state, context, config)
                    │       └─ context.resilient_invoke()             ← 같은 모델
                    │
                    └─ memory_reflect.execute(state, context, config)
                            └─ context.resilient_structured_invoke()  ← 같은 모델
```

### 2.2 핵심 컴포넌트

| 컴포넌트 | 파일 | 역할 |
|----------|------|------|
| `ExecutionContext` | `workflow/nodes/base.py` | 모든 노드에 전달되는 실행 컨텍스트 (모델 포함) |
| `ClaudeCLIChatModel` | `langgraph/claude_cli_model.py` | Claude CLI 서브프로세스 래퍼 (LangChain BaseChatModel) |
| `WorkflowExecutor` | `workflow/workflow_executor.py` | 그래프 빌드 시 모든 노드에 동일 context 주입 |
| `AgentSession._build_graph()` | `langgraph/agent_session.py` | ExecutionContext 생성, 그래프 컴파일 |
| `APIConfig` | `config/sub_config/general/api_config.py` | 모델명, API 키 등 전역 설정 |

### 2.3 모델 생성 방식

```python
# ClaudeCLIChatModel — CLI 서브프로세스 방식
self._model = ClaudeCLIChatModel(
    session_id=self._session_id,
    model_name=self._model_name,   # "claude-sonnet-4-6"
    working_dir=...,
)
await self._model.initialize()     # ClaudeProcess 서브프로세스 스폰
```

- 각 `execute()` 호출마다 `node.exe cli.js --model <model> ...` 서브프로세스 실행
- 실행당 수 초의 프로세스 스폰 오버헤드
- `_execution_lock`으로 인스턴스당 직렬 실행

---

## 3. VTuber 워크플로우 노드별 LLM 호출 분석

### 3.1 전체 워크플로우 그래프

```
START → memory_inject → vtuber_classify
            │
            ├─ "direct_response" → vtuber_respond ──┐
            ├─ "delegate_to_cli" → vtuber_delegate ─┤
            └─ "thinking"        → vtuber_think ────┘
                                                    ▼
                                              memory_reflect → END
```

### 3.2 노드별 LLM 호출 상세

| 노드 | LLM 호출 | 용도 | 난이도 | 경량 모델 적합? |
|------|----------|------|--------|----------------|
| **memory_inject** | 0~1회 (gate) | "메모리 검색이 필요한가?" (bool) | ⭐ 매우 낮음 | ✅ **최적 후보** |
| **vtuber_classify** | 0~1회 | 입력을 3가지 카테고리로 분류 | ⭐ 매우 낮음 | ✅ **최적 후보** |
| **vtuber_respond** | 1회 | 사용자 메시지에 페르소나 기반 응답 생성 | ⭐⭐⭐ 높음 | ❌ 메인 모델 필요 |
| **vtuber_think** | 1회 | idle 시 내부 독백/반성 생성 | ⭐⭐ 중간 | ⚠️ 상황에 따라 |
| **vtuber_delegate** | 1회 | 사용자 요청을 서브 워커 작업 지시로 변환 | ⭐⭐ 중간 | ⚠️ 상황에 따라 |
| **memory_reflect** | 0~1회 | 대화에서 인사이트 추출 (JSON) | ⭐⭐ 중간 | ✅ **적합** |
| **transcript_record** | 0회 | 파일 I/O만 수행 | - | - |

### 3.3 노드별 상세 분석

#### `memory_inject` — Memory Gate (LLM 호출 0~1회)

```python
# enable_llm_gate=True (기본값)일 때:
result, fallback = await context.resilient_structured_invoke(
    messages, "memory_gate", MemoryGateOutput,
    # MemoryGateOutput = { needs_memory: bool, reasoning: Optional[str] }
)
```

- **입력**: 사용자 메시지 1줄
- **출력**: `needs_memory: bool` (단일 boolean)
- **판단**: "안녕" → False, "어제 내가 말한 거 기억나?" → True
- **경량 모델 적합도**: ★★★★★ — 이진 분류. Haiku 4.5로 충분
- **비용 절감**: 이 호출이 스킵되면 0, 경량 모델 사용 시 ~1/10 비용

#### `vtuber_classify` — Input Classification (LLM 호출 0~1회)

```python
response, fallback = await context.resilient_invoke(classify_messages, "vtuber_classify")
# 응답에서 "direct_response" / "delegate_to_cli" / "thinking" 중 하나 파싱
```

- **입력**: 사용자 메시지 + 분류 프롬프트
- **출력**: 단일 단어 (3개 중 택1)
- **Fast-path**: `[THINKING_TRIGGER]`, `[SUB_WORKER_RESULT]` 시 LLM 호출 없이 바로 라우팅
- **경량 모델 적합도**: ★★★★★ — 3-way 분류. Haiku 4.5로 충분
- **비용 절감**: ~1/10 비용

#### `vtuber_respond` — 응답 생성 (LLM 호출 1회)

```python
response, fallback = await context.resilient_invoke(messages, "vtuber_respond")
```

- **입력**: 사용자 메시지 + 메모리 컨텍스트 + 페르소나 지시
- **출력**: 감정 태그 포함 자연어 응답
- **경량 모델 적합도**: ★☆☆☆☆ — 페르소나 일관성, 감정 표현, 문맥 이해 필요
- **결론**: **메인 모델 필수**. 사용자가 직접 보는 출력.

#### `vtuber_think` — 사고/독백 (LLM 호출 1회)

```python
response, fallback = await context.resilient_invoke(messages, "vtuber_think")
```

- **입력**: [THINKING_TRIGGER] 프롬프트 + 메모리 컨텍스트
- **출력**: 독백 텍스트 또는 `[SILENT]`
- **경량 모델 적합도**: ★★★☆☆ — 내부 독백이나 사용자에게 표시됨 (VTuber 채팅 패널)
- **결론**: Config로 선택 가능하게. 기본은 메인 모델, 비용 절감 시 경량 모델 옵션

#### `vtuber_delegate` — 서브 워커 작업 위임 (LLM 호출 1회)

```python
response, fallback = await context.resilient_invoke(messages, "vtuber_delegate")
```

- **입력**: 사용자 요청 + 위임 프롬프트
- **출력**: 서브 워커에 전달할 작업 지시문
- **경량 모델 적합도**: ★★★☆☆ — 작업 지시 품질이 서브 워커 실행 품질에 직결
- **결론**: Config로 선택 가능하게. 기본은 메인 모델 권장

#### `memory_reflect` — 인사이트 추출 (LLM 호출 0~1회)

```python
result, fallback = await context.resilient_structured_invoke(
    messages, "memory_reflect", MemoryReflectOutput,
    # MemoryReflectOutput = { learned: List[MemoryReflectLearnedItem], should_save: bool }
)
```

- **입력**: input 2000자 + output 3000자 (제한됨)
- **출력**: JSON 구조화 인사이트 목록 (제목, 내용, 카테고리, 태그, 중요도)
- **스킵 조건**: `skip_memory_reflect=True` (SILENT) 또는 empty output
- **경량 모델 적합도**: ★★★★☆ — 구조화된 정보 추출. 품질은 약간 하락 가능하나 수용 범위
- **비용 절감**: ~1/10 비용. Thinking trigger 경로에서 특히 효과적

---

## 4. 기술적 실현 가능성

### 4.1 의존성 현황

| 패키지 | 상태 | 용도 |
|--------|------|------|
| `langchain-anthropic>=0.3.0` | ✅ **이미 설치됨** (requirements.txt) | `ChatAnthropic` 직접 API 모델 |
| `anthropic` | ✅ 설치됨 (transitive) | langchain-anthropic 의존성 |
| `langchain-core` | ✅ 설치됨 | `BaseChatModel`, `AIMessage` 인터페이스 |

**`ChatAnthropic`은 이미 사용 가능**하다. 추가 패키지 설치 불필요.

### 4.2 인터페이스 호환성

```python
# 현재 메인 모델 (CLI 래퍼)
class ClaudeCLIChatModel(BaseChatModel):
    async def ainvoke(self, messages) -> AIMessage: ...

# 보조 모델 후보 (직접 API)
from langchain_anthropic import ChatAnthropic
class ChatAnthropic(BaseChatModel):
    async def ainvoke(self, messages) -> AIMessage: ...
```

**동일한 `BaseChatModel` 인터페이스**를 공유한다.
`ExecutionContext.resilient_invoke()`는 `self.model.ainvoke(messages)`만 호출하므로,
`ChatAnthropic` 인스턴스를 drop-in replacement로 사용 가능하다.

### 4.3 두 가지 구현 방식 비교

| 방식 | 장점 | 단점 |
|------|------|------|
| **A. `ChatAnthropic` (직접 API)** | 스폰 오버헤드 0, 경량, 빠름 | 대화 기록 없음 (stateless), CLI 도구 미사용 |
| **B. 두 번째 `ClaudeCLIChatModel`** | 대화 기록 유지, CLI 도구 사용 가능 | 프로세스 스폰 오버헤드, 메모리 사용 2배 |

**권장: 방식 A (`ChatAnthropic`)**

보조 작업(분류, 메모리 게이트, 인사이트 추출)은 **상태 없는 단발 호출**이다.
대화 기록이나 도구 실행이 불필요하므로 `ChatAnthropic` 직접 API가 최적이다.

### 4.4 `ChatAnthropic`의 보조 모델 적합성

```python
from langchain_anthropic import ChatAnthropic

aux_model = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    api_key=os.environ.get("ANTHROPIC_API_KEY"),
    max_tokens=1024,        # 보조 작업은 출력이 짧음
    timeout=30,             # 빠른 타임아웃
)
```

- **latency**: ~0.5–2초 (vs ClaudeProcess 5–15초)
- **비용**: Haiku 4.5 — 입력 $0.80/1M, 출력 $4/1M (Sonnet 4.6 대비 ~1/4~1/10)
- **품질**: 분류/boolean/구조화 추출에 충분

---

## 5. 구현 설계

### 5.1 변경 범위

```
변경 파일:
  backend/service/workflow/nodes/base.py          — ExecutionContext에 auxiliary_model 추가
  backend/service/langgraph/agent_session.py      — _build_graph()에서 auxiliary 모델 생성
  backend/service/config/sub_config/general/api_config.py  — auxiliary_model 설정 추가

노드별 수정 (선택적):
  backend/service/workflow/nodes/memory/memory_inject_node.py
  backend/service/workflow/nodes/vtuber/vtuber_classify_node.py
  backend/service/workflow/nodes/memory/memory_reflect_node.py
  (+ 추가로 적용하고 싶은 노드들)
```

### 5.2 ExecutionContext 확장

```python
@dataclass
class ExecutionContext:
    model: Any                          # 메인 모델 (ClaudeCLIChatModel)
    session_id: str = "unknown"
    memory_manager: Any = None
    session_logger: Any = None
    context_guard: Any = None
    max_retries: int = 2
    model_name: Optional[str] = None

    # ── NEW: 보조 경량 모델 ──
    auxiliary_model: Any = None         # ChatAnthropic (Haiku 등)
    auxiliary_model_name: Optional[str] = None
```

### 5.3 보조 모델용 invoke 메서드

```python
async def auxiliary_invoke(self, messages: list, node_name: str) -> tuple:
    """경량 보조 모델로 LLM 호출. auxiliary_model이 없으면 메인 모델 fallback."""
    target = self.auxiliary_model or self.model
    # resilient_invoke와 동일한 retry 로직 적용
    ...

async def auxiliary_structured_invoke(self, messages, node_name, schema_cls, **kwargs) -> tuple:
    """경량 보조 모델로 구조화된 출력 호출."""
    target = self.auxiliary_model or self.model
    ...
```

**핵심 원칙**: `auxiliary_model`이 `None`이면 메인 모델로 자동 fallback.
→ 설정 안 하면 현재와 동일하게 작동 (zero regression risk).

### 5.4 Config 확장

```python
# api_config.py

AUXILIARY_MODEL_OPTIONS = [
    {"value": "", "label": "Same as main model (default)"},
    {"value": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5 (cheapest)"},
    {"value": "claude-sonnet-4-5-20250929", "label": "Claude Sonnet 4.5"},
    # ... 기존 MODEL_OPTIONS 재사용 가능
]

class APIConfig(BaseConfig):
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    auxiliary_model: str = ""              # NEW: 빈 문자열 = 메인 모델과 동일
    max_thinking_tokens: int = 31999
    ...
```

### 5.5 노드별 적용 방식

각 노드의 `execute()`에서:

```python
# 방식 1: 노드 코드에서 직접 auxiliary 사용
result, fb = await context.auxiliary_structured_invoke(messages, "memory_gate", MemoryGateOutput)

# 방식 2: 노드 config에 use_auxiliary_model 파라미터 추가 (유연)
use_aux = config.get("use_auxiliary_model", True)
if use_aux:
    result, fb = await context.auxiliary_structured_invoke(...)
else:
    result, fb = await context.resilient_structured_invoke(...)
```

**권장: 방식 1** (기본적으로 auxiliary 사용, `auxiliary_model=None`이면 자동 fallback).
UI 노출 불필요한 내부 최적화이므로 복잡한 토글보다 코드 레벨 결정이 적합.

### 5.6 `_build_graph()` 수정

```python
def _build_graph(self):
    # 보조 모델 생성 (Config에 설정된 경우)
    auxiliary = None
    aux_model_name = None
    try:
        from service.config.manager import ConfigManager
        api_cfg = ConfigManager().get_config("api")
        aux_name = api_cfg.get("auxiliary_model", "")
        api_key = api_cfg.get("anthropic_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")

        if aux_name and api_key:
            from langchain_anthropic import ChatAnthropic
            auxiliary = ChatAnthropic(
                model=aux_name,
                api_key=api_key,
                max_tokens=2048,
                timeout=30,
            )
            aux_model_name = aux_name
    except Exception:
        pass  # fallback to main model

    context = ExecutionContext(
        model=self._model,
        auxiliary_model=auxiliary,           # NEW
        auxiliary_model_name=aux_model_name, # NEW
        session_id=self._session_id,
        ...
    )
```

---

## 6. 비용 절감 효과 추정

### 6.1 모델별 가격 (2026-04 기준)

| 모델 | 입력 ($/1M tokens) | 출력 ($/1M tokens) |
|------|-------------------|--------------------|
| Claude Sonnet 4.6 | $3.00 | $15.00 |
| Claude Haiku 4.5 | $0.80 | $4.00 |
| **절감율** | **~73%** | **~73%** |

### 6.2 VTuber Thinking Trigger 경로 비용 절감

| 노드 | 현재 모델 | 보조 모델 적용 | 예상 토큰 | 현재 비용 | 최적화 비용 |
|------|----------|--------------|----------|----------|------------|
| memory_inject gate | Sonnet 4.6 | **Haiku 4.5** | ~200 | $0.0006 | $0.0002 |
| vtuber_classify | (fast-path) | - | 0 | $0 | $0 |
| vtuber_think | Sonnet 4.6 | Sonnet 4.6 (유지) | ~600 | $0.0050 | $0.0050 |
| memory_reflect | Sonnet 4.6 | **Haiku 4.5** | ~800 | $0.0070 | $0.0019 |
| **합계 (1회)** | | | | **$0.0126** | **$0.0071** |
| **트리거 100회/일** | | | | **$1.26** | **$0.71** |

**Thinking Trigger 경로: ~44% 비용 절감**

### 6.3 VTuber 일반 대화 경로 비용 절감

| 노드 | 현재 | 최적화 | 예상 토큰 | 현재 비용 | 최적화 비용 |
|------|------|--------|----------|----------|------------|
| memory_inject gate | Sonnet 4.6 | **Haiku 4.5** | ~200 | $0.0006 | $0.0002 |
| vtuber_classify | Sonnet 4.6 | **Haiku 4.5** | ~300 | $0.0015 | $0.0004 |
| vtuber_respond | Sonnet 4.6 | Sonnet 4.6 (유지) | ~800 | $0.0070 | $0.0070 |
| memory_reflect | Sonnet 4.6 | **Haiku 4.5** | ~800 | $0.0070 | $0.0019 |
| **합계 (1회)** | | | | **$0.0161** | **$0.0095** |

**일반 대화 경로: ~41% 비용 절감**

### 6.4 월간 예상 절감 (1 VTuber 세션, 하루 8시간 활동 가정)

| 항목 | 현재 | 최적화 | 절감 |
|------|------|--------|------|
| Thinking triggers (~160회/일) | $2.02/일 | $1.14/일 | -$0.88 |
| User chat (~50회/일) | $0.81/일 | $0.48/일 | -$0.33 |
| **일간 합계** | **$2.83** | **$1.62** | **-$1.21** |
| **월간 합계 (30일)** | **$84.90** | **$48.60** | **-$36.30** |

---

## 7. 적용 가능한 노드 최종 판정

| 노드 | 보조 모델 적용 | 이유 | 리스크 |
|------|--------------|------|--------|
| `memory_inject` (gate) | ✅ **적용** | 이진 분류 — Haiku로 충분 | 매우 낮음 |
| `vtuber_classify` | ✅ **적용** | 3-way 분류 — Haiku로 충분 | 낮음 |
| `memory_reflect` | ✅ **적용** | 구조화 추출 — Haiku 적합 | 낮음 (인사이트 품질 약간↓) |
| `vtuber_delegate` | ⚠️ **선택적** | 작업 지시 품질 영향 가능 | 중간 |
| `vtuber_think` | ⚠️ **선택적** | 사용자 표시됨 — 품질 관심 | 중간 |
| `vtuber_respond` | ❌ **미적용** | 핵심 사용자 응답 — 메인 모델 필수 | - |

---

## 8. 구현 순서

### Phase 1: 인프라 (기반 작업)

1. `ExecutionContext`에 `auxiliary_model`, `auxiliary_model_name` 필드 추가
2. `auxiliary_invoke()`, `auxiliary_structured_invoke()` 메서드 추가
3. `APIConfig`에 `auxiliary_model` 설정 필드 추가
4. `AgentSession._build_graph()`에서 `ChatAnthropic` 인스턴스 생성

### Phase 2: 핵심 노드 적용

5. `memory_inject_node.py` — gate 호출을 `auxiliary_structured_invoke`로 교체
6. `vtuber_classify_node.py` — 분류 호출을 `auxiliary_invoke`로 교체
7. `memory_reflect_node.py` — 인사이트 추출을 `auxiliary_structured_invoke`로 교체

### Phase 3: 선택적 노드 적용

8. `vtuber_delegate_node.py` — (선택) 작업 지시 변환에 적용
9. `vtuber_think_node.py` — (선택) 독백 생성에 적용

---

## 9. 리스크 및 완화

| 리스크 | 영향 | 완화 방안 |
|--------|------|----------|
| API 키 관리 이중화 | 낮음 | 동일한 `ANTHROPIC_API_KEY` 사용 (같은 계정) |
| Haiku 품질 부족 | 중간 | Config에서 모델 변경 가능, 빈 값이면 메인 모델 fallback |
| Rate limit 분리 | 낮음 | 같은 API 키 → 같은 rate limit pool |
| 구조화 출력 파싱 실패율 증가 | 중간 | `resilient_structured_invoke` retry + correction 로직 그대로 적용 |
| latency 변화 | 긍정적 | API 직접 호출이 CLI 서브프로세스보다 빠름 |

---

## 10. 핵심 코드 변경 요약

| 파일 | 변경 | LOC |
|------|------|-----|
| `workflow/nodes/base.py` | `auxiliary_model` 필드 + `auxiliary_invoke` 2개 메서드 | ~60 |
| `langgraph/agent_session.py` | `_build_graph()`에 `ChatAnthropic` 생성 | ~20 |
| `config/sub_config/general/api_config.py` | `auxiliary_model` 설정 필드 | ~15 |
| `workflow/nodes/memory/memory_inject_node.py` | gate 호출 교체 | ~3 |
| `workflow/nodes/vtuber/vtuber_classify_node.py` | 분류 호출 교체 | ~3 |
| `workflow/nodes/memory/memory_reflect_node.py` | reflect 호출 교체 | ~3 |
| **합계** | | **~104** |

**약 100줄의 코드 변경으로 ~40% 비용 절감 달성 가능.**
