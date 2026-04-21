# PR-X3-7 · `feat/affect-tag-emitter` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 528/528 사이클 관련 pass (기존 500 + 신규 28).
`AffectTagEmitter` + s14 chain 주입 헬퍼 구현. `[emotion[:strength]]`
태그를 LLM 출력에서 추출하고, 동일 턴의 `MutationBuffer` 에 mood/bond
델타를 push, `final_text` 에서 태그를 제거.

## 범위

`plan/04 §4.2` 의 Emitter 규격 그대로 구현. `s10_tool` (PR-X3-6) 과
`s14_emit` (본 PR) 이 하나의 턴에서 같은 버퍼를 보며 동시에 상태를
쌓는다 — 두 경로 모두 PR-X3-6 의 ContextVar/bind 경로를 공유.

**Emitter 등록 전략.** executor 의 `EmitStage` 는 manifest 기반 chain
을 쓰며 기본 registry 는 `text`/`callback`/`vtuber`/`tts` 네 개. 이
registry 를 포크하거나 manifest 스키마를 확장하는 대신, Geny 가
`instantiate_pipeline` 직후에 "이미 만들어진 pipeline 의 chain 에
prepend" 방식으로 넣는다 (`install_affect_tag_emitter`). executor 는
CreatureState 를 모른 채로 남아 있다.

쉐도우 모드 유지. `state_provider` 가 None (classic mode) 이면 install
호출 자체를 건너뛰어서 기존 세션의 `final_text` 가 간접적으로라도
변조되지 않도록.

## 적용된 변경

### 1. `backend/service/emit/affect_tag_emitter.py` (신규)

```python
AFFECT_TAGS = ("joy", "sadness", "anger", "fear", "calm", "excitement")
AFFECT_TAG_RE = re.compile(
    r"\[(" + "|".join(AFFECT_TAGS) + r")\s*(?::(-?\d+(?:\.\d+)?))?\s*\]",
    flags=re.IGNORECASE,
)
MOOD_ALPHA = 0.15

class AffectTagEmitter(Emitter):
    async def emit(self, state) -> EmitResult:
        # 1. 태그 추출 (없으면 no-op)
        # 2. 태그 제거한 final_text 재기록 (double-space 정리)
        # 3. MutationBuffer 에 mood.<tag> += strength * MOOD_ALPHA
        # 4. joy/calm → bond.affection +=0.5, anger/fear → bond.trust -=0.3
```

**설계 포인트:**

- **Per-turn cap (`max_tags_per_turn=3`).** LLM 이 "[joy][joy][joy][joy]"
  로 mood 스팸하는 걸 차단. 캡을 초과한 매치는 mutation 만 drop 하고
  **스트립은 계속 적용** — 유저에게 태그가 그대로 노출되는 쪽이 더
  나쁘기 때문.
- **Unknown 태그는 regex 수준에서 거름.** whitelist (6개) 가 regex 에
  박혀 있어 `[giddy]` 같은 비공인 태그는 애초에 매치되지 않음. 모델이
  만든 희한한 태그가 들어와도 데이터 경로 오염 없음.
- **Missing buffer 는 strip-only 모드.** provider 가 없거나 hydrate 실패
  로 `state.shared[MUTATION_BUFFER_KEY]` 가 비어 있으면, mutation 은
  안 쌓지만 태그는 **계속 제거**. 유저에게 raw `[joy:2]` 가 새는 것이
  가장 나쁜 UX 이므로 strip 은 무조건.
- **Secondary 델타는 tag 별.** `joy`/`calm` → `bond.affection +`,
  `anger`/`fear` → `bond.trust −`, `sadness`/`excitement` 는 mood 만.
  `plan/04 §4.2` 의 차등 규약 그대로.
- **Source 태그는 `emit:affect_tag/{tag}`.** 디버깅 시 어떤 감정이
  어떤 경로로 들어왔는지 로그에서 분별 가능.

### 2. `backend/service/emit/chain_install.py` (신규)

```python
def install_affect_tag_emitter(pipeline, *, max_tags_per_turn=3):
    stage = pipeline.get_stage(14)                   # EmitStage
    chain = stage.emitters                            # SlotChain
    if any(e.name == "affect_tag" for e in chain.items):
        return None                                   # idempotent
    emitter = AffectTagEmitter(max_tags_per_turn=...)
    chain.items.insert(0, emitter)                    # prepend
    return emitter
```

**왜 prepend.** chain 은 순서 있는 ordered 리스트. VTuberEmitter 는
`final_text` 를 읽어 감정 키워드 검사 / 표정 신호를 발행하므로, 태그가
아직 남아 있는 상태로 이 단계를 거치면 "[joy]" 문자열이 그대로 키워드
매칭에 끼어드는 문제가 생긴다. `affect_tag` 를 제일 앞에 두어 *텍스트
정제 + mutation 기록* 을 먼저 끝내고, 이후 emitter 들은 정제된 텍스트만
본다.

**Idempotent.** 이미 `affect_tag` 라는 name 의 emitter 가 있으면 추가
하지 않고 `None` 반환. 세션 매니저가 재진입해도 중복 설치 안 됨.

**get_stage / _stages 양쪽 지원.** 표준 path 는 `pipeline.get_stage(14)`.
일부 테스트용 파이프라인이 `get_stage` 없이 `_stages` dict 만 갖는
경우에도 동작하도록 폴백.

### 3. `backend/service/emit/__init__.py` (신규)

public API: `AffectTagEmitter` / `AFFECT_TAGS` / `AFFECT_TAG_RE` /
`MOOD_ALPHA` / `install_affect_tag_emitter`.

### 4. `backend/service/langgraph/agent_session_manager.py` (수정)

`create_agent_session` 의 `instantiate_pipeline` 직후, `state_provider`
가 설정돼 있을 때만 `install_affect_tag_emitter(prebuilt_pipeline)` 호출.
4 줄 guard.

```python
if self._state_provider is not None:
    from service.emit import install_affect_tag_emitter
    install_affect_tag_emitter(prebuilt_pipeline)
```

왜 state_provider 게이팅인가: provider 가 없으면 `final_text` rewrite
자체가 불필요한 부작용. 쉐도우 모드를 완전히 격리.

## 테스트 (신규 28)

### `backend/tests/service/emit/test_affect_tag_emitter.py` — 21

1. Regex: 6개 태그 모두 매치, strength 옵셔널, 대소문자 무시, 여백
   허용.
2. `joy:2` → mood.joy +0.30, bond.affection +1.0.
3. `anger:1` → mood.anger +0.15, bond.trust −0.3.
4. `calm` → affection +, `fear` → trust −.
5. strength 생략 시 1.0 로 폴백.
6. 태그 제거 + double-space 정리.
7. 태그 없는 평문 → not emitted, buffer 무변동.
8. 빈 `final_text` 안전 처리.
9. Buffer 부재 시 strip 은 계속, mutation 은 skip, 메타에
   `"reason": "no_mutation_buffer"` 기록.
10. per-turn cap: 4 매치 중 앞 2개만 mutation, 나머지 drop, strip 은
    전부 적용.
11. source 는 `emit:affect_tag/{tag}` 접두.
12. 잘못된 strength (`[joy:]`) 는 regex 에서 걸리지 않고 그대로 방치
    (strip 도 안 함). 이게 더 safe.
13. 미공인 태그 (`[giddy]`) 는 아예 매치 안 됨.
14. 생성자 `-1` cap 은 `ValueError`.
15. `name == "affect_tag"`.
16. `max_tags_per_turn=0` 은 strip 은 해도 mutation 0.
17. sadness/excitement 는 mood 만 (secondary bond 델타 없음).

### `backend/tests/service/emit/test_chain_install.py` — 7

1. Empty chain → 단일 emitter 로 prepend.
2. 기존 emitter 앞에 prepend (ordering 계약).
3. 이미 `affect_tag` 가 있으면 no-op + `None` 반환 (idempotent).
4. `get_stage(14)` 가 `None` → `None` 반환.
5. `stage.emitters` 속성 없음 → `None` 반환.
6. `get_stage` 없이 `_stages` dict 만 있는 폴백 경로.
7. `max_tags_per_turn` 인자 전달 확인.

## 테스트 결과

- `tests/service/emit/` — **28/28** (신규).
- `tests/service/game/` — **53/53** (PR-X3-6 동일).
- `tests/service/state/` — **151/151** (PR-X3-6 동일).
- `tests/service/langgraph/` — **127/127** (PR-X3-6 동일).
- 사이클 관련 전체 **528/528 pass** (500 기존 + 28 신규).

(사이클 무관 실패 4 건 — `environment/test_templates.py` × 3,
`utils/test_text_sanitizer.py` × 1 — 모두 `fastapi` / `numpy` missing
환경 문제로 PR-X3-7 와 무관.)

## 설계 결정

- **Executor fork vs post-build install.** 태그 기반 mutation 은 Geny
  고유 개념. executor 의 EmitStage registry 에 넣으면 executor 가
  CreatureState 를 알아야 해서 추상화가 깨진다. post-build install
  로 경계 유지 + 책임 분리.
- **Prepend.** 체인 순서 계약 (plan/04 §4.3). 뒤쪽 emitter 가 태그
  포함된 텍스트를 보지 않게.
- **Idempotent install.** 세션 생성 경로가 재호출될 때 중복 설치 방지.
  future-proof (reload / hot-swap 상황).
- **State-provider gate.** 쉐도우 모드 완전 격리. provider 없으면
  기존 세션의 출력이 우연히도 바뀌지 않음.
- **MOOD_ALPHA = 0.15 모듈 상수로.** 튜닝이 들어올 지점이라 상수화.
  Tests 도 이 상수를 import 해 비교하므로 한 곳만 바꾸면 기대치까지
  같이 움직임.
- **Strip 은 mutation 의 선결 조건과 독립.** buffer 가 없어도 strip 은
  수행. 이유: 유저에게 raw 태그 유출은 버그 시그널.

## 의도적 비움

- **Prompt-level 지시.** "감정이 선명할 때만 `[joy]` 태그를 덧붙여라"
  는 system prompt 쪽 변경. persona/builder 쪽 PR 에서.
- **VTuberEmitter 의 mood-aware 확장.** 본 PR 은 mood delta 만 기록.
  mood 기반 표정 선택은 PR-X3-9.
- **Affect-aware retrieval.** 감정 강도를 검색 가중치로 쓰는 건 X6.
- **Drop 이 발생할 때 state-event 발행.** 디버깅 가시성은 현재 `logger.debug`
  만. WS 경로 노출은 관찰성 PR 에서.

## 다음 PR

PR-X3-8 `feat/mood-rel-vitals-blocks-live` — X1 에서 no-op 로 심어뒀던
`MoodBlock` / `RelationshipBlock` / `VitalsBlock` 을 CreatureState 를
읽어 실제 PromptBlock 텍스트로 변환하는 실구현. 본 PR 의 emitter 가
쌓은 mood 값이 system prompt 에 실제로 반영되는 첫 지점.
