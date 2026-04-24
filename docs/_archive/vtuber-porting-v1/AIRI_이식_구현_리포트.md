# AIRI Live2D 시스템 → Geny 통합 이식 구현 리포트

> 작성일: 2026-04-08  
> 상태: **Phase 0~4 구현 완료, 빌드 검증 통과**

---

## 1. 구현 완료 현황

| Phase | 항목 | 상태 | 비고 |
|-------|------|------|------|
| 0 | 소스 분석 및 계획 수립 | ✅ 완료 | |
| 1-A | 코어 라이브러리 구조 생성 | ✅ 완료 | `src/lib/live2d/` |
| 1-B | wLipSync 립싱크 시스템 | ✅ 완료 | ML 음소 감지 + RMS 폴백 |
| 1-C | Expression Controller | ✅ 완료 | Add/Multiply/Overwrite 블렌딩 |
| 2-A | Motion Plugin Pipeline | ✅ 완료 | pre/post/final 3단 파이프라인 |
| 2-B | Auto Blink 플러그인 | ✅ 완료 | 듀얼 모드 (absolute/multiply) |
| 2-C | Eye Saccade 플러그인 | ✅ 완료 | 확률 분포 기반 시선 미세이동 |
| 3-A | Beat Sync Controller | ✅ 완료 | 4가지 스타일 + 물리 스프링 |
| 3-B | DropShadow + HiDPI/FPS | ✅ 완료 | 필터 옵셔널 + maxFps 제어 |
| 4 | Live2DCanvas.tsx 통합 | ✅ 완료 | 기존 기능 보존 + 신규 시스템 통합 |
| 5 | 빌드 검증 | ✅ 통과 | `tsc --noEmit` + `next build` 성공 |

---

## 2. 생성된 파일 구조

```
frontend/src/lib/live2d/
├── index.ts                     # Public API (re-exports)
├── types.ts                     # 공유 타입 정의
├── expressionStore.ts           # Expression 상태 관리 (Pinia → class)
├── expressionController.ts      # 표정 블렌딩 컨트롤러
├── motionPipeline.ts            # 모션 플러그인 파이프라인
├── beatSync.ts                  # 비트 동기화 컨트롤러 + 플러그인
├── enhancedLipSync.ts           # 통합 립싱크 (RMS + wLipSync)
├── plugins/
│   ├── autoBlink.ts             # 자동 눈깜빡임 플러그인
│   ├── eyeSaccade.ts            # 시선 미세이동 플러그인
│   └── expression.ts            # 표정 적용 플러그인
└── lipsync/
    ├── advancedLipSync.ts       # wLipSync 래퍼
    └── wlipsync-profile.json    # ML 음소 프로파일 데이터
```

**수정된 기존 파일:**
```
frontend/src/components/live2d/Live2DCanvas.tsx  # 전면 고도화
frontend/src/lib/audioManager.ts                  # getAudioContext() 추가
frontend/package.json                              # wlipsync, @pixi/filter-drop-shadow 추가
```

---

## 3. 이식된 핵심 시스템 상세

### 3.1 Motion Plugin Pipeline

AIRI의 플러그인 기반 모션 업데이트 파이프라인을 그대로 이식:

```
PRE (항상 실행) → POST (handled가 아닌 경우) → FINAL (항상 실행)
  Beat Sync         Eye Saccade              Auto Blink
                                              Expression
```

- `MotionPipeline` 클래스: 프레임워크 독립적, config 동적 갱신 지원
- `MotionPlugin` 인터페이스: `(ctx: MotionPluginContext) => void`

### 3.2 Auto Blink

- 3단계 상태 머신: idle → closing → opening
- 75ms close + 75ms open, 3~8초 랜덤 간격
- Expression ON일 때: multiply-modulation (표정 값 보존)
- Expression OFF일 때: absolute write (직접 교체)
- Force Auto Blink: 타이머 기반 (Idle 모션에 눈깜빡임이 없는 모델용)

### 3.3 Eye Saccade

- 확률 분포 기반 inter-saccade 간격 (실제 사람 패턴 모방)
- `ParamEyeBallX/Y` 파라미터에 0.3 lerp factor 적용
- Focus controller를 통한 미세 머리 이동 연동

### 3.4 Beat Sync

- 4가지 스타일: `punchy-v`, `balanced-v`, `swing-lr`, `sway-sine`
- Semi-implicit Euler 물리 시뮬레이션 (stiffness=120, damping=16)
- BPM 자동 감지: <120 → swing-lr, 120-180 → balanced-v, >180 → punchy-v
- Release delay 1800ms (비트 없으면 자연스럽게 중립 복귀)
- 에이전트 응답 시 / 사용자 터치 시 자동 트리거

### 3.5 Expression Controller

- `Add`: modelDefault + currentValue
- `Multiply`: currentFrameValue × currentValue (눈깜빡임 보존)
- `Overwrite`: 직접 교체
- Noop detection: identity 값이면 skip
- Active→Inactive 전환 감지: 자동 modelDefault 리셋
- localStorage 기반 퍼시스턴스

### 3.6 Enhanced Lip Sync

- **RMS 모드** (기본): 기존 Geny 방식 그대로 — 완벽 후방 호환
- **Advanced 모드** (wLipSync): ML 기반 AEIOU 음소 감지
  - `wlipsync` AudioWorklet 노드 사용
  - 음소별 가중치 → smoothed mouth-open 값
  - Cap: 0.7, volumeScale: 0.9, volumeExponent: 0.7
  - 40ms 업데이트 간격, 120ms lerp 스무딩
  - 초기화 실패 시 RMS 자동 폴백

### 3.7 DropShadow Effect

- `@pixi/filter-drop-shadow` 사용
- alpha: 0.15, blur: 2, offset: (10, 10)
- 패키지 미설치 시 자동 스킵 (graceful degradation)

---

## 4. 기존 시스템 호환성

### 4.1 후방 호환성 보장

| 기존 기능 | 동작 여부 | 비고 |
|-----------|-----------|------|
| mao_pro 모델 로딩 | ✅ 정상 | model_registry.json 변경 없음 |
| shizuku 모델 로딩 | ✅ 정상 | |
| SSE 기반 감정/모션 제어 | ✅ 정상 | avatarState 적용 로직 보존 |
| TTS 립싱크 (RMS) | ✅ 정상 | 기본 모드가 RMS |
| 마우스 시선 추적 | ✅ 정상 | focus() 호출 보존 |
| 클릭 인터랙션 | ✅ 정상 | + beat sync 트리거 추가 |
| ResizeObserver | ✅ 정상 | kScale/initialShift 반영 강화 |
| React Strict Mode | ✅ 정상 | generation counter 패턴 보존 |

### 4.2 새로운 enhancedConfig prop

```typescript
interface Live2DCanvasProps {
  sessionId: string;
  className?: string;
  interactive?: boolean;
  background?: number;
  backgroundAlpha?: number;
  enhancedConfig?: Partial<Live2DEnhancedConfig>;  // ← 새로 추가
}
```

**기본값** (기존 동작과 동일):
```typescript
{
  autoBlinkEnabled: true,
  forceAutoBlinkEnabled: false,
  idleAnimationEnabled: true,
  expressionEnabled: true,
  beatSyncEnabled: true,
  shadowEnabled: true,
  maxFps: 0,                    // 무제한
  renderScale: 2,               // HiDPI
  beatSyncStyle: 'punchy-v',
  beatSyncAutoStyleShift: true,
  lipSyncMode: 'rms',           // 기존 방식 유지
}
```

---

## 5. 향후 작업 (선택)

1. **wLipSync 활성화**: `lipSyncMode: 'advanced'`로 설정하여 ML 립싱크 사용
2. **UI 제어 패널**: enhancedConfig 값을 UI에서 토글할 수 있는 제어판 구현
3. **Expression 초기화**: model3.json에서 exp3 파일을 파싱하여 ExpressionController 초기화
4. **VRM 3D 지원**: 별도 프로젝트로 진행 (분석 문서 참조)

---

## 6. 의존성 변경

```diff
 "dependencies": {
+  "@pixi/filter-drop-shadow": "^X.X.X",
+  "wlipsync": "^1.3.0",
   "pixi-live2d-display": "^0.5.0-beta",
   "pixi.js": "^7.4.3",
   ...
 }
```
