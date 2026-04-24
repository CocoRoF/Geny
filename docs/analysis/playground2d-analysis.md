# Playground 2D 심층 분석 및 개편안

> 작성일: 2026-04-08  
> 대상: `Geny/frontend/src/lib/playground2d/` + `Geny/backend/routers/playground2d.py`

---

## 1. 시스템 아키텍처 현황

### 1.1 전체 데이터 흐름

```
┌─────────────┐     polling      ┌──────────────────┐     convert      ┌───────────────────┐
│   Backend    │ ───────────────→ │  useAppStore     │ ───────────────→ │ Playground2DTab   │
│ GET /agents  │  (수동 호출)     │  sessions[]      │   sessionTo      │ sessionToWorld    │
│              │                  │                  │   WorldEvents()  │ Events()          │
└─────────────┘                  └──────────────────┘                  └────────┬──────────┘
                                                                                │
                                                                        applyWorldEvent()
                                                                                │
                                                                                ▼
┌─────────────┐  setWorldState   ┌──────────────────┐   syncRuntime    ┌───────────────────┐
│  WorldMap    │ ◄───────────── │  WorldState       │ ───────────────→ │ AvatarRuntime     │
│  (Canvas)    │    render()     │  agents{}         │  pathfinding     │ movement, chat    │
│              │                 │  avatars{}        │  destinations    │ walk animation    │
└─────────────┘                 └──────────────────┘                  └───────────────────┘
```

### 1.2 핵심 문제: 실시간 연동 부재

| 항목 | 현재 상태 | 기대 상태 |
|------|----------|----------|
| 세션 상태 수신 | 수동 polling (`GET /api/agents`) | SSE/WebSocket 실시간 push |
| 세션 → 이벤트 변환 | `session_id:status` 변경시만 | 모든 상태 변화 (tool 호출, task 진행 등) |
| 아바타 위치 | 프론트엔드에서만 관리 (휘발) | 서버 추적 or 최소 localStorage persist |
| 에이전트 활동 | `running`/`stopped` 2가지만 | tool_called, task_created 등 세분화 |

**현재 Backend SSE가 있지만 Playground에 미연결:**
- `GET /api/agents/{id}/execute/events` — 개별 세션 실행 이벤트 SSE 존재
- 이벤트 타입: `status`, `log`, `result`, `heartbeat`, `error`, `done`
- 그러나 **Playground2DTab에서 이 SSE를 구독하지 않음**
- 결과: 세션이 실행 중이어도 playground에서는 최초 1회 `task_assigned` 이벤트만 발생

---

## 2. 각 모듈별 상세 분석

### 2.1 이벤트 파이프라인 (`eventsPipeline.ts`)

**작동하는 것:**
- 7가지 이벤트 타입 처리 (`task_created` → `run_completed`)
- Agent zone 전이 (idle → intake → planning → tools → done)
- Avatar 동기화 (이름, bubble text, destination)

**문제점:**

| # | 문제 | 영향도 | 설명 |
|---|------|--------|------|
| E1 | `moving` 플래그 역전 | **Critical** | `normalizeAvatars()`에서 `moving: !task` — task가 있으면 정지, 없으면 이동. 의도와 반대됨 |
| E2 | `ROLE_BUILDING_MAP` 미사용 | **High** | 역할별 건물 배정 정의되어 있으나 `deriveDestinationForZone()`에서 무시 |
| E3 | 이벤트 소스 부재 | **Critical** | Backend SSE → Playground 연결 없음. `sessionToWorldEvents()`만으로는 2가지 상태만 전달 |
| E4 | destination 재계산 빈도 | **Medium** | 세션 상태 변경시에만 destination 재계산, 자연스러운 이동 패턴 불가 |

**`moving` 플래그 문제 상세 (E1):**
```typescript
// worldMap.ts normalizeAvatars() — 현재 코드
moving: !task,  // task 있으면 moving=false → 제자리 고정

// 기대하는 동작:
// task 있음 → work station으로 이동 후 seated
// task 없음 → idle station에서 대기 or 느리게 배회
```

### 2.2 아바타 런타임 (`avatarRuntime.ts`)

**작동하는 것:**
- A* pathfinding + agent별 jitter
- 근접 기반 대화 시스템 (2타일 이내, 30% 확률, 3.5초/턴)
- Soft-blocking (타 에이전트 타일 회피)
- Walk animation (2프레임, 180ms 간격)

**문제점:**

| # | 문제 | 영향도 | 설명 |
|---|------|--------|------|
| A1 | Station claiming 비영속 | **Medium** | `claimedStationIds`가 매 프레임 지역변수. 2명이 같은 자리 점유 가능 |
| A2 | 도착 후 행동 부재 | **Low** | 목적지 도착 → seated=true → 그 이후 아무 행동 없음 |
| A3 | Chat 이후 복귀 미구현 | **Low** | 대화 끝나면 경로 null. 원래 목적지로 복귀하지 않음 |
| A4 | Idle 배회 패턴 단순 | **Low** | Outdoor station 중 random 1곳만 선택. 산책 경로 개념 없음 |

### 2.3 월드맵 렌더러 (`worldMap.ts`, ~1920줄)

**렌더 레이어 (10단계):**

| Layer | 내용 | 상태 |
|-------|------|------|
| 0 | Terrain (잔디/흙/돌/물) | OK — 물 타일 프로시져럴 애니메이션 |
| 1 | Decorations (꽃) | OK — 6개 클러스터 + 배경 산포 |
| 2 | Building Interiors | OK — 바닥, 벽, 가구, 문 |
| 3 | Props (나무, 바위) | OK — tree/tree.conifer 제거 완료 |
| 4 | Avatars | OK — 스프라이트, 그림자, 말풍선, 이름 |
| 5 | Building Roofs | OK — station 없는 건물만 지붕 표시 |
| 6 | Location Signs | OK — 나무 간판 |
| 6.5 | Sky Overlay | OK — Day/Night/Clock 3모드 |
| 7 | UI (시간, 에이전트 목록) | OK |
| 8 | Agent Profile + Character Picker | **NEW** — 방금 구현 |
| 9 | Editor Overlays | OK |

**문제점:**

| # | 문제 | 영향도 | 설명 |
|---|------|--------|------|
| R1 | Agent Roster 클릭 불가 | **Medium** | 우측 상단 목록은 표시만. 클릭으로 에이전트 선택 불가 |
| R2 | Character Picker UX | **Medium** | 212캐릭터 순차 탐색만 가능. 검색/필터 없음 |
| R3 | Missing terrain sprites | **Low** | dirt, path, sand, stone = 빈 candidates (fallback 색상) |
| R4 | Missing prop sprites | **Low** | rock, rock.small = 빈 candidates (fallback 도형) |

### 2.4 월드 에디터 (`worldEditor.ts`, ~1430줄)

**작동하는 것:**
- 건물/나무/가구/야외스테이션 배치
- Undo/Redo (50단계)
- API를 통한 Save/Load/Revert
- 키보드 단축키 (E, Ctrl+Z/Y/S, Delete, F, 방향키)
- Flip X/Y, 화살표 미세조정

**문제점:**

| # | 문제 | 영향도 | 설명 |
|---|------|--------|------|
| W1 | 건물 리사이즈 불가 | **Medium** | 배치 후 크기 변경 불가. auto-size만 |
| W2 | 실내 가구 위치지정 UI 부재 | **High** | 어떤 건물에 가구를 넣는지 선택하는 UI 없음 |
| W3 | 나무 좌표 클램핑 오류 | **Medium** | 0-29로 제한하는데 월드는 60×60 |
| W4 | 충돌 검사 없음 | **Low** | 건물끼리 겹쳐 배치 가능 |
| W5 | 건물 내부 편집 불가 | **Low** | zone, wall, interior는 JSON 직접 편집 필요 |

### 2.5 커스텀 기능 현황 (`usePlayground2DStore.ts`)

**방금 구현한 것:**
- `agentAvatars: Record<string, number>` — localStorage 영속화
- `setAgentAvatar` / `getAgentAvatar` — Store actions
- `drawCharacterVariant` → Store 우선 조회 후 hash fallback
- Profile panel 하단 Character Picker (thumbnail + 좌우 스크롤)

**문제점:**

| # | 문제 | 영향도 | 설명 |
|---|------|--------|------|
| C1 | Picker 접근성 | **High** | 에이전트를 캔버스에서 클릭해야만 접근 가능. 에이전트가 없으면 picker 볼 수 없음 |
| C2 | 212개 순차 탐색 | **Medium** | 페이지당 ~6개씩 35페이지. 원하는 캐릭터 찾기 어려움 |
| C3 | 서버 미동기화 | **Low** | localStorage만. 다른 기기에서 설정 공유 불가 |

### 2.6 스프라이트 시스템 (`spriteManager.ts`)

**현황:**
- 53 character sheets × 4 variants = **212 캐릭터**
- 8 건물 스프라이트, 8 나무, 4 꽃, 50 가구
- 총 ~84 이미지 로드

**Missing sprites (7개):**
```
terrain.dirt    → fallback 색상 #c4a46c
terrain.path    → fallback 색상 #d4c4a0
terrain.sand    → fallback 색상 #e0d3a8
terrain.stone   → fallback 색상 #b0b0a8
terrain.water   → 프로시져럴 애니메이션
prop.rock       → fallback 타원
prop.rock.small → fallback 소형 타원
```

---

## 3. Backend 연동 분석

### 3.1 현재 API

| Endpoint | Method | 용도 | 상태 |
|----------|--------|------|------|
| `/api/playground2d/layout` | GET | 월드 레이아웃 조회 | OK |
| `/api/playground2d/layout` | PUT | 월드 레이아웃 저장 | OK |
| `/api/playground2d/state` | GET | 아바타 상태 조회 | **STUB** — 빈 배열 반환 |
| `/api/agents` | GET | 세션 목록 | OK (polling) |
| `/api/agents/{id}/execute/events` | GET (SSE) | 실행 이벤트 스트림 | OK but **Playground 미연결** |

### 3.2 `agent_session.py` 분석

세션 라이프사이클:
```
STARTING → RUNNING → IDLE (10분 후 자동전이) → STOPPED
                  ↘ ERROR
```

세션이 제공하는 데이터:
- `session_id`, `session_name`, `status`, `role`
- `session_type` (vtuber/cli), `model`, `linked_session_id`
- 실행 로그 (SessionLogger) — tool 호출, 결과, 에러 등

**Playground에서 활용 가능하지만 미사용인 데이터:**
- Tool 호출 정보 (`tool_called` 이벤트로 변환 가능)
- Task 진행 상황 (graph node 실행 결과)
- 세션 idle 전이 (자동 감지 → `idle` 이벤트)

### 3.3 프론트엔드 세션 Polling

```typescript
// useAppStore.ts
loadSessions: async () => {
  const sessions = await agentApi.list();  // GET /api/agents
  set({ sessions });
}
```

- **자동 polling 없음** — 수동 호출 필요
- Playground2DTab의 `useEffect`에서 `sessions` 변경 감지:
  ```typescript
  const sessionKey = sessions.map(s => `${s.session_id}:${s.status}`).join('|');
  if (sessionKey === prevSessionIdsRef.current) return;  // 변경 없으면 skip
  ```
- **session_name, role 변경은 무시됨** (sessionKey에 포함 안 됨)

---

## 4. 문제 우선순위 종합

### Critical (즉시 수정 필요)

| ID | 문제 | 파일 | 영향 |
|----|------|------|------|
| **E1** | `moving: !task` 역전 로직 | worldMap.ts:157 | 에이전트가 task 받으면 정지 (이동 불가) |
| **E3** | Backend SSE → Playground 미연결 | Playground2DTab.tsx | 실시간 활동 반영 불가. 최초 1회 이벤트만 |
| **C1** | 커스텀 기능 접근성 | worldMap.ts | 에이전트 없으면 picker 접근 불가 |

### High (기능성 문제)

| ID | 문제 | 파일 | 영향 |
|----|------|------|------|
| **E2** | ROLE_BUILDING_MAP 미사용 | eventsPipeline.ts | 역할별 자연스러운 건물 배정 불가 |
| **W2** | 실내 가구 위치지정 UI 부재 | worldEditor.ts | Indoor 탭 사실상 사용 불가 |
| **R1** | Agent Roster 클릭 불가 | worldMap.ts | 에이전트 많을 때 선택 어려움 |

### Medium (UX 개선)

| ID | 문제 | 파일 | 영향 |
|----|------|------|------|
| **E4** | destination 재계산 빈도 | eventsPipeline.ts | 단조로운 에이전트 행동 |
| **A1** | Station claiming 비영속 | avatarRuntime.ts | 2명이 같은 자리 점유 |
| **R2** | Character Picker UX | worldMap.ts | 212개 순차 탐색 |
| **W3** | 나무 좌표 클램핑 60×60 미반영 | worldEditor.ts | 에디터 이동 범위 제한 |
| **R3** | Missing terrain sprites | spriteManager.ts | fallback 색상만 표시 |

---

## 5. 개편안

### Phase 1: 핵심 동작 수정 (즉시)

#### 1-1. `moving` 플래그 로직 수정
```
현재: task 있음 → moving=false (정지)
수정: task 있음 → moving=true, destination=work station → 도착 후 seated
      task 없음 → moving=true, destination=rest/outdoor → 느린 배회
```

**수정 범위:**
- `worldMap.ts` — `normalizeAvatars()` 내 `moving` 로직 반전
- `eventsPipeline.ts` — `syncAvatarFromAgent()`에서 `moving` 명시적 설정
- `avatarRuntime.ts` — 도착 후 행동 추가 (seated → 일정 시간 후 다음 목적지)

#### 1-2. 역할 기반 건물 배정

**수정 범위:**
- `eventsPipeline.ts` — `deriveDestinationForZone()`에서 `ROLE_BUILDING_MAP` 활용
- `Playground2DTab.tsx` — `sessionToWorldEvents()`에서 role 정보 전달
- Agent에 `role` 필드 추가 → destination 결정시 우선 해당 건물 탐색

```typescript
// 개편 후 destination 결정 로직:
function deriveDestinationForZone(agent, world) {
  const role = agent.role || 'worker';
  const preferredBuildingId = ROLE_BUILDING_MAP[role];
  
  if (agent.zone === 'idle' || agent.zone === 'blocked') {
    // 건물 앞 야외 스테이션 or 배회
    return pickOutdoorNear(preferredBuildingId, world);
  }
  
  // Working zones: 역할에 해당하는 건물의 work station
  const building = world.locations.find(l => l.id === preferredBuildingId);
  if (building) {
    return pickWorkStation(building, agent);
  }
  // fallback: 아무 building
  return pickAnyWorkStation(world, agent);
}
```

#### 1-3. Character Picker 독립 접근

**방안:** Agent Roster 패널에서 에이전트 이름 클릭 → Profile 패널 + Picker 열기

**수정 범위:**
- `worldMap.ts` — `drawAgentRoster()`에 클릭 히트 영역 추가
- 로스터 항목 클릭 → `selectedAgent` 설정 + 카메라 해당 에이전트로 이동

### Phase 2: 실시간 연동 (중기)

#### 2-1. Backend SSE 구독

**아키텍처:**
```
Playground2DTab
  ├─ useEffect: sessions 초기 로드 (기존)
  ├─ useEffect: 각 running session에 대해 SSE 구독 (신규)
  │   └─ EventSource(`/api/agents/${id}/execute/events`)
  │       ├─ onmessage('log') → parseLogToWorldEvent() → applyWorldEvent()
  │       ├─ onmessage('status') → agent status 업데이트
  │       └─ onmessage('heartbeat') → idle 표시
  └─ cleanup: EventSource close
```

**수정 범위:**
- `Playground2DTab.tsx` — SSE 구독 useEffect 추가
- `eventsPipeline.ts` — `parseLogToWorldEvent()` 함수 추가
  - `tool_call` 로그 → `tool_called` 이벤트
  - `task_start` 로그 → `task_created` 이벤트
  - `task_complete` 로그 → `task_completed` 이벤트
  - `heartbeat` → `idle` 체크

#### 2-2. 세션 자동 Polling

```typescript
// 30초 간격 자동 polling
useEffect(() => {
  const interval = setInterval(() => {
    useAppStore.getState().loadSessions();
  }, 30_000);
  return () => clearInterval(interval);
}, []);
```

#### 2-3. Session Role/Name 변경 감지

```typescript
// sessionKey에 role, name 포함
const sessionKey = sessions.map(s => 
  `${s.session_id}:${s.status}:${s.role}:${s.session_name}`
).join('|');
```

### Phase 3: UX 개선 (후기)

#### 3-1. Character Picker 개선
- **Grid View**: 전체 212캐릭터를 6×N grid로 표시하는 별도 모달
- **Category Filter**: 시트별 or 색상별 필터
- **Random 버튼**: 랜덤 할당
- **에이전트 없이도 접근**: 설정 패널 or 에디터 내 탭

#### 3-2. Agent Roster 인터랙션
- 클릭 → 해당 에이전트 선택 + 카메라 팬
- 더블클릭 → 줌 + 프로필 패널
- 드래그 → 패널 크기 조절
- 상태별 정렬/필터

#### 3-3. 에이전트 행동 패턴 다양화
- **일과 시스템**: 시간대별 행동 변화 (아침=출근, 점심=카페, 저녁=귀가)
- **건물 친밀도**: 자주 가는 건물 가중치 증가
- **그룹 행동**: 같은 run의 에이전트끼리 모임
- **이동 다양화**: 직선 외 경유지 (공원 벤치, 분수대)

#### 3-4. 에디터 개선
- 건물 리사이즈 (드래그 핸들)
- 실내 가구 배치시 건물 선택 드롭다운
- 나무 좌표 클램핑 → 60×60 반영
- 충돌 표시 (겹침 경고)

#### 3-5. Missing Sprite 보충
- `terrain.dirt/path/sand/stone` → tileset에서 올바른 좌표 매핑
- `prop.rock/rock.small` → tileset에서 바위 스프라이트 추출

---

## 6. 구현 진행 상태

### Phase 1 — ✅ 완료 (2026-04-08)

| 항목 | 상태 | 변경 파일 |
|------|------|----------|
| E1: moving 플래그 역전 수정 | ✅ | eventsPipeline.ts, worldMap.ts |
| E2: ROLE_BUILDING_MAP 연결 | ✅ | eventsPipeline.ts, types.ts, Playground2DTab.tsx |
| R1: Agent Roster 클릭 + panToAgent | ✅ | worldMap.ts |
| C1: Character Picker 접근성 (via R1) | ✅ | worldMap.ts |
| W3: 에디터 좌표 클램핑 60×60 | ✅ | worldEditor.ts |

### Phase 2 — ✅ 완료 (2026-04-08)

| 항목 | 상태 | 변경 파일 |
|------|------|----------|
| P2-1: SSE 구독 (running sessions) | ✅ | Playground2DTab.tsx |
| P2-2: SSE log → WorldEvent 파싱 | ✅ | Playground2DTab.tsx |
| P2-3: 세션 자동 polling (30초) | ✅ | Playground2DTab.tsx |
| P2-bonus: sessionKey에 role/name 포함 | ✅ | Playground2DTab.tsx |

### Phase 3 — ✅ 완료 (2026-04-08)

| 항목 | 상태 | 변경 파일 |
|------|------|----------|
| P3-1: Missing sprites 보충 (dirt/path/sand/stone/rock) | ✅ | spriteManager.ts |
| P3-2: 도착 후 행동 개선 (20-45초 작업, 같은 건물 60% 재바인딩) | ✅ | avatarRuntime.ts |
| P3-3: Station claiming 검증 (per-frame rebuild 충분) | ✅ | — (변경 불필요) |
| P3-4: Agent Roster 정렬 (working 우선) + 호버 효과 | ✅ | worldMap.ts |

---

## 7. 구현 우선순위 로드맵

```
Week 1 (Phase 1):
  ├─ [P0] moving 로직 수정 → 에이전트가 실제로 건물로 이동
  ├─ [P0] ROLE_BUILDING_MAP 연결 → 역할별 건물 배정
  └─ [P0] Roster 클릭 → 에이전트 선택 + picker 접근성

Week 2 (Phase 2):
  ├─ [P1] SSE 구독 → 실시간 에이전트 활동 반영
  ├─ [P1] 세션 자동 polling (30초)
  └─ [P1] Session role/name 변경 감지

Week 3+ (Phase 3):
  ├─ [P2] Character Picker grid modal
  ├─ [P2] 에이전트 일과 시스템
  ├─ [P2] Missing sprite 보충
  └─ [P3] 에디터 고급 기능
```

---

## 7. 파일별 수정 필요 목록

| 파일 | Phase | 수정 내용 |
|------|-------|----------|
| `worldMap.ts` | 1 | `normalizeAvatars()` moving 수정, roster 클릭 |
| `eventsPipeline.ts` | 1+2 | role 기반 destination, SSE 이벤트 파싱 |
| `Playground2DTab.tsx` | 1+2 | role 전달, SSE 구독, 자동 polling |
| `avatarRuntime.ts` | 1 | 도착 후 행동, station claiming 개선 |
| `types.ts` | 1 | Agent에 role 필드 추가 |
| `worldEditor.ts` | 3 | 좌표 클램핑, 건물 선택 UI |
| `spriteManager.ts` | 3 | missing sprite candidates 추가 |
| `usePlayground2DStore.ts` | — | 완료 (avatar customization) |

---

## 8. 결론

현재 Playground 2D는 **렌더링 파이프라인은 완성도가 높으나, 실시간 데이터 연동과 에이전트 행동 로직에 근본적 결함**이 있다.

가장 심각한 3가지:
1. **`moving: !task`** — task 받은 에이전트가 움직이지 못함 (의도 반대)
2. **SSE 미연결** — 세션 실행 중 세부 이벤트가 Playground에 전달되지 않음
3. **역할 무시** — ROLE_BUILDING_MAP이 정의만 되고 사용되지 않아 모든 에이전트가 무작위 건물 방문

Phase 1 수정만으로도 에이전트가 자기 역할에 맞는 건물로 걸어가고, task에 따라 작업하는 모습을 볼 수 있게 된다. Phase 2에서 SSE를 연결하면 tool 호출, task 완료 등이 실시간으로 아바타 행동에 반영된다.
