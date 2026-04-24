# PR-5 Progress — Dissolve `claude_manager/` folder

**Branch:** `refactor/20260424_2-pr5-dissolve-claude-manager`
**Base:** `main @ 6d33d53` (PR-4 merged)

## Folder relocations (`git mv`)

| Old | New | Reason |
|---|---|---|
| `backend/service/claude_manager/models.py` | `backend/service/sessions/models.py` | 도메인 모델, CLI 무관 |
| `backend/service/claude_manager/session_store.py` | `backend/service/sessions/store.py` | 세션 영속화, 더 짧은 이름 |
| `backend/service/claude_manager/platform_utils.py` | `backend/service/utils/platform.py` | 범용 플랫폼 유틸 |
| `backend/service/claude_manager/storage_utils.py` | `backend/service/utils/file_storage.py` | 범용 파일 I/O + gitignore |

`backend/service/claude_manager/__init__.py` 삭제 → 폴더 제거.

## New package — `backend/service/sessions/`

```
service/sessions/
├── __init__.py   # public re-exports (SessionInfo, SessionRole, MCPConfig, ...)
├── models.py
└── store.py
```

`__init__.py` 는 `service.sessions` 로 접근 가능한 심볼들을 단일 지점에서 노출.

## Import rewrites (bulk sed)

21 파일에서 `from service.claude_manager.X` / `service.claude_manager.X` / `service/claude_manager/X` 경로를 새 위치로 치환. 치환 규칙:

- `service.claude_manager.models` → `service.sessions.models`
- `service.claude_manager.session_store` → `service.sessions.store`
- `service.claude_manager.platform_utils` → `service.utils.platform`
- `service.claude_manager.storage_utils` → `service.utils.file_storage`

### 특수 케이스 — `from service.claude_manager import storage_utils`
`agent_controller.py:885, 916` 두 곳이 submodule 을 alias 로 import 하는 패턴. `from service.utils import file_storage as storage_utils` 로 교체 (호출부 `storage_utils.list_storage_files(...)` 그대로 작동).

### 내부 self-reference
`service/sessions/store.py` docstring 예제의 import 경로 + `service/logging/tool_detail_formatter.py` 의 historical 주석 (`service.claude_manager.process_manager ... removed in cycle 20260424_2 PR-4`) 적절히 갱신.

## Active docs 경로 갱신 (sed bulk)

- `backend/docs/EXECUTION{,_KO}.md`
- `backend/docs/MCP{,_KO}.md`
- `backend/docs/SUB_WORKER{,_KO}.md`
- `docs/VTUBER_ARCHITECTURE_REVIEW.md`
- `docs/DUAL_AGENT_ARCHITECTURE_PLAN.md`
- `backend/README{,_KO}.md` 파일 트리 diagram

## Intentional leftovers

다음 `claude_manager` 언급은 **의도적으로 유지**:
- `docs/EXECUTOR_INTEGRATION_REPORT.md` 본문 — 2026-04-14 시점 스냅샷 (cycle 20260424_1 에서 상단 배너로 시간 맥락 명시)
- `docs/analysis/STORAGE_MEMORY_INTERACTION_REVIEW.md` — 분석 당시 관찰 (스냅샷 문서 원칙)
- `backend/service/logging/tool_detail_formatter.py:4` — historical context 주석
- `backend/service/sessions/__init__.py:5` — "Moved here from claude_manager/ in cycle 20260424_2 PR-5" 출처 명시
- `dev_docs/20260424_*/` — 이 cycle 들의 audit/plan/progress 자체가 claude_manager 를 기술

## Verification

```bash
$ grep -rn "claude_manager" backend/ docs/ \
    | grep -v __pycache__ | grep -v _archive | grep -v 20260424 \
    | grep -v tool_detail_formatter | grep -v EXECUTOR_INTEGRATION_REPORT \
    | grep -v sessions/__init__.py
docs/analysis/STORAGE_MEMORY_INTERACTION_REVIEW.md:72 ... (의도된 스냅샷)
```

```bash
$ test -d backend/service/claude_manager && echo EXISTS || echo "(gone)"
(gone)
```

## Cycle close

| PR | 결과 | LOC 영향 |
|---|---|---|
| PR-1 #262 | `claude_controller` 삭제 | −397 |
| PR-2 #263 | `SessionManager` 상속 끊기 | −16 |
| PR-3 #264 | `command_controller` 재작성 | −169 |
| PR-4 #265 | Dead chain 파일 삭제 | −2,101 |
| PR-5 (this) | 폴더 해체 + 재배치 | rename only |

**총 삭제 ~2,683 LOC.** `backend/service/claude_manager/` 폴더 완전 해체.
