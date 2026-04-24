# Thinking Trigger 시스템 심층 분석 리포트

> **작성일**: 2025-07
> **대상 코드**: `geny/backend/service/vtuber/thinking_trigger.py` 및 관련 워크플로우 노드
> **목적**: 비용 최적화 및 제어 기능 설계를 위한 현황 분석

---

## 1. 시스템 개요

Thinking Trigger는 VTuber 세션이 일정 시간 이상 유휴 상태일 때 **자발적 사고(self-initiated thinking)**를 발생시키는 백그라운드 서비스이다. 사용자와 대화가 없는 동안에도 VTuber가 "살아 있는" 느낌을 주기 위해 설계되었다.

### 핵심 파라미터

| 파라미터 | 값 | 설명 |
|---|---|---|
| `_DEFAULT_IDLE_THRESHOLD` | **120초** (2분) | 마지막 활동 후 트리거 발화까지 대기 시간 |
| Polling interval | **30초** | `_loop()`의 `asyncio.sleep(30)` |
| Prompt variants | **4개** + CLI-aware 1개 | 총 5가지 트리거 프롬프트 |

---

## 2. 메시지 흐름 (전체 파이프라인)

```
ThinkingTriggerService._loop()         (30초 폴링)
  │
  ▼ idle >= 120초?
  │
  ▼ _fire_trigger(session_id)
  │   └─ _build_trigger_prompt()      CLI 실행 중이면 _CLI_AWARE_PROMPT 선택
  │   └─ execute_command(session_id, prompt)
  │
  ▼ VTuber Workflow Graph 실행
  │
  ├─ START
  ├─ memory_inject                    ← 메모리 주입 (LLM 호출 없음)
  ├─ vtuber_classify                  ← ⚡ Fast-path: [THINKING_TRIGGER] 감지 → LLM 호출 없이 바로 "thinking" 라우팅
  ├─ vtuber_think                     ← 🔴 LLM 호출 #1 (resilient_invoke)
  ├─ memory_reflect                   ← 🔴 LLM 호출 #2 (resilient_structured_invoke)
  └─ END
  │
  ▼ _save_to_chat_room()              DB 저장 + SSE 실시간 알림
```

### 핵심 관찰

1. **classify 노드는 무료**: `[THINKING_TRIGGER]` 접두사를 감지하면 LLM을 호출하지 않고 즉시 `vtuber_route="thinking"`으로 라우팅
2. **vtuber_think 노드**: 메인 LLM 호출. **일반 VTuber 응답과 동일한 모델** 사용 (`context.resilient_invoke`)
3. **memory_reflect 노드**: 실행 결과를 분석하여 인사이트를 추출하는 **두 번째 LLM 호출**
4. **[SILENT] 응답도 memory_reflect를 통과**: vtuber_think가 `[SILENT]`을 반환해도 워크플로우는 memory_reflect로 진행됨

---

## 3. 비용 분석

### 3.1 트리거 1회당 비용

| 단계 | LLM 호출 | 예상 토큰 (입력+출력) | 비고 |
|---|---|---|---|
| memory_inject | 없음 | 0 | 메모리 파일 읽기만 |
| vtuber_classify | **없음** (fast-path) | 0 | `[THINKING_TRIGGER]` 감지 시 스킵 |
| vtuber_think | **1회** | ~300–800 토큰 | 프롬프트(~200) + 메모리 컨텍스트 + 응답(~100–400) |
| memory_reflect | **1회** | ~400–1,200 토큰 | 입력(2000자 제한) + 출력(3000자 제한) + JSON 응답 |
| **합계** | **2회** | **~700–2,000 토큰** | |

### 3.2 시간당/일당 비용 (Claude Sonnet 4 기준)

| 시나리오 | 트리거 횟수 | 예상 비용 |
|---|---|---|
| 유휴 1시간 (1 세션) | **~20회** (120초 간격, 30초 폴링) | **$0.03–$0.10** |
| 유휴 8시간 (1 세션) | **~160회** | **$0.24–$0.80** |
| 유휴 24시간 (1 세션) | **~480회** | **$0.72–$2.40** |
| 유휴 24시간 (3 세션) | **~1,440회** | **$2.16–$7.20** |

> **참고**: 실제 비용은 모델, 메모리 컨텍스트 크기, [SILENT] 비율에 따라 변동됨.
> Claude Sonnet 4 입력: $3/1M tokens, 출력: $15/1M tokens 기준 추정.

### 3.3 [SILENT] 응답의 숨은 비용

vtuber_think가 `[SILENT]`을 반환하는 경우:
- **vtuber_think LLM 호출**: 발생 (피할 수 없음)
- **memory_reflect LLM 호출**: **발생** (`is_complete=True`만 설정, `final_answer` 없음 → `output_text` 빈 문자열 → `memory_reflect` 내부에서 empty check로 스킵될 **가능성**)

코드 확인 결과:
```python
# memory_reflect_node.py (line 157-162)
if not input_text.strip() or not output_text.strip():
    logger.debug("memory_reflect: empty input/output — skipping")
    return {}
```

[SILENT] 시 `final_answer`, `answer`, `last_output` 모두 미설정 → `output_text = ""` → **스킵됨**.
단, `input_text`는 트리거 프롬프트가 있으므로 비어있지 않음. 따라서 **output이 비어있을 때만 스킵**.

**결론**: [SILENT] 경우 memory_reflect의 LLM 호출은 **스킵**되지만, 노드 자체는 실행됨 (메모리 매니저 접근, 상태 필드 읽기 등 minor overhead).

---

## 4. 현재 아키텍처의 문제점

### 4.1 제어 메커니즘 부재 🔴

```python
# main.py — 앱 시작 시 무조건 시작
thinking_trigger = get_thinking_trigger_service()
thinking_trigger.start()

# agent_session_manager.py — VTuber 세션 생성 시 무조건 등록
get_thinking_trigger_service().record_activity(session_id)
```

- **세션별 on/off 불가**: 모든 VTuber 세션에 일괄 적용
- **전역 on/off 불가**: 앱 라이프사이클에 묶여 있음 (start/stop만 존재)
- **사용자 UI 없음**: Info 페이지에 설정 항목 없음

### 4.2 고정된 타이밍 🟡

- `_DEFAULT_IDLE_THRESHOLD = 120` 하드코딩
- 폴링 간격 30초 하드코딩
- 사용 패턴에 따른 적응형 조절 없음

### 4.3 동일 모델 사용 🔴

```python
# vtuber_think_node.py
response, fallback = await context.resilient_invoke(messages, "vtuber_think")
```

`resilient_invoke`는 세션에 할당된 모델을 그대로 사용. 일반 응답(Sonnet 4)과 동일한 비싼 모델로 내부 독백을 생성.

### 4.4 토큰 예산 제한 없음 🟡

- 일일/시간당 thinking trigger 횟수 제한 없음
- 비용 누적 추적 없음
- 세션이 계속 유휴면 120초마다 무한히 트리거

### 4.5 프롬프트 다양성 제한 🟢 (minor)

- 4개 한국어/영어 프롬프트 + 1개 CLI-aware
- 시간이 지나면 반복적이고 예측 가능한 반응 생성 가능

---

## 5. 관련 코드 인벤토리

| 파일 | 역할 | LLM 호출 |
|---|---|---|
| `service/vtuber/thinking_trigger.py` | 백그라운드 서비스, 폴링/발화 | 없음 |
| `service/workflow/nodes/vtuber/vtuber_classify_node.py` | 입력 분류 (fast-path) | **없음** (trigger 시) |
| `service/workflow/nodes/vtuber/vtuber_think_node.py` | 내부 독백 생성 | **1회** |
| `service/workflow/nodes/memory/memory_reflect_node.py` | 인사이트 추출 | **0~1회** (output 유무) |
| `service/execution/agent_executor.py` | `record_activity()` 호출 | 없음 |
| `service/executor/agent_session_manager.py` | VTuber 생성 시 자동 등록 | 없음 |
| `main.py` | 서비스 시작/종료 | 없음 |
| `service/workflow/templates.py` | VTuber 워크플로우 그래프 정의 | 없음 |

---

## 6. 최적화 전략 제안

### 6.1 세션별 Enable/Disable 토글 [우선순위: 높음]

**변경 범위**: ThinkingTriggerService + 세션 설정 + Info 페이지 UI

```
ThinkingTriggerService:
  - _disabled_sessions: Set[str]  # 비활성화된 세션 목록
  - enable(session_id)
  - disable(session_id)
  - is_enabled(session_id) -> bool

_loop() 수정:
  if sid in self._disabled_sessions:
      continue
```

**예상 효과**: 불필요한 세션의 트리거를 즉시 차단. 비용 절감의 가장 직접적인 방법.

### 6.2 Configurable Idle Threshold [우선순위: 중간]

```
ThinkingTriggerService:
  - _session_thresholds: Dict[str, float]  # 세션별 유휴 임계값
  - set_threshold(session_id, seconds)

기본값: 120초 (현행 유지)
UI: Info 페이지 슬라이더 (60초 ~ 600초)
```

**예상 효과**: 세션 용도에 따라 빈도 조절. 데모용(짧게) vs 작업용(길게).

### 6.3 Thinking 전용 경량 모델 [우선순위: 높음]

현재 `resilient_invoke`는 세션의 기본 모델을 사용. 내부 독백은 고품질 모델이 필요하지 않음.

**방안 A**: 노드 config에 `model_override` 파라미터 추가
```python
# vtuber_think_node.py
model_name = config.get("model_override", None)
if model_name:
    context.use_model(model_name)  # 저렴한 모델로 교체
```

**방안 B**: ThinkingTriggerService가 트리거 시 모델 힌트 전달
```python
execute_command(session_id, prompt, model_hint="haiku")
```

**예상 효과**: Haiku급 모델 사용 시 비용 ~1/10~1/5 수준으로 절감.

### 6.4 일일 트리거 예산 (Daily Budget Cap) [우선순위: 중간]

```
ThinkingTriggerService:
  - _daily_counts: Dict[str, int]
  - _daily_limit: int = 100  # 기본 100회/일
  - _daily_cost_limit_usd: float = 1.0

_fire_trigger() 앞에서 체크:
  if self._daily_counts[sid] >= self._daily_limit:
      return  # 예산 초과, 스킵
```

**예상 효과**: 과도한 비용 누적 방지. 예측 가능한 비용 관리.

### 6.5 적응형 빈도 조절 [우선순위: 낮음]

사용자 활동 패턴에 기반한 지능적 빈도 조절:
- 사용자가 자주 돌아오는 패턴 → 짧은 idle threshold
- 장시간 부재 패턴 → threshold를 점진적으로 증가 (exponential backoff)

```python
# 예: 첫 번째 트리거 후 idle가 계속되면 다음 트리거까지 대기 시간을 2배로
trigger_count = 0
next_threshold = base_threshold * (2 ** min(trigger_count, 5))
```

**예상 효과**: 장기 유휴 시 불필요한 트리거 자연 감소.

### 6.6 Memory Reflect 조건부 스킵 [우선순위: 중간]

현재 [SILENT] 응답 시 memory_reflect는 empty output으로 자동 스킵되지만, 일반 thinking 응답도 매번 reflect할 필요는 없음.

**방안**: memory_reflect에 `skip_for_thinking` 설정 추가, 또는 vtuber_think 노드에서 직접 END로 라우팅하는 별도 edge 추가.

```
vtuber_think ─── [SILENT] ──→ END  (memory_reflect 완전 스킵)
             └── [normal] ──→ memory_reflect → END
```

---

## 7. 구현 우선순위 매트릭스

| # | 전략 | 구현 난이도 | 비용 절감 효과 | 추천 순서 |
|---|---|---|---|---|
| 6.1 | 세션별 Enable/Disable | ⭐ 낮음 | ⭐⭐⭐ 높음 | **1순위** |
| 6.3 | 경량 모델 사용 | ⭐⭐ 중간 | ⭐⭐⭐ 높음 | **2순위** |
| 6.2 | Configurable Threshold | ⭐ 낮음 | ⭐⭐ 중간 | 3순위 |
| 6.4 | Daily Budget Cap | ⭐⭐ 중간 | ⭐⭐ 중간 | 4순위 |
| 6.6 | Memory Reflect 조건부 스킵 | ⭐⭐ 중간 | ⭐ 낮음 | 5순위 |
| 6.5 | 적응형 빈도 조절 | ⭐⭐⭐ 높음 | ⭐⭐ 중간 | 6순위 |

---

## 8. 즉시 실행 가능한 최소 변경 (Quick Win)

### Info 페이지 토글만 추가하는 경우

**Backend 변경**:
1. `ThinkingTriggerService`에 `_disabled_sessions: Set[str]` 추가
2. `enable(sid)` / `disable(sid)` / `is_enabled(sid)` 메서드 추가
3. `_loop()` 에서 `_disabled_sessions` 체크
4. REST API endpoint 1개: `PUT /api/sessions/{id}/thinking-trigger` (body: `{"enabled": bool}`)

**Frontend 변경**:
1. Info 페이지에 토글 스위치 1개 추가
2. API 연동

**예상 작업량**: Backend ~50줄, Frontend ~30줄, API ~20줄

---

## 9. 참고: 트리거 프롬프트 현황

```python
_TRIGGER_PROMPTS = [
    "[THINKING_TRIGGER] You've been idle for a while. Reflect on recent conversations...",
    "[THINKING_TRIGGER] 잠깐 여유가 생겼네. 최근 대화를 돌아보거나...",
    "[THINKING_TRIGGER] 조용한 시간이야. 재미있는 관찰이나 팁을...",
    "[THINKING_TRIGGER] 사용자가 잠깐 자리를 비운 것 같아...",
]

_CLI_AWARE_PROMPT = "[THINKING_TRIGGER] CLI 에이전트가 지금 작업 중이야..."
```

5개 프롬프트가 `random.choice()`로 선택됨. CLI 에이전트가 실행 중이면 `_CLI_AWARE_PROMPT`가 우선 사용됨.
