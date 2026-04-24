# Backend Internal Documentation

`backend/` 서브시스템 심층 문서. 프로젝트 상위 문서는 [`../../docs/`](../../docs/README.md) 참조.

모든 문서는 영문 (`X.md`) + 한글 (`X_KO.md`) 쌍으로 유지.

## 현재 상태

Backend 는 [`geny-executor`](https://github.com/CocoRoF/geny-executor) Pipeline 기반으로 운영됨. 과거 LangGraph StateGraph 기반 문서는 [`_archive/langgraph-era/`](_archive/langgraph-era/) 로 이동 완료 (2026-04-24).

## 주제별 인덱스

### 실행 흐름
| EN | KO | 내용 |
|---|---|---|
| [`EXECUTION.md`](EXECUTION.md) | [`EXECUTION_KO.md`](EXECUTION_KO.md) | Pipeline 실행, `execute_command()`, 세션 invoke |
| [`SESSIONS.md`](SESSIONS.md) | [`SESSIONS_KO.md`](SESSIONS_KO.md) | AgentSession 생명주기 |
| [`WORKFLOW.md`](WORKFLOW.md) | [`WORKFLOW_KO.md`](WORKFLOW_KO.md) | 브로드캐스트·트리거·리포트 흐름 |
| [`CHAT.md`](CHAT.md) | [`CHAT_KO.md`](CHAT_KO.md) | Chat room · messenger · broadcast |

### 데이터 & 상태
| EN | KO | 내용 |
|---|---|---|
| [`DATABASE.md`](DATABASE.md) | [`DATABASE_KO.md`](DATABASE_KO.md) | Postgres 스키마 개관 |
| [`DATABASE_ARCHITECTURE.md`](DATABASE_ARCHITECTURE.md) | [`DATABASE_ARCHITECTURE_KO.md`](DATABASE_ARCHITECTURE_KO.md) | 데이터 모델 심층 |
| [`MEMORY.md`](MEMORY.md) | [`MEMORY_KO.md`](MEMORY_KO.md) | LTM / STM / 벡터 메모리 |
| [`CONFIG.md`](CONFIG.md) | [`CONFIG_KO.md`](CONFIG_KO.md) | 설정 시스템 (`@register_config`) |
| [`SHARED_FOLDER.md`](SHARED_FOLDER.md) | [`SHARED_FOLDER_KO.md`](SHARED_FOLDER_KO.md) | 세션 간 공유 저장소 |

### 도구 & 확장
| EN | KO | 내용 |
|---|---|---|
| [`TOOLS.md`](TOOLS.md) | [`TOOLS_KO.md`](TOOLS_KO.md) | 내장 도구 (`tools/built_in/`) |
| [`MCP.md`](MCP.md) | [`MCP_KO.md`](MCP_KO.md) | Model Context Protocol 서버 통합 |
| [`PROMPTS.md`](PROMPTS.md) | [`PROMPTS_KO.md`](PROMPTS_KO.md) | 프롬프트 시스템 (`backend/prompts/`) |
| [`SUB_WORKER.md`](SUB_WORKER.md) | [`SUB_WORKER_KO.md`](SUB_WORKER_KO.md) | VTuber ↔ Sub-Worker 페어링 |

### 운영
| EN | KO | 내용 |
|---|---|---|
| [`LOGGING.md`](LOGGING.md) | [`LOGGING_KO.md`](LOGGING_KO.md) | 이벤트 로깅·관측 |

## `_archive/langgraph-era/`

2025~2026-03 LangGraph StateGraph 기반 시기 문서 (13 쌍 = 26 파일). 현재 아키텍처와 불일치하므로 참고 시 주의. 세부 목차는 [`_archive/README.md`](_archive/README.md).
