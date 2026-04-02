# GPT-SoVITS 디버깅 명령어

## 1단계 결과 분석

- FFmpeg: conda FFmpeg **8.0** 설치됨 (`/root/conda`)
- torch: 2.10.0+cu126, torchaudio: 2.10.0+cu126 ✅
- ldconfig에는 apt FFmpeg **4** 라이브러리만 등록 (libavcodec.so.58 등)
- **문제**: torchaudio가 conda FFmpeg 8 so파일을 찾지 못함 → libtorchcodec 로딩 실패

## 2단계: conda FFmpeg 라이브러리 연결 확인

```bash
# conda FFmpeg8 so파일 위치 찾기
docker exec geny-gpt-sovits-prod find /root/conda -name "libavcodec*" -o -name "libavformat*" -o -name "libavutil*" 2>/dev/null

# LD_LIBRARY_PATH에 conda lib 포함 확인
docker exec geny-gpt-sovits-prod bash -c 'echo $LD_LIBRARY_PATH'

# conda FFmpeg so 직접 로딩 테스트
docker exec geny-gpt-sovits-prod python -c "
import ctypes, glob
for lib in ['libavcodec', 'libavformat', 'libavutil']:
    paths = glob.glob(f'/root/conda/lib/{lib}*')
    print(f'{lib}: {paths}')
"
```

## 3단계: soundfile 백엔드로 우회 시도

```bash
# soundfile 설치 (libsndfile 의존)
docker exec geny-gpt-sovits-prod pip install soundfile

# soundfile로 wav 읽기 테스트
docker exec geny-gpt-sovits-prod python -c "
import soundfile as sf
data, sr = sf.read('/workspace/GPT-SoVITS/references/paimon_ko/ref_joy.wav')
print(f'soundfile OK: shape={data.shape}, sr={sr}')
"

# torchaudio로 wav 읽기 테스트 (soundfile 설치 후 자동 폴백)
docker exec geny-gpt-sovits-prod python -c "
import torchaudio
waveform, sr = torchaudio.load('/workspace/GPT-SoVITS/references/paimon_ko/ref_joy.wav')
print(f'torchaudio.load OK: shape={waveform.shape}, sr={sr}')
"
```

## 4단계: is_half 설정 확인

```bash
# GPT-SoVITS가 is_half를 어디서 읽는지 확인
docker exec geny-gpt-sovits-prod grep -rn "is_half" /workspace/GPT-SoVITS/GPT_SoVITS/ --include="*.py" | head -20

# config 파일에서 is_half 확인
docker exec geny-gpt-sovits-prod grep -rn "is_half" /workspace/GPT-SoVITS/ --include="*.yaml" --include="*.json" | head -10

# 환경변수 확인
docker exec geny-gpt-sovits-prod bash -c 'echo is_half=$is_half'
```

## 5단계: TTS API 직접 테스트

```bash
# references 폴더 내용 확인
docker exec geny-gpt-sovits-prod ls -la /workspace/GPT-SoVITS/references/

# 3단계 성공 후: curl로 TTS API 직접 호출
docker exec geny-gpt-sovits-prod curl -s -X POST http://localhost:9880/tts \
  -H "Content-Type: application/json" \
  -d '{"text":"안녕하세요","text_lang":"ko","ref_audio_path":"/workspace/GPT-SoVITS/references/paimon_ko/ref_joy.wav","prompt_lang":"ko","prompt_text":"테스트"}' \
  -o /tmp/test.wav && echo "TTS OK" || echo "TTS FAILED"
```

## 현재 진행: TTS API 테스트

nvidia-npp-cu12 설치 후 서버 재시작 필요 (실행 중인 서버가 이전 상태):

    docker compose -f docker-compose.prod.yml --profile tts-local up -d gpt-sovits

재시작 후 로그 확인:

    docker logs -f geny-gpt-sovits-prod

서버 뜬 후 python으로 TTS API 테스트 (curl은 conda libcurl 충돌):

    docker exec geny-gpt-sovits-prod python -c "import requests,json; r=requests.post('http://localhost:9880/tts',json={'text':'안녕하세요','text_lang':'ko','ref_audio_path':'/workspace/GPT-SoVITS/references/paimon_ko/ref_joy.wav','prompt_lang':'ko','prompt_text':'테스트'}); print(r.status_code, len(r.content), 'bytes')"

200이 나오면 성공.
