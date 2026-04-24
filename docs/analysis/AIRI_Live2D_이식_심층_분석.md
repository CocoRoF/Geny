# AIRI Live2D 아바타 → Geny 이식 심층 분석 리포트

> 작성일: 2026-04-08  
> 대상 프로젝트: AIRI (Project AIRI v0.9.0-beta.7) → Geny (VTuber Service)

---

## 목차

1. [Executive Summary](#1-executive-summary)
2. [AIRI 프로젝트 아키텍처 총괄](#2-airi-프로젝트-아키텍처-총괄)
3. [AIRI Live2D 렌더링 시스템 심층 분석](#3-airi-live2d-렌더링-시스템-심층-분석)
4. [Geny Live2D 렌더링 시스템 현황](#4-geny-live2d-렌더링-시스템-현황)
5. [핵심 기술 스택 비교](#5-핵심-기술-스택-비교)
6. [이식 가능성 분석](#6-이식-가능성-분석)
7. [이식 전략 및 작업 분류](#7-이식-전략-및-작업-분류)
8. [리스크 분석](#8-리스크-분석)
9. [단계별 구현 로드맵](#9-단계별-구현-로드맵)
10. [결론 및 권고사항](#10-결론-및-권고사항)

---

## 1. Executive Summary

### 결론: 이식 가능 (조건부)

AIRI의 Live2D 아바타는 Geny에 이식할 수 있다. 두 프로젝트 모두 **동일한 핵심 렌더링 라이브러리**(pixi-live2d-display + Cubism 4 SDK)를 사용하고 있어 기술적 호환성이 확보되어 있다. 그러나 다음 영역에서 상당한 적응 작업이 필요하다:

| 영역 | 난이도 | 비고 |
|------|--------|------|
| 모델 파일 호환 | **낮음** | 동일한 Cubism 4 포맷 (.model3.json, .moc3) |
| 렌더링 엔진 호환 | **중간** | pixi.js v6 vs v7, pixi-live2d-display 버전 차이 |
| 프레임워크 전환 | **높음** | Vue 3 → React 19 컴포넌트 재작성 필요 |
| 아키텍처 패러다임 | **높음** | 클라이언트 주도 → 서버 주도 전환 |
| 고급 기능 이식 | **중간~높음** | Beat Sync, wLipSync, Expression Controller 등 |
| VRM 3D 모델 지원 | **별도 판단** | Geny 현재 미지원, 추가 시 대규모 작업 필요 |

---

## 2. AIRI 프로젝트 아키텍처 총괄

### 2.1 프로젝트 개요

AIRI (Project AIRI)는 Neuro-sama 스타일의 오픈소스 AI VTuber 플랫폼이다. "soul container"라는 개념 아래 가상 AI 캐릭터를 구현하며, 다중 플랫폼을 지원한다.

- **버전**: 0.9.0-beta.7
- **패키지 매니저**: pnpm v10.32.1
- **모노레포 도구**: Turbo
- **빌드 도구**: Vite 8.0.2
- **프레임워크**: Vue 3 (Composition API)
- **상태관리**: Pinia 3.0.4
- **언어**: TypeScript

### 2.2 모노레포 패키지 구조

```
airi/
├── apps/
│   ├── stage-web/              # 브라우저 버전 (airi.moeru.ai)
│   ├── stage-tamagotchi/       # 데스크톱 버전 (Electron)
│   ├── stage-pocket/           # 모바일 버전 (Capacitor)
│   └── stage-docs/             # 문서 사이트
│
├── packages/
│   ├── stage-ui/               # 공유 UI 컴포넌트 & 스토어
│   ├── stage-ui-live2d/        # ★ Live2D 2D 렌더링 시스템
│   ├── stage-ui-three/         # ★ Three.js VRM 3D 렌더링
│   ├── pipelines-audio/        # 오디오 처리 파이프라인
│   ├── model-driver-lipsync/   # 립싱크 드라이버 (wLipSync)
│   ├── core-character/         # 캐릭터 감정/텍스트 분할
│   ├── audio/                  # Web Audio API 래퍼
│   ├── drizzle-duckdb-wasm/    # DuckDB WASM ORM
│   └── ...
│
└── services/
    ├── discord-bot/
    ├── telegram-bot/
    ├── minecraft-agent/
    └── factorio-agent/
```

### 2.3 듀얼 렌더링 아키텍처

AIRI의 핵심 차별점은 **2D(Live2D)와 3D(VRM)를 동시 지원**하는 듀얼 렌더링 아키텍처이다.

```
                    ┌─────────────────────────┐
                    │   Display Model Store    │
                    │   (format discriminator) │
                    └────────┬────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼                              ▼
   ┌──────────────────┐          ┌──────────────────┐
   │ stage-ui-live2d  │          │  stage-ui-three   │
   │ (Pixi.js 6.x)   │          │  (Three.js 0.183) │
   │ Cubism 4 모델    │          │  VRM 0.0/1.0 모델 │
   └──────────────────┘          └──────────────────┘
```

**모델 포맷 분류 (DisplayModelFormat enum)**:
```typescript
enum DisplayModelFormat {
  Live2dZip = 'live2d-zip',           // ZIP 압축 Cubism 4
  Live2dDirectory = 'live2d-directory', // 디렉토리 기반 Cubism 4
  VRM = 'vrm',                         // VRM 0.0/1.0 3D 모델
  PMXZip = 'pmx-zip',                 // MMD 모델 (미구현)
  PMXDirectory = 'pmx-directory',
  PMD = 'pmd',
}
```

### 2.4 LLM 통합

AIRI는 **xsai**라는 자체 LLM 통합 레이어를 통해 20개 이상의 프로바이더를 지원한다:
OpenAI, Claude, DeepSeek, Qwen, Groq, Mistral 등

Geny의 LangGraph 기반 멀티에이전트 시스템과는 근본적으로 다른 접근이며, 이 부분은 이식 대상이 아니다.

---

## 3. AIRI Live2D 렌더링 시스템 심층 분석

### 3.1 기술 스택 상세

```
패키지: @proj-airi/stage-ui-live2d

핵심 의존성:
├── @pixi/app:         ^6.5.10
├── @pixi/core:        ^6.5.10
├── @pixi/display:     ^6.5.10
├── @pixi/interaction:  ^6.5.10
├── @pixi/ticker:      ^6.5.10
├── @pixi/sprite:      ^6.5.10
├── pixi-live2d-display: ^0.4.0
├── pixi-filters:      4
├── animejs:           ^4.3.6
├── culori:            ^4.0.2
├── jszip:             ^3.10.1
└── es-toolkit:        (Mutex 등)
```

> **핵심 차이**: AIRI는 pixi.js를 **모듈 단위(@pixi/*)로 개별 import**하여 번들 사이즈를 최적화한다. Geny는 `pixi.js` 패키지를 통째로 사용한다.

### 3.2 컴포넌트 계층 구조

```
Live2D.vue (Root)
├── Canvas.vue          # Pixi.js Application 초기화
│   └── Model.vue       # 모델 로딩, 스케일링, 애니메이션
│       ├── MotionManager       # 플러그인 기반 모션 파이프라인
│       ├── ExpressionController # 표정 파라미터 블렌딩
│       ├── BeatSyncController   # 오디오 비트 동기화
│       └── DropShadowFilter     # 그림자 렌더링
```

### 3.3 Live2D.vue — 루트 컴포넌트

**상태 머신**: `'pending' | 'loading' | 'mounted'` (3단계: 컴포넌트 → 캔버스 → 모델)

**Props 인터페이스** (외부 제어 포인트):
```typescript
{
  modelSrc?: string              // 모델 URL/경로
  modelId?: string               // 고유 모델 식별자
  paused?: boolean               // 렌더링 일시정지 (default: false)
  mouthOpenSize?: number         // 입 열림 크기 (0-100)
  focusAt?: { x, y }             // 시선 집중점
  disableFocusAt?: boolean
  scale?: number                 // 스케일 배율 (default: 1)
  
  // 테마 / 시각 설정
  themeColorsHue?: number        // 색조 (default: 220.44)
  themeColorsHueDynamic?: boolean
  
  // 애니메이션 플래그
  live2dIdleAnimationEnabled: boolean    // Idle 모션 (default: true)
  live2dAutoBlinkEnabled: boolean        // 자동 눈깜빡임 (default: true)
  live2dForceAutoBlinkEnabled: boolean   // 강제 눈깜빡임 (default: false)
  live2dExpressionEnabled: boolean       // 표정 시스템 (default: true)
  live2dShadowEnabled: boolean           // 그림자 (default: true)
  
  // 성능 설정
  live2dMaxFps?: number          // FPS 제한 (0=무제한)
  live2dRenderScale?: number     // 렌더 해상도 배율 (default: 2 = HiDPI)
}
```

### 3.4 Canvas.vue — Pixi.js 초기화

```javascript
// Pixi.js Application 설정
new Application({
  width: props.width * props.resolution,
  height: props.height * props.resolution,
  backgroundAlpha: 0,           // 투명 배경
  preserveDrawingBuffer: true,  // 캔버스 캡처 지원
  autoDensity: false,
  resolution: 1,                // stage.scale로 HiDPI 처리
})

// Live2D 등록
Live2DModel.registerTicker(Ticker)
// TickerPlugin 확장 설치
// Error guard로 ticker 에러 시 자동 중지
// Stage scale = props.resolution (HiDPI 지원)
```

### 3.5 Model.vue — 모델 로딩 파이프라인

**로딩 프로세스**:
1. **Mutex Lock** (es-toolkit) — 동시 로딩 방지
2. `Live2DFactory.setupLive2DModel(live2DModel, { url, id }, { autoInteract: false })`
3. 스케일 계산: **2.2x offset factor** (모바일/데스크톱 공용)
4. 리사이즈 애니메이션: anime.js, 200ms 'outQuad' 이징

**파라미터 바인딩 시스템** — 모든 Live2D 파라미터를 개별 watch:
```
Angles:    ParamAngleX, ParamAngleY, ParamAngleZ
           ParamBodyAngleX, ParamBodyAngleY, ParamBodyAngleZ
Eyes:      ParamEyeLOpen, ParamEyeROpen
           ParamEyeBallX, ParamEyeBallY, ParamEyeSmile  
Eyebrows:  ParamBrowLX, ParamBrowRX, ParamBrowLY, ParamBrowRY
           ParamBrowLAngle, ParamBrowRAngle, ParamBrowLForm, ParamBrowRForm
Mouth:     ParamMouthOpenY, ParamMouthForm
Face:      ParamCheek, ParamBreath
```

> 20개 이상의 파라미터를 **개별 reactive watch**로 실시간 갱신 — 모델 리로드 없이 즉시 반영

### 3.6 Motion Manager — 플러그인 파이프라인

AIRI의 모션 시스템은 **플러그인 기반 파이프라인**으로 설계되어 있다. 이것이 Geny와의 가장 큰 아키텍처 차이이다.

```
┌──────────────────────────────────────────────────────────┐
│                    Motion Update Cycle                     │
│                                                            │
│  PRE-plugins ──→ Hooked Update ──→ POST-plugins ──→ FINAL │
│  (always)        (if !handled)      (always)       (always)│
│                                                            │
│  ┌──────────┐   ┌──────────────┐   ┌─────────────┐        │
│  │ Beat     │   │ SDK Default  │   │ Idle Focus  │        │
│  │ Sync     │   │ Motion       │   │ (eye        │        │
│  │          │   │ Update       │   │  saccades)  │        │
│  └──────────┘   └──────────────┘   └─────────────┘        │
│  ┌──────────┐                       ┌─────────────┐        │
│  │ Idle     │                       │ Auto Eye    │        │
│  │ Disable  │                       │ Blink       │        │
│  └──────────┘                       └─────────────┘        │
│                                     ┌─────────────┐        │
│                                     │ Expression  │        │
│                                     │ Plugin      │        │
│                                     └─────────────┘        │
└──────────────────────────────────────────────────────────┘
```

#### 3.6.1 Beat Sync Plugin (PRE)
- **물리 기반 스프링 시뮬레이션**: stiffness=120, damping=16, mass=1
- Semi-implicit Euler 적분으로 속도 추적
- `ParamAngleX/Y/Z` 제어
- velocity & error < 0.01 일 때 snap

**Beat Pattern 스타일**:
```typescript
type BeatSyncStyleName = 'punchy-v' | 'balanced-v' | 'swing-lr' | 'sway-sine'

'punchy-v':   { topYaw: 10, topRoll: 8,  bottomDip: 4,  pattern: 'v' }
'balanced-v': { topYaw: 6,  topRoll: 0,  bottomDip: 6,  pattern: 'v' }
'swing-lr':   { topYaw: 8,  topRoll: 0,  bottomDip: 6,  swingLift: 8, pattern: 'swing' }
'sway-sine':  { topYaw: 10, topRoll: 0,  bottomDip: 0,  swingLift: 10, pattern: 'sway' }
```

**자동 BPM 스타일 전환**:
- < 120 BPM → swing-lr
- 120~180 BPM → balanced-v  
- > 180 BPM → punchy-v
- Release delay: 1800ms (비트 없으면 중립으로 복귀)

#### 3.6.2 Auto Eye Blink Plugin (FINAL)
- 3단계 상태: idle → closing → opening
- 타이밍: 75ms close + 75ms open
- 간격: 3000~8000ms 랜덤
- **듀얼 모드**:
  - Expression OFF → absolute write (직접 교체)
  - Expression ON → multiply-modulation (표정 값 위에 곱셈 적용)
- Force Auto Blink: Idle 모션에 눈깜빡임 커브가 없는 모델용 타이머 기반

#### 3.6.3 Expression Plugin (FINAL)
- Expression Store에서 파라미터 오버라이드를 읽어 적용
- `handled` 플래그 무시 — 항상 실행
- Blend 모드: Add / Multiply / Overwrite

#### 3.6.4 Idle Focus Plugin (POST)
- Idle 상태에서 시선 미세 이동 (saccade)
- EyeBallX, EyeBallY 파라미터에 0.3 lerp factor 적용
- 랜덤 타깃: [-1, 1] × [-1, 0.7] 범위

### 3.7 Expression Controller — 표정 시스템

AIRI의 표정 시스템은 Geny보다 훨씬 정교하다.

**Expression Entry 구조**:
```typescript
interface ExpressionEntry {
  name: string              // 표정 그룹명 또는 파라미터 ID
  parameterId: string       // Live2D 파라미터 ID
  blend: 'Add' | 'Multiply' | 'Overwrite'
  currentValue: number      // 프레임별 적용 값
  defaultValue: number      // 사용자 커스텀 기본값 (localStorage)
  modelDefault: number      // moc3/exp3 원본 기본값
  targetValue: number       // exp3 활성화 시 목표값
  resetTimer?: ReturnType<typeof setTimeout>  // 자동 리셋 타이머
}
```

**Blend 모드 동작**:
```
Add:       최종값 = modelDefault + currentValue          (identity: 0)
Multiply:  최종값 = currentFrameValue × currentValue     (identity: 1)
Overwrite: 최종값 = currentValue                         (identity: modelDefault)
```

**Expression Parsing Pipeline**:
1. model3.json에서 `FileReferences.Expressions[]` 읽기
2. 각 exp3.json 파싱 → `Exp3Parameter[]` 추출
3. 파라미터별 blend 모드와 값으로 ExpressionEntry 생성
4. Noop 감지: identity 값이면 skip하여 불필요한 write 방지

**LLM 노출 도구 함수**:
```typescript
expression_set(name, value, duration?)    // 표정 설정
expression_get(name?)                      // 현재 상태 조회
expression_toggle(name, duration?)         // 토글
expression_save_defaults()                 // 기본값 저장
expression_reset_all()                     // 전체 리셋
```

### 3.8 감정 시스템 (Emotion)

```typescript
enum Emotion {
  Happy = 'happy',      // → Motion: 'Happy'
  Sad = 'sad',          // → Motion: 'Sad'
  Angry = 'angry',      // → Motion: 'Angry'
  Think = 'think',      // → Motion: 'Think'
  Surprise = 'surprised', // → Motion: 'Surprise'
  Awkward = 'awkward',  // → Motion: 'Awkward'
  Question = 'question', // → Motion: 'Question'
  Curious = 'curious',  // → Motion: 'Curious'
  Neutral = 'neutral',  // → Motion: 'Idle'
}
```

### 3.9 Lip Sync 시스템 — wLipSync 기반

AIRI는 단순 RMS 진폭이 아닌 **ML 기반 음소 감지(wLipSync)**를 사용한다.

**패키지**: `@proj-airi/model-driver-lipsync`

```typescript
// 핵심 API
async function createLive2DLipSync(
  audioContext: AudioContext,
  profile: Profile,
  options?: Live2DLipSyncOptions
): Promise<Live2DLipSync>

interface Live2DLipSync {
  node: WLipSyncNode          // Web Audio 워크렛 노드
  getVowelWeights(): Record<VowelKey, number>  // AEIOU 가중치
  getMouthOpen(): number      // 최종 입 열림 값
  connectSource(source: AudioNode): void
}
```

**음소 매핑**: AEIOUS → AEIOU (S는 'I'에 매핑하여 부드러운 닫힘 효과)

**입 열림 계산**:
```
volume = min(node.volume * volumeScale, 1) ^ volumeExponent
vowelWeight = max(vowelWeight, min(cap, rawValue * volume))
mouthOpen = max(...vowelWeights)
```

**기본 옵션**:
- cap: 0.7 (과도한 열림 방지)
- volumeScale: 0.9
- volumeExponent: 0.7
- mouthUpdateIntervalMs: 40 (~25fps)
- mouthLerpWindowMs: 120 (스무딩)

### 3.10 모델 저장 시스템

| 저장소 | 용도 |
|--------|------|
| IndexedDB (localforage) | 모델 파일 바이너리 |
| OPFS (Origin Private File System) | 대용량 모델 파일 |
| localStorage | 표정 기본값, 모션 설정, 포지션 |
| BroadcastChannel API | 크로스 탭 동기화 |

### 3.11 VRM 3D 렌더링 시스템 (참고)

AIRI는 Live2D 외에 VRM 3D 아바타도 지원한다:

```
stage-ui-three/
├── ThreeScene.vue        # 루트 씬 오케스트레이터
├── VRMModel.vue          # 모델 로딩, 셰이더 주입, 애니메이션
├── OrbitControls.vue     # 인터랙티브 카메라
└── SkyBox.vue            # IBL 환경 조명
```

**핵심 라이브러리**:
- three.js v0.183.2
- @pixiv/three-vrm v3.5.1
- @tresjs/core v5.7.0 (Vue 3 Three.js 바인딩)
- wlipsync v1.3.0

**VRM Lip Sync**:
- wLipSync → 음소 분류 (aa, ee, ih, oh, ou)
- Attack 50ms / Release 30ms 스무딩
- Winner + runner 방식 (상위 2개 음소 가중치)
- 160ms 무음 시 자동 리셋

---

## 4. Geny Live2D 렌더링 시스템 현황

### 4.1 기술 스택

```
프레임워크: Next.js 16.1.6 + React 19.2.3
상태관리:   zustand 5.0.11
렌더링:     pixi.js 7.4.3 + pixi-live2d-display 0.5.0-beta
3D (City):  @react-three/fiber 9.5.0, three 0.183.1
백엔드:     FastAPI + LangGraph
```

### 4.2 컴포넌트 구조

```
Live2DCanvas.tsx (단일 컴포넌트)
├── Dynamic script loading (Cubism Core SDK)
├── Pixi.js Application 초기화
├── pixi-live2d-display 모델 로딩
├── Expression/Motion 제어
├── 마우스 시선 추적
├── Hit Area 클릭 감지
├── LipSyncController 연동
└── ResizeObserver 반응형
```

### 4.3 렌더링 파이프라인

```typescript
// SDK 로딩
const win = window as any;
if (!win.Live2DCubismCore) {
  const script = document.createElement('script');
  script.src = '/lib/live2d/live2dcubismcore.min.js';
}

// 모델 초기화
const PIXI = await import('pixi.js');
const { Live2DModel } = await import('pixi-live2d-display/cubism4');
Live2DModel.registerTicker(PIXI.Ticker);

// 표정/모션 제어
live2dModel.expression(expressionIndex);   // 인덱스 기반
live2dModel.motion(motionGroup, motionIndex);

// 립싱크
coreModel.setParameterValueById('ParamMouthOpenY', mouthOpenValue);
```

### 4.4 Lip Sync — 단순 RMS 방식

```typescript
class LipSyncController {
  SMOOTHING = 0.3;
  MOUTH_OPEN_SCALE = 1.8;
  THRESHOLD = 0.015;

  onAmplitude = (amplitude: number) => {
    this.smoothValue = 0.3 * this.smoothValue + 0.7 * amplitude;
    const mouthOpen = (this.smoothValue > 0.015)
      ? Math.min(this.smoothValue * 1.8, 1.0)
      : 0;
    coreModel.setParameterValueById('ParamMouthOpenY', mouthOpen);
  };
}
```

### 4.5 감정/모션 시스템

**백엔드 주도**:
```python
# EmotionExtractor — 텍스트에서 감정 태그 추출
regex: \[([a-zA-Z_]+)\]
# "[joy] Hello!" → emotion="joy", expression_index=3

# AvatarStateManager — SSE로 프론트엔드에 브로드캐스트
emotion → motion 매핑:
  joy, surprise, anger → "TapBody"
  sadness, fear, disgust, neutral → "Idle"
```

**프론트엔드 적용**:
```typescript
// SSE 이벤트 수신 → Zustand 스토어 갱신 → Live2D 렌더링
live2dModel.expression(state.expression_index);
live2dModel.motion(state.motion_group, state.motion_index);
```

### 4.6 Model Registry

```json
{
  "name": "mao_pro",
  "url": "/static/live2d-models/mao_pro/runtime/mao_pro.model3.json",
  "kScale": 0.5,
  "idleMotionGroupName": "Idle",
  "emotionMap": {
    "neutral": 0, "anger": 2, "disgust": 2, "fear": 1,
    "joy": 3, "smirk": 3, "sadness": 1, "surprise": 3
  },
  "tapMotions": {
    "HitAreaHead": { "": 1 },
    "HitAreaBody": { "": 1 }
  }
}
```

---

## 5. 핵심 기술 스택 비교

### 5.1 렌더링 엔진 비교

| 항목 | AIRI | Geny | 호환성 |
|------|------|------|--------|
| **pixi.js 버전** | v6.5.10 (모듈 @pixi/*) | v7.4.3 (번들) | ⚠️ 주의 |
| **pixi-live2d-display** | v0.4.0 | v0.5.0-beta | ⚠️ 주의 |
| **Cubism SDK** | Cubism 4 Core | Cubism 4 Core | ✅ 호환 |
| **모델 포맷** | .model3.json, .moc3 | .model3.json, .moc3 | ✅ 동일 |
| **텍스처 포맷** | PNG (4096x4096) | PNG (4096x4096) | ✅ 동일 |
| **표정 포맷** | .exp3.json | .exp3.json | ✅ 동일 |
| **모션 포맷** | .motion3.json | .motion3.json | ✅ 동일 |
| **물리 연산** | .physics3.json | .physics3.json | ✅ 동일 |

### 5.2 pixi.js v6 → v7 주요 변경점

| 변경 영역 | v6 (AIRI) | v7 (Geny) | 영향도 |
|-----------|-----------|-----------|--------|
| 패키지 구조 | 모듈별 import | 통합 패키지 | 낮음 |
| Interaction | @pixi/interaction | EventSystem | **높음** |
| Ticker | TickerPlugin | 빌트인 | 중간 |
| Renderer | Renderer | WebGLRenderer / WebGPU | 중간 |
| Filter | pixi-filters v4 | @pixi/filter-* v7 | 중간 |

> **핵심**: pixi-live2d-display가 pixi.js 버전 차이를 내부적으로 추상화하므로, 직접적인 pixi.js API 호출 부분만 주의하면 된다. AIRI의 DropShadowFilter, Canvas 초기화 등은 Geny의 pixi.js v7에 맞게 조정이 필요하다.

### 5.3 프레임워크 비교

| 항목 | AIRI | Geny |
|------|------|------|
| **UI 프레임워크** | Vue 3 (Composition API) | React 19 (Hooks) |
| **상태관리** | Pinia 3.0.4 | Zustand 5.0.11 |
| **반응성 모델** | Vue Reactivity (ref, watch) | React useState, useEffect |
| **컴포넌트 라이프사이클** | onMounted, onUnmounted | useEffect cleanup |
| **의존성 주입** | Vue provide/inject | React Context |

### 5.4 아키텍처 패러다임 비교

```
AIRI: 클라이언트 주도 (Client-Driven)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Browser]
  ├── LLM 호출 → 감정 파싱 → 표정 적용
  ├── 오디오 처리 → 립싱크 → 파라미터 갱신
  ├── 모델 저장/로딩 (IndexedDB/OPFS)
  └── 모든 상태가 프론트엔드에 존재

Geny: 서버 주도 (Server-Driven)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[FastAPI Backend]
  ├── LLM 호출 → 감정 추출 → 상태 갱신
  ├── SSE 브로드캐스트 → 프론트엔드 반영
  └── 모델 레지스트리 관리

[Next.js Frontend]
  ├── SSE 구독 → 상태 수신 → 렌더링
  └── 오디오 재생 → 립싱크 (RMS)
```

### 5.5 기능 격차 분석

| 기능 | AIRI | Geny | 격차 |
|------|------|------|------|
| **기본 Live2D 렌더링** | ✅ | ✅ | 없음 |
| **표정 제어** | 고급 (Blend 모드, 다중 파라미터) | 기본 (인덱스 기반) | **큼** |
| **모션 시스템** | 플러그인 파이프라인 | 단순 그룹/인덱스 | **큼** |
| **립싱크** | wLipSync (ML 음소 감지) | RMS 진폭 | **큼** |
| **Beat Sync** | 물리 기반 스프링 | 미지원 | **매우 큼** |
| **Auto Blink** | 듀얼 모드 (absolute/multiply) | 미지원 (SDK 기본) | 중간 |
| **Eye Saccade** | 구현됨 | 미지원 | 중간 |
| **그림자 효과** | DropShadowFilter + 동적 색조 | 미지원 | 낮음 |
| **HiDPI 지원** | renderScale prop | 기본 | 낮음 |
| **FPS 제한** | maxFps prop | 미지원 | 낮음 |
| **모델 ZIP 로딩** | JSZip 기반 | 미지원 (서버 정적 파일) | 중간 |
| **크로스탭 동기화** | BroadcastChannel | 미지원 | 낮음 |
| **VRM 3D 모델** | Three.js + @pixiv/three-vrm | 미지원 | **매우 큼** |
| **Expression Tools (LLM)** | 구현됨 | 미지원 | 중간 |

---

## 6. 이식 가능성 분석

### 6.1 이식 가능성 판정 매트릭스

| 이식 대상 | 가능 여부 | 난이도 | 가치 | 우선순위 |
|-----------|-----------|--------|------|----------|
| **모델 파일 직접 사용** | ✅ 즉시 가능 | 낮음 | 높음 | P0 |
| **Expression Controller** | ✅ 가능 | 중간 | 높음 | P1 |
| **Motion Plugin Pipeline** | ✅ 가능 | 높음 | 높음 | P1 |
| **wLipSync 립싱크** | ✅ 가능 | 중간 | 매우 높음 | P0 |
| **Auto Blink 시스템** | ✅ 가능 | 낮음 | 중간 | P2 |
| **Eye Saccade** | ✅ 가능 | 낮음 | 중간 | P2 |
| **Beat Sync** | ✅ 가능 | 높음 | 중간 | P3 |
| **DropShadow 효과** | ✅ 가능 | 낮음 | 낮음 | P3 |
| **VRM 3D 지원** | ⚠️ 대규모 작업 | 매우 높음 | 높음 | P4 (별도) |
| **크로스탭 동기화** | ✅ 가능 | 낮음 | 낮음 | P4 |
| **모델 ZIP 로딩** | ✅ 가능 | 낮음 | 중간 | P3 |

### 6.2 "즉시 사용 가능" 영역

#### 6.2.1 모델 파일 호환성

AIRI와 Geny 모두 **Cubism 4 포맷**을 사용한다. AIRI의 모델 파일은 Geny에서 **즉시 사용 가능**하다:

```
AIRI 모델 구조:
{model_name}/
├── {name}.model3.json     ← Geny model_registry.json의 url 필드로 등록
├── {name}.moc3            ← 자동 참조
├── {name}.physics3.json   ← 자동 참조
├── expressions/           ← 자동 참조
│   └── *.exp3.json
├── motions/               ← 자동 참조
│   └── *.motion3.json
└── textures/              ← 자동 참조
    └── *.png
```

**이식 방법**: 
1. AIRI 모델 파일을 `Geny/backend/static/live2d-models/` 하위에 복사
2. `model_registry.json`에 메타데이터 추가
3. 즉시 동작

#### 6.2.2 Cubism Core SDK

동일한 `live2dcubismcore.min.js`를 사용. AIRI의 SDK 파일을 그대로 사용 가능.

### 6.3 "적응 필요" 영역

#### 6.3.1 Expression Controller 이식

**현재 Geny**: 인덱스 기반 (`live2dModel.expression(3)`)  
**AIRI**: 파라미터 레벨 블렌딩 (Add/Multiply/Overwrite)

**이식 방법**: AIRI의 `expression-controller.ts`와 `expression-store.ts`를 React 훅으로 변환
```
expression-controller.ts (Vue composable)
    → useExpressionController.ts (React hook)

expression-store.ts (Pinia)
    → useExpressionStore (Zustand slice 또는 독립 store)
```

**핵심 변환 포인트**:
- Vue `watch()` → React `useEffect()` 
- Pinia store → Zustand store
- Vue `ref()` / `computed()` → React `useState()` / `useMemo()`
- localStorage 접근은 동일하게 유지 가능

#### 6.3.2 wLipSync 이식

**현재 Geny**: RMS 진폭 → 단일 `ParamMouthOpenY`  
**AIRI**: wLipSync AudioWorklet → AEIOU 음소 → 가중치 기반 입 파라미터

**이식 방법**:
1. `wlipsync` npm 패키지를 Geny에 추가
2. AIRI의 `model-driver-lipsync` 패키지 로직을 Geny의 `audioManager.ts`에 통합
3. `LipSyncController` 클래스를 확장하여 vowel weight 기반 제어 추가

```typescript
// 현재 Geny (단순)
coreModel.setParameterValueById('ParamMouthOpenY', mouthOpen);

// 이식 후 (AIRI 방식)
const weights = lipSync.getVowelWeights();
coreModel.setParameterValueById('ParamMouthOpenY', weights.a);
coreModel.setParameterValueById('ParamMouthForm', weights.o * 0.5);
// 더 자연스러운 입 모양 표현
```

#### 6.3.3 Motion Plugin Pipeline

AIRI의 플러그인 파이프라인은 프레임워크 독립적 로직이므로 순수 TypeScript로 추출 가능:

```typescript
// 프레임워크 독립적 핵심 로직 (그대로 재사용)
interface MotionUpdatePlugin {
  stage: 'pre' | 'post' | 'final';
  update(model: InternalModel, deltaTime: number, handled: boolean): void;
}

// React 래퍼만 새로 작성
function useMotionManager(model: Live2DModel) {
  const plugins = useRef<MotionUpdatePlugin[]>([]);
  // ... plugin 등록/실행 로직
}
```

### 6.4 "대규모 작업 필요" 영역

#### 6.4.1 VRM 3D 모델 지원

Geny에 VRM 지원을 추가하려면 완전히 새로운 렌더링 파이프라인이 필요하다:

**필요 패키지**:
- three.js (이미 Geny에 포함, v0.183.1)
- @pixiv/three-vrm v3.5.1
- wlipsync (VRM용 립싱크)
- @react-three/fiber (이미 포함)

**필요 작업**:
1. VRM 모델 로더 컴포넌트 개발
2. VRM 전용 립싱크 (AEIOU blend shape)
3. VRM 전용 표정/감정 매핑
4. IBL / 포스트프로세싱 파이프라인
5. 기존 Live2D 시스템과 통합된 모델 선택 UI

> **판단**: VRM 지원은 별도 프로젝트로 분리하여 진행하는 것이 적절하다. 현재 이식 범위에서는 제외를 권고한다.

---

## 7. 이식 전략 및 작업 분류

### 7.1 전략: 점진적 이식 (Incremental Migration)

한번에 모든 것을 이식하지 않고, **가치 순서대로 점진적으로 이식**한다.

```
Phase 0: 모델 파일 즉시 이식 (0일)
    │
Phase 1: wLipSync + Expression Controller (핵심 품질 향상)
    │
Phase 2: Motion Plugin + Auto Blink + Eye Saccade
    │
Phase 3: Beat Sync + 시각 효과
    │
Phase 4: (선택) VRM 3D 지원
```

### 7.2 Phase 0 — 모델 파일 이식

**작업 내용**: AIRI의 Live2D 모델 파일을 Geny의 정적 파일 서버에 배치

**작업 목록**:
1. AIRI 프리셋 모델(Hiyori 등) 파일을 `Geny/backend/static/live2d-models/`에 복사
2. `model_registry.json`에 새 모델 엔트리 추가
3. 감정맵(emotionMap), 탭모션(tapMotions) 매핑 설정
4. 동작 확인

**파일 변경**: `model_registry.json` 수정만으로 완료

### 7.3 Phase 1 — 립싱크 & 표정 시스템 고도화

**7.3.1 wLipSync 통합**

```
변경 파일:
├── package.json                    # wlipsync 의존성 추가
├── src/lib/lipSync.ts              # LipSyncController 확장
├── src/lib/audioManager.ts         # AudioWorklet 노드 통합
└── public/worklet/                 # wLipSync worklet 파일
```

**핵심 변경**:
```typescript
// lipSync.ts 확장
import { createLive2DLipSync } from './wlipsync-adapter';

class LipSyncController {
  private wLipSync?: Live2DLipSync;
  
  async initAdvancedLipSync(audioContext: AudioContext) {
    this.wLipSync = await createLive2DLipSync(audioContext, profile, {
      cap: 0.7,
      volumeScale: 0.9,
      volumeExponent: 0.7,
    });
  }

  onFrame = () => {
    if (this.wLipSync && this.coreModel) {
      const mouthOpen = this.wLipSync.getMouthOpen();
      this.coreModel.setParameterValueById('ParamMouthOpenY', mouthOpen);
    }
  };
}
```

**7.3.2 Expression Controller 이식**

```
새 파일:
├── src/lib/live2d/expressionController.ts   # AIRI expression-controller 포팅
├── src/lib/live2d/expressionStore.ts        # Zustand store 또는 클래스
└── src/components/live2d/ExpressionPanel.tsx # (선택) 표정 제어 UI
```

**변환 패턴**:
```typescript
// AIRI (Vue/Pinia)
const store = useLive2dExpressionStore();
watch(() => store.entries, (entries) => {
  for (const entry of entries) {
    applyBlend(coreModel, entry);
  }
});

// Geny (React/Zustand)
const entries = useExpressionStore(s => s.entries);
useEffect(() => {
  for (const entry of entries) {
    applyBlend(coreModel, entry);
  }
}, [entries, coreModel]);
```

### 7.4 Phase 2 — 모션 파이프라인 & 생동감

**7.4.1 Motion Plugin Pipeline**

```
새 파일:
├── src/lib/live2d/motionManager.ts          # 플러그인 파이프라인 코어
├── src/lib/live2d/plugins/autoBlink.ts      # 자동 눈깜빡임
├── src/lib/live2d/plugins/idleFocus.ts      # 시선 미세 이동
├── src/lib/live2d/plugins/expression.ts     # 표정 플러그인
└── src/hooks/useMotionManager.ts            # React 훅 래퍼
```

**플러그인 인터페이스** (프레임워크 독립):
```typescript
interface MotionUpdatePlugin {
  stage: 'pre' | 'post' | 'final';
  enabled: boolean;
  update(
    coreModel: CubismModel,
    deltaTime: number,
    handled: boolean
  ): boolean;  // true = handled
}
```

> **핵심**: 플러그인 로직은 Vue/React에 의존하지 않으므로 AIRI의 코드를 **거의 그대로** 재사용 가능하다.

**7.4.2 Auto Blink**

AIRI의 듀얼 모드 Auto Blink를 `autoBlink.ts`로 포팅:
- State machine: idle → closing → opening
- 75ms close + 75ms open
- 3000~8000ms 랜덤 간격
- Expression 활성화 시 multiply-modulation

**7.4.3 Eye Saccade**

AIRI의 idle eye focus 로직 포팅:
- 랜덤 시선 이동 (EyeBallX, EyeBallY)
- 0.3 lerp factor 스무딩
- idle 모션 시에만 활성화

### 7.5 Phase 3 — 고급 시각 효과

**7.5.1 Beat Sync Controller**

가장 복잡한 이식 대상. 물리 기반 스프링 시뮬레이션을 포함.

```
새 파일:
├── src/lib/live2d/beatSync.ts               # 비트 감지 + 물리 시뮬레이션
├── src/lib/live2d/beatSyncStyles.ts         # 4가지 스타일 설정
└── src/hooks/useBeatSync.ts                 # React 훅 래퍼
```

**핵심 로직** (프레임워크 독립 — 재사용 가능):
```typescript
// 스프링 물리 시뮬레이션
const stiffness = 120, damping = 16, mass = 1;

function springUpdate(target: number, current: number, velocity: number, dt: number) {
  const force = stiffness * (target - current) - damping * velocity;
  const newVelocity = velocity + (force / mass) * dt;
  const newCurrent = current + newVelocity * dt;
  return { current: newCurrent, velocity: newVelocity };
}
```

**7.5.2 DropShadow 효과**

pixi.js v7 호환 DropShadow 필터 적용:
```typescript
import { DropShadowFilter } from '@pixi/filter-drop-shadow';
model.filters = [new DropShadowFilter({
  alpha: 0.2,
  blur: 0,
  distance: 20,
  rotation: 45,
  color: computedThemeColor,
})];
```

### 7.6 Phase 4 — (선택) VRM 3D 지원

별도 문서에서 상세 기획이 필요한 대규모 작업. 개략적 범위만 기술.

```
새 컴포넌트:
├── src/components/vrm/VRMCanvas.tsx         # Three.js + VRM 렌더링
├── src/components/vrm/VRMModel.tsx          # VRM 모델 로딩
├── src/lib/vrm/vrmLipSync.ts               # VRM 전용 립싱크
├── src/lib/vrm/vrmExpression.ts            # VRM blend shape 제어
└── src/lib/vrm/vrmAnimation.ts             # 애니메이션 시스템
```

**Geny 장점**: 이미 `@react-three/fiber`, `three.js`가 City 시각화에 사용 중이므로, VRM 렌더러 추가 시 번들 사이즈 부담이 적다.

---

## 8. 리스크 분석

### 8.1 기술적 리스크

| 리스크 | 가능성 | 영향도 | 완화 방안 |
|--------|--------|--------|-----------|
| **pixi.js v6/v7 API 비호환** | 중간 | 중간 | pixi-live2d-display가 대부분 추상화; 직접 API 호출부만 확인 |
| **pixi-live2d-display v0.4/v0.5 동작 차이** | 낮음 | 높음 | 버전 통일 또는 분기 처리; 0.5-beta가 0.4의 상위 호환 |
| **wLipSync AudioWorklet CORS** | 중간 | 중간 | worklet 파일을 same-origin으로 서빙; Next.js public/ 폴더 활용 |
| **Beat Sync 성능** | 낮음 | 중간 | 물리 시뮬레이션 경량, RAF 내에서 실행 |
| **React Strict Mode 더블 마운트** | 중간 | 중간 | Geny에 이미 generation counter 패턴 적용 중 |
| **모델별 파라미터 불일치** | 중간 | 높음 | 모델 레지스트리에 파라미터 매핑 필드 추가 |

### 8.2 아키텍처 리스크

| 리스크 | 가능성 | 영향도 | 완화 방안 |
|--------|--------|--------|-----------|
| **서버/클라이언트 상태 동기화 복잡도** | 높음 | 중간 | 표정/모션 제어를 프론트엔드에서 자율적으로 처리하되 SSE 트리거는 유지 |
| **Zustand/Pinia 상태 구조 차이** | 중간 | 낮음 | 인터페이스 기반 설계로 구현 교체 가능 |
| **기존 기능 회귀** | 중간 | 높음 | 페이즈별 이식으로 각 단계에서 검증 |

### 8.3 운영 리스크

| 리스크 | 가능성 | 영향도 | 완화 방안 |
|--------|--------|--------|-----------|
| **번들 사이즈 증가** | 높음 | 낮음 | wLipSync ~100KB, 기타 로직은 경량 |
| **메모리 사용량 증가** | 중간 | 중간 | Expression Store의 localStorage 사용량 모니터링 |
| **AIRI 업스트림 변경** | 높음 | 중간 | 특정 버전(v0.9.0-beta.7) 기준으로 이식; 이후 선택적 동기화 |

---

## 9. 단계별 구현 로드맵

### Phase 0: 모델 파일 이식 (즉시)

```
작업:
  1. AIRI 모델 파일을 Geny static 경로에 배치
  2. model_registry.json 에 모델 등록
  3. 기존 Live2DCanvas.tsx에서 로딩 확인

검증:
  - 새 모델이 캔버스에 표시되는가?
  - 기본 idle 모션이 재생되는가?
  - 표정(expression) 인덱스 전환이 동작하는가?
```

### Phase 1: 립싱크 & 표정 고도화

```
작업:
  1. wlipsync NPM 패키지 설치
  2. AudioWorklet 파일 배치 (public/worklet/)
  3. LipSyncController 클래스 확장 (wLipSync 모드 추가)
  4. AudioManager에 AudioWorklet 연결 파이프라인 추가
  5. ExpressionController 클래스 (AIRI expression-controller.ts 포팅)
  6. ExpressionStore (Zustand 기반)
  7. Live2DCanvas.tsx에 Expression 적용 로직 연동

검증:
  - TTS 재생 시 AEIOU 기반 립싱크가 동작하는가?
  - 다양한 언어 TTS에서 음소 감지가 정상인가?
  - Expression blend (Add/Multiply/Overwrite)가 기대대로 작동하는가?
  - 기존 감정 태그 시스템과 호환되는가?
```

### Phase 2: 모션 파이프라인 & 생동감

```
작업:
  1. MotionUpdatePlugin 인터페이스 정의
  2. 플러그인 파이프라인 코어 (pre → hooked → post → final)
  3. Auto Blink 플러그인 구현
  4. Eye Saccade 플러그인 구현
  5. Expression Plugin (Phase 1 ExpressionController 연동)
  6. Live2DCanvas.tsx ticker에 플러그인 파이프라인 연결
  7. useVTuberStore에 모션 플러그인 설정 상태 추가

검증:
  - 자동 눈깜빡임이 자연스러운가?
  - Idle 상태에서 시선 미세 이동이 동작하는가?
  - 표정 ↔ 눈깜빡임 간 multiply-modulation이 정상인가?
  - 기존 SSE 기반 감정/모션 제어와 충돌이 없는가?
```

### Phase 3: 고급 기능

```
작업:
  1. BeatSyncController 포팅 (스프링 물리 시뮬레이션)
  2. Beat Sync 스타일 4종 구현 (punchy-v, balanced-v, swing-lr, sway-sine)
  3. DropShadowFilter 적용 (pixi.js v7 호환)
  4. FPS 제한, HiDPI 렌더스케일 옵션 추가
  5. (선택) 모델 ZIP 로딩 지원

검증:
  - TTS 재생 시 머리가 비트에 맞춰 자연스럽게 흔들리는가?
  - BPM별 자동 스타일 전환이 동작하는가?
  - 그림자 효과가 렌더링 성능에 미치는 영향은?
```

### Phase 4: (선택) VRM 3D 지원

```
별도 기획 필요. 이 문서의 범위를 벗어남.
참고: Geny에 이미 Three.js 인프라가 있으므로 기술적으로 가능하나
      별도의 상세 분석이 필요함.
```

---

## 10. 결론 및 권고사항

### 10.1 핵심 결론

1. **이식 가능성: 확인됨** — AIRI의 Live2D 아바타를 Geny에서 서빙할 수 있다. 핵심 렌더링 인프라(Cubism 4 + pixi-live2d-display)가 동일하기 때문이다.

2. **모델 파일은 즉시 사용 가능** — .model3.json, .moc3, .exp3.json, .motion3.json 등 모든 모델 파일은 포맷 변환 없이 Geny에서 로딩된다.

3. **고급 기능 이식은 가치 있음** — AIRI의 wLipSync, Expression Controller, Motion Plugin Pipeline은 Geny의 아바타 품질을 크게 향상시킬 수 있다. 특히 wLipSync는 현재 Geny의 단순 RMS 방식 대비 **입 모양의 사실감을 획기적으로 개선**한다.

4. **플러그인 로직의 대부분은 프레임워크 독립적** — 물리 시뮬레이션, 립싱크 계산, 표정 블렌딩 등 핵심 로직은 Vue/React에 의존하지 않으므로 **거의 그대로 재사용**할 수 있다. React 래퍼만 새로 작성하면 된다.

5. **VRM 3D 지원은 별도 판단** — 가능하지만 대규모 작업이므로 별도 프로젝트로 분리를 권고한다.

### 10.2 권고 사항

1. **Phase 0 즉시 실행** — AIRI의 모델 파일을 Geny에 배치하고 동작을 확인한다. 리스크 제로, 즉시 가치 창출.

2. **Phase 1을 최우선 진행** — wLipSync와 Expression Controller는 **사용자 체감 품질을 가장 크게 높이는** 요소이다.

3. **pixi-live2d-display 버전 통일 검토** — AIRI(v0.4.0)와 Geny(v0.5.0-beta) 간 버전 차이를 확인하고, 가능하면 하나로 통일한다. v0.5.0-beta가 v0.4.0의 상위 호환이므로 Geny의 버전을 유지하는 것이 유리하다.

4. **프레임워크 독립 코어 라이브러리 분리** — 이식 과정에서 motionManager, expressionController, beatSync 등을 프레임워크 독립 `lib/live2d/` 모듈로 구성하면, 향후 유지보수와 AIRI 업스트림 동기화가 용이하다.

5. **백엔드 감정 시스템 확장** — AIRI의 9가지 감정(Happy, Sad, Angry, Think, Surprise, Awkward, Question, Curious, Neutral)을 Geny의 EmotionExtractor와 model_registry.json emotionMap에 반영한다.

---

## 부록 A: AIRI 주요 파일 참조

| 컴포넌트 | 파일 경로 |
|----------|-----------|
| Live2D Root | `airi/packages/stage-ui-live2d/src/components/scenes/Live2D.vue` |
| Live2D Model | `airi/packages/stage-ui-live2d/src/components/scenes/live2d/Model.vue` |
| Live2D Canvas | `airi/packages/stage-ui-live2d/src/components/scenes/live2d/Canvas.vue` |
| Motion Manager | `airi/packages/stage-ui-live2d/src/composables/live2d/motion-manager.ts` |
| Beat Sync | `airi/packages/stage-ui-live2d/src/composables/live2d/beat-sync.ts` |
| Expression Controller | `airi/packages/stage-ui-live2d/src/composables/live2d/expression-controller.ts` |
| Expression Store | `airi/packages/stage-ui-live2d/src/composables/live2d/expression-store.ts` |
| Emotions | `airi/packages/stage-ui-live2d/src/composables/live2d/emotions.ts` |
| Lip Sync Driver | `airi/packages/model-driver-lipsync/src/` |
| Display Models | `airi/packages/stage-ui/src/stores/display-models.ts` |
| Character Orchestrator | `airi/packages/stage-ui/src/stores/character/orchestrator/store.ts` |
| Audio Pipeline | `airi/packages/pipelines-audio/src/speech-pipeline.ts` |
| VRM Model | `airi/packages/stage-ui-three/src/components/Model/VRMModel.vue` |
| VRM Lip Sync | `airi/packages/stage-ui-three/src/composables/vrm/lip-sync.ts` |
| Live2D Store | `airi/packages/stage-ui-live2d/src/stores/live2d.ts` |

## 부록 B: Geny 주요 파일 참조

| 컴포넌트 | 파일 경로 |
|----------|-----------|
| Live2D Canvas | `Geny/frontend/src/components/live2d/Live2DCanvas.tsx` |
| Lip Sync | `Geny/frontend/src/lib/lipSync.ts` |
| Audio Manager | `Geny/frontend/src/lib/audioManager.ts` |
| VTuber Store | `Geny/frontend/src/store/useVTuberStore.ts` |
| Types | `Geny/frontend/src/types/index.ts` |
| Model Registry | `Geny/backend/static/live2d-models/model_registry.json` |
| Avatar State Manager | `Geny/backend/service/vtuber/avatar_state_manager.py` |
| Emotion Extractor | `Geny/backend/service/vtuber/emotion_extractor.py` |
| Model Manager | `Geny/backend/service/vtuber/live2d_model_manager.py` |
| VTuber Controller | `Geny/backend/controller/vtuber_controller.py` |

## 부록 C: 패키지 의존성 차이 요약

| 패키지 | AIRI | Geny | 비고 |
|--------|------|------|------|
| pixi.js | 6.5.10 (모듈) | 7.4.3 (번들) | 메이저 버전 차이 |
| pixi-live2d-display | 0.4.0 | 0.5.0-beta | 마이너 버전 차이 |
| three.js | 0.183.2 | 0.183.1 | 사실상 동일 |
| wlipsync | 1.3.0 | 미사용 | 신규 추가 필요 |
| animejs | 4.3.6 | 미사용 | 선택적 추가 |
| jszip | 3.10.1 | 미사용 | ZIP 로딩 시 필요 |
| Vue 3 | 3.5+ | 미사용 | 프레임워크 전환 |
| React | 미사용 | 19.2.3 | 대상 프레임워크 |
| Pinia | 3.0.4 | 미사용 | → Zustand 변환 |
| Zustand | 미사용 | 5.0.11 | 대상 상태관리 |
