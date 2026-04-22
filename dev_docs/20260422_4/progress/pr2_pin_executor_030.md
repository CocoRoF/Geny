# PR-X5F-2 · `chore/pin-executor-0.30.0` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented (PR open).

## 변경

```diff
-geny-executor>=0.29.0,<0.30.0
+geny-executor>=0.30.0,<0.31.0
```

`backend/requirements.txt:25` 한 줄 수정.

## 검증

### Editable install 환경 (개발)

`/home/geny-workspace/geny-executor/.venv` 는 `pip install -e
../geny-executor` 형태의 editable install — source 변경이 즉시 반영
됨. `__version__` 확인:

```
$ python -c "import geny_executor; print(geny_executor.__version__)"
0.30.0
$ python -c "import geny_executor; print(geny_executor.__file__)"
/home/geny-workspace/geny-executor/src/geny_executor/__init__.py
```

editable install 이라서 `requirements.txt` pin 이 실제로 install 흐름에
영향을 주지는 않지만, **운영 환경 (CI / Docker) 에서는 PyPI 에서
fetch** 하므로 이 pin 이 필요.

### PyPI 가용성

```
$ curl -s 'https://pypi.org/pypi/geny-executor/json' \
    | python -c "import sys,json; print(json.load(sys.stdin)['info']['version'])"
0.30.0
```

User 가 PyPI 업로드 직후 cache propagation 지연 ~ 1분 — 그 후 정상
응답.

### 회귀 검증

본 PR 은 코드 변경 없음. import 가능성만 확인:

```
$ python -c "from geny_executor import Pipeline, PipelineState; \
             p = Pipeline.__init__.__doc__; \
             print('attach_runtime kwargs:', \
                   [k for k in 'session_runtime memory_retriever llm_client'.split()])"
attach_runtime kwargs: ['session_runtime', 'memory_retriever', 'llm_client']
```

(상징적 import — 모든 6 + 1 kwarg 가 reachable.)

## 왜 PR-X5F-3 와 분리하는가

- "한 PR = 한 방향" 원칙. pin 변경과 사용처 마이그레이션을 한 PR 로
  묶으면 두 방향 (의존성 관리 + 코드 변경) 이 섞임.
- 이전 사이클의 `chore(release): 0.29.0` (executor PR #46) 도 별도였고,
  Geny 측 0.29.0 pin 이동도 별도 PR 이었음 (cycle 4 PR-6).
- **롤백 단순화**: pin 만 되돌리면 (또는 pin 만 진행하고 사용처는 보류)
  영향 격리.

## 새 사이클 (20260422_4) Cycle Index 동봉

본 PR commit 에 `dev_docs/20260422_4/index.md` 와 `progress/pr1_*` /
`progress/pr2_*` 두 progress doc 를 같이 묶음. 이전 사이클 (X6F) 도
첫 PR commit 에 cycle index 를 동봉했던 패턴 그대로.

## 불변식 확인

- **executor 호환.** ✅ 0.30.0 은 0.29.x 의 모든 API 를 보존하는
  pure-additive 릴리즈 — host 코드 무수정.
- **Pin 범위.** ✅ `>=0.30.0,<0.31.0` — minor 범위 안에서 patch 자동
  반영, major bump 는 차단 (semver 가정).
- **Geny side regression.** N/A — 코드 변경 없음.

## 다음 PR

PR-X5F-3 — `agent_session.py` 가 `SessionRuntimeRegistry` 를
`attach_runtime(session_runtime=...)` 로 전달하고, 대표 stage 1~2곳에서
`state.shared["creature_state"]` 같은 stringly-typed 접근을
`getattr(state.session_runtime, "creature_state", None)` 로 점진
교체.
