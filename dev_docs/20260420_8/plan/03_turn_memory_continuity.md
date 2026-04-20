# Plan/03 — 턴 간 대화 연속성 (assistant STM 기록 + 리트리버 L0 최근 턴 계층)

**목적.** `analysis/02_subworker_result_broadcast_gap.md` § Bug 2b
해결. VTuber가 SUB_WORKER_RESULT 턴 2분 뒤의 THINKING_TRIGGER에서
"아직 답이 없다"고 망각 응답하는 문제를 제거한다.

**구성.** 두 층의 결함 → 두 개 PR.

- **PR-4 (Geny)**: 2b-α — assistant 응답을 STM에 기록
- **PR-5 (geny-executor)**: 2b-β — retriever에 L0 recent-turns 계층 신설

PR-4만으로도 session_summary 및 STM 기반 경로가 회복되어 큰 개선.
PR-5는 보강 — 트리거 쿼리가 의미/키워드 매칭에 의존하지 않도록.

---

## PR-4 — `record_message("assistant", ...)` 호출 추가 (Geny)

### 범위 (Geny)

#### 4-1. `backend/service/langgraph/agent_session.py`

**`_invoke_pipeline`** (line 870-1039):

accumulated_output이 확정되는 지점 직후, `record_execution` 호출
*바로 앞*에 assistant 메시지 기록을 추가:

```python
# Record user input to short-term memory
if self._memory_manager:
    try:
        self._memory_manager.record_message("user", input_text)
    except Exception:
        logger.debug("Failed to record user message — non-critical", exc_info=True)

# ... (pipeline 실행, accumulated_output 누적) ...

# [NEW] Record assistant output to short-term memory before LTM write.
# Without this, STM transcript only contains user-side messages, and
# downstream retrieval (session_summary, keyword, vector) cannot see
# what the assistant actually said in the previous turn — which breaks
# trigger-driven continuity. See dev_docs/20260420_8/analysis/02.
if self._memory_manager and success and accumulated_output.strip():
    try:
        self._memory_manager.record_message(
            "assistant",
            accumulated_output[:10000],  # cap; STM은 transcript용
        )
    except Exception:
        logger.debug(
            "Failed to record assistant message — non-critical",
            exc_info=True,
        )

# Record to long-term memory (existing)
self._execution_count += 1
if self._memory_manager:
    try:
        await self._memory_manager.record_execution(...)
```

**`_astream_pipeline`** (line 1041-1195): 동일 로직 추가. 스트림 종료
시점에 `accumulated_output`이 완성되므로 loop exit 직후 삽입.

#### 4-2. 정교한 role tagging — 트리거/DM/사용자 메시지 구분

현재 `record_message("user", input_text)`는 모든 invoke 입력을 "user"
role로 기록한다. 이는 *사람이 친 메시지*와 *내부 자동 트리거*, *다른
에이전트가 보낸 DM*을 섞어버린다. 개선안:

| input_text 시작 태그 | 의미 | input role | output role |
|---|---|---|---|
| `[THINKING_TRIGGER:*]` | 내부 idle/reflection 트리거 | `internal_trigger` | `assistant` |
| `[ACTIVITY_TRIGGER:*]` | 내부 activity 트리거 | `internal_trigger` | `assistant` |
| `[SUB_WORKER_RESULT]` | Sub→VTuber 자동 리포트 | `assistant_dm` | `assistant` |
| `[SUB_WORKER_PROGRESS]` | Sub→VTuber 진행 업데이트 | `assistant_dm` | `assistant` |
| `[FROM_COUNTERPART]` 계열 | 카운터파트 간 DM (VTuber↔Sub) | `assistant_dm` | `assistant` |
| (그 외) | 실제 유저 입력 | `user` | `assistant` |

**`assistant_dm`**: 다른 에이전트가 이쪽으로 보낸 DM. "나(나 자신)"의
이전 발화가 아니라 "내 카운터파트/동료가 나에게 한 말". STM 읽는
쪽(retriever, session_summary 생성기)에서 "user 대화"처럼 취급하지
않고, 대화 다자성 맥락을 보존한다.

**`internal_trigger`**: 시스템이 자기 자신에게 보낸 자극. 유저 대화로
오인되면 안 된다 — 나중 턴에서 "아까 유저가 X라고 했는데..." 식의
잘못된 참조를 유발.

**STM 쪽 영향**: `short_term.add_message(role, ...)`는 `role` 값을
그대로 저장하므로 추가 코드 없이 이 새 role들을 받을 수 있다
(line 133 docstring은 `"user"/"assistant"/"system"`만 언급하지만,
실제 저장/조회 로직은 role-agnostic). docstring 업데이트 필요.

**Retriever 쪽 영향**: PR-5의 `_load_recent_turns`는 role 값을 그대로
`[{role}] {content}` 포맷으로 주입하므로 자동으로 새 role들을
지원한다. LLM이 "internal_trigger"/"assistant_dm" 라벨을 보고 해당
턴을 적절히 해석하도록 프롬프트 변경은 불필요 — 태그가 이미
content 내부에도 있음.

#### 4-3. `agent_session.py` role 결정 로직

`_invoke_pipeline` / `_astream_pipeline` 진입부:

```python
def _classify_input_role(input_text: str) -> str:
    """Map invoke input to the STM role it should be recorded under.

    Internal auto-triggers and inter-agent DMs must not be recorded as
    "user" — that would cause downstream reasoning to confuse system
    self-prompts and counterpart messages with real user input. See
    dev_docs/20260420_8/plan/03 § 4-2.
    """
    head = input_text.lstrip()[:64]
    if head.startswith("[THINKING_TRIGGER") or head.startswith("[ACTIVITY_TRIGGER"):
        return "internal_trigger"
    if (
        head.startswith("[SUB_WORKER_RESULT]")
        or head.startswith("[SUB_WORKER_PROGRESS]")
        or head.startswith("[FROM_COUNTERPART]")
    ):
        return "assistant_dm"
    return "user"
```

`record_message` 호출 시 이 함수를 쓴다:

```python
if self._memory_manager:
    try:
        self._memory_manager.record_message(
            _classify_input_role(input_text), input_text,
        )
    except Exception:
        logger.debug("Failed to record input message — non-critical", exc_info=True)
```

assistant 쪽은 항상 `"assistant"`.

#### 4-3. 회귀 테스트

파일: `tests/service/langgraph/test_agent_session_memory.py` (신규
또는 `test_agent_session.py`에 확장)

- `test_invoke_records_user_and_assistant_to_stm`:
  - MemoryManager mock, 평범한 유저 입력
  - `_invoke_pipeline("hello", ...)` 실행
  - `record_message`가 user(1회) + assistant(1회) 호출됨
- `test_thinking_trigger_classified_as_internal_trigger`:
  - input이 `[THINKING_TRIGGER:first_idle] ...`
  - `record_message`가 internal_trigger + assistant 로 호출됨
- `test_sub_worker_result_classified_as_assistant_dm`:
  - input이 `[SUB_WORKER_RESULT] Task completed...`
  - `record_message`가 assistant_dm + assistant 로 호출됨
- `test_stream_classifies_input_role_the_same_way`:
  - `_astream_pipeline` 동일 분류 로직
- `test_empty_output_does_not_record_assistant`:
  - pipeline이 빈 output으로 끝남 → assistant 호출 0회
- `test_failed_execution_does_not_record_assistant`:
  - success=False → assistant 호출 0회 (실패 기록은 `record_execution`
    이 처리)
- `test_assistant_record_is_non_critical`:
  - `record_message("assistant", ...)`이 예외 → invoke 결과는 정상

### 검증 (PR-4)

```bash
cd backend && pytest tests/service/langgraph -x -q
```

기존 메모리 관련 테스트 + 신규 5개 통과.

### 배포 관점

- STM transcript 파일이 *두 배* 쓰이게 됨 (user + assistant). 용량
  영향은 현실적으로 무시 가능 (일반적으로 수 MB/세션 수준)
- `record_message`의 DB dual-write 경로 (`db_stm_add_message`)가 이미
  assistant role을 정상 처리하고 있음 (`short_term.py:133` 주석:
  *"role: 'user', 'assistant', or 'system'"*)
- session_summary 생성 주기에 assistant 메시지가 자연스럽게 포함됨
  (기존 요약 프롬프트는 role-agnostic)

### 단독 효과

PR-5 없이도 이것만으로:
- STM transcript에 양쪽 대화가 쌓임
- 다음 session_summary reflection 시 assistant 응답 포함
- 키워드 검색이 이전 턴 응답에 매치 가능
- `_load_keyword_memory` 쿼리가 "Sub-Worker" 같은 단어를 포함하면 이전
  `[SUB_WORKER_RESULT]` 턴을 찾아낼 수 있음

트리거 턴에서도 "조용해졌다" 쿼리로는 여전히 못 찾음 — PR-5가 이를 보완.

---

## PR-5 — geny-executor retriever에 L0 recent-turns 계층 신설

### 범위 (geny-executor)

#### 5-1. `src/geny_executor/memory/retriever.py`

`GenyMemoryRetriever`에 L0 계층 신설. L1(session_summary) 앞에 배치.

**생성자 인수 추가**:

```python
def __init__(
    self,
    memory_manager: Any,
    *,
    enable_vector_search: bool = True,
    max_results: int = 5,
    max_inject_chars: int = 10000,
    search_chars: int = 500,
    llm_gate: Optional[Callable[[str], Awaitable[bool]]] = None,
    curated_knowledge_manager: Any = None,
    recent_turns: int = 6,   # [NEW] L0 tail size
):
    ...
    self._recent_turns = recent_turns
```

**`retrieve` 메서드 업데이트**:

```python
async def retrieve(self, query, state):
    ...
    chunks: List[MemoryChunk] = []
    total_chars = 0
    budget = self._max_inject

    # 0. Recent turns (tail of STM transcript) — always injected
    #    regardless of semantic/keyword match. Ensures trigger-style
    #    queries (idle reflection, auto-reports) still see the last
    #    few conversation turns.
    if self._recent_turns > 0:
        total_chars = self._load_recent_turns(chunks, total_chars, budget)

    # 1. Session summary (existing)
    total_chars = self._load_session_summary(chunks, total_chars, budget)
    ...
```

**`_load_recent_turns` 신설**:

```python
def _load_recent_turns(
    self,
    chunks: List[MemoryChunk],
    total: int,
    budget: int,
) -> int:
    """Inject the last N STM messages verbatim as a L0 memory chunk.

    Bypasses semantic/keyword matching: ensures auto-triggered turns
    (idle reflection, sub-worker auto-reports) see the most recent
    conversation regardless of lexical match.
    """
    try:
        stm = getattr(self._mgr, "short_term", None)
        if stm is None:
            return total
        get_recent = getattr(stm, "get_recent", None)
        if get_recent is None:
            return total

        recent = get_recent(self._recent_turns)
        if not recent:
            return total

        lines: List[str] = []
        for entry in recent:
            role = (
                entry.metadata.get("role", "user")
                if hasattr(entry, "metadata") and entry.metadata
                else "user"
            )
            content = getattr(entry, "content", "") or ""
            if not content.strip():
                continue
            lines.append(f"[{role}] {content.strip()}")

        if not lines:
            return total

        body = "\n".join(lines)
        # Budget: at most 40% of total so other layers can still fit
        max_body = min(len(body), int(budget * 0.4))
        if max_body < len(body):
            body = body[-max_body:]  # keep the most recent

        chunk_len = len(body)
        if (total + chunk_len) > budget:
            return total

        chunks.append(
            MemoryChunk(
                key="recent_turns",
                content=body,
                source="short_term",
                relevance_score=1.0,
                metadata={
                    "layer": "recent_turns",
                    "turns": len(lines),
                },
            )
        )
        return total + chunk_len

    except Exception:
        logger.debug("geny_retriever: recent turns load failed", exc_info=True)
        return total
```

`get_recent(n)`은 Geny의 `ShortTermMemory`가 이미 제공한다
(`backend/service/memory/short_term.py:320` 주변 — DB 우선, 파일
폴백). duck-typed 의존이므로 executor 측은 속성 존재 여부만 체크.

#### 5-2. Geny 측 파이프라인 인수 연결

`backend/service/langgraph/agent_session.py:785-789` 에서 `recent_turns`
인수 전달:

```python
attach_kwargs["memory_retriever"] = GenyMemoryRetriever(
    self._memory_manager,
    max_inject_chars=max_inject_chars,
    enable_vector_search=True,
    curated_knowledge_manager=curated_km,
    recent_turns=6,  # [NEW] L0 tail
)
```

이는 PR-5 머지 후 executor 버전을 0.28.0으로 올리면서 같이 반영
(executor 버전 floor 업데이트는 PR-5의 Geny 측 follow-up 커밋).

#### 5-3. 회귀 테스트 (executor 측)

파일: `tests/unit/test_geny_retriever_recent_turns.py` (신규)

- `test_recent_turns_injected_as_l0`:
  - STM mock with 8 messages → retrieve() → 첫 chunk가 recent_turns,
    최근 6개 포함
- `test_recent_turns_disabled_when_zero`:
  - `recent_turns=0` → chunks에 recent_turns 없음
- `test_recent_turns_budget_capped`:
  - 매우 긴 메시지 → budget의 40% 초과 안 함
- `test_recent_turns_missing_get_recent_skipped`:
  - STM이 `get_recent` 없음 → 조용히 스킵, 다른 layer 정상 동작
- `test_recent_turns_precedes_session_summary_in_chunks`:
  - chunks[0].key == "recent_turns", chunks[1+].source != "short_term"
    또는 "recent_turns"
- `test_trigger_style_query_finds_prior_subworker_result`:
  - STM에 `[SUB_WORKER_RESULT] Task completed...` 메시지 있음
  - retrieve("[THINKING_TRIGGER:continued_idle] 여전히 조용하다")
  - 반환된 chunks의 recent_turns 내용에 "SUB_WORKER_RESULT"가 포함됨
  - → **Bug 2b-β 시나리오의 end-to-end 검증**

### 검증 (PR-5)

```bash
cd ~/workspace/geny-executor && pytest tests/unit/test_geny_retriever_recent_turns.py -x -q
```

기존 executor suite(`1046 passed, 18 skipped`)도 회귀 없어야 함.

#### 5-4. Executor 버전 + CHANGELOG

- `pyproject.toml` / `__init__.py`: `0.27.0` → `0.28.0` (additive — 신규
  생성자 인수, 기존 호출자는 기본값 `recent_turns=6`으로 동작. 호환성
  유지)
- `CHANGELOG.md`: L0 recent-turns layer 추가 기록

#### 5-5. Geny 측 executor floor 업데이트 (PR-5 후속 커밋)

- `backend/pyproject.toml` / `requirements.txt`:
  `geny-executor>=0.27.0,<0.28.0` → `>=0.28.0,<0.29.0`
- `agent_session.py`의 `recent_turns=6` 전달 커밋과 같이 올림

### 단독 효과 / PR-4와의 결합

- **PR-5만 머지**: STM에 assistant 메시지가 없어도 user 측 메시지는
  전부 tail 주입됨 → 최소한 이전 user 입력(`[SUB_WORKER_RESULT] Task
  completed...`)은 맥락으로 들어감. VTuber가 "아직 답이 없다"고
  말하지 않을 가능성이 크지만, 자기 응답(`와! Sub-Worker가...`)을
  기억하지는 못함
- **PR-4 + PR-5**: 양방향 대화가 tail에 보존됨 → 완전한 맥락

---

## 라이브 스모크 체크리스트 (PR-4 + PR-5 머지 후)

1. 서비스 재시작 (executor 0.28.0 로드)
2. VTuber 세션 생성 → Sub-Worker 자동 링크
3. 유저: "Sub-Worker에게 test.txt 파일을 만들라고 해줘"
4. Sub-Worker Write 성공, VTuber 응답 브로드캐스트 (plan/02 효과)
5. **2분 대기 → continued_idle THINKING_TRIGGER 발동**
6. **새 체크**: VTuber의 트리거 응답이 "Sub-Worker가 방금 test.txt를
   만들었다"는 인식을 반영함 — "아직 답이 없다" 류 발언이 **없음**
7. STM transcript 파일 확인: user 입력 + assistant 응답 양쪽이 기록됨
8. Retriever 로그 확인: `geny_retriever: loaded N chunks (... chars)`
   에서 N이 이전보다 증가 (recent_turns 추가)

## 완료 기준 (plan/03 단독)

- 스모크 6번 일관되게 동작
- PR-4 테스트 5개 + PR-5 테스트 6개 전부 통과
- 기존 retriever/memory 테스트 회귀 없음
- 성능 영향: recent_turns 로딩 추가로 retrieve() 평균 지연 <5ms 상승
  예상 (STM DB read 한 번 추가)

## 비범위

- 트리거 태그 기반 role tagging (`internal_trigger` 같은 새 role) —
  추후 cycle
- Vector search 재가중 / `[SUB_WORKER_RESULT]` 전용 boost — L0 계층
  효과가 충분하므로 이번엔 생략
- STM 크기 제한 / rolling window 정책 변경 — 현 구조 유지
