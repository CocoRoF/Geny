# 20260422_OmniVoice_Perf — OmniVoice 인퍼런스 극대화 + 문장 스트리밍 큐

> **사이클 시작:** 2026-04-22
> **대상 범위:** `Geny/omnivoice/**`, `Geny/backend/service/vtuber/tts/**`, `Geny/backend/controller/tts_controller.py`, `Geny/frontend/src/store/useVTuberStore.ts`, `Geny/frontend/src/lib/audioManager.ts`, `Geny/frontend/src/components/live2d/VTuberChatPanel.tsx`
> **선행:** [20260422_OmniVoice/index.md](../20260422_OmniVoice/index.md) (마이크로서비스 골격)
> **결과물:** 본 디렉터리의 [analysis.md](analysis.md), [plan.md](plan.md), [streaming.md](streaming.md), [benchmarks.md](benchmarks.md), [environment.md](environment.md)
>
> **하드 제약 (반드시 준수).**
> 1. **추론 결과 품질 손실 0.** 출력 오디오 파형이 *비트 동등(bit-equivalent)* 까진 아니더라도, 청취 평가에서 baseline 과 통계적 차이가 없어야 한다. 따라서 `num_step` 감소, `guidance_scale` 변경, dtype 강등 등 *모델 출력 분포를 바꾸는* 최적화는 **디폴트 OFF, 옵트인 옵션**으로만 노출한다.
> 2. **운영 GPU = GTX 1070 (Pascal sm_61) 단일.** Ampere+ 전제의 최적화(`bf16`, `torch.compile`+inductor, FlexAttention, CUDA Graphs 의 강한 모드)는 본 사이클에서 *디폴트 비활성*. Pascal 에서 검증된 항목만 운영 경로에 진입.
> 3. **개발 환경에 GPU 없음.** 모델 추론 벤치마크는 *별도 GPU 호스트* 에서 컨테이너 단위로 원격 수행. dev 에서는 CPU 로 가능한 단위 테스트(분할 규칙, 큐 자료구조, 어댑터 mock, 컨트롤러 라우팅) 만. 자세한 워크플로우는 [environment.md](environment.md).
> 4. **영구 GPU/VRAM 점유는 *허용되며 권장*.** vLLM 이 KV-cache 풀로 VRAM 을 시작 시점에 한 번 잡고 들고 가듯, omnivoice 컨테이너도 *서비스 수명 내내* 모델 가중치 + workspace 텐서 + reference-embedding 캐시 + pinned host 버퍼 + CUDA 스트림을 **시작 시 일괄 할당하고 해제하지 않는다**. per-request allocator 호출/단편화/cold path 를 모두 제거하는 것이 본 사이클의 핵심 철학. 단, *전체* VRAM 점유는 명시된 예산(아래 KPI) 안. 컨테이너가 살아 있는 동안 사용 가능한 *유일한* 텐션트는 omnivoice 라는 가정 (단일 GPU, 단일 모델 서비스).

---

## 0. 개요 — 무엇을, 왜, 어떻게

### 무엇을

1. **인퍼런스 성능 극대화 — 단, 출력 품질 손실 0.** 운영 GPU(GTX 1070, sm_61) 에서 RTF(Real-Time Factor) 를 *품질을 바꾸지 않는* 최적화만으로 **현재 ~3-8x → 목표 ≤1.5x (스트레치 ≤1.0x)** 로 끌어내린다. 품질을 바꾸는 최적화(num_step↓, CFG 스킵 등)는 *옵트인 옵션*으로만 노출하고 디폴트 경로에는 적용하지 않는다.
2. **문장 단위 점진 처리.** 어시스턴트 LLM 토큰이 yield 되는 시점부터 *문장 경계*를 감지해 **즉시 TTS 큐에 enqueue → 순서 보장 재생** 파이프라인을 만든다. 사용자가 첫 음성을 듣기까지의 **TTFA(Time To First Audio)** 를 LLM 응답 완료 시점이 아닌 **첫 문장 완료 시점**으로 단축. 이 축은 RTF 자체를 줄이지 않더라도 *체감 latency* 를 크게 개선한다 — 품질에 영향 없음.

### 왜

- 현 상태: `OmniVoiceEngine.synthesize_stream` 은 전체 어시스턴트 메시지를 한 번에 받아 단일 POST `/tts` 로 전송 → 서버는 *전체 오디오 생성 완료까지 블로킹* → 응답 본문 한 덩어리 반환. 즉 **TTFA = 전체 텍스트 합성 시간**.
- 모델 자체도 비효율: warm-up 없음, `torch.compile` 미적용, voice clone reference 가 매 호출마다 재토큰화, CFG 가 `guidance_scale=0` 일 때도 2×B 배치, num_step=32 고정.
- 어댑터 단(`omnivoice_engine.py`)에 모듈 락 + 서버 단 `Semaphore(1)` 의 **이중 직렬화**가 있고, 어댑터 락이 우선 잡혀 서버의 큐잉 정책이 효과 없음.
- 프론트는 `audioManager` 가 큐를 갖고 있지만 백엔드가 한 번에 하나의 enqueue 만 보내므로 큐가 가진 *prefetch / crossfade* 잠재력을 못 살림.

### 어떻게

- **세 축으로 분해.** (a) 모델 단계 (omnivoice 컨테이너 내부), (b) 서비스 단계 (FastAPI 라우팅 + 큐), (c) 통합 단계 (Geny backend ↔ 프론트 SSE/스트림).
- **순수 가산적 (additive).** 기존 `provider=edge_tts` / `gpt_sovits` 경로는 0줄 영향. 모든 신규 동작은 `tts_omnivoice.streaming_mode` 플래그 등으로 옵트인.
- **시작 시 모든 자원 일괄 점유.** lifespan 단계에서 (i) 모델 가중치 GPU 적재 → (ii) `_generate_iterative` 의 *최대 shape* 워크스페이스 텐서(`batch_input_ids`, `attention_mask`, `logits` 출력 버퍼) 사전 할당 → (iii) 자주 사용하는 voice profile 1~3개의 reference 임베딩 사전 계산/캐시 → (iv) 출력 PCM 용 pinned host 버퍼 풀 할당 → (v) 워크로드별 shape bucket(짧음/중간/긺) warmup 합성 — *이 모든 것이 끝난 뒤에야* `/health` 가 `phase: ok`. 이후 런타임은 새 큰 할당이 발생하지 않는 *정상 상태(steady state)* 만 본다.
- **측정 기반.** Phase 0 에서 **벤치마크 스크립트** 를 먼저 만들어 baseline 을 박제 → 각 최적화의 효과를 RTF / TTFA / *steady-state VRAM* / cold-warm gap 으로 정량 검증 → [benchmarks.md](benchmarks.md) 에 누적 기록.

### 비목적

- vLLM / SGLang 같은 *AR LLM 전용 서빙 프레임워크* 도입 — OmniVoice 는 **MaskGIT-style non-AR iterative diffusion** 이라 PagedAttention/KV-cache/continuous batching 의 전제(autoregressive token-by-token decoding)가 성립하지 않는다. 본 사이클은 *non-AR diffusion 에 적합한* 최적화만 다룬다.
- 모델 재학습/distillation (예: num_step 4-step distill) — 본 사이클 외.
- **`num_step` 의 디폴트 변경.** 청취 평가 기반의 품질 보장 절차(별도 사이클) 가 통과하기 전까지는 *옵트인 옵션* 으로만 둔다. 디폴트는 upstream 권장값 32 그대로.
- **`guidance_scale` 의 디폴트 변경.** CFG 스킵(O3) 은 *코드 분기* 만 추가하고 디폴트는 2.0 유지. 사용자가 명시적으로 0 으로 두었을 때만 발동.
- **dtype 강등.** Pascal 에서 fp16 이 이미 최적이므로 본 사이클은 *fp16 고정*. bf16 자동 선택(O10) 은 비활성화 (Ampere+ 인프라 도입 시 별도 사이클).
- `gpt_sovits` 엔진 동등 최적화 — 본 사이클은 OmniVoice 한정.
- 다중 GPU / multi-replica horizontal scaling — 단일 GPU 가정.
- **Ampere+ 전용 가속.** `torch.compile` + inductor, FlexAttention, BlockMask, CUDA Graphs 강한 모드는 sm_61 에서 회귀 위험 (inductor 의 Pascal 지원 미약, BlockMask 가 sm_70+ 권장). 코드는 *capability 가드* 뒤로 숨겨 추후 GPU 교체 시 자동 활성되게만 준비, 본 사이클의 측정/디폴트 경로에는 포함하지 않는다.
- **VRAM 절약을 위한 lazy-load / on-demand offload / weight streaming.** 본 사이클은 그 정반대 — *최대 사전 점유*. CPU↔GPU swap, accelerate 의 `device_map='auto'` 류 자동 분산, `torch.cuda.empty_cache()` 정기 호출 모두 비목적. (단일 모델, 단일 GPU, 단일 컨테이너 가정.)

---

## 1. 통증 지점 (Pain Points)

| # | 위치 | 증상 | 영향 | 측정 근거 |
|---|------|------|------|-----------|
| P1 | [omnivoice/server/api.py](../../omnivoice/server/api.py#L35-L200) `POST /tts` | 응답이 *전체 오디오 완료* 후 한 덩어리 반환 | TTFA = 합성 전체 시간 | 사용자 보고 "현재 속도가 매우 느린 심각한 문제" |
| P2 | [omnivoice/omnivoice_core/models/omnivoice.py](../../omnivoice/omnivoice_core/models/omnivoice.py#L1145-L1300) `_generate_iterative` | num_step=32 회 forward 패스, 매번 2×B (CFG) 배치 | GPU 시간의 95%+ | 기본 config `num_step=32`, `guidance_scale=2.0` |
| P3 | 동상, `_prepare_inference_inputs` | 매 호출마다 voice clone reference 텍스트/오디오 재토큰화 | per-call 100ms~수백ms 낭비 | 현 코드는 캐시 없음 |
| P4 | [omnivoice/server/engine.py](../../omnivoice/server/engine.py) `EngineState.synthesize` | 첫 호출 시 cold latency 매우 큼 (CUDA 컴파일/메모리 할당) | 첫 발화가 지연 / 타임아웃 위험 | 사용자 보고 "처음 한 번은 성공... 이후 안 됨" |
| P5 | [backend/service/vtuber/tts/engines/omnivoice_engine.py](../../backend/service/vtuber/tts/engines/omnivoice_engine.py) | 모듈 레벨 `_synthesis_lock` + 서버 `Semaphore(1)` 이중 직렬화 | 큐잉 책임 분산, 디버깅/확장 어려움 | 코드 직접 확인 |
| P6 | [backend/service/vtuber/tts/tts_service.py](../../backend/service/vtuber/tts/tts_service.py#L60-L170) `speak()` | 입력 `text` 전체를 그대로 단일 엔진 호출에 전달 | 문장 단위 파이프라이닝 불가 | 함수 시그니처 |
| P7 | [backend/controller/tts_controller.py](../../backend/controller/tts_controller.py#L69-L160) `POST /agents/{sid}/speak` | request body 가 단일 `text` 필드, 한 번의 `StreamingResponse` 만 반환 | 클라이언트가 문장 단위 호출하려면 N 번 fetch 필요 | 코드 직접 확인 |
| P8 | [frontend/src/components/live2d/VTuberChatPanel.tsx](../../frontend/src/components/live2d/VTuberChatPanel.tsx#L240-L260) | 어시스턴트 메시지 `status='executing'` *완료 시점*에만 `speakResponse` 1회 호출 | 첫 음성 = LLM 전체 응답 완료 + 합성 완료 이후 | 244, 153번 라인 |
| P9 | [omnivoice/Dockerfile](../../omnivoice/Dockerfile) / 런타임 | 모델 로드 후 warmup 합성 없음 → 첫 진짜 호출이 cold | 첫 응답에서만 latency 폭증 | Dockerfile / lifespan 코드 |
| P10 | omnivoice 모델 dtype | 현재 fp16 사용. Pascal 은 fp16 텐서코어 없음. RTX 30/40 은 bf16 가 안정적 | Pascal: fp16 손실 적음 / Ampere+: bf16 가 더 안전 + 비슷한 속도 | 코드 확인 |
| P11 | OmniVoice 기본 chunk threshold = 30s, chunk_duration = 15s | 짧은 어시스턴트 응답(보통 <15s) 은 chunked 경로 미진입 → *모델 내부 batch* 도 활용 못함 | 작은 청크/문장 batch coalescing 의 기회 손실 | [omnivoice.py L787-L902](../../omnivoice/omnivoice_core/models/omnivoice.py#L787-L902) |
| P12 | 어댑터 `httpx` POST → 응답 본문 한 번에 다운로드 | 서버가 chunked transfer 보내도 어댑터가 ` await resp.aread()` 로 기다림 | 스트리밍 협상이 의미없음 | [omnivoice_engine.py](../../backend/service/vtuber/tts/engines/omnivoice_engine.py) 코드 |

---

## 2. 모델/서버 심층 분석 — 왜 vLLM 이 안 통하는가

OmniVoice 의 디코더는 [`_generate_iterative`](../../omnivoice/omnivoice_core/models/omnivoice.py#L1145-L1300) 에서 다음 패턴으로 동작한다:

```
for step in range(num_step=32):                        # diffusion-like outer loop
    batch_logits = self(                              # ★ 1 forward pass over (2*B, C, T_total)
        input_ids=batch_input_ids,                    #   (cond + uncond stacked → CFG 2x batch)
        audio_mask=batch_audio_mask,
        attention_mask=batch_attention_mask,          # pre-allocated bool 4-D mask
    ).logits.to(torch.float32)
    for i in range(B):
        # mask k tokens this step (schedule), unmask top-k by score
        ...
        batch_input_ids[i, :, c_len-t_len:c_len] = sample_tokens   # in-place update
        batch_input_ids[B+i, :, :t_len]          = sample_tokens   # in-place update
```

핵심 관찰:

1. **Non-autoregressive.** 모든 step 에서 *전체 시퀀스* 가 한 번에 forward 된다. 토큰 추가가 아니라 *언마스킹*. → **KV-cache 가 의미 없다** (매 step 마다 입력이 부분적으로 갱신되어 cache invalidation 비율이 매우 높음).
2. **고정 shape.** `B`, `max_c_len`, `target_lens` 는 generate() 시작 시 결정 → 32 step 동안 **shape 불변**. → **CUDA Graphs** 와 **`torch.compile(mode="reduce-overhead")`** 의 *최적 시나리오*. (vLLM 의 가치는 가변 shape 동적 batching 인데, 우리는 정반대 방향이 이득.)
3. **Forward pass 가 전체 시간의 95%+.** Logits sampling / scoring / topk 는 GPU on-device 연산. host↔device 전송은 결과 토큰 텐서 한 번뿐.
4. **CFG (classifier-free guidance) 는 항상 2×B 배치.** `guidance_scale=0` 일 때도 uncond 절반이 돌아간다 — 의미없는 50% 낭비. (`_predict_tokens_with_scoring` 첫 분기 보면 guidance_scale=0 시 c_logits 만 사용.)
5. **`_flex_attention_available` 가 import 되어 있지만 기본은 SDPA.** `attention_mask` 가 4-D bool tensor 로 직접 들어가는 경로 → 단순 SDPA fallback. FlexAttention 은 이런 *블록 스파스* 패턴에 강함.
6. **Voice clone 의 `_prepare_inference_inputs` 는 매 호출마다 ref_audio 재인코딩.** 동일 voice profile 을 재사용하는 우리 워크로드에서 이 비용은 캐시로 100% 제거 가능.

→ **요약.** OmniVoice 는 *고정-shape, non-AR, CFG-batched, 32-step* 디코더. AR LLM 서빙 최적화(KV-cache 페이징/continuous batching) 는 부적합. 대신 **정적 shape 컴파일(torch.compile + CUDA Graphs)**, **CFG 조건부 스킵**, **참조 임베딩 캐시**, **warm-up**, **문장 단위 micro-batching** 이 정공법.

---

## 3. 최적화 전략 (impact × effort 매트릭스)

> **분류 기준.**
> - **Tier-A (디폴트 ON, 품질 동치).** 모델 출력 분포를 바꾸지 않는다. *수학적 동치* 또는 *호출 경계의 부수적 비용 제거*. → 디폴트 활성, 본 사이클의 *측정/검증 대상*.
> - **Tier-B (옵트인, 품질 변경 가능).** 품질 영향이 있을 수 있어 사용자 명시적 ON 시에만 동작. *코드 분기만 추가*, 디폴트 경로에는 영향 없음.
> - **Tier-C (Pascal 제외, 향후).** sm_70+ 가 전제. 가드 뒤로 숨겨 두고 본 사이클에서는 *측정 대상 아님*.
>
> 예상 효과는 GTX 1070 (sm_61) 기준의 *추정치*. 실측은 staging GPU 호스트에서 [benchmarks.md](benchmarks.md) 표에 누적 (자세한 절차는 [environment.md](environment.md)).

| ID | Tier | 기법 | 적용 위치 | GTX 1070 예상 효과 | 품질 영향 | 의존성 |
|----|------|------|-----------|-------------------|-----------|--------|
| **O1** | A | Lifespan **warm-up** 합성 1~2회 | [server/main.py](../../omnivoice/server/main.py) lifespan | 첫 호출 cold-latency 제거 (수 초→0) | 없음 (호출 외부 효과) | — |
| **O2** | A | 어댑터 모듈 락 제거 → 서버 Semaphore 단일 책임 | [omnivoice_engine.py](../../backend/service/vtuber/tts/engines/omnivoice_engine.py) | 직렬화 오버헤드 제거 (μs 단위, 안정성 ↑) | 없음 (직렬성 동일) | — |
| **O4** | A | **Voice reference 임베딩 캐시** (`{(profile_path, mtime, lang) → prepared_inputs}`) | server wrapper (`cached_model.py` 신설) | per-call 100~수백ms 절감 — text 짧을 때 효과 큼 | 없음 (동일 입력→동일 출력) | profile dir mtime 무효화 |
| **O11** | A (조사 후) | Audio tokenizer encode/decode GPU 상주 — `.cpu().numpy()` 왕복 제거 | omnivoice_core 경계 | per-call 50~100ms (실측 후 확정) | 없음 (수치 동치) | spike 로 실제 왕복 여부 확인 선행 |
| **O13** | A | httpx **keep-alive 풀** 재사용 (어댑터의 매 호출 `AsyncClient` 생성 제거) + chunked transfer 협상 | [omnivoice_engine.py](../../backend/service/vtuber/tts/engines/omnivoice_engine.py) | per-call 수십ms + TTFA 기여 | 없음 | — |
| **O14** | A | **Persistent workspace 텐서 사전 할당** — `_generate_iterative` 의 `batch_input_ids` / `attention_mask` / `logits` / scoring buffer 를 *최대 T_total* 기준으로 lifespan 에서 1회 할당, 매 호출 *in-place* 재사용. allocator 호출 0, 단편화 0. | `cached_model.py` + engine init | per-call 5~30ms (allocator 비용) + 안정적 jitter 감소 | 없음 (값 덮어쓰기, shape 동치) | O4 와 함께 [analysis.md §11](analysis.md#11-persistent-residency-vram-점유-철학) |
| **O15** | A | **Pinned host 버퍼 풀** — 출력 PCM/wav 직렬화용 host 메모리를 `torch.empty(..., pin_memory=True)` 로 사전 할당, `.cpu()` 가 아닌 `to('cpu', non_blocking=True)` + 풀 재사용. | server output path | per-call 1~5ms + GPU↔host 오버랩 | 없음 (수치 동치) | — |
| **O16** | A | **Multi-shape warmup** — lifespan 에서 짧음/중간/긺 3 bucket (T_total ≈ 256/512/1024) × cond+uncond 각각 1회씩 합성하여 cuDNN/cuBLAS 알고리즘 선택 캐시 + JIT autotune + workspace 확정. | `engine.warmup()` | 첫 *bucket-별* 호출의 cold latency 0 | 없음 (호출 외부 효과) | O1 의 강화판 |
| **O17** | A | **Allocator/스트림 정책 고정** — `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb=128`, `torch.cuda.set_per_process_memory_fraction()` 로 예산 명시, 보조 CUDA stream 1~2개 lifespan 에서 생성하여 입력 H2D 와 출력 D2H 를 컴퓨트와 오버랩. | engine init / Dockerfile env | jitter 감소, cold path 제거 | 없음 (수치 동치) | — |
| **P1** | A | **문장 스트리밍** (TTFA 단축) | 백엔드 큐 + 프론트 SentenceAccumulator | 체감 latency 대폭 ↓ (RTF 자체는 불변) | 없음 — 동일 텍스트 동일 합성, 재생 시점만 빠름 | §4 |
| **O3** | B | CFG 조건부 스킵 — `guidance_scale==0` 시 cond-only forward (B 배치) | [omnivoice.py L1145+](../../omnivoice/omnivoice_core/models/omnivoice.py#L1145) `_generate_iterative` | 1.8~2× | **있음** (CFG=0 의 출력은 다름). 디폴트 `gs=2.0` 유지 → 사용자 명시 시만 발동 | vendored copy patch |
| **O7** | B | Adaptive `num_step` 옵트인 | server schema + config 노출 | 1.3~2× | **있음**. 청취 A/B 평가 별도 사이클에서 통과 후에 디폴트화 가능 | 품질 평가 절차 |
| **O5** | C (Pascal 가드 OFF) | `torch.compile(mode="reduce-overhead")` | server engine init | sm_61 에서는 0~+5% (또는 회귀). sm_70+ 에서 1.3~2× | inductor 코드젠 회귀로 인한 *간접* 영향 가능 → Pascal 비활성 | torch ≥2.6 OK |
| **O6** | C | CUDA Graphs 명시 capture | server engine | sm_70+ 에서 +10~30% | 동치이나 capture 검증 필요 | static buffers |
| **O9** | C | Micro-batch coalescer (B>1 묶음) | server | 단일 사용자 시 의미 없음. 다중 동시세션 전제 | 동치 (배치 padding mask 정확하면) | 본 환경 multi-user 미발생 |
| **O10** | C | bf16 자동 선택 (Ampere+) | settings | Pascal 무관 (fp16 유지) | dtype 변경은 미세 차이 → Pascal 에선 강제 fp16 | — |
| **O12** | C | FlexAttention / BlockMask | omnivoice_core | sm_70+ 만 의미 | mask 변환 검증 필요 | torch ≥2.5 |

**우선순위 (1차 캠페인, Pascal-safe).**

1. **Tier-A 만으로 가능한 모든 것.** O1 → O2 → O17 (allocator 정책) → O16 (multi-shape warmup) → O14 (workspace 사전 할당) → O15 (pinned host) → O13 (httpx keep-alive) → O4 (ref-cache) → (O11: 조사 후) → P1 (문장 스트리밍).
2. **Tier-B 는 *코드만* 머지.** O3 / O7 의 분기를 추가하되 디폴트 OFF, 옵션으로만 노출. 청취 평가는 별도 사이클.
3. **Tier-C 는 *capability 가드* 뒤로 숨겨만 두기.** sm_61 에선 무조건 비활성. 미래 GPU 교체 시 자동 활성.

**Pascal 단일 환경에서의 솔직한 RTF 전망.**

원천적으로 sm_61 은 fp16 텐서코어가 없고 SDPA 의 fp16 backward kernel 은 cuDNN 일반 경로다. 모델 자체의 산술 강도(arithmetic intensity)는 그대로이므로, *Tier-A 만으로* 얻을 수 있는 RTF 개선은 **per-call 부수 비용 제거 + allocator/host-transfer 오버랩 + 첫 호출 cold 제거** 가 대부분. 모델 forward 자체를 빠르게 하는 수단(compile/graphs/bf16/distill)은 Pascal 에서 제한적이거나 부재. 따라서 *지속 RTF* 는 baseline 대비 **-15~30% 수준** 이 현실적 목표이고, 사용자 체감 개선의 대부분은 **TTFA 단축(문장 스트리밍, P1) + cold-warm gap 제거(O14~O17)** 에서 나온다. 영구 점유 정책은 *분산 jitter* 를 줄여 RTF p95/p99 의 안정성에 결정적으로 기여한다 — 평균은 비슷해도 "가끔 느려지는" 사례가 사라진다.

---

## 4. 문장 스트리밍 큐 아키텍처 (요약)

상세 설계는 [streaming.md](streaming.md). 여기서는 데이터 플로우만:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Frontend (VTuberChatPanel)                                                     │
│   LLM SSE token chunks ──▶ SentenceAccumulator ──▶ for each finished sentence: │
│                                                     POST /api/tts/agents/{sid}/│
│                                                          speak/sentence        │
│                                                          (text, seq, total?)   │
│   audioManager.enqueue(response, sessionId, seq) — seq 보장 재생              │
└─────────────────────────────────────────────────────────────────────────────────┘
                                          │ HTTP (chunked transfer)
┌─────────────────────────────────────────▼───────────────────────────────────────┐
│ Backend (tts_controller)                                                       │
│   POST /api/tts/agents/{sid}/speak/sentence                                    │
│     │ session-scoped TTSJobQueue (asyncio) — FIFO + cancel on new turn         │
│     │   worker → tts_service.speak(sentence) → omnivoice_engine                │
│     ▼                                                                          │
│   StreamingResponse (chunked transfer of single-sentence audio)                │
└────────────────────────────────────────┬───────────────────────────────────────┘
                                         │ HTTP (small payload, 1 sentence each)
┌────────────────────────────────────────▼───────────────────────────────────────┐
│ omnivoice service                                                              │
│   FastAPI POST /tts (또는 새 /tts/stream)                                      │
│     ├─ Semaphore(MAX_CONCURRENCY=1) (단일 GPU)                                 │
│     └─ MicroBatchCoalescer (옵션, 50ms 윈도우, B≤4)                            │
│   StreamingResponse — wav header → pcm chunks 점진적 yield                     │
└────────────────────────────────────────────────────────────────────────────────┘
```

핵심 결정:

- **문장 분할 위치는 프론트.** 백엔드 LLM SSE 스트림은 이미 토큰을 프론트로 흘리고 있다. 같은 정보를 백엔드가 한 번 더 인터셉트해서 분할하는 것은 책임 중복. 프론트가 SSE 리시버에서 한 군데 분할.
- **분할 규칙.** 한국어/영어 통합:
  - 종결 부호: `[.!?。！？\n]` 직후 + 다음 문자가 *공백/문장 시작* 일 때.
  - 길이 안전판: 80 글자 누적 시 가장 가까운 쉼표 `[,，、:;]` 에서 강제 분할.
  - 코드블록/URL/숫자(소수점) 보호: 정규식 white-list 로 분할 억제.
- **세션 스코프 큐.** `session_id` 별 `asyncio.Queue` + 워커 1개 (TTS 백엔드 직렬). 사용자 새 입력 도착 시 큐 flush + 진행 중 작업 cancel.
- **순서 보장.** 각 sentence 요청에 `seq` 번호 부여. 프론트 audioManager 가 seq 가 빠진 채로 도착한 것은 대기시키고 순서대로 재생. seq=0 부터 monotonically.
- **백프레셔.** GPU 큐 길이 > N 이면 프론트의 추가 sentence enqueue 를 200ms 디바운스 (아직 LLM 이 토큰을 더 토해내고 있다는 가정).
- **취소.** 사용자가 stop / 재입력 시 세션 큐 `cancel_all()` + 진행중 omnivoice 호출에 `httpx.AsyncClient` 의 `aclose()` 가 아닌 *서버 측 cancellation* 까지 전달 (FastAPI 의 `Request.is_disconnected`).

---

## 5. 단계별 구현 계획 (요약)

상세는 [plan.md](plan.md). 여기서는 페이즈 헤더만:

- **Phase 0 — 벤치마크 박제 (코드 변경 0줄)**
  실측 도구 작성, RTX/GTX 두 환경 baseline 캡처, [benchmarks.md](benchmarks.md) 행 0 작성.

- **Phase 1 — 안전한 저-위험 가속 (O1 + O2 + O10 + warm-up)**
  warmup, 어댑터 락 제거, dtype 자동 선택. 동작 변경 없음, 속도만 개선.

- **Phase 2 — 모델 단계 가속 (O7 + O4 + O3)**
  per-call num_step override, voice reference 캐시, CFG 스킵 분기.

- **Phase 3 — 컴파일/그래프 (O5, 옵션 O6)**
  torch.compile 적용. shape bucketing 정책 결정. CUDA Graphs 는 sm_61 호환성 검증 후.

- **Phase 4 — 문장 스트리밍 큐 (전 섹션 4 구현)**
  - 4a: omnivoice 서버 `/tts/stream` 신규 + chunked transfer
  - 4b: backend `/api/tts/agents/{sid}/speak/sentence` + `TTSJobQueue`
  - 4c: 프론트 `SentenceAccumulator` + audioManager seq 큐 보강

- **Phase 5 — Throughput 확장 (O8 + O9, 옵션)**
  micro-batch coalescer. multi-session 사용 패턴 발생 시에만.

- **Phase 6 — 회귀/품질 검증**
  - num_step 16/24/32 A/B (MOS proxy, 청취 평가)
  - fp16 ↔ bf16 NaN 모니터링
  - benchmarks.md 최종 행 누적

---

## 6. 검증 지표 (KPI)

| 지표 | 정의 | 측정 위치 | 1차 캠페인 목표 (GTX 1070) |
|------|------|-----------|----------------------------|
| **RTF (steady-state)** | `wall / audio_duration`, warmup 후 평균 | omnivoice 서버 로그 (staging GPU) | baseline 대비 **-15~30%**, 절대값 ≤1.5 (스트레치 ≤1.0) |
| **TTFA (E2E)** | LLM 첫 토큰 → 클라이언트 첫 PCM byte | 프론트 `performance.now()` (staging GPU 백엔드) | 문장 스트리밍 ON 시 **baseline 대비 -60~80%** |
| **Cold-start latency** | 컨테이너 healthy → 첫 합성 응답 byte | 컨테이너 재시작 직후 1회 측정 | warmup 적용 후 *정상 RTF 와 동일*. `phase=warming` 노출되어 fallback 명확 |
| **출력 동치성 (Tier-A)** | 동일 (text, voice, seed) 재호출 시 PCM 차이 | `numpy.allclose(audio_pre, audio_post, atol=1e-4)` | **100% 동치**. 한 케이스라도 깨지면 회귀 — 머지 차단 |
| **NaN/inf 발생률** | 합성 결과 텐서에 NaN/inf | 1000 합성 sample | 0% |
| **GPU steady-state VRAM** | `torch.cuda.memory_allocated()` lifespan warmup 완료 직후 + 임의의 100 합성 후 | 서버 정상 운영 중 | **시작 직후 ≈ 합성 후 ≈ 운영 종료 직전** 의 *세 값이 ±5% 이내* (영구 점유 정책 검증 — fragmentation 0). 절대값 예산 = 모델가중치 + 워크스페이스(최대 shape) + ref-cache 8개 + pinned host pool. GTX 1070 8GB 의 **≤ 5.5 GB** (여유 2.5GB+ 는 dwarf workloads/디스플레이 점유 대비). |
| **GPU 단편화 비율** | `(reserved - allocated) / reserved` | warmup 완료 후, 100 합성 후 | ≤ 5%. 그 이상이면 expandable_segments 정책 또는 워크스페이스 사전 할당 회귀. |
| **단위 테스트 (CPU)** | sentence splitter / job queue / 어댑터 mock / 컨트롤러 라우팅 | dev 환경 (GPU 불요) | 100% 통과, CI 게이트 |

**측정 환경.** RTF/TTFA/cold-start/메모리/NaN 은 *staging GPU 호스트* (별도 1070 머신 또는 사이드 데스크톱) 의 omnivoice 컨테이너로만 수행. dev 워크스테이션에는 GPU 가 없으므로 모델-경로 측정을 일절 하지 않는다. 절차는 [environment.md](environment.md).

**출력 동치성 검증의 핵심.** Tier-A 항목은 *모델 출력 분포 불변* 이 원칙. 따라서 PR 마다 `compare_audio.py` 스크립트로 baseline vs 신버전을 동일 입력 30 케이스에 대해 PCM 직접 비교. fp16 의 비결정성으로 완전 동치는 어렵지만 `atol=1e-4` (PCM 정수 환산 ≤2/32768) 는 청취 차이가 사실상 0. 이를 깨는 변경은 Tier-B 로 강등하거나 머지 거부.

**영구 점유 검증의 핵심.** O14~O17 의 의도는 *런타임 allocator 활동 0*. 검증 방법: warmup 직후 `torch.cuda.memory_stats()` 의 `num_alloc_retries`, `num_ooms`, `allocated_bytes.all.peak` 를 스냅샷 → 100 합성 후 다시 스냅샷 → `num_alloc_retries` 증가량 = 0, `allocated_bytes` peak 증가량 = 0. 한 번이라도 새 segment 가 잡히면 워크스페이스 사전 할당이 빠진 경로가 있다는 뜻 → 회귀.

---

## 7. 리스크 & 롤백

| 리스크 | 영향 | 완화 |
|--------|------|------|
| **개발 환경 GPU 부재로 인한 회귀 미감지** | dev 에서 단위 테스트 통과해도 staging 에서 모델 회귀 가능 | (a) 모든 모델-측 PR 은 *staging GPU 검증을 거쳐야 머지* 를 PR 체크리스트에 명시, (b) `compare_audio.py` 가 CI 의 staging 단계 게이트, (c) 머지 후 카나리 — prod 배포 전 staging 에서 24h 운영 |
| Voice ref 캐시가 *품질에 영향* (이론상 동치이나 구현 버그 가능) | 출력이 baseline 과 달라짐 | `compare_audio.py` 가 캐시 hit/miss 양쪽에서 동일 PCM 보장 — 깨지면 즉시 캐시 비활성 (`OMNIVOICE_REF_CACHE_SIZE=0` 환경변수로 런타임 OFF 가능) |
| httpx 풀 keep-alive 가 omnivoice 측 stale connection 으로 503 | 간헐적 합성 실패 | `httpx.Limits(max_keepalive_connections=4, keepalive_expiry=30.0)` + 503/connection-reset 시 *현재 keep-alive 풀 폐기 후 1회 재시도* |
| 문장 분할이 한국어 인용/숫자에서 오작동 | 부자연한 끊김 (품질 영향은 아니나 UX 회귀) | 분할 규칙 단위 테스트 30 케이스 ([streaming.md §2.2](streaming.md)), CI 게이트 |
| 서버 chunked transfer + httpx 어댑터 비호환 | TTFA 개선 효과 0 | 어댑터에 `client.stream("POST", ...)` 사용 + per-chunk yield 단위 테스트 (mock httpx) |
| Tier-B 옵션 (`guidance_scale=0`, `adaptive_steps=true`) 을 사용자가 모르고 켰다가 품질 회귀 | 사용자 인지 회귀 | (a) config 필드 메타데이터에 *경고 라벨* ("품질 변화 가능, A/B 평가 권장"), (b) UI 에서 별도 "실험적 (experimental)" 섹션 분리 |
| Pascal 에서 Tier-C 항목이 실수로 켜짐 | 회귀/오류 | 모든 Tier-C 항목은 `torch.cuda.get_device_capability() >= (7,0)` 가드. settings 에서 켜져 있어도 capability 미달이면 *경고 로그 + 자동 비활성* |
| 첫 호출 warmup 이 lifespan 내에서 5~30s 소모 | healthcheck timeout | healthcheck `start-period` 180s 유지, `/health` 가 `phase: warming` 동안 어댑터 fallback (현 동작 그대로) |

---

## 8. 인접 사이클과의 관계

- [20260422_OmniVoice/index.md](../20260422_OmniVoice/index.md) 의 어댑터/서비스 구조 위에 *순수 가산*. 디렉터리/엔진 명/엔드포인트 명 모두 그대로 유지.
- [docs/CHAT_SYSTEM_DEEP_ANALYSIS_REPORT.md](../../docs/CHAT_SYSTEM_DEEP_ANALYSIS_REPORT.md) 의 SSE 토큰 스트림 경로를 그대로 활용. 신규 SSE 채널을 만들지 않는다.
- 기존 audioManager 큐 설계는 *이미 충분*. seq 필드 보강만으로 OOO 안전성 확보 가능.

---

## 9. 본 사이클의 산출물

| 파일 | 내용 |
|------|------|
| [analysis.md](analysis.md) | OmniVoice 모델/서버 라인-바이-라인 심층 분석, 측정된 병목, 각 최적화 기법의 *근거* |
| [plan.md](plan.md) | Phase 0~6 의 체크리스트 형태 구현 계획, 각 PR 단위 |
| [streaming.md](streaming.md) | 문장 분할 규칙 / 큐 자료구조 / 순서 보장 / 취소 / 백프레셔 상세 |
| [benchmarks.md](benchmarks.md) | baseline → 각 최적화 적용 후 RTF/TTFA/메모리 누적 표 (Pascal sm_61 단일 환경) |
| [environment.md](environment.md) | **GPU-less dev / staging GPU / prod GPU 의 책임 분리, 측정/검증 워크플로우, `compare_audio.py` 스펙** |
| [progress/](progress/) | 일자별 진행 로그 |
