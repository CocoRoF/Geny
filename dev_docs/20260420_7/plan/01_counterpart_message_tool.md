# Plan/01 — 내장 대칭 도구 `geny_message_counterpart`

**브랜치.** `feat/counterpart-message-tool`
**선행.** 20260420_6 (병합 완료) — 어댑터 `session_id` 주입 확정

## 설계 원칙

- 입력 스키마에 **target이 없다**. LLM이 UUID를 복사할 자리 자체가
  없다 → 오배달 불가능.
- **대칭**: VTuber → Sub-Worker, Sub-Worker → VTuber 둘 다 같은
  도구를 쓴다. 로직 동일 — "내 링크된 상대에게 보낸다".
- **런타임 해석**: 어댑터가 `ToolContext.session_id`로 호출자 에이전
  트를 찾고, `agent._linked_session_id`로 상대를 결정.
- **실패 시 명확한 에러**: 링크가 없으면 새 세션 생성 같은 fallback
  없이 `{"error": "no linked counterpart"}` 반환.

## 코드 변경

### 1) 새 도구 — `backend/tools/built_in/geny_tools.py`

`GenySendDirectMessageTool` 바로 아래에 추가:

```python
class GenyMessageCounterpartTool(BaseTool):
    """링크된 상대 에이전트에게 메시지를 보낸다.

    VTuber→Sub-Worker 및 Sub-Worker→VTuber 모두 동일 로직.
    session_id(호출자)는 어댑터가 주입하며, 상대 세션은
    AgentSession._linked_session_id에서 해석한다. LLM은 상대 ID를
    알 필요도, 전달할 필요도 없다.
    """

    name = "geny_message_counterpart"
    description = (
        "Send a message to your bound counterpart (VTuber↔Sub-Worker). "
        "No target is needed — the runtime routes to whichever agent is "
        "linked to you. Use this instead of geny_send_direct_message "
        "whenever you want to reach your paired agent."
    )

    def run(self, session_id: str, content: str) -> str:
        if not content.strip():
            return json.dumps({"error": "content must be non-empty"})

        manager = _get_agent_manager()
        self_agent = manager.get_agent(session_id) \
            or manager.resolve_session(session_id)
        if self_agent is None:
            return json.dumps({"error": f"caller session not found: {session_id}"})

        counterpart_id = getattr(self_agent, "_linked_session_id", None)
        if not counterpart_id:
            return json.dumps({
                "error": "no linked counterpart — this session has no bound pair",
            })

        target, resolved_id = _resolve_session(counterpart_id)
        if not target:
            return json.dumps({
                "error": f"linked counterpart {counterpart_id} no longer exists",
            })

        inbox = _get_inbox_manager()
        msg = inbox.deliver(
            target_session_id=resolved_id,
            content=content.strip(),
            sender_session_id=session_id,
            sender_name=self_agent.session_name or session_id[:8],
        )

        _trigger_dm_response(
            target_session_id=resolved_id,
            sender_session_id=session_id,
            sender_name=self_agent.session_name or session_id[:8],
            content=content.strip(),
            message_id=msg["id"],
        )

        return json.dumps({
            "success": True,
            "message_id": msg["id"],
            "delivered_to": resolved_id,
            "delivered_to_name": target.session_name,
            "timestamp": msg["timestamp"],
        }, indent=2, ensure_ascii=False, default=str)
```

`session_id`를 `run` 시그니처에 실제 파라미터로 선언하므로
`_probe_session_id_support`(Cycle 6)가 True를 반환 → 어댑터가
`ToolContext.session_id`를 자동 주입 → LLM-visible 스키마에서는
`content`만 노출.

### 2) VTuber 프롬프트 전환 — `backend/prompts/vtuber.md`

`## Task Delegation` / `## Task Handling` 섹션의 `geny_send_direct_
message` 언급을 `geny_message_counterpart`로 교체. 인자 설명은
`content`만.

### 3) Sub-Worker 프롬프트 대응

`agent_session_manager.py:290-297`의 Sub 섹션:

```python
sub_ctx = (
    f"\n\n## Paired VTuber Agent\n"
    f"You are bound to a VTuber persona.\n"
    f"Report results via `geny_message_counterpart` — you do not "
    f"need to specify any target; the runtime routes to your "
    f"paired VTuber automatically."
)
```

마찬가지로 `agent_session_manager.py:653-664`의 VTuber 섹션도
`geny_message_counterpart`를 쓰도록 재작성 (링크 ID 노출 제거).

### 4) VTuber 프리셋에서 `geny_session_create` 제거

`backend/service/environment/templates.py` — VTuber가 세션을 만들 일은
없다. 접두사 화이트리스트 대신 명시적 블랙리스트를 추가:

```python
_VTUBER_PLATFORM_DENY = frozenset({"geny_session_create"})

def _vtuber_tool_roster(all_tool_names):
    return [
        name for name in all_tool_names
        if (name.startswith(_PLATFORM_TOOL_PREFIXES)
            and name not in _VTUBER_PLATFORM_DENY)
        or name in _VTUBER_CUSTOM_TOOL_WHITELIST
    ]
```

`install_environment_templates`가 boot 시 재작성하므로 배포 즉시 반영.

## 테스트 — `backend/tests/tools/test_counterpart_message_tool.py` (신규)

| 케이스 | 기대 |
|---|---|
| VTuber 호출자, 링크된 Sub-Worker 존재 | 성공; Sub-Worker inbox에 배달; `_trigger_dm_response` 호출 |
| Sub-Worker 호출자, 링크된 VTuber 존재 | 성공; VTuber inbox에 배달 (대칭성) |
| 링크 없는 솔로 Worker | `{"error": "no linked counterpart..."}`, 부작용 없음 |
| 링크된 세션이 이미 삭제된 상태 | `{"error": "linked counterpart ... no longer exists"}` |
| 빈 content | `{"error": "content must be non-empty"}` |
| 어댑터 주입 확인 | `_probe_session_id_support` True, `ToolContext.session_id` 자동 주입되어 `session_id` 인자가 생략된 LLM 호출도 성공 |
| 스키마 노출 확인 | `GenyMessageCounterpartTool().parameters["properties"]`에 `target_session_id` 없음, `content`만 존재 |

기존 `test_tool_bridge.py`의 matrix(14건)와 합쳐 probe 경로 회귀도
유지.

## VTuber 프리셋 회귀 — `test_templates.py` 확장

- `geny_session_create`가 VTuber 롤에서 제외되는지
- `geny_message_counterpart`가 VTuber & Worker 양쪽에 포함되는지

## 라이브 스모크 (병합 후)

1. 백엔드 재시작
2. VTuber 세션 하나 생성 — 로그에서 `🔗 Sub-Worker created` 확인
3. "Sub-Worker에게 인사해달라고 해줘" 요청
4. 기대: VTuber가 `geny_message_counterpart(content="...")` 한 번
   호출, Sub-Worker가 응답, VTuber가 사용자에게 전달
5. **반례 검증**: `geny_session_create` 호출 로그가 없어야 함

## 롤백

- 새 도구 클래스 삭제, 프롬프트/템플릿 revert → 이전 상태 복귀
- 데이터 손상 없음 (inbox만 읽고 쓰는 도구이므로 부작용이 세션 런타임
  범위를 벗어나지 않음)
