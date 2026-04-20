# 04 — Observability and Error Surface (Phase D)

`(parse error)` 라는 무정보 문자열을 뿌리째 제거하고, tool 실행의 성공/실패를
투명하게 log 와 UI 로 전달한다. 대응 취약점: F-3, F-7.

## §A. Logger stacktrace 확보

**변경 위치**:
- `geny-executor/stages/s10_tool/.../routers.py:41-45` (plan/02 §A 와 병행).

**현재**: `except Exception as e: return ToolResult(f"Tool 'X' failed: ...")`
— 로그 한 줄 없이 문자열로 평탄화.

**변경**: 예외 포착 지점에서 `logger.exception(...)` 로 stacktrace 남기고,
LLM 에게는 구조화 에러만 전달.

```python
except Exception as e:
    logger.exception("tool %s crashed; input=%r", tool_name, tool_input)
    return ToolResult.error(ToolError.tool_crashed(tool_name, e))
```

`tool_input` 로깅 시 민감 데이터 ( API key 등) 는 이미 `ToolContext.env_vars`
경로로 분리되어 있어 직접 문제는 없지만, 확실히 하려면 logger formatter 에
**환경변수 이름 필터** 를 붙이고, 입력 딕셔너리의 값 중 secrets 키워드를 담은
키는 `***` 로 치환.

## §B. `_format_tool_detail` swallower 제거

**위치**:
- `Geny/backend/service/logging/session_logger.py:565-667`
- `Geny/backend/service/claude_manager/process_manager.py` 의 중복 정의
  (line ~870).

**현재**: 광범위 `except Exception: return "(parse error)"`. 이 함수가 **로그
표시용** 과 **UI 에 보여주는 tool invocation 요약** 양쪽에 쓰이고 있음.

**변경**:
1. 두 파일의 중복 정의를 하나로 통합 → `service/logging/tool_detail_formatter.py`
   로 이동.
2. 예외 swallow 를 없애고, 실패 시 다음 원칙:
   - 개별 필드 포맷 실패는 `<unrepresentable: ValueError>` 같은 **구체적**
     플레이스홀더.
   - 최상위 포맷 실패는 `logger.exception(...)` 으로 남기고, `repr(tool_input)`
     의 잘려진 버전 (≤ 200 자) 을 반환 — **절대 빈 문자열이나 `"(parse error)"`
     를 반환하지 않는다**.
3. 호출 지점 (`session_logger.py:408` 등) 은 반환값을 그대로 log 에 넣으면 됨.

## §C. Tool event 이벤트 타입 분리

`agent_session.py:857-870` 의 이벤트 스트림 처리에서 `tool.execute_complete`
이벤트 payload 가 성공/실패 양쪽을 섞어 표시. structured error 도입 후:

- `tool.execute_start { name, input_preview }`
- `tool.execute_ok { name, output_preview }`
- `tool.execute_error { name, code, message, details }`

UI (`SessionEnvironmentTab`, 채팅 메시지 컴포넌트) 는 `execute_error` 를 빨간
badge 로 렌더.

## §D. UI 표현

- 채팅 스트림에서 tool_result 의 **첫 줄** 이 `ERROR code:` 로 시작하면
  (plan/02 §B 의 Anthropic 호환 포맷), 메시지 컴포넌트는 해당 블록을 에러
  스타일로 렌더하고 details JSON 은 접어두는 disclosure 로 표시.
- `CodeViewModal` (PR #128) 은 그대로. manifest 자체는 변경 안 됨.
- `PipelineCanvas` 의 stage 상세 패널에서 각 tool 의 실패 / 성공 카운트를
  라이브로 표시 — 이는 plan/04 의 stretch goal.

## §E. Developer mode

`GENY_TOOL_DEBUG=true` 환경변수로 설정하면:
- structured error 의 `details` 에 stacktrace 일부 포함.
- `(parse error)` 관련 로깅이 ERROR 레벨로 승격.
- UI 에 "debug badge" 표시.

기본값 false. 운영 환경에서는 stacktrace 가 UI 로 새지 않는다.

## 테스트

- `tests/logging/test_tool_detail_formatter.py` — 비직렬화 객체, 순환 참조,
  비문자열 키 등 악성 케이스에서 swallower 없이 의미 있는 문자열 반환.
- `tests/logging/test_tool_events.py` — `execute_error` 이벤트가 반드시 code
  를 포함.
- E2E: `news_search` 의 과거 실패 케이스 (경로 B) 를 강제 재현한 뒤, log /
  UI / LLM 세 채널 모두에서 `(parse error)` 가 **한 번도** 나오지 않는지
  확인.

## 성공 기준

- 리포 grep `"parse error"` → 테스트 fixture 외에는 0 건.
- `execute_error` 이벤트에 `code` 필드가 항상 존재.
- Developer mode 에서 실제 stacktrace 확인 가능.
