# Sudo Compiler — Workflow Dry-Run Testing

> 워크플로우 그래프를 실제 LLM 호출 없이 검증하는 테스트 컴파일러.

## 개요

Sudo Compiler는 `WorkflowExecutor`가 컴파일하는 LangGraph StateGraph를 실제 Claude CLI 호출 없이 실행하는 **dry-run 테스트 도구**입니다.

모든 LLM 호출(`resilient_invoke`, `resilient_structured_invoke`)은 `SudoModel`이 자동으로 대체하며, 각 노드가 요구하는 응답 형식(structured output schema)을 자동 감지하여 유효한 mock 값을 반환합니다.

## 아키텍처

```
┌──────────────────────────────────────────────────┐
│                 SudoCompiler                      │
│                                                   │
│  ┌─────────────┐   ┌──────────────────────────┐  │
│  │  SudoModel   │   │  WorkflowExecutor        │  │
│  │  (mock LLM)  │──▶│  (real graph compiler)   │  │
│  └─────────────┘   └──────────────────────────┘  │
│         │                       │                  │
│         ▼                       ▼                  │
│  ┌─────────────┐   ┌──────────────────────────┐  │
│  │  AIMessage   │   │  LangGraph StateGraph     │  │
│  │  (fake cost) │   │  (real nodes, real edges) │  │
│  └─────────────┘   └──────────────────────────┘  │
│                           │                        │
│                           ▼                        │
│                  ┌─────────────────┐               │
│                  │  SudoRunReport   │               │
│                  │  (full telemetry)│               │
│                  └─────────────────┘               │
└──────────────────────────────────────────────────┘
```

## 핵심 컴포넌트

### `SudoModel` (`model.py`)

실제 `ClaudeCLIChatModel`을 대체하는 mock 모델:

- **자동 스키마 감지**: 노드가 structured output을 기대하는 경우 (ClassifyOutput, ReviewOutput 등) 유효한 JSON을 자동 생성
- **결정론적 실행**: seed 기반 `random.Random`으로 재현 가능한 결과
- **오버라이드 지원**: 특정 노드의 응답을 강제 지정 가능 (예: classify → "hard" 고정)
- **비용 시뮬레이션**: mock `cost_usd`를 `AIMessage.additional_kwargs`에 포함

지원하는 structured output 스키마:
| 스키마 | 노드 | 생성 항목 |
|--------|------|-----------|
| `ClassifyOutput` | classify, adaptive_classify | classification, confidence, reasoning |
| `ReviewOutput` | review | verdict, feedback, issues |
| `MemoryGateOutput` | memory_inject (gate) | needs_memory, reasoning |
| `RelevanceOutput` | relevance_gate | relevant, reasoning |
| `CreateTodosOutput` | create_todos | todos[] (2~4개 랜덤) |
| `FinalReviewOutput` | final_review | overall_quality, completed_summary |

### `SudoCompiler` (`compiler.py`)

워크플로우 컴파일 및 실행 엔진:

- **`run(input_text)`**: 단일 실행, `SudoRunReport` 반환
- **`run_all_paths(workflow, input_text)`**: classify 노드의 모든 카테고리를 자동 감지하여 각 경로별 실행
- **`validate(workflow, input_text)`**: 빠른 pass/fail 검증

### `SudoRunReport` (`report.py`)

실행 결과 리포트:

- 노드 실행 순서 및 소요 시간
- 라우팅 결정 (조건부 엣지 선택)
- 최종 상태 스냅샷
- LLM 호출 로그
- `.summary()` — 사람이 읽을 수 있는 텍스트 리포트
- `.to_json()` — JSON 직렬화

### `runner.py` (CLI)

커맨드라인 실행 도구:

```bash
# 특정 워크플로우 단일 실행
python -m service.workflow.compiler.runner -w template-autonomous

# 모든 경로(easy/medium/hard) 자동 테스트
python -m service.workflow.compiler.runner -w template-autonomous --all-paths

# hard 경로 강제 실행
python -m service.workflow.compiler.runner -w template-autonomous -o classify=hard

# 전체 워크플로우 검증
python -m service.workflow.compiler.runner --validate

# JSON 출력
python -m service.workflow.compiler.runner -w template-simple --json

# 사용 가능한 워크플로우 목록
python -m service.workflow.compiler.runner --list
```

## 사용 예제

### Python API

```python
from service.workflow.compiler import SudoCompiler
from service.workflow.workflow_model import WorkflowDefinition

# 워크플로우 로드
with open("workflows/template-autonomous.json") as f:
    workflow = WorkflowDefinition(**json.load(f))

# 단일 실행
compiler = SudoCompiler(workflow)
report = await compiler.run("Python에 대해 설명해줘")
print(report.summary())

# 특정 경로 강제
compiler = SudoCompiler(workflow, overrides={"classify": "hard"})
report = await compiler.run("복잡한 멀티스텝 작업")
print(report.path_string)  # "Memory Inject → Relevance Gate → Guard (Classify) → ..."

# 전체 경로 검증
reports = await SudoCompiler.run_all_paths(workflow, "테스트 입력")
for r in reports:
    status = "✅" if r.success else "❌"
    print(f"{status} {r.path_string}")

# 빠른 검증
result = await SudoCompiler.validate(workflow, "테스트")
print(f"Valid: {result['valid']}, Paths: {result['total_paths']}")
```

### 리포트 출력 예시

```
═══ Sudo Run Report: Autonomous Difficulty-Based ═══
Status:           ✅ SUCCESS
Input:            Python에 대해 설명해줘
Duration:         12ms
Nodes executed:   8
Unique nodes:     8
LLM calls:        4
Mock cost:        $0.024531
Path:             Memory Inject → Relevance Gate → Guard (Classify) → Classify → Guard (Direct) → Direct Answer → Post (Direct) → END

─── Routing Decisions ───
  Relevance Gate ──[continue]──▶ Guard (Classify)
  Classify ──[easy]──▶ Guard (Direct)

─── Final State ───
  is_complete: True
  final_answer: [sudo:direct_answer] This is a mock response...
  difficulty: easy
  total_cost: 0.024531
  iteration: 1
═══════════════════════════════════════════════════
```

## 설계 원칙

1. **Zero External Dependencies**: 네트워크, Claude CLI, API 키 불필요
2. **실제 그래프 실행**: `WorkflowExecutor`의 실제 컴파일/실행 로직 사용 — mock은 LLM만 대체
3. **자동 노드 감지**: 노드가 요구하는 structured output을 자동 감지하여 유효한 mock 생성
4. **결정론적**: 동일 seed → 동일 결과 (디버깅 용이)
5. **경로 커버리지**: `run_all_paths()`로 모든 classify 분기 자동 테스트

## 파일 구조

```
service/workflow/compiler/
├── __init__.py      # Public API exports
├── model.py         # SudoModel — mock LLM
├── compiler.py      # SudoCompiler — dry-run orchestrator
├── report.py        # SudoRunReport — execution results
├── runner.py        # CLI entry point
└── SUDO_COMPILER.md # This file
```
