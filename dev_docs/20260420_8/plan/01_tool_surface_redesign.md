# Plan/01 — Tool surface 재설계: rename + internal/external 분리 + room 전역 비활성

**목적.** `analysis/01_vtuber_counterpart_fallback.md`가 밝힌
3개 층의 결함을 한 번에 해소한다.

**전제.** geny-executor 버전 고정 없음 (executor 측 변경 없음).
현재 floor `>=0.27.0,<0.28.0` 유지.

**PR 구성.** 두 개 PR로 분할. 순서 의존 있음 (PR-1 먼저, PR-2 나중).

---

## PR-1 — 내장 툴 rename + counterpart 정식 등록 + room 주석 비활성

### 범위 (Geny)

#### 1-1. `backend/tools/built_in/geny_tools.py` — 클래스/이름/export

**클래스 rename** (class name도 이름과 맞춤):

| 기존 class | 신규 class | 기존 `name` | 신규 `name` |
|---|---|---|---|
| `GenySessionListTool` | `SessionListTool` | `geny_session_list` | `session_list` |
| `GenySessionInfoTool` | `SessionInfoTool` | `geny_session_info` | `session_info` |
| `GenySessionCreateTool` | `SessionCreateTool` | `geny_session_create` | `session_create` |
| `GenyRoomListTool` | `RoomListTool` | `geny_room_list` | `room_list` |
| `GenyRoomCreateTool` | `RoomCreateTool` | `geny_room_create` | `room_create` |
| `GenyRoomInfoTool` | `RoomInfoTool` | `geny_room_info` | `room_info` |
| `GenyRoomAddMembersTool` | `RoomAddMembersTool` | `geny_room_add_members` | `room_add_members` |
| `GenySendRoomMessageTool` | `SendRoomMessageTool` | `geny_send_room_message` | `send_room_message` |
| `GenySendDirectMessageTool` | `SendDirectMessageExternalTool` | `geny_send_direct_message` | `send_direct_message_external` |
| `GenyMessageCounterpartTool` | `SendDirectMessageInternalTool` | `geny_message_counterpart` | `send_direct_message_internal` |
| `GenyReadRoomMessagesTool` | `ReadRoomMessagesTool` | `geny_read_room_messages` | `read_room_messages` |
| `GenyReadInboxTool` | `ReadInboxTool` | `geny_read_inbox` | `read_inbox` |

**description 수정** — `send_direct_message_internal`의 설명을 다시
작성해 LLM이 내부용/외부용 구분을 명확히 인식하도록:

```python
class SendDirectMessageInternalTool(BaseTool):
    name = "send_direct_message_internal"
    description = (
        "Send a direct message to your bound counterpart agent. "
        "Use this when you want to reach the agent you are paired with "
        "(VTuber↔Sub-Worker). No target id is needed — the runtime "
        "routes to whichever session is linked to you. Prefer this over "
        "send_direct_message_external whenever you want to reach your "
        "paired counterpart."
    )
```

그리고 `send_direct_message_external`의 description에 *"only when
you need to reach a session that is not your bound counterpart"* 를
명시해 LLM이 기본 선택으로 오도되지 않게 한다.

**`TOOLS` export 리스트 재작성** (line 939-954):

```python
TOOLS = [
    # Session management — Sub-Worker only (VTuber denied at roster level)
    SessionListTool(),
    SessionInfoTool(),
    SessionCreateTool(),
    # Messaging
    SendDirectMessageExternalTool(),
    SendDirectMessageInternalTool(),   # ← cycle 7-1 누락 복구
    ReadInboxTool(),
    # Room tools intentionally disabled at the export level.
    # Classes remain defined above for future re-enablement; simply
    # uncomment the lines below to restore. See dev_docs/20260420_8/
    # analysis/01_vtuber_counterpart_fallback.md § Room 도구 전역 비활성.
    # RoomListTool(),
    # RoomCreateTool(),
    # RoomInfoTool(),
    # RoomAddMembersTool(),
    # SendRoomMessageTool(),
    # ReadRoomMessagesTool(),
]
```

#### 1-2. `backend/prompts/vtuber.md` — 툴 이름 참조 교체

```
geny_message_counterpart → send_direct_message_internal
```

(3곳, grep 확인됨). `geny_send_direct_message` 언급이 남아 있다면
그것도 제거 (VTuber는 이 툴을 이제 받지 않음).

#### 1-3. `backend/prompts/templates/sub-worker-default.md` / `sub-worker-detailed.md`

`geny_message_counterpart` 참조를 `send_direct_message_internal`로,
`geny_send_direct_message`을 `send_direct_message_external`로 교체.
기존 가이드 문구(카운터파트 우선 사용)는 유지.

#### 1-4. `backend/service/langgraph/agent_session_manager.py`

warm-restart / fresh-create injection 블록의 툴 이름 참조를 신규
이름으로 교체 (cycle 7-1의 `geny_message_counterpart` 주입 위치).

#### 1-5. 테스트 업데이트 (rename만)

- `tests/service/langgraph/test_counterpart_message_tool.py` —
  `GenyMessageCounterpartTool` → `SendDirectMessageInternalTool`,
  문자열 비교 "geny_message_counterpart" → "send_direct_message_internal"
- `tests/service/environment/test_templates.py` — 동일 rename
- `tests/service/environment/test_tool_registry_roster.py` — 동일
- `tests/service/environment/test_system_stage_tools.py` — 동일
- `tests/integration/test_vtuber_dm_delegation.py` — 동일
- `tests/integration/test_delegation_round_trip.py` — 동일
- `tests/service/langgraph/test_default_manifest.py` — 동일
- `tests/service/langgraph/test_tool_bridge.py` — 동일

기계적 문자열 교체. 로직 변경 없음.

### 검증 (PR-1)

```bash
cd backend && pytest tests/service/langgraph tests/service/environment \
  tests/integration -x -q
```

기존 테스트가 rename된 이름으로 전부 통과해야 한다. 새 테스트는 PR-2에서.

### 배포 관점

- Sub-Worker 프롬프트가 rename을 반영하므로 기존 세션도 문제 없음
- 사용자 DB에 저장된 manifest들은 `external_tool_names`에 기존
  `geny_*` 이름을 들고 있을 수 있음 → `install_environment_templates`가
  boot 시 seed env를 재생성하는 구조이므로 재시작만으로 덮어씀
- 사용자 생성 커스텀 환경에 `geny_*` 이름이 박혀 있다면 해당 세션은
  "존재하지 않는 도구" 경고를 찍고 external에서 스킵됨. 파괴적이지
  않음

---

## PR-2 — `_PLATFORM_TOOL_PREFIXES` 폐기 + VTuber deny 확장 + 카테고리 allowlist

### 범위 (Geny)

#### 2-1. `backend/service/environment/templates.py`

`_PLATFORM_TOOL_PREFIXES` 상수는 접두사 기반 식별이었지만 rename
이후 `geny_` 접두사가 없어졌으므로 접두사 매칭으로 플랫폼 툴을
식별할 수 없다. **ToolLoader의 source stem 기반 allowlist**로 전환:

```python
# 플랫폼 제공 built-in tool 파일 stem. ToolLoader가 각 툴의 source
# stem을 `_tool_source`에 저장하므로, 이 set에 속한 stem의 툴은
# 플랫폼 카테고리로 간주한다.
_PLATFORM_TOOL_SOURCES = frozenset({
    "geny_tools",
    "memory_tools",
    "knowledge_tools",
})
```

`_vtuber_tool_roster` 시그니처 변경 — 이제 `ToolLoader` 인스턴스를
받아 source 기반 필터링을 한다:

```python
def _vtuber_tool_roster(
    all_tool_names: List[str],
    tool_loader: Optional[Any] = None,
) -> List[str]:
    """..."""
    if tool_loader is None:
        # legacy signature fallback — prefix heuristic
        return _legacy_prefix_filter(all_tool_names)

    return [
        name for name in all_tool_names
        if (
            tool_loader.get_tool_source(name) in _PLATFORM_TOOL_SOURCES
            and name not in _VTUBER_PLATFORM_DENY
        )
        or name in _VTUBER_CUSTOM_TOOL_WHITELIST
    ]
```

`_legacy_prefix_filter`는 tool_loader가 없는 호출자(주로 테스트)를
위한 좁은 폴백. 프로덕션 경로(`create_vtuber_env` → `install_
environment_templates` → main.py의 boot 시퀀스)는 tool_loader를
넘기는 시그니처로 업데이트.

#### 2-2. `_VTUBER_PLATFORM_DENY` 확장

```python
_VTUBER_PLATFORM_DENY = frozenset({
    "session_create",                 # cycle 7 보존
    "session_list",                    # 탐색 유혹 차단
    "session_info",
    "send_direct_message_external",    # 주소지정형 DM 차단
})
```

Sub-Worker 쪽에는 별도 deny 없음 — Sub-Worker는 legitimate하게
`session_create` 등을 쓸 수 있다.

#### 2-3. `create_vtuber_env` 호출 경로 업데이트

`all_tool_names` + `tool_loader` 쌍을 받도록 시그니처 확장.
`install_environment_templates`와 `main.py`의 boot 시퀀스에서
이미 가지고 있는 ToolLoader 인스턴스를 넘겨준다.

#### 2-4. 새 회귀 테스트

파일: `tests/service/environment/test_templates.py` (확장)

- `test_vtuber_env_has_internal_dm_and_inbox_only`:
  VTuber env의 external 리스트에 `send_direct_message_internal`,
  `read_inbox`가 있고, `send_direct_message_external`,
  `session_list`, `session_info`, `session_create`가 *없음*
- `test_vtuber_env_has_no_room_tools`:
  `room_*`으로 시작하는 이름이 하나도 없음 (source 기반 allowlist가
  room 툴을 포함하는 것을 방지하는 게 아니라, TOOLS export에서
  빠져 있어서 애초에 ToolLoader가 모르기 때문)
- `test_worker_env_retains_full_messaging_set`:
  Worker env에는 `session_*`과 `send_direct_message_external`이
  정상적으로 포함됨

파일: `tests/service/environment/test_tool_registry_roster.py` (확장)

- `test_vtuber_pipeline_registers_internal_dm_tool`:
  실제 `Pipeline.from_manifest`로 구성한 VTuber registry에
  `send_direct_message_internal`이 실제로 등록되어 있음
  → **cycle 7의 통합 테스트 갭을 메우는 핵심 케이스**
- `test_vtuber_pipeline_does_not_register_external_dm_tool`:
  동일 registry에 `send_direct_message_external` 없음

파일: `tests/service/test_tool_loader.py` (신규 또는 기존 확장)

- `test_tool_loader_does_not_load_room_tools`:
  `ToolLoader.load_all()` 후 `get_all_names()`에 `room_*`이 0개

### 검증 (PR-2)

```bash
cd backend && pytest tests/service/environment tests/service/langgraph \
  tests/integration tests/service/test_tool_loader.py -x -q
```

PR-1의 기존 테스트 + PR-2의 새 케이스 모두 통과.

### 배포 관점

기존 VTuber 세션은 재시작 시 새 매니페스트 seed를 받으므로 로스터가
자동으로 수렴. 커스텀 VTuber 환경이 DB에 저장되어 있는 경우는 매니페스트의
`external_tool_names`에 과거 이름이 남아 있을 수 있으나 `session_list`
등 deny 대상은 ToolRegistry에 등록되지 않는다 (`_vtuber_tool_roster`
필터가 환경 생성 시점에 적용됨 — 다만 기존 DB seed는 재생성되지 않음).

이 케이스를 위해 `install_environment_templates`는 boot 시 seed env
두 개를 무조건 덮어쓰도록 이미 되어 있으므로(`templates.py:228-234`),
표준 boot sequence로 충분. 사용자 맞춤 환경은 유저 책임.

---

## 라이브 스모크 체크리스트 (PR-1 + PR-2 머지 후)

1. 서비스 재시작
2. 새 VTuber 세션 생성 → 바인딩된 Sub-Worker 자동 생성 확인
3. 툴 로스터 검사 (log line "Tool registry loaded" 또는 API):
   - VTuber: `send_direct_message_internal`, `read_inbox`, +
     `memory_*`, `knowledge_*`, `web_search`, `news_search`,
     `web_fetch` 만
   - Sub-Worker: full set (Read/Write/Edit/Bash/Glob/Grep +
     `send_direct_message_external`, `session_*`, `read_inbox`,
     `send_direct_message_internal`)
   - `room_*` 이름이 **양쪽 모두에** 없음
4. 유저: "Sub-Worker에게 test.txt 파일을 만들라고 해줘"
5. VTuber 첫 호출에 `send_direct_message_internal` 이 찍힘.
   `send_direct_message_external` 호출 **0회**, `session_list`
   호출 **0회**.
6. Sub-Worker가 Write 성공 → `storage/<sub_id>/test.txt` 존재
7. *(Bug 2a/2b는 plan/02, plan/03에서 별도로 마무리)*

## 비범위 (이번 plan에서 안 함)

- Bug 2a (채팅 브로드캐스트) — plan/02에서
- Bug 2b (메모리 연속성) — plan/03에서
- Room 기능의 실제 삭제 — 코드 유지, export만 주석 (재활성 용이성
  확보)
- geny-executor 버전 변경 — 이번 plan은 Geny 단독
