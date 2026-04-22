# analysis.md — OmniVoice 인퍼런스 심층 분석

> 본 문서는 [index.md](index.md) §3 의 각 최적화 기법이 *왜* 그 위치에서 의미를 갖는지에 대한 코드 레벨 근거를 모은다. 모든 줄 번호는 2026-04-22 시점 기준.

---

## 1. `_generate_iterative` 의 한 step 비용 분해

[omnivoice.py L1255-L1300](../../omnivoice/omnivoice_core/models/omnivoice.py#L1255-L1300) 발췌:

```python
for step in range(gen_config.num_step):                                   # ── (A)
    batch_logits = self(                                                  # ── (B) ★ heavy
        input_ids=batch_input_ids,                                        #     (2*B, C, T_total)
        audio_mask=batch_audio_mask,
        attention_mask=batch_attention_mask,
    ).logits.to(torch.float32)                                            # ── (C) dtype upcast

    for i in range(B):                                                    # ── (D) per-item, but B=1 in chat
        k = schedules[i][step]
        if k <= 0: continue
        c_logits = batch_logits[i:i+1, :, c_len-t_len:c_len, :]
        u_logits = batch_logits[B+i:B+i+1, :, :t_len, :]
        pred_tokens, scores = self._predict_tokens_with_scoring(          # ── (E) softmax + CFG combo
            c_logits, u_logits, gen_config
        )
        ...
        _, topk_idx = torch.topk(scores.flatten(), k)                     # ── (F)
        flat_tokens[topk_idx] = pred_tokens.flatten()[topk_idx]
        sample_tokens.copy_(flat_tokens.view_as(sample_tokens))           # ── (G)
        batch_input_ids[i:i+1, :, c_len-t_len:c_len] = sample_tokens      # ── (H) in-place ★
        batch_input_ids[B+i:B+i+1, :, :t_len]        = sample_tokens      # ── (H')
```

GPU 시간 분포 (RTX 3090, T_total≈400, B=1, num_codebook=8, 하나의 1024-context 모델 가정 — 실측은 [benchmarks.md](benchmarks.md) Phase 0 참조):

| 라벨 | 비중 | 비고 |
|------|------|------|
| (B) forward | **~93%** | 32회 × `(2, C, T)` self-attention + FFN |
| (C) fp16→fp32 cast | ~1% | 매 step. 누적은 작지만 메모리 트래픽 ↑ |
| (E) `_predict_tokens_with_scoring` | ~3% | softmax 두 번 + log 결합 |
| (F) topk over flat | ~1% | T·C 사이즈, 수천~수만 |
| (G/H/H') in-place writes | ~1% | 매우 작음 |
| host↔device | ~1% | 결과만 한 번 cpu() |

→ **결론.** O5/O6 (compile + cuda graphs) 의 표적은 (B). O3 (CFG 스킵) 은 (B) 의 batch 차원을 절반으로. O7 (num_step↓) 은 (A) 의 반복 횟수를 직접 줄임 — 가장 비례 효과 큼.

---

## 2. CFG 절반 낭비의 정확한 위치

[omnivoice.py L1300+ `_predict_tokens_with_scoring`](../../omnivoice/omnivoice_core/models/omnivoice.py#L1300):

```python
if gen_config.guidance_scale != 0:
    c_log_probs = F.log_softmax(c_logits, dim=-1)
    u_log_probs = F.log_softmax(u_logits, dim=-1)
    log_probs = torch.log_softmax(
        c_log_probs + gen_config.guidance_scale * (c_log_probs - u_log_probs),
        dim=-1,
    )
else:
    log_probs = F.log_softmax(c_logits, dim=-1)                            # ★ uncond 사용 안 함
```

→ `guidance_scale=0` 인 경우 `u_logits` 가 *사용되지 않음*. 그런데 `_generate_iterative` 는 무조건 `(2*B, ...)` batch 로 forward 를 돌린다. 따라서:

**O3 패치 스케치** ([omnivoice.py L1145+](../../omnivoice/omnivoice_core/models/omnivoice.py#L1145) 인근):

```python
use_cfg = gen_config.guidance_scale != 0
batch_mult = 2 if use_cfg else 1

batch_input_ids = torch.full((batch_mult * B, ...), ...)
# ... (uncond 절반 셋업은 use_cfg 일 때만)

for step in range(gen_config.num_step):
    batch_logits = self(
        input_ids=batch_input_ids,           # (B,...) or (2B,...)
        ...
    ).logits.to(torch.float32)
    for i in range(B):
        c_logits = batch_logits[i:i+1, :, c_len-t_len:c_len, :]
        u_logits = batch_logits[B+i:B+i+1, :, :t_len, :] if use_cfg else None
        pred_tokens, scores = self._predict_tokens_with_scoring(c_logits, u_logits, gen_config)
        ...
        if use_cfg:
            batch_input_ids[B+i:B+i+1, :, :t_len] = sample_tokens
```

**디폴트로 `guidance_scale=0` 으로 못 가나?** OmniVoice 의 zero-shot voice clone 품질은 CFG 의존도가 매우 높다. 본 사이클은 *유저가 명시적으로 끌 수 있는 옵션* 으로만 노출 (`tts_omnivoice.guidance_scale=0` config). 디폴트는 2.0 유지.

---

## 3. Voice reference 재토큰화 비용

[omnivoice.py 의 `_prepare_inference_inputs`](../../omnivoice/omnivoice_core/models/omnivoice.py) 는 매 호출마다:
1. ref_text 토크나이즈 (HF tokenizer, fast — μs)
2. ref_audio 가 있으면 `audio_tokenizer.encode(...)` — **GPU 호출, 수십~수백 ms**
3. instruct/lang prompt template 채워넣기 (μs)

우리 워크로드: 동일 voice profile (`paimon_ko`, `mao_pro`) 로 수십~수백번 합성. → ref_audio 의 토큰 시퀀스는 *불변*. 캐시 키 = `(profile_path, profile_mtime, lang)`.

**캐시 위치 결정.** `omnivoice_core/models/omnivoice.py` 직접 패치 vs `server/engine.py` wrapper.

- 직접 패치는 upstream sync 시 conflict 위험.
- wrapper 가 정답: `EngineState` 가 자체적으로 `_voice_cache: dict[tuple, dict]` 를 두고, `synthesize` 진입 시 캐시 hit 면 사전에 `model.set_inputs(...)` 같은 우회 — 하지만 OmniVoice API 는 그 우회로를 제공하지 않음 → **monkey-patch** 또는 **subclass**.
- 추천: `omnivoice/server/cached_model.py` 신설, `class CachedOmniVoice(OmniVoice)` 가 `_prepare_inference_inputs` 를 오버라이드하여 캐시 키에 따라 deepcopy 반환. (deepcopy 가 부담스러우면 `clone()` 으로 대체.)

---

## 4. Cold start 의 정확한 원인

P9. 모델 로드는 lifespan 에서 끝난다. 그러나 **첫 forward** 에서:
- cuDNN heuristic search (algo selection) — 수백 ms
- 첫 CUDA mem 할당 (tensor cores warmup) — 수백 ms
- 첫 attention kernel JIT (SDPA) — 수백 ms
- (torch.compile 적용 시) **5~60s 컴파일**

→ Lifespan 끝에 `model.generate(text="안녕하세요", ...)` 1~2회 더미 호출을 *반드시* 추가. 이때:
- 한국어/영어 각 1회씩 (lang-specific tokenizer warmup)
- `audio_tokenizer.encode/decode` warmup
- `torch.cuda.empty_cache()` 후 `synchronize()`

코드 위치: [omnivoice/server/main.py](../../omnivoice/server/main.py) 의 lifespan (현재 모델 로드 직후) 에 추가. 동안 `/health` 는 `status: "warming"` 으로 노출 → 어댑터의 `health_check` 가 200 이지만 `status != "ok"` 면 잠깐 backoff.

---

## 5. 어댑터 이중 직렬화 — 정확한 라인

(파일을 다시 확인할 필요가 있는 부분이지만, summary 와 grep 결과로 충분히 식별 가능.)

[omnivoice_engine.py](../../backend/service/vtuber/tts/engines/omnivoice_engine.py) 의 모듈 상단:

```python
_synthesis_lock = asyncio.Lock()   # ★ 이게 문제
```

그리고 `synthesize_stream` 내부:

```python
async with _synthesis_lock:
    async with httpx.AsyncClient(...) as client:
        resp = await client.post(...)
        ...
```

서버 [server/engine.py](../../omnivoice/server/engine.py) 의 `synthesize`:

```python
async with self.semaphore:
    return await loop.run_in_executor(None, self._generate_sync, ...)
```

→ **둘 다 동일한 직렬성 보장**. 어댑터 락은 **즉시 제거**.

단, 제거 전에 *왜 추가됐었는지* 추적 필요. 추정: 서버 단 Semaphore 가 도입되기 전 단계에서 클라이언트가 GPU OOM 보호 차원으로 넣었던 흔적. 본 사이클에서는 서버 Semaphore 가 정답이므로 제거.

---

## 6. dtype 선택의 미묘함

| GPU | fp16 | bf16 | tf32 |
|-----|------|------|------|
| GTX 1070 (sm_61) | ✅ (cudnn 경로) — 텐서코어 없음 | ❌ (소프트웨어 fallback, 느림) | ❌ |
| RTX 3090 (sm_86) | ✅ (텐서코어) | ✅ (텐서코어, NaN 안전) | ✅ |
| RTX 4090 (sm_89) | ✅ | ✅ | ✅ |

OmniVoice 모델은 long-context attention + 다층 FFN. fp16 은 attention softmax 의 overflow 발생 가능. bf16 가능 환경에서는 bf16 로 자동 전환.

**구현.**

```python
# server/settings.py
OMNIVOICE_DTYPE: str = "auto"   # auto | float16 | bfloat16 | float32

# server/engine.py
def resolve_dtype(setting: str, device: torch.device) -> torch.dtype:
    if setting != "auto":
        return getattr(torch, setting)
    if device.type != "cuda":
        return torch.float32
    cap = torch.cuda.get_device_capability(device)
    if cap >= (8, 0):
        return torch.bfloat16
    return torch.float16
```

---

## 7. `torch.compile` 적용 전제

`mode="reduce-overhead"` 는 CUDA Graphs 를 *내부적으로* 사용 — input shape 가 안정적이어야 한다. OmniVoice 의 forward 는 `(2*B, C, T_total)` 인데:

- **B**: 우리 워크로드에서 1 고정 (single-session). micro-batch 도입 전까지 안정.
- **C** (num_codebook): 모델 config 에 fix.
- **T_total** (= max_c_len = ref_len + target_len): **호출마다 가변** ← 여기가 문제.

**해결책.** Shape bucketing.

```python
# 가까운 32의 배수로 padding
def bucket_T(T: int) -> int:
    return ((T + 31) // 32) * 32
```

각 bucket 별로 `torch.compile` 결과가 캐시됨 (dynamo). 처음 만나는 bucket 마다 한 번씩 컴파일 비용 — warmup 단계에서 [128, 256, 384, 512, 768, 1024] 미리 트리거.

`fullgraph=False` 로 시작 — Python control flow (CFG 분기 등) 허용.

---

## 8. CUDA Graphs 명시 적용 (O6, 옵션)

`torch.compile(mode="reduce-overhead")` 로 충분할 수 있으나, 더 빡빡한 제어가 필요하면 직접 `torch.cuda.CUDAGraph()`. 그러나:

- 입력 텐서가 *같은 메모리 주소*여야 한다 → `batch_input_ids` 를 graph capture 전에 reuse pool 로 잡아야 함.
- 그런데 `_generate_iterative` 는 `batch_input_ids[i, :, c_len-t_len:c_len] = sample_tokens` in-place update 가 매 step 발생 → 이는 동일 텐서이므로 OK.
- shape 가 bucket 별로 다르면 graph 도 bucket 별로 capture.

**결정.** Phase 3 에서는 `torch.compile` 만 적용. CUDA Graphs 직접 사용은 measurement 후 추가 이득이 ≥10% 일 때만.

---

## 9. FlexAttention (O12) 호환성

- import 가 이미 `omnivoice_core/models/omnivoice.py` 상단에 존재 (`_flex_attention_available`).
- 단, 모델은 4-D bool `attention_mask` 를 직접 SDPA 에 전달하는 구조. FlexAttention 으로 전환하려면 `BlockMask` 변환 함수 + `mask_mod` 정의 필요.
- 현재 attention 패턴은 *블록 대각 + cond/uncond split* — `mask_mod = lambda b, h, q, k: attention_mask[b, 0, q, k]` 로 표현 가능하지만 이는 dense mask 해석이라 FlexAttention 의 진짜 이득(sparsity) 을 못 살림.
- → **본 사이클 비목적**. 향후 사이클에서 마스크 패턴 분석 후 별도로.

---

## 10. 측정 도구 (Phase 0)

`Geny/omnivoice/scripts/bench.py` 신설:

```python
# 사용: docker compose exec omnivoice python -m server.bench --runs 10 --texts texts_ko.txt
import time, json, statistics, asyncio, soundfile as sf
from server.engine import EngineState
from server.settings import Settings

async def main():
    settings = Settings()
    engine = await EngineState.create(settings)
    await engine.warmup()  # Phase 1 결과물

    samples = open("texts_ko.txt").read().splitlines()
    rows = []
    for run in range(10):
        for text in samples:
            t0 = time.perf_counter()
            audio, sr = await engine.synthesize(text=text, voice_profile="paimon_ko")
            t1 = time.perf_counter()
            dur = len(audio) / sr
            rows.append({
                "text_len": len(text), "audio_dur": dur,
                "wall": t1-t0, "rtf": (t1-t0)/dur,
                "gpu_peak_mb": torch.cuda.max_memory_allocated()/1e6,
            })
            torch.cuda.reset_peak_memory_stats()
    rtfs = [r["rtf"] for r in rows]
    print(json.dumps({
        "rtf_mean": statistics.mean(rtfs),
        "rtf_p50": statistics.median(rtfs),
        "rtf_p95": sorted(rtfs)[int(len(rtfs)*0.95)],
    }, indent=2))
```

산출 결과는 [benchmarks.md](benchmarks.md) 표에 행으로 누적. 각 Phase 완료마다 갱신.

---

## 11. 공식 OmniVoice 의 비공식 가속 정보

- upstream README 는 추론 가속 명시적 가이드 없음. `OmniVoiceGenerationConfig` 의 `num_step` 이 유일한 dial.
- Paper (HiggsAudio v2 family) 도 distillation 변형은 후속 작업으로 언급, 본문 내 가속 패치 없음.
- → **우리가 직접 측정 + 적용**. 본 사이클 산출 데이터는 향후 OmniVoice issue 로 환류 가능 (별도 사이클).

---

## 12. Persistent residency — VRAM 점유 철학 (Phase 1d 근거)

> **출발점.** 본 컨테이너는 GPU 의 *유일한 텐션트* (단일 모델, 단일 서비스, 단일 GPU). VRAM 을 다른 프로세스와 공유할 동기가 없다. → vLLM 류의 *시작 시 일괄 점유 + 절대 해제 안 함* 정책이 그대로 정당화된다.

### 12.1 PyTorch CUDA caching allocator 의 비용

매 호출마다 발생할 수 있는 비용:

1. **`cudaMalloc` 직접 호출.** 첫 호출이거나 caching pool 에 적합한 크기가 없을 때 → ms 단위 latency, **비결정적**.
2. **단편화로 인한 `num_alloc_retries`.** `torch.cuda.OutOfMemoryError` 직전 단계에서 `empty_cache` + 재시도. 통계에 잡힘.
3. **새 segment 생성.** `expandable_segments=False` (기본) 면 segment 단위 확장이 비싸다.
4. **합성 길이 변동에 따른 `logits_buf` 재할당.** 가장 큰 텐서이므로 재할당 시 GPU 시간 수 ms.

→ `_generate_iterative` 가 *고정-shape* 라는 점을 활용해 **MAX_T 기준 1회 할당 → 슬라이스 뷰 사용** 으로 위 4가지를 모두 제거.

### 12.2 왜 in-place 슬라이스 뷰가 정답인가

`_generate_iterative` 의 코드를 다시 보면:

```python
batch_input_ids[i, :, c_len-t_len:c_len] = sample_tokens   # in-place
batch_input_ids[B+i, :, :t_len]          = sample_tokens   # in-place
```

이미 *in-place 의미론* 으로 작성되어 있다. 즉 외부에서 텐서 buffer 만 적절히 슬라이스해서 넣어주면 모델 코드 수정 없이 영구 점유 정책으로 전환 가능. `cached_model.py` 의 wrapper 가 `super()._generate_iterative` 호출 직전 `self._workspace.batch_input_ids[:2*B, :, :T_total].zero_()` (or mask 채움) 으로 초기화 + 동일 view 를 모델에 전달.

**불변 검증.** `compare_audio --atol 1e-4` 가 hit/miss 양쪽에서 PASS = 슬라이스 뷰 사용이 새 텐서 사용과 *수치 동치* 임을 자동으로 확인.

### 12.3 Pinned host buffer 의 이득

- **현재.** `audio_gpu.cpu().numpy()` 는 (a) host malloc, (b) implicit `cudaStreamSynchronize`, (c) D2H copy, (d) GIL 잡고 numpy 변환. 합쳐서 ms~수십ms.
- **개선.** 사전 할당된 pinned `int16` 텐서로 `to(host_buf, non_blocking=True)` + `d2h_stream.synchronize()` 후 `host_buf.numpy()` (zero-copy). **(a)(d) 제거, (b)(c) 시간 단축**.
- 추가 효과: D2H 전용 stream 으로 **다음 합성의 GPU 컴퓨트와 오버랩** 가능 (Phase 4 streaming 단계에서 진가 발휘).

### 12.4 Multi-shape warmup 의 이유

cuDNN/cuBLAS 는 (input shape, dtype, layout) 별로 *최적 알고리즘*을 첫 호출 때 탐색하고 결과를 캐시한다 (`torch.backends.cudnn.benchmark=True`). 첫 short / medium / long 호출이 각각 cold gap 을 만들면 사용자 체감이 들쭉날쭉. → lifespan 에서 3 bucket 모두 1회씩 합성하여 알고리즘 캐시 + workspace + JIT autotune 결과를 모두 확정.

`_generate_iterative` 가 32 step 동안 *동일 shape* 인 점을 떠올리면, 한 번 warmup 된 bucket 은 **32 forward 모두 cache hit** → cold gap 0.

### 12.5 GPU memory budget — GTX 1070 (8 GB) 분배

| 구성 요소 | 추정 (GB) | 비고 |
|-----------|-----------|------|
| 모델 가중치 (omnivoice fp16) | ~3.0 | 실측 후 확정 |
| `GenerationWorkspace` (max_T=1500, B=1, V=수만) | ~1.0~1.5 | logits_buf 가 가장 크다 |
| ref-cache (8 voice profile × prepared inputs) | ~0.2 | 작음 |
| Pinned host pool (4 slots × 30s × 24kHz × int16) | ~0.0 | host 에 있음, GPU 무관 |
| cuDNN/cuBLAS workspace | ~0.5 | benchmark=True 시 |
| 디스플레이/시스템 점유 (Wayland, 다른 컨테이너) | ~0.5 | 호스트 의존 |
| **합계 (예약 목표)** | **~5.5 GB** | `OMNIVOICE_GPU_MEM_FRACTION=0.7` 정도가 안전. 실측으로 0.9 까지 끌어올림 검토 |

단편화 0 + 새 할당 0 이라는 영구 점유 정책의 결정적 이점은 *p95/p99 latency 안정화*. 평균은 비슷해도 "가끔 0.5초씩 튀는" 사례가 사라진다 — 스트리밍 큐가 사용자에게 노출되는 시점에서 결정적으로 중요.
