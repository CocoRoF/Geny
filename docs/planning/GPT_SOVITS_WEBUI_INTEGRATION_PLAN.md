# GPT-SoVITS WebUI 통합 계획서

## 1. 현황 분석

### 1.1 GPT-SoVITS WebUI란?

GPT-SoVITS는 TTS API(`api_v2.py`, 포트 9880) 외에도 **Gradio 기반 WebUI**(`webui.py`)를 제공한다.
이 WebUI는 다음 기능들을 포함하는 종합 대시보드이다:

| 포트   | 용도                       | 설명                                |
|--------|----------------------------|-------------------------------------|
| `9871` | SoVITS Training WebUI      | SoVITS 모델 파인튜닝               |
| `9872` | GPT Training WebUI         | GPT 모델 파인튜닝                  |
| `9873` | UVR5 WebUI                 | 보컬/반주 분리, 리버브 제거         |
| `9874` | **메인 WebUI (Gradio)**    | 전체 파이프라인: 데이터 준비 → 학습 → 추론 |
| `9880` | API Server (`api_v2.py`)   | TTS REST API (현재 Geny에서 사용 중) |

WebUI(9874)에서 제공하는 주요 기능:
- 오디오 슬라이싱 (학습 데이터 분할)
- 노이즈 제거
- ASR (음성 인식 → 텍스트 라벨링)
- 전사 교정
- GPT/SoVITS 모델 파인튜닝
- 추론 테스트

### 1.2 현재 Geny 프로젝트 설정

```
# 현재 command (모든 docker-compose 파일 공통)
exec python api_v2.py -a 0.0.0.0 -p 9880
```

- **`api_v2.py`만 실행** → API 서버(9880)만 동작
- **WebUI(`webui.py`)는 실행되지 않음** → 9874 포트 미사용
- 노출 포트: `9880`만 (dev에서는 호스트 바인딩, prod에서는 expose only)
- Nginx(prod): GPT-SoVITS 관련 라우팅 없음

---

## 2. 통합 방안

### 방안 A: WebUI + API 동시 실행 (권장)

`webui.py`를 메인 프로세스로 실행하면 내부적으로 9874(메인 WebUI)를 서빙하고,
WebUI 내 추론 탭에서 API와 유사한 기능도 사용 가능.
단, **기존 `api_v2.py` (9880) 도 유지 필요** — Geny 백엔드가 이 API를 호출하므로.

**→ 두 프로세스를 동시에 실행하는 방식 채택**

```bash
# supervisord 또는 bash 병렬 실행
python webui.py &
exec python api_v2.py -a 0.0.0.0 -p 9880
```

### 방안 B: API만 유지 + WebUI 별도 서비스

GPT-SoVITS 컨테이너를 2개(api용, webui용) 분리 운영.
→ GPU 메모리 이중 소모, 복잡도 증가. **비권장.**

### 방안 C: 필요 시에만 WebUI 전환 (profile 분리)

WebUI가 필요할 때만 별도 profile로 올리는 방식.
→ 간편하지만 동시 사용 불가. **절충안.**

---

## 3. 구현 계획 (방안 A 기준)

### 3.1 Phase 1: Docker Compose 수정

#### 변경 대상 파일
- `docker-compose.yml`
- `docker-compose.dev.yml`
- `docker-compose.prod.yml`

#### 변경 내용

**1) command 수정 — WebUI + API 병렬 실행**

```yaml
command:
  - /bin/bash
  - "-c"
  - |
    # ... (기존 pip install / symlink 단계 동일) ...
    echo '[4/4] Starting GPT-SoVITS WebUI + API...';
    python webui.py &
    exec python api_v2.py -a 0.0.0.0 -p 9880
```

> `webui.py`는 Gradio를 9874로 서빙, `api_v2.py`는 9880로 서빙.
> `webui.py`가 백그라운드, `api_v2.py`가 포그라운드(exec) → 컨테이너 헬스체크는 API 기준.

**2) 포트 추가 노출**

```yaml
# dev (docker-compose.dev.yml, docker-compose.yml)
ports:
  - "127.0.0.1:${GPT_SOVITS_PORT:-9880}:9880"
  - "127.0.0.1:${GPT_SOVITS_WEBUI_PORT:-9874}:9874"

# prod (docker-compose.prod.yml)
expose:
  - "9880"
  - "9874"
```

### 3.2 Phase 2: Nginx 라우팅 추가 (Prod)

`nginx/nginx.conf`에 GPT-SoVITS WebUI 프록시 블록 추가:

```nginx
# ── GPT-SoVITS WebUI (Gradio) ──────────────────────────
upstream gpt-sovits-webui {
    server gpt-sovits:9874;
}

location /tts-studio/ {
    # tts-local 프로파일로 gpt-sovits가 올라왔을 때만 동작
    proxy_pass         http://gpt-sovits-webui/;
    proxy_http_version 1.1;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;

    # Gradio WebSocket 지원
    proxy_set_header   Upgrade    $http_upgrade;
    proxy_set_header   Connection $connection_upgrade;

    # Gradio 파일 업로드 (학습 데이터)
    client_max_body_size 500m;
    proxy_read_timeout   600s;
}
```

> Nginx에서 `gpt-sovits` 서비스가 없으면(프로파일 미활성) 502 반환.
> 프론트엔드에서 이를 감지하여 "TTS Studio 미실행" 메시지 표시 가능.

### 3.3 Phase 3: Geny 프론트엔드 — TTS Studio 탭 추가

#### 3.3.1 새 탭 등록

`TabNavigation.tsx`의 `GLOBAL_TAB_IDS`에 `'ttsStudio'` 추가:

```typescript
const GLOBAL_TAB_IDS = [
  'main', 'playground', 'workflows', 'toolSets',
  'sharedFolder', 'ttsStudio', 'settings'
] as const;
```

`DEV_ONLY_GLOBAL`에도 추가 (개발자 모드에서만 표시):

```typescript
const DEV_ONLY_GLOBAL = new Set(['workflows', 'toolSets', 'ttsStudio', 'settings']);
```

#### 3.3.2 TTS Studio 탭 컴포넌트

`frontend/src/components/tabs/TtsStudioTab.tsx` 신규 생성:

```tsx
'use client';

import { useState, useEffect } from 'react';

export default function TtsStudioTab() {
  const [available, setAvailable] = useState<boolean | null>(null);

  // WebUI 가용성 체크
  useEffect(() => {
    const checkAvailability = async () => {
      try {
        // dev: 직접 9874 접근, prod: /tts-studio/ 경유
        const url = process.env.NEXT_PUBLIC_API_URL
          ? '/tts-studio/'
          : `http://localhost:${process.env.NEXT_PUBLIC_GPT_SOVITS_WEBUI_PORT || 9874}`;
        const res = await fetch(url, { method: 'HEAD', mode: 'no-cors' });
        setAvailable(true);
      } catch {
        setAvailable(false);
      }
    };
    checkAvailability();
    const interval = setInterval(checkAvailability, 10000);
    return () => clearInterval(interval);
  }, []);

  if (available === false) {
    return (
      <div className="flex-1 flex items-center justify-center text-[var(--text-muted)]">
        <div className="text-center">
          <p className="text-lg font-medium mb-2">TTS Studio 미실행</p>
          <p className="text-sm">
            GPT-SoVITS WebUI가 실행 중이지 않습니다.<br/>
            <code>--profile tts-local</code> 옵션으로 시작해주세요.
          </p>
        </div>
      </div>
    );
  }

  // iframe으로 Gradio WebUI 임베딩
  const src = typeof window !== 'undefined' && window.location.port
    ? `http://${window.location.hostname}:9874`  // dev: 직접 접근
    : '/tts-studio/';                            // prod: nginx 프록시

  return (
    <div className="flex-1 overflow-hidden">
      <iframe
        src={src}
        className="w-full h-full border-none"
        title="GPT-SoVITS TTS Studio"
        allow="microphone"  // 음성 녹음 기능 지원
      />
    </div>
  );
}
```

#### 3.3.3 TabContent 등록

`TabContent.tsx`에 추가:

```typescript
const TtsStudioTab = dynamic(
  () => import('@/components/tabs/TtsStudioTab'),
  { ssr: false }
);

// TAB_MAP에 추가
const TAB_MAP: Record<string, React.ComponentType> = {
  // ...기존 탭들...
  ttsStudio: TtsStudioTab,
};
```

#### 3.3.4 i18n 키 추가

```json
// ko
"tabs.ttsStudio": "TTS Studio"

// en
"tabs.ttsStudio": "TTS Studio"
```

---

## 4. 접근 방식별 비교

| 항목 | Dev 환경 | Prod 환경 |
|------|----------|-----------|
| WebUI 접근 | `localhost:9874` (직접) 또는 iframe | Nginx `/tts-studio/` 경유 iframe |
| API 접근 | `localhost:9880` | 내부 네트워크 `gpt-sovits:9880` |
| 활성화 조건 | `--profile tts-local` | `--profile tts-local` |
| GPU 추가 소요 | 없음 (동일 컨테이너 내 실행) | 없음 |

---

## 5. 보안 고려사항

1. **Dev 환경**: `127.0.0.1` 바인딩 유지 → 외부 접근 차단
2. **Prod 환경**: Nginx 경유만 허용 (`expose`만 사용, `ports` 미사용)
3. **파일 업로드**: Gradio WebUI는 학습 데이터 업로드를 지원하므로 `client_max_body_size` 적절히 설정 (500MB)
4. **인증**: 현재 Geny에 자체 인증이 없다면 Gradio WebUI도 동일 레벨. 필요 시 Nginx에 Basic Auth 추가 고려

---

## 6. 작업 순서

| 단계 | 작업 | 영향 범위 |
|------|------|-----------|
| 1 | docker-compose command 수정 (webui.py 병렬 실행) | docker-compose.yml, dev.yml, prod.yml |
| 2 | 포트 노출 추가 (9874) | docker-compose.yml, dev.yml, prod.yml |
| 3 | nginx.conf에 `/tts-studio/` 라우팅 추가 | nginx/nginx.conf |
| 4 | `TtsStudioTab.tsx` 컴포넌트 생성 | frontend/src/components/tabs/ |
| 5 | `TabNavigation.tsx`, `TabContent.tsx` 등록 | frontend 탭 시스템 |
| 6 | i18n 키 추가 | frontend/src/lib/i18n |
| 7 | 동작 테스트 (dev → prod) | 전체 |

---

## 7. 대안: iframe 대신 외부 링크

iframe 임베딩이 Gradio CSP 정책으로 작동하지 않을 경우, 폴백 방안:

- TTS Studio 탭에 "새 창에서 열기" 버튼 배치
- `window.open()`으로 GPT-SoVITS WebUI를 별도 브라우저 탭에서 열기
- Gradio 측에서 `--share` 또는 CORS 설정 필요 여부 확인

> Gradio는 기본적으로 iframe 임베딩을 허용하지만, 동일 오리진이 아닌 경우
> 쿠키/세션 이슈가 발생할 수 있다. Dev에서 충분히 테스트 필요.
