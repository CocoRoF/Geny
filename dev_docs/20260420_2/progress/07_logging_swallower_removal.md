# 07 — Geny logging swallower 제거 (PR7, Phase D §B)

- **Repo**: `Geny` (backend)
- **Plan 참조**: `plan/04_observability_and_error_surface.md` §B
- **Branch**: `feat/tool-detail-formatter`
- **PR**: [CocoRoF/Geny#137](https://github.com/CocoRoF/Geny/pull/137)
- **의존**: 없음 (executor 버전 변동 없이 수행 가능한 순수 백엔드
  리팩터). PR8 cutover 와 독립적이라 먼저 머지.

## 변경 요지

`_format_tool_detail` 의 `except Exception: return "(parse error)"`
swallower 두 벌을 제거. 두 호출 지점 — `session_logger.py:408` (DB/파일
로그) 과 `process_manager.py:657` (CLI tool-call 로그) — 가 동일한
포맷터를 공유하던 점을 살려, 단일 모듈 함수 (`format_tool_detail`) 로
수렴.

수렴 과정에서 두 구현의 미묘한 표기 차이가 있었음:
| 위치 | Read 라인 표기 | Write 메타 | MCP/default 값 quoting |
| --- | --- | --- | --- |
| `session_logger.py` | `(L10-50)` / `(from L10)` | `+N lines, M chars` | backtick |
| `process_manager.py` | `(lines 10-50)` / `(from line 10)` | `N lines` | none |

UI 가 두 출력을 모두 그대로 화면에 던지므로 사용자에게 혼란을 주는
표현 차이가 있었음. 더 정보량이 많은 `session_logger.py` 형식을
canonical 로 채택 (`L` prefix + char count + backtick quoting).

## 추가 / 변경된 파일

1. **신규** `backend/service/logging/tool_detail_formatter.py`
   - `format_tool_detail(tool_name, tool_input) -> str` — pure 함수.
   - **실패 정책**:
     - 개별 필드 stringify 실패 → `<unrepresentable: {ExcType}>`
       플레이스홀더로 그 필드만 격리.
     - 최상위 실패 → `logger.exception(...)` 로 stacktrace 남기고
       `repr(tool_input)` 의 ≤ 200 자 자른 fallback 반환. **빈 문자열
       이나 `(parse error)` 는 절대 반환하지 않는다**.
     - `repr()` 자체가 raise 하면 `<unrepresentable input: ExcType>`.
   - 헬퍼: `_safe_str` (per-field guard), `_truncate`, `_basename`.
   - MCP key 우선순위: `query / path / file_path / command / url /
     content / message / prompt`.

2. **수정** `backend/service/logging/__init__.py` — `format_tool_detail`
   re-export. 향후 새로운 호출 지점이 클래스 메서드 우회해서 직접
   import 가능하게 함.

3. **수정** `backend/service/logging/session_logger.py`
   - 100 줄 가까운 `_format_tool_detail` 메서드를 1줄 delegate 로
     교체 (`return format_tool_detail(tool_name, tool_input)`).
   - 호출 지점 (line 408) 변경 없음.

4. **수정** `backend/service/claude_manager/process_manager.py`
   - 동일하게 1줄 delegate.
   - 호출 지점 (line 657) 변경 없음.

## 검증

- `python3 -m py_compile` — 4 개 파일 모두 성공.
- 직접 호출 smoke (`python3 -c ...`):
  - Happy path: Bash / Read+offset / Write / Grep+path / MCP / default
    각각 기대대로 formatted string 반환.
  - Adversarial:
    - `__str__` 가 `RuntimeError` 를 raise 하는 값 →
      `k=`<unrepresentable: RuntimeError>`` (문자열 내 backtick 포함).
    - 자기 참조 dict (`d['self'] = d`) → `repr` 이 `{...}` 로 안전
      처리되어 `self=`{'self': {...}}`` 반환.
    - `.items()` 가 raise 하는 mapping → 최상위 except 에 걸려
      `logger.exception` 한 줄 + `<BadMap>` (repr 결과) 반환.
- `grep -rn "parse error" backend/` → 새 모듈의 docstring 3 건 (제거
  사실을 설명) + `controller/environment_controller.py:236` 의 무관한
  HTTP 400 코멘트 1 건. **swallower 코드 0 건**.

## 호환성

- 기존 메서드 시그니처 유지 (`SessionLogger._format_tool_detail`,
  `ProcessManager._format_tool_detail`) → 외부에서 메서드를 직접
  호출하는 코드가 있어도 영향 없음.
- 출력 표기는 `process_manager.py` 쪽이 `lines 10-50` → `L10-50` 로,
  `(N lines)` → `(+N lines, M chars)` 로 살짝 더 정보가 늘어남. 로그
  파서 (현재 없음) 와 UI 가 자유 텍스트로 취급하므로 호환성 영향 없음.

## Plan §B 성공 기준 매핑

| 기준 | 충족 여부 |
| --- | --- |
| 두 파일의 중복 정의 통합 | ✅ `tool_detail_formatter.py` 단일 모듈 |
| 개별 필드 실패는 구체적 placeholder | ✅ `<unrepresentable: ExcType>` |
| 최상위 실패: `logger.exception` + 잘려진 `repr` | ✅ |
| 빈 문자열 / `(parse error)` 절대 반환 안 함 | ✅ smoke 로 확인 |
| 호출 지점은 반환값을 그대로 log 에 전달 | ✅ 두 호출 지점 모두 변경 없음 |

## 후속 TODO

- **PR8 (Phase C switch-over)** — 본격 활성화. PR6 에서 도입한
  `GenyToolProvider` / `build_default_manifest` 를 `AgentSession.
  _build_pipeline` 과 `EnvironmentService.instantiate_pipeline` 에
  꽂고, `geny-executor` pin 을 `>=0.22.0,<0.23.0` 로 이동.
- Plan §C–E (이벤트 분리 / UI 적색 badge / `GENY_TOOL_DEBUG`) 는 별도
  사이클로 분리 — Phase D 의 본 PR 은 §B (swallower) 에 한정.
