# 음성 프로파일 시스템 심층 분석 리포트

## 1. 개요

음성 프로파일 시스템은 **감정 기반 음성 클로닝**을 구현한다. GPT-SoVITS v2 엔진을 사용하며, 감정별 참조 오디오(reference audio)를 기반으로 해당 감정 톤의 음성을 합성한다.

**핵심 질문: neutral만 등록된 경우?**
→ 다른 감정(joy, anger 등)이 요청되면 **neutral로 폴백**하여 합성이 정상 진행된다. 에러 없이 동작하지만, 감정 표현 없이 중립 톤으로만 출력된다.

---

## 2. 데이터 모델

### 2.1 프로파일 디렉토리 구조

```
backend/static/voices/{profile_name}/
├── profile.json           ← 메타데이터 + emotion_refs 매핑
├── ref_neutral.wav        ← 감정별 참조 오디오 (5-10초)
├── ref_joy.wav
├── ref_anger.wav
├── ref_sadness.wav
├── ref_fear.wav
├── ref_surprise.wav
├── ref_disgust.wav
└── ref_smirk.wav
```

### 2.2 profile.json 스키마

```json
{
  "name": "paimon_ko",
  "display_name": "파이몬 (한국어)",
  "language": "ko",
  "is_template": false,
  "prompt_text": "으음~ 나쁘지 않은데?",
  "prompt_lang": "ko",
  "gpt_sovits_settings": {
    "enabled": true,
    "top_k": 5,
    "top_p": 1.0,
    "temperature": 1.0,
    "speed": 1.0
  },
  "emotion_refs": {
    "neutral": {
      "file": "ref_neutral.wav",
      "prompt_text": "으음~ 나쁘지 않은데? 너도 먹어봐~",
      "prompt_lang": "ko"
    },
    "joy": {
      "file": "ref_joy.wav",
      "prompt_text": "우와아——! 이건 세상에서 제일 맛있는 요리야!",
      "prompt_lang": "ko"
    }
  }
}
```

**필드 설명:**

| 필드 | 설명 |
|------|------|
| `emotion_refs[emotion].file` | 참조 오디오 파일명 (e.g., `ref_joy.wav`) |
| `emotion_refs[emotion].prompt_text` | 참조 오디오에 담긴 대사 (GPT-SoVITS 컨디셔닝용) |
| `emotion_refs[emotion].prompt_lang` | 참조 오디오 언어 |
| `prompt_text` / `prompt_lang` | 프로파일 레벨 기본값 (감정별 prompt 없으면 이 값 사용) |

### 2.3 지원 감정 목록

```
neutral, joy, anger, sadness, fear, surprise, disgust, smirk
```

총 8개 감정. 프론트엔드 `EMOTIONS` 상수와 백엔드 허용 목록이 일치한다.

---

## 3. 전체 플로우: 프론트엔드 → 백엔드 → TTS → 음성 출력

### 3.1 프로파일 등록 플로우

```
[프론트엔드: /tts-voice 페이지]
  │
  ├─ (1) 프로파일 생성
  │      POST /api/tts/profiles
  │      { name, display_name, language }
  │      → backend/static/voices/{name}/profile.json 생성
  │
  ├─ (2) 감정별 참조 오디오 업로드
  │      POST /api/tts/profiles/{name}/ref
  │      multipart: { emotion, text, lang, file(.wav) }
  │      → ref_{emotion}.wav 저장
  │      → profile.json의 emotion_refs[emotion] 업데이트
  │
  ├─ (3) 프롬프트 텍스트 수정 (오디오 재업로드 불필요)
  │      PUT /api/tts/profiles/{name}/ref/{emotion}
  │      { prompt_text, prompt_lang }
  │
  └─ (4) 프로파일 활성화
         POST /api/tts/profiles/{name}/activate
         → GPTSoVITSConfig 업데이트:
           voice_profile = name
           ref_audio_dir = /app/static/voices/{name}
           container_ref_dir = /workspace/GPT-SoVITS/references/{name}
```

### 3.2 VTuber 응답 시 음성 합성 플로우

```
사용자 메시지 입력
    ↓
VTuber 워크플로우 실행 (vtuber_respond_node)
    ↓
LLM이 감정 태그 포함 응답 생성
    예: "[joy] 안녕하세요! 기분이 좋아요!"
    ↓
EmotionExtractor.extract() ─────────────────────────────────┐
    ├─ primary_emotion: "joy"                                │
    ├─ cleaned_text: "안녕하세요! 기분이 좋아요!"              │
    └─ expression_index: 3 (emotionMap["joy"])               │
    ↓                                                        │
[분기 1] 아바타 표정 업데이트 ←──────────────────────────────┘
    state_manager.update_state(emotion="joy", index=3)
    → Live2D 아바타가 기쁜 표정으로 변경
    ↓
[분기 2] TTS 합성 요청
    POST /api/tts/agents/{session_id}/speak
    { text: "안녕하세요! 기분이 좋아요!", emotion: "joy" }
    ↓
TTS Service
    ├─ 세션별 voice_profile 확인 (session.extra_data["tts_voice_profile"])
    ├─ 없으면 글로벌 GPTSoVITSConfig.voice_profile 사용
    └─ GPT-SoVITS 엔진으로 라우팅
    ↓
GPT-SoVITS Engine: synthesize_stream()
    ↓
_get_emotion_ref(emotion="joy", ...)  ← ⭐ 핵심 메서드
    ├─ ref_joy.wav 존재? → 사용
    ├─ 없으면 ref_neutral.wav 존재? → 폴백 사용
    └─ 둘 다 없으면 → 컨테이너 경로 전달 (실패 가능)
    ↓
GPT-SoVITS API v2 호출
    POST http://gpt-sovits:9880/tts
    {
      text: "안녕하세요! 기분이 좋아요!",
      text_lang: "ko",
      ref_audio_path: "/workspace/GPT-SoVITS/references/paimon_ko/ref_joy.wav",
      prompt_text: "우와아! 이건 최고야!",
      prompt_lang: "ko",
      temperature: 1.0,
      speed_factor: 1.0
    }
    ↓
WAV 오디오 바이트 반환 → 프론트엔드 재생
```

---

## 4. 감정 참조 오디오 선택 로직 (핵심)

### 4.1 `_get_emotion_ref()` 메서드

파일: `backend/service/vtuber/tts/engines/gpt_sovits_engine.py` L206-265

```python
def _get_emotion_ref(self, emotion, config, ref_dir, container_dir):
    # profile.json 로드
    emotion_refs = load_profile_json(ref_dir)

    def _resolve(emo):
        full_path = os.path.join(ref_dir, f"ref_{emo}.wav")
        if os.path.exists(full_path):
            return (container_path, prompt_text, prompt_lang)
        return None

    # ① 요청된 감정 시도
    result = _resolve(emotion)
    if result:
        return result

    # ② neutral로 폴백
    result = _resolve("neutral")
    if result:
        logger.info(f"Emotion '{emotion}' not found, falling back to neutral")
        return result

    # ③ 로컬 파일 없음 — 컨테이너 경로 그대로 전달
    return (container_path_as_is, "", "")
```

### 4.2 시나리오별 동작 매트릭스

| 시나리오 | 요청 감정 | 참조 오디오 | 결과 | 로그 |
|----------|-----------|------------|------|------|
| **neutral만 등록, joy 요청** | joy | ref_neutral.wav 사용 | ✅ 정상 합성 (중립 톤) | `"Emotion 'joy' not found, falling back to neutral"` |
| **neutral만 등록, neutral 요청** | neutral | ref_neutral.wav 사용 | ✅ 정상 합성 | — |
| **joy만 등록, neutral 요청** | neutral | ref_neutral.wav 없음 | ❌ 실패 가능 | `"sending container path as-is"` |
| **joy만 등록, joy 요청** | joy | ref_joy.wav 사용 | ✅ 정상 합성 | — |
| **joy만 등록, anger 요청** | anger | ref_neutral.wav 없음 | ❌ 실패 가능 | `"sending container path as-is"` |
| **아무것도 없음** | any | 없음 | ❌ 실패 | `"No reference audio found"` |

### 4.3 "neutral만 등록" 시나리오 상세

**상황:** `emotion_refs`에 neutral만 등록, 에이전트가 `[joy]` 태그 출력

1. `EmotionExtractor.extract("[joy] 안녕!")` → `primary_emotion = "joy"`
2. `tts.speak(emotion="joy", voice_profile="paimon_ko")`
3. `_get_emotion_ref("joy", ...)`
   - `_resolve("joy")` → `ref_joy.wav` 없음 → `None`
   - `_resolve("neutral")` → `ref_neutral.wav` **존재** → 반환 ✅
   - 로그: `"Emotion 'joy' not found, falling back to neutral"`
4. neutral의 `prompt_text`, `prompt_lang`으로 GPT-SoVITS API 호출
5. **결과:** 합성 성공, 단 중립 톤으로 출력

**영향:**
- 음성은 나오지만, 기쁜/슬픈/화난 톤 변화가 없음
- Live2D 아바타 표정은 `joy`로 정상 변경됨 (감정 추출은 TTS와 독립)
- **아바타 표정은 기쁜데, 목소리는 중립** — 약간 부자연스럽지만 치명적이지는 않음

---

## 5. 감정 추출 파이프라인

### 5.1 EmotionExtractor

파일: `backend/service/vtuber/emotion_extractor.py`

```python
# 패턴: [알파벳_단어] 형태 매칭
_EMOTION_TAG_PATTERN = re.compile(r"\[([a-zA-Z_]+)\]")
```

**동작:**
1. 텍스트에서 `[emotion]` 태그 전부 추출
2. `emotion_map`에 등록된 유효 감정만 필터
3. 첫 번째 유효 감정 = `primary_emotion`
4. 태그 제거 후 클린 텍스트 반환

**예시:**
- Input: `"[joy] 안녕! [surprise] 와!"`
- emotions: `["joy", "surprise"]`
- primary_emotion: `"joy"`
- cleaned_text: `"안녕! 와!"`

### 5.2 감정 태그 생성 (LLM 프롬프트)

`vtuber_respond_node.py`의 프롬프트에서 LLM에게 감정 태그를 붙이도록 지시:

```
Start your response with an emotion tag:
[neutral], [joy], [anger], [disgust], [fear], [smirk], [sadness], [surprise]
```

### 5.3 사용처

| 사용처 | 타이밍 | 용도 |
|--------|--------|------|
| SSE 스트리밍 (agent_controller) | 실행 중 실시간 | 아바타 표정 업데이트 |
| 실행 완료 (agent_executor) | 실행 후 | 최종 감정 상태 반영 |
| TTS 합성 | 실행 후 | 감정별 참조 오디오 선택 |

---

## 6. 프론트엔드 UI

### 6.1 페이지 구조 (`/tts-voice`)

```
┌────────────────┬────────────────────────────────────┐
│   사이드바      │   메인 콘텐츠                        │
│                │                                    │
│  [← 돌아가기]   │   프로파일명     [ACTIVE]            │
│  [+ 새 프로파일] │                                    │
│                │   [★ 활성화]                        │
│  paimon_ko ★   │                                    │
│  my_voice      │   ── 감정별 참조 오디오 ──            │
│  ...           │                                    │
│                │   ● neutral  ref_neutral.wav [▶][⬆][🗑] │
│                │     프롬프트: [____________]  [한국어▼] │
│                │                                    │
│                │   ● joy      미등록        [⬆]      │
│                │                                    │
│                │   ● anger    미등록        [⬆]      │
│                │   ...                              │
└────────────────┴────────────────────────────────────┘
```

### 6.2 EmotionRefCard 컴포넌트

각 감정(8개)마다 카드 하나:
- **오디오 등록됨:** 초록 테두리, 재생/업로드/삭제 버튼, prompt 텍스트 편집
- **미등록:** 기본 테두리, 업로드 버튼만
- **템플릿 프로파일:** 읽기 전용 (업로드/삭제 불가)

### 6.3 업로드 플로우

1. 업로드 버튼 클릭 → `<input type="file" accept=".wav">` 트리거
2. 파일 선택 시 `onUpload(file, localPromptText, localPromptLang)` 호출
3. `ttsApi.uploadRef(profile, emotion, file, text, lang)` → `POST /api/tts/profiles/{name}/ref`
4. 성공 시 프로파일 새로고침 → UI 업데이트

### 6.4 프롬프트 텍스트 편집

- `input` 필드에서 직접 편집
- `onBlur` 시 변경 감지 → 자동 저장 (`PUT /api/tts/profiles/{name}/ref/{emotion}`)
- 언어 드롭다운 변경 시 즉시 저장

---

## 7. 세션별 프로파일 오버라이드

VTuber 세션마다 다른 음성 프로파일을 지정할 수 있다.

```
PUT /api/tts/agents/{session_id}/profile
{ "profile_name": "my_voice" }
```

- 저장 위치: `session.extra_data["tts_voice_profile"]`
- TTS 합성 시: 세션 프로파일 > 글로벌 설정 순으로 우선
- 삭제 시 (`DELETE`): 글로벌 설정으로 복귀

---

## 8. GPT-SoVITS 설정 연동

### GPTSoVITSConfig

```python
@dataclass
class GPTSoVITSConfig(BaseConfig):
    enabled: bool = False
    api_url: str = "http://gpt-sovits:9880"
    voice_profile: str = "paimon_ko"
    ref_audio_dir: str = "/app/static/voices/paimon_ko"         # 레거시 (자동 파생)
    container_ref_dir: str = "/workspace/GPT-SoVITS/references/paimon_ko"  # 레거시
    prompt_text: str = ""
    prompt_lang: str = "ko"
    top_k: int = 5
    top_p: float = 1.0
    temperature: float = 1.0
    speed: float = 1.0
```

프로파일 활성화 시:
- `voice_profile`, `ref_audio_dir`, `container_ref_dir` 자동 동기화
- `prompt_text`, `prompt_lang`도 profile.json에서 가져옴

---

## 9. 발견된 이슈 및 개선점

### 🔴 Issue #1: neutral 미등록 시 TTS 실패

**심각도:** Critical

**현상:**
- neutral 없이 joy만 등록한 상태에서 anger 요청 시:
  - `_resolve("anger")` → None
  - `_resolve("neutral")` → None (neutral 없음)
  - 컨테이너 경로만 전달 → GPT-SoVITS가 파일 못 찾음 → 에러

**원인:** 폴백 체인이 `요청 감정 → neutral → 실패`로만 구성. 등록된 아무 감정이라도 써야.

**권장 수정:**
```python
# 현재 (2단계 폴백)
result = _resolve(emotion) or _resolve("neutral")

# 개선안 (3단계 폴백: 아무 등록 감정이라도 사용)
result = _resolve(emotion) or _resolve("neutral")
if not result and emotion_refs:
    # 등록된 아무 감정이라도 폴백
    for fallback_emo in emotion_refs:
        result = _resolve(fallback_emo)
        if result:
            logger.info(f"Emotion '{emotion}' and 'neutral' not found, "
                       f"falling back to '{fallback_emo}'")
            break
```

### 🟡 Issue #2: 참조 오디오 길이 검증 없음

**심각도:** Medium

GPT-SoVITS는 5-10초 참조 오디오를 요구하나, 업로드 시 길이 검증이 없다. 너무 짧거나 긴 오디오가 업로드되면 합성 품질 저하 또는 실패.

**권장:** 업로드 시 오디오 길이 검증 + 프론트엔드 경고

### 🟡 Issue #3: 프론트엔드에서 neutral 필수 안내 부족

**심각도:** Medium

사용자가 joy만 업로드하고 neutral을 건너뛸 수 있는데, UI에서 "neutral은 폴백용이므로 반드시 등록하세요"라는 안내가 없다.

**권장:** neutral 카드에 필수 뱃지 표시 또는 미등록 시 경고

### 🟢 Issue #4: 태그 정리 불완전

**심각도:** Low

`EmotionExtractor`는 유효 감정만 추출하나, `[happy]` 같은 유효하지 않은 태그도 텍스트에서 제거한다 (`_EMOTION_TAG_PATTERN.sub("", text)`). 문제는 없지만 `remove_tags()`와 동작이 다소 중복.

### 🟢 Issue #5: 템플릿 프로파일 수정 시도 시 에러만 반환

**심각도:** Low

`is_template: true` 프로파일 수정 시 403 에러가 반환되나, 프론트엔드에서 미리 경고하지 않고 에러 후에야 사용자가 알게 됨. (현재는 버튼이 숨겨져 있어 큰 문제는 아님)

---

## 10. 요약

| 항목 | 상태 |
|------|------|
| 프로파일 등록 (CRUD) | ✅ 정상 동작 |
| 감정별 참조 오디오 업로드 | ✅ 정상 동작 |
| 감정 추출 파이프라인 | ✅ 정상 동작 |
| neutral만 등록 → 다른 감정 요청 | ✅ neutral로 폴백 (정상) |
| neutral 미등록 → 폴백 실패 | ⚠️ 개선 필요 (Issue #1) |
| 세션별 프로파일 오버라이드 | ✅ 정상 동작 |
| 프론트엔드 UI | ✅ 정상 동작 |
| 아바타 표정 연동 | ✅ 독립적으로 정상 동작 |
| 오디오 길이 검증 | ⚠️ 미구현 (Issue #2) |
