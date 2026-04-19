# 66. Phase 7-34 — diff-bulk 에 per-env read cache

## Scope

Phase 7-32 의 `POST /api/environments/diff-bulk` 엔드포인트는 pair
마다 `svc.diff()` 를 호출했고, 그 안에서 pair 의 env 두 개를 각각
`_read_raw()` 로 읽는다. 매트릭스 형태 (N 개 env → N·(N-1)/2 pair) 에서
같은 env id 가 pair 여러 개에 걸쳐 반복 등장하므로 총 읽기 횟수가
`2 · N·(N-1)/2 = N·(N-1)` 에 달한다. 10 envs / 45 pairs 면 fs read 가
90 번, 50 envs / 1225 pairs 면 2450 번이다.

Phase 7-33 follow-up 에서 "diff-bulk 의 read cache (50 envs × 2 = 100
reads → 50 reads)" 로 표기했던 항목 — 실제로는 N·(N-1) → N 이다.

해결 방식: `/diff-bulk` 에서 pair 를 돌기 전에 `pairs` 에 등장하는
모든 unique env id 를 한 번씩만 읽어 `raw_cache` 에 모아두고, 각 pair
는 캐시 dict lookup 으로 처리.

## PR Link

- Branch: `feat/phase7-34-diff-bulk-cache`
- PR: (커밋 푸시 시 발행)

## Summary

`backend/service/environment/service.py` — 수정
- `diff(env_id_a, env_id_b)` 를 얇게 유지하고 실제 비교 로직을
  `diff_from_raw(raw_a, raw_b)` 로 분리. `diff()` 는 두 id 를 읽어
  `diff_from_raw()` 에 넘기는 thin wrapper. 기존 호출자 (없지만
  향후의) 에 대해 동일한 동작 유지.
- `diff_from_raw()` 는 둘 중 하나라도 `None` 이면 `[]` 반환 —
  `diff()` 와 동일한 "missing → empty" 계약.
- 새로운 public `read_raw(env_id)` — `_read_raw` 에 얇은 wrapper.
  `/diff-bulk` 처럼 "같은 env 를 여러 pair 에 걸쳐 읽고 싶지 않은"
  호출자가 load 의 manifest coercion 을 우회해 raw 레코드를 직접
  받을 수 있다.

`backend/controller/environment_controller.py` — 수정
- `/diff-bulk` 엔드포인트 진입부에서 `pairs` 의 `env_id_a`,
  `env_id_b` 를 set 으로 수집해 unique id 목록 생성.
- `raw_cache: dict[str, dict | None] = {id: svc.read_raw(id) for id in
  unique_ids}` — 각 env 당 최대 1 회 fs 읽기. 존재하지 않는 id 는
  `None` 값으로 저장되어 이후 pair 루프에서 자연스럽게 `ok=False,
  error="env not found"` 경로로 흐름.
- pair 루프는 기존 `svc.diff()` 대신 `svc.diff_from_raw(raw_cache.get(a),
  raw_cache.get(b))` 를 호출. 결과 집계는 동일.

## Verification

- 단일 pair (`env_id_a=X, env_id_b=Y`) — 두 env 모두 존재:
  unique_ids = {X, Y}, raw_cache 에 2 entry, diff 결과 Phase 7-32 와
  동일.
- 10 env 매트릭스 (45 pairs) — unique_ids 10 개, read 10 번.
  이전에는 90 번이었음. 응답 payload 는 동일.
- 하나의 env 만 존재하지 않음 (X 삭제됨, Y/Z 존재) — `raw_cache[X] =
  None`. 모든 `X` 관련 pair 가 `ok=False, error="env not found"`,
  나머지 pair 는 성공.
- 빈 pairs 리스트 → validator 가 먼저 차단 (Phase 7-32).
- 500 pair 상한 초과 → validator 가 차단 (Phase 7-32, 변화 없음).

## Deviations

- `diff_from_raw` 는 기존의 `diff` 내부 로직을 그대로 분리한 것이라
  동작상 변화 없음. 추가 테스트는 Phase 7-32 의 통합 테스트가 그대로
  커버.
- `read_raw` 는 `_read_raw` 의 얇은 wrapper. "왜 `_read_raw` 를 직접
  부르지 않느냐" — private leading-underscore 는 service 외부에서의
  호출을 의도하지 않는 규약이다. controller 가 private 에 의존하지
  않게끔 명시적 public surface 로 노출.
- "dict | None" 대신 `Optional[Dict[str, Any]]` 로 annotation —
  Pydantic / typing 호환 위해. controller 는 `dict | None` 를 사용
  (Python 3.10+, 해당 파일 이미 신택스 사용 중).
- raw_cache miss (캐시에 아예 키가 없음) 는 pair 가 검증을 통과한
  이상 발생하지 않지만, `dict.get(id)` 가 기본값 `None` 을 반환하므로
  `diff_from_raw` 의 "missing → []" 경로로 안전하게 흐른다.

## Follow-ups

- `_read_raw` 자체의 캐시 (서비스 인스턴스 수명 동안) — 지금은
  stateless 하지만 짧은 수명의 LRU 를 붙이면 diff-bulk 바깥의
  고빈도 read (예: drawer sessions + env detail 동시 로드) 도 감소.
  단 테스트 격리를 해쳐 위험. 측정 후 도입.
- `diff_from_raw` 를 service 의 `load()` 결과에 대해서도 사용할
  수 있게 overload — 현재는 `_read_raw` 결과 (manifest/snapshot 키
  포함 dict) 전용. 사용처가 생기면 시그니처 확장 검토.
- Matrix 모달이 결과를 받아 "most different pair" 를 하이라이트
  하는 UX (changed count 가 가장 큰 상단 비대각 셀에 tint). Phase
  7-35 후보.
