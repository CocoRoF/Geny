# Phase 2: geny-executor Stage Strategy 기반 완성 계획 v2

> Direction: Option B — 워크플로우 노드 그래프 폐기, Stage Strategy 레벨 커스터마이징
> Date: 2026-04-14

---

## 1. 핵심 원칙

워크플로우 그래프를 폐기하고 geny-executor 16-stage Pipeline의
**Strategy 교체**만으로 동일한 기능을 달성한다.

기존 Geny가 **실제로 사용한** 패턴 2가지에 집중한다:
1. **Worker**: `easy / not_easy` 이진 분류
2. **VTuber**: `direct_response / delegate_to_cli / thinking` 행동 분류

---

## 2. 실제 사용 패턴 분석

### 2.1 Worker (optimized-autonomous) — 이진 분류

```
입력 → [relevance_gate: 관련 있는가?]
         ├─ skip → END
         └─ continue → [adaptive_classify: easy or not_easy?]
                          ├─ easy → 1회 LLM 응답 → END
                          └─ not_easy → memory_inject → TODO 생성
                                        → batch 실행 → memory_reflect → END
```

핵심:
- **easy**: 단답 1회. 도구 불필요. 토큰 최소화.
- **not_easy**: 메모리 주입 → TODO 분해 → 배치 실행 → 메모리 기록. 다회전 루프.
- 3단계(medium/hard) 분류는 사용하지 않았음. 이진 분류가 실전에서 더 효과적.

### 2.2 VTuber — 행동 분류

```
입력 → memory_inject → [vtuber_classify: 무엇을 할 것인가?]
         ├─ direct_response → 직접 답변 생성
         ├─ delegate_to_cli → CLI 에이전트에 작업 위임
         └─ thinking → 자발적 사고 (아이디어 발전)
         └→ memory_reflect → END
```

핵심:
- 난이도가 아니라 **행동 유형** 분류
- delegate는 외부 에이전트 호출 (sub-pipeline)
- thinking은 사용자 요청 없이도 자발적으로 사고

---

## 3. Stage Strategy 매핑

### 3.1 Worker 이진 분류 → s12_evaluate 전략

**새 전략: `BinaryClassifyEvaluation`**

```python
class BinaryClassifyEvaluation(EvaluationStrategy):
    """easy/not_easy 이진 분류 기반 적응형 평가.
    
    첫 턴: LLM 응답에서 난이도를 추론하여 분류
    - easy: 도구 호출 없이 텍스트만 → 즉시 complete
    - not_easy: 도구 호출 또는 [CONTINUE] 시그널 → 루프 계속
    
    이후 턴: not_easy 경로에서의 완료 판단
    - [COMPLETE] 시그널 → complete
    - max_turns 초과 → complete (강제 종료)
    """
```

분류 기준 (프롬프트 의존이 아닌, **응답 패턴 기반**):
- `pending_tool_calls`가 있으면 → not_easy (도구가 필요한 작업)
- `completion_signal == "complete"`이면 → easy (1회 완료)
- 첫 턴에서 도구 없이 완료 시그널 → easy
- 그 외 → not_easy

easy일 때:
- `state.max_iterations = 1` (추가 턴 차단)
- 즉시 `decision = "complete"`

not_easy일 때:
- `state.max_iterations` 유지 (기본 30)
- TODO 분해와 반복 실행은 LLM이 시스템 프롬프트 지시에 따라 자율 수행
- `decision = "continue"` until `[COMPLETE]`

### 3.2 VTuber 행동 분류 → s09_parse 시그널 + s11_agent

**VTuber 분류는 시그널 기반으로 처리:**

```
시스템 프롬프트:
  "응답 시 다음 시그널을 포함하라:
   - 직접 답변: [COMPLETE]
   - CLI에 위임: [DELEGATE: cli]  
   - 자발적 사고: [CONTINUE]"

s09_parse: CompletionSignalDetector가 시그널 감지
  → COMPLETE: 직접 답변 완료
  → DELEGATE: s11_agent의 DelegateOrchestrator가 CLI 실행
  → CONTINUE: 사고 루프 계속
```

기존 인프라로 충분:
- `s09_parse`의 `RegexDetector` → `[DELEGATE: cli]` 감지
- `s11_agent`의 `DelegateOrchestrator` → sub-pipeline 호출
- `s13_loop`의 `StandardLoopController` → max_turns 존중

### 3.3 시스템 프롬프트가 노드를 대체

워크플로우 노드가 하던 일을 **시스템 프롬프트**로 지시:

```python
WORKER_ADAPTIVE_PROMPT = """
## Execution Strategy

Classify the task and act accordingly:

**Easy tasks** (factual Q&A, simple lookups, greetings):
Answer directly in one response. Do not use tools unless absolutely necessary.

**Complex tasks** (coding, research, multi-step work):
1. Plan: Decompose into clear steps
2. Execute: Use tools to complete each step  
3. Verify: Check your work
4. Signal [COMPLETE] when done, [CONTINUE] if more steps remain
"""

VTUBER_CLASSIFY_PROMPT = """
## Response Strategy

Choose your action:
- **Direct response**: Answer conversational questions yourself. Signal [COMPLETE].
- **Delegate to CLI**: For coding/file/system tasks, signal [DELEGATE: cli] with task description.
- **Self-thinking**: For creative/analytical topics, think deeply. Signal [CONTINUE] to keep thinking.
"""
```

---

## 4. geny-executor 변경

### 4.1 BinaryClassifyEvaluation (신규)

위치: `s12_evaluate/artifact/adaptive/`

```python
@dataclass
class BinaryClassifyConfig:
    """이진 분류 설정."""
    easy_max_turns: int = 1        # easy 판정 시 최대 턴
    not_easy_max_turns: int = 30   # not_easy의 기본 최대 턴
    classify_on_first_turn: bool = True  # 첫 턴에서 자동 분류

class BinaryClassifyEvaluation(EvaluationStrategy):
    
    def __init__(self, config: Optional[BinaryClassifyConfig] = None):
        self.config = config or BinaryClassifyConfig()
    
    async def evaluate(self, state: PipelineState) -> EvaluationResult:
        # 첫 턴: 자동 분류
        if state.iteration == 1 and self.config.classify_on_first_turn:
            is_easy = self._classify(state)
            state.metadata["task_class"] = "easy" if is_easy else "not_easy"
            if is_easy:
                state.max_iterations = self.config.easy_max_turns
                return EvaluationResult(decision="complete", score=1.0)
            else:
                state.max_iterations = self.config.not_easy_max_turns
        
        # 이후 턴: 시그널 기반 판단
        if state.completion_signal == "complete":
            return EvaluationResult(decision="complete", score=1.0)
        
        if state.pending_tool_calls:
            return EvaluationResult(decision="continue")
        
        # 시그널 없이 텍스트만 → complete로 간주
        if state.final_text and not state.pending_tool_calls:
            return EvaluationResult(decision="complete", score=0.8)
        
        return EvaluationResult(decision="continue")
    
    def _classify(self, state: PipelineState) -> bool:
        """첫 턴 응답 패턴으로 easy/not_easy 분류."""
        # 도구 호출이 있으면 not_easy
        if state.pending_tool_calls:
            return False
        # [CONTINUE] 시그널이면 not_easy
        if state.completion_signal == "continue":
            return False
        # 짧은 텍스트 + 완료 시그널 → easy
        return True
```

### 4.2 GenyPresets.worker_adaptive() (신규)

```python
@staticmethod
def worker_adaptive(
    api_key: str,
    memory_manager=None,
    model: str = "claude-sonnet-4-20250514",
    system_prompt: str = "",
    tools: Optional[ToolRegistry] = None,
    max_turns: int = 30,
    easy_max_turns: int = 1,
    curated_knowledge_manager=None,
    llm_reflect=None,
) -> Pipeline:
    """이진 분류 적응형 에이전트.
    
    easy: 1턴 직답, not_easy: TODO 분해 + 다회전 도구 실행.
    기존 template-optimized-autonomous의 철학을 Pipeline으로 계승.
    """
    classify_config = BinaryClassifyConfig(
        easy_max_turns=easy_max_turns,
        not_easy_max_turns=max_turns,
    )
    
    return (
        PipelineBuilder(f"geny-adaptive", api_key=api_key)
        .with_model(model=model)
        .with_context(retriever=GenyMemoryRetriever(memory_manager, ...))
        .with_system(prompt=system_prompt + WORKER_ADAPTIVE_PROMPT)
        .with_guard()
        .with_cache(strategy="aggressive")
        .with_tools(registry=tools)
        .with_evaluate(strategy=BinaryClassifyEvaluation(classify_config))
        .with_loop(max_turns=max_turns)
        .with_memory(
            strategy=GenyMemoryStrategy(memory_manager, llm_reflect=llm_reflect),
            persistence=GenyPersistence(memory_manager),
        )
        .build()
    )
```

### 4.3 GenyPresets.vtuber() 개선

현재 vtuber preset은 이미 존재. 시스템 프롬프트에 행동 분류 지시를 추가하고,
`DelegateOrchestrator`를 연결하면 기존 vtuber_classify 노드를 대체.

---

## 5. Geny 백엔드 변경

### 5.1 _build_pipeline() 수정

```python
if is_vtuber:
    self._pipeline = GenyPresets.vtuber(...)       # 기존 유지
elif is_simple:
    self._pipeline = GenyPresets.worker_easy(...)   # 기존 유지
else:
    # autonomous, optimized, ultra-light 전부 → worker_adaptive
    self._pipeline = GenyPresets.worker_adaptive(
        api_key=api_key,
        memory_manager=self._memory_manager,
        model=model,
        system_prompt=system_prompt,
        tools=tools,
        max_turns=max_turns,
        curated_knowledge_manager=curated_km,
        llm_reflect=llm_reflect,
    )
```

### 5.2 ToolContext session_id 자동 주입

```python
# tool_bridge.py _GenyToolAdapter.execute()
async def execute(self, input: Dict[str, Any], context: Any = None) -> Any:
    if context and hasattr(context, "session_id") and context.session_id:
        input.setdefault("session_id", context.session_id)
    # ... 기존 로직
```

### 5.3 MCP 외부 서버 연동

_build_pipeline()에서 MCP 서버를 Pipeline ToolRegistry에 직접 등록.

### 5.4 Dead code 정리

| 대상 | 줄수 | 조치 |
|------|------|------|
| CLI: process_manager, cli_discovery, stream_parser, claude_cli_model | ~1,600 | deprecated/ |
| MCP Proxy: _proxy_mcp_server, _mcp_server, internal_tool_controller | ~500 | deprecated/ |
| Workflow: nodes/ (30+), workflow_executor, workflow_state, autonomous_graph | ~4,600 | deprecated/ |
| **Total** | **~6,700** | |

---

## 6. 구현 순서

```
Step 1: geny-executor — BinaryClassifyEvaluation 전략 추가
  └── s12_evaluate/artifact/adaptive/ 디렉토리
  └── BinaryClassifyConfig + BinaryClassifyEvaluation
  └── 테스트 추가

Step 2: geny-executor — GenyPresets.worker_adaptive() 추가
  └── memory/presets.py 확장
  └── WORKER_ADAPTIVE_PROMPT 시스템 프롬프트
  └── 버전 업 → PyPI 배포

Step 3: Geny — _build_pipeline() + tool_bridge 수정
  └── worker_full → worker_adaptive 전환
  └── session_id 자동 주입
  └── MCP 외부 서버 연동

Step 4: Geny — Dead code deprecated/ 이동 + 레거시 정리
  └── agent_session.py 레거시 import/필드/메서드 제거
  └── ~6,700줄 deprecated/ 이동
```

---

## 7. 최종 아키텍처

```
Preset Selection:
  vtuber → GenyPresets.vtuber()
    └── 시그널: [COMPLETE] / [DELEGATE: cli] / [CONTINUE]
    └── s11_agent: DelegateOrchestrator → CLI sub-pipeline

  simple → GenyPresets.worker_easy()
    └── 1턴 직답, 도구/루프 없음

  *      → GenyPresets.worker_adaptive()        ← NEW
    └── s12: BinaryClassifyEvaluation
    └── 첫 턴: easy(1턴) vs not_easy(30턴) 자동 분류
    └── not_easy: 시스템 프롬프트로 TODO 분해 + 도구 실행 지시

Pipeline 16-stage:
  s01 Input
  s02 Context (GenyMemoryRetriever)
  s03 System  (+ WORKER_ADAPTIVE_PROMPT)
  s04 Guard   (budget + iteration)
  s05 Cache   (aggressive)
  s06 API     (Anthropic direct)
  s07 Token
  s08 Think
  s09 Parse   (completion signals + [DELEGATE])
  s10 Tool    (41종: 6 빌트인 + 35 Geny)
  s11 Agent   (DelegateOrchestrator)
  s12 Evaluate (BinaryClassifyEvaluation)     ← NEW
  s13 Loop    (StandardLoopController)
  s14 Emit
  s15 Memory  (GenyMemoryStrategy)
  s16 Yield

폐기:
  ◆ WorkflowDefinition 노드 그래프 (28+ 노드)
  ◆ 30+ 워크플로우 노드 구현체
  ◆ LangGraph CompiledStateGraph
  ◆ ClaudeProcess CLI subprocess
  ◆ Proxy MCP 서버
```
