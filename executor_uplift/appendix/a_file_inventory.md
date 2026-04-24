# Appendix A — File Inventory

**Status:** Draft

본 문서와 설계 문서 전체에서 참조하는 **파일 경로 인덱스**. 빠른 네비게이션용.

---

## 1. geny-executor (`/home/geny-workspace/geny-executor/`)

### Core primitives
| Path | 역할 |
|---|---|
| `src/geny_executor/__init__.py` | 공개 API 집합 |
| `src/geny_executor/core/pipeline.py` | `Pipeline` — run/run_stream/attach_runtime |
| `src/geny_executor/core/state.py` | `PipelineState`, `TokenUsage`, `CacheMetrics` |
| `src/geny_executor/core/stage.py` | `Stage`, `Strategy`, `StageDescription`, `StrategyInfo` ABC |
| `src/geny_executor/core/slot.py` | `StrategySlot`, `SlotChain` |
| `src/geny_executor/core/mutation.py` | `PipelineMutator`, `MutationKind`, `MutationRecord`, `MutationResult` |
| `src/geny_executor/core/builder.py` | `PipelineBuilder` |
| `src/geny_executor/core/config.py` | `PipelineConfig`, `ModelConfig` |
| `src/geny_executor/core/schema.py` | `ConfigField`, `ConfigSchema` |
| `src/geny_executor/core/environment.py` | `EnvironmentManifest`, `EnvironmentResolver`, `EnvironmentSanitizer`, `EnvironmentManager` |
| `src/geny_executor/core/presets.py` | `PipelinePresets`, `PresetManager`, `PresetRegistry` |
| `src/geny_executor/core/introspection.py` | `introspect_all`, `introspect_stage`, `_STAGE_CAPABILITY_MATRIX` |
| `src/geny_executor/core/artifact.py` | `create_stage`, `describe_artifact`, `list_artifacts` |
| `src/geny_executor/core/result.py` | `PipelineResult` |
| `src/geny_executor/core/errors.py` | 모든 exception 계층 |
| `src/geny_executor/core/snapshot.py` | `PipelineSnapshot`, `StageSnapshot` |
| `src/geny_executor/core/diff.py` | `DiffEntry`, `EnvironmentDiff` |

### Stages
| Path | Stage |
|---|---|
| `src/geny_executor/stages/s01_input/` | 1. Input |
| `src/geny_executor/stages/s02_context/` | 2. Context |
| `src/geny_executor/stages/s03_system/` | 3. System |
| `src/geny_executor/stages/s04_guard/` | 4. Guard |
| `src/geny_executor/stages/s05_cache/` | 5. Cache |
| `src/geny_executor/stages/s06_api/` | 6. API |
| `src/geny_executor/stages/s07_token/` | 7. Token |
| `src/geny_executor/stages/s08_think/` | 8. Think |
| `src/geny_executor/stages/s09_parse/` | 9. Parse |
| `src/geny_executor/stages/s10_tool/` | 10. Tool |
| `src/geny_executor/stages/s11_agent/` | 11. Agent |
| `src/geny_executor/stages/s12_evaluate/` | 12. Evaluate |
| `src/geny_executor/stages/s13_loop/` | 13. Loop |
| `src/geny_executor/stages/s14_emit/` | 14. Emit |
| `src/geny_executor/stages/s15_memory/` | 15. Memory |
| `src/geny_executor/stages/s16_yield/` | 16. Yield |

### LLM client
| Path | 역할 |
|---|---|
| `src/geny_executor/llm_client/base.py` | `BaseClient`, `ClientCapabilities` |
| `src/geny_executor/llm_client/types.py` | `APIRequest`, `APIResponse`, `ContentBlock` |
| `src/geny_executor/llm_client/registry.py` | `ClientRegistry` + anthropic/openai/google/vllm factory |

### Memory
| Path | 역할 |
|---|---|
| `src/geny_executor/memory/provider.py` | `MemoryProvider` + `Layer/Capability/Scope/Importance` enums |
| `src/geny_executor/memory/strategy.py` | `GenyMemoryStrategy` (reflection resolver) |
| `src/geny_executor/memory/retriever.py` | `GenyMemoryRetriever` |
| `src/geny_executor/memory/persistence.py` | `GenyPersistence` |
| `src/geny_executor/memory/presets.py` | `GenyPresets` |

### Tools / MCP
| Path | 역할 |
|---|---|
| `src/geny_executor/tools/built_in/` | 내장 tool (Read/Write/Edit/Bash/Glob/Grep) |
| `src/geny_executor/tools/base.py` | 현재 `Tool` ABC (uplift 대상) |
| `src/geny_executor/tools/mcp/manager.py` | `MCPManager` (현재) |
| `src/geny_executor/tools/mcp/adapter.py` | MCP → Tool 래핑 |

### Events
| Path | 역할 |
|---|---|
| `src/geny_executor/events/__init__.py` | `EventBus`, `PipelineEvent` |

### Tests
| Path | 주요 테스트 |
|---|---|
| `tests/unit/test_phase1_foundation.py` | 기초 API |
| `tests/unit/test_phase1_pipeline.py` | Pipeline 구성 |
| `tests/unit/test_phase2_agent_loop.py` | 에이전트 루프 |
| `tests/unit/test_phase2_tools.py` | Tool 등록·실행 |
| `tests/unit/test_phase3_context_memory.py` | 컨텍스트 / 메모리 |
| `tests/unit/test_phase4_think_agent_evaluate.py` | 심화 기능 |
| `tests/unit/test_phase5_emit_presets_mcp.py` | Emit / Preset / MCP |
| `tests/unit/test_phase5_environment.py` | Manifest |
| `tests/unit/test_phase6_history.py` | History 저장 |
| `tests/unit/test_geny_memory.py` | Geny 메모리 어댑터 |
| `tests/unit/test_mcp_lifecycle.py` | MCP 수명 |
| `tests/integration/test_integration.py` | end-to-end |

---

## 2. Geny backend (`/home/geny-workspace/Geny/backend/`)

### Executor integration
| Path | 역할 |
|---|---|
| `backend/service/executor/__init__.py` | AgentSession, AgentSessionManager 공개 |
| `backend/service/executor/agent_session.py` | `AgentSession` — Pipeline 래퍼, invoke/stream |
| `backend/service/executor/agent_session_manager.py` | `AgentSessionManager` — 세션 생성 / state_provider / global MCP |
| `backend/service/executor/stage_manifest.py` | VTuber 성장 단계 manifest |
| `backend/service/executor/default_manifest.py` | `build_default_manifest(preset)` |
| `backend/service/executor/tool_bridge.py` | `_GenyToolAdapter` |
| `backend/service/executor/geny_tool_provider.py` | `GenyToolProvider` (AdhocToolProvider) |
| `backend/service/executor/context_guard.py` | 도구 권한·경로 검증 유틸 |
| `backend/service/executor/session_freshness.py` | 세션 재활성화 타이밍 |
| `backend/service/executor/model_fallback.py` | LLM 모델 폴백 체인 |

### Tools
| Path | 역할 |
|---|---|
| `backend/tools/base.py` | `BaseTool`, `ToolWrapper`, `@tool` |
| `backend/tools/built_in/geny_tools.py` | 플랫폼 도구 (세션 / 메시징 등) |
| `backend/tools/built_in/knowledge_tools.py` | 지식 질의 |
| `backend/tools/built_in/memory_tools.py` | 메모리 조작 |
| `backend/tools/custom/web_search_tools.py` | 웹 검색 |
| `backend/tools/custom/browser_tools.py` | 브라우저 자동화 |
| `backend/tools/custom/web_fetch_tools.py` | URL fetch |

### Tool infra
| Path | 역할 |
|---|---|
| `backend/service/tool_loader.py` | `ToolLoader` |
| `backend/service/tool_policy/policy.py` | `ToolPolicyEngine`, `ToolProfile`, `ROLE_DEFAULT_PROFILES` |
| `backend/service/tool_preset/models.py` | `ToolPresetDefinition` |
| `backend/service/tool_preset/store.py` | 프리셋 DB |
| `backend/service/tool_preset/templates.py` | 기본 프리셋 |

### MCP
| Path | 역할 |
|---|---|
| `backend/service/mcp_loader.py` | `MCPLoader`, `build_session_mcp_config` |
| `backend/mcp/built_in/*.json` | 내장 MCP 서버 |
| `backend/mcp/custom/*.json` | 커스텀 MCP 서버 |

### Sessions / Models
| Path | 역할 |
|---|---|
| `backend/service/sessions/models.py` | `SessionInfo`, `SessionRole`, `MCPConfig`, `MCPServer*` |
| `backend/service/sessions/store.py` | `SessionStore` (PostgreSQL + JSON) |

### Environment
| Path | 역할 |
|---|---|
| `backend/service/environment/service.py` | `EnvironmentService` |
| `backend/service/environment/templates.py` | 환경 템플릿 |
| `backend/service/environment/role_defaults.py` | role 별 기본 환경 |

### Prompt / Persona
| Path | 역할 |
|---|---|
| `backend/service/prompt/builder.py` | `PromptBuilder`, `PromptMode`, `PromptSection` |
| `backend/service/prompt/sections.py` | `SectionLibrary` |
| `backend/service/prompt/protocols.py` | Opt-in prompt 섹션 |
| `backend/service/prompt/context_loader.py` | 컨텍스트 데이터 로더 |
| `backend/service/persona/provider.py` | `PersonaProvider` 프로토콜 |
| `backend/service/persona/character_provider.py` | `CharacterPersonaProvider` (VTuber) |
| `backend/service/persona/dynamic_builder.py` | `DynamicPersonaSystemBuilder` |

### Lifecycle
| Path | 역할 |
|---|---|
| `backend/service/lifecycle/bus.py` | `SessionLifecycleBus` |
| `backend/service/lifecycle/events.py` | `LifecycleEvent` |

### Execution
| Path | 역할 |
|---|---|
| `backend/service/execution/agent_executor.py` | `execute_command`, `_execute_core`, `ExecutionResult` |

### Controllers
| Path | 역할 |
|---|---|
| `backend/controller/agent_controller.py` | `/api/agents/*` |
| `backend/controller/chat_controller.py` | `/api/chat/rooms/*/broadcast` |
| `backend/controller/command_controller.py` | `/api/command/batch`, `/logs`, `/prompts` |
| `backend/controller/session_memory_controller.py` | `/api/sessions/{id}/memory` |
| `backend/controller/upload_controller.py` | `/api/uploads` |

### Game (타마고치)
| Path | 역할 |
|---|---|
| `backend/service/game/tools/feed.py` | feed tool |
| `backend/service/game/tools/play.py` | play tool |
| `backend/service/game/tools/gift.py` | gift tool |
| `backend/service/game/tools/talk.py` | talk tool |

---

## 3. claude-code-main (`/home/geny-workspace/claude-code-main/`)

### 핵심 참조
| Path | 내용 |
|---|---|
| `src/Tool.ts` | `Tool<Input, Output, Progress>` 전체 계약 (L362–695) + `buildTool()` (L757–792) |
| `src/tools.ts` | 전역 tool 레지스트리 (conditional import, MCP 주입) |
| `src/services/tools/toolOrchestration.ts` | partition + concurrency 실행 (L26–80) |
| `src/services/tools/StreamingToolExecutor.ts` | 스트리밍 실행 + 수신 순 버퍼 (L39–110) |
| `src/utils/toolResultStorage.ts` | Tool 결과 디스크 persist |
| `src/services/mcp/types.ts` | MCP config / connection 타입 (L23–135) |
| `src/services/mcp/client.ts` | MCP 클라이언트 + 연결 관리 |
| `src/services/mcp/auth.ts` | OAuth 흐름 |
| `src/services/mcp/xaa.ts` | Cross-app access |
| `src/skills/bundledSkills.ts` | 번들 skill 레지스트리 (L14–100) |
| `src/skills/loadSkillsDir.ts` | 디스크 skill 로더 |
| `src/skills/mcpSkillBuilders.ts` | MCP prompt → skill 변환 |
| `src/tools/SkillTool/SkillTool.ts` | SkillTool 메타 tool |
| `src/tools/AgentTool/AgentTool.tsx` | AgentTool — subagent spawn |
| `src/commands.ts` | Slash command 레지스트리 |
| `src/types/command.ts` | `Command` union 타입 |
| `src/types/hooks.ts` | Hook event schema (150+ LOC) |
| `src/types/permissions.ts` | Permission rule 타입 |
| `src/utils/hooks/hooksConfigManager.ts` | Hook 설정 로드 |
| `src/utils/hooks/registerFrontmatterHooks.ts` | CLAUDE.md frontmatter hook |
| `src/utils/permissions/permissions.ts` | Permission 평가 |
| `src/Task.ts` | Task (pending/running/completed/failed/killed) |
| `src/tasks/` | Task 구현 (Local/Remote/Dream/InProcessTeammate) |
| `src/coordinator/coordinatorMode.ts` | Multi-agent coordinator |
| `src/context.ts` | System prompt + user context 어셈블 |
| `src/query.ts` | 메인 쿼리 루프 |
| `src/QueryEngine.ts` | SDK 모드 (headless) |

### 대표 tool 구현 참고
| Path | 목적 |
|---|---|
| `src/tools/FileReadTool/FileReadTool.ts` | Read-only tool — PDF / 이미지 / 토큰 budget 예시 |
| `src/tools/BashTool/` | Destructive / exclusive / permission 매처 예시 |
| `src/tools/FileEditTool/` / `FileWriteTool/` | Write 직렬화 |
| `src/tools/AgentTool/` | Subagent spawn (isolation, background task) |
| `src/tools/MCPTool/` | MCP tool 래핑 |
