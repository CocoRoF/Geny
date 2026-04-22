# environment.md — 측정·검증 환경 분리 전략

> **현실 제약.**
> - **운영 GPU = GTX 1070 (Pascal sm_61) 단일.** Ampere+ 가속(`bf16`, `torch.compile` inductor, FlexAttention/BlockMask, CUDA Graphs 강한 모드)은 *디폴트 비활성*.
> - **개발 워크스테이션에 GPU 없음.** `nvidia-smi` 자체가 부재. `omnivoice` 컨테이너는 dev compose 의 `tts-local` profile 을 *띄우지 않음*. dev 에서는 모델-경로 코드를 *실행조차 할 수 없다*.
>
> 본 문서는 이 두 제약 위에서 **(a) 어떤 검증을 어디서 수행하는지**, **(b) 모델-경로 변경의 PR 게이트는 누가/어디서 통과시키는지**, **(c) `compare_audio.py` 의 정확한 사용 절차** 를 정의한다.

---

## 1. 환경 3-tier 책임 분리

| 환경 | 위치 | GPU | 역할 | 본 사이클 사용 |
|------|------|-----|------|----------------|
| **dev** | 워크스테이션 (현재) | ❌ | 코드 작성, 단위 테스트 (CPU only), 통합 테스트 (mock omnivoice), 프론트 빌드 | sentence splitter / job queue / 어댑터 mock / 컨트롤러 라우팅 / 프론트 컴포넌트 모두 |
| **staging GPU** | 별도 1070 머신 (또는 동일 1070 가 사이드 프로파일로 띄워질 때) | ✅ GTX 1070 | 모델-경로 검증, 벤치마크, `compare_audio.py` 회귀 게이트, smoke test | **모든 모델 영향 PR 의 머지 게이트** |
| **prod** | 운영 (현재 1070) | ✅ GTX 1070 | 실서비스 | staging 통과 + 24h 카나리 후에만 |

**핵심 룰.**
1. dev 에서 **모델-경로 측정값을 어떤 표에도 기록하지 않는다**. (CPU 추론은 시간/GPU 메모리 의미 없음.)
2. staging 과 prod 는 **동일 컨테이너 이미지**. 빌드 SHA 동일 보장.
3. `compare_audio.py` baseline PCM 은 *staging 에서 한 번만 캡처*해 git LFS (또는 별도 artifact 저장소)에 저장. PR 은 baseline 변경 사유를 명시해야만 갱신.

---

## 2. dev 에서 가능한 검증 (GPU 불요)

### 2.1 단위 테스트 — 100% CPU

| 대상 | 도구 | 위치 |
|------|------|------|
| `SentenceAccumulator` 30 케이스 | vitest / jest | `frontend/src/lib/__tests__/sentenceSplitter.test.ts` |
| `audioManager` seq 보장 / OOO 도착 | vitest, fake AudioContext | `frontend/src/lib/__tests__/audioManager.seq.test.ts` |
| `TTSJobQueue` enqueue / cancel / 워커 종료 | pytest + asyncio | `backend/tests/service/vtuber/tts/test_job_queue.py` |
| `OmniVoiceEngine` 어댑터 (락 제거 후 동시성) | pytest + httpx mock (`respx`) | `backend/tests/service/vtuber/tts/test_omnivoice_engine_concurrency.py` |
| 컨트롤러 라우팅 / `/speak/sentence` / `DELETE /queue` | pytest + httpx ASGI | `backend/tests/controller/test_tts_controller_streaming.py` |
| 분할 규칙 정규식 (한국어 인용/숫자/URL/코드블록) | vitest 30 시드 | 위 sentenceSplitter 테스트에 포함 |
| dtype resolver / capability 가드 | pytest, `torch.cuda.get_device_capability` 를 monkeypatch | `omnivoice/tests/test_dtype_resolver.py` |

### 2.2 통합 테스트 — mock omnivoice 컨테이너

`backend/tests/integration/test_tts_with_mock_omnivoice.py`:

```python
# pytest fixture: aiohttp/httpx app on 127.0.0.1:0 가 fake /tts /health 응답
@pytest.fixture
async def fake_omnivoice():
    async def health(request):
        return web.json_response({"phase": "ok", "status": "ok"})
    async def tts(request):
        body = await request.json()
        # 24kHz 1s sine 반환 (실제 오디오 모양만 갖춘 fixture)
        return web.Response(body=_sine_wav_bytes(1.0), content_type="audio/wav")
    ...
```

→ backend 의 어댑터/큐/컨트롤러 전체 경로가 *실제 GPU 없이* 검증된다. 모델 출력의 *정확성* 은 검증되지 않지만 *전송/직렬성/취소/순서* 는 100% 검증.

### 2.3 프론트 E2E (Playwright, optional)

- mock omnivoice + mock LLM SSE 로 프론트의 SentenceAccumulator → `/speak/sentence` → audioManager 시퀀스를 *시간축 모킹* 으로 검증.
- 본 사이클의 필수는 아님. 단, 사용자 새 입력 시 cancel 동작 회귀에 유용.

---

## 3. staging GPU 워크플로우

### 3.1 머신 준비

- **호스트.** GTX 1070, NVIDIA driver ≥ 535, CUDA 12.6 호환.
- **OS.** Ubuntu 22.04 (prod 동일).
- **저장소.** `geny-workspace/Geny/` 클론. `dev_docs/20260422_OmniVoice_Perf/baselines/` 디렉터리에 baseline PCM 보관 (git LFS 또는 `.gitignore` + 별도 artifact 저장소).
- **컨테이너.** `docker compose --profile tts-local up -d omnivoice` (omnivoice 만, 풀스택 불필요).

### 3.2 PR 게이트 절차

```
1. dev 에서 PR 작성, dev 단위/통합 테스트 통과
2. PR 라벨 `needs-staging` 자동 부여 (모델-경로 변경 감지: omnivoice/server/**, omnivoice/omnivoice_core/**)
3. staging 에 PR 브랜치 체크아웃, omnivoice 컨테이너 재빌드
4. scripts/staging_gate.sh 실행:
     a. compare_audio.py baseline_set/  → PASS 면 다음
     b. bench.py --runs 3 → benchmarks.md 의 임시 행 출력
     c. 사람이 행을 보고 회귀 없음 확인
5. PR 코멘트에 결과 붙여넣기, 라벨 `staging-passed` 부여
6. 머지
```

### 3.3 staging 에서만 도는 자동화

`Geny/omnivoice/scripts/staging_gate.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. health 가 phase=ok 까지 대기
for i in {1..60}; do
  phase=$(curl -fsS http://localhost:9881/health | jq -r .phase)
  [[ "$phase" == "ok" ]] && break
  sleep 5
done

# 2. 출력 동치성
python -m server.compare_audio \
  --baseline ../dev_docs/20260422_OmniVoice_Perf/baselines/sm_61/ \
  --atol 1e-4 --texts scripts/texts_smoke.txt
echo "[gate] compare_audio PASS"

# 3. 영구 점유 검증 (Phase 1d 이후)
# warmup 직후 스냅샷
curl -fsS http://localhost:9881/diag/memory > /tmp/mem_before.json
# 100 합성
python -m server.bench --runs 1 --texts scripts/texts_smoke.txt --warmup 0 --json /tmp/_warm.json
for i in {1..20}; do
  python -m server.bench --runs 5 --texts scripts/texts_smoke.txt --warmup 0 --json /tmp/_loop.json > /dev/null
done
curl -fsS http://localhost:9881/diag/memory > /tmp/mem_after.json
python scripts/check_memory_residency.py /tmp/mem_before.json /tmp/mem_after.json \
  --max-allocated-delta-bytes 0 \
  --max-reserved-delta-bytes 0 \
  --max-retries-delta 0 \
  --max-fragmentation 0.05
echo "[gate] persistent residency PASS"

# 4. RTF 측정
python -m server.bench --runs 3 --texts scripts/texts_ko.txt --texts scripts/texts_en.txt \
  --json /tmp/bench.json
python scripts/bench_to_md.py /tmp/bench.json >> /tmp/bench_row.md
cat /tmp/bench_row.md
```

---

## 4. `compare_audio.py` — 출력 동치성 검증

> 본 사이클의 **Tier-A 모든 최적화** 는 출력 PCM 이 baseline 과 거의 일치(`atol=1e-4`)해야 한다. fp16 의 비결정성으로 비트 단위 일치는 어렵지만 PCM int16 환산 시 차이 ≤2 (전체 다이내믹 range 의 0.006%) 는 청취 차이가 0.

### 4.1 baseline 캡처 (1회만, staging 에서)

```bash
# omnivoice 컨테이너 내부
python -m server.compare_audio \
  --capture \
  --output /baselines/sm_61/ \
  --texts scripts/texts_smoke.txt \
  --voice paimon_ko --voice mao_pro
```

→ 텍스트별 PCM 을 `.npz` 로 저장. 메타데이터(`voice`, `text`, `lang`, `model_sha`, `git_sha`) 동봉.

### 4.2 회귀 검사 (PR 마다)

```bash
python -m server.compare_audio \
  --baseline /baselines/sm_61/ \
  --atol 1e-4 \
  --texts scripts/texts_smoke.txt
# 한 케이스라도 atol 초과 → exit 1, 어떤 케이스가 어디서 깨졌는지 stdout
```

### 4.3 Tier-B 옵션 활성 시

`--mode equivalence` (Tier-A 검증) vs `--mode quality-drift` (Tier-B 검증, atol 완화 + 청취 평가 시트 자동 생성). Tier-B 가 켜진 신규 PR 은 청취 평가 첨부 의무.
### 4.4 영구 점유 검증 (`/diag/memory` + `check_memory_residency.py`)

Phase 1d 이후 모든 PR 의 staging 게이트에 추가되는 *제2 필수 검증*. compare_audio 가 *출력 동치* 를 검증한다면, 이것은 *메모리 동맥* 을 검증한다.

```bash
# warmup 완료 직후
curl -fsS http://localhost:9881/diag/memory > before.json
# N 합성
python -m server.bench --runs 100 --warmup 0
curl -fsS http://localhost:9881/diag/memory > after.json
python scripts/check_memory_residency.py before.json after.json
```

`check_memory_residency.py` 는 다음 항목을 검사:

| 지표 | 허용 대역 (기본값) | 의미 |
|------|---------------------|------|
| `allocated_bytes.all.current` 증가 | 0 바이트 (±0.5%) | 새 텐서 할당 없으면 증가 0 |
| `reserved_bytes.all.current` 증가 | 0 바이트 | 새 segment 도 잡히지 않아야 함 |
| `num_alloc_retries` 증가 | 0 | `cudaMalloc` 재시도가 0 |
| `num_ooms` | 0 | OOM 이벤트 없음 |
| fragmentation `(reserved-allocated)/reserved` | ≤ 5% | caching allocator 건강 |

하나라도 깨지면 비제로 종료 상태 리턴 → 머지 거부. *동적 할당 흔적이 남은 코드 경로가 있다* 는 결정적 증거.
---

## 5. dev 에서 *절대 하지 말 것*

| 안티패턴 | 이유 | 대안 |
|----------|------|------|
| dev 에서 omnivoice 컨테이너를 CPU 로 띄워 RTF 측정 | CPU 추론은 GPU 와 다른 코드패스 + 절대값 무의미 | staging 에서만 측정 |
| `torch.compile` 를 dev 에서 검증 | inductor 가 CPU 백엔드로 fallback, 결과가 GPU 와 다름 | staging dry-run |
| benchmarks.md 에 dev 측정값 추가 | 표가 오염되어 비교 불가 | 추가 금지 (CI lint 로 차단 — 행 형식에 `gpu` 컬럼 필수) |
| dev 에서 fp16 NaN 검사 | CPU 는 fp16 지원이 제한적, 결과 다름 | staging 1000-sample 회귀 스크립트 |
| 모델 자체에 print/breakpoint 추가 후 staging 푸시 | 운영 회귀 위험 | 항상 별도 디버그 환경변수 (`OMNIVOICE_DEBUG_FORWARD=true`) 가드 |

---

## 6. 본 사이클 PR 의 환경별 게이트 매트릭스

| Phase | PR 내용 | dev 게이트 | staging 게이트 |
|-------|---------|-----------|----------------|
| 0 | bench 스크립트 추가 | smoke (script 가 import 됨) | 1회 baseline 캡처 + benchmarks.md 행 0 추가 |
| 1a | warmup | dev: lifespan 코드 lint | staging: cold-call → warm-call RTF 비교 |
| 1b | 어댑터 락 제거 | 동시성 단위 테스트 (mock) | RTF 회귀 없음 확인 |
| 1c | dtype auto | dtype resolver pytest | staging: capability 감지 → fp16 선택 확인 |
| **1d** | **영구 점유 (workspace + pinned + multi-warmup + allocator)** | **workspace/pool unit + settings monkeypatch** | **`/diag/memory` 영구 점유 5조건 + `compare_audio --atol 1e-4` + p95-p50 jitter 감소 확인** |
| 2a | adaptive_steps (Tier-B, OFF 기본) | config schema pytest | staging: ON 시에만 RTF 변동 확인 + compare_audio `--mode quality-drift` |
| 2b | ref-cache | unit (캐시 키, mtime invalidation) | staging: `compare_audio --atol 1e-4` 동치성 + RTF 측정 |
| 2c | CFG 분기 (Tier-B, gs=0 시에만) | unit (분기 정합성) | staging: gs=2.0 동치성, gs=0 별도 측정 |
| 3a | torch.compile (Tier-C, sm_61 자동 OFF) | capability 가드 unit | staging: `phase=ok` 도달, sm_61 에서 비활성 확인 |
| 4a | 서버 /tts/stream | unit (chunked 헤더) | staging: 첫 byte 도달 시각 측정 |
| 4b | backend 큐 + sentence endpoint | unit (TTSJobQueue 시나리오 9개) | staging: 실제 omnivoice 와 30초 다중 enqueue smoke |
| 4c | 프론트 SentenceAccumulator | vitest 30 케이스 | staging: 사용자 수동 한 턴 |
| 5 | coalescer | unit | (multi-user 발생 시에만 staging) |
| 6 | 최종 회귀 | 전 단위 재실행 | benchmarks.md 최종 행 + compare_audio 전 케이스 |

---

## 7. CI 통합 (선택, 단기 비목적)

본 사이클에서는 *수동* staging 게이트로 충분. CI 자동화는 별도 사이클:

- GitHub Actions self-hosted runner 가 staging 머신에 상주
- PR 라벨 `needs-staging` 감지 → `staging_gate.sh` 실행 → 결과 코멘트
- 실패 시 머지 차단

---

## 8. 정리 — 사이클 진행 시 워크플로우

```
                ┌──────────────────────────────┐
                │ dev 워크스테이션 (GPU 없음) │
                │  - 코드 작성                 │
                │  - 단위 테스트 (pytest/vitest)│
                │  - 통합 테스트 (mock omnivoice)│
                └──────────────┬───────────────┘
                               │ git push, PR
                               ▼
                ┌──────────────────────────────┐
                │ staging GPU (GTX 1070)       │
                │  - omnivoice 컨테이너 재빌드  │
                │  - staging_gate.sh           │
                │    ├─ compare_audio (Tier-A)  │
                │    └─ bench.py (RTF/TTFA)    │
                └──────────────┬───────────────┘
                               │ PASS + 사람 검토
                               ▼
                ┌──────────────────────────────┐
                │ prod (GTX 1070)              │
                │  - 카나리 24h 후 전면 적용   │
                └──────────────────────────────┘
```

**dev 에 GPU 가 없다는 사실은 본 사이클의 진행을 막지 않는다.** 단, *모델 코드 변경* 은 항상 staging gate 통과 후 머지. dev 가 책임지는 영역(어댑터/큐/컨트롤러/프론트)은 GPU 와 무관하므로 100% dev 에서 완결.
