# GPT-SoVITS TTS 무음 문제 심층 분석 리포트

> 2026-04-01 | `/api/tts/agents/{session_id}/speak` → 200 OK, 응답 본문 비어 있음

---

## 1. 증상 요약

| 항목 | 값 |
|------|-----|
| Request URL | `POST /api/tts/agents/{session_id}/speak` |
| Status Code | **200 OK** |
| Response Headers | `Content-Type: audio/mpeg`, `X-TTS-Engine: gpt_sovits` |
| Response Body | **비어 있음 (0 bytes)** |
| GPT-SoVITS 컨테이너 로그 | **완전히 비어 있음** (요청이 한 번도 도달하지 않음) |
| 오디오 출력 | **없음** |

---

## 2. 요청 흐름 추적

```
Frontend (ttsApi.speak)
  → POST /api/tts/agents/{id}/speak
  → tts_controller.speak()
  → StreamingResponse(audio_generator())
       └─ TTSService.speak()
            ├─ TTSGeneralConfig 로드 (provider = "gpt_sovits")
            ├─ GPTSoVITSEngine.health_check() ← ❌ 실패
            ├─ EdgeTTSEngine.health_check() (fallback) ← ❌ 실패 가능
            └─ return (빈 제너레이터) → 200 OK + 0 bytes
```

---

## 3. 근본 원인 분석 (7가지)

### 🔴 Critical #1: `media_type: "mp3"` — GPT-SoVITS가 mp3를 지원하지 않음

**파일**: `service/vtuber/tts/engines/gpt_sovits_engine.py:58`

```python
payload = {
    ...
    "media_type": request.audio_format.value,  # → "mp3"
    ...
}
```

**GPT-SoVITS API v2에서 지원하는 `media_type`**: `"wav"`, `"raw"`, `"ogg"`, `"aac"` 만 지원.
`"mp3"`를 보내면 **400 에러**를 반환함.

**`TTSGeneralConfig.audio_format`** 기본값이 `"mp3"`이고, `AudioFormat.MP3`로 변환되어 `request.audio_format.value = "mp3"`가 됨.

---

### 🔴 Critical #2: `api_url` Docker 네트워크 주소 불일치

**파일**: `service/config/sub_config/tts/gpt_sovits_config.py:21`

```python
api_url: str = "http://localhost:9871"  # ← 기본값
```

**문제**: Backend 컨테이너 안에서 `localhost`는 Backend 컨테이너 자신을 가리킴.
GPT-SoVITS는 별도 컨테이너(`geny-gpt-sovits-dev`)에서 실행되므로, Docker 네트워크 DNS를 사용해야 함.

**올바른 값**: `http://gpt-sovits:9871`

사용자가 설정 UI에서 변경하지 않았다면, health_check에서 `GET http://localhost:9871/`이 Backend 컨테이너 내부로 요청되어 실패함.

---

### 🔴 Critical #3: `enabled: false` 기본값

**파일**: `service/config/sub_config/tts/gpt_sovits_config.py:19`

```python
enabled: bool = False  # ← 기본값이 비활성화
```

`GPTSoVITSEngine.health_check()`에서:
```python
if not config.enabled:
    return False  # ← 즉시 False 반환, 서버에 연결 시도조차 안 함
```

이것이 GPT-SoVITS 컨테이너 로그가 완전히 비어 있는 **직접적 원인**.

---

### 🟡 Critical #4: 레퍼런스 오디오 `.wav` 파일 부재

**디렉토리**: `backend/static/voices/mao_pro/`

```
mao_pro/
  └── profile.json       ← 메타데이터만 있음
  └── (ref_neutral.wav)  ← 없음!
  └── (ref_joy.wav)      ← 없음!
  ...
```

`profile.json`은 8개 감정별 `.wav` 파일을 참조하지만, 실제 `.wav` 파일이 하나도 없음.
GPT-SoVITS는 **reference audio가 필수**이므로 이 파일들이 없으면 합성 불가.

---

### 🟡 Critical #5: `ref_audio_path` 경로 아키텍처 결함

**파일**: `service/vtuber/tts/engines/gpt_sovits_engine.py:135-148`

```python
def _get_emotion_ref(self, emotion: str, config) -> str:
    ref_dir = config.ref_audio_dir      # Backend 컨테이너 기준 경로
    emotion_file = f"ref_{emotion}.wav"
    full_path = os.path.join(ref_dir, emotion_file)
    if os.path.exists(full_path):       # ← Backend 컨테이너에서 파일 존재 확인
        return full_path                # ← 이 경로를 GPT-SoVITS API에 그대로 전송
```

**이중 문제**:
1. `os.path.exists()` → Backend 컨테이너 파일시스템에서 확인
2. 반환된 경로 → GPT-SoVITS 컨테이너 API에 전송 (다른 파일시스템)

**Docker 볼륨 매핑 비교**:
| 컨테이너 | 볼륨 | 컨테이너 내 경로 |
|-----------|-------|-------------------|
| Backend | `./backend:/app` | `/app/static/voices/mao_pro/` |
| GPT-SoVITS | `./backend/static/voices:/app/references:ro` | `/app/references/mao_pro/` |

Backend에서 확인하는 경로와 GPT-SoVITS에서 사용하는 경로가 다름.

---

### 🟠 Issue #6: Health Check 엔드포인트 오류

**파일**: `service/vtuber/tts/engines/gpt_sovits_engine.py:112`

```python
resp = await self._client.get(f"{config.api_url}/", timeout=5.0)
return resp.status_code == 200
```

GPT-SoVITS API v2에는 `GET /` 루트 엔드포인트가 정의되어 있지 않음.
FastAPI 기본은 404 반환 → `health_check()` 실패.
**올바른 체크 방법**: `GET /tts?text=test&text_lang=ko&...` 같은 유효 엔드포인트를 사용하거나, `GET /docs` (FastAPI 자동 생성) 사용.

---

### 🟠 Issue #7: Silent Failure (200 OK + 빈 바디)

**파일**: `service/vtuber/tts/tts_service.py:95-100`

```python
if not await engine.health_check():
    engine = self._engines.get("edge_tts")
    if not engine or not await engine.health_check():
        logger.error("All TTS engines unavailable")
        return  # ← 빈 async generator → 200 OK + 0 bytes
```

**컨트롤러**: `StreamingResponse(audio_generator())` — 제너레이터가 아무것도 yield하지 않아도 200 OK 반환.

**클라이언트**: `AudioManager.playTTSResponse()`에서 `response.ok = true`이므로 에러로 처리하지 않음.
빈 Blob으로 Audio 엘리먼트를 만들고, `audio.play()` 호출 시 재생할 데이터가 없어 아무 소리도 안 남.

---

## 4. 실패 흐름 전체 시퀀스

```
1. 프론트엔드 → POST /speak { text: "...", emotion: "joy" }
2. tts_controller → TTSGeneralConfig.provider = "gpt_sovits"
3. TTSService.speak() → self.get_engine("gpt_sovits")
4. GPTSoVITSEngine.health_check():
   a. GPTSoVITSConfig.enabled = False → return False  ← ❌ 여기서 즉시 실패
   (만약 enabled=True라도)
   b. GET http://localhost:9871/ → 연결 실패 (Docker 네트워크 문제) ← ❌
   (만약 api_url이 올바라도)
   c. GET http://gpt-sovits:9871/ → 404 (루트 엔드포인트 없음) ← ❌
5. Fallback → edge_tts.health_check() → 성공/실패 (네트워크 의존)
6. 최종: 빈 제너레이터 또는 edge_tts 오디오 반환
7. StreamingResponse → 200 OK + (빈 바디 또는 edge_tts 오디오)
8. X-TTS-Engine 헤더는 config 값("gpt_sovits")을 반환 → 실제 사용 엔진과 무관
```

---

## 5. 해결 방안

### Phase 1: 즉시 수정 (코드 변경)

| # | 파일 | 수정 내용 |
|---|------|-----------|
| F1 | `gpt_sovits_engine.py` | `media_type`를 GPT-SoVITS 지원 포맷(`wav`)으로 강제 변환 |
| F2 | `gpt_sovits_config.py` | Docker 환경 기본 `api_url`을 `http://gpt-sovits:9871`로 변경 |
| F3 | `gpt_sovits_engine.py` | Health check를 `GET /tts` 대신 `GET /docs` 또는 TCP connect로 변경 |
| F4 | `gpt_sovits_engine.py` | `ref_audio_path`를 GPT-SoVITS 컨테이너 기준 경로로 변환하는 로직 추가 |
| F5 | `tts_service.py` | Silent failure 대신, 빈 응답 시 에러 정보를 포함하도록 개선 |
| F6 | `tts_controller.py` | 빈 오디오 스트림일 때 적절한 에러 응답 (4xx) 반환 |

### Phase 2: 레퍼런스 오디오 준비

사용자가 GPT-SoVITS용 레퍼런스 오디오 `.wav` 파일을 `backend/static/voices/mao_pro/`에 추가해야 함.

---

## 6. 영향도/우선순위 매트릭스

| 원인 | 심각도 | 수정 난이도 | 순서 |
|------|--------|-------------|------|
| `enabled: false` | 🔴 Critical | Low (config) | 1 |
| `api_url` 주소 | 🔴 Critical | Low (config) | 2 |
| `media_type: mp3` 미지원 | 🔴 Critical | Low (코드) | 3 |
| Health check 엔드포인트 | 🟠 High | Low (코드) | 4 |
| `ref_audio_path` 아키텍처 | 🟡 High | Medium (코드) | 5 |
| Silent failure | 🟠 High | Medium (코드) | 6 |
| 레퍼런스 오디오 파일 부재 | 🟡 Medium | 수동 (사용자) | 7 |
