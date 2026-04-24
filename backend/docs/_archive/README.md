# Backend Docs Archive

현재 아키텍처와 불일치하지만 히스토리 보존용으로 남긴 문서들. 새 참고용이 아닌 "왜 이 설계가 폐기됐나" 재추적용.

## `langgraph-era/`

Geny backend 가 LangGraph `StateGraph` + 커스텀 노드 시스템으로 운영되던 시기 (2025~2026-03) 의 15 쌍 = 30 파일. 2026-04 `geny-executor` Pipeline 도입으로 전면 대체됨. 2026-04-24 에 `SESSIONS`, `WORKFLOW` 가 본문이 stale 이어서 추가 이동됨 (그들이 설명하던 `ClaudeCLIChatModel`, `WorkflowExecutor`, `CompiledStateGraph` 는 현재 존재하지 않음).

### 내용 카테고리

**Autonomous Graph 계열** — LangGraph 기반 자율 에이전트 설계·분석·최적화
- `AUTONOMOUS_AGENT_ANALYSIS.{md,_KO.md}` — AgentState / AutonomousState 스키마
- `AUTONOMOUS_GRAPH_ANALYSIS.{md,_KO.md}` — `autonomous_graph.py` 해부
- `AUTONOMOUS_GRAPH_DEEP_DIVE.{md,_KO.md}` — 9개 노드 상세
- `AUTONOMOUS_GRAPH_OPTIMIZATION.{md,_KO.md}` — 최적화 로드맵 (결국 geny-executor 로 대체)

**Node / Workflow 시스템**
- `NODE_EXECUTION.{md,_KO.md}` — LangGraph 노드 실행 의미론
- `NODE_INTERFACE.{md,_KO.md}` — 노드 인터페이스 계약
- `NEW_NODE_GUIDE.{md,_KO.md}` — 새 노드 작성 가이드
- `WORKFLOW_OVERVIEW.{md,_KO.md}` — 워크플로우 시스템 개관
- `SUDO_COMPILER.{md,_KO.md}` — StateGraph dry-run 도구

**포팅·이행 계획**
- `LANGGRAPH_PORTING.{md,_KO.md}` — Claude CLI → LangGraph 포팅 계획
- `AGENT_IMPROVEMENT_PLAN.{md,_KO.md}` — resilience / fallback 계획

**부가 분석**
- `TOOLS_INTEGRATION_ANALYSIS.{md,_KO.md}` — LangGraph 노드 관점 도구 분석
- `COST_TRACKING_ANALYSIS.{md,_KO.md}` — `claude_cli_model.py` 기반 비용 추적

**Session / Workflow 상위 문서 (2026-04-24 추가 이동)**
- `SESSIONS.{md,_KO.md}` — "Claude CLI → LangChain → LangGraph StateGraph" 시절 세션 생명주기 문서. `ClaudeCLIChatModel` / `ClaudeProcess` / `CompiledStateGraph` 등 더 이상 존재하지 않는 클래스 기반.
- `WORKFLOW.{md,_KO.md}` — `WorkflowDefinition → WorkflowExecutor → StateGraph(AutonomousState)` 컴파일러 문서. `WorkflowExecutor`, `backend/service/workflow/` 폴더 자체가 현재 존재하지 않음.

## 아카이브 사유 요약

| 사유 | 해당 문서 수 |
|---|---|
| 노드 시스템 (`service/langgraph/nodes/`) 폐기 | 8 |
| `autonomous_graph.py` 파일 자체가 `.bak` 으로 묻힌 후 삭제됨 (2026-04-24) | 8 |
| Claude CLI era 산출물 (`claude_cli_model.py` 관련) | 2 |
| StateGraph 기반 워크플로우 실행기 폐기 | 4 |
| LangGraph 포팅 계획 (완료되어 geny-executor 로 다시 이행됨) | 2 |
| Resilience/fallback 재구현됨 | 2 |
| SESSIONS / WORKFLOW 상위 문서 (2026-04-24) | 4 |

**대체 참조:** 현재 실행 흐름과 세션 관리는 [`../EXECUTION.md`](../EXECUTION.md) + [`../CHAT.md`](../CHAT.md) 와 소스 코드 (`service/executor/`, `service/execution/`) 가 Source of Truth.
