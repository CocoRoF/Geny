# 01. 의존성 점프

## 목표

`geny-executor` 를 `>=0.8.3` → `>=0.20.0` 으로 바꾼다. 이후 단계의 전제.

## 변경 파일

- `backend/pyproject.toml` (직접 수정)
- `backend/requirements.txt` (동기화)
- `docker-compose.yml` / `docker-compose.dev.yml` / `docker-compose.prod.yml` (빌드 캐시 버스트 확인)

## `pyproject.toml` 수정 예시

```toml
# Before
"geny-executor>=0.8.3",

# After
"geny-executor>=0.20.0",

# Optional
[project.optional-dependencies]
postgres = [
  "geny-executor[postgres]>=0.20.0",
]
```

> **주의**: Geny 는 이미 `psycopg[binary]>=3.2.0`, `psycopg-pool>=3.2.0` 을 가지고
> 있으므로 executor `[postgres]` extra 와 중복. 중복은 괜찮지만 **psycopg 버전 충돌
> 여부**를 PR CI 에서 확인.

## 작업 순서

1. `backend/pyproject.toml` 에서 pin 교체.
2. `pip install -U geny-executor` (로컬 확인).
3. 스모크:
   ```bash
   python -m py_compile backend/service/langgraph/agent_session.py
   python -m py_compile backend/service/langgraph/tool_bridge.py
   ```
4. 실제 실행 스모크 (가능한 경우):
   - `POST /api/agents` → 세션 생성.
   - `POST /api/agents/{id}/invoke` → 간단 프롬프트.
   - 이벤트 스트림이 `stage.enter`, `tool.execute_*`, `pipeline.complete` 순으로 들어오는지.
5. 실패 시:
   - 가장 가능성 높은 회귀 지점: `GenyPresets.vtuber` / `worker_adaptive` 의 시그니처 파라미터 추가/변경 — `memory/presets.py` 읽어서 비교.
   - `ToolContext` 의 새 필드 (`stage_order/stage_name`) 는 기본값 있으므로 무시 가능.

## PR 메시지 (템플릿)

```
chore(dep): bump geny-executor to 0.20.0

- GenyPresets still exposed at geny_executor.memory.GenyPresets (compat).
- New memory provider ecosystem not wired yet — see plan/03, plan/04.
- Smoke: session create + simple invoke verified.

Refs analysis/03_executor_api_delta.md, plan/00_strategy.md
```

## 리스크

| 리스크 | 감지 | 대응 |
|--------|------|------|
| `GenyPresets` 시그니처 변경 | 타입/런타임 에러 | `agent_session.py:_build_pipeline` 의 kwargs 맞춰 조정 |
| 내장툴 동작 변경 (파일 접근 제약 등) | 스모크 실패 | 내장툴 사용 최소 테스트 케이스 돌리고 파라미터 조정 |
| 이벤트 스키마 변동 | UI 로그 에러 | 이벤트 문자열 비교 로직은 enum 화 고려 |

## 수용 기준

- 기존 `/api/agents` 플로우가 회귀 없이 동작.
- CI 통과.
- 아무 Environment 기능도 **아직** 추가되지 않음 (순수 의존성 교체).
