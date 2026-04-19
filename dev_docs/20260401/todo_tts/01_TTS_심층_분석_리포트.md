# 01. TTS 심층 분석 리포트

> **작성일**: 2026-04-01
> **대상 시스템**: GenY VTuber 서비스
> **범위**: TTS(Text-to-Speech) 전용 — 클라우드 플랫폼 + 오픈소스(GPT-SoVITS 등) 완벽 분석

---

## 1. 현재 시스템 상태 진단

### 1.1 VTuber 응답 파이프라인 (현재)

```
User Text → POST /broadcast → LLM → "[joy] 안녕하세요!"
  → EmotionExtractor.extract() → emotion="joy", text="안녕하세요!"
  → AvatarStateManager.update_state() → expression_index=3, motion="TapBody"
  → SSE push → Frontend Live2D 렌더링 (표정+모션만, 음성 없음)
```

**현재 한계**:
- VTuber가 텍스트로만 응답 → **캐릭터 몰입감 심각하게 부족**
- Live2D 모델에 ParamMouthOpenY/ParamMouthForm 파라미터 존재하지만 **미사용**
- 감정 태그(`[joy]`, `[anger]` 등)는 표정에만 반영, **음성 톤에는 미반영**

### 1.2 기존 설정 시스템 패턴

GenY는 강력한 설정 시스템을 보유하고 있어 TTS 통합에 매우 유리:

```python
# 검증된 패턴: @register_config + BaseConfig 데이터클래스
@register_config
@dataclass
class SomeConfig(BaseConfig):
    field: str = "default"

    @classmethod
    def get_config_name(cls) -> str: return "some_config"
    @classmethod
    def get_fields_metadata(cls) -> list: return [...]  # UI 자동 생성
```

- **저장**: Cache → PostgreSQL → JSON 파일 (3단계 폴백)
- **API**: `GET/PUT /api/config/{name}` 로 즉시 조회/변경
- **UI**: `get_fields_metadata()` 기반으로 프론트엔드 자동 렌더링
- **콜백**: `apply_change` 로 설정 변경 시 실시간 반영 가능
- **i18n**: 한국어/영어 동시 지원

→ TTS 설정도 이 패턴을 그대로 따르면 **설정 UI가 자동으로 생성**됨

### 1.3 관련 기술 스택

| 항목 | 현재 기술 | TTS 연관성 |
|------|-----------|-----------|
| Backend | FastAPI + asyncio | async TTS 스트리밍에 최적 |
| 통신 | SSE (Server-Sent Events) | 오디오 메타데이터 전송 가능 |
| 감정 시스템 | EmotionExtractor (8개 감정) | TTS 감정 파라미터 직접 매핑 |
| 모델 레지스트리 | model_registry.json | 모델별 보이스 프로필 추가 가능 |
| 설정 시스템 | @register_config + BaseConfig | TTS 엔진 설정 자동 UI 생성 |
| 프론트엔드 | Pixi.js + Live2D Cubism 4 | ParamMouthOpenY 립싱크 연동 |
| 인프라 | Docker Compose (3 서비스) | TTS 엔진 서비스 추가 가능 |

---

## 2. 클라우드 TTS 플랫폼 심층 분석

### 2.1 OpenAI TTS

| 항목 | 내용 |
|------|------|
| **API** | `POST https://api.openai.com/v1/audio/speech` |
| **모델** | `tts-1` (빠름), `tts-1-hd` (고품질) |
| **보이스** | alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer (10개) |
| **포맷** | mp3, opus, aac, flac, wav, pcm |
| **스트리밍** | ✅ chunked transfer-encoding |
| **한국어** | ✅ 자연스러움 |
| **일본어** | ✅ 자연스러움 |
| **감정 제어** | △ 보이스 프리셋별 톤 차이만 (명시적 감정 파라미터 없음) |
| **보이스 클로닝** | ✗ 불가 |
| **비용** | tts-1: $15/1M chars, tts-1-hd: $30/1M chars |
| **지연** | ~500ms (첫 청크), 스트리밍으로 체감 지연 낮음 |

**구현 예시**:
```python
import httpx

async def openai_tts_stream(text: str, voice: str = "nova"):
    async with httpx.AsyncClient() as client:
        async with client.stream("POST", "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "tts-1", "input": text, "voice": voice, "response_format": "mp3"}
        ) as resp:
            async for chunk in resp.aiter_bytes(4096):
                yield chunk
```

**장점**: 간단한 API, 안정적, 다국어 우수
**단점**: 감정 제어 제한, 보이스 클로닝 불가, 커스터마이징 한계

---

### 2.2 ElevenLabs

| 항목 | 내용 |
|------|------|
| **API** | `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream` |
| **모델** | `eleven_multilingual_v2`, `eleven_turbo_v2.5` |
| **보이스** | 수천 개 커뮤니티 보이스 + 커스텀 클로닝 |
| **스트리밍** | ✅ HTTP chunked + WebSocket 실시간 |
| **한국어** | ✅ multilingual_v2로 양호 |
| **일본어** | ✅ multilingual_v2로 양호 |
| **감정 제어** | ✅ stability, similarity_boost, style, use_speaker_boost |
| **보이스 클로닝** | ✅ Instant Voice Cloning (짧은 샘플), Professional Voice Cloning |
| **비용** | Starter $5/30K chars, Creator $22/100K chars, Pro $99/500K chars |
| **지연** | turbo_v2.5: ~300ms, multilingual_v2: ~500ms |

**감정 매핑 전략**:
```python
EMOTION_TO_ELEVENLABS = {
    "neutral":  {"stability": 0.50, "similarity_boost": 0.75, "style": 0.00},
    "joy":      {"stability": 0.30, "similarity_boost": 0.75, "style": 0.80},
    "anger":    {"stability": 0.70, "similarity_boost": 0.85, "style": 0.60},
    "sadness":  {"stability": 0.60, "similarity_boost": 0.70, "style": 0.40},
    "fear":     {"stability": 0.40, "similarity_boost": 0.65, "style": 0.50},
    "surprise": {"stability": 0.20, "similarity_boost": 0.75, "style": 0.90},
    "disgust":  {"stability": 0.65, "similarity_boost": 0.80, "style": 0.30},
    "smirk":    {"stability": 0.45, "similarity_boost": 0.75, "style": 0.60},
}
```

**장점**: 최고 품질, 감정 제어 우수, 보이스 클로닝, WebSocket 스트리밍
**단점**: 높은 비용, 문자 수 제한, 외부 의존

---

### 2.3 Google Cloud TTS

| 항목 | 내용 |
|------|------|
| **API** | `POST https://texttospeech.googleapis.com/v1/text:synthesize` |
| **모델** | Standard, WaveNet, Neural2, Studio, Journey |
| **보이스** | ko-KR: 4개, ja-JP: 6개, en-US: 30+개 |
| **스트리밍** | ✅ gRPC Streaming API (Streaming Synthesis) |
| **한국어** | ✅ 우수 (ko-KR-Neural2-A/B/C, ko-KR-Wavenet-A/B/C/D) |
| **일본어** | ✅ 우수 |
| **감정 제어** | ✅ SSML `<prosody>`, `<emphasis>`, `<say-as>` |
| **보이스 클로닝** | ✅ Custom Voice (최소 100 발화 필요) |
| **비용** | Standard $4/1M, WaveNet $16/1M, Neural2 $16/1M, Studio $160/1M |
| **지연** | ~300ms (Neural2), ~200ms (Standard) |

**SSML 감정 표현**:
```xml
<!-- joy -->
<speak>
  <prosody rate="110%" pitch="+2st">
    안녕하세요! 오늘 기분이 정말 좋아요!
  </prosody>
</speak>

<!-- sadness -->
<speak>
  <prosody rate="85%" pitch="-3st" volume="-2dB">
    그런 일이 있었군요... 안타깝네요.
  </prosody>
</speak>

<!-- anger -->
<speak>
  <prosody rate="120%" pitch="+1st" volume="+3dB">
    <emphasis level="strong">그건 정말 아니에요!</emphasis>
  </prosody>
</speak>
```

**장점**: SSML로 세밀한 감정/운율 제어, 안정적, 합리적 비용
**단점**: 보이스 다양성 제한, 클로닝 진입장벽 높음

---

### 2.4 Microsoft Azure Speech Services

| 항목 | 내용 |
|------|------|
| **API** | REST + SDK (azure-cognitiveservices-speech) |
| **보이스** | ko-KR: 6개 Neural, ja-JP: 10+개, en-US: 50+개 |
| **스트리밍** | ✅ WebSocket 실시간 (Speech SDK) |
| **한국어** | ✅ 우수 (ko-KR-SunHiNeural, ko-KR-InJoonNeural 등) |
| **감정 제어** | ✅✅ SSML `<mstts:express-as>` — 업계 최강 |
| **보이스 클로닝** | ✅ Custom Neural Voice (Pro/Lite) |
| **Viseme 지원** | ✅✅ **실시간 Viseme 이벤트** — 립싱크에 매우 유용 |
| **비용** | Neural: $16/1M chars, Custom Neural: $24/1M chars |
| **지연** | ~200ms (첫 청크) |

**감정 SSML (Azure 전용 — 업계 최강)**:
```xml
<speak version="1.0" xmlns:mstts="https://www.w3.org/2001/mstts">
  <voice name="ko-KR-SunHiNeural">
    <!-- 직접적인 감정 스타일 지정! -->
    <mstts:express-as style="cheerful" styledegree="2">
      안녕하세요! 정말 반가워요!
    </mstts:express-as>
  </voice>
</speak>
```

**지원 감정 스타일 (ko-KR-SunHiNeural)**:
- `cheerful`, `sad`, `angry`, `fearful`, `disgruntled`, `serious`
- `friendly`, `gentle`, `envious`, `calm`
- `styledegree`: 0.01 ~ 2.0 (감정 강도)

**Viseme 이벤트 (립싱크 핵심!)**:
```json
// Azure에서 TTS 합성 시 실시간으로 제공
{
  "VisemeId": 6,          // 입모양 ID (0~21)
  "AudioOffset": 500000,  // 오디오 시작 시점 (100ns 단위)
  "Animation": {          // blend shape 가중치 (선택적)
    "BlendShapes": [[...]]
  }
}
```

**장점**: 감정 표현 최강, Viseme 네이티브 지원, 풍부한 보이스
**단점**: SDK 무거움, 비용 높음, 설정 복잡

---

### 2.5 NAVER CLOVA Voice / HyperCLOVA

| 항목 | 내용 |
|------|------|
| **API** | `POST https://naveropenapi.apigw.ntruss.com/tts-premium/v1/tts` |
| **보이스** | 한국어 특화 20+개 (아라, 미진, 지호, 하준 등) |
| **한국어** | ✅✅✅ **한국어 최고 자연스러움** |
| **일본어** | ✗ 미지원 |
| **감정 제어** | △ 일부 보이스에서 감정 변형 지원 |
| **스트리밍** | △ 배치 방식 (결과 바로 반환) |
| **비용** | Premium $8/1M chars |
| **지연** | ~500ms (전체 생성) |

**장점**: 한국어 최고 자연스러움, 합리적 비용
**단점**: 스트리밍 미흡, 일본어 미지원, 감정 제어 제한

---

### 2.6 Edge TTS (비공식 무료)

| 항목 | 내용 |
|------|------|
| **라이브러리** | `edge-tts` (Python), Microsoft Edge 읽기 기능 활용 |
| **보이스** | 400+개 (ko-KR 4개, ja-JP 4개, en-US 20+개) |
| **한국어** | ✅ 양호 (SunHiNeural, InJoonNeural, BongJinNeural, YuJinNeural) |
| **일본어** | ✅ 양호 (NanamiNeural, KeitaNeural, AoiNeural, DaichiNeural) |
| **감정 제어** | △ rate, pitch, volume만 조절 가능 |
| **스트리밍** | ✅ 네이티브 청크 스트리밍 |
| **비용** | ✅✅✅ **완전 무료** |
| **지연** | ~300ms (첫 청크) |
| **보이스 클로닝** | ✗ |

```python
import edge_tts

async def edge_tts_stream(text: str, voice: str = "ko-KR-SunHiNeural"):
    communicate = edge_tts.Communicate(text, voice, rate="+0%", pitch="+0Hz")
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            yield chunk["data"]
        elif chunk["type"] == "WordBoundary":
            # offset, duration, text — 립싱크 타이밍에 활용 가능
            pass
```

**장점**: 완전 무료, 빠름, 다국어, WordBoundary 이벤트 제공
**단점**: 비공식 API (안정성 보장 불가), 감정 제어 제한, 이용약관 회색지대

---

### 2.7 클라우드 TTS 종합 비교 매트릭스

| 기준 | OpenAI | ElevenLabs | Google | Azure | CLOVA | Edge TTS |
|------|--------|------------|--------|-------|-------|----------|
| **음질** | ★★★★★ | ★★★★★ | ★★★★ | ★★★★★ | ★★★★★ | ★★★★ |
| **한국어** | ★★★★ | ★★★★ | ★★★★ | ★★★★ | ★★★★★ | ★★★★ |
| **감정 제어** | ★★ | ★★★★ | ★★★★ | ★★★★★ | ★★ | ★★ |
| **스트리밍** | ★★★★ | ★★★★★ | ★★★★ | ★★★★★ | ★★ | ★★★★ |
| **보이스 클로닝** | ✗ | ★★★★★ | ★★★ | ★★★★ | ✗ | ✗ |
| **비용** | $$$ | $$$$ | $$ | $$$ | $$ | **무료** |
| **Viseme/립싱크** | ✗ | △ | ✗ | ★★★★★ | ✗ | △ WordBoundary |
| **API 안정성** | ★★★★★ | ★★★★ | ★★★★★ | ★★★★★ | ★★★★ | ★★ (비공식) |
| **설정 복잡도** | ★ 쉬움 | ★★ | ★★★ | ★★★★ | ★★ | ★ 쉬움 |

---

## 3. 오픈소스 TTS 심층 분석

### 3.1 GPT-SoVITS (⭐ 핵심 — 35K+ GitHub Stars)

| 항목 | 내용 |
|------|------|
| **GitHub** | `RVC-Boss/GPT-SoVITS` |
| **아키텍처** | GPT (텍스트→시맨틱 토큰) + SoVITS (시맨틱→오디오) |
| **핵심 기능** | **5초 레퍼런스 오디오만으로 보이스 클로닝** |
| **한국어** | ✅ v2에서 한국어/일본어/영어/중국어/광둥어 공식 지원 |
| **감정 제어** | ✅ 레퍼런스 오디오의 감정을 반영 |
| **실시간성** | △ 2~5초 (GPU에 따라 다름, RTX 4090: ~1.5초) |
| **VRAM** | 4GB+ (추론), 8GB+ (학습) |
| **라이선스** | MIT |
| **API 서버** | ✅ 내장 WebUI + API 서버 (`api_v2.py`) |

**GPT-SoVITS v2 API 엔드포인트**:
```
POST /tts
{
  "text": "안녕하세요",
  "text_lang": "ko",
  "ref_audio_path": "/path/to/reference.wav",   // 5초 레퍼런스
  "prompt_text": "레퍼런스 오디오의 텍스트",
  "prompt_lang": "ko",
  "top_k": 5,
  "top_p": 1.0,
  "temperature": 1.0,
  "speed_factor": 1.0,
  "media_type": "wav",          // wav, raw, ogg, aac
  "streaming_mode": true,        // ✅ 스트리밍 지원
  "parallel_infer": true,
  "repetition_penalty": 1.35
}
→ Response: audio/wav (chunked streaming)
```

**감정 제어 방식 (핵심!)**:
```
GPT-SoVITS는 "레퍼런스 오디오"의 감정을 복사한다.
→ 감정별 레퍼런스 오디오를 미리 준비하면 됨!

캐릭터 "Mao"의 감정별 레퍼런스:
├── ref_neutral.wav   → "평범한 톤으로 말하는 5초 샘플"
├── ref_joy.wav       → "밝고 활기찬 톤으로 말하는 5초 샘플"
├── ref_anger.wav     → "화가 난 톤으로 말하는 5초 샘플"
├── ref_sadness.wav   → "슬프고 조용한 톤으로 말하는 5초 샘플"
├── ref_fear.wav      → "불안하고 떨리는 톤으로 말하는 5초 샘플"
├── ref_surprise.wav  → "놀라고 흥분한 톤으로 말하는 5초 샘플"
├── ref_disgust.wav   → "불쾌한 톤으로 말하는 5초 샘플"
└── ref_smirk.wav     → "장난스러운 톤으로 말하는 5초 샘플"
```

**학습 파이프라인**:
```
[Zero-Shot] 레퍼런스 오디오 5초만으로 즉시 사용 (품질: ★★★★)
[Few-Shot]  레퍼런스 3~10개 + 파인튜닝 없이 (품질: ★★★★★)
[Fine-Tune] 1~30분 학습 데이터 + SoVITS/GPT 파인튜닝 (품질: ★★★★★+)

파인튜닝 과정:
1. 오디오 수집 (1~30분)
2. UVR5로 보컬 분리 + 노이즈 제거
3. Whisper로 자동 전사
4. ASR 결과 교정
5. SoVITS 모델 학습 (~30분, RTX 3060)
6. GPT 모델 학습 (~30분, RTX 3060)
7. 추론 테스트
```

**Docker 배포**:
```yaml
gpt-sovits:
  image: breakstring/gpt-sovits:latest
  ports:
    - "9880:9880"   # WebUI
    - "9871:9871"   # API v2
  volumes:
    - ./gpt-sovits-data/models:/app/GPT_SoVITS/pretrained_models
    - ./gpt-sovits-data/output:/app/output
    - ./gpt-sovits-data/references:/app/references
  deploy:
    resources:
      reservations:
        devices:
          - capabilities: [gpu]
  environment:
    - is_share=false
```

---

### 3.2 Fish Speech 1.5 (⭐ 16K+ GitHub Stars)

| 항목 | 내용 |
|------|------|
| **GitHub** | `fishaudio/fish-speech` |
| **아키텍처** | VQGAN + Transformer (LLAMA 스타일) |
| **핵심 기능** | 10초 레퍼런스로 보이스 클로닝, **매우 빠른 추론** |
| **한국어** | ✅ 양호 |
| **감정 제어** | ✅ 레퍼런스 기반 |
| **실시간성** | ✅ RTF ~0.1 (RTX 4090 기준, 실시간의 10배 빠름) |
| **VRAM** | 2-4GB (추론) |
| **라이선스** | Apache 2.0 + BY-CC-NC-SA-4.0 (모델 가중치) |
| **API** | ✅ OpenAI 호환 API 서버 |

**Fish Speech API (OpenAI 호환)**:
```python
# OpenAI SDK로 그대로 호출 가능!
from openai import OpenAI

client = OpenAI(base_url="http://fish-speech:8080/v1", api_key="not-needed")
response = client.audio.speech.create(
    model="fish-speech-1.5",
    voice="mao_voice",       # 사전 등록된 보이스
    input="안녕하세요!",
    response_format="mp3",
)
```

**장점**: 매우 빠른 추론, OpenAI 호환 API, 적은 VRAM
**단점**: 한국어가 GPT-SoVITS보다 약간 부족, 감정 세밀도 낮음

---

### 3.3 StyleTTS 2 (⭐ 5K+ GitHub Stars)

| 항목 | 내용 |
|------|------|
| **아키텍처** | Diffusion + Style Transfer |
| **핵심 기능** | **사람 수준 자연스러움** (MOS 4.86, 사람과 0.01 차이) |
| **감정 제어** | ✅✅ **스타일 벡터로 감정/톤 정밀 제어** — 오픈소스 최강 |
| **실시간성** | ✅ RTF ~0.06 (매우 빠름) |
| **한국어** | △ 영어 학습 기본, 한국어 파인튜닝 필요 |
| **VRAM** | 2-4GB |
| **보이스 클로닝** | △ 파인튜닝 필요 |
| **라이선스** | MIT |

**감정 제어 (스타일 벡터)**:
```python
# StyleTTS 2의 가장 큰 강점: 스타일 공간에서 감정 보간
import torch

# 감정 레퍼런스 오디오에서 스타일 벡터 추출
style_neutral = model.extract_style("ref_neutral.wav")   # [1, 128]
style_happy = model.extract_style("ref_happy.wav")       # [1, 128]
style_angry = model.extract_style("ref_angry.wav")       # [1, 128]

# 감정 강도 조절 (보간)
style_slightly_happy = 0.7 * style_neutral + 0.3 * style_happy
style_very_happy = 0.2 * style_neutral + 0.8 * style_happy

# 감정 간 부드러운 전환도 가능
style_transition = alpha * style_happy + (1 - alpha) * style_sad
```

**장점**: 감정 정밀 제어 오픈소스 최강, 매우 빠름, 사람 수준 자연스러움
**단점**: 한국어 파인튜닝 필요, API 서버 직접 구축 필요

---

### 3.4 XTTS v2 (Coqui TTS)

| 항목 | 내용 |
|------|------|
| **아키텍처** | GPT-2 + VQ-VAE + HiFi-GAN |
| **핵심 기능** | 6초 레퍼런스로 17개 언어 보이스 클로닝 |
| **한국어** | △ 지원하지만 품질 중간 |
| **감정 제어** | △ 레퍼런스 기반만 |
| **실시간성** | △ RTF ~0.3 (중간) |
| **VRAM** | 4-6GB |
| **라이선스** | CPML (상업적 사용 시 라이선스 필요) |

**장점**: 다국어 원포인트 클로닝
**단점**: 한국어 품질 부족, Coqui 회사 운영 종료, 라이선스 제한

---

### 3.5 Bark (Suno AI)

| 항목 | 내용 |
|------|------|
| **아키텍처** | GPT 기반 (3단계 토크나이저) |
| **핵심 기능** | 웃음, 한숨, 망설임 등 **비언어적 소리**까지 생성 |
| **한국어** | ✅ 양호 |
| **감정 제어** | ✅ 텍스트 프롬프트로 자연스러운 감정 표현 |
| **실시간성** | ✗ RTF ~5.0 (매우 느림) |
| **VRAM** | 8GB+ |
| **라이선스** | MIT |

```python
# Bark의 독특한 감정 표현
text = """
    [laughs] 진짜요?
    [sighs] 아... 그런 일이 있었군요.
    HAHAHA! 너무 웃겨요~
    안녕하세요... [clears throat] 네, 반갑습니다.
"""
```

**장점**: 비언어적 소리 표현 (VTuber에 매력적), MIT 라이선스
**단점**: 매우 느림, 프로덕션 부적합

---

### 3.6 VITS2 / MB-iSTFT-VITS2

| 항목 | 내용 |
|------|------|
| **아키텍처** | VAE + Normalizing Flows + Transformer |
| **핵심 기능** | End-to-End TTS, 한국어 사전 학습 모델 풍부 |
| **한국어** | ✅✅ 한국어 커뮤니티 모델 다수 (KSS, AIHub 등) |
| **실시간성** | ✅✅ RTF ~0.05 (초고속) |
| **VRAM** | 2GB |
| **감정 제어** | △ 파인튜닝으로 가능 |
| **라이선스** | Apache 2.0 |

**장점**: 초고속, 한국어 모델 풍부, 경량
**단점**: 보이스 클로닝 어려움, 감정 제어 제한

---

### 3.7 Edge TTS (Wrapper) / Piper

| Edge TTS | Piper |
|----------|-------|
| MS Edge 서비스 래핑 | 로컬 전용 VITS 기반 |
| 무료 | 무료 |
| 인터넷 필요 | 오프라인 가능 |
| 한국어 우수 | 한국어 모델 부족 |
| RTF ~즉시 | RTF ~0.01 (초고속) |
| CPU만으로 OK | CPU만으로 OK |

---

### 3.8 오픈소스 TTS 종합 비교 매트릭스

| 기준 | GPT-SoVITS | Fish Speech | StyleTTS 2 | XTTS v2 | Bark | VITS2 | Edge TTS |
|------|-----------|-------------|------------|---------|------|-------|----------|
| **음질** | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★ | ★★★★ | ★★★★ | ★★★★ |
| **한국어** | ★★★★★ | ★★★★ | ★★★ | ★★★ | ★★★★ | ★★★★★ | ★★★★ |
| **감정 제어** | ★★★★ | ★★★ | ★★★★★ | ★★★ | ★★★★ | ★★ | ★★ |
| **보이스 클로닝** | ★★★★★ | ★★★★★ | ★★★ | ★★★★ | ★★ | ★★ | ✗ |
| **추론 속도** | ★★★ | ★★★★★ | ★★★★★ | ★★★ | ★ | ★★★★★ | ★★★★★ |
| **VRAM 요구** | 4GB+ | 2-4GB | 2-4GB | 4-6GB | 8GB+ | 2GB | 0 |
| **설치 난이도** | ★★★ | ★★★★ | ★★ | ★★★ | ★★★★ | ★★★ | ★★★★★ |
| **API 서버** | ✅ 내장 | ✅ OpenAI 호환 | △ 직접 구축 | ✅ | △ | △ | ✅ pip |
| **라이선스** | MIT | Apache+CC | MIT | CPML | MIT | Apache | 무료(비공식) |

---

## 4. VTuber 캐릭터 음성 전략

### 4.1 감정별 보이스 시스템 설계

현재 GenY의 EmotionExtractor는 8개 감정을 지원:

```
neutral, joy, anger, fear, sadness, surprise, disgust, smirk
```

**각 TTS 엔진별 감정 매핑 전략**:

| 감정 | Cloud (SSML/파라미터) | GPT-SoVITS (레퍼런스) | StyleTTS 2 (스타일 벡터) |
|------|----------------------|----------------------|------------------------|
| neutral | 기본 파라미터 | ref_neutral.wav | style_neutral |
| joy | pitch +5%, rate +10% | ref_joy.wav | 0.2·neutral + 0.8·joy |
| anger | pitch +2%, rate +20%, vol +3dB | ref_anger.wav | style_angry |
| fear | pitch +8%, rate +30% | ref_fear.wav | 0.3·neutral + 0.7·fear |
| sadness | pitch -5%, rate -10%, vol -2dB | ref_sadness.wav | style_sad |
| surprise | pitch +10%, rate +20% | ref_surprise.wav | style_surprise |
| disgust | pitch -2%, rate -5% | ref_disgust.wav | style_disgust |
| smirk | pitch +2%, rate +5% | ref_smirk.wav | 0.5·joy + 0.5·playful |

### 4.2 캐릭터-보이스 프로필 구조

```json
{
  "voice_profiles": {
    "mao_pro_voice": {
      "display_name": "Mao Pro 보이스",
      "linked_model": "mao_pro",
      "language": "ko",
      "engine_configs": {
        "edge_tts": {
          "voice_id": "ko-KR-SunHiNeural",
          "rate": "+0%",
          "pitch": "+0Hz"
        },
        "openai": {
          "voice": "nova",
          "model": "tts-1"
        },
        "elevenlabs": {
          "voice_id": "custom_mao_voice_id",
          "model_id": "eleven_multilingual_v2"
        },
        "gpt_sovits": {
          "refer_wav_path": "/references/mao_pro/",
          "emotion_refs": {
            "neutral": "ref_neutral.wav",
            "joy": "ref_joy.wav",
            "anger": "ref_anger.wav",
            "sadness": "ref_sadness.wav",
            "fear": "ref_fear.wav",
            "surprise": "ref_surprise.wav",
            "disgust": "ref_disgust.wav",
            "smirk": "ref_smirk.wav"
          },
          "prompt_text": "안녕하세요, 저는 마오입니다.",
          "prompt_lang": "ko"
        },
        "fish_speech": {
          "reference_id": "mao_voice_v1"
        }
      }
    }
  }
}
```

---

## 5. 립싱크 연동 분석

### 5.1 TTS 엔진별 립싱크 데이터 제공 현황

| 엔진 | 립싱크 데이터 | 활용 방법 |
|------|--------------|----------|
| **Azure** | ✅ Viseme ID + 타임스탬프 | 직접 매핑 (최고 품질) |
| **Edge TTS** | △ WordBoundary (단어 단위) | 단어 타이밍 기반 진폭 추정 |
| **ElevenLabs** | △ alignment (단어 단위) | 유사하게 활용 |
| **OpenAI** | ✗ 없음 | 진폭 기반만 가능 |
| **Google** | △ Timepoint (SSML 마크) | 제한적 활용 |
| **GPT-SoVITS** | ✗ 없음 | 진폭 기반 |
| **Fish Speech** | ✗ 없음 | 진폭 기반 |

### 5.2 립싱크 단계별 전략

```
[Level 1] 진폭 기반 (모든 엔진 호환)
  Web Audio AnalyserNode → RMS → ParamMouthOpenY
  품질: ★★★ | 구현: ★ 쉬움

[Level 2] WordBoundary 활용 (Edge TTS/ElevenLabs)
  단어 타이밍 + 진폭 결합 → 더 자연스러운 입 움직임
  품질: ★★★★ | 구현: ★★ 중간

[Level 3] Viseme 기반 (Azure)
  Viseme ID → Live2D 파라미터 매핑 (입모양 정확)
  품질: ★★★★★ | 구현: ★★★ 높음
```

---

## 6. 핵심 결론 및 추천

### 6.1 TTS 엔진 선정 우선순위

```
┌─────────────────────────────────────────────────────────────┐
│  1순위 (MVP - 즉시 구현 가능)                                 │
│  ├── Edge TTS       : 무료, 빠름, 한국어 양호                │
│  └── OpenAI TTS     : 간단한 API, 고품질 백업                │
│                                                              │
│  2순위 (프로덕션 품질)                                         │
│  ├── GPT-SoVITS     : 보이스 클로닝 + 감정 제어 최강         │
│  └── ElevenLabs     : 클라우드 고품질 (비용 여유 시)          │
│                                                              │
│  3순위 (고급 옵션)                                            │
│  ├── Azure Speech   : Viseme 립싱크 + 감정 SSML             │
│  ├── Fish Speech    : 빠른 추론 + OpenAI 호환 API           │
│  └── Google Cloud   : SSML 세밀 제어                         │
│                                                              │
│  4순위 (실험적)                                               │
│  ├── StyleTTS 2     : 감정 정밀 제어 (한국어 파인튜닝 필요)   │
│  └── VITS2          : 초경량 (커스텀 모델 필요)              │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 핵심 발견

1. **GPT-SoVITS가 VTuber TTS의 최적해** — 5초 레퍼런스로 보이스 클로닝 + 감정별 레퍼런스로 감정 제어
2. **Edge TTS가 최고의 MVP** — 무료, 즉시 사용 가능, 충분한 한국어 품질
3. **설정 시스템(`@register_config`)으로 엔진 교체를 매우 쉽게** 구현 가능
4. **감정 태그 시스템이 이미 존재**하므로 TTS 감정 매핑에 직접 활용 가능
5. **립싱크는 진폭 기반으로 시작**, Azure Viseme으로 고도화 가능

---

*다음 문서: [02_TTS_시스템_설계서.md](02_TTS_시스템_설계서.md)*
