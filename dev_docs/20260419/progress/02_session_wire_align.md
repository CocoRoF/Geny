# 02. AgentSession 배선 0.20.0 정렬

## Scope

`plan/02_executor_rewire.md` 의 2-A (observability) 와 2-C (manager placeholder)
만 건드리는 최소 변경. 기능 회귀는 없음.

## PR Link

- Branch: `refactor/session-wire-0.20.0`
- PR: (이 커밋 푸시 시 발행)

## Summary

- `agent_session.py` : `_invoke_pipeline` / `_astream_pipeline` 두 이벤트 루프에
  `loop.escalate`, `loop.error` 핸들링 추가. 둘 다 `session_logger.log_graph_event`
  로 `node_name="s13_loop"` 에 `loop_signal` 타입으로 남긴다. max_turns 초과 /
  예산 초과 시점을 사후에 관찰 가능해짐.
- `agent_session_manager.py` : `_memory_registry = None` 필드 + `set_memory_registry()`
  setter 추가. Phase 4 에서 `MemorySessionRegistry` 가 attach 될 때 쓸 자리.
  현재 시점에서는 **기본값 None 으로 기동 → 레거시 경로가 그대로 돈다**.
- `tool_bridge.py` : 수정 없음 (plan/02 2-B 에 명시됨).

## Deviations

- plan/02 는 `loop.force_complete` 를 언급했으나 실제 executor v0.20.0 의
  `s13_loop` 는 `LoopDecision.{CONTINUE,COMPLETE,ERROR,ESCALATE}` 네 가지만
  방출한다 (`stages/s13_loop/interface.py`). 따라서 본 PR 은 실제 방출되는
  이름을 따라 `loop.escalate`, `loop.error` 를 구독한다. `loop.complete` 는
  곧 `pipeline.complete` 로 흘러가므로 중복 로그를 피하기 위해 구독하지 않는다.

## Follow-ups

- Phase 4 (`plan/06` PR #9) 에서 `set_memory_registry()` 를 `main.py` lifespan
  에서 호출. 이때부터 `_memory_registry` 가 실제 객체를 가지게 된다.
- `loop_signal` 이벤트는 프론트엔드 session log 뷰어에서 별도 뱃지로 보이게
  Phase 6 UI PR (`plan/06` PR #15) 에서 스타일링 추가.
