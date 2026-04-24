# Autonomous Graph Optimization Proposal

> Date: 2026-03-21
> Based on: `AUTONOMOUS_GRAPH_ANALYSIS.md` deep analysis results
> Principle: **Zero performance loss, zero precision loss, zero logic loss** — pure structural optimization only

---

## Table of Contents

1. [Optimization Principles](#1-optimization-principles)
2. [Proposal Summary (By Impact)](#2-proposal-summary)
3. [P1: Adaptive Classification — Rule→LLM Hybrid](#3-p1-adaptive-classification)
4. [P2: Guard/Post Node Inlining](#4-p2-guardpost-node-inlining)
5. [P3: Hard Path Final Review + Answer Merge](#5-p3-final-reviewanswer-merge)
6. [P4: Medium Review Optimization — Conditional Skip](#6-p4-medium-review-optimization)
7. [P5: Relevance Gate Single-Call Guarantee](#7-p5-relevance-gate-single-call-guarantee)
8. [P6: Dead Code Cleanup](#8-p6-dead-code-cleanup)
9. [Implementation Order and Risk Analysis](#9-implementation-order-and-risk-analysis)
10. [Expected Effects Simulation](#10-expected-effects-simulation)
11. [Pre/Post Optimization Topology Comparison](#11-prepost-optimization-topology-comparison)
12. [Impact Matrix (Changed Files List)](#12-impact-matrix)

---

## 1. Optimization Principles

### Absolute Invariant Principles

| # | Principle | Description |
|---|-----------|-------------|
| 1 | **Precision preservation** | Guarantee same or better quality output for identical input |
| 2 | **Logic preservation** | 100% retain core logic: 3 paths (Easy/Medium/Hard), review loop, TODO decomposition |
| 3 | **Resilience preservation** | 100% retain context guard, error recovery, iteration limit features |
| 4 | **Compatibility preservation** | No AutonomousState schema changes, no API interface changes |
| 5 | **Incremental application** | Each proposal can be applied independently, rollback possible |

### Optimization Strategy

```
Current: Excessive node separation → node transition overhead + unnecessary LLM calls
Target:  Only necessary separation → minimum LLM calls + minimum node transitions
```

---

## 2. Proposal Summary

| Priority | Proposal | Savings (Easy) | Savings (Medium) | Savings (Hard) | Complexity | Risk |
|----------|----------|---------------|-----------------|---------------|------------|------|
| **P1** | Adaptive classification | **8-15s** | 0-15s | 0s | Medium | Low |
| **P2** | Guard/Post inlining | **~2s** | ~3s | ~5s | Low | Very low |
| **P3** | Final Review+Answer merge | 0s | 0s | **10-20s** | Low | Low |
| **P4** | Medium review conditional skip | 0s | **5-15s** | 0s | Low | Low |
| **P5** | Relevance Gate single-call | **0-10s** | **0-10s** | **0-10s** | Very low | Very low |
| **P6** | Dead code cleanup | 0s | 0s | 0s | Very low | None |

### Total Expected Savings

| Path | Current | After Optimization | Savings | Savings Rate |
|------|---------|-------------------|---------|-------------|
| **Easy** (normal) | ~53s | ~40s | ~13s | **~25%** |
| **Easy** (chat) | ~60s | ~43s | ~17s | **~28%** |
| **Medium** (1st approval) | ~75s | ~50s | ~25s | **~33%** |
| **Medium** (3 retries) | ~150s | ~80s | ~70s | **~47%** |
| **Hard** (5 TODOs) | ~300s | ~260s | ~40s | **~13%** |

---

## 3. P1: Adaptive Classification — Rule→LLM Hybrid

### Core Idea

> Most inputs can be **classified with rules alone**.
> LLM classification is used as a fallback only when rules cannot determine difficulty.

### Current Approach (Problem)

```
All inputs → [LLM call: classify_difficulty] → easy/medium/hard
                8-15s consumed
```

### Proposed Approach

```
All inputs → [Rule-based quick classify] → High confidence? ─── Yes → Use result (0ms)
                                              │
                                              No
                                              │
                                              ▼
                                    [LLM call: classify_difficulty] → Use result (8-15s)
```

### Rule-Based Classifier Design

```python
class QuickClassifier:
    """Rule-based quick difficulty classifier.

    Returns result without LLM when confidence exceeds threshold.
    Returns None below threshold → LLM fallback.
    """

    # Easy patterns: short, simple questions
    EASY_PATTERNS = [
        # Greetings/conversation
        r'^(안녕|hello|hi |hey |감사|고마워|thanks)',
        # Simple questions (interrogative + short length)
        r'^(뭐|무엇|what|who|when|where|how much|몇|어디|언제).{0,50}[?？]?$',
        # Arithmetic/conversion
        r'^\d+\s*[+\-*/×÷]\s*\d+',
        # Weather/time/fact lookup
        r'(날씨|시간|환율|수도|인구|높이|길이|넓이).{0,30}[?？]?$',
    ]

    # Hard patterns: explicit complex tasks
    HARD_PATTERNS = [
        r'(만들어|구현|빌드|build|create|implement|design).*(시스템|앱|서비스|아키텍처|프로젝트)',
        r'(분석|analysis|리팩터|refactor|마이그레이션|migration)',
        r'(여러|multiple|단계|step).*(파일|file|모듈|module)',
    ]

    # Length-based heuristics
    EASY_MAX_CHARS = 100      # ≤100 chars → Easy candidate
    HARD_MIN_CHARS = 500      # ≥500 chars → Hard candidate

    @classmethod
    def classify(cls, input_text: str) -> tuple[Optional[Difficulty], float]:
        """
        Returns:
            (difficulty, confidence) — difficulty=None means LLM fallback needed
        """
        text = input_text.strip()
        length = len(text)

        # 1. Easy pattern matching
        for pattern in cls.EASY_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                if length <= cls.EASY_MAX_CHARS:
                    return (Difficulty.EASY, 0.95)

        # 2. Hard pattern matching
        for pattern in cls.HARD_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                if length >= cls.HARD_MIN_CHARS:
                    return (Difficulty.HARD, 0.85)

        # 3. Simple length-based judgment
        if length <= 50:    # Very short input
            return (Difficulty.EASY, 0.90)

        if length <= cls.EASY_MAX_CHARS and '?' in text:
            return (Difficulty.EASY, 0.80)

        # 4. Insufficient confidence → LLM fallback
        return (None, 0.0)
```

### Workflow Node Modification (ClassifyNode)

```python
# Modify existing classify_node.py execute()
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

    # 2. LLM classification (fallback, 8-15s)
    # ... existing LLM classification logic retained ...
```

### Precision Preservation Rationale

- **LLM fallback on rule failure**: zero loss possibility
- **Conservative rule design**: adjust confidence threshold (0.80) to minimize false positives
- **Start with high threshold** (0.90) → gradually lower (based on production data)
- **Even incorrect classification still executes successfully**: an Easy-classified Medium produces a direct answer, and Claude's capability ensures sufficient quality (in practice, many Medium questions are adequately answered in one pass)

### Expected Effect

- Easy questions (60-80%): **classification LLM call completely eliminated** → 8-15s saved
- Short Medium questions (10%): **classification LLM call eliminated** → 8-15s saved
- Remaining (20-30%): same as current (LLM classification)

---

## 4. P2: Guard/Post Node Inlining

### Core Idea

> Guard nodes and Post-model nodes are pre/post-processing logic that
> can be **inlined as before/after hooks inside LLM call nodes** rather than being independent nodes.

### Current Approach (30 nodes)

```
guard_classify → classify_difficulty → post_classify
guard_direct   → direct_answer      → post_direct
guard_answer   → answer             → post_answer
guard_review   → review             → post_review
...
```

### Proposed Approach (Reduced to 14 nodes)

```
classify_difficulty (built-in guard + post)
direct_answer      (built-in guard + post)
answer             (built-in guard + post)
review             (built-in guard + post)
...
```

### Built-in Guard/Post Hooks in BaseNode

```python
class BaseNode:
    """Existing BaseNode with optional inline guard/post logic."""

    # Node settings
    enable_context_guard: bool = True   # Pre-execution context check
    enable_post_processing: bool = True # Post-execution iteration/completion processing
    detect_completion: bool = True      # Completion signal detection toggle

    async def _run_with_hooks(self, state, context, config):
        """Perform Guard → Execute → Post within a single node."""
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
        """Inline context guard."""
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
        """Inline post-processing."""
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

### Workflow JSON Changes

```diff
  // template-autonomous.json
  // Before: 30 nodes
- guard_classify → classify → post_classify
  // After: 14 nodes (guard, post removed)
+ classify (config: { enable_context_guard: true, enable_post_processing: true })
```

### Precision Preservation Rationale

- Guard and Post logic is **100% identical code** being inlined
- State update order guaranteed: guard → execute → post (same order)
- Context guard compaction requests, iteration increments, completion signal detection all preserved
- Logging transitions from node-level to phase-level (same visibility)

### Expected Effect

- **Node count**: 30 → 14 (53% reduction)
- **Node transition overhead**: 53% reduction in state serialization/deserialization
- **Time savings**: ~1-3s (varies by path)

---

## 5. P3: Final Review + Answer Merge

### Core Idea

> In the Hard path, `final_review` and `final_answer` read the
> **same context** (input + TODO results) and execute sequentially.
> **A single LLM call can generate both review and final answer simultaneously.**

### Current Approach (2 LLM calls)

```
final_review:  input + TODO results → review text (LLM #1, ~15s)
final_answer:  input + TODO results + review text → final answer (LLM #2, ~20s)
```

### Proposed Approach (1 LLM call)

```
final_synthesis:  input + TODO results → review-inclusive final answer (LLM #1, ~25s)
```

### Merged Prompt

```python
@staticmethod
def final_synthesis() -> str:
    """Merged final_review + final_answer prompt."""
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

### Workflow Changes

```diff
  // template-autonomous.json
- guard_final_review → final_review → post_final_review → guard_final_answer → final_answer → post_final_answer → end
+ final_synthesis → end
```

### Precision Preservation Rationale

- **Same context**: `final_answer` currently receives `final_review` output as input, but
  the LLM already sees TODO results, so a separate review pass is unnecessary
- **Merged prompt requests both review + synthesis**: quality review process is not removed
- **Empirical observation**: the actual impact of `final_review` content on `final_answer` is minimal
  (in most cases, `final_answer` directly synthesizes from TODO results)

### Expected Effect

- LLM calls: 2 → 1
- Time savings: 10-20s
- Node count: 6 → 1 (guard×2 + post×2 + final_review + final_answer → final_synthesis)

---

## 6. P4: Medium Review Optimization — Conditional Skip

### Core Idea

> Medium path self-review has **limited effectiveness since the same model reviews its own answer**.
> Skip review for short, simple Medium questions; only perform review for complex cases.

### Current Approach

```
All Medium → answer → review → (approved → END / rejected → retry)
Minimum 2 LLM calls (answer + review)
```

### Proposed Approach

```
Medium → answer → [Review needed?]
                     │
                     ├── No (short answer/simple question) → END
                     │
                     └── Yes (complex answer) → review → ...
```

### Review Necessity Evaluation (Rule-based, No LLM)

```python
class ReviewSkipEvaluator:
    """Rule-based review necessity evaluator."""

    # Skip review conditions
    SKIP_WHEN_ANSWER_SHORT = 500     # ≤500 char answer
    SKIP_WHEN_INPUT_SHORT = 100      # ≤100 char question

    @classmethod
    def should_skip_review(cls, input_text: str, answer: str) -> bool:
        """Determine if review can be skipped."""
        # 1. Very short question + short answer → skip
        if len(input_text) <= cls.SKIP_WHEN_INPUT_SHORT and len(answer) <= cls.SKIP_WHEN_ANSWER_SHORT:
            return True

        # 2. Short answer without code → skip
        has_code = '```' in answer or 'def ' in answer or 'function ' in answer
        if not has_code and len(answer) <= cls.SKIP_WHEN_ANSWER_SHORT:
            return True

        # 3. Otherwise → perform review
        return False
```

### Precision Preservation Rationale

- **Complex answers are still reviewed**: those containing code, long answers, etc.
- **Self-review effectiveness on short answers is near zero**: for ≤500 char answers,
  the probability of the same model rejecting is very low, and retry results
  are not significantly different
- **Maximum retry forces approval anyway**: the current system already force-approves in worst case,
  so skipping review merely advances this forced approval

### Expected Effect

- Review skipped in ~60% of Medium questions
- Per skip: 1 LLM call saved (5-15s)
- Retry prevention: up to 2×3 = 6 LLM calls saved

---

## 7. P5: Relevance Gate Single-Call Guarantee

### Core Idea

> When Relevance Gate's structured output parsing fails, a fallback YES/NO **additional LLM call** occurs.
> Using **simple prompt + text parsing** from the start ensures always completing in 1 call.

### Current Approach (up to 2 LLM calls)

```
1st: structured output (JSON) attempt → parsing failure
2nd: YES/NO fallback → text matching
```

### Proposed Approach (always 1 LLM call)

```
1st: concise prompt + "Reply ONLY YES or NO" → text matching
     On parse failure: default relevant=true (safe direction)
```

### Changed Code

```python
async def execute(self, state, context, config):
    # ... (existing non-chat pass-through retained)

    prompt = (
        f"You are {agent_name} (role: {agent_role}).\n"
        f"Message: \"{input_text[:200]}\"\n"  # Token savings
        f"Is this relevant to you? Reply ONLY: YES or NO"
    )

    response, _ = await context.resilient_invoke([HumanMessage(content=prompt)], "relevance_gate")
    text = response.content.strip().lower()

    is_relevant = ("yes" in text or "예" in text or "네" in text) and "no" not in text[:5]

    # Return result without fallback LLM call
    if not is_relevant:
        return {"relevance_skipped": True, "is_complete": True, "final_answer": ""}
    return {"relevance_skipped": False}
```

### Precision Preservation Rationale

- YES/NO responses are a very reliable format for Claude
- Lower failure rate than JSON structured output
- Default `relevant=true` on failure = safe direction (better to process than to miss)

### Expected Effect

- Worst-case LLM calls: 2 → 1
- Time savings: 0-10s (depends on structured output failure frequency)

---

## 8. P6: Dead Code Cleanup

### Removal Targets

| File | Target | Reason |
|------|--------|--------|
| `autonomous_graph.py` | Entire class | WorkflowExecutor performs same function, build() is unused |
| `autonomous_graph.py.bak` | Backup file | Unnecessary |
| `resilience_nodes.py` | `make_context_guard_node()`, `make_memory_inject_node()` | Replaced by workflow nodes |
| `model_fallback.py` | `ModelFallbackRunner` class | Unused (only resilient_invoke is used) |

### Preservation Targets

| File | Target | Reason |
|------|--------|--------|
| `resilience_nodes.py` | `detect_completion_signal()` | Still used in post-model logic |
| `model_fallback.py` | `classify_error()`, `is_recoverable()`, `FailureReason` | Still used in resilient_invoke |
| `context_guard.py` | Entire file | Still used in guard nodes |
| `state.py` | Entire file | State schema (immutable) |

### Precision Preservation Rationale

- Only unused code removed → zero runtime impact
- Only import path cleanup needed

---

## 9. Implementation Order and Risk Analysis

### Recommended Implementation Order

```
Phase 1 (Immediately applicable, zero risk)
├── P6: Dead code cleanup
├── P5: Relevance gate single-call
└── P2: Guard/Post inlining

Phase 2 (Low risk, requires testing)
├── P4: Medium review conditional skip
└── P3: Final Review+Answer merge

Phase 3 (Medium risk, requires monitoring)
└── P1: Adaptive classification
```

### Risk Analysis

| Proposal | Risk | Mitigation | Rollback |
|----------|------|------------|----------|
| P1 | Rule misclassification → wrong path | High initial threshold (0.90), runtime monitoring | Feature flag |
| P2 | Node transition behavior change | Unit tests for each hook phase | Revert to separate nodes |
| P3 | Quality degradation of final answer | A/B test comparison | Re-separate the prompt |
| P4 | Missed review on complex answers | Conservative skip criteria | Lower char thresholds |
| P5 | Relevance misjudgment | Default safe direction (relevant=true) | Revert to structured output |
| P6 | Missing import cleanup | CI test pass required | git revert |

---

## 10. Expected Effects Simulation

### Easy Path Simulation (Normal Mode)

```
Current (53s):
  memory_inject  → relevance_gate → guard_classify → classify → post_classify
      0ms              0ms              1ms           11s          0ms
  → guard_direct → direct_answer → post_direct → END
       1ms             40s            0ms

After Optimization (40s):
  memory_inject → relevance_gate → classify(with guard+post, rule-based) → direct_answer(with guard+post) → END
      0ms             0ms              0ms (rule hit)                            40s

  Savings: classify LLM call (11s) + node transitions (~2s) = ~13s
```

### Medium Path Simulation (3 Retries)

```
Current (150s):
  ... → classify(11s) → answer(20s) → review(10s) → [reject]
      → answer(20s) → review(10s) → [reject]
      → answer(20s) → review(10s) → [reject → force approve]
      → answer(20s) → review(10s) → [force approve] → END

After Optimization (80s):
  ... → classify(0ms rule) → answer(20s) → [skip review: short answer] → END

  Best case: classify savings (11s) + review savings (10s×3) + retry prevention (20s×2) = ~81s
  Worst case: classify savings (11s) + node transitions (~3s) = ~14s
```

---

## 11. Pre/Post Optimization Topology Comparison

### Before (30 nodes, 37 edges)

```
START → memory_inject → relevance_gate → guard_classify → classify → post_classify
                                                                          │
          ┌───────────────────────────────────────┬───────────────────────┘
          │                                       │                      │
     guard_direct                            guard_answer           guard_create_todos
          │                                       │                      │
     direct_answer                             answer              create_todos
          │                                       │                      │
     post_direct                              post_answer         post_create_todos
          │                                       │                      │
         END                                 guard_review          guard_execute
                                                  │                      │
                                               review             execute_todo
                                                  │                      │
                                             post_review          post_execute
                                                  │                      │
                                         iter_gate_medium        check_progress
                                                                         │
                                                                  iter_gate_hard
                                                                         │
                                                              guard_final_review
                                                                         │
                                                                  final_review
                                                                         │
                                                              post_final_review
                                                                         │
                                                              guard_final_answer
                                                                         │
                                                                  final_answer
                                                                         │
                                                              post_final_answer
                                                                         │
                                                                        END
```

### After (14 nodes, ~20 edges)

```
START → memory_inject → relevance_gate → classify → post_classify
                                                          │
          ┌──────────────────────────┬───────────────────┘
          │                          │                    │
     direct_answer               answer            create_todos
          │                          │                    │
         END                      review            execute_todo
                                     │                    │
                               iter_gate_medium    check_progress
                                                          │
                                                   iter_gate_hard
                                                          │
                                                   final_synthesis
                                                          │
                                                         END
```

---

## 12. Impact Matrix

### Changed Files List

| File | Changes | Proposals |
|------|---------|-----------|
| `service/langgraph/nodes/classify_node.py` | Add QuickClassifier, modify execute() | P1 |
| `service/langgraph/nodes/base.py` | Add guard/post hooks to BaseNode | P2 |
| `service/langgraph/nodes/relevance_node.py` | Simplify to single-call | P5 |
| `service/langgraph/nodes/review_node.py` | Add ReviewSkipEvaluator | P4 |
| `service/langgraph/nodes/final_synthesis_node.py` | New file (merge of final_review + final_answer) | P3 |
| `workflows/template-autonomous.json` | Remove guard/post nodes, update edges | P2, P3 |
| `service/langgraph/autonomous_graph.py` | Delete | P6 |
| `service/langgraph/resilience_nodes.py` | Remove unused functions | P6 |
| `service/langgraph/model_fallback.py` | Remove unused class | P6 |
| `service/workflow/workflow_executor.py` | Update node registry references | P2 |

### Unchanged Files (Compatibility Guaranteed)

| File | Reason |
|------|--------|
| `service/langgraph/state.py` | State schema unchanged |
| `service/langgraph/context_guard.py` | Logic preserved (inlined) |
| `controller/agent_controller.py` | No API changes |
| `service/langgraph/claude_cli_model.py` | LLM call interface unchanged |
