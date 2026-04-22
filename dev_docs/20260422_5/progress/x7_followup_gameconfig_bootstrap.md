# X7-follow-up · GameConfig bootstrap + role gating — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented. 201 backend tests pass (regression 0).
사용자 피드백 **"이전에 처리한 수많은 VTuber status를 이용한 다마고치
형 gameification 시스템이 아무것도 안 나온다"** 에 대한 실행 수정.

## 원인 재확인 (Explore 두 차례)

- `backend/main.py:368-389` 가 `GENY_GAME_FEATURES` env var 에 의해
  gating. default `"0"` (off).
- `.env.example` / docker 설정 어디에도 해당 env var 명시 없음 →
  operator 가 존재 자체를 몰랐음.
- 결과: `agent_manager._state_provider = None`. 모든 세션이
  `state_provider=None` 으로 생성 → `load_creature_state_snapshot()`
  None 반환 → X7 에서 얹은 CreatureStatePanel UI 는 숨김 조건 성립.
- 사용자가 본 세션 `b66c0285-97ae-49ba-81bb-495349ef36d1` 은 당시
  classic 으로 frozen — 되돌릴 수 없음.

X3 PR-X3-5 (2026-04-21) 이 의도적으로 "shadow mode default" 로 닫아
둔 것을 **활성화 사이클에서 열어야 했는데 한 번도 열지 않음**. 내가
X7 작업 시 bootstrap 확인 안 한 실책.

## 변경 요약

### 1. `service.config.sub_config.general.game_config.GameConfig` (신규)

Config 시스템 기반 toggle. env var 를 대체하면서도 legacy env 를
**1 사이클** 동안 fallback 으로 지원.

- `enabled: bool = True` — **default on**. X3..X7 인프라가 이미
  production-ready 이므로 다마고치가 기본 동작.
- `state_db_path: str = ""` — 빈 문자열 = main.py 의 canonical path
  사용 (`backend/data/geny_state.sqlite3`).
- `vtuber_only: bool = True` — VTuber role 세션에만 state_provider 를
  wire. 일반 Worker / Sub-Worker 는 classic 유지 → orphan creature
  rows 방지.
- `get_default_instance()` 가 `read_env_defaults(_ENV_MAP, ...)` 로
  legacy env (`GENY_GAME_FEATURES` / `GENY_STATE_DB`) 를 한 번만 반영.
  이후 DB + JSON 으로 persist → 다음 부팅부터 config 값 우선.
- i18n (ko/en) + FieldType metadata 로 **Settings UI 자동 렌더**.
  별도 frontend 작업 불필요.

### 2. `backend/main.py` lifespan 재배선

기존:
```python
geny_game_features = (
    os.environ.get("GENY_GAME_FEATURES", "0").strip().lower()
    in ("1", "true", "yes", "on")
)
# ... env-based construction
agent_manager.set_state_provider(state_provider, decay_service=decay_service)
```

신규:
```python
from service.config.sub_config.general.game_config import GameConfig
game_cfg = config_manager.load_config(GameConfig)
if game_cfg.enabled:
    resolved_db_path = game_cfg.state_db_path.strip() or default_path
    ...
    agent_manager.set_state_provider(
        state_provider,
        decay_service=decay_service,
        vtuber_only=game_cfg.vtuber_only,
    )
```

### 3. `AgentSessionManager` — `vtuber_only` 롤 게이팅

- `set_state_provider(..., vtuber_only: bool = True)` 시그니처 확장.
- `__init__` 에 `self._state_provider_vtuber_only: bool = True` 초기화.
- `create_agent_session` 에서 provider 전달 직전에 per-session 결정:
  ```python
  _role_allows_state = (
      (not self._state_provider_vtuber_only)
      or request.role == SessionRole.VTUBER
  )
  _session_state_provider = (
      self._state_provider if (_has_state_provider and _role_allows_state)
      else None
  )
  ```
  `state_provider=_session_state_provider` / `character_id` / `manifest_selector`
  / `install_affect_tag_emitter` 모두 이 값으로 게이트.

### 4. 테스트

신규:
- `tests/service/config/test_game_config.py` — 7 tests. 기본값, name/
  category, 필드 shape, BOOLEAN type pin, legacy env fallback 양방향
  (on/off), i18n 존재.
- `tests/service/langgraph/test_agent_session_manager_state.py` — 2
  tests 추가. vtuber_only 저장 / default.

회귀:
```
pytest backend/tests/service/emit/ backend/tests/service/affect/ \
       backend/tests/service/database/ backend/tests/service/state/test_registry.py \
       backend/tests/service/state/test_registry_catchup.py \
       backend/tests/service/state/test_tool_context.py \
       backend/tests/service/config/test_game_config.py \
       backend/tests/service/langgraph/test_agent_session_manager_state.py \
       backend/tests/integration/test_state_e2e.py -q

201 passed
```

## 불변식 체크

- **executor 무수정.** ✅
- **Pure additive config.** ✅ 기존 config class 들 무변. 새 GameConfig
  하나 추가. 기존 env var 는 legacy fallback 으로 여전히 동작.
- **기존 세션 무영향.** ✅ 이미 frozen 된 classic 세션 (user 의
  `b66c0285...` 포함) 은 그대로. 재시작 후 *새* 세션부터 효과.
- **Worker / Sub-Worker classic 유지.** ✅ `vtuber_only=True` default
  로 role 기반 게이팅.
- **Mutation 4 op / FAISS / retriever 무영향.** ✅
- **Side-door 금지.** ✅ config manager 는 기존 공식 접점.

## 사용자 액션 체크리스트

1. **Backend 컨테이너 재빌드 + 재시작.** GameConfig 가 load 되면서
   default (enabled=True) 로 state_provider bootstrap. 로그 확인:
   ```
   - CreatureState: enabled (sqlite=/app/data/geny_state.sqlite3,
     decay interval=15m, vtuber_only=True)
   ```
2. **Frontend 재빌드.** 이전 X7 PR 의 CreatureStatePanel 이 이미 들어
   있으므로 별도 변경 없음.
3. **새 VTuber 세션 생성.** 기존 `b66c0285...` 는 buried classic.
   **새로 만든** VTuber 세션부터 creature_state 가 채워지고 InfoTab
   에 다마고치 패널이 뜸.
4. **Settings UI 확인 (선택).** `/settings` → "Tamagotchi" (한국어:
   "다마고치") 카테고리. enabled toggle / vtuber_only toggle 조정
   가능. 변경 후 재시작 필요.

## 다음 액션 후보

- **이벤트 페인트.** 현재 CreatureStatePanel 은 InfoTab mount 시
  1회 fetch. 턴 종료마다 live update 하려면 `agent_progress` SSE 에
  `creature_state_update` 합류.
- **Config 변경 즉시 적용.** `apply_change` 콜백이 `agent_manager.set_state_provider(...)`
  를 재호출하도록 (현재는 재시작 필요).
- **기존 세션 마이그레이션.** 원하는 경우 classic 세션에 state_provider
  를 **retroactively** 붙이는 admin path (현재는 불가능).
