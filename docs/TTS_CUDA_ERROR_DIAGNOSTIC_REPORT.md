# GPT-SoVITS CUDA 커널 이미지 오류 심층 진단 리포트

**작성일**: 2026-04-02
**오류**: `torch.AcceleratorError: CUDA error: no kernel image is available for execution on the device`
**오류 코드**: `cudaErrorNoKernelImageForDevice` (CUDA Runtime Error 209)
**GPU**: NVIDIA GeForce GTX 1070 (Pascal, Compute Capability 6.1, sm_61)
**드라이버**: 570.211.01 / CUDA 12.8

---

## 1. 오류 요약

```
torch.AcceleratorError: CUDA error: no kernel image is available for execution on the device
```

GPT-SoVITS 컨테이너 시작 시 `api_v2.py` → `TTS.py:608`에서 모델 FP16 변환 (`self.t2s_model.half()`) 과정에서 크래시 발생.

---

## 2. 근본 원인

### GTX 1070 (sm_61) 아키텍처가 Docker 이미지의 PyTorch에서 제외됨

| 항목 | 현재 환경 |
|---|---|
| **GPU** | NVIDIA GeForce GTX 1070 |
| **아키텍처** | Pascal |
| **Compute Capability** | **6.1 (sm_61)** |
| **VRAM** | 8GB |
| **드라이버** | 570.211.01 |
| **Docker 이미지** | `xxxxrt666/gpt-sovits:latest-cu128` |
| **이미지 내 CUDA** | 12.8 |

Docker 이미지 `xxxxrt666/gpt-sovits:latest-cu128`에 탑재된 PyTorch는 CUDA 12.8용으로 빌드되었으며, **최신 PyTorch cu128 빌드는 Pascal 아키텍처(sm_60, sm_61) 커널을 포함하지 않습니다.**

PyTorch cu128 빌드의 일반적인 아키텍처 지원:
```
포함됨: sm_70 (Volta), sm_75 (Turing), sm_80/86 (Ampere), sm_89 (Ada), sm_90 (Hopper), sm_100+
미포함: sm_50 (Maxwell), sm_60/61 (Pascal) ← GTX 1070은 여기
```

### 왜 `nvidia-smi`는 정상인가?

| 구성요소 | 역할 | 상태 |
|---|---|---|
| **nvidia-smi** | 드라이버 수준 GPU 인식 | ✅ 정상 |
| **CUDA Runtime** | 컨테이너 내 CUDA 라이브러리 | ✅ 정상 |
| **PyTorch CUDA Kernels** | 실제 텐서 연산 (half, matmul 등) | ❌ **sm_61 커널 없음** |

`nvidia-smi`는 드라이버가 GPU를 인식하는지만 확인합니다. `.half()`, `.to('cuda')` 등 실제 CUDA 커널이 실행될 때 비로소 아키텍처 호환성이 검증됩니다.

### 오류 발생 지점

```python
# GPT_SoVITS/TTS_infer_pack/TTS.py:608
self.t2s_model = self.t2s_model.half()  # is_half=True 설정에 의해
```

`.half()` 호출 시 모든 파라미터에 FP32→FP16 변환 CUDA 커널이 실행되고, sm_61용 커널 바이너리가 없어 크래시합니다. 단, `is_half=False`로 바꿔도 이후 추론 시 다른 CUDA 연산(matmul, conv 등)에서 동일한 오류가 발생합니다. **`.half()` 자체가 아니라 sm_61 커널 전체가 부재하는 것이 근본 원인입니다.**

---

## 3. 왜 이런 일이 발생하는가?

### 3.1 PyTorch의 아키텍처 지원 축소 추세

PyTorch는 바이너리 크기 최적화를 위해 점진적으로 구형 GPU 아키텍처 지원을 제거합니다:

| PyTorch 버전 | 지원 아키텍처 (cu12x 빌드) |
|---|---|
| 2.1~2.3 | sm_50, sm_60, sm_61, sm_70, sm_75, sm_80, sm_86, sm_89, sm_90 |
| 2.4~2.5 | sm_50, sm_60, sm_70, sm_75, sm_80, sm_86, sm_89, sm_90 |
| 2.6+ (cu128) | sm_70, sm_75, sm_80, sm_86, sm_89, sm_90, sm_100 ← **sm_61 제거** |

### 3.2 CUDA 12.8과 Pascal의 관계

CUDA Toolkit 12.x는 공식적으로 sm_50+ 을 지원하지만, PyTorch의 **사전 빌드 바이너리**는 이와 별개로 빌드 시 `TORCH_CUDA_ARCH_LIST`에 명시된 아키텍처만 포함합니다. `xxxxrt666/gpt-sovits:latest-cu128` 이미지 제작자가 sm_61을 포함하지 않고 빌드한 것입니다.

### 3.3 GTX 1070 + 드라이버 570의 특이성

드라이버 570은 원래 Blackwell(RTX 50 시리즈) 출시와 함께 릴리스된 드라이버 라인이지만, Pascal까지 하위 호환됩니다. 드라이버 자체는 GTX 1070과 호환되나, Docker 이미지 내 PyTorch 빌드가 문제입니다.

---

## 4. 확인 명령어

### 4.1 Docker 이미지 내 PyTorch 아키텍처 목록 확인

```bash
docker run --rm --gpus all xxxxrt666/gpt-sovits:latest-cu128 \
  python -c "
import torch
print('PyTorch:', torch.__version__)
print('CUDA:', torch.version.cuda)
print('Arch List:', torch.cuda.get_arch_list())
print('GPU:', torch.cuda.get_device_name(0))
print('Capability:', torch.cuda.get_device_capability(0))
"
```

예상 결과:
```
Arch List: ['sm_70', 'sm_75', 'sm_80', 'sm_86', 'sm_89', 'sm_90']  ← sm_61 없음
Capability: (6, 1)  ← GTX 1070
```

→ Arch List에 `sm_61`이 없으면 이것이 확정 원인.

### 4.2 간단한 CUDA 텐서 테스트

```bash
docker run --rm --gpus all xxxxrt666/gpt-sovits:latest-cu128 \
  python -c "import torch; x = torch.randn(2,2).cuda(); print(x.half()); print('OK')"
```

→ 동일한 `cudaErrorNoKernelImageForDevice` 오류 발생 시 확정.

---

## 5. 해결 방안

### 방안 1: `latest-cu126-lite` 또는 `latest-cu126` 이미지 사용 ✅ (권장 / 가장 빠름)

```yaml
gpt-sovits:
  image: xxxxrt666/gpt-sovits:latest-cu126-lite  # cu128 → cu126-lite
```

또는:

```yaml
gpt-sovits:
  image: xxxxrt666/gpt-sovits:latest-cu126
```

**근거**:
- CUDA 12.6용 PyTorch 빌드는 sm_61(Pascal) 커널을 포함할 가능성이 **훨씬 높음**
- Docker Hub에서 `latest-cu126-lite`(9.75GB)는 `latest-cu128`(14.46GB)보다 작고 `latest` 태그와 동일 SHA → 기본 이미지일 가능성
- GTX 1070은 CUDA 12.6에서 완벽히 동작
- `LD_LIBRARY_PATH` 환경변수도 함께 조정 필요할 수 있음

```yaml
environment:
  - is_half=False
  - LD_LIBRARY_PATH=/root/conda/lib:/root/conda/lib/python3.12/site-packages/nvidia/npp/lib
```

> ⚠️ GTX 1070은 Tensor Core가 없으므로 FP16 추론 성능 이점이 크지 않습니다. `is_half=False`를 권장.

### 방안 2: `is_half=False` + cu126 이미지 조합 ✅

GTX 1070(Pascal)은 **Tensor Core가 없습니다**. FP16 연산은 가능하지만 속도 이점이 없고, 오히려 FP16↔FP32 변환 오버헤드가 발생합니다.

```yaml
gpt-sovits:
  image: xxxxrt666/gpt-sovits:latest-cu126-lite
  environment:
    - is_half=False  # GTX 1070에는 FP32가 적합
    - LD_LIBRARY_PATH=/root/conda/lib:/root/conda/lib/python3.12/site-packages/nvidia/npp/lib
```

### 방안 3: 커스텀 Dockerfile로 sm_61 포함 PyTorch 설치

```dockerfile
FROM xxxxrt666/gpt-sovits:latest-cu126-lite

# Pascal(sm_61) 지원이 확실한 PyTorch 설치
RUN pip install --no-cache-dir torch==2.3.1+cu121 torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu121
```

PyTorch 2.3.x + CUDA 12.1 조합은 sm_61을 확실히 포함합니다.

### 방안 4: `device=cpu` 강제 사용 (최후의 수단)

GPT-SoVITS 설정에서 CPU 모드로 전환. 매우 느리지만 동작은 합니다.

---

## 6. GTX 1070의 현실적 한계

| 항목 | GTX 1070 | 권장 사양 |
|---|---|---|
| VRAM | 8GB | 8GB+ |
| Tensor Core | ❌ 없음 | ✅ (RTX 20+) |
| FP16 성능 | FP32의 ~1/64 | FP32의 2배+ |
| Compute Capability | 6.1 | 7.0+ |
| CUDA 지원 | 최대 12.6 권장 | 12.x |

- **VRAM 8GB**: GPT-SoVITS v2 모델은 FP32 기준 약 4~6GB → GTX 1070으로 동작 가능하지만 여유가 적음
- **FP16 비권장**: Tensor Core 없어 성능 이점 없음 → `is_half=False` 사용
- **추론 속도**: RTX 30/40 시리즈 대비 매우 느림 (실시간 TTS에는 부족할 수 있음)

---

## 7. 왜 "음성 출력은 정상, 샘플 파일 기반은 실패"인가?

| 기능 | 사용 엔진 | GPU 필요 | 상태 |
|---|---|---|---|
| 기본 TTS (텍스트→음성) | Edge TTS / OpenAI TTS 등 | ❌ CPU/클라우드 | ✅ 정상 |
| 샘플 기반 음성 복제 | GPT-SoVITS | ✅ GPU 필수 | ❌ 컨테이너 크래시 |

GPT-SoVITS 컨테이너가 시작 시 모델 로딩에서 크래시하므로 서비스 자체가 가동되지 않습니다. 다른 TTS 엔진은 백엔드 컨테이너 내에서 CPU/API로 동작하기 때문에 영향 없음.

---

## 8. 실행 계획

| 우선순위 | 작업 | 비고 |
|---|---|---|
| **1** | 섹션 4.1 명령어로 PyTorch arch list 확인 | 원인 확정 |
| **2** | `latest-cu126-lite` 이미지 + `is_half=False` 적용 (방안 2) | 가장 빠른 해결 |
| **3** | 재배포 후 GPT-SoVITS 컨테이너 로그 확인 | 정상 기동 확인 |
| **4** | (선택) PyTorch 2.3.x + cu121 커스텀 이미지 빌드 (방안 3) | 안정성 극대화 |

---

## 9. Docker Compose 변경안

현재 (`docker-compose.prod.yml` 및 `docker-compose.yml`):

```yaml
gpt-sovits:
  image: xxxxrt666/gpt-sovits:latest-cu128
  environment:
    - is_half=True
```

변경 후:

```yaml
gpt-sovits:
  image: xxxxrt666/gpt-sovits:latest-cu126-lite
  environment:
    - is_half=False
    - LD_LIBRARY_PATH=/root/conda/lib:/root/conda/lib/python3.12/site-packages/nvidia/npp/lib
```

---

## 10. 참고자료

- [NVIDIA CUDA Runtime API — cudaErrorNoKernelImageForDevice](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__TYPES.html) (Error 209)
- [PyTorch CUDA Compute Capability 지원](https://pytorch.org/docs/stable/cpp_extension.html)
- Docker Image: `xxxxrt666/gpt-sovits:latest-cu128` (2026-02-09 빌드, 14.46GB)
- Docker Image: `xxxxrt666/gpt-sovits:latest-cu126-lite` (2026-02-09 빌드, 9.75GB)
- GPU: NVIDIA GeForce GTX 1070 — Compute Capability 6.1 (Pascal)
