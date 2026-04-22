# PR-X5F-1 (+ PR-X5F-R) · executor `session_runtime` attach slot — 진행 기록

**Date.** 2026-04-22
**Repo.** `geny-executor`
**Status.** Shipped — 0.30.0 PyPI 업로드 완료.

본 사이클의 **선행** PR (executor 리포) 두 개를 Geny 쪽 dev_docs
에서 회고로 보관.

## PR-X5F-1 (executor PR #47, commit `7fbd92b`)

브랜치: `feat/attach-runtime-session-runtime-kwarg`

### 변경

- `Pipeline.attach_runtime(session_runtime=...)` — 7번째 kwarg.
- `PipelineState.session_runtime: Optional[Any] = field(default=None, repr=False)`.
- `Pipeline.__init__` 에 `self._attached_session_runtime` 초기화.
- `_init_state` 에서 `state.session_runtime` 이 `None` 일 때만 attached
  값을 propagate — 호출자가 미리 채운 state 가 우선 (기존 `llm_client`
  semantics 와 동일).
- attach_runtime docstring 에 plugin-compat 가이드라인 추가:
  `getattr(state.session_runtime, "foo", None)` 로 접근, 없는 attr 은
  opt-out.

### 핵심 설계 결정

**왜 `Any`인가.** Protocol / ABC 를 강제하면 "executor 는 게임을 모른다"
불변식과 충돌. plugin 들의 attribute schema 협의는 host 정책
(docstring 가이드라인 수준)으로 격리.

**왜 새 stage 가 아니라 state field 인가.** `session_runtime` 은
"현재 turn 동안 어떤 stage 든 들춰볼 수 있어야 하는 host-scoped 객체"
다. stage 로 만들면 (a) order 결정 부담, (b) stage 간 dependency 가
생김. state field 는 "free-form carrier" 라는 의도를 가장 직접 표현.

**왜 `_attached_*` + `_init_state` 패턴인가.** 기존 `llm_client` 가
이미 같은 형태로 운영 중. 동일 패턴으로 두면 호출자 / reviewer 의
모델이 간단해지고, post-run re-attach 거부 등 invariant 검사도 그대로
재사용.

### 테스트

`tests/unit/test_pipeline_session_runtime.py` (신규, 9 tests):

1. `test_fresh_state_has_null_session_runtime` — 기본값 `None`.
2. `test_attach_runtime_no_session_runtime_kwarg_leaves_state_none` — 기존
   host 무영향.
3. `test_attach_runtime_accepts_arbitrary_session_runtime` — 임의 객체
   attach + run 정상.
4. `test_session_runtime_lands_on_state_inside_stage` — stage 안에서
   `state.session_runtime` 으로 가져갈 수 있음.
5. `test_session_runtime_accepts_any_type` — dict / `object()` / lambda
   모두 통과.
6. `test_pre_populated_state_session_runtime_is_preserved` — 호출자
   state 가 우선.
7. `test_attach_runtime_session_runtime_idempotent_before_run` — 같은
   kwarg 두 번 호출 → 마지막 wins.
8. `test_attach_runtime_session_runtime_refused_after_run` — run 시작 후
   `RuntimeError`.
9. `test_session_runtime_does_not_affect_llm_client_resolution` — 기존
   `llm_client` 경로와 독립.

전체 unit sweep: 682 passed, 1 skipped (회귀 0).

## PR-X5F-R (executor PR #48, commit `4bd2ef2`)

브랜치: `chore/release-0.30.0`

- `pyproject.toml`: `0.29.0` → `0.30.0`.
- `src/geny_executor/__init__.py`: `__version__ = "0.30.0"`.
- `CHANGELOG.md`: 0.30.0 entry 추가 (Added / Intentionally not added /
  Host upgrade note).

### PyPI 업로드

merge 후 user 가 `python -m build && twine upload` 로 PyPI 게시.
PyPI JSON API 가 0.30.0 으로 보고하기까지 ~ 1분의 cache propagation
지연 후 검증 완료 (2026-04-22).

## Geny 측 영향 — 후속 PR 들

| PR | 어떤 의존 |
|---|---|
| PR-X5F-2 | `requirements.txt` 의 executor pin 을 0.30.0 으로 이동 — *PyPI 0.30.0 가용성*에 의존 |
| PR-X5F-3 | `attach_runtime(session_runtime=...)` 호출 — *executor 0.30.0 코드 가용성*에 의존 |
| PR-X5F-4 | cycle close — 위 둘 merge 에 의존 |
