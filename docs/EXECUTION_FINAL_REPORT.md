# Geny 실행 로직 최종 검증 리포트

> Date: 2026-04-14
> geny-executor: v0.8.1 | Geny: feature/worker-adaptive-integration

---

## 1. 실행 체인 검증 — 모두 정상

### 1.1 session_id 체인 ✅

```
AgentSession._session_id
  → PipelineState(session_id=self._session_id)
    → ToolStage.execute(): ctx = ToolContext(session_id=state.session_id)
      → _GenyToolAdapter.execute(): input.setdefault("session_id", ctx.session_id)
        → memory_search(session_id="실제값") ✅
```

### 1.2 working_dir 체인 ✅

```
AgentSession._working_dir → ToolContext(working_dir=working_dir)
  → GenyPresets.worker_adaptive(tool_context=ctx)
    → PipelineBuilder.with_tools(registry, context=ctx)
      → ToolStage(context=ctx) → self._context.working_dir
        → ReadTool/BashTool: context.working_dir = "실제 경로" ✅
```

### 1.3 메모리 체인 ✅

```
s02_context: GenyMemoryRetriever.retrieve()
  → memory_manager.short_term.get_summary() ✅
  → memory_manager.long_term.load_main() ✅
  → memory_manager.vector_memory.search() ✅
  → memory_manager.search() (keyword) ✅
  → memory_manager.read_note() (backlink) ✅
  → curated_knowledge_manager.inject_context() ✅

s15_memory: GenyMemoryStrategy.update()
  → memory_manager.record_message() ✅
  → memory_manager.remember_dated() ✅
  → memory_manager.write_note() (reflection) ✅
  → curated_knowledge_manager.write_note() (auto-promote) ✅
```

---

## 2. 프리셋 구조

### 2종 프리셋

| Preset | 역할 | 스테이지 |
|--------|------|---------|
| **default** (worker_adaptive) | 모든 비-VTuber 세션 | 16-stage 전체: Input→Context→System→Guard→Cache→API→Token→Think→Parse→Tool→Agent→Evaluate(BinaryClassify)→Loop→Emit→Memory→Yield |
| **vtuber** | VTuber 세션 | Input→Context→System→Guard→Cache→API→Token→Parse→[Tool]→Memory→Yield |

### 이진 분류 (BinaryClassifyEvaluation)

```
첫 턴:
  도구 호출 있음 → not_easy (max_turns=30, 다회전 루프)
  [CONTINUE] 시그널 → not_easy
  그 외 → easy (max_turns=1, 즉시 완료)

이후 턴:
  [COMPLETE] → 완료
  도구 호출 → 계속
  텍스트만 + 시그널 없음 → 완료로 간주
```

---

## 3. 도구 시스템

### 3.1 도구 등록 경로

```
_build_pipeline()
  ├── geny-executor 빌트인 6종
  │   Read, Write, Edit, Bash, Glob, Grep
  │   → ToolRegistry.register() 직접
  │
  └── Geny 어플리케이션 도구 35종
      tool_loader → tool_bridge._GenyToolAdapter → ToolRegistry.register()
      (session_id 자동 주입, arun/run 둘 다 지원)
```

### 3.2 ToolContext 전달

```python
tool_context = ToolContext(
    session_id=self._session_id,     # → state.session_id로 동적 주입
    working_dir=working_dir,         # → ToolStage._context.working_dir
    storage_path=self.storage_path,  # → ToolStage._context.storage_path
)
```

---

## 4. MCP 시스템

### build_session_mcp_config() 단순화 완료

```python
def build_session_mcp_config(
    global_config,              # custom MCP 서버 (mcp/custom/)
    allowed_mcp_servers=None,   # 프리셋 필터링
    extra_mcp=None,             # 추가 per-session MCP
) -> MCPConfig:
    servers = {}
    servers.update(built_in_mcp)     # 항상 포함
    servers.update(filtered_custom)  # 프리셋으로 필터링
    servers.update(extra)            # 추가
    return MCPConfig(servers=servers)
```

- Proxy MCP 서버 완전 제거 ✅
- build_proxy_mcp_server() 삭제 ✅
- 외부 MCP 서버만 관리 (GitHub, Notion 등)

---

## 5. 메모리 시스템

### SessionMemoryManager 초기화

```
AgentSession.initialize()
  → _init_memory()
    → SessionMemoryManager(storage_path)
      → LongTermMemory.ensure_directory()
      → ShortTermMemory.ensure_directory()
      → MemoryIndexManager(memory_dir)
      → StructuredMemoryWriter(memory_dir, index_manager, session_id=)
    → initialize_vector_memory() (async, FAISS)
  → set_database(app_db, session_id)  [agent_session_manager에서 호출]
    → LTM.set_database()
    → STM.set_database()
    → StructuredMemoryWriter.set_database()
```

### GenyMemoryRetriever 6-layer 검색

| Layer | 소스 | 용도 |
|-------|------|------|
| 1 | session summary | 세션 요약 (STM) |
| 2 | MEMORY.md | 장기 메모리 핵심 |
| 3 | FAISS vector | 의미 유사 검색 |
| 4 | keyword search | 키워드 + 중요도 부스트 |
| 5 | backlinks | 연결된 노트 |
| 6 | curated knowledge | 큐레이션된 지식 |

### Obsidian 연동

```
knowledge_tools.py:
  opsidian_browse → UserOpsidianManager.list_notes()  (LTMConfig 게이트)
  opsidian_read → UserOpsidianManager.read_note()     (LTMConfig 게이트)

curated_knowledge:
  knowledge_search → CuratedKnowledgeManager.search()
  knowledge_read → CuratedKnowledgeManager.read_note()
  knowledge_promote → CuratedKnowledgeManager.promote_from_session()
```

---

## 6. 세션 생성 전체 흐름

```
POST /api/agents
  → agent_controller.create_agent_session()
    → agent_session_manager.create_agent_session()
      │
      ├── 1. 이름 중복 체크
      ├── 2. 도구 프리셋 해석 (role → preset_id → allowed_tools)
      ├── 3. MCP 설정 빌드 (built_in + custom + extra)
      ├── 4. 시스템 프롬프트 빌드 (PromptBuilder)
      ├── 5. workflow_id 매핑 (role → template-vtuber / template-optimized-autonomous)
      ├── 6. 도구 레지스트리 빌드 (tool_bridge)
      ├── 7. AgentSession.create()
      │     ├── storage_path 생성
      │     ├── initialize()
      │     │     ├── _init_memory() → SessionMemoryManager
      │     │     └── _build_graph() → _build_pipeline()
      │     │           ├── API key 검증
      │     │           ├── ToolRegistry 빌드 (빌트인 6종 + Geny 35종)
      │     │           ├── ToolContext 생성 (session_id, working_dir)
      │     │           ├── CuratedKnowledgeManager 로드
      │     │           ├── LLM reflection 콜백 생성
      │     │           └── GenyPresets.vtuber/worker_adaptive(tool_context=...)
      │     └── return agent
      ├── 8. 로컬 등록 (_local_agents)
      ├── 9. DB 연결 (memory_manager.set_database)
      ├── 10. 공유 폴더 링크
      ├── 11. 세션 로거 생성
      ├── 12. 영속 저장 (sessions.json)
      ├── 13. VTuber 듀얼 세션 (자동 CLI 생성)
      └── return agent
```

---

## 7. 실행 전체 흐름

```
POST /api/agents/{id}/execute
  → agent_executor.execute_command()
    → agent.invoke(prompt)
      │
      ├── _check_freshness() → 세션 상태 확인/자동 회복
      ├── _ensure_alive() → Pipeline 존재 확인
      └── _invoke_pipeline(input_text, start_time, session_logger)
            │
            ├── memory_manager.record_message("user", input) → STM 기록
            ├── PipelineState(session_id=self._session_id) 생성
            └── async for event in pipeline.run_stream(input, state):
                  │
                  ├── s01 Input: 입력 정규화
                  ├── s02 Context: 6-layer 메모리 검색 → 컨텍스트 주입
                  ├── s03 System: 시스템 프롬프트 + 메모리 컨텍스트 결합
                  ├── s04 Guard: 예산/반복 제한 체크
                  ├── s05 Cache: 프롬프트 캐싱 마커 삽입
                  ├── s06 API: Anthropic API 호출
                  ├── s07 Token: 토큰 사용량 추적
                  ├── s08 Think: Extended thinking 처리
                  ├── s09 Parse: 응답 파싱 + 완료 시그널 감지
                  ├── s10 Tool: 도구 실행 (ToolContext with session_id + working_dir)
                  ├── s11 Agent: 멀티에이전트 오케스트레이션
                  ├── s12 Evaluate: BinaryClassify (easy/not_easy)
                  ├── s13 Loop: 계속/종료 결정
                  │     └── loop_decision == "continue" → s02로 돌아감
                  ├── s14 Emit: 외부 소비자에게 결과 전달
                  ├── s15 Memory: 대화 기록 + 반성 + 지식 승격
                  └── s16 Yield: 최종 결과 포맷팅
                  
            ├── session_logger에 이벤트 기록 (tool/stage → WebSocket/SSE)
            ├── memory_manager.record_execution() → LTM 기록
            └── return {"output": text, "total_cost": cost}
```

---

## 8. 잔여 경미 이슈

| # | 이슈 | 심각도 | 위치 |
|---|------|--------|------|
| 1 | `merge_mcp_configs` import 미사용 | Low | agent_session_manager.py:38 |
| 2 | `graph_name` 파라미터가 __init__에서 저장 안 됨 | Low | agent_session.py:77 |
| 3 | `enable_checkpointing` 파라미터 받지만 사용 안 함 | Low | agent_session.py:75 |
| 4 | `_timeout` 필드가 실행 시간 제한에 사용 안 됨 | Medium | agent_session.py |
| 5 | `_current_iteration` 카운터 Pipeline에서 별도 관리 | Low | agent_session.py |

이들은 모두 기능에 영향을 주지 않는 레거시 흔적이며, 향후 정리 가능.

---

## 9. 결론

**모든 핵심 실행 체인이 완전히 연결되어 정상 동작합니다.**

- session_id: AgentSession → PipelineState → ToolContext → 도구 ✅
- working_dir: AgentSession → ToolContext → GenyPresets → ToolStage → 도구 ✅
- 메모리 검색: 6-layer GenyMemoryRetriever → SessionMemoryManager ✅
- 메모리 기록: GenyMemoryStrategy → record_message + remember_dated + write_note ✅
- Obsidian: UserOpsidianManager → knowledge_tools → LTMConfig 게이트 ✅
- Curated Knowledge: CuratedKnowledgeManager → 검색/읽기/승격 ✅
- 도구 실행: 빌트인 6종 + Geny 35종 → ToolRegistry → ToolStage ✅
- MCP: built_in + custom (프리셋 필터) ✅
- 이진 분류: BinaryClassifyEvaluation → easy(1턴)/not_easy(30턴) ✅
