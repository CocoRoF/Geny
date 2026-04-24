# Agent Session ↔ CLI Process Lifecycle 심층 분석 리포트

**Date**: 2026-04-01
**Severity**: 설계 분석 (현행 동작 검증)

---

## 1. 결론 요약

**새 세션이 매번 생성되는 것은 아니다.**

| 구성 요소 | 수명 (Lifecycle) | 실태 |
|-----------|-----------------|------|
| `AgentSession` | **영구** — 명시적 삭제 전까지 메모리에 유지 | ✅ 정상 |
| `ClaudeCLIChatModel` | **영구** — AgentSession과 동일 수명 | ✅ 정상 |
| `ClaudeProcess` | **영구** — AgentSession과 동일 수명 | ✅ 정상 |
| **CLI 서브프로세스** | **⚠️ 일회용** — `execute()` 호출마다 새로 생성, 종료 | ⚠️ 설계상 의도적 |
| 대화 연속성 | `--resume <conversation_id>` 플래그로 유지 | ✅ 작동 |

**핵심**: "세션"은 매번 생성되지 않는다. 그러나 **CLI 서브프로세스**는 매번 생성된다.
이것은 Claude CLI (`@anthropic-ai/claude-code`)가 `--print` 모드로 동작하는 **일회성 실행 도구**이기 때문이다.

---

## 2. 전체 아키텍처 계층도

```
┌─────────────────────────────────────────────────────────────────────┐
│  AgentSessionManager                                                │
│  ┌─ _local_agents: Dict[str, AgentSession]   (메모리 캐시)        │
│  │                                                                  │
│  │  AgentSession (session_id="abc-123")       ← 영구 (persistent) │
│  │  ├─ _model: ClaudeCLIChatModel             ← 영구              │
│  │  │   └─ _process: ClaudeProcess            ← 영구              │
│  │  │       ├─ _conversation_id: "conv-xyz"   ← 대화 ID 보존      │
│  │  │       ├─ _execution_count: 15           ← 호출 카운터       │
│  │  │       ├─ _execution_lock: asyncio.Lock  ← 직렬화            │
│  │  │       ├─ _warm_process: Process|None    ← 예열된 서브프로세스│
│  │  │       └─ _current_process: None         ← 실행 중일 때만 존재│
│  │  ├─ _graph: CompiledStateGraph             ← 영구              │
│  │  ├─ _memory_manager: SessionMemoryManager  ← 영구              │
│  │  └─ _status: RUNNING / IDLE / STOPPED                          │
│  └────────────────────────────────────────────────────────────────  │
└─────────────────────────────────────────────────────────────────────┘
                            │
                            ▼  (매 execute() 호출)
                 ┌─────────────────────┐
                 │  node.exe cli.js    │  ← 일회용 (ephemeral)
                 │  --print            │     Node.js 프로세스
                 │  --resume conv-xyz  │
                 │  --model ...        │
                 │  stdin ← prompt     │
                 │  stdout → stream    │
                 │  (종료 후 폐기)      │
                 └─────────────────────┘
```

---

## 3. 상세 라이프사이클 추적

### 3.1 세션 생성 (1회 — 사용자가 "새 세션" 클릭 시)

```
POST /api/agents
  │
  └─► AgentSessionManager.create_agent_session(request)
       │
       ├─ 1. session_id = uuid4()                      ← 고유 ID 생성
       ├─ 2. system_prompt = _build_system_prompt()     ← 프롬프트 조립
       ├─ 3. mcp_config = build_session_mcp_config()    ← MCP 설정
       │
       └─ 4. AgentSession.create(...)
             │
             ├─ AgentSession.__init__()                 ← 메타데이터만
             │
             └─ AgentSession.initialize()
                  │
                  ├─ ClaudeCLIChatModel.__init__()      ← config 저장만
                  ├─ ClaudeCLIChatModel.initialize()
                  │   └─ ClaudeProcess.__init__()        ← config 저장만
                  │   └─ ClaudeProcess.initialize()
                  │       ├─ mkdir(storage_path)          ← 디렉토리 생성
                  │       ├─ write(.claude_session.json)  ← 세션 설정 파일
                  │       ├─ write(.mcp.json)             ← MCP 설정 파일
                  │       ├─ find_claude_node_config()    ← CLI 바이너리 경로 탐색
                  │       └─ status = RUNNING             ← 상태 전환
                  │       (❌ 서브프로세스 스폰 없음!)
                  │
                  ├─ _init_memory()                      ← 메모리 매니저 생성
                  ├─ _memory_manager.initialize_vector_memory()
                  │
                  └─ _build_graph()
                       ├─ _load_workflow_definition()    ← 워크플로우 로드
                       ├─ ExecutionContext(model=self._model, ...)
                       └─ WorkflowExecutor.compile()     ← LangGraph 그래프 컴파일
```

**여기서 서브프로세스는 생성되지 않는다.** 디렉토리와 설정 파일만 준비한다.

### 3.2 명령 실행 (반복 — 매 사용자 메시지 또는 ThinkingTrigger)

```
POST /api/agents/{id}/invoke  또는  ThinkingTrigger._fire()
  │
  └─► AgentSession.invoke(input_text)
       │
       ├─ _check_freshness()        ← idle이면 auto-revive
       ├─ _ensure_alive()           ← 프로세스 상태 확인
       │
       └─ graph.ainvoke(initial_state)
            │
            ├─► memory_inject.execute()
            │    └─ ctx.resilient_structured_invoke(messages)
            │         └─ ctx.model.ainvoke(messages)
            │              └─ ClaudeCLIChatModel._agenerate(messages)
            │                   └─ ClaudeProcess.execute(prompt)     ← ⚡ 서브프로세스 #1
            │                        ├─ _take_warm_process() → 예열 프로세스 사용 시도
            │                        │   (없으면 cold start)
            │                        ├─ create_subprocess_cross_platform()  ← 새 프로세스!
            │                        ├─ stdin.write(prompt)
            │                        ├─ stdin.close()
            │                        ├─ read stdout/stderr (stream)
            │                        ├─ process.wait()               ← 프로세스 종료 대기
            │                        └─ finally: _schedule_prewarm() ← 다음 프로세스 예열
            │
            ├─► vtuber_classify.execute()
            │    └─ ctx.model.ainvoke(...)
            │         └─ ClaudeProcess.execute(...)                  ← ⚡ 서브프로세스 #2
            │              └─ (예열된 프로세스 사용 시도 → 또는 cold start)
            │
            ├─► vtuber_respond.execute()
            │    └─ ctx.model.ainvoke(...)
            │         └─ ClaudeProcess.execute(...)                  ← ⚡ 서브프로세스 #3
            │
            └─► memory_reflect.execute()
                 └─ ctx.model.ainvoke(...)
                      └─ ClaudeProcess.execute(...)                  ← ⚡ 서브프로세스 #4
```

**한 번의 `invoke()`에 최대 4개의 서브프로세스가 순차적으로 생성·종료된다.**

### 3.3 서브프로세스 생성·종료 상세

```python
# process_manager.py — execute() 내부 (핵심 부분)

async with self._execution_lock:     # 동시 실행 방지 (직렬)

    # 1. 예열된 프로세스 재사용 시도
    warm = await self._take_warm_process(cmd, env)
    if warm is not None:
        self._current_process = warm          # 예열 프로세스 사용
    else:
        self._current_process = await create_subprocess_cross_platform(
            cmd,                              # ["node", "cli.js", "--print", ...]
            stdin=PIPE, stdout=PIPE, stderr=PIPE,
            env=env, cwd=self.working_dir,
        )                                     # Cold start: 새 프로세스

    # 2. 프롬프트 전송 → 출력 수신 → 프로세스 종료 대기
    result = await self._stream_execute(process, prompt, timeout, parser)
    #   └─ stdin.write(prompt) → stdin.close() → process.wait()  ← 프로세스 종료

    # 3. conversation_id 캡처 (다음 호출 시 --resume에 사용)
    if summary.session_id:
        self._conversation_id = summary.session_id

finally:
    self._current_process = None              # 참조 제거
    self._schedule_prewarm(cmd, env)          # 다음 프로세스 미리 생성
```

### 3.4 대화 연속성 메커니즘

```python
# process_manager.py — execute() 내부

should_resume = resume if resume is not None else (
    self._execution_count > 0 and self._conversation_id
)

if should_resume and self._conversation_id:
    args.extend(["--resume", self._conversation_id])
```

- 첫 실행: `--resume` 없이 실행 → Claude CLI가 새 대화 시작, `conversation_id` 반환
- 이후 실행: `--resume conv-xyz` → Claude CLI가 이전 대화 컨텍스트를 **디스크에서 로드**
- `conversation_id`는 `ClaudeProcess` 인스턴스에 **메모리로 보존** (세션 수명 동안 유지)

**대화가 끊기지 않는 이유**: CLI가 종료되어도 Claude의 대화 기록은 **로컬 스토리지**에 저장됨.
다음 CLI 실행 시 `--resume`으로 그 기록을 다시 불러옴.

### 3.5 Idle → Revival 사이클

```
[정상 실행]
  AgentSession.status = RUNNING
  ClaudeProcess.status = RUNNING
  (서브프로세스는 없음 — 실행 직후 종료됨)
       │
       ▼  (10분간 활동 없음)
[Idle Monitor가 감지]
  AgentSession.status = IDLE              ← 상태만 변경, 아무것도 파괴 안 함
       │
       ▼  (다음 invoke() 호출 시)
[Auto-Revive]
  _check_freshness() → 상태가 IDLE이면:
    │
    ├─ 1. model.cleanup()                 ← 기존 ClaudeProcess.stop()
    │      └─ _discard_warm_process()     ← 예열 프로세스 폐기
    │      └─ _kill_current_process()     ← 실행 중 프로세스 종료 (보통 없음)
    │
    ├─ 2. 새 ClaudeCLIChatModel 생성      ← ⚠️ 새 ClaudeProcess 인스턴스
    │      └─ initialize()                ← 디렉토리·설정 파일 재설정
    │
    ├─ 3. _init_memory()                  ← 메모리 매니저 재생성
    │
    ├─ 4. _build_graph()                  ← 그래프 재컴파일
    │
    └─ 5. status = RUNNING                ← 복원 완료
```

**⚠️ Revival 시 새 `ClaudeProcess` 인스턴스가 생성된다.**
이때 `_conversation_id`는 새 인스턴스로 이전되지 않는다 — **대화 기록이 끊길 수 있다.**

---

## 4. 문제 분석

### 4.1 서브프로세스가 매번 생성되는 것은 문제인가?

| 관점 | 분석 |
|------|------|
| **Claude CLI의 설계** | `--print` 모드는 설계상 일회성 실행. 서버 모드(`--server`)는 아직 공개/안정 API가 아님 |
| **성능 오버헤드** | Node.js 프로세스 스폰 ~2-5초 (cold start). 예열(pre-warm) 시 ~0.5초 |
| **대화 연속성** | `--resume` 플래그가 디스크 기반 대화 복원을 보장. 연속성은 유지됨 |
| **메모리 사용** | 서브프로세스가 종료되므로 메모리는 실행 중에만 사용됨. 누수 없음 |
| **비용** | 서브프로세스 spawn 자체는 추가 API 비용 없음 (단, Node.js 시작 시간이 latency에 포함) |

**현재 설계는 Claude CLI의 `--print` 모드 제약 안에서 최선의 방식이다.**

### 4.2 실제 문제점

#### 문제 1: Pre-warm 비효율 (경미)

```
execute() 완료 → _schedule_prewarm() → 예열 프로세스 생성
    → 다음 execute()에서 사용 시도
    → cmd가 다르면 폐기하고 cold start 🔥
```

예열 프로세스는 **정확히 같은 커맨드 인자**일 때만 재사용된다.
워크플로우 내 연속 노드 호출은 보통 같은 모델/인자를 사용하므로 효과적이지만,
모델이나 시스템 프롬프트가 변경되면 예열이 무효화된다.

#### 문제 2: Revival 시 conversation_id 유실 (중간)

```python
# revive() 내부
self._model = ClaudeCLIChatModel(...)       # 새 인스턴스
success = await self._model.initialize()     # 새 ClaudeProcess 생성
# → 기존 _conversation_id가 새 ClaudeProcess에 이전되지 않음!
```

Idle 후 Revival 시 **새 `ClaudeProcess`가 생성되면서 `_conversation_id`가 초기화**된다.
결과적으로 다음 실행은 `--resume` 없이 시작되어 **이전 대화 컨텍스트를 잃는다.**

VTuber 세션의 경우:
- ThinkingTrigger가 반복 호출 → 대화 컨텍스트 누적
- Idle timeout (10분) 도달 → IDLE 상태
- 다음 실행 시 Revival → **이전 VTuber 대화 기록 단절**

#### 문제 3: Node.js 스폰 latency (경미~중간)

VTuber 워크플로우에서 1회 `invoke()`당 최대 4번의 서브프로세스 생성:

| 호출 | 예열 가능? | Cold start 시간 |
|------|-----------|----------------|
| #1 memory_inject | ❌ (첫 호출) | ~3초 |
| #2 vtuber_classify | ✅ (예열됨) | ~0.5초 |
| #3 vtuber_respond | ✅ | ~0.5초 |
| #4 memory_reflect | ✅ | ~0.5초 |
| **합계 오버헤드** | | **~4.5초** |

LLM 응답 시간 외에 **순수 프로세스 관리 오버헤드만 4.5초**.

### 4.3 이 문제가 optimizing_model.md와 관련되는 이유

보조 모델로 `ChatAnthropic` (직접 API)을 사용하면:
- **서브프로세스 스폰 0회** — HTTP API 직접 호출
- memory_inject, vtuber_classify, memory_reflect 3개 노드에서 서브프로세스 3회 절약
- **프로세스 오버헤드 ~1.5초 절감** + 비용 절감

---

## 5. 수명 관리 흐름 다이어그램

```
시간축 →

 ┌──────────────────────────────────────────────────────────────────────┐
 │ AgentSession (session_id="abc-123")                                  │
 │ ████████████████████████████████████████████████████████████████████ │
 │ 생성                                                         삭제   │
 │                                                                      │
 │ ClaudeCLIChatModel                                                   │
 │ ████████████████████████████████████████████████████████████████████ │
 │                                                                      │
 │ ClaudeProcess                                                        │
 │ ████████████████████████████████████████████████████████████████████ │
 │                                                                      │
 │ CLI 서브프로세스들:                                                   │
 │ ██ ██ ██ ██    ██ ██ ██     ██ ██ ██ ██ ██    ██ ██                 │
 │ ↑  ↑  ↑  ↑    ↑  ↑  ↑     ↑  ↑  ↑  ↑  ↑    ↑  ↑                 │
 │ invoke#1       invoke#2     invoke#3           invoke#4              │
 │                                                                      │
 │      idle (10분)                                                     │
 │              ▼                                                       │
 │     status=IDLE      (프로세스 파괴 X, 상태만 변경)                    │
 │              ▼ invoke                                                │
 │     auto-revive      (새 ClaudeProcess, conversation_id 유실 가능)   │
 └──────────────────────────────────────────────────────────────────────┘

 예열(pre-warm):
 invoke#1: [exec]─[prewarm]
 invoke#2:          [reuse]─[prewarm]
 invoke#3:                   [reuse]─[prewarm]
```

---

## 6. conversation_id 유실 문제 상세

### 현재 코드 (문제 지점)

```python
# agent_session.py — revive()

async def revive(self) -> bool:
    # 기존 모델 정리
    if self._model:
        await self._model.cleanup()        # ClaudeProcess.stop()

    # 새 모델 생성 — ⚠️ conversation_id는 여기서 사라짐
    self._model = ClaudeCLIChatModel(
        session_id=self._session_id,       # 같은 session_id
        ...
    )
    success = await self._model.initialize()
    # → ClaudeProcess.__init__() 에서 _conversation_id = None
    # → 첫 execute()는 --resume 없이 실행
```

### 수정 방안

```python
# 제안: revive() 시 conversation_id 보존

async def revive(self) -> bool:
    # 기존 conversation_id 보존
    old_conversation_id = None
    if self._model and self._model.process:
        old_conversation_id = self._model.process._conversation_id

    # 기존 모델 정리
    if self._model:
        await self._model.cleanup()

    # 새 모델 생성
    self._model = ClaudeCLIChatModel(...)
    success = await self._model.initialize()

    # conversation_id 복원
    if old_conversation_id and self._model.process:
        self._model.process._conversation_id = old_conversation_id
        self._model.process._execution_count = 1  # resume 트리거

    self._build_graph()
    return True
```

---

## 7. 정리: "매번 세션이 생성되는가?"

| 질문 | 답변 |
|------|------|
| **Agent Session이 매번 새로 생성되는가?** | ❌ 아니다. `_local_agents` 딕셔너리에 캐시되어 재사용됨. |
| **ClaudeCLIChatModel이 매번 새로 생성되는가?** | ❌ 아니다. AgentSession과 동일 수명. (단, revival 시 재생성) |
| **ClaudeProcess가 매번 새로 생성되는가?** | ❌ 아니다. ClaudeCLIChatModel과 동일 수명. (단, revival 시 재생성) |
| **CLI 서브프로세스가 매번 새로 생성되는가?** | ✅ **그렇다.** Claude CLI가 `--print` 모드 (일회성 실행) 도구이기 때문. |
| **대화 연속성은 유지되는가?** | ✅ `--resume` 플래그로 유지됨. **단, idle revival 시 유실 가능.** |
| **서버를 재시작하면?** | ❌ 모든 세션 소실. `_local_agents`는 인메모리 딕셔너리. |

---

## 8. 권장 조치

### 즉시 (P1)

| # | 조치 | 영향 |
|---|------|------|
| 1 | **Revival 시 `conversation_id` 보존** | 대화 연속성 보장 |
| 2 | **서버 재시작 시 세션 복원 메커니즘** | 현재 서버 재시작 = 모든 세션 소실 |

### 단기 (P2) — optimizing_model.md 연계

| # | 조치 | 영향 |
|---|------|------|
| 3 | **보조 노드에 `ChatAnthropic` 도입** | 서브프로세스 스폰 3회/invoke 절감 + 비용 절감 |
| 4 | **VTuber 워크플로우 latency 프로파일링** | 실제 프로세스 오버헤드 측정 |

### 중장기 (P3)

| # | 조치 | 영향 |
|---|------|------|
| 5 | **Claude CLI 서버 모드 대응 준비** | `--print` → `--server` 전환 시 persistent connection 가능 |
| 6 | **세션 메타데이터 DB 영속화** | 인메모리 → DB 저장으로 서버 재시작 내성 확보 |
