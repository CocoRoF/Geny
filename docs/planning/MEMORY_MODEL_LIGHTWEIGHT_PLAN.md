# Memory Model 경량화 계획서

**작성일**: 2026-04-02
**범위**: Memory 로직 전용 경량 모델 도입 + VTuber 기본 모델 변경 검증

---

## 1. 현재 상황 분석

### 1.1 문제: 모든 노드가 동일한 고가 모델 사용

현재 시스템은 **하나의 `ExecutionContext.model`이 모든 워크플로우 노드에 동일하게 전달**된다.

```
AgentSession._build_graph()
    └─ ExecutionContext(model=self._model)   ← 단일 모델
            ├─ memory_inject.execute()        ← 메인 모델로 boolean 분류
            ├─ vtuber_classify.execute()      ← 메인 모델로 3-way 분류
            ├─ vtuber_respond.execute()       ← 메인 모델로 응답 생성 (적절)
            └─ memory_reflect.execute()       ← 메인 모델로 인사이트 추출
```

**핵심 파일**: `backend/service/workflow/nodes/base.py` → `ExecutionContext` 클래스

```python
@dataclass
class ExecutionContext:
    model: Any                      # ClaudeCLIChatModel — 유일한 모델
    session_id: str = "unknown"
    memory_manager: Any = None
    model_name: Optional[str] = None
    # ... auxiliary_model 필드 없음
```

### 1.2 메모리 관련 LLM 호출 지점 (2곳)

| 위치 | 파일 | 호출 방식 | 용도 | 난이도 |
|------|------|----------|------|--------|
| **Memory Gate** | `nodes/memory/memory_inject_node.py:167` | `context.resilient_structured_invoke()` | "메모리 검색 필요?" (bool) | ⭐ 매우 낮음 |
| **Memory Reflect** | `nodes/memory/memory_reflect_node.py:160` | `context.resilient_structured_invoke()` | 대화에서 인사이트 추출 (JSON) | ⭐⭐ 중간 |

#### Memory Gate — `_check_memory_needed()`

```python
# memory_inject_node.py:167-200
async def _check_memory_needed(self, input_text, context):
    prompt = _MEMORY_GATE_PROMPT.format(input=input_text[:500])
    messages = [HumanMessage(content=prompt)]
    parsed, cost_updates = await context.resilient_structured_invoke(
        messages, "memory_gate", MemoryGateOutput,
    )
    return parsed.needs_memory, cost_updates
```

- **입력**: 사용자 메시지 최대 500자 + 게이트 프롬프트 (~300자)
- **출력**: `{ needs_memory: bool, reasoning: str }` — **단순 이진 분류**
- **Haiku 적합도**: ★★★★★ — 가장 단순한 LLM 작업

#### Memory Reflect — `execute()`

```python
# memory_reflect_node.py:160-200
prompt = _REFLECT_PROMPT.format(input=input_text[:2000], output=output_text[:3000])
messages = [HumanMessage(content=prompt)]
parsed, cost_updates = await context.resilient_structured_invoke(
    messages, "memory_reflect", MemoryReflectOutput,
)
```

- **입력**: user input 2000자 + execution output 3000자 + 프롬프트
- **출력**: `{ learned: [{ title, content, category, tags, importance }], should_save: bool }`
- **Haiku 적합도**: ★★★★☆ — 구조화된 정보 추출, Haiku로 대부분 충분

### 1.3 메모리 비-LLM 작업 (영향 없음)

아래 작업들은 LLM을 사용하지 않으므로 모델 변경의 영향을 받지 않는다:

| 작업 | 방식 | 비용 |
|------|------|------|
| STM 기록/조회 | JSONL 파일 I/O | 0 |
| LTM MEMORY.md 로드 | 파일 읽기 | 0 |
| FAISS 벡터 검색 | 별도 임베딩 API (OpenAI) | 별도 과금 |
| 키워드 검색 | 인메모리 문자열 매칭 | 0 |
| 노트 쓰기/읽기 | 마크다운 파일 I/O | 0 |

### 1.4 VTuber 기본 모델 변경 상태

이전 작업에서 `vtuber_default_model: str = "claude-haiku-4-5-20251001"`를 추가했다.
VTuber 세션이 기본적으로 Haiku 4.5를 사용하게 됨으로써 **VTuber 메인 응답(vtuber_respond)도 Haiku로 실행**된다.

VTuber는 일상적 대화를 담당하고 복잡한 작업은 CLI 세션에 위임하므로,
메인 응답에도 Haiku를 사용하는 것이 비용 대비 적절하다.

---

## 2. 문제점 정리

### 2.1 Memory 로직에 별도 경량 모델 미지원

| 문제 | 영향 |
|------|------|
| Memory Gate가 메인 모델로 실행됨 | boolean 분류에 고가 모델 낭비 |
| Memory Reflect가 메인 모델로 실행됨 | 인사이트 추출에 불필요한 비용 |
| CLI 세션의 메모리도 CLI 메인 모델(Sonnet)로 실행됨 | **CLI Memory가 Sonnet으로 동작 → 여기가 핵심 절감 포인트** |
| Memory Model을 독립적으로 설정할 수 없음 | 유연성 부족 |

### 2.2 핵심 절감 포인트: CLI 세션의 Memory 비용

VTuber 세션은 이미 Haiku 기본값으로 변경되어 메모리 비용도 자동으로 하락한다.
하지만 **CLI 세션은 `anthropic_model` (Sonnet 4.6)**을 사용하므로,
CLI의 Memory Gate / Memory Reflect도 Sonnet 4.6으로 실행된다.

```
CLI 세션 (Sonnet 4.6):
  ├─ memory_inject (gate)   → Sonnet 4.6  ← 과잉 (boolean 분류)
  ├─ main execution         → Sonnet 4.6  ← 적절 (코드 작업)
  └─ memory_reflect         → Sonnet 4.6  ← 과잉 (인사이트 추출)
```

독립적인 `memory_model` 설정으로 CLI 세션의 메모리 비용을 절감할 수 있다.

### 2.3 현재 인프라 상태

| 항목 | 상태 |
|------|------|
| `langchain-anthropic>=0.3.0` (ChatAnthropic) | ✅ 의존성에 포함 (미사용) |
| `ANTHROPIC_API_KEY` 환경변수/Config | ✅ 이미 관리됨 |
| `ExecutionContext` 패턴 | ✅ 의존성 주입으로 확장 용이 |
| Config 시스템 (`register_config`, `ConfigField`) | ✅ 새 필드 추가 용이 |
| 기존 분석 문서 (`docs/optimizing_model.md`) | ✅ auxiliary_model 설계 존재 |

---

## 3. 개선 설계

### 3.1 용어 정의 변경

기존 `optimizing_model.md`에서는 `auxiliary_model`이라는 범용 이름을 사용했다.
이번 작업에서는 **Memory 전용 경량 모델**에 초점을 맞추므로 `memory_model`로 명명한다.

> 이후 Phase에서 `vtuber_classify` 등에도 경량 모델을 적용할 경우,
> 더 범용적인 `auxiliary_model`로 확장할 수 있다.

### 3.2 전체 아키텍처 (개선 후)

```
AgentSession._build_graph()
    │
    ├─ self._model (ClaudeCLIChatModel)       ← 메인 모델 (세션별 설정)
    │
    └─ ChatAnthropic(memory_model)            ← 메모리 전용 경량 모델 (전역 설정)
            │
            └─ ExecutionContext(
                    model=self._model,
                    memory_model=ChatAnthropic(...),    ← NEW
                    memory_model_name="claude-haiku-4-5-20251001",
               )
```

**적용 범위**:

| 노드 | 사용 모델 (개선 후) |
|------|-------------------|
| `memory_inject` (gate) | `context.memory_model` (Haiku) |
| `memory_reflect` | `context.memory_model` (Haiku) |
| `vtuber_classify` | `context.model` (메인 — 추후 경량화 가능) |
| `vtuber_respond` | `context.model` (메인) |
| `vtuber_think` | `context.model` (메인) |
| `vtuber_delegate` | `context.model` (메인) |

### 3.3 Config 설계

`APIConfig`에 `memory_model` 필드를 추가한다.

```python
# api_config.py 변경
@dataclass
class APIConfig(BaseConfig):
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"          # CLI 기본
    vtuber_default_model: str = "claude-haiku-4-5-20251001"  # VTuber 기본
    memory_model: str = "claude-haiku-4-5-20251001"     # NEW: 메모리 전용
    max_thinking_tokens: int = 31999
    skip_permissions: bool = True
    app_port: int = 8000
```

**설정 UI 동작**:
- 빈 값 (`""`) → 메인 모델과 동일하게 동작 (fallback)
- `"claude-haiku-4-5-20251001"` (기본값) → Haiku로 메모리 처리
- 사용자가 원하는 모델로 변경 가능 (SELECT 드롭다운)

### 3.4 ExecutionContext 확장

```python
# workflow/nodes/base.py 변경

@dataclass
class ExecutionContext:
    model: Any                              # 메인 모델 (ClaudeCLIChatModel)
    session_id: str = "unknown"
    memory_manager: Any = None
    session_logger: Any = None
    context_guard: Any = None
    max_retries: int = 2
    model_name: Optional[str] = None

    # ── NEW: 메모리 전용 경량 모델 ──
    memory_model: Any = None                # ChatAnthropic (Haiku 등)
    memory_model_name: Optional[str] = None
```

### 3.5 메모리 전용 invoke 메서드

`ExecutionContext`에 `memory_invoke` / `memory_structured_invoke` 메서드를 추가한다.
`memory_model`이 설정되지 않으면 기존 `resilient_invoke`로 자동 fallback.

```python
async def memory_invoke(self, messages, node_name) -> tuple:
    """Memory 전용 경량 모델로 호출. 없으면 메인 모델 fallback."""
    if self.memory_model is None:
        return await self.resilient_invoke(messages, node_name)

    # ChatAnthropic 직접 호출 + retry 로직
    ...

async def memory_structured_invoke(self, messages, node_name, schema_cls, **kwargs) -> tuple:
    """Memory 전용 경량 모델로 구조화된 출력 호출."""
    if self.memory_model is None:
        return await self.resilient_structured_invoke(messages, node_name, schema_cls, **kwargs)

    # ChatAnthropic 구조화 호출 + retry 로직
    ...
```

**핵심 원칙**: `memory_model=None`이면 현재와 완전히 동일하게 동작 → **zero regression risk**.

### 3.6 ChatAnthropic 인스턴스 생성

`AgentSession._build_graph()`에서 `ChatAnthropic`을 생성하여 `ExecutionContext`에 전달한다.

```python
# agent_session.py — _build_graph() 내부

memory_chat_model = None
memory_model_name = None

try:
    from service.config.manager import get_config_manager
    from service.config.sub_config.general.api_config import APIConfig

    api_cfg = get_config_manager().load_config(APIConfig)
    mem_model = api_cfg.memory_model
    api_key = api_cfg.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    if mem_model and api_key:
        from langchain_anthropic import ChatAnthropic
        memory_chat_model = ChatAnthropic(
            model=mem_model,
            api_key=api_key,
            max_tokens=2048,
            timeout=30,
        )
        memory_model_name = mem_model
except Exception as e:
    logger.warning(f"[{self._session_id}] Failed to create memory model: {e}")

context = ExecutionContext(
    model=self._model,
    memory_model=memory_chat_model,           # NEW
    memory_model_name=memory_model_name,      # NEW
    session_id=self._session_id,
    memory_manager=self._memory_manager,
    session_logger=self._get_logger(),
    max_retries=2,
    model_name=self._model_name,
)
```

### 3.7 노드 수정 (최소 변경)

#### memory_inject_node.py — Gate 호출

```diff
  # _check_memory_needed() 내부
- parsed, cost_updates = await context.resilient_structured_invoke(
+ parsed, cost_updates = await context.memory_structured_invoke(
      messages, "memory_gate", MemoryGateOutput,
  )
```

#### memory_reflect_node.py — Reflect 호출

```diff
  # execute() 내부
- parsed, cost_updates = await context.resilient_structured_invoke(
+ parsed, cost_updates = await context.memory_structured_invoke(
      messages, "memory_reflect", MemoryReflectOutput,
  )
```

**각 노드 변경량: 1줄** — 메서드 이름만 교체.

---

## 4. ChatAnthropic vs ClaudeCLIChatModel 비교

| 속성 | ChatAnthropic (직접 API) | ClaudeCLIChatModel (CLI 래퍼) |
|------|------------------------|------------------------------|
| 호출 방식 | HTTP API 직접 호출 | `node.exe cli.js` 서브프로세스 |
| 스폰 오버헤드 | 0ms | ~1-2초 |
| 응답 지연 | 0.5-2초 (API만) | 5-15초 (프로세스 + API) |
| 상태 유지 | Stateless (매 호출 독립) | Stateful (대화 기록 유지) |
| 도구 실행 | 불가 | Claude CLI 도구 사용 가능 |
| 메모리 사용 | ~0 (HTTP 클라이언트) | ~200MB (Node.js 프로세스) |
| 적합 용도 | 단발 분류/추출 | 대화형 에이전트 |

**Memory 작업은 stateless 단발 호출** → ChatAnthropic이 최적.

---

## 5. 비용 절감 효과 추정

### 5.1 모델 가격표 (2026-04 기준)

| 모델 | 입력 ($/1M tokens) | 출력 ($/1M tokens) |
|------|-------------------|--------------------|
| Claude Sonnet 4.6 | $3.00 | $15.00 |
| Claude Haiku 4.5 | $0.80 | $4.00 |
| **절감율** | **~73%** | **~73%** |

### 5.2 CLI 세션 Memory 비용 절감 (핵심 효과)

CLI 세션은 Sonnet 4.6을 사용하므로 Memory 분리 효과가 크다:

| 호출 | 현재 (Sonnet) | 개선 후 (Haiku) | 예상 토큰 |
|------|-------------|----------------|----------|
| Memory Gate | $0.0006/회 | $0.0002/회 | ~250 |
| Memory Reflect | $0.0070/회 | $0.0019/회 | ~800 |
| **합계 (1회)** | **$0.0076** | **$0.0021** | |
| **절감율** | | **~72%** | |

### 5.3 VTuber 세션 Memory 비용 (이미 최적화됨)

VTuber 기본 모델이 이미 Haiku이므로, `memory_model`도 Haiku인 경우 **추가 절감 없음**.
다만 VTuber 모델을 Sonnet으로 업그레이드하더라도 Memory는 Haiku로 유지된다는 **안전장치** 역할.

### 5.4 월간 예상 절감 (CLI 세션 기준)

| 항목 | CLI Memory 호출 수/일 | 현재 비용/일 | 개선 비용/일 |
|------|----------------------|------------|------------|
| Memory Gate | ~200회 | $0.12 | $0.04 |
| Memory Reflect | ~100회 | $0.70 | $0.19 |
| **일간 합계** | | **$0.82** | **$0.23** |
| **월간 합계** | | **$24.60** | **$6.90** |
| **월간 절감** | | | **-$17.70** |

### 5.5 추가 이점: 응답 속도 개선

| 항목 | ClaudeCLIChatModel | ChatAnthropic |
|------|-------------------|---------------|
| Memory Gate 응답 | 5-15초 | **0.5-2초** |
| Memory Reflect 응답 | 7-20초 | **1-3초** |

CLI 서브프로세스 스폰 오버헤드가 없으므로 **메모리 처리 속도가 3-10배 향상**된다.

---

## 6. 구현 계획

### 6.1 변경 파일 목록

| # | 파일 | 변경 내용 | LOC |
|---|------|----------|-----|
| 1 | `service/config/sub_config/general/api_config.py` | `memory_model` 필드 + Config UI | ~25 |
| 2 | `service/workflow/nodes/base.py` | `memory_model` 필드 + `memory_invoke` 2개 메서드 | ~80 |
| 3 | `service/langgraph/agent_session.py` | `_build_graph()`에서 ChatAnthropic 생성 | ~25 |
| 4 | `service/workflow/nodes/memory/memory_inject_node.py` | gate 호출 메서드 교체 | ~1 |
| 5 | `service/workflow/nodes/memory/memory_reflect_node.py` | reflect 호출 메서드 교체 | ~1 |
| | **합계** | | **~132** |

### 6.2 구현 순서

#### Step 1: Config 추가

`api_config.py`에 `memory_model` 필드를 추가한다.
- 기본값: `"claude-haiku-4-5-20251001"`
- 환경변수: `MEMORY_MODEL`
- Config UI: SELECT 드롭다운 (MODEL_OPTIONS 재사용 + 빈 값 옵션)
- i18n: "Memory Model" / "메모리 전용 모델 — 메모리 게이트, 인사이트 추출에 사용"

#### Step 2: ExecutionContext 확장

`base.py`의 `ExecutionContext`에:
- `memory_model: Any = None` 필드 추가
- `memory_model_name: Optional[str] = None` 필드 추가
- `memory_invoke()` 메서드 추가 — ChatAnthropic 호출 + retry
- `memory_structured_invoke()` 메서드 추가 — 구조화 출력 + retry

핵심: `memory_model is None`이면 기존 `resilient_invoke/resilient_structured_invoke`로 fallback.

#### Step 3: AgentSession 모델 생성

`agent_session.py`의 `_build_graph()`에서:
- `APIConfig.memory_model` 값 로드
- `ChatAnthropic` 인스턴스 생성 (api_key는 기존 `ANTHROPIC_API_KEY` 재사용)
- `ExecutionContext`에 `memory_model`, `memory_model_name` 전달

#### Step 4: Memory 노드 적용

- `memory_inject_node.py`: `context.resilient_structured_invoke` → `context.memory_structured_invoke`
- `memory_reflect_node.py`: `context.resilient_structured_invoke` → `context.memory_structured_invoke`

### 6.3 ChatAnthropic 응답 → cost_usd 변환

현재 `resilient_invoke`는 `response.additional_kwargs.get("cost_usd")` 로 비용을 추출한다.
`ChatAnthropic`의 응답 형식에서도 비용 정보를 추출할 수 있도록 처리한다.

```python
# ChatAnthropic 응답에서 usage 추출
response = await self.memory_model.ainvoke(messages)
usage = response.usage_metadata  # langchain-anthropic이 제공
input_tokens = usage.get("input_tokens", 0)
output_tokens = usage.get("output_tokens", 0)
# Haiku 4.5 가격으로 비용 계산
cost_usd = (input_tokens * 0.80 + output_tokens * 4.00) / 1_000_000
```

또는 `response.response_metadata`에서 Anthropic API 응답의 usage 필드를 직접 읽을 수 있다.

---

## 7. 리스크 및 완화

| 리스크 | 영향 | 완화 방안 |
|--------|------|----------|
| Haiku의 구조화 출력 파싱 실패율 | 중간 | `memory_structured_invoke`에 기존 retry + correction 로직 그대로 적용 |
| Memory Reflect 인사이트 품질 하락 | 낮음 | 프롬프트가 명확한 JSON 스키마를 제공하므로 Haiku도 충분 |
| API 키가 없을 때 fallback | 없음 | `memory_model=None` → 기존 메인 모델로 fallback (zero regression) |
| Rate limit 공유 | 낮음 | 같은 API 키 → 같은 rate limit pool이지만, 메모리 호출은 빈도가 낮음 |
| ChatAnthropic 임포트 실패 | 낮음 | try/except로 감싸서 fallback |

---

## 8. 향후 확장 가능성

이번 작업으로 `memory_model` 인프라가 갖춰지면, 같은 패턴으로 다른 경량 작업에도 적용 가능하다:

| 노드 | 현재 | 향후 가능 | 비고 |
|------|------|----------|------|
| `vtuber_classify` | 메인 모델 | `auxiliary_model` | 3-way 분류에 Haiku 충분 |
| `vtuber_think` | 메인 모델 | 선택적 `auxiliary_model` | 품질 vs 비용 트레이드오프 |
| `context_guard` | 메인 모델 | `auxiliary_model` | 토큰 길이 판단에 Haiku 충분 |

이번 Phase에서는 **Memory 로직에만 집중**하고, `auxiliary_model`로의 범용 확장은 추후 논의한다.

---

## 9. 요약

| 항목 | 내용 |
|------|------|
| **목표** | Memory 로직(Gate + Reflect)에 전용 경량 모델 사용 |
| **방식** | `ChatAnthropic` 직접 API (서브프로세스 불필요) |
| **Config 필드** | `memory_model` (기본값: `claude-haiku-4-5-20251001`) |
| **변경 파일** | 5개 파일, ~132줄 |
| **핵심 효과** | CLI 세션 Memory 비용 ~72% 절감, 응답 속도 3-10배 향상 |
| **Regression 위험** | Zero — `memory_model` 미설정 시 기존과 동일 동작 |
