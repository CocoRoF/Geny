# benchmarks.md — OmniVoice 가속 측정 누적 표 (GTX 1070 / sm_61 단일)

> **측정 환경.** *모든 행은 staging GPU 호스트 (GTX 1070, Pascal sm_61, fp16, CUDA 12.6, torch 2.6) 의 omnivoice 컨테이너에서 수집*. dev 워크스테이션(GPU 없음)에서 측정한 값은 *표에 추가 금지*. 자세한 환경 분리는 [environment.md](environment.md).
> **측정 도구.** [plan.md Phase 0](plan.md#phase-0--벤치마크-박제-pr-0) 의 `omnivoice/scripts/bench.py`. 30개 한국어/영어 mixed sample (5/15/40/100/200자 × 6) × 3 runs.
> **출력 동치성.** Tier-A 행은 *모두* `compare_audio --atol 1e-4` PASS 가 전제. PASS 하지 않으면 행 자체가 무효 (회귀 PR).

## 결과 표 (GTX 1070, fp16)

| Phase | 적용 | num_step | warmup | ref-cache | adaptive | CFG (gs) | RTF mean | RTF p50 | RTF p95 | p95-p50 (jitter) | TTFA p50 (s) | VRAM steady (GB) | VRAM 증가/100call (MB) | NaN% | compare_audio | 비고 |
|-------|------|----------|--------|-----------|----------|----------|----------|---------|---------|------------------|--------------|-------------------|-------------------------|------|----------------|------|
| 0 (baseline, cold 포함) | — | 32 | ❌ | ❌ | ❌ | 2.0 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | (capture 기준) | 첫 호출 cold 포함 |
| 0 (baseline, steady) | — | 32 | ❌ | ❌ | ❌ | 2.0 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | (capture 기준) | 첫 호출 제외 |
| 1a-c | warmup + 락 제거 + dtype 가드 | 32 | ✅ (1-shot) | ❌ | ❌ | 2.0 | TBD | | | | | TBD | TBD | 0% | PASS | 첫 호출 cold 제거가 핵심 |
| **1d (영구 점유)** | + workspace 사전 할당 + pinned pool + 3-bucket warmup + allocator 정책 | 32 | ✅ (3-bucket) | ❌ | ❌ | 2.0 | TBD | | | **↓↓** | TBD | TBD | **= 0** | 0% | PASS | **vLLM 류 사전 점유. p95-p50 gap 결정적 감소** |
| 2 (Tier-A only) | + ref-cache | 32 | ✅ | ✅ | ❌ | 2.0 | TBD | | | | | TBD | = 0 | 0% | PASS | **본 사이클 디폴트 운영 행** |
| 2 (Tier-B 참고: adaptive ON) | + adaptive_steps | 16/24/32 | ✅ | ✅ | ❌ | 2.0 | TBD | | | | | TBD | = 0 | 0% | quality-drift | **별도 청취 평가 후에만 디폴트화 검토** |
| 2 (Tier-B 참고: gs=0) | + cfg_skip | 32 | ✅ | ✅ | ❌ | 0.0 | TBD | | | | | TBD | = 0 | 0% | quality-drift | **별도 청취 평가 후에만 디폴트화 검토** |
| 3 | (compile 비활성 확인) | 32 | ✅ | ✅ | ❌ | 2.0 | =Phase 2 | | | | | =Phase 2 | = 0 | 0% | PASS | sm_61 가드로 회귀 0 |
| 4 | + 문장 스트리밍 | 32 | ✅ | ✅ | ❌ | 2.0 | =Phase 2 | | | | TBD (★ 단축) | =Phase 2 | = 0 | 0% | PASS | RTF 불변, **TTFA 가 측정 포인트** |

## VRAM 영구 점유 검증 표 (Phase 1d 게이트)

`/diag/memory` 가 반환하는 핵심 지표를 *컨테이너 시작 직후* (warmup 완료 시점) 와 *100 합성 후* 두 시점에서 비교. 영구 점유 정책이 제대로 적용되었다면 모든 증가량이 0(±오차) 이어야 한다.

| Phase | `allocated_bytes.current` 증가 | `reserved_bytes.current` 증가 | `num_alloc_retries` 증가 | `num_ooms` | fragmentation `(reserved-allocated)/reserved` | 게이트 |
|-------|--------------------------------|-------------------------------|--------------------------|------------|----------------------------------------------|--------|
| 0 (baseline) | TBD (양수 예상 — workspace 동적 할당 흔적) | TBD | TBD | 0 | TBD | (참고) |
| 1a-c | TBD | TBD | TBD | 0 | TBD | (참고) |
| **1d (영구 점유 ON)** | **= 0 (±0.5%)** | **= 0** | **= 0** | **0** | **≤ 5%** | **모두 충족 시만 PR 머지** |
| 2~4 | = 0 | = 0 | = 0 | 0 | ≤ 5% | 회귀 게이트 (1d 와 동일) |

**해석.**
- `allocated_bytes` 증가 ≠ 0: 어딘가에서 *새 텐서가 할당* 됨 → workspace 슬라이스 뷰가 빠진 경로 존재 → 회귀.
- `reserved_bytes` 증가 ≠ 0: caching allocator 가 새 segment 를 잡음 → fragmentation 위험.
- `num_alloc_retries` 증가: `cudaMalloc` 직후 재시도가 발생 → latency p99 튐.
- fragmentation > 5%: `expandable_segments:True` 정책이 안 먹거나 사이즈 분포가 깨짐.

## TTFA 별도 표 (Phase 4)

문장 스트리밍 ON/OFF 의 *체감 latency* 비교. 메시지 길이별로 구분:

| 메시지 길이 | streaming OFF (E2E) | streaming ON (TTFA) | streaming ON (E2E) |
|-------------|---------------------|---------------------|---------------------|
| 1 문장 (~30자) | TBD | TBD (= 1문장 합성) | TBD (≈ OFF) |
| 3 문장 (~100자) | TBD | TBD (≈ 1문장) | TBD |
| 6 문장 (~250자) | TBD | TBD (≈ 1문장) | TBD |
| 12 문장 (~500자) | TBD | TBD (≈ 1문장) | TBD |

**기대.** OFF 의 E2E 와 ON 의 TTFA 가 *문장 수에 무관하게* 일정 — 즉 첫 문장 합성 시간으로 수렴.

## 측정 프로토콜 (요약)

1. **Cold-start.** 컨테이너 재시작 직후 `/health` 가 `phase: ok` 까지 대기 (warmup 3 bucket 포함) → 그때부터 첫 합성 응답 첫 byte 까지 측정.
2. **Warm steady-state.** 60초 idle 후 100건 직렬 합성. 첫 1건은 통계 제외.
3. **TTFA E2E.** 프론트 `performance.now()` — 사용자 send → 클라이언트 첫 PCM byte 수신.
4. **VRAM steady-state.** warmup 완료 직후 `torch.cuda.memory_allocated()` 1회 측정 → 100 합성 후 다시 측정. 두 값 비교 = `VRAM 증가/100call`.
5. **Jitter (p95-p50 gap).** 영구 점유 정책의 *결정적 검증 포인트*. 평균이 아니라 분산을 본다.
6. **NaN%.** 합성 결과 텐서 `torch.isnan().any()` true 비율.
7. **`compare_audio` PCM 동치성.** baseline_set 30 케이스 모두 `atol ≤ 1e-4`. 한 케이스라도 미달 시 표 행 무효 + 회귀 라벨.

## 무엇을 측정하지 *않는가*

- **Ampere/Ada 환경 RTF.** 본 운영 환경 아님. 별도 사이클에서.
- **bf16 / torch.compile / FlexAttention 의 RTF.** Pascal 비활성. 측정 의미 없음.
- **micro-batch coalescer 의 throughput.** 단일 사용자 워크로드, 다중 동시 세션 발생 시 별도 사이클.
- **dev 워크스테이션 CPU 추론 시간.** 환경 미스매치, 표 추가 금지.
- **청취 평가 점수 (MOS, ALER).** Tier-B 옵션 디폴트화 사이클에서. 본 사이클은 Tier-A 출력 동치 게이트만.

## 한계 / 솔직한 노트

- GTX 1070 은 fp16 텐서코어 미지원이라 절대 RTF 는 빠르지 않음. 본 사이클 디폴트 경로(Tier-A only)의 *현실적인* RTF 평균 개선은 baseline 대비 **-15~30% 수준**. 사용자 체감 latency 의 *대부분* 은 **TTFA 단축 (Phase 4) + jitter 감소 (Phase 1d 영구 점유)** 에서 나온다 — 평균 RTF 는 비슷해도 "가끔 튀는" 사례가 사라지는 것이 결정적.
- 영구 점유 정책으로 GPU steady-state VRAM 은 **시작부터 ~5.5GB 점유**. GTX 1070 8GB 의 ~70%. 디스플레이 출력에 GPU 를 함께 쓰는 호스트는 `OMNIVOICE_GPU_MEM_FRACTION` 을 0.6~0.7 로 낮춰야 안전 (별도 사이클 가이드).
- Tier-B 옵션을 모두 켜면 추가 1.5~2× 가속 가능하지만 *본 사이클 비목적*. 별도 청취 평가 사이클이 통과해야 디폴트화.
- baseline PCM 은 fp16 비결정성이 있으므로 동일 호스트 동일 빌드에서도 약간씩 다를 수 있다 — 그래서 `atol=1e-4` 사용. 비트 동치는 요구하지 않는다.
