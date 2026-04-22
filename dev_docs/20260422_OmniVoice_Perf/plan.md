# plan.md — Phase별 구현 체크리스트

> 모든 변경은 *순수 가산*. 기존 기본 동작(`tts_omnivoice` 의 디폴트 옵션)은 유지. 새 동작은 신규 옵션으로 진입.
> PR 단위로 묶어 검토. 각 PR 은 *해당 Phase 의 완료 기준*을 통과해야 머지.
>
> **환경 게이트.** 각 PR 은 dev 단위 테스트 + (모델-경로 변경 시) staging GPU 게이트를 모두 통과해야 한다. 정확한 절차는 [environment.md §6](environment.md#6-본-사이클-pr-의-환경별-게이트-매트릭스).
>
> **티어 표기.** [index.md §3](index.md#3-최적화-전략-impact--effort-매트릭스) 의 Tier-A/B/C 를 따른다. *Tier-A 만 디폴트 ON*. Tier-B 는 코드만 추가, 디폴트 OFF. Tier-C 는 capability 가드 뒤로 숨겨두고 sm_61 에서는 자동 비활성.

---

## Phase 0 — 벤치마크 박제 (PR-0)

**목표.** baseline 을 박제. 이후 모든 최적화의 기준선. **dev 에서는 스크립트 import/lint 만**, 실제 측정은 staging.

- [ ] `Geny/omnivoice/scripts/bench.py` 신설 ([analysis.md §10](analysis.md#10-측정-도구-phase-0) 참조 스니펫 기반).
- [ ] `Geny/omnivoice/scripts/texts_ko.txt`, `texts_en.txt`, `texts_smoke.txt` — 5/15/40/100/200 자 길이 5종 × 6개 = 30 문장 + smoke 5문장.
- [ ] `Geny/omnivoice/scripts/run_bench.sh`, `staging_gate.sh` — 컨테이너 내부에서 호출, 결과 JSON 을 호스트로 mount-out.
- [ ] `Geny/omnivoice/server/compare_audio.py` 신설 ([environment.md §4](environment.md#4-compare_audiopy--출력-동치성-검증)) — `--capture` / `--baseline` 모드 양쪽.
- [ ] `Geny/omnivoice/scripts/bench_to_md.py` — bench JSON → benchmarks.md 행 한 줄 변환 (사람이 복붙).
- [ ] dev: `python -m server.bench --help` 가 GPU 없이도 ImportError 없이 동작 (lazy CUDA 호출).
- [ ] **staging 1회**: baseline PCM 캡처 → `dev_docs/20260422_OmniVoice_Perf/baselines/sm_61/` 보관 (또는 별도 artifact 저장소).
- [ ] **staging 1회**: [benchmarks.md](benchmarks.md) 에 baseline 행 (`Phase 0 / GTX1070 / fp16 / num_step=32 / no-warmup`) 추가.

**완료 기준.**
- dev: bench.py / compare_audio.py 가 GPU 없이 `--help`, dry-run, mock-mode 통과.
- staging: 30 sample × 3 runs 의 RTF/TTFA 통계 + baseline PCM 30개 캡처.

---

## Phase 1 — 저-위험 가속 (PR-1)

**목표.** 동작 변경 0, 안전한 셋업 개선.

### 1a. Warmup (O1)

- [ ] [`omnivoice/server/main.py`](../../omnivoice/server/main.py) lifespan 에서 모델 로드 *후*:
  ```python
  await engine.warmup(
      texts=["안녕하세요. 반갑습니다.", "Hello, this is a warmup."],
      voice_profile=settings.warmup_voice_profile,  # 신규, 기본 "paimon_ko"
  )
  ```
- [ ] `server/engine.py` 에 `async def warmup(self, texts, voice_profile)` 추가. 내부적으로 `synthesize` 호출 + 결과 폐기.
- [ ] `/health` 응답에 `phase: "loading"|"warming"|"ok"` 필드 추가 (기존 `status` 호환 유지).
- [ ] [`omnivoice_engine.py`](../../backend/service/vtuber/tts/engines/omnivoice_engine.py) `health_check()` 가 `phase != "ok"` 면 False 반환 — fallback 로 위임.

### 1b. 어댑터 락 제거 (O2)

- [ ] `omnivoice_engine.py` 에서 `_synthesis_lock` 모듈 변수 + 사용처 제거.
- [ ] 회귀: 동시 N개 합성 요청 시 GPU OOM 안 나는지 확인 (서버 Semaphore 가 처리).
- [ ] 단위 테스트 신설: `backend/tests/service/vtuber/tts/test_omnivoice_engine_concurrency.py` — 2개 동시 호출이 GPU OOM 없이 순차 완료되는지 (mock httpx 로 200 반환).

### 1c. dtype 고정 (Pascal fp16)

> **본 환경에서는 dtype 자동 선택(O10) 이 불필요**. Ampere+ 인프라 도입 시 별도 사이클 안건. 대신 *capability 가드* 의 키 코드만 설치.

- [ ] `server/settings.py` 에 `OMNIVOICE_DTYPE` 디폴트를 `"float16"` 으로 명시 고정. `"auto"` / `"bfloat16"` 값은 수락하되 *롤아서 CUDA capability < (8,0) 이면 경고 로그 + fp16 강제*.
- [ ] `server/engine.py` 에 `resolve_dtype(setting, device)` 추가 ([analysis.md §6](analysis.md#6-dtype-선택의-미묘함)). 핵심은 *Pascal 에서 사용자가 실수로 bf16 켰을 때 모델 로드 실패를 막는 것*.
- [ ] `Dockerfile` env 디폴트 `OMNIVOICE_DTYPE=float16` 명시.
- [ ] dev 단위: `torch.cuda.get_device_capability` monkeypatch 로 sm_61 / sm_86 두 시나리오 검증.

**Tier.** A (Pascal 에서는 무동작 — 디폴트가 이미 fp16 이라 행동 변화 없음, *방어 코드*).

### 1d. 영구 점유 (O14 + O15 + O16 + O17, **Tier-A**)

> **철학.** vLLM 이 KV-cache pool 을 시작 시 *한 번에* 잡고 운영 종료까지 들고 있는 것처럼, omnivoice 컨테이너도 모델 가중치 + workspace 텐서 + ref-cache + pinned host buffer + CUDA stream 을 **lifespan 단계에서 일괄 할당하고 절대 해제하지 않는다**. 런타임 중에는 *새로운 큰 할당이 발생하지 않는 정상 상태(steady state)* 만 본다 — allocator 호출/단편화/cold path 를 0 으로 수렴.
>
> 이 결정의 이유: 본 컨테이너는 *유일한 텐션트* (단일 GPU, 단일 모델, 단일 서비스). VRAM 을 다른 프로세스와 공유할 동기 없음. 사용 가능한 모든 VRAM 을 사전 점유하여 *예측 가능한 latency* 를 사는 것이 옳음.

#### 1d-1. Allocator/스트림 정책 고정 (O17, *가장 먼저*)

- [ ] [`omnivoice/Dockerfile`](../../omnivoice/Dockerfile) `ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb=128`. fragmentation 회피 + 큰 텐서 재사용 가능.
- [ ] `server/engine.py` 모델 로드 직전:
  ```python
  if torch.cuda.is_available():
      torch.backends.cudnn.benchmark = True              # 고정 shape → 알고리즘 캐시 활용
      torch.backends.cuda.matmul.allow_tf32 = False      # Pascal 무관, sm_80+ 안전성 위해 명시
      if settings.gpu_memory_fraction > 0:               # 디폴트 0.9
          torch.cuda.set_per_process_memory_fraction(
              settings.gpu_memory_fraction, device=device
          )
  engine_state.streams = {
      "compute": torch.cuda.current_stream(device),
      "h2d": torch.cuda.Stream(device),                  # 입력 업로드 전용
      "d2h": torch.cuda.Stream(device),                  # 출력 다운로드 전용
  }
  ```
- [ ] `server/settings.py` 신규: `OMNIVOICE_GPU_MEM_FRACTION: float = 0.9` (GTX 1070 8GB → ~7.2GB cap).
- [ ] dev: settings 파싱 / monkeypatched `torch.cuda` 로 분기 단위 테스트.

#### 1d-2. Workspace 텐서 사전 할당 (O14)

- [ ] `omnivoice/server/workspace.py` 신설:
  ```python
  @dataclass
  class GenerationWorkspace:
      """_generate_iterative 가 사용할 모든 가변 in-place 버퍼.
      lifespan 에서 max(T_total) 기준 1회 할당, 매 호출 in-place 재사용.
      """
      batch_input_ids: torch.Tensor   # (2*MAX_B, C, MAX_T) int64
      attention_mask:  torch.Tensor   # (2*MAX_B, 1, MAX_T, MAX_T) bool
      audio_mask:      torch.Tensor   # (2*MAX_B, MAX_T) bool
      logits_buf:      torch.Tensor   # (2*MAX_B, C, MAX_T, V) float16  (가장 큼)
      score_buf:       torch.Tensor   # (MAX_B, C, MAX_T) float32
      sample_buf:      torch.Tensor   # (MAX_B, C, MAX_T) int64

      @classmethod
      def allocate(cls, *, max_B: int, num_codebooks: int, max_T: int,
                   vocab_size: int, device, dtype) -> "GenerationWorkspace": ...
      def reset(self) -> None:
          """매 호출 시작 시 *0/마스크 초기값*으로 in-place reset (할당 없음)."""
  ```
- [ ] `cached_model.py` 의 `CachedOmniVoice._generate_iterative` 가 `self._workspace` 를 받아 `batch_input_ids = self._workspace.batch_input_ids[:2*B, :, :T_total]` 식의 *슬라이스 뷰* 로 사용. *새 텐서 할당 0*.
- [ ] settings: `OMNIVOICE_MAX_AUDIO_SECONDS: float = 30.0` → `MAX_T = ceil(30.0 * 50)` (50 fps token rate). `OMNIVOICE_MAX_BATCH: int = 1` (단일 사용자 가정, 향후 coalescer 켜질 때 4 로 확장).
- [ ] 안전: 요청이 `MAX_T` 초과 시 즉시 400 (or 청크 분할). `MAX_T` 는 lifespan 에서 *실제 할당 가능한 VRAM* 에 맞춰 자동 조정 (예산 초과 시 한 단계 낮춰 재시도, 시작 실패 회피).
- [ ] dev: `GenerationWorkspace.allocate(...)` 의 shape/dtype/device 단위 테스트 (CPU 텐서로). `reset()` 이 in-place 인지 확인.
- [ ] staging: workspace 사용 전/후 `compare_audio --atol 1e-4` PASS — *슬라이스 뷰 사용이 출력에 영향 0*.

#### 1d-3. Pinned host pool (O15)

- [ ] `server/host_pool.py` 신설:
  ```python
  class PinnedPCMPool:
      def __init__(self, *, slots: int = 4, max_seconds: float = 30.0,
                   sample_rate: int = 24000):
          n = int(max_seconds * sample_rate)
          self._free: deque[torch.Tensor] = deque(
              torch.empty(n, dtype=torch.int16, pin_memory=True)
              for _ in range(slots)
          )
          self._lock = asyncio.Lock()
      async def acquire(self, n_samples: int) -> torch.Tensor: ...
      def release(self, buf: torch.Tensor) -> None: ...
  ```
- [ ] 합성 결과를 `gpu_audio.to(host_buf, non_blocking=True)` 로 *전용 d2h stream* 통해 다운로드. 기존 `.cpu().numpy()` 동기 왕복 제거.
- [ ] `StreamingResponse` 가 yield 후 `release()` 로 슬롯 반납 (`finally` 블록).
- [ ] settings: `OMNIVOICE_PINNED_SLOTS: int = 4` (concurrent ≤ Semaphore(1) 이지만 streaming 단계에선 chunk 단위 in-flight 가능).
- [ ] dev: pool acquire/release/exhaustion 단위 테스트 (CPU 환경에서 `pin_memory=False` mock).

#### 1d-4. Multi-shape warmup (O16)

- [ ] `engine.warmup()` 확장:
  ```python
  WARMUP_BUCKETS = [
      ("short",  "안녕하세요."),                          # T_total ≈ 256
      ("medium", "오늘 날씨가 정말 좋네요. " * 3),       # T_total ≈ 512
      ("long",   "긴 문장 합성 워밍업입니다. " * 8),      # T_total ≈ 1024
  ]
  for name, text in WARMUP_BUCKETS:
      _ = await self.synthesize(text, voice=settings.warmup_voice_profile,
                                discard_output=True)
      logger.info("warmup bucket=%s done", name)
  ```
- [ ] 결과: cuDNN/cuBLAS 알고리즘 캐시 + autotune workspace 가 3 bucket 모두에 대해 확정 → 런타임 첫 호출의 *bucket-별* cold gap 0.
- [ ] `/health` 의 `phase` 가 `loading` → `warming` → `ok` 단계 전이를 정확히 반영. `warming` 동안 `OmniVoiceEngine.health_check()` 는 False → 어댑터가 fallback (현 동작과 동일).
- [ ] dev: warmup 호출 시퀀스 (mock `synthesize`) 단위 테스트.
- [ ] staging: 컨테이너 재시작 직후 short/medium/long 첫 호출의 RTF 가 *steady-state RTF 와 ±10%* 이내 (cold gap 제거 검증).

#### 1d-5. 검증 — 영구 점유의 결정적 증거

- [ ] `server/diagnostics.py` 신설: `GET /diag/memory` 가 `torch.cuda.memory_stats()` 의 핵심 키 (`allocated_bytes.all.current`, `.peak`, `reserved_bytes.all.current`, `num_alloc_retries`, `num_ooms`) JSON 반환.
- [ ] staging 회귀 게이트: 컨테이너 시작 직후 → 100 합성 후 두 시점 비교:
  - `allocated_bytes.all.current` 증가량 = 0 (±0.5%)
  - `reserved_bytes.all.current` 증가량 = 0
  - `num_alloc_retries` 증가량 = 0
  - `num_ooms` = 0
  - `(reserved - allocated) / reserved` ≤ 5% (단편화 검증)
- [ ] 위 중 하나라도 깨지면 PR 머지 거부 (workspace pre-alloc 이 빠진 경로가 있다는 뜻).

**Tier.** A (전 단계 출력 동치, 단지 메모리/스트림 정책만 바뀜).

**완료 기준.**
- dev: workspace allocator / pinned pool / 알로케이터 settings / warmup 시퀀스 단위 테스트 PASS.
- staging:
  - `/health` 가 lifespan 완료 후 `phase: ok` (warmup 3 bucket 포함, ~60s 이내).
  - `/diag/memory` 가 위 영구 점유 5개 조건 모두 충족.
  - `compare_audio --atol 1e-4` 30 케이스 PASS.
  - 100 합성 sustained RTF p95 가 1a~1c 단계 대비 *동일하거나 개선*, p95-p50 gap (jitter) 가 *감소*.
- [benchmarks.md](benchmarks.md) 에 Phase 1d 행 추가 (steady-state VRAM, fragmentation, p95-p50 gap 컬럼 포함).

---

**Phase 1 전체 완료 기준.**
- dev: 1a~1d 의 모든 단위 테스트 PASS.
- staging: 컨테이너 재시작 → `/health` 가 ~60s 내 `phase: ok`. 첫 진짜 호출의 RTF 가 정상 호출과 ±10% 이내. `compare_audio --atol 1e-4` 30 케이스 PASS. `/diag/memory` 영구 점유 조건 충족.
- [benchmarks.md](benchmarks.md) 에 Phase 1 / Phase 1d 행 추가, baseline 대비 cold-call 제거 + steady RTF 회귀 없음.

---

## Phase 2 — 모델 단계 가속 (PR-2)

> Phase 2 는 **2b 만 Tier-A**, 2a 와 2c 는 Tier-B (디폴트 OFF, 코드만 추가). 이 분리는 *품질 손실 0* 하드 제약 때문.

### 2a. Adaptive `num_step` (O7, **Tier-B, 디폴트 OFF**)

> ⚠️ 출력 분포가 변한다. 사용자가 명시적으로 켠 경우에만 동작. 디폴트 사이클 머지 후 **별도 청취 평가 사이클** 통과 시점에 디폴트화 검토.

- [ ] `server/schemas.py` 의 `TTSRequest.num_step` 디폴트 32 유지. 별도 필드 `adaptive_steps: bool = False` 추가.
- [ ] `server/engine.py` 가 `adaptive_steps=True` 시:
  ```python
  est_dur = estimate_duration(text, lang)  # OmniVoice 의 utils.duration 활용
  num_step = 16 if est_dur < 3.0 else 24 if est_dur < 8.0 else 32
  ```
- [ ] backend `OmniVoiceConfig` 에 `adaptive_steps: bool = False` 노출, 메타데이터에 *"실험적: 출력 변경 가능"* 경고 라벨.
- [ ] dev: schema/config 단위 테스트.
- [ ] staging: ON/OFF 양쪽으로 RTF + `compare_audio --mode quality-drift` 출력 (디폴트 OFF 경로는 baseline 동치).

### 2b. Voice reference 캐시 (O4, **Tier-A**)

> 출력 동치 — `_prepare_inference_inputs` 의 결과는 결정론적 함수이므로 캐시 hit/miss 가 출력에 영향 없음. 단, 구현 버그로 캐시 키 충돌 시 잘못된 reference 가 적용될 위험 → `compare_audio` 가 끝까지 게이트.

- [ ] `omnivoice/server/cached_model.py` 신설:
  ```python
  class CachedOmniVoice(OmniVoice):
      def __init__(self, *a, **kw):
          super().__init__(*a, **kw)
          self._ref_cache: dict[tuple, dict] = {}

      def _prepare_inference_inputs(self, text, target_len, ref_text, ref_audio_tokens, lang, instruct, denoise):
          key = (lang, ref_text, _hash_tensor(ref_audio_tokens), instruct, denoise)
          base = self._ref_cache.get(key)
          if base is None:
              base = super()._prepare_inference_inputs(text=text, ...)
              self._ref_cache[key] = _strip_text_specific(base)
          return _merge_text_into_template(base, text, target_len)
  ```
- [ ] `_strip_text_specific` / `_merge_text_into_template` 의 정확한 분리는 분석 단계에서 *실제* `_prepare_inference_inputs` 의 토큰 레이아웃을 보고 결정. (분리 가능성 검증을 위한 spike 가 PR-2 의 첫 일감 — staging 에서 실제 텐서 shape 덤프.)
- [ ] 캐시 무효화: profile dir mtime 변경 시 자동 flush. settings 에 `OMNIVOICE_REF_CACHE_SIZE=8` (LRU). `=0` 으로 두면 *완전 비활성* (롤백 핫스위치).
- [ ] dev: 캐시 키 / mtime invalidation / LRU 단위 테스트 (모델 mock).
- [ ] staging: `compare_audio --atol 1e-4` 30 케이스 PASS — 캐시 hit/miss 양쪽에서 동일 PCM 보장.

### 2c. CFG 조건부 스킵 (O3, **Tier-B, 디폴트 OFF**)

> ⚠️ `guidance_scale=0` 은 *upstream 권장값과 다름*, 출력 분포 변경. 디폴트 `gs=2.0` 유지. 본 PR 은 *코드 분기만 설치*.

- [ ] **vendored copy 직접 패치**: [omnivoice.py L1145+ `_generate_iterative`](../../omnivoice/omnivoice_core/models/omnivoice.py#L1145) 에 [analysis.md §2](analysis.md#2-cfg-절반-낭비의-정확한-위치) 의 `use_cfg = gen_config.guidance_scale != 0` 분기 추가.
- [ ] `_generate_chunked` 도 동일 처리 ([omnivoice.py L787+](../../omnivoice/omnivoice_core/models/omnivoice.py#L787)).
- [ ] `omnivoice/docs/upstream_sync.md` 에 *우리 patch 목록* 섹션 신설, 이 변경 기록 (이후 upstream sync 시 재적용 표시).
- [ ] backend `OmniVoiceConfig.guidance_scale: float = 2.0` 유지. 사용자가 0.0 으로 설정 시에만 효과 발휘.
- [ ] dev: 분기 정합성 단위 테스트 (mock 모델, batch_input_ids shape 만 검증).
- [ ] staging: `gs=2.0` 으로 `compare_audio --atol 1e-4` 동치성 PASS (분기 추가가 디폴트 경로 회귀 없음). `gs=0` 별도 측정은 *참고용*만, 게이트 아님.

**완료 기준.**
- dev: 모든 Phase 2 단위 테스트 PASS.
- staging: 디폴트 경로 (Tier-A 만 ON, ref-cache 활성, adaptive/CFG 분기는 코드만 존재) 가 baseline 과 출력 동치 + RTF 가 Phase 1 대비 *동일하거나 개선* (텍스트 짧을수록 ref-cache 효과로 5~15% 개선 기대).

---

## Phase 3 — 컴파일 (PR-3, **Tier-C, sm_61 자동 OFF**)

> ⚠️ **본 운영 환경(GTX 1070, sm_61)에서는 자동 비활성**. inductor 의 Pascal 지원이 약하고 회귀 위험이 큼. 본 PR 은 *capability 가드 코드와 settings 만* 추가하여 미래 GPU 교체 시 즉시 활성화 가능한 상태로 둔다. **벤치마크 측정 대상 아님**.

### 3a. `torch.compile` (O5) — capability 가드만

- [ ] `server/settings.py` 에 `OMNIVOICE_USE_COMPILE: str = "auto"` (디폴트 auto). 값: `auto | always | never`.
- [ ] `server/engine.py` 의 모델 로드 직후:
  ```python
  def should_compile(setting: str, device: torch.device) -> bool:
      if setting == "never": return False
      if device.type != "cuda": return False
      cap = torch.cuda.get_device_capability(device)
      if cap < (7, 0):
          if setting == "always":
              logger.warning("compile=always 지정됐지만 sm_%d%d 는 inductor 지원 약함, 비활성", *cap)
          return False
      return setting in ("auto", "always")

  if should_compile(settings.use_compile, device):
      model.forward = torch.compile(model.forward, mode="reduce-overhead", fullgraph=False, dynamic=False)
      _trigger_compile_warmup(model, buckets=[128, 256, 384, 512, 768, 1024])
  else:
      logger.info("torch.compile 비활성 (cap=%s)", torch.cuda.get_device_capability(device))
  ```
- [ ] `T_total` bucketing 헬퍼 추가 ([analysis.md §7](analysis.md#7-torchcompile-적용-전제) 의 `bucket_T`).
- [ ] healthcheck 의 `start-period` 는 *현행 유지* (180s) — 본 환경에서 compile 안 돔. Ampere+ 에서는 별도 사이클에서 300s 로.
- [ ] `/health` 의 `phase` 에 `compiling` 상태 코드 자리만 추가 (사용 안 됨).
- [ ] dev: capability=(8,0) / (6,1) / (cpu) 3 케이스 분기 단위 테스트.
- [ ] staging (GTX 1070): `phase=ok` 도달, `should_compile()` 이 False 반환 + 경고 로그 1줄, RTF 가 Phase 2 와 동치.

**완료 기준.**
- Pascal 환경에서 *동작 변화 0*. `compare_audio --atol 1e-4` PASS.
- Ampere+ 환경 (보조 머신이 있다면) 에서 compile 활성 시 동치 PCM (compile 은 산술 동치이지 *수치 동치는 아닐 수 있음* — 별도 atol 협의).

### 3b. CUDA Graphs (O6, 옵션, **본 사이클 비목적**)

- [ ] sm_70+ 도입 사이클로 이월. 본 사이클에서는 코드/문서 추가 없음.

---

## Phase 4 — 문장 스트리밍 큐 (PR-4)

상세 설계 [streaming.md](streaming.md). 본 절은 체크리스트.

### 4a. omnivoice 서버 chunked transfer

- [ ] `server/api.py` 에 `POST /tts/stream` 신규. body 는 `/tts` 와 동일.
- [ ] 응답: `StreamingResponse(media_type="audio/wav")`. 첫 chunk 는 wav header (PCM 24kHz 16bit mono), 이후 PCM frames 점진적 yield.
- [ ] OmniVoice 의 `_generate_chunked` 가 *audio chunk* 를 yield 할 수 있도록 server 단에서 callback 또는 streaming generator 로 wrap. (모델 자체는 전체 합성 후 list 반환이므로, 첫 단계로는 *문장 단위 다중 호출 + yield* 접근이 더 안전.)
- [ ] `/tts` 는 그대로 유지 (backward compat).

### 4b. backend job queue + sentence endpoint

- [ ] `Geny/backend/service/vtuber/tts/job_queue.py` 신설:
  ```python
  class TTSJobQueue:
      def __init__(self): self._queues: dict[str, asyncio.Queue] = {}
      def enqueue(self, session_id, sentence, seq, ...) -> Future
      def cancel_session(self, session_id) -> int  # returns dropped count
      async def _worker(self, session_id): ...
  ```
- [ ] `controller/tts_controller.py` 에 신규 엔드포인트:
  ```
  POST /api/tts/agents/{session_id}/speak/sentence
       body: { text, seq, emotion?, language?, is_last?: bool }
       response: StreamingResponse(audio chunked)
  ```
- [ ] 기존 `/speak` 는 *전체 텍스트 한 번* 시나리오로 그대로 유지.
- [ ] 새 입력 도착 시 `cancel_session()` — chat WS 의 user-input 이벤트에 hook.

### 4c. 프론트 SentenceAccumulator + audioManager seq

- [ ] `Geny/frontend/src/lib/sentenceSplitter.ts` 신설:
  ```ts
  export class SentenceAccumulator {
    private buf = ''
    push(chunk: string): string[] { /* return finished sentences */ }
    flush(): string[]              /* on stream end */
  }
  ```
  분할 규칙: [streaming.md](streaming.md) §2 의 정규식.
- [ ] `Geny/frontend/src/lib/sentenceSplitter.test.ts` — edge case (한국어 인용, 숫자 소수점, URL, 코드블록, 이모지) 30 케이스.
- [ ] [`audioManager.ts`](../../frontend/src/lib/audioManager.ts) `enqueue()` 에 `seq?: number` 옵션. seq 가 있으면 OOO 도착 시 대기, monotonic 재생.
- [ ] [`useVTuberStore.ts`](../../frontend/src/store/useVTuberStore.ts) 에 `speakSentence(sessionId, text, seq, isLast)` 추가. 기존 `speakResponse` 는 보존.
- [ ] [`VTuberChatPanel.tsx`](../../frontend/src/components/live2d/VTuberChatPanel.tsx) 의 어시스턴트 SSE 수신 부:
  - `useVTuberStore.getState().ttsStreamingEnabled` (신규 setting) 가 켜져 있으면 — 토큰 도착 시 SentenceAccumulator 에 push, 완료된 문장마다 `speakSentence` 호출.
  - 메시지 종료 시 `flush()` + 마지막 호출에 `isLast=true`.
  - 디폴트는 OFF — 기존 `status='executing'` end-of-stream 1-shot 경로 유지.

**완료 기준.** TTS streaming 옵션 ON 시 TTFA 가 LLM 첫 문장 완료 시점 + ~1×문장 합성시간. 30개 케이스 분할 단위 테스트 100% 통과. 사용자 새 입력 시 진행 중 큐가 200ms 내 cancel.

---

## Phase 5 — Throughput (PR-5, 옵션)

다중 동시 사용자가 발생할 때만. 본 사이클의 권장 산출은 *설계 문서 + 비활성 코드*. 실제 활성화는 운영 데이터 보고 결정.

- [ ] `server/coalescer.py` 신설 — `MicroBatchCoalescer(window_ms=50, max_B=4)`.
- [ ] settings `OMNIVOICE_COALESCE_WINDOW_MS=0` (디폴트 OFF).
- [ ] B>1 batching 을 위한 shape padding/masking 로직.

---

## Phase 6 — 검증 / 회귀 (PR-6)

- [ ] [benchmarks.md](benchmarks.md) 의 모든 Phase 행이 채워졌는지 확인 (Pascal sm_61 환경만).
- [ ] **출력 동치 회귀 게이트.** `compare_audio.py --atol 1e-4` 가 *모든 누적 변경 적용* 상태에서 baseline 30 케이스 PASS. 한 케이스라도 실패 시 *전체 사이클* 회귀.
- [ ] fp16 NaN 발생률 0% 확인 (1000 합성 sample, staging).
- [ ] E2E 회귀: edge_tts / gpt_sovits / openai / elevenlabs 4개 엔진이 본 사이클 변경 후 동작 그대로 — `tts_general.provider=` 각각 으로 전환하여 합성 성공 (dev: mock 응답으로도 충분).
- [ ] [docs/MIGRATION_PROGRESS.md](../../docs/MIGRATION_PROGRESS.md) 에 사이클 완료 항목 추가.
- [ ] **Tier-B 옵션 청취 평가는 별도 사이클로 이월** (본 사이클 비목적).

---

## 부록 A — 신규/수정 파일 목록

### omnivoice 컨테이너

| 파일 | 종류 | Phase |
|------|------|-------|
| [`omnivoice/server/settings.py`](../../omnivoice/server/settings.py) | 수정 | 1c, 1d, 3a |
| [`omnivoice/server/main.py`](../../omnivoice/server/main.py) | 수정 (lifespan warmup) | 1a, 1d, 3a |
| [`omnivoice/server/engine.py`](../../omnivoice/server/engine.py) | 수정 (`warmup`, dtype, allocator/streams, compile) | 1a, 1c, 1d, 2b, 3a |
| `omnivoice/server/cached_model.py` | 신설 | 1d, 2b |
| `omnivoice/server/workspace.py` | 신설 (`GenerationWorkspace`) | 1d |
| `omnivoice/server/host_pool.py` | 신설 (`PinnedPCMPool`) | 1d |
| `omnivoice/server/diagnostics.py` | 신설 (`/diag/memory`) | 1d |
| [`omnivoice/server/api.py`](../../omnivoice/server/api.py) | 수정 (+`/tts/stream`, `/diag/*`) | 1d, 4a |
| [`omnivoice/omnivoice_core/models/omnivoice.py`](../../omnivoice/omnivoice_core/models/omnivoice.py) | 수정 (CFG 분기, workspace 슬라이스 뷰 hook) | 1d, 2c |
| `omnivoice/scripts/bench.py` | 신설 | 0 |
| `omnivoice/scripts/texts_ko.txt`, `texts_en.txt`, `texts_smoke.txt` | 신설 | 0 |
| `omnivoice/scripts/run_bench.sh`, `staging_gate.sh`, `bench_to_md.py` | 신설 | 0 |
| `omnivoice/server/compare_audio.py` | 신설 | 0 |
| `dev_docs/20260422_OmniVoice_Perf/baselines/sm_61/` | 신설 (PCM 30개) | 0 |
| [`omnivoice/Dockerfile`](../../omnivoice/Dockerfile) | 수정 (healthcheck start-period, `PYTORCH_CUDA_ALLOC_CONF`, `OMNIVOICE_GPU_MEM_FRACTION`) | 1d, 3a |
| [`omnivoice/docs/upstream_sync.md`](../../omnivoice/docs/upstream_sync.md) | 수정 (patch list) | 2c |

### Geny backend

| 파일 | 종류 | Phase |
|------|------|-------|
| [`backend/service/vtuber/tts/engines/omnivoice_engine.py`](../../backend/service/vtuber/tts/engines/omnivoice_engine.py) | 수정 (락 제거, healthcheck phase) | 1a, 1b |
| [`backend/service/config/sub_config/tts/omnivoice_config.py`](../../backend/service/config/sub_config/tts/omnivoice_config.py) | 수정 (`adaptive_steps`, `streaming_mode`) | 2a, 4b |
| `backend/service/vtuber/tts/job_queue.py` | 신설 | 4b |
| [`backend/controller/tts_controller.py`](../../backend/controller/tts_controller.py) | 수정 (+sentence endpoint) | 4b |

### Geny frontend

| 파일 | 종류 | Phase |
|------|------|-------|
| `frontend/src/lib/sentenceSplitter.ts` | 신설 | 4c |
| `frontend/src/lib/__tests__/sentenceSplitter.test.ts` | 신설 | 4c |
| [`frontend/src/lib/audioManager.ts`](../../frontend/src/lib/audioManager.ts) | 수정 (seq) | 4c |
| [`frontend/src/store/useVTuberStore.ts`](../../frontend/src/store/useVTuberStore.ts) | 수정 (`speakSentence`, `ttsStreamingEnabled`) | 4c |
| [`frontend/src/components/live2d/VTuberChatPanel.tsx`](../../frontend/src/components/live2d/VTuberChatPanel.tsx) | 수정 (SentenceAccumulator 연결) | 4c |
| `frontend/src/lib/i18n/{ko,en}.ts` | 수정 (`tts.streaming.*` 라벨) | 4c |

---

## 부록 B — Out of scope / 향후 사이클

- 모델 distillation (4-step student)
- multi-replica 수평 확장 + load balancer
- 음성 클로닝 quality auto-eval (UTMOS, SECS)
- FlexAttention 진짜 sparse mask 활용 (마스크 패턴 분석 선행)
- WebRTC 기반 PCM streaming (HTTP chunked 의 한계 도달 시)
- Whisper 자동 ASR (`OMNIVOICE_AUTO_ASR=true`) latency 최적화
