# TTS Voice 시스템 개선 계획서

> 작성일: 2026-04-03

---

## 1. 현황 분석

### 1.1 현재 데이터 모델

```
profile.json
├── name, display_name, language
├── prompt_text: "우와아 이건 세상에서..."  ← 프로필 전역 1개
├── prompt_lang: "ko"                       ← 프로필 전역 1개
└── emotion_refs:
    ├── neutral: { file: "ref_neutral.wav", text: "" }
    ├── joy:     { file: "ref_joy.wav",     text: "" }
    └── ...
```

### 1.2 현재 GPT-SoVITS API 호출 구조

```python
# gpt_sovits_engine.py — 현재 TTS 요청
payload = {
    "ref_audio_path": "/workspace/.../ref_joy.wav",  # 감정별로 다른 오디오
    "prompt_text": config.prompt_text,                # ⚠️ 항상 동일한 전역 텍스트
    "prompt_lang": config.prompt_lang,                # ⚠️ 항상 동일한 전역 언어
    "text": "합성할 텍스트",
    ...
}
```

### 1.3 핵심 문제점

| # | 문제 | 설명 |
|---|------|------|
| P1 | **오디오-프롬프트 불일치** | GPT-SoVITS는 `[1개 오디오 + 해당 오디오의 발화 텍스트]`를 쌍으로 요구하나, 현재는 감정별로 다른 오디오를 보내면서 prompt_text는 하나만 사용. ref_joy.wav의 발화 내용이 ref_neutral.wav와 다르면 품질 저하 |
| P2 | **수동 경로 입력** | GPT-SoVITS 설정 모달에서 `ref_audio_dir`, `container_ref_dir`를 직접 타이핑 → 오타 가능성, 비직관적 UX |
| P3 | **미리듣기 불가** | 등록된 레퍼런스 오디오를 재생할 방법이 없어 어떤 음성인지 확인 불가 |

---

## 2. GPT-SoVITS 레퍼런스 입력 사양

GPT-SoVITS v2 API (`POST /tts`)의 레퍼런스 관련 필수 3요소:

```
┌─────────────────────────────────────────────────┐
│  Reference = [ Audio File + Prompt Text + Lang ] │
│                                                   │
│  ref_audio_path : 레퍼런스 오디오 파일 경로        │
│  prompt_text    : 해당 오디오에서 말하는 정확한 텍스트│
│  prompt_lang    : 해당 텍스트의 언어               │
└─────────────────────────────────────────────────┘
```

**핵심**: 오디오마다 다른 내용을 말하므로, **각 오디오 파일에 prompt_text/prompt_lang이 개별 매핑**되어야 함.

---

## 3. 개선 목표

| # | 목표 | 우선순위 |
|---|------|---------|
| G1 | 감정별 레퍼런스 오디오 **미리듣기** 기능 | 🔴 HIGH |
| G2 | GPT-SoVITS 설정에서 **Select Box 기반** 프로필/오디오 선택 | 🔴 HIGH |
| G3 | 각 오디오별 **[Audio + Prompt Text + Lang] 쌍** 관리 | 🔴 HIGH |

---

## 4. 개선 설계

### 4.1 데이터 모델 변경

#### profile.json (Before → After)

```jsonc
// ── BEFORE ──
{
  "name": "paimon_ko",
  "prompt_text": "우와아 이건...",    // 전역 하나
  "prompt_lang": "ko",               // 전역 하나
  "emotion_refs": {
    "neutral": { "file": "ref_neutral.wav", "text": "" },
    "joy":     { "file": "ref_joy.wav",     "text": "" }
  }
}

// ── AFTER ──
{
  "name": "paimon_ko",
  "display_name": "파이몬 (한국어)",
  "language": "ko",
  "emotion_refs": {
    "neutral": {
      "file": "ref_neutral.wav",
      "prompt_text": "안녕 나는 파이몬이야 여행자 반가워",     // ✅ 개별 텍스트
      "prompt_lang": "ko"                                    // ✅ 개별 언어
    },
    "joy": {
      "file": "ref_joy.wav",
      "prompt_text": "우와아 이건 세상에서 제일 맛있는 요리야",  // ✅ 개별 텍스트
      "prompt_lang": "ko"                                     // ✅ 개별 언어
    }
  }
}
```

> **호환성**: 기존 `prompt_text`/`prompt_lang` 전역 필드는 마이그레이션 기간 중 fallback으로 유지

#### GPTSoVITSConfig (Before → After)

```python
# ── BEFORE ──
@dataclass
class GPTSoVITSConfig:
    ref_audio_dir: str      # "/app/static/voices/paimon_ko"  (수동 입력)
    container_ref_dir: str  # "/workspace/.../paimon_ko"      (수동 입력)
    prompt_text: str        # 전역 단일 텍스트
    prompt_lang: str        # 전역 단일 언어

# ── AFTER ──
@dataclass
class GPTSoVITSConfig:
    voice_profile: str = ""             # ✅ 프로필 이름 (Select Box로 선택)
    # ref_audio_dir / container_ref_dir → voice_profile에서 자동 파생
    prompt_text: str = ""               # (fallback) 개별 텍스트 없는 오디오용
    prompt_lang: str = "ko"             # (fallback) 개별 언어 없는 오디오용
```

경로 자동 파생 로직:
```
voice_profile = "paimon_ko"
→ ref_audio_dir    = "/app/static/voices/paimon_ko"
→ container_ref_dir = "/workspace/GPT-SoVITS/references/paimon_ko"
```

### 4.2 TTS 엔진 호출 흐름 변경

```
현재:
  emotion → ref_{emotion}.wav 파일 선택
  prompt_text → 항상 전역 config.prompt_text 사용

개선:
  emotion → ref_{emotion}.wav 파일 선택
  prompt_text → profile.json의 emotion_refs[emotion].prompt_text 사용
  fallback → profile.json 전역 prompt_text → config.prompt_text
```

```python
# 개선된 _get_emotion_ref() — (audio_path, prompt_text, prompt_lang) 반환
def _get_emotion_ref(self, emotion, config):
    profile_json → emotion_refs[emotion] 읽기
    return (
        container_path,     # GPT-SoVITS 컨테이너 기준 오디오 경로
        prompt_text,        # 해당 오디오의 프롬프트 텍스트
        prompt_lang,        # 해당 오디오의 프롬프트 언어
    )
```

### 4.3 Frontend UI 변경

#### A. Voice 페이지 — Emotion Reference Card 개선

```
현재 EmotionRefCard:
┌─────────────────────────────────────┐
│ ● Neutral                    [↑] [🗑] │
│   ref_neutral.wav                    │
└─────────────────────────────────────┘

개선 EmotionRefCard:
┌─────────────────────────────────────────────────────┐
│ ● Neutral                        [▶] [↑] [🗑]       │
│   ref_neutral.wav                                    │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Prompt: 안녕 나는 파이몬이야 여행자 반가워      │ │
│ └─────────────────────────────────────────────────┘ │
│   Language: [한국어 ▾]                               │
└─────────────────────────────────────────────────────┘
```

변경사항:
1. **▶ 재생 버튼** 추가 → `<audio>` 태그로 오디오 재생
2. **Prompt Text 입력** 추가 → 해당 오디오의 발화 텍스트 편집
3. **Language 선택** 추가 → 해당 오디오의 프롬프트 언어 선택
4. 업로드 시 Prompt Text 입력 필수화

#### B. GPT-SoVITS 설정 모달 — Select Box 전환

```
현재:
┌─────────────────────────────────────┐
│ Reference Audio Path (Backend)       │
│ [/app/static/voices/paimon_ko     ] │ ← 수동 텍스트 입력
│                                      │
│ Reference Audio Path (GPT-SoVITS)    │
│ [/workspace/.../references/paimon_ko]│ ← 수동 텍스트 입력
│                                      │
│ Prompt Text                          │
│ [우와아 이건 세상에서 제일 맛있는...] │ ← 전역 단일 텍스트
└─────────────────────────────────────┘

개선:
┌─────────────────────────────────────┐
│ Voice Profile                        │
│ [▾ paimon_ko (파이몬 한국어)       ] │ ← Select Box
│   ℹ️ /app/static/voices/paimon_ko    │     (경로 자동 표시)
│                                      │
│ Fallback Prompt Text                 │
│ [우와아 이건 세상에서 제일 맛있는...] │ ← 개별 텍스트 없을 때만 사용
│                                      │
│ Fallback Prompt Language             │
│ [▾ 한국어                          ] │
└─────────────────────────────────────┘
```

---

## 5. 구현 범위

### 5.1 Backend 변경

| # | 파일 | 변경 내용 |
|---|------|----------|
| B1 | `tts_controller.py` | `GET /profiles/{name}/ref/{emotion}/audio` — 오디오 파일 스트리밍 엔드포인트 신규 |
| B2 | `tts_controller.py` | `upload_reference_audio` — `text` 파라미터 활용하여 `emotion_refs[emotion].prompt_text` 저장, `lang` 파라미터 추가 |
| B3 | `tts_controller.py` | `update_profile`, `list_profiles` — 개별 emotion_refs 텍스트 반환 |
| B4 | `gpt_sovits_config.py` | `ref_audio_dir` / `container_ref_dir` → `voice_profile` (SELECT type) 전환, 필드 메타데이터에 프로필 목록 동적 주입 |
| B5 | `gpt_sovits_engine.py` | `_get_emotion_ref()` → `(audio_path, prompt_text, prompt_lang)` 튜플 반환, `synthesize_stream()`에서 개별 prompt 사용 |
| B6 | `tts_controller.py` | `PUT /profiles/{name}/ref/{emotion}` — 개별 emotion의 prompt_text/prompt_lang 수정 엔드포인트 신규 |

### 5.2 Frontend 변경

| # | 파일 | 변경 내용 |
|---|------|----------|
| F1 | `tts-voice/page.tsx` | EmotionRefCard에 ▶ 재생 버튼 추가 (HTML5 Audio) |
| F2 | `tts-voice/page.tsx` | EmotionRefCard에 prompt_text 입력 필드 + language 선택 추가 |
| F3 | `tts-voice/page.tsx` | 프로필 전역 Prompt Settings 섹션 → Fallback Prompt로 역할 변경 |
| F4 | `api.ts` | `getRefAudioUrl(name, emotion)` 유틸 추가, `updateEmotionRef()` 메소드 추가 |
| F5 | `i18n/en.ts`, `ko.ts` | 관련 번역 키 추가 (`ttsVoice.play`, `ttsVoice.promptPerEmotion` 등) |

### 5.3 GPT-SoVITS Config (설정 모달) 변경

| # | 파일 | 변경 내용 |
|---|------|----------|
| C1 | `gpt_sovits_config.py` | `voice_profile` 필드를 SELECT 타입으로 정의, options를 동적으로 프로필 목록에서 로드 |
| C2 | `gpt_sovits_config.py` | `ref_audio_dir`, `container_ref_dir` 필드 제거 (voice_profile에서 자동 파생) |
| C3 | `gpt_sovits_engine.py` | `voice_profile` → 경로 자동 파생 로직 추가 |

---

## 6. 마이그레이션 전략

### 6.1 하위 호환성

```python
# 엔진에서 경로 파생 (voice_profile 우선, 레거시 fallback)
if config.voice_profile:
    ref_audio_dir = f"/app/static/voices/{config.voice_profile}"
    container_ref_dir = f"/workspace/GPT-SoVITS/references/{config.voice_profile}"
else:
    # 레거시: 직접 경로 사용 (기존 설정 호환)
    ref_audio_dir = config.ref_audio_dir
    container_ref_dir = config.container_ref_dir
```

### 6.2 profile.json 마이그레이션

```python
# list_profiles / get_profile에서 자동 마이그레이션
if "prompt_text" in data and data.get("emotion_refs"):
    for emotion, ref in data["emotion_refs"].items():
        if "prompt_text" not in ref:
            ref["prompt_text"] = data["prompt_text"]  # 전역값을 개별로 복사
            ref["prompt_lang"] = data.get("prompt_lang", "ko")
```

---

## 7. API 엔드포인트 변경 요약

### 신규

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/api/tts/profiles/{name}/ref/{emotion}/audio` | 레퍼런스 오디오 파일 스트리밍 (재생용) |
| `PUT` | `/api/tts/profiles/{name}/ref/{emotion}` | 개별 emotion의 prompt_text / prompt_lang 수정 |

### 변경

| Method | Path | 변경 내용 |
|--------|------|----------|
| `POST` | `/api/tts/profiles/{name}/ref` | `lang` Form 파라미터 추가 |
| `GET` | `/api/tts/profiles` | 각 emotion_refs에 prompt_text/prompt_lang 포함 반환 |
| `GET` | `/api/tts/profiles/{name}` | 각 emotion_refs에 prompt_text/prompt_lang 포함 반환 |

---

## 8. 작업 순서

```
Phase 1 — Backend 데이터 모델 & API 변경
  ├─ B1. 오디오 스트리밍 엔드포인트
  ├─ B2. 업로드 시 prompt_text/lang 저장
  ├─ B6. 개별 emotion prompt 수정 API
  └─ B3. list/get에서 개별 prompt 반환

Phase 2 — Frontend Voice 페이지 개선
  ├─ F1. 오디오 재생 버튼
  ├─ F2. 개별 prompt_text/lang 입력 UI
  ├─ F4. API 메소드 추가
  └─ F5. i18n 키 추가

Phase 3 — GPT-SoVITS Config & Engine 전환
  ├─ C1-C2. voice_profile SELECT 전환
  ├─ B4. Config 필드 메타데이터 변경
  ├─ B5. 엔진 호출 시 개별 prompt 사용
  └─ C3. 경로 자동 파생

Phase 4 — 마이그레이션 & 테스트
  └─ 기존 profile.json 자동 마이그레이션 로직
```

---

## 9. 최종 UX Flow

```
사용자 시나리오:

1. /tts-voice 페이지 접속
2. paimon_ko 프로필 선택
3. Neutral 카드 → [↑] 클릭 → ref_neutral.wav 업로드
   → Prompt: "안녕 나는 파이몬이야 여행자 반가워" 입력
   → Language: 한국어 선택
4. [▶] 클릭 → 업로드한 오디오 미리듣기
5. Joy 카드 → [↑] 클릭 → ref_joy.wav 업로드
   → Prompt: "우와아 이건 세상에서 제일 맛있는 요리야" 입력
6. [★ Activate] → 프로필 활성화

7. 설정 모달 (GPT-SoVITS) 확인:
   → Voice Profile: [▾ paimon_ko] (Select Box)
   → Fallback Prompt: (개별 prompt 없는 오디오 대비)

8. TTS 요청 시:
   → emotion=joy → ref_joy.wav + "우와아 이건..." (개별 prompt) 전송
   → emotion=neutral → ref_neutral.wav + "안녕 나는..." (개별 prompt) 전송
```
