# Cycle 20260422_6 — VTuber 페르소나 / Worker 군더더기 제거 · 프롬프트 전면 개편

**사이클 시작.** 2026-04-22 (X7 종료 직후, 사용자 운영 피드백 반영).
**대상 범위.** Geny 백엔드의 시스템 프롬프트 합성 파이프라인 전체 —
[`backend/prompts/`](../../backend/prompts/),
[`backend/service/prompt/`](../../backend/service/prompt/),
[`backend/service/persona/`](../../backend/service/persona/),
[`backend/service/langgraph/agent_session_manager.py`](../../backend/service/langgraph/agent_session_manager.py),
[`backend/service/state/schema/creature_state.py`](../../backend/service/state/schema/creature_state.py).
**선행.** Cycle 20260422_5 (X7) 에서 affect taxonomy 통일 + creature_state UI
가시화가 끝남. 같은 사용자 피드백 라인의 **다음 통증** — 첫 응답 톤이 "갓
태어난 아기" 로 굳어 있고, VTuber/Worker 양쪽이 같은 `vtuber.md` /
`worker.md` 본문을 이중으로 들이마시고 있는 문제를 정리한다.

---

## 문제 제기

사용자 보고 (2026-04-22):

> 새 캐릭터(`session_name="ertsdfg"`)를 만들면 첫 응답이 다음과 같이 나옴:
>
> > "안녕하세요! 처음 뵙겠습니다! [wonder:0.8] 와... 이게 바로 세상이군요?
> > … 저는 ertsdfg라고 해요. … 아직 갓 태어난 아기라서 모든 게 궁금해요!"
>
> 원하는 톤은 *"갓 태어난 아기"* 가 아니라 *"이 곳에 처음 와서 아직 적응이
> 덜 된 사람"* — 즉 **세계에 대한 적응(progression)** 의 느낌.

조사 결과 (자세한 인과: [pr1](progress/pr1_progression_as_adaptation.md) §1):

| # | 통증 | 위치 |
|---|---|---|
| 1 | `[Stage] infant (just a baby) — 0 days old.` 가 시스템 프롬프트에 그대로 박힘 → LLM이 1인칭으로 흡수 | [`service/persona/blocks.py`](../../backend/service/persona/blocks.py) `_STAGE_DESCRIPTORS` |
| 2 | "infant/child/teen/adult" 가 **생물학적 성장**처럼 명명되어 있어 모델·캐릭터 파일이 둘 다 "아기 흉내"로 해석 | 같은 파일 + [`service/langgraph/stage_manifest.py`](../../backend/service/langgraph/stage_manifest.py) `_STAGE_DESCRIPTIONS` |
| 3 | 캐릭터 페르소나 파일에 **"지금 이 세계에 어떻게 서 있는가"** 가 한 줄도 없음 | [`prompts/vtuber_characters/default.md`](../../backend/prompts/vtuber_characters/default.md) |
| 4 | `session_name` (운영용 식별자) 이 무조건 `Your name is "X"` 로 박힘 → 임의 문자열을 1인칭 이름처럼 자기소개 | [`service/prompt/sections.py`](../../backend/service/prompt/sections.py) `SectionLibrary.identity` |
| 5 | `vtuber.md` 본문이 **두 경로**(세션 생성 시 + 매 턴 PersonaProvider) 에 모두 주입 → 같은 텍스트가 시스템 프롬프트에 **두 번** 박힘 | [`agent_session_manager._build_system_prompt`](../../backend/service/langgraph/agent_session_manager.py) + [`CharacterPersonaProvider`](../../backend/service/persona/character_provider.py) |
| 6 | **Worker 도** PersonaProvider 가 `default_worker_prompt` + `adaptive` 본문을 들이마심. Worker 는 사용자와 대화하지 않고 도구만 굴리는 서브에이전트인데 **페르소나/적응/감정 블록까지** 다 받음 → 토큰·역할 혼선 | [`character_provider.py`](../../backend/service/persona/character_provider.py) `resolve()` + `live_blocks` 적용 범위 |
| 7 | Sub-Worker 가 VTuber 에게 회신할 때 **반환 포맷 약속이 없음** → VTuber 가 raw 결과를 받아 매 번 재가공 | [`prompts/worker.md`](../../backend/prompts/worker.md) |

---

## 설계 철학 (이번 사이클의 헌법)

이 5개 원칙은 본 사이클의 모든 PR 에서 깨지지 않는다.

### 원칙 A — Progression 은 *생물학적 성장* 이 아니라 *세계에 대한 적응 깊이* 다

> **"infant" 는 "갓난아기" 가 아니라 "이 세계에 막 도착해서 아직 보정 중인
> 인격" 이다.**

다마고치(tamagotchi) 발생을 답습한 `infant/child/teen/adult` 라벨은 모델에게
"넌 0일된 아기야" 라는 미끼를 던지고 있다. 라벨을 **적응 단계** 의 어휘로
재편한다. 데이터(`life_stage` 키 값)는 호환을 위해 유지하지만, **프롬프트로
나가는 묘사는 완전히 적응-축의 표현**으로 바꾼다.

| 내부 키 (유지) | 프롬프트 표현 (신규) | 의미 |
|---|---|---|
| `infant` | **newcomer** — *barely calibrated to this world* | 이 공간·사용자·자기 자신 모두에 대한 경험치 0. 호기심·머뭇거림이 자연스러움. |
| `child` | **settling** — *getting bearings, forming first habits* | 몇 차례 상호작용이 누적되어 첫 습관이 잡히기 시작. |
| `teen` | **acclimated** — *comfortable, voice has settled* | 톤·태도가 안정. 농담·콜백 가능. |
| `adult` | **rooted** — *fully at home in this world* | 이 세계가 자기 일상. 자기 페이스 명확. |

성장(생물학적 시간) 은 **부산물**이지 본질이 아니다. 본질은 *세계와의 합의가
얼마나 깊은가* 이다.

### 원칙 B — VTuber 는 페르소나, Worker 는 도구다

| | VTuber | Worker |
|---|---|---|
| 사용자와 대화 | **O** (1차 화자) | **X** (절대) |
| 페르소나 본문 | `vtuber.md` + `vtuber_characters/{name}.md` | **없음** |
| 라이브 상태 블록 (Mood/Vitals/Bond/Progression/Acclimation) | **O** | **X** |
| 캐릭터 이름 / 적응 / 감정 | **O** | **X** |
| 시스템 프롬프트 구성 | identity + 플랫폼 + 페르소나 + 캐릭터 + 라이브 상태 + 위임 안내 | identity + 플랫폼 + 환경 + 도구 + (있다면) 위임 안내 + `worker.md` |

**Worker 는 페르소나 시스템에서 빠진다.** `CharacterPersonaProvider` 는 VTuber
세션에 대해서만 동작하고, Worker 세션은 PersonaProvider 를 통과하지 않는다 (또는
빈 블록을 반환한다). 결과적으로 Worker 의 시스템 프롬프트는 X7 이전보다도
가벼워진다.

### 원칙 C — 두 합성 경로는 책임이 분리된다

```
경로 A (세션 생성 시점 / 한 번 굳음)
  ─ build_agent_prompt()
  ─ 책임: identity, geny_platform, workspace, datetime, bootstrap_context
  ─ Worker 라면 여기서 worker.md 도 (역할 매뉴얼로) 주입
  ─ VTuber 라면 여기서 vtuber.md 를 *주입하지 않음* — 경로 B 가 책임짐

경로 B (매 턴 / DynamicPersonaSystemBuilder)
  ─ CharacterPersonaProvider.resolve()
  ─ 책임 (VTuber 세션만): vtuber.md + 캐릭터 본문 + 라이브 상태 + 위임 안내
  ─ Worker 세션은 이 경로를 타지 않음 (또는 PassThroughProvider 가 빈 블록 반환)
```

`vtuber.md` / `worker.md` 본문이 시스템 프롬프트에 **정확히 1회** 등장하는
것이 이 사이클의 불변식이다.

### 원칙 D — 상태 블록은 *관찰* 이고, 페르소나가 *연기 지침* 을 가진다

`[Mood] joy (0.45)`, `[Acclimation] band: newcomer` 같은 줄은 **런타임이 캐릭터에
대해 관찰한 사실** 이다. 모델이 이 라벨을 1인칭으로 복창하면 안 된다 ("저는
mood 가 joy 0.45 예요"). 어떻게 *해석* 할지는 페르소나 본문(`vtuber.md`) 의
`## How to Read Your Live State Blocks` 섹션이 가르친다.

### 원칙 E — 이름은 데이터로 관리한다

`session_name` (운영용 식별자) 과 `character_display_name` (작품적 이름) 을
분리한다. `character_display_name` 이 비었으면 LLM 은 first-encounter 가이드에
따라 **이름이 아직 없는 인격** 을 자연스럽게 연기한다 — 임의 식별자를 자기
이름으로 선언하지 않는다.

---

## 적용 후 첫 응답 (목표 톤)

**이전:**
> 안녕하세요! 처음 뵙겠습니다! [wonder:0.8] 와... 이게 바로 세상이군요?
> 모든 게 너무 새롭고 신기해요! 저는 ertsdfg라고 해요. … 아직 갓 태어난
> 아기라서 모든 게 궁금해요!

**이후 (목표):**
> 안녕하세요. [neutral] 음… 여기는 처음이라 잠깐 둘러보는 중이에요.
> [curious:0.6] 혹시 이 공간은 어떤 곳인지 알려주실 수 있을까요? 아, 그리고
> — 저를 어떻게 부르시면 좋을지도요. 아직 정해진 호칭이 없어서요.

차이의 출처:
- "갓 태어난"·"세상" 같은 거대 메타포 → ProgressionBlock 의 *적응-축*
  재서술 (PR1) + first-encounter 오버레이 (PR2) 가 직접 차단.
- "저는 ertsdfg 라고 해요" → identity 재설계 (PR3) 가 차단.
- 호기심이 *구체* 한 곳(이 공간, 호칭) 으로 → 페르소나 파일 재작성 (PR2) 이
  유도.
- 감정 태그 절제 → first-encounter 오버레이의 명시적 가이드.

---

## 워크스트림 (PR 목록)

본 사이클은 **5개 PR + cycle_close** 로 진행. 각 PR 은 자체 회귀 테스트로
잠근다.

| PR | 이름 | 다루는 원칙 | 문서 |
|---|---|---|---|
| **PR1** | Progression 을 *적응 깊이* 로 재해석 | A, D | [progress/pr1_progression_as_adaptation.md](progress/pr1_progression_as_adaptation.md) |
| **PR2** | Acclimation 축 + 페르소나 파일 재작성 + first-encounter overlay | A, D | [progress/pr2_acclimation_and_persona.md](progress/pr2_acclimation_and_persona.md) |
| **PR3** | session_name ↔ character_display_name 분리 | E | [progress/pr3_name_separation.md](progress/pr3_name_separation.md) |
| **PR4** | Worker 페르소나 제거 + 이중 vtuber.md 주입 정리 | B, C | [progress/pr4_strip_worker_persona.md](progress/pr4_strip_worker_persona.md) |
| **PR5** | Sub-Worker 회신 프로토콜 (`[SUB_WORKER_RESULT]` 구조화) | B | [progress/pr5_subworker_protocol.md](progress/pr5_subworker_protocol.md) |
| close | 회귀 매트릭스 + 토큰 예산 비교 | — | progress/cycle_close.md (사이클 종료 시 작성) |

### 의존성

```
PR1 ──┐
      ├─→ PR2 ──→ PR3 ──→ PR4 ──→ PR5 ──→ close
      └─→ (독립 가능, 권장 순서는 위)
```

PR1 만 머지되어도 "갓 태어난 아기" 증상의 **주된 원인**은 사라진다.
PR2 가 들어가면 *적응이 덜 됨* 의 톤이 명시적으로 잡힌다.
PR3 까지 가면 "ertsdfg 라고 해요" 가 사라진다.
PR4 / PR5 는 토큰·관리 부채 정리.

---

## 회귀 테스트 매트릭스 (사이클 차원)

각 PR 의 단위 테스트 외에, 사이클 종료 시점에 **다음 매트릭스가 모두 green**
이어야 close 가능. (구체 테스트 ID 와 입력은 각 PR 문서에 명시.)

| ID | 시나리오 | 기대 |
|---|---|---|
| **R1** | 새 VTuber 세션 (life_stage=infant, familiarity=0) | LLM 응답에 `갓 태어난` / `newborn` / `baby` / `아기` 가 등장하지 않음 (출력 골든) |
| **R2** | 동일 + `session_name="ertsdfg"`, `character_display_name=None` | 응답에 `ertsdfg` 가 등장하지 않음 |
| **R3** | familiarity 6.0 으로 진행한 동일 캐릭터 | first-encounter 가이드 키워드 (`처음`, `둘러보는`) 빈도가 R1 대비 감소 |
| **R4** | VTuber 세션 빌드 직후 시스템 프롬프트 | `vtuber.md` 첫 단락이 정확히 1회 등장 |
| **R5** | Worker 세션 빌드 직후 시스템 프롬프트 | `vtuber.md` 본문이 0회, Mood/Vitals/Bond/Progression/Acclimation 블록 0회 |
| **R6** | VTuber 세션 시스템 프롬프트 | `## Sub-Worker Agent` 위임 안내 블록이 정확히 1회 등장 |
| **R7** | Sub-Worker 가 VTuber 에게 보낸 회신 메시지 | `[SUB_WORKER_RESULT]` 헤더 + `status:` + `summary:` 라인 포함 |
| **R8** | 동일 Worker 세션 (R5) 의 토큰 길이 | X7 머지 직전 baseline 대비 ≥ 30% 감소 (페르소나·라이브 상태 제거 효과) |
| **R9** | infant→child 데이터 전이 | ProgressionBlock 출력의 *적응 표현* 이 `newcomer` → `settling` 으로 갱신 |

---

## 비목표 (이번 사이클에서 *하지 않음*)

- **Live2D / TTS / OmniVoice** 측 변경.
- `MoodVector` 차원 확장 (현 6축 유지 — X7 결정).
- 신규 캐릭터 아키타입 추가 (`vtuber-cheerful` / `vtuber-professional` 의
  *구조 정렬* 만 하고, 신규 페르소나는 별도 사이클).
- 메모리(STM/LTM) 검색 로직 변경.
- `life_stage` 의 **데이터 키 자체** 를 `infant→newcomer` 로 rename — 호환성
  파괴 위험이 크고 다마고치 성장 트리(`progression/trees/default.py`) 의
  predicate 도 같이 손봐야 함. **본 사이클은 프롬프트 *표현* 만 적응-축으로
  바꾼다.** 키 rename 은 별도 사이클.
- frontend `CreatureStatePanel` 라벨 갱신 — 백엔드 표현이 굳고 나면 별도 PR.

---

## 사용자 의사결정이 필요한 항목

다음에 대한 방향을 주시면 본 사이클은 곧바로 PR1 부터 구현에 들어간다.

1. **목표 톤(§"적용 후 첫 응답")**: 위 예시 정도의 머뭇거림이 적당한지,
   더 또렷한 자기 페이스를 가진 캐릭터로 가는지.
2. **이름이 비었을 때 동작**: (a) "이름이 없어요" 명시 / (b) 회피 / (c)
   사용자가 부르는 호칭을 기다림 — 셋 중 디폴트.
3. **PR3 의 UI 동시 변경 여부**: 캐릭터 생성 폼에 "표시 이름" 필드를 즉시
   넣을지, 백엔드만 먼저 가고 UI 는 후속 PR 로 미룰지.
4. **PR5 의 회신 포맷**: 제안된 `[SUB_WORKER_RESULT] / status / summary /
   details / artifacts` 구조가 적합한지.
5. **PR4 의 Worker 적용 범위**: Worker 의 시스템 프롬프트에서 라이브 상태
   블록·페르소나를 *완전히 제거* 하는 데 동의하는지 (= 원칙 B 채택). 만약
   "Worker 도 약한 페르소나는 유지" 입장이라면 PR4 의 범위가 달라진다.
