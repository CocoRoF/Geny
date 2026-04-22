# Cycle 20260422_OmniVoice — OmniVoice 이식 · 신규 TTS 마이크로서비스 도입

**사이클 시작.** 2026-04-22 (X5F 종료 직후, GPT-SoVITS 이미지 의존 제거 작업의 출발점).
**대상 범위.** Geny 모노레포 (`backend/`, `frontend/`, `docker-compose*.yml`),
신규 추가될 `omnivoice/` 서브프로젝트, 신규 백엔드 어댑터
`backend/service/vtuber/tts/engines/omnivoice_engine.py`,
신규 Config `service/config/sub_config/tts/omnivoice_config.py`,
voice profile 디렉터리 규약 확장.
**선행.** 현재 docker-compose 스택은 [xxxxrt666/gpt-sovits](https://hub.docker.com/r/xxxxrt666/gpt-sovits)
이미지를 `--profile tts-local` 로 띄워 [`GPTSoVITSEngine`](../../backend/service/vtuber/tts/engines/gpt_sovits_engine.py)
가 HTTP `POST /tts` 로 호출하는 구조. 이미지 자체에 npp/torchaudio 호환성
패치를 매번 컨테이너 시작 시 `pip install` 로 우회해야 하고
([docker-compose.yml](../../docker-compose.yml#L131)), webui/api 두 프로세스가
한 컨테이너에서 백그라운드 실행되며, 모델 가중치는 외부 `/workspace/models`
바인드 마운트에 의존한다. 이 모든 우회는 *우리가 이미지 내부 소스에 손을
댈 수 없다는 한 가지 제약*에서 파생된다.

## 배경 — 왜 OmniVoice 로 가는가

### 현 GPT-SoVITS 통합의 통증 지점

| # | 통증 | 근거 |
|---|---|---|
| 1 | **소스 부재.** 이미지만 사용 → 코드 수정 / 패치 / 디버깅 불가. 버그 발생 시 upstream 의존. | [docker-compose.yml#L122](../../docker-compose.yml#L122) `image: xxxxrt666/gpt-sovits:latest-cu126` |
| 2 | **컨테이너 시작 시 런타임 패치.** `nvidia-npp-cu12` 설치, `torchaudio==2.10.0` 강제 재설치, 가중치 심볼릭 링크 재생성 — 매 부팅마다 수십 초 소요. | [docker-compose.yml#L132-L142](../../docker-compose.yml#L132) |
| 3 | **두 프로세스 동거.** `webui.py &` + `api_v2.py` — graceful shutdown 어려움, 한쪽 죽어도 init 가 살림. | [docker-compose.yml#L143-L144](../../docker-compose.yml#L143) |
| 4 | **단일 GPU 직렬화.** 어댑터에 모듈 레벨 `_synthesis_lock` 으로 *우리 쪽에서* 직렬화. 큐 깊이/타임아웃 제어 불가. | [gpt_sovits_engine.py#L29](../../backend/service/vtuber/tts/engines/gpt_sovits_engine.py#L29) |
| 5 | **언어 지원의 한계.** v2 가 ko/en/zh/ja/yue 5종. 더 다양한 다국어 VTuber 페르소나에 대응 어려움. | [gpt_sovits_engine.py#L294-L300](../../backend/service/vtuber/tts/engines/gpt_sovits_engine.py#L294) `_lang_to_sovits` |
| 6 | **emotion = "ref_audio 파일 교체"라는 우회.** 감정마다 별도 wav 를 미리 녹음/등록해야 함. 즉석 톤 변경 불가. | [profile.json](../../backend/static/voices/paimon_ko/profile.json) `emotion_refs` |
| 7 | **이미지 cu126 핀.** GPU 드라이버 / CUDA 업그레이드 시 호환성 깨짐 위험. | [docker-compose.yml#L122](../../docker-compose.yml#L122) |
| 8 | **API 컨트랙트 불투명.** 우리가 호출하는 `POST /tts` 의 v2 schema 가 upstream 변경되면 무방비. | [gpt_sovits_engine.py#L84-L99](../../backend/service/vtuber/tts/engines/gpt_sovits_engine.py#L84) |

### OmniVoice 채택의 명분

[k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) (Apache-2.0, 2026
공개) 는 다음 특성을 가진다 — 모두 위 통증을 정면으로 해결한다.

| 특성 | 이득 |
|---|---|
| **600+ 언어 zero-shot.** | 통증 #5 해소. 다국어 페르소나 무료 확장. |
| **Voice Design (instruct 문자열).** `"female, low pitch, british accent"` 같은 자연어로 음성 생성. ref audio 불필요. | 통증 #6 의 근본 해결 — 감정마다 wav 미리 녹음할 필요 없이 instruct 변경만으로 톤 변화. |
| **Voice Cloning.** 3~10초 ref audio 로 zero-shot 클로닝. ref_text 자동(Whisper) 가능. | 기존 paimon_ko / mao_pro 등 voice profile 재활용 가능. |
| **순수 Python 패키지.** `pip install omnivoice` 또는 `uv sync`. 소스 클론·편집 가능. | 통증 #1, #2 해소. *우리가 소스를 가진다.* |
| **`OmniVoice.from_pretrained()` 단일 진입점.** | 통증 #3 해소 — 단일 프로세스. |
| **HuggingFace 모델 (`k2-fsa/OmniVoice`).** | 통증 #7 완화 — torch / cuda 버전 자유. |
| **Apache-2.0.** | 우리가 fork·개선·재배포 가능. |
| **CLI 3종 + Gradio demo + Python API.** | demo.py 로 빠른 수동 검증, infer.py 로 batch 검증. |
| **RTF 0.025 (40× 실시간).** | GPT-SoVITS 대비 동등 이상 추론 속도. |

### 비목적 — 본 사이클에서 *하지 않는 것*

- **GPT-SoVITS 즉시 제거.** 본 사이클 종료 시점에도 `gpt_sovits` 엔진은
  코드/profile에 *그대로 남는다*. OmniVoice 검증 완료 후 *별도 사이클*
  에서 deprecate 한다. 두 엔진이 fallback 체인에 공존.
- **Training / 데이터 준비 파이프라인 이식.** [omnivoice/training/](../../../OmniVoice/omnivoice/training)
  과 [omnivoice/data/](../../../OmniVoice/omnivoice/data) 는 *Geny 의
  배포 산출물에서 제외*. 추론(inference) 코드만 가져온다. fine-tuning
  은 [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) 본가에서.
- **`omnivoice-demo` Gradio UI 노출.** 개발용으로만. 프로덕션 docker-compose
  에서는 비활성. (개발에서는 `--profile tts-debug` 같은 별도 프로파일)
- **Voice profile UI 자동 마이그레이션.** 기존 4개 profile (`ellen_joe`,
  `mao_pro`, `paimon_ko`, `ruan_mei`) 의 OmniVoice 호환 필드 추가는
  *수동* 으로 한다. 마이그레이션 스크립트 작성은 별도 사이클.
- **frontend UI 신설.** TTS 설정 카드는 Config Field 메타데이터만
  추가하면 자동 렌더링되므로 frontend 작업 없음. (필요 시 별도 사이클.)

## OmniVoice 구조 분석

### 패키지 트리

```
OmniVoice/                              ← 현재 /home/geny-workspace/OmniVoice 에 클론됨
├── pyproject.toml                      torch>=2.4, transformers>=5.3, gradio, librosa, soundfile, pydub, accelerate
├── omnivoice/
│   ├── __init__.py                     OmniVoice / OmniVoiceConfig / OmniVoiceGenerationConfig 노출
│   ├── models/omnivoice.py             핵심 모델 (PreTrainedModel 상속, .from_pretrained / .generate)
│   ├── cli/
│   │   ├── infer.py                    omnivoice-infer 단일 합성
│   │   ├── infer_batch.py              omnivoice-infer-batch 멀티 GPU 배치
│   │   ├── demo.py                     omnivoice-demo Gradio UI (포트 7860)
│   │   └── train.py                    [제외 — training]
│   ├── data/                           [제외 — training]
│   ├── eval/                           [제외 — eval, optional]
│   ├── training/                       [제외 — training]
│   ├── scripts/                        [제외 — examples 보조]
│   └── utils/
│       ├── audio.py                    load_audio, remove_silence, fade_and_pad_audio, cross_fade_chunks
│       ├── duration.py                 RuleDurationEstimator
│       ├── lang_map.py                 LANG_IDS, LANG_NAMES, lang_display_name (600+ codes)
│       ├── text.py                     add_punctuation, chunk_text_punctuation
│       ├── voice_design.py             instruct 검증 / EN↔ZH 매핑
│       └── common.py                   str2bool 등
├── docs/                               참고 문서 — 우리 docs/에 일부 가져올 예정
└── examples/                           [제외 — training examples]
```

### 핵심 API 요약 (인용)

```python
# OmniVoice/omnivoice/models/omnivoice.py 발췌
class OmniVoice(PreTrainedModel):
    @classmethod
    def from_pretrained(cls, name_or_path, device_map="cuda:0", dtype=torch.float16): ...

    def generate(
        self,
        text: str,
        ref_audio: str | None = None,    # 클로닝 모드
        ref_text: str | None = None,     # 자동 ASR 가능 (Whisper)
        instruct: str | None = None,     # 디자인 모드: "female, british accent, low pitch"
        language: str | None = None,     # auto-detect 가능
        speed: float = 1.0,
        duration: float | None = None,   # 고정 길이 (speed 무시)
        generation_config: OmniVoiceGenerationConfig = ...,
        voice_clone_prompt: VoiceClonePrompt | None = None,  # 미리 토큰화된 ref
    ) -> list[np.ndarray]:               # (T,) at 24 kHz
```

세 가지 모드가 **`generate()` 한 함수에 통합**되어 있다 — Geny 어댑터에서
모드 분기를 단순화할 수 있다.

### 의존성 무게

`pyproject.toml` 기준:

- **무거운 것.** `torch>=2.4`, `torchaudio>=2.4` (CUDA), `transformers>=5.3`,
  `accelerate`, `librosa`, `soundfile`, `pydub`, `webdataset`, `gradio`,
  `tensorboardX`.
- **공식 모델.** `k2-fsa/OmniVoice` HuggingFace repo, FP16 ≈ 수 GB. 컨테이너
  볼륨에 캐시되어야 함.

→ Backend 컨테이너에 직접 넣으면 Backend 이미지가 수 GB 부풀고 GPU 의존이
생긴다. **별도 마이크로서비스 컨테이너가 필수**. (이미 GPT-SoVITS 도 동일
이유로 분리되어 있음.)

## 현 Geny TTS 아키텍처 정리

```
┌──────────────────────────────────────────────────────────────────────┐
│ Geny Backend                                                         │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ TTSService (singleton)                                         │  │
│  │  ├── EdgeTTSEngine        (free, library 직접 호출)            │  │
│  │  ├── OpenAITTSEngine      (HTTP)                               │  │
│  │  ├── ElevenLabsEngine     (HTTP)                               │  │
│  │  ├── GPTSoVITSEngine      (HTTP → gpt-sovits:9880)             │  │
│  │  └── (NEW) OmniVoiceEngine (HTTP → omnivoice:9881)             │  │
│  │   ↓ provider 선택은 TTSGeneralConfig.provider 가 결정           │  │
│  │   ↓ 실패 시 edge_tts 로 fallback                                │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  Config (DB-backed): tts_general / tts_gpt_sovits / tts_omnivoice ...│
│  Voice profiles: backend/static/voices/<name>/{ref_*.wav, profile.json}│
└──────────────────────────────────────────────────────────────────────┘
                                 │ HTTP
┌──────────────────┬─────────────┴──────────────────┬──────────────────┐
│ gpt-sovits       │ (NEW) omnivoice                │ edge / openai /  │
│ docker container │ docker container               │ elevenlabs       │
│ profile=tts-local│ profile=tts-local              │ (외부 SaaS)      │
└──────────────────┴────────────────────────────────┴──────────────────┘
```

### 어댑터 계약 — TTSEngine ABC

[`base.py`](../../backend/service/vtuber/tts/base.py) 의 `TTSEngine` 추상은
단순하다. 새 엔진 추가의 **유일한 의무**는:

```python
class TTSEngine(ABC):
    engine_name: str

    @abstractmethod
    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]: ...

    @abstractmethod
    async def get_voices(self, language: Optional[str] = None) -> list[VoiceInfo]: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
```

`TTSRequest` 가 운반하는 필드는 `text / emotion / language / speed /
pitch_shift / audio_format / sample_rate / voice_profile`. **emotion** 은
이미 General Config 의 emotion-speed/pitch 매핑으로 변환된 후 전달된다.

→ OmniVoiceEngine 은 *완전히 같은 계약* 위에 얹는다. 새 모드(instruct)
를 위해 추가 필드가 필요한 경우 `voice_profile` 의 의미를 확장한다.

## 목표 아키텍처 — Monorepo 통합

### 모노레포 새 디렉터리

```
Geny/
├── backend/                            (기존)
├── frontend/                           (기존)
├── omnivoice/                          ★ NEW — 마이크로서비스 (backend/frontend 와 동급)
│   ├── Dockerfile
│   ├── pyproject.toml                  fork 한 OmniVoice 의 의존성 + FastAPI 추가
│   ├── README.md
│   ├── README_KO.md
│   ├── server/                         ★ Geny 가 추가한 FastAPI 래퍼
│   │   ├── __init__.py
│   │   ├── main.py                     FastAPI app, lifespan에서 모델 로드
│   │   ├── api.py                      POST /tts, GET /voices, GET /health
│   │   ├── schemas.py                  Pydantic request/response
│   │   ├── settings.py                 환경변수 로드 (모델 path, device, dtype)
│   │   └── streaming.py                청크 인코딩 (wav/mp3/ogg/pcm)
│   ├── omnivoice_core/                 ★ upstream 에서 *복사* 한 추론 코드
│   │   ├── __init__.py                 OmniVoice / OmniVoiceConfig 재노출
│   │   ├── models/
│   │   │   └── omnivoice.py            (그대로 복사)
│   │   └── utils/                      audio.py, lang_map.py, text.py, voice_design.py, duration.py, common.py
│   ├── voices/                         ★ 컨테이너 내부 ref-audio mount 지점
│   │                                   (실제 데이터는 backend/static/voices 와 공유 볼륨)
│   ├── docs/
│   │   ├── architecture.md
│   │   ├── api_contract.md
│   │   ├── voice_profile_format.md
│   │   └── upstream_sync.md            upstream OmniVoice 와 동기화 전략
│   └── tests/
│       ├── test_api_smoke.py
│       └── test_engine_loading.py
└── docker-compose*.yml                 (수정: omnivoice 서비스 추가)
```

### 왜 `omnivoice_core/` 와 `server/` 를 분리하나

1. **Upstream 동기화.** `omnivoice_core/` 는 [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)
   의 `omnivoice/` 와 *1:1 대응*. upstream 새 버전이 나오면 디렉터리 교체
   + diff 리뷰만으로 갱신. 우리 fork 라기보단 *bundled vendored copy*.
2. **우리 코드의 격리.** `server/` 는 Geny 가 100% 소유. FastAPI / 스트리밍
   / 설정 / 로깅 / 메트릭 등 *우리만의 개선*은 모두 여기에.
3. **테스트 경계.** `server/` 는 mock OmniVoice 로 단위 테스트 가능.

### 왜 `tools/` 가 아니라 `server/` 로 부르나

Geny 의 backend 도 `controller/`, `service/`, `routers/`, `mcp/` 식으로
역할 기반 폴더를 쓴다. `server/` 는 "이 컨테이너의 HTTP 서버 진입점"이라는
역할을 직관적으로 표현한다.

## 마이그레이션 — 점진 단계 (Pure Additive)

본 사이클의 **불변식**: *기존 GPT-SoVITS 경로를 한 줄도 망가뜨리지 않는다.*
모든 변경은 *순수 추가 (additive)*. 두 엔진이 docker-compose 와 코드에
공존하며, `tts_general.provider` 값으로 전환된다.

### Phase 0 — 사전 점검 (코드 변경 없음)

- [ ] 호스트에 NVIDIA GPU + driver 확인 (CUDA 12.x). OmniVoice 모델 로드
      검증을 위해 `OmniVoice/` 클론된 디렉터리에서 `uv sync && uv run python -c "from omnivoice import OmniVoice; m = OmniVoice.from_pretrained('k2-fsa/OmniVoice')"` 실행 — *호스트* 에서.
- [ ] HuggingFace 캐시 위치 결정. 컨테이너 볼륨 `geny-omnivoice-models`
      예약. 모델 ≈ 수 GB.
- [ ] 한국어 합성 품질 *수동* 평가 — `omnivoice-demo --port 7860` 띄워
      현 paimon_ko/mao_pro 의 ref_neutral.wav 로 클로닝 테스트. **PASS
      판정 없이 Phase 1 진행 금지.**

### Phase 1 — `omnivoice/` 디렉터리 골격 (Geny 모노레포에 추가)

- [ ] `Geny/omnivoice/` 생성. 위 트리 그대로.
- [ ] `omnivoice_core/` 에 upstream 의 다음 파일을 *복사*:
  - `omnivoice/__init__.py` → 이름만 `omnivoice_core/__init__.py` 로
  - `omnivoice/models/omnivoice.py` → `omnivoice_core/models/omnivoice.py`
  - `omnivoice/utils/{audio,duration,lang_map,text,voice_design,common}.py`
  - 내부 import 경로 `omnivoice.utils.X` → `omnivoice_core.utils.X` 일괄 치환
- [ ] **복사 *제외*:** `cli/`, `data/`, `eval/`, `training/`, `scripts/`,
  `examples/`. (Gradio demo 는 server 가 대체.)
- [ ] `pyproject.toml` 작성 — upstream 의 `[project] dependencies` 그대로
      + `fastapi>=0.115`, `uvicorn[standard]>=0.32`, `python-multipart`,
      `httpx`, `pydantic>=2.0`, `pydantic-settings`. **`gradio` 제거.**
- [ ] `README.md` / `README_KO.md` — Geny 컨텍스트의 사용법 + upstream
      참고 링크.

**완료 기준:** `cd Geny/omnivoice && uv sync && uv run python -c "from
omnivoice_core import OmniVoice; print('ok')"` 가 호스트에서 PASS.

### Phase 2 — FastAPI 서버 구현 (`server/`)

- [ ] `server/settings.py` — 환경변수: `OMNIVOICE_MODEL`, `OMNIVOICE_DEVICE`,
      `OMNIVOICE_DTYPE`, `OMNIVOICE_HOST`, `OMNIVOICE_PORT`, `OMNIVOICE_VOICES_DIR`,
      `OMNIVOICE_HF_CACHE`, `OMNIVOICE_LOG_LEVEL`, `OMNIVOICE_AUTO_ASR` (Whisper
      사용 여부), `OMNIVOICE_MAX_CONCURRENCY` (단일 GPU 직렬화 정도).
- [ ] `server/main.py` — FastAPI app, `lifespan` 에서 OmniVoice 로드 +
      asyncio.Semaphore 초기화.
- [ ] `server/schemas.py`:
  ```python
  class TTSRequest(BaseModel):
      text: str
      mode: Literal["clone", "design", "auto"] = "auto"
      ref_audio_path: Optional[str] = None        # 컨테이너 내부 절대경로
      ref_text: Optional[str] = None              # None 이면 Whisper 자동
      instruct: Optional[str] = None              # design 모드
      language: Optional[str] = None              # None=auto-detect
      speed: float = 1.0
      duration: Optional[float] = None
      num_step: int = 32
      guidance_scale: float = 2.0
      audio_format: Literal["wav", "mp3", "ogg", "pcm"] = "wav"
      sample_rate: int = 24000
      streaming: bool = False                     # True 면 chunked transfer
  ```
- [ ] `server/api.py`:
  - `POST /tts` — 위 schema → `model.generate(...)` → wav 인코딩 → 응답.
  - `POST /tts/stream` — 동일 입력, `StreamingResponse(media_type="audio/wav")`.
    OmniVoice 의 `generate()` 는 list[ndarray] 반환이므로 *문장 단위 청크*
    로 yield (whole-audio fallback 가능).
  - `GET /voices` — `OMNIVOICE_VOICES_DIR` 스캔, 디렉터리별 `profile.json`
    파싱. 응답: `[{id, name, language, ref_audios: [{emotion, file}], ...}]`.
  - `GET /health` — 모델 로드 상태 + GPU 가용 + (옵션) 1초 더미 합성 ping.
  - `GET /languages` — `LANG_NAMES` 600+ 노출.
  - `GET /` — 서비스 메타 (version, model id, device).
- [ ] `server/streaming.py` — wav header 생성, mp3/ogg 는 `pydub` 또는
      `soundfile` 사용 (이미 OmniVoice deps 에 포함).
- [ ] **동시성 정책.** `Semaphore(MAX_CONCURRENCY)` 로 GPU 직렬화. Backend
      쪽 모듈 락은 *제거 가능* (서버가 직접 큐잉). 다만 fallback 안전을
      위해 어댑터 락은 첫 사이클에선 유지.

**완료 기준:** `curl -X POST http://localhost:9881/tts -d '{"text":"안녕하세요"}' --output out.wav` 로 음성 생성. `pytest omnivoice/tests/` 통과.

### Phase 3 — Dockerfile

- [ ] `omnivoice/Dockerfile` 작성:
  ```dockerfile
  FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04 AS base
  RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3-pip ffmpeg libsndfile1 curl ca-certificates \
        && rm -rf /var/lib/apt/lists/*
  RUN ln -sf /usr/bin/python3.12 /usr/bin/python
  WORKDIR /app
  COPY pyproject.toml ./
  COPY omnivoice_core/ ./omnivoice_core/
  COPY server/ ./server/
  RUN pip install --no-cache-dir torch==2.8.0 torchaudio==2.8.0 \
        --extra-index-url https://download.pytorch.org/whl/cu128 \
   && pip install --no-cache-dir -e .
  ENV OMNIVOICE_HF_CACHE=/models/hf-cache \
      OMNIVOICE_VOICES_DIR=/voices \
      OMNIVOICE_HOST=0.0.0.0 \
      OMNIVOICE_PORT=9881 \
      HF_HOME=/models/hf-cache \
      PYTHONUNBUFFERED=1
  EXPOSE 9881
  HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fs http://localhost:9881/health || exit 1
  CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "9881"]
  ```
- [ ] `.dockerignore` — `tests/`, `docs/`, `__pycache__/`.

**완료 기준:** `docker build -t geny-omnivoice ./omnivoice` 성공. 컨테이너
단독 실행 후 `/health` 200 OK.

### Phase 4 — docker-compose 통합

3개 compose 파일 모두에 *동일 패턴* 으로 추가. profile = `tts-local`
(GPT-SoVITS 와 동일 — 둘 다 GPU 옵션이라).

- [ ] `docker-compose.yml` (standalone):
  ```yaml
    omnivoice:
      build:
        context: ./omnivoice
        dockerfile: Dockerfile
      image: geny-omnivoice:latest
      container_name: geny-omnivoice
      profiles: ["tts-local"]
      init: true
      restart: unless-stopped
      ports:
        - "127.0.0.1:${OMNIVOICE_PORT:-9881}:9881"
      environment:
        - OMNIVOICE_MODEL=${OMNIVOICE_MODEL:-k2-fsa/OmniVoice}
        - OMNIVOICE_DEVICE=${OMNIVOICE_DEVICE:-cuda:0}
        - OMNIVOICE_DTYPE=${OMNIVOICE_DTYPE:-float16}
        - OMNIVOICE_MAX_CONCURRENCY=${OMNIVOICE_MAX_CONCURRENCY:-1}
        - OMNIVOICE_AUTO_ASR=${OMNIVOICE_AUTO_ASR:-false}
        - HF_ENDPOINT=${HF_ENDPOINT:-https://huggingface.co}
      volumes:
        - geny-voices:/voices:ro
        - geny-omnivoice-models:/models
      shm_size: 8G
      deploy:
        resources:
          reservations:
            devices:
              - driver: nvidia
                count: 1
                capabilities: [gpu]
      networks:
        - geny-net

  volumes:
    geny-omnivoice-models:
      driver: local
  ```
- [ ] `docker-compose.dev.yml` — 동일 + `volumes: - ./omnivoice/server:/app/server`
      로 server 코드 hot-reload + `command: uvicorn server.main:app --reload --host 0.0.0.0 --port 9881`.
      `omnivoice_core/` 는 reload 대상 아님 (모델 코드는 컨테이너 빌드 시 고정).
- [ ] `docker-compose.prod.yml` — standalone 패턴 그대로.
- [ ] `docker-compose.dev-core.yml` / `prod-core.yml` — TTS 비활성 빌드, 변경 없음 (omnivoice 도 `tts-local` profile 이므로 자동 제외).
- [ ] **GPT-SoVITS 서비스는 *그대로 둔다*.** `tts-local` profile 띄우면
      두 서비스가 동시 기동. 단일 GPU 환경에선 *동시 사용 시 OOM* 가능 —
      이 경우 사용자에게 `--profile omnivoice-only` / `--profile sovits-only`
      세분화 profile 추가는 *향후 사이클*. 본 사이클은 두 서비스 공존만
      보장.

**완료 기준:** `docker compose --profile tts-local up -d` 시 `geny-omnivoice`
컨테이너 healthy. `curl http://localhost:9881/health` 200.

### Phase 5 — Backend 어댑터 (`OmniVoiceEngine`)

- [ ] `backend/service/config/sub_config/tts/omnivoice_config.py` 신설:
  ```python
  @register_config
  @dataclass
  class OmniVoiceConfig(BaseConfig):
      enabled: bool = False
      api_url: str = "http://omnivoice:9881"
      mode: str = "clone"                       # clone | design | auto
      voice_profile: str = "paimon_ko"
      instruct: str = ""                        # mode=design 시 사용
      language: str = ""                        # 빈 문자열 = auto-detect
      num_step: int = 32
      guidance_scale: float = 2.0
      speed: float = 1.0
      duration_seconds: float = 0.0             # 0 = speed 사용
      auto_asr: bool = False                    # ref_text 없을 때 Whisper
      audio_format: str = "wav"
      streaming: bool = False
      timeout_seconds: float = 60.0
  ```
  + `get_fields_metadata()` 에 mode 셀렉트, voice_profile 동적 옵션,
  instruct 자유 텍스트, num_step/guidance_scale 슬라이더 등.

- [ ] `backend/service/config/sub_config/tts/tts_general_config.py` —
      `provider` 셀렉트 옵션에 `{"value": "omnivoice", "label": "OmniVoice (Open Source · 600+ langs)"}`
      추가.

- [ ] `backend/service/vtuber/tts/engines/omnivoice_engine.py` 신설:
  ```python
  class OmniVoiceEngine(TTSEngine):
      engine_name = "omnivoice"

      async def synthesize_stream(self, request): ...
      async def get_voices(self, language=None): ...
      async def health_check(self): ...
  ```
  - **모드 결정.** `OmniVoiceConfig.mode` (clone/design/auto) → request.voice_profile
    이 있으면 clone 강제 가능 (voice_profile override 우선).
  - **payload.** clone 모드는 `ref_audio_path` 를 *컨테이너 경로*로 변환
    (`/voices/<profile>/ref_<emotion>.wav`). emotion → 파일 매핑은 GPT-SoVITS
    어댑터의 `_get_emotion_ref()` 패턴을 *재사용*. helper 를 [base.py](../../backend/service/vtuber/tts/base.py)
    근처 신규 모듈로 추출(`engines/_voice_profile.py`)해 두 어댑터가 공유.
  - **ref_text.** profile.json 의 emotion-specific prompt_text 사용. 없으면
    `auto_asr=True` 일 때 ref_text 생략 → 서버측 Whisper.
  - **응답.** wav 바이너리. `TTSChunk(audio_data, is_final=True)` 로 한 번에
    yield (스트리밍은 차후 사이클).
  - **lock.** GPT-SoVITS 와 마찬가지로 모듈 레벨 `asyncio.Lock` 보유 —
    서버측 Semaphore 와 *이중* 으로 안전망.

- [ ] `backend/service/vtuber/tts/tts_service.py#L213-L218` 의 엔진 등록
      목록에 `OmniVoiceEngine()` 추가.

- [ ] `backend/requirements.txt` — *변경 없음*. 어댑터는 `httpx` 만 사용 (이미
      포함). OmniVoice 라이브러리 자체는 backend 에 들어가지 않는다.

**완료 기준:** Geny backend 단위 테스트 + `tts_general.provider="omnivoice"`
설정 + `tts_omnivoice.enabled=true` 로 채팅 메시지가 음성으로 생성됨.
fallback 도 동작 (omnivoice 컨테이너 끄면 edge_tts 로 자동 전환).

### Phase 6 — Voice profile 호환성

기존 `backend/static/voices/<name>/profile.json` 포맷 ([paimon_ko 예시](../../backend/static/voices/paimon_ko/profile.json))
은 GPT-SoVITS 가 도입한 스키마. OmniVoice 도 *같은 ref_audio + ref_text*
규약을 클로닝 모드에서 그대로 활용 가능 → **포맷 변경 불필요**.

추가 (선택):

- `omnivoice_design.instruct` — design 모드 기본 instruct 문자열
- `omnivoice_design.preferred_language` — auto-detect 신뢰 못할 때 강제

미사용 시 default 동작은 GPT-SoVITS 와 동일.

**작업.**
- [ ] `omnivoice/docs/voice_profile_format.md` 에 확장 스키마 명세.
- [ ] backend `omnivoice_engine.py` 에 *역호환 로더* — 새 필드 없으면
      구 동작.

### Phase 7 — 검증 / 테스트

- [ ] `omnivoice/tests/test_api_smoke.py` — FastAPI TestClient 로 `/health`,
      `/voices`, `/tts` (mock model) 응답 검증.
- [ ] `omnivoice/tests/test_engine_loading.py` — `lifespan` 에서 모델 로드
      실패 시 graceful 종료 검증 (mock).
- [ ] `backend/tests/service/vtuber/tts/test_omnivoice_engine.py` — `httpx.MockTransport`
      로 어댑터 단위 테스트 (synthesize_stream, health_check, voice resolution).
- [ ] **수동 시나리오:**
    1. clone 모드 — 4개 기존 profile 모두로 한국어 합성.
    2. design 모드 — `instruct="female, low pitch, japanese accent"` 일본어 합성.
    3. auto 모드 — 영문/일문/중문 텍스트.
    4. fallback — omnivoice 컨테이너 강제 종료 → edge_tts 자동 전환 확인.
    5. 동시성 — 3개 세션 병렬 합성 → 큐잉만 되고 실패 없음.
    6. emotion 체인 — joy/anger/neutral 순환 합성 → ref_audio 가 emotion 별로
       올바르게 선택됨.

### Phase 8 — 문서화 / 사이클 종료

- [ ] `Geny/omnivoice/README.md` — quickstart, env vars, voice profile 규약.
- [ ] `Geny/omnivoice/README_KO.md` — 한국어판.
- [ ] `Geny/docs/` 에 `OmniVoice_INTEGRATION.md` — 운영자용 문서 (provider
      전환, fallback, 트러블슈팅).
- [ ] `dev_docs/20260422_OmniVoice/progress/` 에 PR 별 회고 작성.
- [ ] **GPT-SoVITS deprecate 결정.** OmniVoice 가 모든 manual scenario
      를 PASS 한 후 *별도 사이클* 에서:
    1. compose 의 `gpt-sovits` 서비스를 `profiles: ["tts-legacy"]` 로 격리
    2. README 에 deprecation 공지
    3. 1~2 사이클 grace period
    4. `gpt_sovits_engine.py` / `gpt_sovits_config.py` / 이미지 핀 제거

## 핵심 결정 사항 — Trade-off 명시

| 결정 | 대안 | 채택 이유 |
|---|---|---|
| **마이크로서비스 분리** | backend 컨테이너에 직접 통합 | (1) torch+model = 수 GB → backend 이미지 비대 (2) GPU 의존 분리로 backend 는 CPU 노드에서도 실행 가능 (3) GPT-SoVITS 와 동일 운영 패턴 — 학습곡선 0 |
| **upstream 코드 vendoring (`omnivoice_core/`)** | `pip install omnivoice` 로 PyPI 의존 | (1) 사용자 요구: "소스를 편집" — vendoring 이 편집권의 본질 (2) PyPI 의존 시 우리가 패치하면 fork·재배포 비용 (3) upstream pace 가 빠르므로 *고정 시점 스냅샷* 이 운영 안정성에 유리. 동기화는 분기마다 수동. |
| **FastAPI 래퍼 신설 (`server/`)** | OmniVoice 의 `cli/demo.py` (Gradio) 를 그대로 사용 | (1) Gradio 는 데모용 — 동시성/스트리밍/health-check 표준 부재 (2) Geny 의 다른 엔진 어댑터(`OpenAITTSEngine`, `ElevenLabsEngine`) 들이 모두 HTTP API 호출 패턴 → 일관성 (3) 우리가 추후 metrics/auth/streaming 확장 시 자유 |
| **gradio 의존 제거** | upstream 그대로 | gradio 는 데모용으로만 필요. server 진입점에서 무가치하며 이미지를 무겁게 만듦 |
| **profile 포맷 무변경 + 선택적 확장** | OmniVoice 전용 profile 신설 | 4개 기존 profile 의 마이그레이션 비용 0. instruct 확장은 opt-in |
| **`provider="omnivoice"` 토글로 전환** | gpt_sovits 를 omnivoice alias 로 | 사용자가 *어느 엔진이 활성*인지 알아야 함 (성격 차이 있음). UI 에 둘 다 보이는 게 정직 |
| **fallback 체인은 그대로 edge_tts** | omnivoice → gpt_sovits → edge | 두 GPU 엔진을 fallback 체인에 두면 같은 GPU OOM 시 cascading 실패. SaaS-free 인 edge_tts 가 안전망 |
| **단일 GPU 직렬화는 서버측 Semaphore + 어댑터 Lock 이중** | 서버측만 | 첫 사이클 안전 마진. 안정화 후 어댑터 Lock 제거하는 별도 사이클 |
| **제외: training/data/eval 코드 vendoring** | 전부 복사 | Geny 는 추론 host. 학습은 upstream 에서 — 책임 분리 |
| **포트 9881** | 9880 (GPT-SoVITS 와 동일) | 두 서비스 공존이 가능해야 하므로 포트 충돌 회피 |

## OmniVoice 자체에 가할 수 있는 개선 (오픈소스 기여 후보)

upstream 에 PR 을 보내는 *별도* 작업으로 분리 (본 사이클 비범위), 다만
*기록* 차원에서:

1. **HTTP 서버 진입점 부재.** `omnivoice-server` CLI 가 있다면 우리가
   `server/` 를 안 짜도 됨. → upstream PR 후보.
2. **스트리밍 합성.** `model.generate()` 가 list[ndarray] 만 반환. 청크
   yield 가능한 `generate_stream()` 추가 → upstream PR 후보.
3. **`device` 인자 통일.** `from_pretrained(device_map=...)` 가 transformers
   convention 인데, `device` alias 가 직관적. 사소한 DX 개선.
4. **HF cache 환경변수 표준화 문서.** `HF_HOME` / `HF_ENDPOINT` 사용법을
   README 에.
5. **Voice profile registry 표준.** clone 용 reference 를 `voices/<name>/`
   디렉터리에 넣으면 자동 인식하는 컨벤션. (Geny 의 profile.json 형식이
   참고 사례가 될 수 있음.)

## 환경변수 요약 (Geny 측 추가)

| 변수 | 기본값 | 용도 |
|---|---|---|
| `OMNIVOICE_PORT` | `9881` | 호스트 포트 |
| `OMNIVOICE_MODEL` | `k2-fsa/OmniVoice` | HF repo id 또는 마운트된 절대경로 |
| `OMNIVOICE_DEVICE` | `cuda:0` | 추론 장치 |
| `OMNIVOICE_DTYPE` | `float16` | `float16` / `bfloat16` / `float32` |
| `OMNIVOICE_MAX_CONCURRENCY` | `1` | 동시 추론 슬롯 |
| `OMNIVOICE_AUTO_ASR` | `false` | ref_text 누락 시 Whisper |
| `HF_ENDPOINT` | `https://huggingface.co` | 모델 다운로드 미러 (e.g. `https://hf-mirror.com`) |

## Definition of Done

본 사이클 Ship 조건:

- [ ] `Geny/omnivoice/` 가 모노레포에 추가되어 `docker compose --profile tts-local up`
      시 `geny-omnivoice` 컨테이너가 healthy.
- [ ] `tts_general.provider="omnivoice"` 로 전환 시 채팅 메시지가 음성
      합성됨 (clone / design / auto 세 모드 모두).
- [ ] `tts_general.provider="gpt_sovits"` 로 되돌리면 기존 동작 그대로 —
      regression 0.
- [ ] omnivoice 컨테이너 강제 종료 시 fallback (edge_tts) 동작.
- [ ] `omnivoice/tests/` + `backend/tests/.../test_omnivoice_engine.py` PASS.
- [ ] 수동 검증 시나리오 6종 모두 PASS.
- [ ] `omnivoice/README.md` + `Geny/docs/OmniVoice_INTEGRATION.md` 작성 완료.
- [ ] dev/prod compose 모두 검증.
- [ ] `progress/` 디렉터리에 PR 별 회고 N건.
- [ ] GPT-SoVITS 코드/이미지/profile **그대로 보존** (regression 가드).

## 위험과 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| 한국어 합성 품질이 GPT-SoVITS 대비 열등 | provider 전환 거부 | Phase 0 의 *수동 PASS 판정* 단계 — 통과 못하면 사이클 자체 보류 |
| 단일 GPU 환경에서 omnivoice + gpt-sovits 동시 OOM | 두 엔진 동시 사용 불가 | 둘 중 하나만 띄우는 별도 profile 도입 (다음 사이클). 본 사이클은 *문서로 경고* |
| HuggingFace 다운로드 실패 | 컨테이너 시작 실패 | `HF_ENDPOINT` 미러 지원, 모델 볼륨 영속화로 첫 1회 성공 후 재현 안 됨 |
| upstream OmniVoice breaking change | 차후 sync 시 conflict | `omnivoice_core/` 는 *고정 스냅샷*, 갱신은 *명시적*. `docs/upstream_sync.md` 에 절차 |
| auto-detect language 오인식 → 톤 이상 | 사용자 체감 품질 저하 | OmniVoiceConfig.language 명시 옵션, profile 별 preferred_language |
| backend 어댑터에서 ref_audio 컨테이너 경로 mismatch | TTS 실패 | `_voice_profile.py` 헬퍼로 경로 변환 단일화 — GPT-SoVITS 어댑터와 동일 패턴 |
| Voice Design 한국어/일본어 instability | design 모드 한정 사용 | upstream README `voice-design.md` 명시 — Chinese/English 학습. 한국어는 clone 모드 권장 |
| tts cache key collision (`engine + voice_profile`) | 다른 엔진 결과가 cache hit | 현 [`tts_service.py#L142`](../../backend/service/vtuber/tts/tts_service.py#L142) 의 voice_id = `f"{engine.engine_name}:{voice_profile}"` 가 이미 분리. 변경 불필요 |

## 산출 PR 목록 (예정)

| PR | 리포 | 브랜치 | 범위 |
|---|---|---|---|
| PR-OV-1 | `Geny` | `feat/omnivoice-vendor-and-server` | `Geny/omnivoice/` 디렉터리 + Dockerfile + tests |
| PR-OV-2 | `Geny` | `feat/omnivoice-compose-services` | docker-compose 3종 omnivoice service 추가 |
| PR-OV-3 | `Geny` | `feat/omnivoice-backend-engine` | OmniVoiceConfig + OmniVoiceEngine + tts_general provider 옵션 + tests |
| PR-OV-4 | `Geny` | `docs/omnivoice-integration` | omnivoice/README, docs/OmniVoice_INTEGRATION.md |
| PR-OV-5 | `Geny` | `docs/cycle-20260422-omnivoice-close` | 사이클 종료 doc |

## 산출 문서 (`progress/`)

- `progress/pr1_vendor_and_server.md`
- `progress/pr2_compose_services.md`
- `progress/pr3_backend_engine.md`
- `progress/pr4_docs.md`
- `progress/cycle_close.md`

---

**다음 단계.** 본 index 를 reviewer 1 인 (사용자) 가 승인하면 PR-OV-1 작업을
`feat/omnivoice-vendor-and-server` 브랜치에서 시작한다. 작업 시작 전
*Phase 0* 의 한국어 합성 품질 수동 평가가 선행된다.
