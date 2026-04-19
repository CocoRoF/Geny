# 01. geny-executor 의존성 0.20.0 으로 교체

## Scope

Geny backend 가 설치하는 `geny-executor` 버전을 `>=0.20.0` 으로 고정.
이 PR 은 **순수 의존성 교체만** 수행한다 — Environment / MemoryProvider /
새 REST 엔드포인트는 후속 PR (Phase 2 이후) 에서 붙인다.

## PR Link

- feat/fix 아님: `chore(dep): bump geny-executor to 0.20.0`
- Branch: `chore/bump-geny-executor-0.20.0`
- PR: (이 커밋 푸시 시 발행)

## Summary

- `backend/pyproject.toml` : `"geny-executor>=0.8.3"` → `"geny-executor>=0.20.0"`.
- `backend/requirements.txt` : `geny-executor>=0.10.0` → `geny-executor>=0.20.0`
  (두 파일의 하한선이 엇갈려 있던 문제도 이 참에 정리).
- `GenyPresets.worker_adaptive / vtuber` 시그니처를 v0.20.0 본문 (`geny_executor/memory/presets.py`)
  과 교차 확인. `agent_session.py:_build_pipeline` 의 호출 kwargs 와 1:1
  일치하므로 별도 조정 없음.
- 스모크:
  - `python -m py_compile backend/service/langgraph/agent_session.py` ✅
  - `python -m py_compile backend/service/langgraph/tool_bridge.py` ✅
- 실제 엔드투엔드 invoke 스모크는 v0.20.0 이 PyPI 에 올라와 있어야 하므로,
  CI / 사용자 환경에서 설치 단계에서 재검증.

## Follow-ups

- Phase 2 (`plan/02_executor_rewire.md`) 부터는 `MemoryProvider` / `Environment`
  주입 경로를 새로 뚫어야 한다. 이 PR 은 의존성만 올린다는 계약을 지킬 것.
- `docker-compose*.yml` 의 빌드 캐시 무효화는 CI 빌드 결과로 확인. 캐시 히트가
  걸려서 구버전이 잡힌다면 후속 PR 에서 `--no-cache` 빌드 트리거 조건 명시.
- v0.20.0 의 선택적 `postgres` extra 도입은 `plan/01_dependency_bump.md` 의
  옵션 스펙에 맞춰 Phase 5 의 pgvector 마이그레이션과 함께 평가.
