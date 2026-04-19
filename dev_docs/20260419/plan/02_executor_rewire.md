# 02. Executor 재배선 (AgentSession / tool_bridge / AgentSessionManager)

## 목표

0.20.0 API 에 맞춰 **기존 호출부를 최소 침습으로 정돈**한다. 단, 대규모 구조 재작성은 **하지 않는다** — Environment/Memory 이식이 먼저다. 이 PR 은 `GenyPresets` 기반 기존 경로가 0.20.0 에서 안정 동작하도록 사소한 조정만 포함.

## 수정 대상

### 2-A. `backend/service/langgraph/agent_session.py`

1. Import 문 확인 (경로는 호환; 단 `GenyPresets` 파라미터 재확인).
   ```python
   from geny_executor.memory import GenyPresets
   ```
2. `_build_pipeline()` 내 `GenyPresets.vtuber(...)` / `GenyPresets.worker_adaptive(...)` 인자 시그니처를 실제 0.20.0 코드와 맞춘다:
   - 0.20.0 의 `worker_adaptive` 와 `vtuber` 는 `api_key, memory_manager, *, model, system_prompt, tools, tool_context, ...` 키워드. 기존 Geny 호출과 대부분 호환되지만 파라미터 누락/오타 확인.
3. `_astream_pipeline`/`_invoke_pipeline` 의 `PipelineState(session_id=...)` 호출은 그대로. 신규 필드는 모두 기본값 있음.
4. `ToolContext(session_id, working_dir, storage_path)` → 그대로. 신규 `stage_order/stage_name` 은 파이프라인이 주입.
5. **관찰성 강화 (선택)**: Geny 의 session_logger 가 `loop.force_complete` 이벤트도 잡도록 이벤트 타입 리스트 확장.

### 2-B. `backend/service/langgraph/tool_bridge.py`

- 변경 없음 (인터페이스 안정).
- `_GenyToolAdapter` 가 이미 `ToolResult(content, is_error)` 반환. 0.20.0 에서도 동일.

### 2-C. `backend/service/langgraph/agent_session_manager.py`

- 변경 없음 (singleton 유지).
- 단, Phase 4 에서 `memory_registry` 를 받도록 생성자 확장 예정 (이번 PR 에서는 자리만 마련하고 None 기본값).

## 테스트

1. **로컬 스모크**: 세션 생성 → 간단 질문 → 파이프라인 이벤트 순서 스냅샷 비교.
2. **수동 VTuber 스모크**: VTuber 세션 생성 후 `avatar_state` 변화 관찰.
3. **툴 스모크**: BashTool / ReadTool / WriteTool / 커스텀 Geny 툴 (search_web, user_opsidian 등) 하나씩 호출.

## 리스크

- `GenyPresets.vtuber/worker_adaptive` 내부는 v0.14 의 `GenyMemoryRetriever/Strategy/Persistence` 를 사용 — 이는 "legacy adapter" 로 표시되어 있음. 동작은 하지만 **향후 제거될 가능성**. Phase 5 에서 대체 경로 마련할 것을 이미 `plan/03` 에 명시.

## 이 PR 에서 하지 않는 것

- MemoryProvider 붙이기 (Phase 4).
- Environment 기반 세션 생성 (Phase 3).
- 레거시 메모리 제거 (Phase 5).

## 수용 기준

- 0.20.0 하에서 agent_controller + chat_controller 의 전 경로가 회귀 없음.
- WS 스트리밍 로그가 기존 필드들을 유지.
