# VRM 3D 아바타 시스템 통합 심층 분석

> 작성일: 2026-04-08  
> 상태: **분석 완료 — 구현 대기**

---

## 0. 핵심 요약

| 항목 | 결론 |
|------|------|
| README의 파란 머리 캐릭터 정체 | **ReLU** — AIRI의 오리지널 AI 캐릭터 (성격/페르소나). 전용 VRM 모델 파일은 **비공개** |
| 레포에 실제 포함된 VRM 모델 | `AvatarSample_A.vrm`, `AvatarSample_B.vrm` (VRoid Hub 샘플, CDN에서 다운로드) |
| Geny에 VRM 통합 가능 여부 | **가능** — Three.js 의존성 이미 설치됨, @react-three/fiber 인프라 존재 |
| 예상 난이도 | **중~상** — AIRI의 Vue 코드를 React로 재작성 필요, 코어 로직은 프레임워크 독립적 |
| ReLU 모델 확보 가능 여부 | **현재 불가** — 비공개. 대안으로 VRoid Hub의 공개 모델 사용 가능 |

---

## 1. ReLU 캐릭터 분석

### 1.1 ReLU는 "페르소나"이지, 전용 3D 모델이 아니다

AIRI 레포를 심층 분석한 결과, **ReLU(热卤)는 AI 캐릭터 페르소나**입니다:

- **정의 위치**: `packages/stage-ui/src/stores/modules/airi-card.ts`
- **성격 파일**: `services/telegram-bot/src/prompts/personality-v1.velin.md`
- **비주얼 에셋**: `relu.avif` (메뉴 이미지), 스티커 이미지들
- **설정**: 15세 디지털 의식체, 중국어/영어/일본어 혼용, 직설적 성격

README의 파란 머리 캐릭터는 **프로모션 일러스트**이며, 실제 앱 내에서는 `AvatarSample_A/B` (VRoid Hub 범용 모델)로 표시됩니다.

### 1.2 레포 내 VRM 모델 파일 현황

| 모델 | 형식 | 위치 | 비고 |
|------|------|------|------|
| AvatarSample_A | .vrm | CDN 다운로드 | `https://dist.ayaka.moe/vrm-models/VRoid-Hub/AvatarSample-A/AvatarSample_A.vrm` |
| AvatarSample_B | .vrm | CDN 다운로드 | `https://dist.ayaka.moe/vrm-models/VRoid-Hub/AvatarSample-B/AvatarSample_B.vrm` |
| idle_loop | .vrma | 로컬 번들 (154KB) | `packages/stage-ui-three/src/assets/vrm/animations/` |
| ReLU 전용 모델 | — | **존재하지 않음** | 비공개 또는 미완성 |

> .vrm 파일은 빌드 시 CDN에서 다운로드되며, Git에는 포함되어 있지 않습니다.

---

## 2. AIRI의 VRM 렌더링 시스템 분석

### 2.1 아키텍처 개요

```
┌─────────────────────────────────────────────────────┐
│  AIRI VRM Rendering Pipeline (Vue 3 + TresJS)       │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ThreeScene.vue (TresJS Canvas)                     │
│    ├── VRMModel.vue (모델 로딩/언로딩)               │
│    ├── SceneBootstrap (카메라/조명 설정)              │
│    └── PostProcessing (HueSaturation)               │
│                                                     │
│  Composables (프레임워크 독립 로직):                  │
│    ├── vrm/core.ts       — VRM 로딩 + 최적화        │
│    ├── vrm/expression.ts — 감정 표현 시스템          │
│    ├── vrm/animation.ts  — 눈깜빡임 + 사카드        │
│    ├── vrm/lip-sync.ts   — wLipSync 립싱크          │
│    ├── vrm/loader.ts     — GLTFLoader + VRM 플러그인│
│    ├── vrm/outline.ts    — 커스텀 아웃라인 셰이더    │
│    ├── vrm/hooks.ts      — 라이프사이클 훅 시스템    │
│    └── shader/ibl.ts     — IBL NPR 셰이더          │
│                                                     │
│  Stores (Pinia):                                    │
│    ├── model-store.ts    — 씬 상태 관리             │
│    └── display-models.ts — 모델 레지스트리           │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 2.2 핵심 의존성

| 패키지 | 버전 | 역할 |
|--------|------|------|
| `three` | ^0.183.2 | Three.js 코어 |
| `@pixiv/three-vrm` | ^3.5.1 | VRM 로딩/렌더링 |
| `@pixiv/three-vrm-animation` | ^3.5.1 | .vrma 애니메이션 |
| `@pixiv/three-vrm-core` | ^3.5.1 | VRM 코어 타입 |
| `@tresjs/core` | ^5.7.0 | Vue 3 Three.js 래퍼 (→ React 이식 시 불필요) |
| `wlipsync` | ^1.3.0 | ML 립싱크 (이미 Geny에 설치됨) |
| `postprocessing` | ^6.39.0 | 후처리 효과 |

### 2.3 VRM 로딩 파이프라인

**파일**: `packages/stage-ui-three/src/composables/vrm/core.ts`

```
.vrm 파일 로드
  → GLTFLoader + VRMLoaderPlugin + VRMAnimationLoaderPlugin
  → VRMUtils.removeUnnecessaryVertices() (정점 최적화)
  → VRMUtils.combineSkeletons() (스켈레톤 합치기)
  → frustumCulled = false (전체 오브젝트)
  → LookAt Quaternion Proxy 설정
  → BoundingBox 계산 (springBone 콜라이더 제외)
  → 카메라 초기 위치 계산 (FOV=40°)
  → { vrm, vrmGroup, modelCenter, modelSize, initialCameraOffset }
```

### 2.4 감정 표현 시스템

**파일**: `packages/stage-ui-three/src/composables/vrm/expression.ts`

| 감정 | VRM Expression | 강도 | 보조 블렌드 |
|------|---------------|------|------------|
| happy | happy | 0.7 | aa (입 벌림) |
| sad | sad | 0.7 | oh |
| angry | angry | 0.7 | ee |
| surprised | surprised | 0.8 | oh |
| neutral | neutral | 1.0 | — |
| think | — | 0.7 | 커스텀 |

- easeInOutCubic 보간으로 부드러운 전환
- 자동 리셋 타이머 지원
- 값 0.7~0.8로 제한 (과도한 표정 방지)

### 2.5 립싱크 시스템

**파일**: `packages/stage-ui-three/src/composables/vrm/lip-sync.ts`

| wLipSync 음소 | VRM BlendShape | 설명 |
|--------------|----------------|------|
| A | aa | 아 |
| E | ee | 에 |
| I | ih | 이 |
| O | oh | 오 |
| U | ou | 우 |
| S | ih | 무음 → 이 |

**파라미터**:
- ATTACK: 50ms (입 열리는 속도)
- RELEASE: 30ms (닫히는 속도)
- CAP: 0.7 (최대 블렌드 가중치)
- SILENCE_VOL: 0.04 (무음 임계값)
- IDLE_MS: 160ms (아이들 감지)

**알고리즘**: Winner + Runner — 상위 2개 음소만 블렌딩 (A-heavy 편향 방지)

### 2.6 애니메이션 시스템

**파일**: `packages/stage-ui-three/src/composables/vrm/animation.ts`

- **Idle**: `idle_loop.vrma` → AnimationMixer → AnimationClip → 루프 재생
- **Blink**: 0.2초 주기, 1~6초 랜덤 간격, sine 곡선
- **Eye Saccade**: 아이들 중 랜덤 시선 이동, VRM LookAt 타겟 시스템 사용

### 2.7 고급 렌더링

- **아웃라인 셰이더**: 뷰스페이스 기반 커스텀 아웃라인 (MToon 확장)
- **IBL**: Image-Based Lighting + NPR 셰이더 주입
- **후처리**: Hue-Saturation 조정
- **톤 매핑**: ACESFilmic
- **스프링 본 물리**: VRM springBoneManager 프레임별 업데이트

---

## 3. Geny 현재 3D 인프라 현황

### 3.1 이미 설치된 Three.js 의존성

| 패키지 | 버전 | 상태 |
|--------|------|------|
| `three` | ^0.183.1 | 설치됨 (AIRI와 거의 동일) |
| `@types/three` | ^0.183.1 | 설치됨 |
| `@react-three/fiber` | ^9.5.0 | 설치됨 (React Three.js 래퍼) |
| `@react-three/drei` | ^10.7.7 | 설치됨 (유틸리티) |
| `wlipsync` | ^1.3.0 | 설치됨 (립싱크 공유 가능) |
| `@pixiv/three-vrm` | — | **미설치** |
| `@pixiv/three-vrm-animation` | — | **미설치** |

### 3.2 기존 3D 사용 현황

**PlaygroundTab** (`components/tabs/PlaygroundTab.tsx`):
- @react-three/fiber Canvas 기반 3D 월드
- GLTFLoader로 3D 에셋 로딩 (건물, 도로, 자연물)
- Kenney 미니캐릭터 아바타 (본 애니메이션)
- A* 길찾기 시스템

**AssetLoader** (`lib/assetLoader.ts`):
- GLTF 모델 캐싱 시스템
- 카테고리별 에셋 관리

> Three.js 렌더링 인프라는 이미 존재하므로, VRM 지원 추가는 **확장** 수준입니다.

### 3.3 아바타 상태 관리

**useVTuberStore** (`store/useVTuberStore.ts`):
```
Backend SSE → avatarStates[sessionId] → Live2DCanvas 컴포넌트
```

현재 Live2D 전용이지만, renderer 타입 분기만 추가하면 VRM으로 확장 가능합니다.

### 3.4 아바타 상태 타입

```typescript
interface AvatarState {
  session_id: string;
  emotion: string;           // "neutral" | "joy" | "sadness" | ...
  expression_index: number;  // Live2D 전용
  motion_group: string;      // Live2D 전용
  motion_index: number;      // Live2D 전용
  intensity: number;         // 0~1
  transition_ms: number;
  trigger: string;
  timestamp: string;
}
```

---

## 4. 통합 구현 계획

### 4.1 Phase 구조

| Phase | 항목 | 예상 규모 | 의존성 |
|-------|------|----------|--------|
| **Phase 0** | 패키지 설치 + VRM 로더 코어 | 소 | 없음 |
| **Phase 1** | VRM3DCanvas 컴포넌트 (기본 렌더링) | 중 | Phase 0 |
| **Phase 2** | 감정/표정 + 눈깜빡임 + 사카드 | 중 | Phase 1 |
| **Phase 3** | 립싱크 (wLipSync 통합) | 중 | Phase 1 |
| **Phase 4** | 아바타 스토어 통합 + 렌더러 전환 UI | 중 | Phase 1~3 |
| **Phase 5** | 고급 렌더링 (아웃라인, IBL, 후처리) | 상 (선택) | Phase 1 |
| **Phase 6** | ReLU/커스텀 모델 지원 | 소 | Phase 4 |

### 4.2 Phase 0 — 패키지 설치 + 코어 타입

**새로 설치할 패키지**:
```bash
npm install @pixiv/three-vrm @pixiv/three-vrm-animation @pixiv/three-vrm-core
```

**새로 생성할 파일**:
```
frontend/src/lib/vrm/
├── index.ts              # Public API
├── types.ts              # VRM 관련 타입 정의
├── loader.ts             # GLTFLoader + VRM 플러그인 설정
└── core.ts               # VRM 로딩/최적화 함수
```

### 4.3 Phase 1 — VRM3DCanvas 컴포넌트

**핵심**: Live2DCanvas와 동일한 인터페이스를 가진 VRM 렌더러

```typescript
// 목표 API
interface VRM3DCanvasProps {
  sessionId: string;
  className?: string;
  interactive?: boolean;
  modelUrl: string;              // .vrm 파일 URL
  animationUrl?: string;         // .vrma 아이들 애니메이션 URL
  enhancedConfig?: Partial<VRMEnhancedConfig>;
}
```

**구현 요소**:
- @react-three/fiber `<Canvas>` 기반 렌더링
- VRM 모델 로딩 (GLTFLoader + VRMLoaderPlugin)
- OrbitControls 카메라
- 기본 조명 (Ambient + Directional)
- 아이들 애니메이션 루프
- 스프링 본 물리 (프레임별 update)
- ResizeObserver 반응형

### 4.4 Phase 2 — 감정/표정 + 애니메이션

**이식 대상** (AIRI → Geny, Vue → 프레임워크 독립):

| AIRI 파일 | Geny 대상 | 변환 내용 |
|-----------|----------|----------|
| `vrm/expression.ts` | `lib/vrm/expression.ts` | Vue ref → 클래스/함수 |
| `vrm/animation.ts` (blink) | `lib/vrm/blink.ts` | Vue composable → 클래스 |
| `vrm/animation.ts` (saccade) | `lib/vrm/saccade.ts` | Vue composable → 클래스 |

**감정 매핑** (Geny의 AvatarState.emotion → VRM Expression):

| Geny emotion | VRM Expression | 강도 |
|-------------|----------------|------|
| neutral | neutral | 1.0 |
| joy | happy | 0.7 |
| sadness | sad | 0.7 |
| anger | angry | 0.7 |
| surprise | surprised | 0.8 |
| fear | sad + surprised blend | 0.5 |
| disgust | angry (약화) | 0.5 |
| smirk | happy (약화) | 0.4 |

### 4.5 Phase 3 — 립싱크

wLipSync는 이미 Geny에 설치되어 있고, Live2D용 `enhancedLipSync.ts`에서 사용 중입니다.

**VRM 립싱크는 BlendShape 기반**:
```
wLipSync 음소 → VRM BlendShape (aa, ee, ih, oh, ou)
```

Live2D의 `ParamMouthOpenY` 단일 값이 아닌, **5개 모음별 블렌드셰이프**를 개별 제어합니다.
이는 더 풍부한 립싱크 표현이 가능하다는 것을 의미합니다.

### 4.6 Phase 4 — 스토어 통합 + 렌더러 전환

**model_registry.json 확장**:
```jsonc
{
  "models": [
    // 기존 Live2D 모델
    {
      "name": "mao_pro",
      "renderer": "live2d",        // ← 새 필드
      "url": "/static/live2d-models/mao_pro/runtime/mao_pro.model3.json",
      // ...
    },
    // 새 VRM 모델
    {
      "name": "avatar_sample_a",
      "renderer": "vrm",           // ← VRM 타입
      "display_name": "Avatar Sample A",
      "description": "VRoid Hub 샘플 캐릭터 A",
      "url": "/static/vrm-models/AvatarSample_A.vrm",
      "animationUrl": "/static/vrm-models/animations/idle_loop.vrma",
      "thumbnail": "/static/vrm-models/AvatarSample_A_preview.png",
      "emotionMap": {
        "neutral": "neutral",
        "joy": "happy",
        "sadness": "sad",
        "anger": "angry",
        "surprise": "surprised"
      }
    }
  ]
}
```

**VTuberPanel 렌더러 분기**:
```tsx
// VTuberPanel.tsx 또는 AvatarRenderer.tsx
{model.renderer === 'vrm' ? (
  <VRM3DCanvas sessionId={sessionId} modelUrl={model.url} />
) : (
  <Live2DCanvas sessionId={sessionId} />
)}
```

### 4.7 Phase 5 — 고급 렌더링 (선택)

| 기능 | 복잡도 | 가치 |
|------|--------|------|
| MToon 아웃라인 셰이더 | 상 | 애니풍 외곽선 효과 |
| IBL (Image-Based Lighting) | 중 | 환경 반사 조명 |
| 후처리 (Hue-Saturation) | 하 | 색감 보정 |
| 톤 매핑 (ACESFilmic) | 하 | HDR 톤 매핑 |

> Phase 5는 시각적 품질 향상을 위한 선택 사항입니다. 기본 VRM 렌더링만으로도 충분히 동작합니다.

### 4.8 Phase 6 — 모델 확보 및 등록

**VRM 모델 확보 방법**:

| 방법 | 가능 여부 | 비고 |
|------|----------|------|
| AIRI AvatarSample_A/B 다운로드 | O | `dist.ayaka.moe` CDN에서 공개 다운로드 |
| VRoid Hub 공개 모델 | O | 수만 개의 무료 VRM 모델 |
| VRoid Studio로 자체 제작 | O | 커스텀 캐릭터 생성 가능 |
| ReLU 전용 VRM 모델 | X | 비공개 (AIRI 팀 연락 필요) |
| Booth/Nizima 유료 모델 | O | 라이선스 확인 필요 |

**즉시 사용 가능한 모델 URL**:
```
https://dist.ayaka.moe/vrm-models/VRoid-Hub/AvatarSample-A/AvatarSample_A.vrm
https://dist.ayaka.moe/vrm-models/VRoid-Hub/AvatarSample-B/AvatarSample_B.vrm
```

---

## 5. 생성될 파일 구조 (예상)

```
frontend/src/
├── lib/vrm/
│   ├── index.ts                  # Public API exports
│   ├── types.ts                  # VRM 관련 타입 정의
│   ├── loader.ts                 # GLTFLoader + VRM 플러그인
│   ├── core.ts                   # VRM 로딩/최적화
│   ├── expression.ts             # 감정 표현 컨트롤러
│   ├── blink.ts                  # 눈깜빡임 애니메이션
│   ├── saccade.ts                # 시선 미세이동
│   └── lipSync.ts                # VRM 립싱크 (5모음 블렌드)
│
├── components/vrm/
│   ├── VRM3DCanvas.tsx           # VRM 3D 렌더러 컴포넌트
│   └── VRMScene.tsx              # Three.js 씬 구성
│
├── components/live2d/
│   └── AvatarRenderer.tsx        # Live2D/VRM 자동 전환 래퍼
│
└── static/ (backend)
    └── vrm-models/
        ├── AvatarSample_A.vrm
        ├── AvatarSample_A_preview.png
        ├── AvatarSample_B.vrm
        ├── AvatarSample_B_preview.png
        └── animations/
            └── idle_loop.vrma
```

---

## 6. AIRI vs Geny 기술 스택 매핑

| 영역 | AIRI (Vue 3) | Geny (React 19) | 이식 전략 |
|------|-------------|-----------------|----------|
| 3D 래퍼 | TresJS (@tresjs/core) | @react-three/fiber | API 다르지만 Three.js 코어 동일 |
| 카메라 | @tresjs/cientos OrbitControls | @react-three/drei OrbitControls | 거의 동일 |
| 상태 관리 | Pinia store | Zustand store | 1:1 매핑 가능 |
| 반응형 | Vue ref/computed | React useRef/useMemo | 패턴 변환 |
| VRM 로딩 | @pixiv/three-vrm | @pixiv/three-vrm | **동일 — 그대로 사용** |
| 립싱크 | wlipsync | wlipsync | **동일 — 이미 설치됨** |
| 후처리 | @tresjs/post-processing | @react-three/postprocessing | 유사 API |

> **핵심 포인트**: VRM 로딩/렌더링 코어 (`@pixiv/three-vrm`)는 프레임워크 독립적이므로 그대로 사용 가능합니다. 변환이 필요한 것은 Vue → React 컴포넌트 래퍼뿐입니다.

---

## 7. 리스크 및 고려사항

### 7.1 기술적 리스크

| 리스크 | 영향 | 완화 방안 |
|--------|------|----------|
| VRM 모델 파일 크기 (10~50MB) | 초기 로딩 지연 | 로딩 프로그레스 바 + 캐싱 |
| WebGL 컨텍스트 충돌 (Pixi + Three.js) | 동시 사용 시 GPU 메모리 | 렌더러 선택 방식 (동시 X) |
| 스프링 본 물리 성능 | 모바일 디바이스 부하 | maxFPS 제한 + LOD |
| MToon 셰이더 호환성 | 일부 GPU에서 렌더링 이상 | 기본 PBR 폴백 |

### 7.2 기존 시스템 영향

| 기존 기능 | 영향 | 대응 |
|-----------|------|------|
| Live2D 아바타 | 영향 없음 | renderer 필드로 분기, 기존 코드 변경 없음 |
| TTS 립싱크 | 공유 가능 | AudioManager + wLipSync 재사용 |
| SSE 아바타 상태 | 확장 필요 | emotion 필드는 그대로, VRM 매핑 추가 |
| 모델 레지스트리 | 확장 필요 | renderer 필드 추가 (후방 호환) |

### 7.3 후방 호환성 보장 전략

```jsonc
// model_registry.json — 기존 모델에 renderer 필드가 없으면 "live2d"로 기본 처리
{
  "name": "mao_pro",
  // "renderer" 필드 없음 → 자동으로 "live2d"
  "url": "/static/live2d-models/mao_pro/runtime/mao_pro.model3.json",
  // ...
}
```

---

## 8. 우선순위 권고

### 즉시 실행 가능 (Phase 0~1)
1. `@pixiv/three-vrm` 패키지 설치
2. VRM 샘플 모델 다운로드 (AvatarSample_A/B)
3. VRM3DCanvas 기본 컴포넌트 구현
4. 아이들 애니메이션 루프

### 단기 목표 (Phase 2~4)
5. 감정 표현 + 눈깜빡임
6. wLipSync VRM 립싱크
7. 렌더러 전환 UI

### 선택 사항 (Phase 5~6)
8. 아웃라인 셰이더
9. 커스텀 모델 업로드 지원
10. ReLU 모델 확보 시 등록

---

## 9. 결론

VRM 3D 아바타 통합은 **기술적으로 충분히 가능**합니다:

- Geny에 Three.js 인프라가 이미 존재 (`@react-three/fiber`, `three`)
- AIRI의 VRM 코어 로직은 프레임워크 독립적 (`@pixiv/three-vrm`)
- 립싱크 라이브러리를 이미 공유 (`wlipsync`)
- Live2D 시스템과 독립적으로 공존 가능 (renderer 필드 분기)

**ReLU 캐릭터**는 현재 비공개이지만, VRoid Hub의 공개 모델이나 자체 제작 모델로 VRM 시스템을 먼저 구축한 후, ReLU 모델 확보 시 즉시 등록할 수 있는 구조입니다.

---

*이 문서는 `Geny/docs/AIRI_이식_구현_리포트.md`의 후속 분석으로, VRM 3D 통합에 대한 심층 검토 결과입니다.*
