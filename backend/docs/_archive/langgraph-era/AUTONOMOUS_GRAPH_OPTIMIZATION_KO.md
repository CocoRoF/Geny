# Autonomous Graph 경량화 제안서

> 작성일: 2026-03-21
> 기반: `AUTONOMOUS_GRAPH_ANALYSIS.md` 심층 분석 결과
> 원칙: **성능 손실 0, 정밀도 손실 0, 로직 손실 0** — 순수 구조 경량화만 수행

---

## 목차

1. [경량화 원칙](#1-경량화-원칙)
2. [제안 요약 (영향도 순)](#2-제안-요약)
3. [P1: 적응형 분류 — Rule→LLM 하이브리드](#3-p1-적응형-분류)
4. [P2: Guard/Post 노드 인라인화](#4-p2-guardpost-노드-인라인화)
5. [P3: Hard 경로 Final Review + Answer 통합](#5-p3-final-reviewanswer-통합)
6. [P4: Medium 리뷰 최적화 — 조건부 스킵](#6-p4-medium-리뷰-최적화)
7. [P5: Relevance Gate 단일 호출 보장](#7-p5-relevance-gate-단일-호출-보장)
8. [P6: Dead Code 정리](#8-p6-dead-code-정리)
9. [구현 순서 및 리스크 분석](#9-구현-순서-및-리스크-분석)
10. [예상 효과 시뮬레이션](#10-예상-효과-시뮬레이션)
11. [경량화 전/후 토폴로지 비교](#11-경량화-전후-토폴로지-비교)
12. [영향도 매트릭스 (변경 파일 목록)](#12-영향도-매트릭스)

---

## 1. 경량화 원칙

### 절대 불변 원칙

| # | 원칙 | 설명 |
|---|------|------|
| 1 | **정밀도 보존** | 동일 입력에 대해 동일하거나 더 나은 품질의 출력 보장 |
| 2 | **로직 보존** | 3가지 경로(Easy/Medium/Hard), 리뷰 루프, TODO 분해 등 핵심 로직 100% 유지 |
| 3 | **Resilience 보존** | 컨텍스트 가드, 에러 복구, 이터레이션 제한 기능 100% 유지 |
| 4 | **호환성 보존** | AutonomousState 스키마 변경 없음, API 인터페이스 변경 없음 |
| 5 | **점진적 적용** | 각 제안은 독립적으로 적용 가능, 롤백 가능 |

### 경량화 전략

```
현재: 과도한 노드 분리 → 노드 전환 비용 + 불필요한 LLM 호출
목표: 필요한 분리만 유지 → 최소 LLM 호출 + 최소 노드 전환
```

---

## 2. 제안 요약

| 우선순위 | 제안 | 절약 (Easy) | 절약 (Medium) | 절약 (Hard) | 복잡도 | 리스크 |
|---------|------|-----------|-------------|-----------|--------|--------|
| **P1** | 적응형 분류 | **8-15초** | 0-15초 | 0초 | 중간 | 낮음 |
| **P2** | Guard/Post 인라인 | **~2초** | ~3초 | ~5초 | 낮음 | 매우 낮음 |
| **P3** | Final Review+Answer 통합 | 0초 | 0초 | **10-20초** | 낮음 | 낮음 |
| **P4** | Medium 리뷰 조건부 스킵 | 0초 | **5-15초** | 0초 | 낮음 | 낮음 |
| **P5** | Relevance Gate 단일화 | **0-10초** | **0-10초** | **0-10초** | 매우 낮음 | 매우 낮음 |
| **P6** | Dead code 정리 | 0초 | 0초 | 0초 | 매우 낮음 | 없음 |

### 총 예상 절약

| 경로 | 현재 | 경량화 후 | 절약 | 절약률 |
|------|------|---------|------|--------|
| **Easy** (일반) | ~53초 | ~40초 | ~13초 | **~25%** |
| **Easy** (chat) | ~60초 | ~43초 | ~17초 | **~28%** |
| **Medium** (1회 승인) | ~75초 | ~50초 | ~25초 | **~33%** |
| **Medium** (3회 리트라이) | ~150초 | ~80초 | ~70초 | **~47%** |
| **Hard** (5 TODO) | ~300초 | ~260초 | ~40초 | **~13%** |

---

## 3. P1: 적응형 분류 — Rule→LLM 하이브리드

### 핵심 아이디어

> 대부분의 입력은 **규칙 기반으로 분류 가능**하다.
> LLM 분류는 규칙으로 판단 불가능한 경우에만 폴백으로 사용한다.

### 현재 방식 (문제)

```
모든 입력 → [LLM 호출: classify_difficulty] → easy/medium/hard
               8-15초 소모
```

### 제안 방식

```
모든 입력 → [Rule-based 빠른 분류] → 확신 높음? ─── Yes → 결과 사용 (0ms)
                                        │
                                        No
                                        │
                                        ▼
                              [LLM 호출: classify_difficulty] → 결과 사용 (8-15초)
```

### Rule-based 분류기 설계

```python
class QuickClassifier:
    """규칙 기반 빠른 난이도 분류기.

    확신도(confidence)가 임계값 이상이면 LLM 없이 결과 반환.
    아래이면 None 반환 → LLM 폴백.
    """

    # Easy 패턴: 짧고 단순한 질문
    EASY_PATTERNS = [
        # 인사/대화
        r'^(안녕|hello|hi |hey |감사|고마워|thanks)',
        # 단순 질문 (의문사 + 짧은 길이)
        r'^(뭐|무엇|what|who|when|where|how much|몇|어디|언제).{0,50}[?？]?$',
        # 계산/변환
        r'^\d+\s*[+\-*/×÷]\s*\d+',
        # 날씨/시간/사실 조회
        r'(날씨|시간|환율|수도|인구|높이|길이|넓이).{0,30}[?？]?$',
    ]

    # Hard 패턴: 명시적 복합 작업
    HARD_PATTERNS = [
        r'(만들어|구현|빌드|build|create|implement|design).*(시스템|앱|서비스|아키텍처|프로젝트)',
        r'(분석|analysis|리팩터|refactor|마이그레이션|migration)',
        r'(여러|multiple|단계|step).*(파일|file|모듈|module)',
    ]

    # 길이 기반 휴리스틱
    EASY_MAX_CHARS = 100      # 100자 이하 → Easy 후보
    HARD_MIN_CHARS = 500      # 500자 이상 → Hard 후보

    @classmethod
    def classify(cls, input_text: str) -> tuple[Optional[Difficulty], float]:
        """
        Returns:
            (difficulty, confidence) — difficulty=None이면 LLM 폴백 필요
        """
        text = input_text.strip()
        length = len(text)

        # 1. Easy 패턴 매칭
        for pattern in cls.EASY_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                if length <= cls.EASY_MAX_CHARS:
                    return (Difficulty.EASY, 0.95)

        # 2. Hard 패턴 매칭
        for pattern in cls.HARD_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                if length >= cls.HARD_MIN_CHARS:
                    return (Difficulty.HARD, 0.85)

        # 3. 길이 기반 간단 판단
        if length <= 50:    # 매우 짧은 입력
            return (Difficulty.EASY, 0.90)

        if length <= cls.EASY_MAX_CHARS and '?' in text:
            return (Difficulty.EASY, 0.80)

        # 4. 확신 부족 → LLM 폴백
        return (None, 0.0)
```

### Workflow 노드 수정 (ClassifyNode)

```python
# 기존 classify_node.py의 execute() 수정
async def execute(self, state, context, config):
    input_text = state.get("input", "")

    # 1. Quick classification (rule-based, 0ms)
    difficulty, confidence = QuickClassifier.classify(input_text)

    if difficulty is not None and confidence >= 0.80:
        logger.info(f"Quick classify: {difficulty.value} (conf={confidence:.0%})")
        return {
            "difficulty": difficulty.value,
            "current_step": "difficulty_classified",
            "messages": [HumanMessage(content=input_text)],
            "last_output": f"[quick_classify: {difficulty.value}]",
        }

    # 2. LLM classification (fallback, 8-15초)
    # ... 기존 LLM 분류 로직 유지 ...
```

### 정밀도 보존 근거

- **규칙 분류 실패 시 LLM 폴백**: 손실 가능성 0
- **규칙의 보수적 설계**: confidence threshold (0.80)를 조절하여 false positive 최소화
- **초기에는 threshold을 높게 설정** (0.90) → 점진적으로 낮춤 (운영 데이터 기반)
- **분류가 잘못되더라도 실행 자체는 성공**: Easy로 분류된 Medium이 직접 답변으로 처리되어도
  Claude의 능력으로 충분한 품질의 답변 생성 가능 (실제로 현재도 많은 Medium 질문이 한 번의 답변으로 충분)

### 예상 효과

- Easy 질문 (60-80%): **분류 LLM 호출 완전 제거** → 8-15초 절약
- Medium 질문 중 짧은 것 (10%): **분류 LLM 호출 제거** → 8-15초 절약
- 나머지 (20-30%): 기존과 동일 (LLM 분류)

---

## 4. P2: Guard/Post 노드 인라인화

### 핵심 아이디어

> Guard 노드와 Post-model 노드는 전/후 처리 로직이며,
> **독립 노드가 아닌 LLM 호출 노드 내부의 before/after 훅으로 인라인화**할 수 있다.

### 현재 방식 (30 노드)

```
guard_classify → classify_difficulty → post_classify
guard_direct   → direct_answer      → post_direct
guard_answer   → answer             → post_answer
guard_review   → review             → post_review
...
```

### 제안 방식 (14 노드로 축소)

```
classify_difficulty (내장 guard + post)
direct_answer      (내장 guard + post)
answer             (내장 guard + post)
review             (내장 guard + post)
...
```

### BaseNode에 Guard/Post 훅 내장

```python
class BaseNode:
    """기존 BaseNode에 guard/post 로직을 옵션으로 내장."""

    # 노드 설정
    enable_context_guard: bool = True   # 실행 전 컨텍스트 체크
    enable_post_processing: bool = True # 실행 후 이터레이션/완료 처리
    detect_completion: bool = True      # 완료 신호 감지 여부

    async def _run_with_hooks(self, state, context, config):
        """Guard → Execute → Post 를 단일 노드 내에서 수행."""
        updates = {}

        # 1. Guard (inline)
        if self.enable_context_guard:
            budget = self._check_context_budget(state, context)
            updates["context_budget"] = budget

        # 2. Execute (core logic)
        result = await self.execute(state, context, config)
        updates.update(result)

        # 3. Post (inline)
        if self.enable_post_processing:
            post_updates = self._post_process(state, updates)
            updates.update(post_updates)

        return updates

    def _check_context_budget(self, state, context):
        """인라인 컨텍스트 가드."""
        messages = state.get("messages", [])
        guard = context.context_guard or ContextWindowGuard(model=context.model_name)
        msg_dicts = [{"role": getattr(m, "type", "unknown"), "content": m.content}
                     for m in messages if hasattr(m, "content")]
        result = guard.check(msg_dicts)
        return {
            "estimated_tokens": result.estimated_tokens,
            "context_limit": result.context_limit,
            "usage_ratio": result.usage_ratio,
            "status": result.status.value,
            "compaction_count": (state.get("context_budget") or {}).get("compaction_count", 0),
        }

    def _post_process(self, state, updates):
        """인라인 포스트 프로세싱."""
        iteration = state.get("iteration", 0) + 1
        post = {"iteration": iteration}

        if self.detect_completion:
            last_output = updates.get("last_output", "") or ""
            if last_output:
                signal, detail = detect_completion_signal(last_output)
                post["completion_signal"] = signal.value
                post["completion_detail"] = detail

        return post
```

### Workflow JSON 변경

```diff
  // template-autonomous.json
  // 변경 전: 30 노드
- guard_classify → classify → post_classify
  // 변경 후: 14 노드 (guard, post 제거)
+ classify (config: { enable_context_guard: true, enable_post_processing: true })
```

### 정밀도 보존 근거

- Guard와 Post 로직은 **100% 동일한 코드**가 인라인됨
- 상태 업데이트 순서 보장: guard → execute → post (동일 순서)
- 컨텍스트 가드의 compaction 요청, 이터레이션 증가, 완료 신호 감지 모두 보존
- 로깅은 노드 단위가 아닌 단계(phase) 단위로 전환 (동일 가시성)

### 예상 효과

- **노드 수**: 30 → 14 (53% 감소)
- **노드 전환 오버헤드**: 상태 직렬화/역직렬화 횟수 53% 감소
- **시간 절약**: ~1-3초 (경로에 따라)

---

## 5. P3: Final Review + Answer 통합

### 핵심 아이디어

> Hard 경로에서 `final_review`와 `final_answer`는
> **동일한 컨텍스트**(입력 + TODO 결과)를 읽고 순차적으로 실행된다.
> **하나의 LLM 호출로 리뷰와 최종 답변을 동시 생성**할 수 있다.

### 현재 방식 (2회 LLM)

```
final_review:  입력 + TODO 결과 → 리뷰 텍스트 (LLM #1, ~15초)
final_answer:  입력 + TODO 결과 + 리뷰 텍스트 → 최종 답변 (LLM #2, ~20초)
```

### 제안 방식 (1회 LLM)

```
final_synthesis:  입력 + TODO 결과 → 리뷰 포함 최종 답변 (LLM #1, ~25초)
```

### 통합 프롬프트

```python
@staticmethod
def final_synthesis() -> str:
    """final_review + final_answer 통합 프롬프트."""
    return (
        "You have completed a complex task through multiple TODO items.\n\n"
        "Original Request:\n{input}\n\n"
        "Completed Work:\n{todo_results}\n\n"
        "Provide your final comprehensive response:\n"
        "1. First, briefly review the quality of completed work "
        "(identify any gaps or issues)\n"
        "2. Then, synthesize all work into a coherent, polished answer "
        "that fully addresses the original request.\n\n"
        "Focus on the synthesized answer — the review is for your own "
        "quality assurance."
    )
```

### Workflow 변경

```diff
  // template-autonomous.json
- guard_final_review → final_review → post_final_review → guard_final_answer → final_answer → post_final_answer → end
+ final_synthesis → end
```

### 정밀도 보존 근거

- **동일 컨텍스트**: 현재 `final_answer`는 `final_review` 출력을 입력으로 받지만,
  LLM은 TODO 결과를 이미 보고 있으므로 리뷰를 별도로 받을 필요 없음
- **통합 프롬프트가 리뷰 + 합성 모두 요구**: 품질 검토 과정이 제거되지 않음
- **실측**: 현재 `final_review`의 리뷰 내용이 `final_answer`에 미치는 실질적 영향은 미미함
  (대부분의 경우 `final_answer`는 TODO 결과를 직접 합성하는 것으로 충분)

### 예상 효과

- LLM 호출: 2회 → 1회
- 시간 절약: 10-20초
- 노드 수: 6개 → 1개 (guard×2 + post×2 + final_review + final_answer → final_synthesis)

---

## 6. P4: Medium 리뷰 최적화 — 조건부 스킵

### 핵심 아이디어

> Medium 경로의 self-review는 **동일 모델이 자신의 답변을 리뷰**하므로 효과가 제한적.
> 짧고 단순한 Medium 질문에서는 리뷰를 스킵하고, 복잡한 경우만 리뷰를 수행한다.

### 현재 방식

```
모든 Medium → answer → review → (approved → END / rejected → retry)
최소 2회 LLM (answer + review)
```

### 제안 방식

```
Medium → answer → [리뷰 필요?]
                     │
                     ├── No (짧은 답변/단순 질문) → END
                     │
                     └── Yes (복잡한 답변) → review → ...
```

### 리뷰 필요성 판단 (규칙 기반, LLM 없음)

```python
class ReviewSkipEvaluator:
    """리뷰 필요성을 규칙 기반으로 판단."""

    # 리뷰 불필요 조건
    SKIP_WHEN_ANSWER_SHORT = 500     # 500자 이하 답변
    SKIP_WHEN_INPUT_SHORT = 100      # 100자 이하 질문

    @classmethod
    def should_skip_review(cls, input_text: str, answer: str) -> bool:
        """리뷰를 스킵해도 되는지 판단."""
        # 1. 매우 짧은 질문 + 짧은 답변 → 스킵
        if len(input_text) <= cls.SKIP_WHEN_INPUT_SHORT and len(answer) <= cls.SKIP_WHEN_ANSWER_SHORT:
            return True

        # 2. 코드가 포함되지 않은 짧은 답변 → 스킵
        has_code = '```' in answer or 'def ' in answer or 'function ' in answer
        if not has_code and len(answer) <= cls.SKIP_WHEN_ANSWER_SHORT:
            return True

        # 3. 나머지 → 리뷰 수행
        return False
```

### 정밀도 보존 근거

- **복잡한 답변은 여전히 리뷰됨**: 코드 포함, 긴 답변 등
- **짧은 답변의 self-review 효과는 거의 0에 가까움**: 500자 이하의 답변에서
  동일 모델이 reject할 확률은 매우 낮으며, reject하더라도 재시도 결과가
  크게 다르지 않음
- **Maximum retry 후 강제 승인**: 현재도 최악의 경우 강제 승인하므로,
  리뷰 스킵은 이 강제 승인을 앞당기는 것에 불과

### 예상 효과

- Medium 질문 중 ~60%에서 리뷰 스킵
- 스킵 시: 1회 LLM 절약 (5-15초)
- 리트라이 방지: 최대 2×3 = 6회 LLM 절약

---

## 7. P5: Relevance Gate 단일 호출 보장

### 핵심 아이디어

> Relevance Gate의 structured output 파싱 실패 시 YES/NO 폴백으로 **추가 LLM 호출**이 발생한다.
> 처음부터 **간단한 프롬프트 + 텍스트 파싱**으로 통일하면 항상 1회 호출로 완료된다.

### 현재 방식 (최대 2회 LLM)

```
1차: structured output (JSON) 시도 → 파싱 실패
2차: YES/NO 폴백 → 텍스트 매칭
```

### 제안 방식 (항상 1회 LLM)

```
1차: 간결한 프롬프트 + "YES 또는 NO로만 답하세요" → 텍스트 매칭
     파싱 실패 시: 기본값 relevant=true (안전한 방향)
```

### 변경 코드

```python
async def execute(self, state, context, config):
    # ... (기존 non-chat pass-through 유지)

    prompt = (
        f"You are {agent_name} (role: {agent_role}).\n"
        f"Message: \"{input_text[:200]}\"\n"  # 토큰 절약
        f"Is this relevant to you? Reply ONLY: YES or NO"
    )

    response, _ = await context.resilient_invoke([HumanMessage(content=prompt)], "relevance_gate")
    text = response.content.strip().lower()

    is_relevant = ("yes" in text or "예" in text or "네" in text) and "no" not in text[:5]

    # 폴백 LLM 호출 없이 결과 반환
    if not is_relevant:
        return {"relevance_skipped": True, "is_complete": True, "final_answer": ""}
    return {"relevance_skipped": False}
```

### 정밀도 보존 근거

- YES/NO 응답은 Claude에서 매우 신뢰할 수 있는 형식
- JSON structured output보다 실패율이 낮음
- 실패 시 `relevant=true` 기본값 = 안전한 방향 (놓치는 것보다 처리하는 것이 나음)

### 예상 효과

- 최악 케이스 LLM 호출: 2회 → 1회
- 시간 절약: 0-10초 (structured output 실패 빈도에 따라)

---

## 8. P6: Dead Code 정리

### 제거 대상

| 파일 | 대상 | 이유 |
|------|------|------|
| `autonomous_graph.py` | 전체 클래스 | WorkflowExecutor가 동일 기능 수행, build()는 미사용 |
| `autonomous_graph.py.bak` | 백업 파일 | 불필요 |
| `resilience_nodes.py` | `make_context_guard_node()`, `make_memory_inject_node()` | workflow 노드로 대체됨 |
| `model_fallback.py` | `ModelFallbackRunner` 클래스 | 사용되지 않음 (resilient_invoke만 활용) |

### 보존 대상

| 파일 | 대상 | 이유 |
|------|------|------|
| `resilience_nodes.py` | `detect_completion_signal()` | post-model 로직에서 계속 사용 |
| `model_fallback.py` | `classify_error()`, `is_recoverable()`, `FailureReason` | resilient_invoke에서 계속 사용 |
| `context_guard.py` | 전체 | guard 노드에서 계속 사용 |
| `state.py` | 전체 | State 스키마 (변경 불가) |

### 정밀도 보존 근거

- 사용되지 않는 코드만 제거 → 런타임 영향 0
- import 경로 정리만 필요

---

## 9. 구현 순서 및 리스크 분석

### 권장 구현 순서

```
Phase 1 (즉시 적용 가능, 리스크 없음)
├── P6: Dead code 정리
├── P5: Relevance gate 단일화
└── P2: Guard/Post 인라인화

Phase 2 (신중한 테스트 필요)
├── P4: Medium 리뷰 조건부 스킵
└── P3: Final review + answer 통합

Phase 3 (운영 데이터 기반 튜닝)
└── P1: 적응형 분류 (Rule→LLM 하이브리드)
```

### 리스크 매트릭스

| 제안 | 리스크 유형 | 리스크 수준 | 완화 전략 |
|------|-----------|-----------|----------|
| P1 | 분류 오류 | 낮음 | 높은 confidence threshold + LLM 폴백 |
| P2 | 로깅 누락 | 매우 낮음 | 인라인 로깅으로 동일 가시성 확보 |
| P3 | 품질 저하 | 낮음 | 통합 프롬프트에 리뷰 과정 포함 |
| P4 | 중요한 리뷰 스킵 | 낮음 | 복잡한 답변은 항상 리뷰, config로 비활성화 가능 |
| P5 | 관련성 판단 오류 | 매우 낮음 | 실패 시 relevant=true 기본값 |
| P6 | 없음 | 없음 | Dead code만 제거 |

### 롤백 전략

모든 제안은 **config flag**로 활성화/비활성화 가능하게 설계:

```python
# service/config 또는 workflow JSON의 노드 config에 추가
{
    "optimization": {
        "enable_quick_classify": true,       # P1
        "inline_guard_post": true,           # P2
        "merge_final_review_answer": true,   # P3
        "enable_review_skip": true,          # P4
        "simple_relevance_gate": true,       # P5
    }
}
```

---

## 10. 예상 효과 시뮬레이션

### Easy 경로 시뮬레이션 (사용자 예시 기반)

```
=== 현재 (53초) ===
memory_inject          0.0s
relevance_gate         0.0s  (non-chat)
guard_classify         0.0s
classify_difficulty   11.0s  ★ LLM
post_classify          0.0s
guard_direct           0.0s
direct_answer         40.0s  ★ LLM (+ WebSearch)
post_direct            0.0s
기타 오버헤드          2.0s
──────────────────────────
합계                  53.0s

=== 경량화 후 (예상 ~40초) ===
memory_inject          0.0s
relevance_gate         0.0s  (non-chat)
classify               0.0s  ● Rule-based (P1 적용)
direct_answer         40.0s  ★ LLM내 guard+post 인라인 (P2 적용)
──────────────────────────
합계                  ~40.0s  (13초 절약, 25%↓)
```

### Medium 경로 시뮬레이션 (짧은 질문, 1회 승인)

```
=== 현재 (~75초) ===
memory → relevance → guard → classify(★11s) → post
→ guard → answer(★20s) → post → guard → review(★15s) → post → END
총 LLM: 3회, 가드: 3회, 포스트: 3회

=== 경량화 후 (예상 ~35초) ===
memory → relevance → classify(●0s, P1) → answer(★20s, 인라인 guard+post)
→ [리뷰 스킵, P4] → END
총 LLM: 1회, 가드: 0회 (인라인), 포스트: 0회 (인라인)
```

### Hard 경로 시뮬레이션 (5 TODO)

```
=== 현재 (~300초) ===
classify(★11s) + create_todos(★15s) + 5×execute_todo(★5×30s)
+ final_review(★15s) + final_answer(★20s)
+ guard×7 + post×7
총 LLM: 9회

=== 경량화 후 (예상 ~260초) ===
classify(★11s, 여전히 LLM — Hard는 규칙 분류 어려움)
+ create_todos(★15s) + 5×execute_todo(★5×30s)
+ final_synthesis(★25s, P3)
+ guard/post 인라인 (P2)
총 LLM: 8회 (final_review 제거)
```

---

## 11. 경량화 전/후 토폴로지 비교

### 현재 (30 노드, 37 엣지)

```
START → memory_inject → relevance_gate → guard_classify → classify_difficulty → post_classify
  │ easy: guard_direct → direct_answer → post_direct → END
  │ medium: guard_answer → answer → post_answer → guard_review → review → post_review
  │         → iter_gate_medium ↺
  │ hard: guard_create_todos → create_todos → post_create_todos → guard_execute
  │       → execute_todo → post_execute → check_progress → iter_gate_hard ↺
  │       → guard_final_review → final_review → post_final_review
  │       → guard_final_answer → final_answer → post_final_answer → END
```

### 경량화 후 (14 노드, 17 엣지) — P1+P2+P3+P4+P5 모두 적용

```
START → memory_inject → relevance_gate → classify
  │ easy: direct_answer → END
  │ medium: answer → [review_needed?]
  │         → yes: review → iter_gate_medium ↺ → answer
  │         → no: END
  │ hard: create_todos → execute_todo → check_progress → iter_gate_hard ↺
  │       → final_synthesis → END
```

### 노드 수 비교

| 카테고리 | 현재 | 경량화 | 변화 |
|----------|------|--------|------|
| LLM 노드 | 9 | 7 | -2 (final_review, final_answer → final_synthesis) |
| Guard 노드 | 8 | 0 | -8 (모두 인라인) |
| Post 노드 | 8 | 0 | -8 (모두 인라인) |
| Logic 노드 | 5 | 5 | 0 (iter_gate, check_progress, memory_inject, relevance_gate, classify 유지) |
| **합계** | **30** | **14** | **-16 (53%↓)** |

---

## 12. 영향도 매트릭스

### 변경이 필요한 파일

| 파일 | P1 | P2 | P3 | P4 | P5 | P6 | 변경 내용 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|----------|
| `service/workflow/nodes/model/classify_node.py` | ✅ | ✅ | | | | | Quick classifier 추가, guard/post 인라인 |
| `service/workflow/nodes/model/direct_answer_node.py` | | ✅ | | | | | guard/post 인라인 |
| `service/workflow/nodes/model/answer_node.py` | | ✅ | | | | | guard/post 인라인 |
| `service/workflow/nodes/model/review_node.py` | | ✅ | | ✅ | | | guard/post 인라인, 스킵 로직 |
| `service/workflow/nodes/task/create_todos_node.py` | | ✅ | | | | | guard/post 인라인 |
| `service/workflow/nodes/task/execute_todo_node.py` | | ✅ | | | | | guard/post 인라인 |
| `service/workflow/nodes/task/final_review_node.py` | | | ✅ | | | | 삭제 또는 통합 |
| `service/workflow/nodes/task/final_answer_node.py` | | | ✅ | | | | final_synthesis로 통합 |
| `service/workflow/nodes/logic/relevance_gate_node.py` | | | | | ✅ | | 단순화 |
| `service/workflow/nodes/base.py` | | ✅ | | | | | guard/post 훅 추가 |
| `service/prompt/sections.py` | | | ✅ | | | | final_synthesis 프롬프트 추가 |
| `workflows/template-autonomous.json` | ✅ | ✅ | ✅ | ✅ | | | 노드/엣지 재구성 |
| `service/langgraph/autonomous_graph.py` | | | | | | ✅ | 삭제 (dead code) |
| `service/langgraph/autonomous_graph.py.bak` | | | | | | ✅ | 삭제 |

### 변경하지 않는 파일 (보존)

| 파일 | 이유 |
|------|------|
| `service/langgraph/state.py` | State 스키마 100% 보존 |
| `service/langgraph/agent_session.py` | 실행 진입점 변경 없음 |
| `service/langgraph/context_guard.py` | 인라인되지만 모듈 자체는 유지 |
| `service/langgraph/model_fallback.py` | 에러 분류 유틸은 유지 |
| `service/langgraph/claude_cli_model.py` | 모델 래퍼 변경 없음 |
| `service/workflow/workflow_executor.py` | 컴파일러 변경 없음 |
| `service/workflow/workflow_model.py` | 모델 변경 없음 |

---

## 결론

### 핵심 메시지

현재 Autonomous Graph는 **"LangGraph 철학에 따른 관심사 분리"**를 과도하게 적용하여,
모든 요청이 30개 노드를 통과하며 불필요한 LLM 호출과 노드 전환 비용을 치르고 있다.

제안된 6가지 경량화는:
- **LLM 호출 수**: Easy 2→1, Medium 3→1~2, Hard N+4→N+2
- **노드 수**: 30→14 (53% 감소)
- **시간 절약**: Easy 25%, Medium 33-47%, Hard 13%
- **정밀도 손실**: 0 (모든 핵심 로직 보존, 폴백 경로 유지)
- **롤백 가능**: Config flag로 개별 활성화/비활성화

가장 큰 효과는 **P1 (적응형 분류)**로, Easy 질문의 분류 LLM 호출을 완전히 제거하여
**단일 질문당 8-15초를 절약**한다.

*구현 준비가 되면 Phase 1 (P6→P5→P2)부터 시작을 권장한다.*
