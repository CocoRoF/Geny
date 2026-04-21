# Plan 04 — 다마고치 상호작용 레이어링 (X3 이후)

**작성일.** 2026-04-21
**선행.** `plan/01` (전략 D), `plan/02` (CreatureState 계약), `plan/03` (구조적 보완).
**가정.** X1 (PersonaProvider), X2 (SessionLifecycleBus + TickEngine), X3 (CreatureState 본체)
가 이미 운영 중.
**본 문서의 책임.** 다마고치/VTuber 관계 시뮬레이션의 **모든 게임 요소가** 16-STAGE 와
`plan/01-03` 의 구조 위에 **정확히 어떤 형태로** 올라가는지 기술. 스펙 수준.

---

## 0. 게임 요소 ↔ 구조 매핑 총괄표

유저가 제시한 게임 디자인의 모든 요소를 stage / slot / provider / tick / block 단위로 본
문서가 확정.

| 게임 요소 | 물리적 위치 | 이 문서 §      | 사이클 |
|---|---|---|---|
| Persona (캐릭터 본체) | PersonaProvider + PersonaBlock                    | §1  | X1 |
| Mood (오늘의 기분)         | MoodBlock (PromptBlock) + state.shared['creature_state'].mood | §2  | X3 |
| Bond (애정/신뢰/친숙/의존) | RelationshipBlock + CreatureState.bond           | §2  | X3 |
| Vitals (배고픔/피로/...)   | VitalsBlock (옵션) + CreatureState.vitals       | §2  | X3 |
| 기본 인터랙션 (feed/play/gift/talk) | s10_tool 의 4개 Tool                      | §3  | X3 |
| 확장 인터랙션 (계절 이벤트 등) | s10_tool 추가 + EventSeed PromptBlock         | §6  | X4 |
| 감정 피드백 (LLM 태그 → state) | s14_emit 의 새 Emitter `AffectTagEmitter`    | §4  | X3 |
| 방치 페널티 (soft)          | TickEngine decay + Bus session.abandoned 로깅   | §5  | X3 |
| 생애 단계 전환 (infant → teen → ...) | ManifestSelector (wrapper)             | §7  | X4 |
| 특별 이벤트 (생일/첫만남)   | state.shared['ephemera'] 주입 + EventSeedBlock | §6  | X4 |
| 기억 가중 (감정 중요도)     | AffectAwareRetrieverMixin (s02 retriever)      | §8  | X6 |
| 표정 / Live2D              | VTuberEmitter + avatar_state_manager (tick)     | §9  | 이미 있음 |
| 재접속 보상                 | Bus `session.resumed` 핸들러 + mutation         | §5  | X3 |

---

## 1. Persona — 캐릭터 본체의 모양

### 1.1. 원천 데이터

`backend/repo/character.py` (기존) 에 이미 `Character` 모델이 있음 (이름, 설명, persona_prompt).
여기에 **게임 전용 메타데이터** 추가:

```python
@dataclass
class Character:
    id: str
    name: str
    species: str                 # 신규: "catgirl" / "dog" / "dragon" 등
    persona_prompt: str          # 기본 성격 prompt (이미 있음)
    default_manifest_id: str     # 신규: "infant_cheerful" 등
    voice_profile_id: Optional[str]
    live2d_model_id: Optional[str]
    growth_tree_id: str          # 신규: ManifestSelector 참조 (§7)
```

### 1.2. CharacterPersonaProvider (X1 완성형)

`plan/03 §2.5` 에서 정의한 Provider 의 *X3 완성형*:

```python
class CharacterPersonaProvider(PersonaProvider):
    async def resolve(self, state, *, session_meta):
        char = await self._repo.get(session_meta['character_id'])
        creature = state.shared.get('creature_state')

        blocks = [
            PersonaBlock(char.persona_prompt),                    # 고정
            DateTimeBlock(),                                       # 항상
        ]
        if creature:
            blocks.append(VitalsBlock.from_vitals(creature.vitals))        # §2.1
            blocks.append(MoodBlock.from_mood(creature.mood))              # §2.2
            blocks.append(RelationshipBlock.from_bond(creature.bond))      # §2.3
            blocks.append(ProgressionBlock.from_progression(creature.progression))  # §7.5
        return PersonaResolution(persona_blocks=blocks, cache_key=...)
```

**핵심.** `CreatureState` 없으면 (게임 기능 off) 기본 PersonaBlock 만. feature-flag 없이
자동 퇴화.

---

## 2. MoodBlock / RelationshipBlock / VitalsBlock — 감정과 관계를 prompt 에 반영

### 2.1. VitalsBlock

```python
class VitalsBlock(PromptBlock):
    @classmethod
    def from_vitals(cls, v: Vitals) -> "VitalsBlock":
        lines = []
        if v.hunger > 70:    lines.append("지금 많이 배고픈 상태이다.")
        if v.hunger > 90:    lines.append("기력이 떨어지고 짜증이 난다.")
        if v.energy < 30:    lines.append("피곤해서 대답이 느려진다.")
        if v.stress > 70:    lines.append("스트레스가 높아 말수가 줄어든다.")
        if v.cleanliness < 40: lines.append("스스로 지저분한 것을 신경 쓴다.")
        return cls(text="\n".join(lines) if lines else "")
```

**Prompt 에 반영되는 방식.** 조건 없으면 빈 블록 → 실제 system prompt 에 문장 0개. 비용 낭비 없음.
조건 맞으면 **한 줄짜리 지시문** 만 추가. LLM 의 자유도를 과하게 제한하지 않음.

### 2.2. MoodBlock

```python
class MoodBlock(PromptBlock):
    @classmethod
    def from_mood(cls, m: MoodVector) -> "MoodBlock":
        dom = m.dominant()   # "joy" / "sadness" / ...
        if m.norm() < 0.25:  return cls(text="지금 평상심 상태이다.")
        hint = {
            "joy":       "지금 기분이 좋고 에너지가 높다.",
            "sadness":   "약간 처진 기분이다. 말수가 줄어든다.",
            "anger":     "불쾌한 기분이 올라와 있다. 날카로운 반응이 나올 수 있다.",
            "fear":      "긴장되어 있다.",
            "calm":      "차분하고 안정된 상태이다.",
            "excitement":"들떠 있어 속도가 빠르다.",
        }[dom]
        return cls(text=hint)
```

### 2.3. RelationshipBlock

```python
class RelationshipBlock(PromptBlock):
    @classmethod
    def from_bond(cls, b: Bond) -> "RelationshipBlock":
        lines = []
        # 친숙도
        if   b.familiarity <  10: lines.append("상대를 아직 어색해한다. 존댓말로 답한다.")
        elif b.familiarity <  50: lines.append("상대와 꽤 친숙하다.")
        else:                     lines.append("상대를 매우 편안하게 느낀다. 말이 부드럽다.")
        # 애정
        if b.affection >  60:     lines.append("상대에게 강한 애정을 느낀다.")
        if b.affection >  90:     lines.append("상대를 각별하게 여긴다. 이따금 그 감정을 드러낸다.")
        # 의존
        if b.dependency > 60:     lines.append("상대가 오래 자리를 비우면 불안해한다.")
        return cls(text="\n".join(lines))
```

### 2.4. 캐시 키 전략

`PersonaResolution.cache_key` 는 다음과 같이:

```
f"{character_id}|{life_stage}|{mood.bucket()}|{vitals.bucket()}|{bond.bucket()}"
```

각 필드를 *이산 구간 (bucket)* 으로 변환 (e.g., hunger 0..30 → "ok", 30..70 → "hungry",
70..100 → "starving"). 이로써 prompt 캐시 hit 률이 합리적 수준으로 유지됨. 연속값을 그대로
키에 넣으면 매 턴 miss.

### 2.5. Why PromptBlock 으로 분리하는가 (하나로 합치지 않는 이유)

- **단일 책임.** Mood 변화와 Bond 변화의 *빈도가 다름*. 분리해야 각자 자연스러운 템플릿 진화.
- **선택적 끄기.** MVP 에서 VitalsBlock 을 쓰지 않기로 했다면 PersonaProvider 에서 빼면 됨.
  한 블록 안에 섞으면 불가능.
- **측정 가능성.** 블록별 prompt 길이 분포를 측정 가능 → 어떤 블록이 비용을 잡아먹는지 투명.

---

## 3. s10_tool — 인터랙션 도구 (feed / play / gift / talk)

### 3.1. 기본 4 tool

```python
# backend/service/game/tools/feed.py
class FeedTool(Tool):
    name = "feed"
    description = "상대에게 음식을 준다. 종류를 지정할 수 있다."

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        kind = args.get('kind', 'snack')
        buf: MutationBuffer = ctx.state.shared['creature_state_mut']

        # 규칙 테이블 (후술 §3.4)
        rule = FEED_RULES.get(kind, FEED_RULES['snack'])
        buf.append(op="add",    path="vitals.hunger",       value=rule.hunger_delta,    source="tool:feed")
        buf.append(op="add",    path="bond.affection",      value=rule.affection_delta, source="tool:feed")
        buf.append(op="append", path="recent_events",       value=f"fed:{kind}",        source="tool:feed")

        # 분위기 힌트 (LLM 이 '맛있다' 등의 반응을 할 수 있게)
        return ToolResult.text(f"FEED_OK kind={kind} pleasure={rule.pleasure}")
```

`PlayTool`, `GiftTool`, `TalkTool` 도 유사 구조. `TalkTool` 은 *특수 케이스* — LLM 의 자연어
대화가 기본 경로이므로, Tool 로서의 Talk 는 "대화 시작/종료 이벤트 마킹" 또는 "주제 전환"
같은 메타 액션에 한정.

### 3.2. Tool 호출의 상태 영향 원칙

- Tool 은 *즉각적이고 결정적인* 영향만 건다. "maybe affection +5" 같은 확률적 영향은 금지
  (테스트 불가능, 유저 혼란).
- 확률적 요소 (특별한 음식이 기분을 유난히 좋게 만드는 등) 는 **Emitter 에서 LLM 출력 기반**
  으로 처리 (§4 참조).

### 3.3. ToolContext 가 mutation buffer 를 보이는 방법

```python
# 현재 ToolContext 는 {state, session_id, ...} 등을 carry.
# mutation buffer 접근은 state.shared 경유가 원칙이지만, 편의를 위한 property 추가:
class ToolContext:
    @property
    def mut(self) -> MutationBuffer:
        return self.state.shared['creature_state_mut']
```

### 3.4. Feed 규칙 테이블 예시

```python
@dataclass(frozen=True)
class FeedRule:
    hunger_delta: float      # < 0 (포만 방향)
    affection_delta: float   # > 0
    pleasure: Literal["low", "medium", "high"]

FEED_RULES = {
    "snack":     FeedRule(-10.0, 0.5,  "low"),
    "meal":      FeedRule(-40.0, 1.5,  "medium"),
    "favorite":  FeedRule(-30.0, 4.0,  "high"),   # 캐릭터별 재정의 가능
    "medicine":  FeedRule(  0.0, 0.0,  "low"),    # hunger 불변, stress 별도 처리
}
```

**캐릭터별 오버라이드.** `Character` 모델에 `favorite_food: str`, `disliked_foods: list[str]`
필드 추가. Tool 실행 시 캐릭터 취향 확인 후 규칙 보정.

### 3.5. Tool 의 안전성

- Tool 이 같은 `path` 에 연속 append 해도 순서만 보존되면 정합.
- Tool 이 동시 두 번 호출 — s10_tool 은 직렬 실행이므로 경합 없음.
- 악성 args 방어 — 숫자 파라미터 범위 검증 필수.

---

## 4. s14_emit — 감정 피드백 (LLM 출력 → state)

### 4.1. 기존 구조

`analysis/01` 에서 확인된 바, s14_emit 은 Emitter **체인** 구조 (SlotChain).
현재 Geny 는 `VTuberEmitter` (키워드 기반) 와 `emotion_extractor` (LLM 괄호 태그 기반) 가
*섞여 있음*. 분석 02 에서 지적.

### 4.2. 새 Emitter — `AffectTagEmitter`

```python
# backend/service/emit/affect_tag_emitter.py

AFFECT_TAG_RE = re.compile(r"\[(joy|sadness|anger|fear|calm|excitement)\s*(?::(-?[\d\.]+))?\]")

class AffectTagEmitter(Emitter):
    """LLM 출력에서 [감정:강도] 태그를 추출, CreatureState 에 mutation 추가."""

    async def emit(self, state: PipelineState) -> None:
        text = state.final_text or ""
        matches = AFFECT_TAG_RE.findall(text)
        if not matches: return

        buf: MutationBuffer = state.shared.get('creature_state_mut')
        if buf is None: return

        for tag, strength in matches:
            s = float(strength) if strength else 1.0
            # Mood EMA 업데이트 (즉시 적용 아닌 diff 로 제출)
            buf.append(op="add", path=f"mood.{tag}", value=s * MOOD_ALPHA, source="emit:affect_tag")
            # joy/calm → affection 미세 상승
            if tag in ("joy", "calm"):
                buf.append(op="add", path="bond.affection", value=s * 0.5, source="emit:affect_tag")
            # anger/fear → trust 미세 하락
            if tag in ("anger", "fear"):
                buf.append(op="add", path="bond.trust", value=-s * 0.3, source="emit:affect_tag")

        # 태그는 최종 유저 출력에서 제거
        state.final_text = AFFECT_TAG_RE.sub("", text).strip()
```

### 4.3. VTuberEmitter (표정) 와의 협조

- `AffectTagEmitter` 는 **감정 tag → state mutation**.
- `VTuberEmitter` 는 **감정 상태 → 표정 커맨드** (기존 로직).
- 둘을 체인으로 순서 조정:
  ```
  emitters = [AffectTagEmitter(), VTuberEmitter()]
  ```
  AffectTagEmitter 가 `final_text` 를 정리하고 mutation 을 남긴 후, VTuberEmitter 가
  *정제된 텍스트* 와 (state.shared['creature_state'] 를 참고하여) 표정 신호 발생.

### 4.4. 태그가 없는 모델 / 프롬프트 호환성

- 모델이 태그를 안 찍으면 mutation 0건. 정상 동작.
- SystemBuilder 에 "감정이 선명할 때만 [joy] 같은 태그를 덧붙여라" 류 지시를 추가. 강요하지
  않음 (필수화하면 LLM 품질 저하).

### 4.5. LLM 이 태그를 **지어내서** mood 를 과하게 올리는 문제

- Emitter 에서 단일 태그 per-turn 상한: `max_tag_mutations_per_turn = 3`.
- 과다 시 첫 3개만 적용, 나머지는 log + 무시.

---

## 5. 방치 페널티 & 재접속 보상

### 5.1. 방치 페널티의 *다층* 구조

**원칙.** penalty 는 **decay 자체** 가 주는 것이지, 별도의 "punishment event" 를 쏘지 않는다.
유저 경험에서 "오래 안 봤더니 배고파하고 우울해함" 은 이미 충분한 시그널.

- `TickEngine` 의 `decay` spec 이 15 분마다 돌면서 vitals 감소.
- Bond 는 decay 하지 않지만 `familiarity` 만 아주 천천히 감소 (-0.1/h). `affection` 은 유지.

### 5.2. `session.abandoned` 훅

Bus 의 `session.abandoned` 이벤트 수신 시 CreatureStateProvider 에 단일 mutation:

```python
# backend/service/game/lifecycle_handlers.py
async def on_abandoned(evt):
    await csp.set_absolute(evt['character_id'], patch={
        'recent_events_push': f"abandoned_at:{evt['at']}",
    })
```

여기서 `set_absolute` 는 *턴 밖* 변경 (즉 mutation 이 아니라 직접 적용). 의존성 / 상처 정도는
decay 가 담당.

### 5.3. 재접속 보상

`session.resumed` 수신 시 `hydrate` 가 이미 catch-up tick 을 돌린 후. 다음 턴의 PersonaProvider
는 자동으로 "오랜만에 왔다" 상태를 읽고 prompt 에 반영. 즉 **별도 보상 로직 없이 자연 발생**.

단, 콘텐츠 면에서 "오랜만이네요" 같은 특수 대사가 원한다면 `EventSeedBlock` 을 사용 (§6).

### 5.4. "떠난 시간" 기반 단계 보정

`last_interaction_at` 으로부터 경과 시간을 판정해 `recent_events` 에 태그 push:

| 경과 | 태그 |
|---|---|
| < 1 시간 | (없음) |
| 1~6 시간 | short_away |
| 6~24 시간 | half_day_away |
| 1~3 일 | multi_day_away |
| > 3 일 | long_away |

`recent_events` 는 ring buffer (최근 20개). PersonaProvider 의 MoodBlock 가 이 태그를
참고해 "걱정했다", "오랜만이네요" 같은 지시를 얹음.

---

## 6. EventSeed — 예측 불가능성 / 특별 이벤트

### 6.1. 왜 필요한가

기획의 "예측 불가능성" 은 *매 턴 다른 무엇* 이 생기는 것. 단순 RNG 는 LLM 품질을 해친다.
대신 **EventSeedBlock** 이라는 작은 prompt hint 를 랜덤 또는 상태 조건으로 주입.

### 6.2. 구조

```python
@dataclass(frozen=True)
class EventSeed:
    id: str
    trigger: Callable[[CreatureState, SessionMeta], bool]
    hint_text: str        # 예: "오늘은 비가 내린다. 그 사실을 대화에 자연스럽게 녹일 수 있다."
    weight: float = 1.0

class EventSeedPool:
    def __init__(self, seeds: list[EventSeed]): self._pool = seeds
    def pick(self, cs: CreatureState, meta, rng) -> Optional[EventSeed]: ...
```

### 6.3. 예시 시드

- `seed_birthday`: `progression.age_days == 다른 배수 (N*365)` → "오늘 내 생일이다".
- `seed_rainy_day`: 외부 날씨 API 가 비 오는 지역 → 즉흥 대사.
- `seed_first_talk_after_7d`: `multi_day_away` 태그 존재 → "오랜만이야" 계열 hint.
- `seed_milestone_hit`: `progression.milestones` 에 새 항목 → 축하 상태.

### 6.4. PersonaProvider 에의 통합

`EventSeedBlock` 을 PersonaResolution 의 blocks 목록 *끝* 에 선택적으로 1개 삽입.
pick() 은 결정적이지 않으므로 cache_key 에 포함.

---

## 7. 생애 단계 전환 — ManifestSelector

### 7.1. 개념

"성장 = Manifest 교체" 로 본다. infant manifest 는 쉬운 말투, 짧은 답. teen manifest 는
풍부한 표현, 길어진 응답. 단지 system prompt 만 바뀌는 것이 아니라:

- Tool 구성 (infant 는 feed/play 만, teen 은 확장 도구 포함)
- 감정 반응 임계 (infant 가 더 자주 운다)
- Retriever 전략 (teen 이 더 장기 기억 참조)

는 모두 manifest 에 선언되어 있으므로, **Manifest 를 통째로 교체** 하는 것이 깔끔.

### 7.2. Manifest ID 체계

```
infant_cheerful           # 기본 어릴 때
child_curious
teen_introvert
teen_extrovert
adult_artisan
...
```

Character 의 `growth_tree_id` 가 "어떤 나무를 따라 성장할지" 지시. 각 나무는 stage 전이 그래프.

### 7.3. 전환 조건

```python
@dataclass
class Transition:
    from_stage: str
    to_stage: str
    predicate: Callable[[CreatureState], bool]

DEFAULT_TREE = [
    Transition("infant", "child",
               lambda s: s.progression.age_days >= 3 and s.bond.familiarity >= 20),
    Transition("child", "teen",
               lambda s: s.progression.age_days >= 14 and s.bond.affection >= 40),
    Transition("teen", "adult",
               lambda s: s.progression.age_days >= 40 and 'first_conflict_resolved' in s.progression.milestones),
]
```

### 7.4. `ManifestSelector` — pipeline 바깥 교체

```python
class ManifestSelector:
    async def select(self, cs: CreatureState, char: Character) -> str:
        tree = self._trees[char.growth_tree_id]
        current = cs.progression.life_stage
        for t in tree:
            if t.from_stage == current and t.predicate(cs):
                return f"{t.to_stage}_{char.species}_{char.personality_archetype}"
        return cs.progression.manifest_id
```

`AgentSession._build_pipeline` 가 매 세션 시작 시:

```python
new_id = await selector.select(cs, char)
if new_id != cs.progression.manifest_id:
    # 1) mutation 남김
    buf.append(op="set", path="progression.manifest_id", value=new_id, source="selector:transition")
    buf.append(op="set", path="progression.life_stage",  value=parse_stage(new_id), source="selector:transition")
    buf.append(op="append", path="progression.milestones", value=f"enter:{new_id}", source="selector:transition")
    # 2) pipeline 재구성
    manifest = load_manifest(new_id)
    pipeline = await Pipeline.from_manifest_async(manifest, ...)
```

### 7.5. ProgressionBlock

```python
class ProgressionBlock(PromptBlock):
    @classmethod
    def from_progression(cls, p: Progression) -> "ProgressionBlock":
        age = p.age_days
        stage_desc = {"infant": "아직 어린", "child": "호기심이 많은",
                      "teen": "감정 기복이 있는", "adult": "성숙한"}[p.life_stage]
        return cls(text=f"{stage_desc} 단계 ({age}일째). 이 단계의 말투와 감정 표현을 유지한다.")
```

### 7.6. 비가역성

기본적으로 *단조 전진*. 후퇴 (adult → child) 는 금지. 특수 운영 명령 (`set_absolute`) 으로만
가능.

---

## 8. 기억 가중 — AffectAwareRetrieverMixin

### 8.1. 현재 Retriever 구조

`s02_context` 의 retriever slot 이 messages + memory 을 섞어서 `current_messages` 를 구성.
점수식은 현재 importance / recency / similarity.

### 8.2. 새 차원 — affect 가중

```python
class AffectAwareRetrieverMixin:
    def score(self, mem_item, state) -> float:
        base = super().score(mem_item, state)
        cs = state.shared.get('creature_state')
        if not cs: return base

        # mood 와 부합하는 기억을 더 높이 평가 (예: 슬플 땐 슬픈 기억을 더 기억)
        mood_bias = self._mood_similarity(mem_item.emotion_vec, cs.mood)
        # 감정 강도 높은 기억은 항상 가중
        intensity_bias = mem_item.emotion_intensity
        # 관계 강도 높은 상대의 말을 더 기억
        bond_bias = ...  # owner 라면 +, 다른 캐릭터는 -

        return base + 0.3 * mood_bias + 0.2 * intensity_bias + 0.1 * bond_bias
```

mem_item 에 `emotion_vec`, `emotion_intensity` 필드가 이미 있어야 함 — 기존 memory schema 에
없다면 X6 에서 옵션 필드로 추가.

### 8.3. 왜 X6 인가

- 기본 retrieval 이 안정화된 후 도입.
- memory schema 변경을 동반하므로 migration 필요.
- affect 가중은 *미세 튜닝* 영역이어서 MVP 외.

---

## 9. 표정 / Live2D

### 9.1. 기존 상태

- `avatar_state_manager` 가 tick 기반 동작.
- `VTuberEmitter` 가 턴마다 표정 커맨드 발행.

### 9.2. 변경 범위

- `avatar_state_manager` 는 TickEngine 경로로 이식 (X2 에서 처리 예정).
- `VTuberEmitter` 는 `state.shared['creature_state'].mood` 를 읽어 표정 선택 (현재는 키워드
  기반) — **X3 의 X3-5 PR** 로 mood-based 표정 전환.

### 9.3. 변경하지 않는 것

- Live2D 애셋 파이프라인.
- TTS 보이스.
- 프론트 WebGL 렌더링.

---

## 10. MVP 정의 — X3 완료 시점의 "최소 플레이 가능" 상태

### 10.1. 포함

- 1 character (테스트용 단일 인스턴스).
- CreatureState 전체 필드.
- feed / play / gift / talk 4 tool.
- AffectTagEmitter + VTuberEmitter(mood 반영).
- MoodBlock / RelationshipBlock / VitalsBlock 세 prompt block.
- decay (TickEngine) + hydrate catch-up.
- session.resumed 시 "오랜만이네" 자연 발생.

### 10.2. 제외 (X4+)

- Manifest 전환 (infant → child).
- EventSeed pool.
- AffectAware retrieval.
- 다중 캐릭터 간 관계.
- 경제 / 재화.
- UI 대시보드 (상태 시각화).

### 10.3. 경계 테스트 시나리오

- **시나리오 S1: 첫 만남.** 새 character 생성 → 첫 턴 → bond.familiarity 증가 → greeting 자연.
- **시나리오 S2: 포만 → 굶주림.** 8시간 tick 시뮬레이션 → hunger > 80 → 대화 톤이 짜증으로
  이동.
- **시나리오 S3: 재접속.** 24h 방치 후 접속 → multi_day_away 태그 → MoodBlock 에 반영 →
  "걱정했어요" 뉘앙스 자연 발생.
- **시나리오 S4: 감정 태그 자동 학습.** LLM 이 [joy] 태그를 종종 쓰면 → affection 이 누적 상승.

---

## 11. 관찰성 / 밸런스 튜닝

### 11.1. 게임 이벤트 로그

모든 mutation 이 (opt-in 으로) event 로그에 기록됨. 밸런스 튜닝용 대시보드:
- 평균 세션 당 mutation 수.
- path 별 누적 delta (affection 이 너무 빨리 오르진 않는지).
- life_stage 진행 분포.

### 11.2. Shadow mode

첫 롤아웃 시, mutation 을 **apply 하지 않고 로그만** 남기는 shadow flag 를 `CreatureStateProvider`
에 둠. 규칙 튜닝 완료 후 flag off.

---

## 12. 의존 관계 & 선후

```
X1 (Persona) ─┐
              ├── X3 (CreatureState + Tools + Emitters + Blocks)
X2 (Bus/Tick)─┘
                │
                └── X4 (Manifest 전환 + EventSeed + ProgressionBlock 고도화)
                         │
                         └── X5 (Plugin Protocol + Registry 통합)
                                 │
                                 └── X6 (AffectAware retrieval + 최적화)
```

Plan 05 에서 X1..X6 각 사이클의 상세 PR 분해와 스케줄을 확정한다.
