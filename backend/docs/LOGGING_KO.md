# Logging System

> 세션별 로그를 파일 + DB + 인메모리에 삼중 기록하는 구조화된 로깅 시스템

## 아키텍처 개요

```
SessionLogger (세션별 인스턴스)
    │
    ├── 파일       ── logs/{session_id}.log (영구)
    ├── PostgreSQL ── session_logs 테이블 (영구)
    └── 인메모리   ── _log_cache (최대 1000개, SSE 스트리밍용)
```

모든 로그 항목은 세 곳에 동시 기록. DB 쓰기는 best-effort (논블로킹).

---

## LogLevel (11종)

| 레벨 | 열거형 | 설명 |
|------|--------|------|
| `DEBUG` | `DEBUG` | 디버그 메시지 |
| `INFO` | `INFO` | 세션 이벤트, 정보 메시지 |
| `WARNING` | `WARNING` | 경고 |
| `ERROR` | `ERROR` | 에러 |
| `COMMAND` | `COMMAND` | 사용자가 Claude에 보낸 프롬프트 |
| `RESPONSE` | `RESPONSE` | Claude의 응답 (성공/실패) |
| `GRAPH` | `GRAPH` | `geny-executor` Stage 전환 (legacy `Graph` 키는 DB row 호환성 위해 유지) |
| `TOOL` | `TOOL_USE` | 도구 호출 이벤트 |
| `TOOL_RES` | `TOOL_RESULT` | 도구 실행 결과 |
| `STREAM` | `STREAM_EVENT` | Claude CLI stream-json 이벤트 |
| `ITER` | `ITERATION` | 자율 실행 이터레이션 완료 |

---

## LogEntry

```python
@dataclass
class LogEntry:
    level: LogLevel
    message: str
    timestamp: datetime = now_kst()
    metadata: Dict[str, Any] = {}
```

- `to_dict()` → `{timestamp, level, message, metadata}`
- `to_line()` → `[KST-timestamp] [LEVEL   ] message | {json-metadata}\n`

---

## SessionLogger

### 생성

```python
logger = SessionLogger(
    session_id="abc-123",
    session_name="My Session",
    logs_dir="backend/logs/"    # 기본값
)
```

- 로그 파일: `logs/{session_id}.log`
- `threading.Lock`으로 스레드 안전
- 인메모리 캐시: 최대 **1000** 항목 (초과 시 오래된 것부터 삭제)

### 기본 로깅

| 메서드 | 레벨 | 설명 |
|--------|------|------|
| `log(level, message, metadata)` | 지정 | 일반 로그 |
| `debug(message)` | DEBUG | 디버그 |
| `info(message)` | INFO | 정보 |
| `warning(message)` | WARNING | 경고 |
| `error(message)` | ERROR | 에러 |

### 특화 로깅

#### `log_command(prompt, timeout, system_prompt, max_turns)`

레벨: **COMMAND** — 사용자 프롬프트 기록.

| 메타데이터 | 설명 |
|-----------|------|
| `prompt_length` | 프롬프트 길이 |
| `preview` | 처음 200자 미리보기 |
| `system_prompt_preview` | 시스템 프롬프트 처음 100자 |
| `timeout`, `max_turns` | 실행 설정 |

#### `log_response(success, output, error, duration_ms, cost_usd, tool_calls, num_turns)`

레벨: **RESPONSE** — Claude 응답 기록. 각 `tool_call`에 대해 자동으로 `log_tool_use()` 호출.

| 메타데이터 | 설명 |
|-----------|------|
| `success` | 성공 여부 |
| `duration_ms`, `cost_usd` | 실행 시간, 비용 |
| `output_length`, `preview` | 출력 길이, 처음 200자 |
| `tool_call_count`, `num_turns` | 도구 호출 수, 턴 수 |

#### `log_iteration_complete(iteration, success, output, ...)`

레벨: **ITERATION** — 자율 실행 이터레이션 완료. 미리보기 500자.

#### `log_tool_use(tool_name, tool_input, tool_id)`

레벨: **TOOL_USE** — 도구 호출. 구조화 추출 자동 수행 (아래 참조).

#### `log_tool_result(tool_name, tool_id, result, is_error, duration_ms)`

레벨: **TOOL_RESULT** — 도구 결과. 파일 도구는 5000자, 기타 500자 미리보기.

### Pipeline 이벤트 로깅

모든 레벨: **GRAPH**. UUID 이벤트 ID 생성(8자).

| 메서드 | 이벤트 타입 | 설명 |
|--------|-----------|------|
| `log_graph_execution_start(input, thread_id, ...)` | `execution_start` | 그래프 실행 시작 |
| `log_graph_node_enter(node_name, iteration, ...)` | `node_enter` | 노드 진입 |
| `log_graph_node_exit(node_name, iteration, duration_ms, ...)` | `node_exit` | 노드 퇴출 |
| `log_graph_state_update(update_type, changes, ...)` | `state_update` | 상태 갱신 |
| `log_graph_edge_decision(from_node, decision, reason, ...)` | `edge_decision` | 엣지 결정 |
| `log_graph_execution_complete(success, total_iterations, ...)` | `execution_complete` | 실행 완료 |
| `log_graph_error(error_message, node_name, ...)` | `error` | 그래프 에러 |

---

## 구조화 추출 (Structured Extraction)

도구 호출 시 자동으로 메타데이터에서 구조화된 정보를 추출.

### 파일 변경 추출 (`_extract_file_changes`)

감지 도구: `write_file`, `create_file`, `edit_file`, `str_replace_editor`, `multi_edit` 등.

```python
{
    "file_path": "src/main.py",
    "operation": "edit",          # create / write / edit / multi_edit
    "changes": [
        {"old_str": "기존 코드", "new_str": "새 코드"}
    ],
    "lines_added": 5,
    "lines_removed": 2
}
```

`multi_edit`는 최대 20개 변경 사항. 콘텐츠 필드 최대 50KB (초과 시 절삭).

### 명령어 추출 (`_extract_command_data`)

감지 도구: `bash`, `shell`, `execute`, `terminal`, `run`.

```python
{
    "command": "npm test",       # 최대 10KB
    "working_dir": "/project"
}
```

### 파일 읽기 추출 (`_extract_file_read_data`)

감지 도구: `read_file`, `view`, `cat`.

```python
{
    "file_path": "src/main.py",
    "start_line": 1,
    "end_line": 50
}
```

### 도구 포맷 (`_format_tool_detail`)

로그 메시지를 위한 간결한 요약:
- bash: `` `npm test` `` (100자)
- read: `main.py (L1-50)`
- write: `main.py (+25 lines, 1024 chars)`
- grep: `"pattern" in src/`
- web/fetch: URL (60자)
- MCP 도구: 첫 관련 파라미터 (`query`, `path` 등)

---

## 로그 조회

### 인메모리 (SSE 스트리밍용)

```python
# 커서 기반 증분 조회
entries, new_cursor = logger.get_cache_entries_since(cursor=0)
```

### 범용 조회

```python
logs = logger.get_logs(
    limit=100,
    level="INFO",            # 단일 또는 세트
    from_cache=True,         # False시 DB → 파일 폴백
    offset=0,
    newest_first=True
)
```

---

## 파일 저장 형식

```
logs/{session_id}.log
```

```
================================================================================
Session ID: abc-123
Session Name: My Session
Started: 2026-03-21 15:30:00 KST
================================================================================

[2026-03-21 15:30:01] [COMMAND ] PROMPT: ... | {"type": "command", ...}
[2026-03-21 15:30:05] [RESPONSE] SUCCESS: ... | {"type": "response", ...}
...

================================================================================
Session Ended: 2026-03-21 16:00:00 KST
================================================================================
```

---

## 모듈 레벨 함수

| 함수 | 설명 |
|------|------|
| `set_log_database(app_db)` | 시작 시 DB 참조 설정 |
| `get_session_logger(session_id, session_name)` | 로거 레지스트리에서 조회/생성 |
| `remove_session_logger(session_id, delete_file)` | 로거 닫기 + 등록 해제 |
| `list_session_logs()` | DB → 파일 시스템 스캔 폴백으로 로그 목록 |
| `read_logs_from_file(session_id, limit, level)` | DB → 파일 파싱 폴백 |
| `count_logs_for_session(session_id, level)` | 캐시 → DB 폴백 |

---

## REST API

| Method | 엔드포인트 | 설명 |
|--------|-----------|------|
| `GET` | `/api/commands/logs` | 전체 세션 로그 파일 목록 |
| `GET` | `/api/commands/logs/{session_id}?limit=&level=&offset=` | 세션 로그 조회 (level 쉼표 구분 가능) |
| `GET` | `/api/commands/stats` | 전체 통계 (세션 수 + 로그 파일) |
| `GET` | `/api/commands/monitor/{session_id}` | 세션 모니터 (최근 50개 로그 포함) |

---

## 관련 파일

```
service/logging/
├── __init__.py              # 공개 API 내보내기
├── types.py                 # LogLevel, LogEntry
└── session_logger.py        # SessionLogger + 모듈 레벨 함수

controller/command_controller.py  # 로그 조회 API 엔드포인트
```
