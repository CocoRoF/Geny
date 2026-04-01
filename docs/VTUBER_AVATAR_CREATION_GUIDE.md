# VTuber 아바타 제작 완벽 가이드

> **목적**: 새로운 작업자가 Live2D 아바타를 처음부터 제작하고, 표정·모션·복장을 설정하여 Geny VTuber 시스템에 완전히 통합할 수 있도록 하는 종합 매뉴얼
>
> **최종 수정**: 2026-04-01

---

## 목차

1. [시스템 아키텍처 개요](#1-시스템-아키텍처-개요)
2. [필요 도구 및 환경](#2-필요-도구-및-환경)
3. [Live2D 모델 파일 구조](#3-live2d-모델-파일-구조)
4. [새 아바타 제작 단계별 가이드](#4-새-아바타-제작-단계별-가이드)
5. [표정(Expression) 시스템 상세](#5-표정expression-시스템-상세)
6. [모션(Motion) 시스템 상세](#6-모션motion-시스템-상세)
7. [물리(Physics) 시스템](#7-물리physics-시스템)
8. [포즈(Pose) 시스템 — 복장/의상 교체](#8-포즈pose-시스템--복장의상-교체)
9. [model_registry.json 등록](#9-model_registryjson-등록)
10. [캐릭터 성격 프롬프트 작성](#10-캐릭터-성격-프롬프트-작성)
11. [감정(Emotion) 매핑 시스템](#11-감정emotion-매핑-시스템)
12. [프론트엔드 렌더링 파이프라인](#12-프론트엔드-렌더링-파이프라인)
13. [백엔드 데이터 흐름](#13-백엔드-데이터-흐름)
14. [체크리스트: 새 아바타 등록 전 확인사항](#14-체크리스트-새-아바타-등록-전-확인사항)
15. [트러블슈팅](#15-트러블슈팅)
16. [참고 자료](#16-참고-자료)

---

## 1. 시스템 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────┐
│                     Geny VTuber 시스템                       │
│                                                             │
│  ┌──────────┐    SSE     ┌──────────┐    Pixi.js    ┌────┐ │
│  │ Backend  │ ─────────> │ Frontend │ ──────────>  │캔버스│ │
│  │ (FastAPI)│            │ (Next.js)│    + Cubism   │렌더 │ │
│  └────┬─────┘            └────┬─────┘      SDK      └────┘ │
│       │                       │                             │
│  ┌────┴─────┐           ┌────┴──────┐                      │
│  │ Service  │           │ Zustand   │                      │
│  │ Layer    │           │ Store     │                      │
│  │          │           │           │                      │
│  │ • Model  │           │ • models  │                      │
│  │   Manager│           │ • states  │                      │
│  │ • Avatar │           │ • SSE sub │                      │
│  │   State  │           └───────────┘                      │
│  │ • Emotion│                                              │
│  │   Extract│                                              │
│  └──────────┘                                              │
│                                                             │
│  Static Assets:                                             │
│  backend/static/live2d-models/{model_name}/runtime/        │
│    ├── {name}.model3.json  (진입점)                         │
│    ├── {name}.moc3          (바이너리 모델)                  │
│    ├── {name}.physics3.json (물리 시뮬레이션)                │
│    ├── {name}.pose3.json    (포즈/의상)                     │
│    ├── {name}.cdi3.json     (파라미터 메타정보)              │
│    ├── {name}.{resolution}/ (텍스처)                        │
│    ├── expressions/         (표정 파일들)                    │
│    └── motions/             (모션 파일들)                    │
└─────────────────────────────────────────────────────────────┘
```

### 핵심 데이터 흐름

```
LLM 응답 생성 → [joy] 태그 감지 → EmotionExtractor → AvatarState 업데이트
    → SSE 푸시 → Frontend Store 업데이트 → Live2DCanvas 표정/모션 적용
```

---

## 2. 필요 도구 및 환경

### 2.1 Live2D 모델 제작 도구

| 도구 | 용도 | 필수 여부 |
|------|------|----------|
| **Live2D Cubism Editor** | 모델 제작, 메시 편집, 디포머 설정, 표정/모션 생성 | ✅ 필수 |
| **Adobe Photoshop / Clip Studio Paint** | 원화 일러스트 (PSD 레이어 분리) | ✅ 필수 |
| **Live2D Cubism Viewer** | 모델 미리보기, 테스트 | 권장 |

### 2.2 출력 파일 형식

Cubism Editor에서 **Runtime용 내보내기**를 해야 합니다:

- `File → Export for Runtime → Export as moc3 file`
- 이 과정에서 아래 파일들이 자동 생성됩니다

### 2.3 Geny 시스템 요구사항

- **Cubism SDK 버전**: Cubism 4 (Cubism 3 이상 호환)
- **프론트엔드 렌더러**: `pixi-live2d-display/cubism4` + Pixi.js
- **SDK 런타임**: `live2dcubismcore.min.js` (프론트엔드 `/lib/live2d/` 에 위치)

---

## 3. Live2D 모델 파일 구조

### 3.1 전체 디렉터리 구조

새로운 모델 `my_avatar`를 만든다면 다음과 같은 구조가 필요합니다:

```
backend/static/live2d-models/
├── model_registry.json          ← 전체 모델 레지스트리 (여기에 등록)
│
└── my_avatar/                   ← 모델 루트 폴더
    ├── ReadMe.txt               ← (선택) 모델 라이선스/출처 정보
    └── runtime/                 ← 런타임 리소스 (Cubism Editor에서 내보내기)
        ├── my_avatar.model3.json    ← ★ 진입점 (모든 파일 참조)
        ├── my_avatar.moc3           ← ★ 바이너리 모델 데이터
        ├── my_avatar.physics3.json  ← 물리 시뮬레이션 설정
        ├── my_avatar.pose3.json     ← 포즈 그룹 (의상 전환용)
        ├── my_avatar.cdi3.json      ← 파라미터 표시 정보
        │
        ├── my_avatar.4096/          ← 텍스처 폴더 (해상도별)
        │   ├── texture_00.png       ← 메인 텍스처 아틀라스
        │   └── texture_01.png       ← (필요시 추가 텍스처)
        │
        ├── expressions/             ← 표정 파일들
        │   ├── exp_01.exp3.json     ← neutral (기본)
        │   ├── exp_02.exp3.json     ← sadness
        │   ├── exp_03.exp3.json     ← anger
        │   ├── exp_04.exp3.json     ← joy
        │   ├── exp_05.exp3.json     ← surprise
        │   ├── exp_06.exp3.json     ← fear
        │   ├── exp_07.exp3.json     ← disgust
        │   └── exp_08.exp3.json     ← smirk (또는 커스텀)
        │
        └── motions/                 ← 모션 파일들
            ├── mtn_01.motion3.json  ← Idle (대기 루프)
            ├── mtn_02.motion3.json  ← TapBody (터치 반응)
            ├── mtn_03.motion3.json  ← TapHead (머리 터치)
            └── special_01.motion3.json ← (특수 모션)
```

### 3.2 각 파일 역할 상세

#### 3.2.1 `*.model3.json` — 모델 진입점 (★ 가장 중요)

모든 리소스 파일의 경로를 정의하는 메타 파일입니다. 프론트엔드가 이 파일 하나만 로드하면 나머지는 자동으로 따라옵니다.

**실제 예시** (`mao_pro.model3.json`):

```json
{
  "Version": 3,
  "FileReferences": {
    "Moc": "mao_pro.moc3",
    "Textures": [
      "mao_pro.4096/texture_00.png"
    ],
    "Physics": "mao_pro.physics3.json",
    "Pose": "mao_pro.pose3.json",
    "DisplayInfo": "mao_pro.cdi3.json",
    "Expressions": [
      { "Name": "exp_01", "File": "expressions/exp_01.exp3.json" },
      { "Name": "exp_02", "File": "expressions/exp_02.exp3.json" },
      { "Name": "exp_03", "File": "expressions/exp_03.exp3.json" },
      { "Name": "exp_04", "File": "expressions/exp_04.exp3.json" },
      { "Name": "exp_05", "File": "expressions/exp_05.exp3.json" },
      { "Name": "exp_06", "File": "expressions/exp_06.exp3.json" },
      { "Name": "exp_07", "File": "expressions/exp_07.exp3.json" },
      { "Name": "exp_08", "File": "expressions/exp_08.exp3.json" }
    ],
    "Motions": {
      "Idle": [
        { "File": "motions/mtn_01.motion3.json" }
      ],
      "": [
        { "File": "motions/mtn_02.motion3.json" },
        { "File": "motions/mtn_03.motion3.json" },
        { "File": "motions/mtn_04.motion3.json" },
        { "File": "motions/special_01.motion3.json" },
        { "File": "motions/special_02.motion3.json" },
        { "File": "motions/special_03.motion3.json" }
      ]
    }
  },
  "Groups": [
    {
      "Target": "Parameter",
      "Name": "EyeBlink",
      "Ids": ["ParamEyeLOpen", "ParamEyeROpen"]
    },
    {
      "Target": "Parameter",
      "Name": "LipSync",
      "Ids": ["ParamA"]
    }
  ],
  "HitAreas": [
    { "Id": "HitAreaHead", "Name": "" },
    { "Id": "HitAreaBody", "Name": "" }
  ]
}
```

**핵심 필드 설명**:

| 필드 | 설명 |
|------|------|
| `Moc` | `.moc3` 바이너리 모델 파일 경로 |
| `Textures` | 텍스처 이미지 배열 (PNG). 해상도별 폴더 사용 |
| `Physics` | 물리 시뮬레이션 설정 파일 |
| `Pose` | 포즈/의상 전환 그룹 정의 |
| `DisplayInfo` | 파라미터 이름·그룹 매핑 (`.cdi3.json`) |
| `Expressions` | 표정 파일 배열. **순서(인덱스)가 중요!** |
| `Motions` | 모션 그룹별 파일 배열 |
| `Groups.EyeBlink` | 자동 눈 깜빡임에 사용할 파라미터 ID |
| `Groups.LipSync` | 립싱크에 사용할 파라미터 ID |
| `HitAreas` | 터치 영역 정의 (머리, 몸통 등) |

> ⚠️ **중요**: `Expressions` 배열의 **인덱스**가 `model_registry.json`의 `emotionMap`과 일치해야 합니다!

#### 3.2.2 `*.moc3` — 바이너리 모델

- Cubism Editor에서 자동 생성되는 바이너리 파일
- 모든 메시(Mesh), 디포머(Deformer), 파라미터(Parameter) 포함
- **직접 편집 불가** — 반드시 Cubism Editor에서 재내보내기

#### 3.2.3 텍스처 파일 (`*.png`)

- PSD 레이어들을 텍스처 아틀라스로 패킹한 결과물
- 해상도 옵션: `1024`, `2048`, `4096` (폴더명으로 구분)
- 고해상도일수록 디테일↑, 파일 크기↑, 로딩 시간↑

| 해상도 | 권장 용도 | 파일 크기 (대략) |
|--------|----------|-----------------|
| `1024` | 미니 아바타, 썸네일 | ~1-2 MB |
| `2048` | 일반 VTuber 패널 | ~3-5 MB |
| `4096` | 고품질 풀스크린 | ~8-15 MB |

---

## 4. 새 아바타 제작 단계별 가이드

### Phase 1: 원화 제작 (PSD)

1. **레이어 분리 규칙**:
   - 각 움직이는 파츠를 **별도 레이어**로 분리
   - 레이어 이름을 명확하게 지정 (영문/일문 권장)

2. **필수 분리 파츠**:

```
📁 PSD 레이어 구조 (권장)
├── 📁 Face (얼굴)
│   ├── 📁 Eyes (눈)
│   │   ├── Eye_L_Open      ← 왼쪽 눈 열림
│   │   ├── Eye_L_Close     ← 왼쪽 눈 감김
│   │   ├── Eye_L_Smile     ← 왼쪽 눈 웃음
│   │   ├── Eye_R_Open      ← 오른쪽 눈 열림
│   │   ├── Eye_R_Close     ← 오른쪽 눈 감김
│   │   ├── Eye_R_Smile     ← 오른쪽 눈 웃음
│   │   ├── Eyeball_L       ← 왼쪽 눈동자
│   │   ├── Eyeball_R       ← 오른쪽 눈동자
│   │   ├── EyeHighlight_L  ← 눈 하이라이트
│   │   └── EyeHighlight_R
│   │
│   ├── 📁 Eyebrows (눈썹)
│   │   ├── Brow_L          ← 왼쪽 눈썹
│   │   └── Brow_R          ← 오른쪽 눈썹
│   │
│   ├── 📁 Mouth (입)
│   │   ├── Mouth_Default   ← 기본 입 모양
│   │   ├── Mouth_Open      ← 입 벌림 (A, I, U, E, O)
│   │   ├── Mouth_Smile     ← 미소
│   │   ├── Mouth_Angry     ← 화난 입
│   │   └── Mouth_Sad       ← 슬픈 입
│   │
│   ├── Nose               ← 코
│   ├── Cheek_Blush        ← 볼 빨간색 (홍조)
│   └── Face_Outline       ← 얼굴 윤곽
│
├── 📁 Hair (머리카락)
│   ├── Hair_Front         ← 앞머리
│   ├── Hair_Side_L        ← 옆머리 (좌)
│   ├── Hair_Side_R        ← 옆머리 (우)
│   ├── Hair_Back          ← 뒷머리
│   └── Hair_Accessory     ← 머리 액세서리
│
├── 📁 Body (몸)
│   ├── Body_Upper         ← 상체
│   ├── Body_Lower         ← 하체 (보이는 경우)
│   ├── 📁 Arms
│   │   ├── Arm_L_A        ← 왼팔 포즈 A
│   │   ├── Arm_L_B        ← 왼팔 포즈 B (의상 교체용)
│   │   ├── Arm_R_A        ← 오른팔 포즈 A
│   │   └── Arm_R_B        ← 오른팔 포즈 B
│   └── Hand_L / Hand_R   ← 손
│
├── 📁 Clothes (의상)
│   ├── Outfit_A           ← 의상 세트 A (기본)
│   └── Outfit_B           ← 의상 세트 B (교체용)
│
└── Background             ← (선택) 배경
```

### Phase 2: Cubism Editor에서 모델링

1. **PSD 가져오기**: `File → New Model From PSD`
2. **메시(Mesh) 편집**: 각 파츠에 변형 가능한 메시 생성
3. **디포머(Deformer) 설정**: 워프 디포머 + 회전 디포머로 움직임 구조 구축
4. **파라미터(Parameter) 연결**: 각 디포머를 파라미터에 바인딩

### Phase 3: 파라미터 설정

Cubism Editor에서 사용하는 **표준 파라미터 ID**:

```
┌─────────────────────────────────────────────────────────────────────┐
│ 파라미터 그룹     │ ID                  │ 이름            │ 범위     │
├─────────────────────────────────────────────────────────────────────┤
│ 얼굴 방향        │ ParamAngleX         │ 얼굴 X축 회전   │ -30~30  │
│                  │ ParamAngleY         │ 얼굴 Y축 회전   │ -30~30  │
│                  │ ParamAngleZ         │ 얼굴 Z축 회전   │ -30~30  │
│                  │ ParamCheek          │ 홍조 (볼)       │ 0~1     │
├─────────────────────────────────────────────────────────────────────┤
│ 눈              │ ParamEyeLOpen       │ 왼눈 열림       │ 0~1     │
│                  │ ParamEyeROpen       │ 오른눈 열림     │ 0~1     │
│                  │ ParamEyeLSmile      │ 왼눈 웃음       │ 0~1     │
│                  │ ParamEyeRSmile      │ 오른눈 웃음     │ 0~1     │
│                  │ ParamEyeLForm       │ 왼눈 변형       │ -1~1    │
│                  │ ParamEyeRForm       │ 오른눈 변형     │ -1~1    │
├─────────────────────────────────────────────────────────────────────┤
│ 눈동자           │ ParamEyeBallX       │ 눈동자 X        │ -1~1    │
│                  │ ParamEyeBallY       │ 눈동자 Y        │ -1~1    │
│                  │ ParamEyeBallForm    │ 눈동자 축소     │ 0~1     │
│                  │ ParamEyeEffect      │ 눈 이펙트       │ 0~1     │
├─────────────────────────────────────────────────────────────────────┤
│ 눈썹             │ ParamBrowLY         │ 왼눈썹 Y        │ -1~1    │
│                  │ ParamBrowRY         │ 오른눈썹 Y      │ -1~1    │
│                  │ ParamBrowLX         │ 왼눈썹 X        │ -1~1    │
│                  │ ParamBrowRX         │ 오른눈썹 X      │ -1~1    │
│                  │ ParamBrowLAngle     │ 왼눈썹 각도     │ -1~1    │
│                  │ ParamBrowRAngle     │ 오른눈썹 각도   │ -1~1    │
│                  │ ParamBrowLForm      │ 왼눈썹 변형     │ -1~1    │
│                  │ ParamBrowRForm      │ 오른눈썹 변형   │ -1~1    │
├─────────────────────────────────────────────────────────────────────┤
│ 입               │ ParamA              │ 입 모양 "아"    │ 0~1     │
│                  │ ParamI              │ 입 모양 "이"    │ 0~1     │
│                  │ ParamU              │ 입 모양 "우"    │ 0~1     │
│                  │ ParamE              │ 입 모양 "에"    │ 0~1     │
│                  │ ParamO              │ 입 모양 "오"    │ 0~1     │
│                  │ ParamMouthUp        │ 입꼬리 올림     │ 0~1     │
│                  │ ParamMouthDown      │ 입꼬리 내림     │ 0~1     │
│                  │ ParamMouthAngry     │ 삐죽 입         │ 0~1     │
│                  │ ParamMouthAngryLine │ 삐죽 입 라인    │ 0~1     │
├─────────────────────────────────────────────────────────────────────┤
│ 몸              │ ParamBodyAngleX     │ 몸 X축 회전     │ -10~10  │
│                  │ ParamBodyAngleY     │ 몸 Y축 회전     │ -10~10  │
│                  │ ParamBodyAngleZ     │ 몸 Z축 회전     │ -10~10  │
│                  │ ParamBreath         │ 호흡             │ 0~1     │
├─────────────────────────────────────────────────────────────────────┤
│ 팔 (포즈 A)     │ ParamArmLA01        │ 왼팔A 어깨      │ -1~1    │
│                  │ ParamArmLA02        │ 왼팔A 팔꿈치    │ -1~1    │
│                  │ ParamArmLA03        │ 왼팔A 손목      │ -1~1    │
│                  │ ParamHandLA         │ 왼손A            │ -1~1    │
│                  │ ParamArmRA01        │ 오른팔A 어깨    │ -1~1    │
│                  │ ParamArmRA02        │ 오른팔A 팔꿈치  │ -1~1    │
│                  │ ParamArmRA03        │ 오른팔A 손목    │ -1~1    │
│                  │ ParamHandRA         │ 오른손A          │ -1~1    │
└─────────────────────────────────────────────────────────────────────┘
```

> 💡 **참고**: 이 파라미터 ID들은 Cubism Editor의 표준 규격입니다. 모델마다 커스텀 파라미터를 추가할 수 있지만, 위 표준 ID를 사용하면 자동 눈 깜빡임, 립싱크 등이 자동으로 작동합니다.

### Phase 4: Runtime 내보내기

Cubism Editor에서:

1. `File → Export for Runtime → Export as moc3 file`
2. 설정:
   - **Texture Size**: `4096` 권장 (고품질), `2048` (일반)
   - **Export Expressions**: ✅ 체크
   - **Export Motions**: ✅ 체크
   - **Export Physics**: ✅ 체크
3. 내보내기 결과물을 `backend/static/live2d-models/{name}/runtime/` 에 배치

---

## 5. 표정(Expression) 시스템 상세

### 5.1 표정 파일 구조 (`.exp3.json`)

표정 파일은 모델의 파라미터 값을 **오버라이드**하여 특정 감정을 표현합니다.

```json
{
  "Type": "Live2D Expression",
  "FadeInTime": 0.5,
  "FadeOutTime": 0.5,
  "Parameters": [
    {
      "Id": "ParamEyeLOpen",
      "Value": 1.2,
      "Blend": "Multiply"
    },
    {
      "Id": "ParamEyeLSmile",
      "Value": 1,
      "Blend": "Add"
    },
    {
      "Id": "ParamMouthUp",
      "Value": 0.8,
      "Blend": "Add"
    }
  ]
}
```

**필드 설명**:

| 필드 | 설명 |
|------|------|
| `FadeInTime` | 표정 전환 시 페이드-인 시간 (초) |
| `FadeOutTime` | 다른 표정으로 전환 시 페이드-아웃 시간 (초) |
| `Parameters[].Id` | 조작할 파라미터 ID |
| `Parameters[].Value` | 적용할 값 |
| `Parameters[].Blend` | 블렌딩 방식: `Add` / `Multiply` / `Overwrite` |

### 5.2 블렌딩 모드 상세

| 모드 | 수식 | 용도 |
|------|------|------|
| **Add** | `기본값 + Value` | 눈썹 위치, 입꼬리 등 이동 |
| **Multiply** | `기본값 × Value` | 눈 열림 정도 (0=감김, 1=유지, 1.2=더 크게) |
| **Overwrite** | `Value` 로 덮어쓰기 | 강제로 특정 값 설정 |

### 5.3 Geny 시스템 표준 표정 8종

아래는 Geny에서 사용하는 **표준 감정 8종**입니다. **인덱스 순서가 매우 중요**합니다:

| 인덱스 | 파일명 | 감정 | 핵심 파라미터 변경 |
|--------|--------|------|-------------------|
| **0** | `exp_01.exp3.json` | **neutral** (기본) | 모든 파라미터 기본값 (0) |
| **1** | `exp_02.exp3.json` | **sadness / fear** | 눈 감김 (`EyeOpen=0×Multiply`), 눈 웃음 (`EyeSmile=1`), 입꼬리 하강 |
| **2** | `exp_03.exp3.json` | **anger / disgust** | 눈 감김 (`EyeOpen=0×Multiply`), 눈 웃음 없음, 눈썹 내림, 입 삐죽 |
| **3** | `exp_04.exp3.json` | **joy / surprise** | 눈 크게 (`EyeOpen=1.2×Multiply`), 눈 웃음 (`EyeSmile=1`), 눈 이펙트 ON, 입꼬리 상승 |
| **4** | `exp_05.exp3.json` | **(커스텀)** | 모델에 따라 다름 |
| **5** | `exp_06.exp3.json` | **(커스텀)** | 모델에 따라 다름 |
| **6** | `exp_07.exp3.json` | **(커스텀)** | 모델에 따라 다름 |
| **7** | `exp_08.exp3.json` | **(커스텀)** | 모델에 따라 다름 |

### 5.4 표정별 파라미터 비교표 (mao_pro 기준)

```
파라미터              │ exp_01     │ exp_02     │ exp_03     │ exp_04
                     │ (neutral)  │ (sadness)  │ (anger)    │ (joy)
─────────────────────┼────────────┼────────────┼────────────┼───────────
ParamEyeLOpen        │ 1 (Mult)   │ 0 (Mult)   │ 0 (Mult)   │ 1.2 (Mult)
ParamEyeLSmile       │ 0 (Add)    │ 1 (Add)    │ 0 (Add)    │ 1 (Add)
ParamEyeROpen        │ 1 (Mult)   │ 0 (Mult)   │ 0 (Mult)   │ 1.2 (Mult)
ParamEyeRSmile       │ 0 (Add)    │ 1 (Add)    │ 0 (Add)    │ 1 (Add)
ParamEyeEffect       │ 0 (Add)    │ 0 (Add)    │ 0 (Add)    │ 1 (Add)
ParamCheek           │ 0 (Add)    │ 0 (Add)    │ 0 (Add)    │ 0 (Add)
ParamMouthUp         │ 0 (Add)    │ – (기본)    │ – (기본)    │ – (기본)
ParamMouthAngry      │ 0 (Add)    │ 0 (Add)    │ – (기본)    │ 0 (Add)
```

**핵심 패턴**:
- **눈을 감기려면**: `ParamEyeLOpen`을 `0`으로 `Multiply`
- **눈을 크게 뜨려면**: `ParamEyeLOpen`을 `1.2` 이상으로 `Multiply`
- **웃는 눈을 만들려면**: `ParamEyeSmile`을 `1`로 `Add`
- **반짝이 이펙트**: `ParamEyeEffect`를 `1`로 `Add`
- **입꼬리 올림**: `ParamMouthUp`을 양수로 `Add`
- **입꼬리 내림**: `ParamMouthDown`을 양수로 `Add`
- **홍조 추가**: `ParamCheek`을 `1`로 `Add`

### 5.5 새 표정 만들기 (수동 JSON 편집)

Cubism Editor를 사용하지 않고 `.exp3.json`을 수동으로 작성할 수도 있습니다:

**예시: "당황" 표정 만들기** (`exp_05.exp3.json`):

```json
{
  "Type": "Live2D Expression",
  "FadeInTime": 0.3,
  "FadeOutTime": 0.5,
  "Parameters": [
    { "Id": "ParamEyeLOpen", "Value": 1.3, "Blend": "Multiply" },
    { "Id": "ParamEyeROpen", "Value": 1.3, "Blend": "Multiply" },
    { "Id": "ParamEyeLSmile", "Value": 0, "Blend": "Add" },
    { "Id": "ParamEyeRSmile", "Value": 0, "Blend": "Add" },
    { "Id": "ParamEyeBallForm", "Value": 0.5, "Blend": "Add" },
    { "Id": "ParamBrowLY", "Value": 0.5, "Blend": "Add" },
    { "Id": "ParamBrowRY", "Value": 0.5, "Blend": "Add" },
    { "Id": "ParamCheek", "Value": 1, "Blend": "Add" },
    { "Id": "ParamA", "Value": 0.3, "Blend": "Add" },
    { "Id": "ParamMouthUp", "Value": 0, "Blend": "Add" }
  ]
}
```

> 💡 **팁**: `FadeInTime`을 짧게 하면 (0.1~0.3초) 놀람 같은 순간적 표정에 적합하고, 길게 하면 (0.5~1.0초) 서서히 변하는 감정에 적합합니다.

### 5.6 표정을 model3.json에 등록

새 표정 파일을 만든 후 `model3.json`의 `Expressions` 배열에 추가:

```json
"Expressions": [
  { "Name": "exp_01", "File": "expressions/exp_01.exp3.json" },
  ...
  { "Name": "exp_09_embarrassed", "File": "expressions/exp_09.exp3.json" }
]
```

> ⚠️ **인덱스와 emotionMap을 반드시 동기화하세요!** 새 표정을 인덱스 8에 추가했다면, `model_registry.json`의 `emotionMap`에도 `"embarrassed": 8`을 추가해야 합니다.

---

## 6. 모션(Motion) 시스템 상세

### 6.1 모션 파일 구조 (`.motion3.json`)

모션은 시간 기반 **키프레임 애니메이션**입니다:

```json
{
  "Version": 3,
  "Meta": {
    "Duration": 4.0,
    "Fps": 30,
    "Loop": true,
    "CurveCount": 12,
    "TotalSegmentCount": 48,
    "TotalPointCount": 92,
    "UserDataCount": 0
  },
  "Curves": [
    {
      "Target": "Parameter",
      "Id": "ParamAngleX",
      "Segments": [0, 0, 1, 0.5, 5, 1, 1, 10, 0, ...]
    },
    {
      "Target": "Parameter",
      "Id": "ParamEyeLOpen",
      "Segments": [0, 1, 0, 1, 0, 2.5, 0, 0, 2.6, 1, 0, 4, 1]
    }
  ]
}
```

**핵심 필드**:

| 필드 | 설명 |
|------|------|
| `Meta.Duration` | 모션 총 길이 (초) |
| `Meta.Fps` | 프레임 레이트 (보통 30) |
| `Meta.Loop` | `true` = 반복 재생 (Idle용), `false` = 1회 재생 (반응용) |
| `Curves[].Target` | `"Parameter"` 또는 `"PartOpacity"` |
| `Curves[].Id` | 대상 파라미터 ID |
| `Curves[].Segments` | 키프레임 데이터 (시간, 값, 보간 타입 등) |

### 6.2 모션 그룹 (Motion Groups)

`model3.json`의 `Motions` 섹션에서 **그룹별**로 모션을 정의:

```json
"Motions": {
  "Idle": [
    { "File": "motions/idle_01.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5 }
  ],
  "TapHead": [
    { "File": "motions/tap_head_01.motion3.json" },
    { "File": "motions/tap_head_02.motion3.json" }
  ],
  "TapBody": [
    { "File": "motions/tap_body_01.motion3.json" }
  ],
  "Happy": [
    { "File": "motions/happy_01.motion3.json" }
  ],
  "Sad": [
    { "File": "motions/sad_01.motion3.json" }
  ]
}
```

**그룹 이름 규칙**:

| 그룹 이름 | 용도 | 재생 방식 |
|-----------|------|----------|
| `Idle` | 대기 상태 루프 | 무한 루프 (`Loop: true`) |
| `TapHead` | 머리 터치 반응 | 1회 재생 |
| `TapBody` | 몸 터치 반응 | 1회 재생 |
| `Happy` / `Sad` / ... | 감정별 커스텀 모션 | 1회 재생 후 Idle 복귀 |

### 6.3 Geny에서의 모션 트리거

**프론트엔드** (`Live2DCanvas.tsx`):

```typescript
// Idle 모션 시작 (초기화 시)
await live2dModel.motion(model.idleMotionGroupName || 'Idle');

// 감정 변화 시 모션 적용 (SSE 수신)
if (avatarState.trigger !== 'system') {
  live2dModel.motion(avatarState.motion_group, avatarState.motion_index);
}
```

**백엔드** — 감정 → 모션 자동 매핑:

```python
# AvatarStateManager._DEFAULT_EMOTION_MOTION
{
    "joy": "TapBody",
    "surprise": "TapBody",
    "anger": "TapBody",
    "sadness": "Idle",
    "fear": "Idle",
    "disgust": "Idle",
    "neutral": "Idle",
}
```

### 6.4 커스텀 모션 그룹 추가하기

1. Cubism Editor에서 새 모션 타임라인 제작 → `.motion3.json` 내보내기
2. `motions/` 폴더에 파일 배치
3. `model3.json`의 `Motions`에 그룹 추가:
   ```json
   "Motions": {
     "Idle": [...],
     "Dancing": [
       { "File": "motions/dance_01.motion3.json" },
       { "File": "motions/dance_02.motion3.json" }
     ]
   }
   ```
4. `model_registry.json`의 `emotionMotionMap`에 매핑 추가:
   ```json
   "emotionMotionMap": {
     "joy": "Dancing"
   }
   ```

---

## 7. 물리(Physics) 시스템

### 7.1 물리 파일 구조 (`.physics3.json`)

물리 시뮬레이션은 머리카락, 의상, 액세서리 등의 **자연스러운 흔들림**을 구현합니다.

```json
{
  "Version": 3,
  "Meta": {
    "PhysicsSettingCount": 16,
    "Fps": 30,
    "EffectiveForces": {
      "Gravity": { "X": 0, "Y": -1 },
      "Wind": { "X": 0, "Y": 0 }
    },
    "PhysicsDictionary": [
      { "Id": "PhysicsSetting1", "Name": "Hair Sway_Front" },
      { "Id": "PhysicsSetting2", "Name": "Hair Sway_Side" },
      { "Id": "PhysicsSetting3", "Name": "Hair Sway_Back" },
      { "Id": "PhysicsSetting9", "Name": "Hat Brim Sway" },
      { "Id": "PhysicsSetting10", "Name": "Hat Ribbon Sway" },
      { "Id": "PhysicsSetting11", "Name": "Feather Sway" },
      { "Id": "PhysicsSetting14", "Name": "Pendant Sway" },
      { "Id": "PhysicsSetting15", "Name": "Robe Sway" }
    ]
  },
  "PhysicsSettings": [
    {
      "Id": "PhysicsSetting1",
      "Input": [
        { "Source": { "Target": "Parameter", "Id": "ParamAngleX" }, "Weight": 60, "Type": "X" }
      ],
      "Output": [
        { "Destination": { "Target": "Parameter", "Id": "ParamHairFront" }, ... }
      ],
      "Vertices": [ ... ]
    }
  ]
}
```

### 7.2 현재 모델(mao_pro)의 물리 설정

| 물리 그룹 | 영향 받는 파츠 |
|-----------|---------------|
| Hair Sway_Front | 앞머리 흔들림 |
| Hair Sway_Side | 옆머리 흔들림 |
| Hair Sway_Back | 뒷머리 흔들림 |
| Hair Sway_Back R L | 뒷머리 좌우 분리 흔들림 |
| Hair Streaks Sway | 머리카락 가닥 흔들림 |
| Front/Side/Back Hair_Fluff | 머리 보풀 미세 움직임 |
| Hat Brim Sway | 모자 챙 흔들림 |
| Hat Ribbon Sway | 모자 리본 흔들림 |
| Feather Sway | 깃털 흔들림 |
| Hat Top Sway | 모자 꼭대기 흔들림 |
| Hood Rope Sway | 후드 끈 흔들림 |
| Pendant Sway | 펜던트 흔들림 |
| Robe Sway | 로브 흔들림 |
| Robe Sway Y | 로브 세로 흔들림 |

### 7.3 물리 설정 핵심 원리

```
Input (입력)                   → Processing (처리)    → Output (출력)
────────────────────────────────────────────────────────────────────
머리가 좌우로 회전              → 진자 물리 계산       → 앞머리가 반대 방향으로 흔들림
(ParamAngleX, Weight: 60)     → (Vertices: 스프링)   → (ParamHairFront)
```

- **Input**: 어떤 파라미터의 변화가 물리를 트리거하는지
- **Weight**: 입력 강도 (값이 클수록 더 크게 반응)
- **Output**: 물리 결과가 적용되는 파라미터
- **Vertices**: 스프링-질량 시뮬레이션의 노드 설정

> 💡 물리 설정은 **Cubism Editor에서 그래픽으로 편집**하는 것을 강력히 권장합니다. JSON 수동 편집은 비직관적입니다.

---

## 8. 포즈(Pose) 시스템 — 복장/의상 교체

### 8.1 포즈 파일 구조 (`.pose3.json`)

```json
{
  "Type": "Live2D Pose",
  "Groups": [
    [
      { "Id": "PartArmLA", "Link": [] },
      { "Id": "PartArmLB", "Link": [] }
    ],
    [
      { "Id": "PartArmRA", "Link": [] },
      { "Id": "PartArmRB", "Link": [] }
    ]
  ]
}
```

### 8.2 포즈 그룹의 원리

- `Groups` 배열의 각 요소는 **상호 배타적인 파츠 그룹**
- 그룹 내 첫 번째 파츠가 기본 표시, 나머지는 숨김
- **같은 그룹의 파츠는 동시에 표시되지 않음**

**현재 mao_pro 모델의 포즈 구성**:

```
그룹 1: [PartArmLA, PartArmLB]  → 왼팔: 포즈A 또는 포즈B
그룹 2: [PartArmRA, PartArmRB]  → 오른팔: 포즈A 또는 포즈B
```

### 8.3 의상 교체 시스템 구현

의상을 교체하려면 PSD에서 **의상별 파츠를 별도 레이어로 분리**한 후 포즈 그룹으로 설정합니다:

**예시: 3벌의 의상**:

```json
{
  "Type": "Live2D Pose",
  "Groups": [
    [
      { "Id": "PartOutfitA", "Link": ["PartArmLA", "PartArmRA"] },
      { "Id": "PartOutfitB", "Link": ["PartArmLB", "PartArmRB"] },
      { "Id": "PartOutfitC", "Link": ["PartArmLC", "PartArmRC"] }
    ],
    [
      { "Id": "PartArmLA", "Link": [] },
      { "Id": "PartArmLB", "Link": [] },
      { "Id": "PartArmLC", "Link": [] }
    ],
    [
      { "Id": "PartArmRA", "Link": [] },
      { "Id": "PartArmRB", "Link": [] },
      { "Id": "PartArmRC", "Link": [] }
    ]
  ]
}
```

**파츠 이름 규칙**:
- `PartOutfitA`: 의상 A의 몸통 파츠
- `PartArmLA`: 의상 A에서의 왼팔
- `Link`: 이 파츠가 활성화되면 같이 활성화될 연결 파츠

### 8.4 의상 교체를 위한 전체 워크플로우

```
1. PSD에서 의상별 레이어 그룹 준비
   ├── OutfitA/ (상의, 하의, 팔, 액세서리)
   └── OutfitB/ (상의, 하의, 팔, 액세서리)

2. Cubism Editor에서 각 의상 파츠를 Part로 설정
   ├── PartOutfitA (기본 표시)
   └── PartOutfitB (숨김)

3. pose3.json에 그룹 정의

4. 런타임에서 파츠 전환
   └── live2dModel.internalModel.coreModel.setPartOpacityById("PartOutfitA", 0)
   └── live2dModel.internalModel.coreModel.setPartOpacityById("PartOutfitB", 1)
```

> ⚠️ **현재 Geny 시스템에서는 의상 교체 API가 미구현** 상태입니다. 구현이 필요한 경우 백엔드에 엔드포인트 추가 + 프론트엔드 UI가 필요합니다.

---

## 9. model_registry.json 등록

### 9.1 파일 위치

```
backend/static/live2d-models/model_registry.json
```

### 9.2 전체 구조

```json
{
  "models": [
    { ... },   // 모델 항목들
    { ... }
  ],
  "default_model": "mao_pro",
  "agent_model_assignments": {}
}
```

### 9.3 새 모델 항목 추가 템플릿

```json
{
  "name": "my_avatar",
  "display_name": "My Avatar",
  "description": "새로운 VTuber 캐릭터 설명",
  "url": "/static/live2d-models/my_avatar/runtime/my_avatar.model3.json",
  "thumbnail": null,
  "kScale": 0.5,
  "initialXshift": 0,
  "initialYshift": 0,
  "idleMotionGroupName": "Idle",
  "emotionMap": {
    "neutral": 0,
    "sadness": 1,
    "fear": 1,
    "anger": 2,
    "disgust": 2,
    "joy": 3,
    "surprise": 3,
    "smirk": 3
  },
  "tapMotions": {
    "HitAreaHead": { "": 1 },
    "HitAreaBody": { "": 1 }
  },
  "emotionMotionMap": {
    "joy": "TapBody",
    "surprise": "TapBody",
    "anger": "TapBody",
    "sadness": "Idle",
    "fear": "Idle",
    "disgust": "Idle",
    "neutral": "Idle"
  }
}
```

### 9.4 각 필드 상세 설명

| 필드 | 타입 | 설명 |
|------|------|------|
| `name` | `string` | 모델 고유 ID (영문 소문자, 밑줄 허용). 폴더명과 일치 권장 |
| `display_name` | `string` | UI에 표시되는 이름 |
| `description` | `string` | 모델 설명 |
| `url` | `string` | `.model3.json` 파일의 서버 경로. `/static/live2d-models/...` 형식 |
| `thumbnail` | `string?` | 썸네일 이미지 경로 (미구현 시 `null`) |
| `kScale` | `float` | 모델 크기 비율. `0.3`=작게, `0.5`=보통, `0.8`=크게 |
| `initialXshift` | `float` | 모델 X축 초기 이동량 (픽셀) |
| `initialYshift` | `float` | 모델 Y축 초기 이동량 (픽셀) |
| `idleMotionGroupName` | `string` | 대기 모션 그룹 이름 (보통 `"Idle"`) |
| `emotionMap` | `Dict[str, int]` | **감정 → 표정 인덱스** 매핑 (아래 상세) |
| `tapMotions` | `Dict[str, Dict]` | 터치 영역별 모션 매핑 |
| `emotionMotionMap` | `Dict[str, str]` | **감정 → 모션 그룹** 매핑 (선택) |

### 9.5 emotionMap — 감정 ↔ 표정 인덱스 매핑

```json
"emotionMap": {
  "neutral":  0,  // → model3.json의 Expressions[0] = exp_01.exp3.json
  "sadness":  1,  // → model3.json의 Expressions[1] = exp_02.exp3.json
  "fear":     1,  // → sadness와 같은 표정 공유
  "anger":    2,  // → model3.json의 Expressions[2] = exp_03.exp3.json
  "disgust":  2,  // → anger와 같은 표정 공유
  "joy":      3,  // → model3.json의 Expressions[3] = exp_04.exp3.json
  "surprise": 3,  // → joy와 같은 표정 공유
  "smirk":    3   // → joy와 같은 표정 공유
}
```

> ⚠️ **인덱스는 `model3.json`의 `Expressions` 배열 순서와 정확히 일치**해야 합니다!
> 여러 감정이 같은 인덱스를 공유할 수 있습니다 (표정이 유사한 경우).

### 9.6 tapMotions — 터치 영역 매핑

```json
"tapMotions": {
  "HitAreaHead": { "": 1 },
  "HitAreaBody": { "": 1 }
}
```

- `HitAreaHead`: 머리 영역 터치 시 → motion index `1` 재생
- `HitAreaBody`: 몸통 영역 터치 시 → motion index `1` 재생
- 프론트엔드에서 클릭 위치의 Y좌표가 `0.4(40%)` 미만이면 Head, 이상이면 Body

### 9.7 emotionMotionMap — 감정별 모션 오버라이드 (선택)

```json
"emotionMotionMap": {
  "joy": "Dancing",       // joy 시 Dancing 그룹의 모션 재생
  "sadness": "Crying"     // sadness 시 Crying 그룹의 모션 재생
}
```

설정하지 않으면 백엔드의 기본 매핑이 사용됩니다:

```python
DEFAULT = {
    "joy": "TapBody",
    "surprise": "TapBody",
    "anger": "TapBody",
    "sadness": "Idle",
    "fear": "Idle",
    "disgust": "Idle",
    "neutral": "Idle",
}
```

---

## 10. 캐릭터 성격 프롬프트 작성

### 10.1 파일 위치

```
backend/prompts/vtuber_characters/{model_name}.md
```

모델명과 파일명이 일치해야 합니다. 없으면 `default.md`가 사용됩니다.

### 10.2 기본 템플릿

```markdown
## Character Personality

{캐릭터 이름}은(는) {성격 설명} VTuber입니다.
{추가 배경 설명}

### Traits
- {특성 1}
- {특성 2}
- {특성 3}
- {특성 4}

### Speech Style
- {말투 특성 1}
- {말투 특성 2}
- {말투 특성 3}
```

### 10.3 현재 default.md 내용

```markdown
## Character Personality

You are a friendly and approachable VTuber with a warm personality.
You enjoy chatting with your viewers and making them feel welcome.

### Traits
- Cheerful and optimistic
- Curious about new things
- Supportive and encouraging
- Uses natural, conversational Korean

### Speech Style
- Casual and friendly tone (반말/존댓말 as appropriate)
- Occasional use of emoticons in text
- Natural reactions to surprises or interesting topics
```

### 10.4 프롬프트가 적용되는 방식

1. 모델이 세션에 할당될 때 (`PUT /api/vtuber/agents/{session_id}/model`)
2. `vtuber_controller.py`의 `_inject_character_prompt()` 호출
3. 에이전트의 시스템 프롬프트에 `## Character Personality` 섹션 추가
4. LLM이 응답 생성 시 이 성격에 맞게 말함

> 💡 **감정 태그 사용을 유도**하려면 프롬프트에 다음을 추가하세요:
> ```
> 당신은 대화할 때 감정을 표현합니다. 기쁠 때는 [joy], 슬플 때는 [sadness],
> 놀랐을 때는 [surprise], 화날 때는 [anger] 태그를 메시지 앞에 붙여주세요.
> ```

---

## 11. 감정(Emotion) 매핑 시스템

### 11.1 전체 파이프라인

```
Agent LLM 응답: "[joy] 와, 정말 좋은 소식이네요!"
        │
        ▼
EmotionExtractor.extract()
        │  정규식: \[([a-zA-Z_]+)\]
        │  추출: emotion = "joy"
        ▼
EmotionExtractor.resolve_emotion()
        │  emotion_map에서 인덱스 조회
        │  "joy" → expression_index = 3
        ▼
AvatarStateManager.update_state()
        │  emotion = "joy"
        │  expression_index = 3
        │  motion_group = resolve_motion("joy") → "TapBody"
        │  trigger = "agent_output"
        ▼
SSE Push → Frontend Store → Live2DCanvas
        │  live2dModel.expression(3)   ← 기쁜 표정
        │  live2dModel.motion("TapBody", 0) ← 반응 모션
        ▼
화면에 아바타가 기쁜 표정으로 움직임!
```

### 11.2 감정 종류 및 우선순위

**EmotionExtractor**의 감정 해석 우선순위:

1. **LLM 응답 텍스트의 `[emotion]` 태그** (최우선)
2. **에이전트 실행 상태** (태그 없을 때 폴백)
   - `thinking` / `planning` → `neutral`
   - `executing` / `tool_calling` → `surprise`
   - `success` / `completed` → `joy`
   - `error` / `failed` → `fear`
   - `idle` / `waiting` → `neutral`
3. **기본값**: `neutral`

### 11.3 지원되는 감정 태그

| 태그 | 감정 | 기본 표정 | 기본 모션 |
|------|------|----------|----------|
| `[neutral]` | 중립 | index 0 | Idle |
| `[joy]` | 기쁨 | index 3 | TapBody |
| `[sadness]` | 슬픔 | index 1 | Idle |
| `[anger]` | 분노 | index 2 | TapBody |
| `[surprise]` | 놀라움 | index 3 | TapBody |
| `[fear]` | 공포 | index 1 | Idle |
| `[disgust]` | 역겨움 | index 2 | Idle |
| `[smirk]` | 능글 | index 3 | Idle |

### 11.4 커스텀 감정 추가하기

1. 새 표정 파일 (`exp_09.exp3.json`) 제작 → [5.5절](#55-새-표정-만들기-수동-json-편집) 참조
2. `model3.json`의 `Expressions` 배열에 추가 (인덱스 8이 됨)
3. `model_registry.json`의 `emotionMap`에 추가:
   ```json
   "emotionMap": {
     ...,
     "excited": 8
   }
   ```
4. (선택) `emotionMotionMap`에 매핑:
   ```json
   "emotionMotionMap": {
     "excited": "Dancing"
   }
   ```
5. LLM 프롬프트에 `[excited]` 태그 사용하도록 안내

---

## 12. 프론트엔드 렌더링 파이프라인

### 12.1 관련 파일

| 파일 | 역할 |
|------|------|
| `frontend/src/components/live2d/Live2DCanvas.tsx` | 핵심 렌더러 (Pixi.js + Live2D) |
| `frontend/src/components/live2d/VTuberPanel.tsx` | VTuber 패널 래퍼 (모델 선택, SSE 관리) |
| `frontend/src/components/live2d/MiniAvatar.tsx` | 미니 아바타 (채팅 메시지 옆) |
| `frontend/src/components/live2d/EmotionTester.tsx` | 디버그용 감정 테스트 UI |
| `frontend/src/store/useVTuberStore.ts` | Zustand 상태 관리 |
| `frontend/src/lib/api.ts` | VTuber API 클라이언트 |

### 12.2 렌더링 초기화 흐름

```
1. VTuberPanel 마운트
   │
   ├── 모델 리스트 로드 (GET /api/vtuber/models)
   ├── 세션에 모델 할당 (PUT /api/vtuber/agents/{session_id}/model)
   └── SSE 연결 시작 (GET /api/vtuber/agents/{session_id}/events)

2. Live2DCanvas 마운트
   │
   ├── Cubism Core SDK 로드 (/lib/live2d/live2dcubismcore.min.js)
   ├── pixi.js + pixi-live2d-display 동적 import
   ├── Live2DModel.registerTicker(PIXI.Ticker) ← 애니메이션 활성화
   │
   ├── PIXI.Application 생성
   │   ├── 캔버스 크기: 컨테이너 크기
   │   ├── 배경: 투명
   │   └── antialias + autoDensity
   │
   ├── Live2DModel.from(model.url) ← model3.json 로드
   │   └── 자동으로 .moc3, 텍스처, 표정, 모션, 물리 로드
   │
   ├── 스케일 조정: min(scaleX, scaleY) × 0.85
   ├── 앵커: (0.5, 0.5) 중앙
   └── Idle 모션 시작

3. SSE 이벤트 수신 루프
   │
   └── avatar_state 이벤트 → 표정/모션 적용
```

### 12.3 기능별 구현

**눈 추적 (Eye Focus)**:
```
마우스 이동 → 좌표 계산 → live2dModel.focus(x, y)
→ 모델의 눈동자가 마우스 방향을 따라감
```

**클릭 상호작용**:
```
캔버스 클릭 → Y좌표 판단 (40% 기준)
→ HitAreaHead 또는 HitAreaBody
→ API 호출 → 터치 모션 재생
```

**리사이즈 대응**:
```
ResizeObserver → 캔버스 크기 변경
→ 렌더러 리사이즈 → 모델 스케일/위치 재계산
```

---

## 13. 백엔드 데이터 흐름

### 13.1 관련 파일

| 파일 | 역할 |
|------|------|
| `backend/controller/vtuber_controller.py` | REST API + SSE 엔드포인트 |
| `backend/service/vtuber/live2d_model_manager.py` | 모델 레지스트리 관리 |
| `backend/service/vtuber/avatar_state_manager.py` | 아바타 상태 관리 + SSE 발행 |
| `backend/service/vtuber/emotion_extractor.py` | 감정 태그 추출 |
| `backend/service/vtuber/thinking_trigger.py` | 유휴 시 사고 트리거 |
| `backend/service/vtuber/delegation.py` | VTuber ↔ CLI 메시지 프로토콜 |

### 13.2 API 엔드포인트 요약

| Method | URL | 설명 |
|--------|-----|------|
| `GET` | `/api/vtuber/models` | 사용 가능한 모든 Live2D 모델 목록 |
| `GET` | `/api/vtuber/models/{name}` | 특정 모델 상세 정보 |
| `PUT` | `/api/vtuber/agents/{session_id}/model` | 세션에 모델 할당 |
| `GET` | `/api/vtuber/agents/{session_id}/state` | 현재 아바타 상태 조회 |
| `POST` | `/api/vtuber/agents/{session_id}/interact` | 터치 상호작용 |
| `POST` | `/api/vtuber/agents/{session_id}/emotion` | 수동 감정 오버라이드 |
| `GET` | `/api/vtuber/agents/{session_id}/events` | **SSE 스트림** (실시간 상태 변경) |

### 13.3 SSE 이벤트 형식

```
event: avatar_state
data: {
  "session_id": "abc123",
  "emotion": "joy",
  "expression_index": 3,
  "motion_group": "TapBody",
  "motion_index": 0,
  "intensity": 1.0,
  "transition_ms": 300,
  "trigger": "agent_output",
  "timestamp": "2026-04-01T12:00:00Z"
}
```

---

## 14. 체크리스트: 새 아바타 등록 전 확인사항

### 파일 준비 체크리스트

- [ ] `backend/static/live2d-models/{name}/runtime/` 디렉터리 생성
- [ ] `{name}.model3.json` — 진입점 파일
- [ ] `{name}.moc3` — 바이너리 모델
- [ ] `{name}.{resolution}/texture_00.png` — 텍스처 (최소 1장)
- [ ] `{name}.physics3.json` — 물리 설정
- [ ] `{name}.pose3.json` — 포즈 그룹 (의상 전환 없으면 빈 그룹 가능)
- [ ] `{name}.cdi3.json` — 파라미터 표시 정보
- [ ] `expressions/exp_01.exp3.json` ~ `exp_0N.exp3.json` — 표정 (최소 1개: neutral)
- [ ] `motions/mtn_01.motion3.json` — Idle 모션 (최소 1개)

### 등록 체크리스트

- [ ] `model3.json`의 `Expressions` 배열 순서 확인
- [ ] `model3.json`의 `Motions` 그룹 이름 확인 (`Idle` 필수)
- [ ] `model3.json`의 `HitAreas` 정의 (터치 반응 필요 시)
- [ ] `model3.json`의 `Groups.EyeBlink` IDs가 모델의 실제 파라미터와 일치
- [ ] `model_registry.json`에 새 모델 항목 추가
- [ ] `emotionMap`의 인덱스가 `model3.json`의 `Expressions` 순서와 일치
- [ ] `idleMotionGroupName`이 `model3.json`의 `Motions` 그룹 이름과 일치
- [ ] `url` 경로가 정확한지 확인
- [ ] (선택) `backend/prompts/vtuber_characters/{name}.md` 캐릭터 프롬프트 작성

### 동작 확인 체크리스트

- [ ] 브라우저에서 모델 로딩 정상 확인
- [ ] Idle 모션 정상 재생 확인
- [ ] 눈 깜빡임 자동 동작 확인
- [ ] 마우스 추적 (눈동자 이동) 확인
- [ ] 각 표정 인덱스별 전환 확인 (EmotionTester 사용)
- [ ] 터치 반응 모션 확인 (클릭)
- [ ] SSE 실시간 상태 업데이트 확인
- [ ] 물리 시뮬레이션 확인 (머리카락 흔들림 등)

---

## 15. 트러블슈팅

### 모델이 로딩되지 않음

| 증상 | 원인 | 해결법 |
|------|------|--------|
| 콘솔에 404 에러 | `url` 경로 오류 | `model_registry.json`의 `url` 확인 |
| "Failed to load Live2D Cubism Core SDK" | SDK 파일 누락 | `frontend/public/lib/live2d/live2dcubismcore.min.js` 존재 확인 |
| 모델이 표시만 되고 움직이지 않음 | Ticker 미등록 | `Live2DModel.registerTicker(PIXI.Ticker)` 호출 확인 |
| 모델이 깨져 보임 | 텍스처 경로 오류 | `model3.json`의 `Textures` 경로 확인 |

### 표정이 바뀌지 않음

| 증상 | 원인 | 해결법 |
|------|------|--------|
| 항상 neutral 표정 | `emotionMap` 매핑 오류 | 인덱스가 `Expressions` 배열 순서와 일치하는지 확인 |
| 특정 표정만 안 됨 | expression 인덱스 범위 초과 | `Expressions` 배열 길이 확인 |
| 감정 태그가 감지 안 됨 | 태그 형식 오류 | `[emotion]` 형식으로 대괄호 사용 확인 |

### 모션이 동작하지 않음

| 증상 | 원인 | 해결법 |
|------|------|--------|
| Idle가 재생 안 됨 | 그룹 이름 불일치 | `idleMotionGroupName`과 `Motions` 키 일치 확인 |
| 터치 반응 없음 | `HitAreas` 미정의 | `model3.json`에 HitAreas 추가 |
| 모션 전환 시 끊김 | FadeIn/FadeOut 미설정 | 모션에 `FadeInTime`, `FadeOutTime` 추가 |

### 물리가 작동하지 않음

| 증상 | 원인 | 해결법 |
|------|------|--------|
| 머리카락이 안 흔들림 | physics3.json 미참조 | `model3.json`의 `Physics` 필드 확인 |
| 비정상적 흔들림 | 물리 파라미터 범위 오류 | Cubism Editor에서 물리 설정 재조정 |

---

## 16. 참고 자료

### Live2D 공식 문서
- [Live2D Cubism SDK Manual](https://docs.live2d.com/cubism-sdk-manual/top/)
- [Cubism Editor Manual](https://docs.live2d.com/cubism-editor-manual/top/)
- [Model3 JSON Format Specification](https://docs.live2d.com/cubism-sdk-manual/cubism-json/)
- [Expression JSON Specification](https://docs.live2d.com/cubism-sdk-manual/exp/)
- [Motion JSON Specification](https://docs.live2d.com/cubism-sdk-manual/motion/)
- [Physics JSON Specification](https://docs.live2d.com/cubism-sdk-manual/physics/)

### 사용 중인 라이브러리
- [pixi-live2d-display](https://github.com/guansss/pixi-live2d-display) — Pixi.js용 Live2D 렌더러
- [Pixi.js](https://pixijs.com/) — 2D 렌더링 엔진
- Live2D Cubism Core SDK (`live2dcubismcore.min.js`)

### Geny 시스템 내부 문서
- `docs/01_VTuber_렌더링_시스템_분석_리포트.md` — 원본 시스템 분석
- `docs/03_VTuber_이식_세부_계획서.md` — 7단계 구현 계획
- `docs/VTUBER_ARCHITECTURE_REVIEW.md` — 아키텍처 리뷰 및 알려진 이슈

---

## 부록 A: Quick Start — 5분만에 새 아바타 추가하기

이미 Cubism Editor에서 내보낸 파일이 있다면:

```bash
# 1. 폴더 구조 생성
mkdir -p backend/static/live2d-models/my_avatar/runtime/expressions
mkdir -p backend/static/live2d-models/my_avatar/runtime/motions

# 2. 파일 복사
cp exported_files/* backend/static/live2d-models/my_avatar/runtime/

# 3. model_registry.json에 항목 추가 (위 9.3절 참조)

# 4. (선택) 캐릭터 프롬프트 작성
echo "## Character Personality\n..." > backend/prompts/vtuber_characters/my_avatar.md

# 5. 서버 재시작 → 브라우저에서 확인
```

## 부록 B: 표정 파라미터 레시피 모음

### 기쁨 (Joy)
```json
{ "ParamEyeLOpen": 1.2, "ParamEyeROpen": 1.2, "ParamEyeLSmile": 1, "ParamEyeRSmile": 1, "ParamEyeEffect": 1, "ParamMouthUp": 0.8 }
```

### 슬픔 (Sadness)
```json
{ "ParamEyeLOpen": 0.5, "ParamEyeROpen": 0.5, "ParamBrowLY": -0.5, "ParamBrowRY": -0.5, "ParamMouthDown": 0.6 }
```

### 분노 (Anger)
```json
{ "ParamEyeLForm": -0.8, "ParamEyeRForm": -0.8, "ParamBrowLAngle": -0.8, "ParamBrowRAngle": -0.8, "ParamMouthAngry": 1 }
```

### 놀라움 (Surprise)
```json
{ "ParamEyeLOpen": 1.4, "ParamEyeROpen": 1.4, "ParamBrowLY": 0.8, "ParamBrowRY": 0.8, "ParamA": 0.5, "ParamEyeBallForm": 0.5 }
```

### 공포 (Fear)
```json
{ "ParamEyeLOpen": 1.3, "ParamEyeROpen": 1.3, "ParamEyeBallForm": 0.8, "ParamBrowLY": 0.6, "ParamBrowRY": 0.6, "ParamBrowLAngle": 0.3, "ParamBrowRAngle": 0.3 }
```

### 역겨움 (Disgust)
```json
{ "ParamEyeLOpen": 0.6, "ParamEyeROpen": 0.6, "ParamEyeLForm": -0.5, "ParamEyeRForm": -0.5, "ParamMouthAngry": 0.7, "ParamBrowLAngle": -0.5, "ParamBrowRAngle": -0.5 }
```

### 능글/비꼬는 (Smirk)
```json
{ "ParamEyeLOpen": 0.8, "ParamEyeROpen": 1.0, "ParamEyeLSmile": 0.7, "ParamEyeRSmile": 0.3, "ParamMouthUp": 0.5, "ParamBrowLY": 0.3 }
```

### 당황/부끄러움 (Embarrassed)
```json
{ "ParamEyeLOpen": 0.7, "ParamEyeROpen": 0.7, "ParamEyeLSmile": 0.5, "ParamEyeRSmile": 0.5, "ParamCheek": 1, "ParamBrowLY": 0.3, "ParamBrowRY": 0.3 }
```

---

## 부록 C: 아키텍처 표준성 검토 — "이 JSON 구조는 표준인가?"

### C.1 결론 요약

| 레이어 | 파일/구조 | 표준 여부 | 설명 |
|--------|----------|----------|------|
| `.model3.json` | Live2D Cubism 4 SDK 공식 규격 | ✅ **Live2D 공식 표준** | Live2D Inc.가 정의한 독점 포맷. 2D VTuber 업계의 *de facto* 표준 |
| `.moc3` | Cubism 4 바이너리 | ✅ **Live2D 공식 표준** | 컴파일된 모델 바이너리. SDK가 직접 로드 |
| `.exp3.json` | Cubism 4 Expression | ✅ **Live2D 공식 표준** | 파라미터 오버라이드 방식의 표정 정의 |
| `.motion3.json` | Cubism 4 Motion | ✅ **Live2D 공식 표준** | 키프레임 기반 애니메이션 |
| `.physics3.json` | Cubism 4 Physics | ✅ **Live2D 공식 표준** | 스프링-질량 물리 시뮬레이션 |
| `.pose3.json` | Cubism 4 Pose | ✅ **Live2D 공식 표준** | 상호배타적 파츠 그룹 |
| `.cdi3.json` | Cubism 4 DisplayInfo | ✅ **Live2D 공식 표준** | 파라미터·파츠 메타데이터 |
| `model_registry.json` | Geny 프로젝트 고유 | ❌ **Geny 커스텀** | 모델 관리·감정 매핑 등 래핑 레이어 |
| `emotionMap` | Geny 프로젝트 고유 | ❌ **Geny 커스텀** | 감정→표정 인덱스 매핑 |
| `emotionMotionMap` | Geny 프로젝트 고유 | ❌ **Geny 커스텀** | 감정→모션 그룹 매핑 |

### C.2 Live2D Cubism JSON 포맷 — 업계 위상

Live2D Cubism SDK의 JSON 포맷은 **개방형 국제 표준(W3C, ISO 등)은 아니지만**, 2D 아바타/VTuber 분야에서 **사실상의 산업 표준(de facto standard)**입니다.

```
2D 아바타 기술 시장 점유율 (VTuber 분야, 2024~2026 기준):

┌──────────────────────────────────────────────────────┐
│ Live2D Cubism     ████████████████████████████  ~85%  │ ← 압도적 1위
│ VRoid/VRM (3D)    ████████                     ~10%  │
│ Spine 2D          ██                            ~3%  │
│ 기타 (자체 엔진)    █                             ~2%  │
└──────────────────────────────────────────────────────┘
```

**Live2D가 표준이 된 이유**:
- 일본·한국·중국 VTuber 업계에서 거의 독점적 위치
- Hololive, Nijisanji 등 대형 사무소 대부분이 Live2D 사용
- Cubism Editor가 유일한 상용 급 2D 리깅 도구 (경쟁자 부재)
- SDK가 무료 제공 (상용 이용 시 라이선스 필요)

### C.3 JSON 기반 설정 패턴 — 게임/애니메이션 업계 표준 관행

JSON으로 모델·애니메이션·물리를 정의하는 것은 **매우 일반적인 아키텍처 패턴**입니다:

| 엔진/프레임워크 | 설정 포맷 | 구조 유사도 |
|----------------|----------|------------|
| **Live2D Cubism 4** | `.model3.json` + 하위 JSON | 현재 사용 중 |
| **Spine (2D 애니메이션)** | `.json` (스켈레톤 + 애니메이션) | 매우 유사 — JSON에 메시, 본, 키프레임 정의 |
| **Lottie (Airbnb)** | `.json` (After Effects 내보내기) | 유사 — JSON 키프레임 애니메이션 |
| **glTF 2.0 (3D 표준)** | `.gltf` (JSON) + `.bin` (바이너리) | 동일 패턴 — JSON 메타 + 바이너리 데이터 |
| **VRM (3D 아바타)** | `.vrm` (glTF 확장) | 유사 — JSON 메타데이터 + 바이너리 메시 |
| **Unity Animator** | `.anim` (YAML/JSON) | 유사 — 키프레임 커브 정의 |
| **Rive (전 Flare)** | `.riv` (바이너리) | 다름 — 바이너리만 사용 |

**공통 패턴**: `진입점 JSON` → `바이너리 모델` + `텍스처` + `애니메이션 JSON` + `물리 JSON`

Live2D의 `model3.json → moc3 + png + exp3.json + motion3.json + physics3.json` 구조는 이 패턴을 **정확히** 따릅니다. 이것은 우연이 아니라, 게임·애니메이션 업계에서 검증된 아키텍처입니다.

### C.4 "파라미터 오버라이드" 방식의 표정 시스템 — 표준성

`.exp3.json`의 표정 방식 (기본값에 Add/Multiply/Overwrite로 파라미터를 덮어쓰는 방식)은 **애니메이션 엔진의 일반적인 블렌딩 패턴**입니다:

```
┌─────────────────────────────────────────────────────────────────┐
│                   표정 블렌딩 기법 비교                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Live2D exp3.json        Unity Animator          Unreal Engine │
│  ┌──────────────┐       ┌──────────────┐       ┌────────────┐  │
│  │ Base State   │       │ Base Layer   │       │ Base Pose  │  │
│  │ (model 기본)  │       │ (Idle)       │       │ (Reference)│  │
│  └──────┬───────┘       └──────┬───────┘       └─────┬──────┘  │
│         │                      │                      │         │
│  ┌──────▼───────┐       ┌──────▼───────┐       ┌─────▼──────┐  │
│  │ Expression   │       │ Override     │       │ Blend      │  │
│  │ Layer        │       │ Layer        │       │ Shape      │  │
│  │              │       │              │       │            │  │
│  │ Add/Multiply │       │ Additive/    │       │ Additive/  │  │
│  │ /Overwrite   │       │ Override     │       │ Override   │  │
│  └──────────────┘       └──────────────┘       └────────────┘  │
│                                                                 │
│  → 동일한 레이어드 블렌딩 개념                                    │
└─────────────────────────────────────────────────────────────────┘
```

**결론**: `Add`/`Multiply`/`Overwrite` 블렌딩은 업계 표준 기법이며, Live2D만의 특수한 방식이 아닙니다.

### C.5 Geny 커스텀 레이어 — `model_registry.json` 분석

Live2D SDK 자체에는 **"감정 매핑"이나 "모델 관리 레지스트리"** 개념이 없습니다. 이 부분은 Geny 프로젝트에서 자체적으로 설계한 래핑 레이어입니다.

```
┌─────────────────────────────────────────────────────────────┐
│                    계층 구분                                  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Geny 래핑 레이어 (model_registry.json)               │  │
│  │  ┌─────────────────┐  ┌──────────────────────────┐   │  │
│  │  │  emotionMap      │  │  emotionMotionMap         │   │  │
│  │  │  "joy" → 3       │  │  "joy" → "TapBody"       │   │  │
│  │  │  "sadness" → 1   │  │  "sadness" → "Idle"      │   │  │
│  │  └─────────────────┘  └──────────────────────────┘   │  │
│  │  ┌─────────────────┐  ┌──────────────────────────┐   │  │
│  │  │  kScale, Xshift │  │  tapMotions               │   │  │
│  │  │  (레이아웃 설정)  │  │  (터치 반응 매핑)          │   │  │
│  │  └─────────────────┘  └──────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────┘  │
│                          ↓ 참조                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Live2D 표준 레이어 (model3.json + SDK 파일들)         │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │  │
│  │  │ .moc3    │ │ .exp3    │ │ .motion3 │ │ .png    │ │  │
│  │  │ (모델)   │ │ (표정)   │ │ (모션)   │ │ (텍스처)│ │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └─────────┘ │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Geny 커스텀 레이어가 필요한 이유**:

| 기능 | Live2D SDK 기본 제공? | Geny에서 구현 |
|------|---------------------|--------------|
| 모델 파일 로딩 | ✅ `model3.json`으로 로딩 | — |
| 표정 인덱스로 전환 | ✅ `expression(index)` | — |
| 모션 그룹으로 재생 | ✅ `motion(group, index)` | — |
| **감정 이름 → 표정 매핑** | ❌ SDK에 없음 | ✅ `emotionMap` |
| **감정 → 모션 자동 연결** | ❌ SDK에 없음 | ✅ `emotionMotionMap` |
| **LLM 감정 태그 파싱** | ❌ SDK에 없음 | ✅ `EmotionExtractor` |
| **여러 모델 중앙 관리** | ❌ SDK에 없음 | ✅ `model_registry.json` |
| **세션별 모델 할당** | ❌ SDK에 없음 | ✅ `Live2dModelManager` |
| **실시간 상태 스트리밍** | ❌ SDK에 없음 | ✅ `SSE + AvatarStateManager` |

### C.6 다른 VTuber 시스템과의 비교

Geny의 아키텍처를 다른 VTuber 시스템과 비교합니다:

#### 1) VTube Studio (상용, 가장 대중적)

```
VTube Studio:
  모델 로딩:    model3.json 직접 로딩 (동일)
  표정 전환:    핫키 바인딩 (사용자 수동 설정)
  감정 연동:    없음 (수동 조작만)
  물리:        physics3.json 그대로 사용 (동일)
  커스텀 레이어: 플러그인 API (JSON-RPC over WebSocket)
```

#### 2) Open-LLM-VTuber (Geny의 원본 참고 시스템)

```
Open-LLM-VTuber:
  모델 로딩:    model3.json (동일)
  표정 전환:    LLM 감정 추론 → 표정 인덱스 매핑
  감정 연동:    Python 서비스에서 처리 (Geny와 유사)
  차이점:       단일 세션, 단일 모델만 지원
```

#### 3) Geny (현재 시스템)

```
Geny:
  모델 로딩:    model3.json (표준)
  표정 전환:    [emotion] 태그 → emotionMap → expression(index)
  감정 연동:    EmotionExtractor + AvatarStateManager
  차별점:       다중 세션, 다중 모델, SSE 실시간 스트리밍,
               듀얼 에이전트(VTuber+CLI), 사고 트리거
```

### C.7 Cubism 파일 포맷 버전 히스토리

| 버전 | 접미사 | SDK 명칭 | 호환성 |
|------|--------|---------|--------|
| Cubism 2.x | `.model.json`, `.moc`, `.exp.json`, `.mtn` | Cubism 2 SDK | ❌ Geny 미지원 |
| Cubism 3.x | `.model3.json`, `.moc3`, `.exp3.json`, `.motion3.json` | Cubism 3 SDK | ⚠️ 부분 호환 |
| **Cubism 4.x** | `.model3.json`, `.moc3`, `.exp3.json`, `.motion3.json` | **Cubism 4 SDK** | ✅ **Geny 사용 중** |
| Cubism 5.x | 동일 확장자 (하위 호환) | Cubism 5 SDK | ✅ 하위 호환 예상 |

> 💡 Cubism 3과 4는 **같은 파일 확장자**를 사용하지만, `.moc3` 바이너리 내부 버전이 다릅니다.
> `pixi-live2d-display/cubism4` 임포트를 사용하므로 Cubism 4+ 전용입니다.

### C.8 이 구조의 장단점 평가

#### 장점

| 항목 | 설명 |
|------|------|
| **검증된 포맷** | Live2D SDK는 10년+ 역사, 수만 개 모델이 이 포맷으로 제작됨 |
| **도구 생태계** | Cubism Editor → 내보내기 → 바로 사용 (커스텀 변환 불필요) |
| **JSON 가독성** | 표정·모션을 사람이 읽고 수동 편집 가능 |
| **관심사 분리** | 모델(moc3), 텍스처(png), 표정(exp3), 모션(motion3), 물리(physics3) 가 각각 독립 파일 |
| **증분 업데이트** | 표정 하나만 수정 시 해당 exp3.json만 교체하면 됨 |
| **Geny 래핑** | emotionMap으로 LLM↔아바타 간 깔끔한 브릿지 구현 |

#### 단점 / 주의사항

| 항목 | 설명 | Geny에서의 영향 |
|------|------|---------------|
| **독점 포맷** | Live2D Inc.의 프로프라이어터리 포맷, 공개 표준 아님 | Live2D SDK 의존성 불가피 |
| **SDK 라이선스** | 상용 이용 시 Live2D 라이선스 필요 (매출 1000만원 이하 무료) | 사업 규모에 따라 비용 발생 |
| **인덱스 기반 매핑** | 표정이 이름이 아닌 **배열 인덱스**로 참조됨 | 순서 변경 시 emotionMap 깨짐 ⚠️ |
| **모션 그룹 느슨한 바인딩** | model3.json의 Motions 키 이름이 자유 텍스트 | 오타 시 런타임에서만 발견 |
| **스키마 검증 없음** | JSON Schema 제공 안 됨 | 잘못된 파일도 로딩 시도 → 런타임 에러 |
| **바이너리 편집 불가** | .moc3는 Cubism Editor 없이 수정 불가 | 모델 구조 변경 시 항상 Editor 필요 |

### C.9 인덱스 기반 매핑의 위험성과 대안

현재 Geny의 가장 취약한 설계 포인트는 **표정 인덱스 매핑**입니다:

```
⚠️ 현재 방식 (인덱스 기반):
model3.json:    Expressions[0]="exp_01", [1]="exp_02", [2]="exp_03", [3]="exp_04"
registry.json:  emotionMap: { "neutral": 0, "sadness": 1, "anger": 2, "joy": 3 }

위험: Expressions 배열 순서가 바뀌면 emotionMap이 전부 틀어짐!
     예: exp_02와 exp_03의 순서를 바꾸면 sadness에 anger 표정이 나옴
```

**대안 가능성 (이름 기반 매핑)**:

```
개선 방식 (이름 기반):
model3.json:    Expressions: [{"Name": "neutral", ...}, {"Name": "sadness", ...}]
registry.json:  emotionMap: { "joy": "exp_04_joy" }  ← 인덱스 대신 Name 사용

→ pixi-live2d-display는 expression(name) 호출도 지원하므로 기술적으로 가능
→ 단, 현재 Geny 코드는 expression(index)를 사용 중
```

> 💡 **현재 시스템에서의 안전 수칙**: `model3.json`의 `Expressions` 배열 순서를 **절대 변경하지 마세요.**
> 새 표정은 항상 **배열 끝에 추가**하고, `emotionMap`에 새 인덱스로 등록하세요.

### C.10 정리: "이 구조를 그대로 따라도 되는가?"

**Yes.** 이 구조는 다음 이유로 신뢰할 수 있습니다:

1. **Live2D SDK 파일 포맷** (`model3.json`, `exp3.json` 등)은 Live2D Inc.의 **공식 규격**이며, Cubism Editor에서 자동 생성됩니다. 직접 포맷을 설계할 필요가 없습니다.

2. **JSON 메타 + 바이너리 데이터** 패턴은 glTF, Spine, Lottie 등 주요 엔진에서 동일하게 사용하는 **업계 표준 아키텍처**입니다.

3. **Geny의 래핑 레이어** (`model_registry.json`, `emotionMap`)는 Live2D SDK가 제공하지 않는 **LLM↔아바타 브릿지**를 구현하기 위한 합리적인 설계입니다.

4. 유일한 주의점은 **인덱스 기반 표정 매핑**의 취약성이며, 이는 표정 순서를 고정하고 새 표정을 끝에만 추가하는 규칙으로 관리합니다.

---

> **이 문서는 Geny VTuber 시스템의 코드베이스를 기반으로 작성되었습니다.**
> 모델 파일 규격은 Live2D Cubism 4 SDK를 따릅니다.
