# VTuber 시스템 심층 분석 리포트

> 작성일: 2026-03-30
> 대상: VTuber 이중 에이전트 아키텍처의 사이드바 및 채팅 관련 치명적 버그

---

## 분석 대상 이슈

| # | 이슈 | 심각도 | 상태 |
|---|---|---|---|
| **BUG-1** | VTuber 세션 생성 시 Sub-Worker 세션이 사이드바에 함께 노출 | Critical | 미해결 |
| **BUG-2** | VTuber 탭에서 다른 탭으로 이동 후 복귀 시 채팅 내역 소실 | Critical | 미해결 |
| **BUG-3** | 탭 전환 시 SSE 연결 끊김 및 재연결 | Medium | 미해결 |
| **BUG-4** | 로그 패널 UI 상태(열림/높이) 탭 전환 시 초기화 | Low | 미해결 |

---

## BUG-1: Sub-Worker 세션 사이드바 노출 문제

### 1.1 현상
VTuber 역할로 세션을 생성하면 VTuber 세션과 함께 `{name}_sub` 세션도 사이드바에 표시됨.
사이드바 전체 카운터(전체/실행 중/오류)에도 Sub-Worker 세션이 포함됨.

### 1.2 관련 코드 흐름

#### 백엔드: 세션 생성
```
agent_session_manager.py:create_agent_session()
│
├─ (1) AgentSession 생성 → agent._session_type = None
├─ (2) _store.register() ← session_type=None 상태로 등록
├─ (3) request.session_type 있으면 agent._session_type 설정
├─ (4) _store.update() ← session_type='sub' 로 갱신
│
├─ (5) VTuber인 경우 Sub-Worker 세션 자동 생성 (재귀 호출)
│   └─ Sub-Worker의 CreateSessionRequest에 session_type='sub', linked_session_id 포함
│   └─ 재귀 호출 시 (3)-(4)에서 정상적으로 설정됨
│
└─ (6) VTuber 세션에 back-link 설정
    └─ _store.update(vtuber_id, { linked_session_id: sub_id, session_type: 'vtuber' })
```

#### 프론트엔드: 사이드바 필터
```typescript
// Sidebar.tsx: SidebarContent 내부
const visibleSessions = sessions.filter(
  s => !(s.session_type === 'sub' && s.linked_session_id)
);
```

#### 프론트엔드: 세션 목록 로드
```typescript
// useAppStore.ts
loadSessions: async () => {
  const sessions = await agentApi.list();  // GET /api/agents
  set({ sessions });  // 전체 교체
},
```

#### 백엔드: 세션 목록 API
```python
# agent_controller.py
@router.get("", response_model=List[SessionInfo])
async def list_agent_sessions():
    agents = agent_manager.list_agents()
    return [agent.get_session_info() for agent in agents]
```

### 1.3 근본 원인 분석

**원인 1: `get_session_info()` 호출 시점**

`list_agent_sessions()`는 라이브 에이전트 객체의 `get_session_info()` 를 호출.
이 메서드는 `agent._session_type`과 `agent._linked_session_id`를 읽어 반환함.

이 값들은 `create_agent_session()` 내에서 `register()` 이후에 설정됨:
- `agent._session_type = request.session_type`  (line 508)
- `agent._linked_session_id = request.linked_session_id` (line 506)

**정상 시나리오에서는 올바르게 작동해야 함.**

Sub-Worker 세션의 경우:
- `request.session_type = "sub"` → `agent._session_type = "sub"` ✅
- `request.linked_session_id = vtuber_id` → `agent._linked_session_id = vtuber_id` ✅

따라서 `agent.get_session_info()`는 `session_type="sub"`, `linked_session_id=vtuber_id`를 반환.
사이드바 필터는 `!(s.session_type === 'sub' && s.linked_session_id)` → 필터링됨 ✅

**그렇다면 왜 문제가 발생하는가?**

**원인 2: 세션이 이전 버전에서 생성됨 (가장 유력)**

`session_type`과 `linked_session_id` 필드 지원은 최근에 추가됨.
이전 버전에서 생성된 세션은 이 필드가 `null`/`None`으로 설정되어 있음.

확인 방법: 백엔드 서버를 재시작하면 기존 세션은 soft-delete되고 저장소에만 남음.
새로 생성된 세션에서 같은 문제가 발생하는지 확인 필요.

**원인 3: 백엔드 미재시작**

코드 변경 후 백엔드 서버를 재시작하지 않아 이전 코드가 실행 중일 수 있음.
이 경우 `session_type` 필드가 `_store.update()`로 저장되지 않거나,
`get_session_info()`에서 반환하지 않을 수 있음.

**원인 4: 프론트엔드 빌드 미반영**

프론트엔드 개발 서버가 HMR로 변경사항을 반영하지만,
`Sidebar.tsx`의 필터 코드가 실제로 실행 중인지 확인 필요.

### 1.4 추가 위험 요소

**서버 재시작 후 세션 복원 시:**
- `_store.update()`로 `session_type`은 저장되므로 store에는 존재
- `restore_session` 엔드포인트는 `get_creation_params()`로 `session_type` 복원 ✅
- 하지만 **자동 복원 없음** — 서버 재시작 시 세션은 soft-deleted 상태

### 1.5 해결 방안

#### 방안 A: 방어적 필터링 강화 (즉시 적용 가능)

`session_type` 필드에만 의존하지 말고, 세션 이름 패턴으로도 필터링:

```typescript
// Sidebar.tsx
const visibleSessions = sessions.filter(s => {
  // 명시적 Sub-Worker 타입 표시
  if (s.session_type === 'sub' && s.linked_session_id) return false;
  // session_type 미설정 레거시 세션의 경우 이름 패턴으로 판단
  if (s.role === 'worker' && s.linked_session_id && s.session_name?.endsWith('_sub')) return false;
  return true;
});
```

#### 방안 B: 백엔드에서 필터링 (권장)

API 응답에서 Sub-Worker 세션을 아예 제외:

```python
# agent_controller.py
@router.get("", response_model=List[SessionInfo])
async def list_agent_sessions(include_sub_workers: bool = False):
    agents = agent_manager.list_agents()
    result = [agent.get_session_info() for agent in agents]
    if not include_sub_workers:
        result = [s for s in result if not (s.session_type == "sub" and s.linked_session_id)]
    return result
```

#### 방안 C: 세션 생성 순서 변경

`_store.register()` 호출 시점에 이미 `session_type`을 포함시킴:

```python
# session_info에 먼저 설정
if request.session_type:
    agent._session_type = request.session_type
if request.linked_session_id:
    agent._linked_session_id = request.linked_session_id

session_info = agent.get_session_info()  # 이제 session_type 포함됨
self._store.register(session_id, session_info.model_dump(mode="json"))
# _store.update() 불필요
```

**권장: 방안 A + C 동시 적용**

---

## BUG-2: VTuber 채팅 내역 소실 (치명적)

### 2.1 현상
VTuber 탭에서 대화 진행 후 다른 탭(명령, 그래프 등)으로 이동했다가
VTuber 탭으로 돌아오면 채팅 내역이 완전히 사라짐.

### 2.2 근본 원인

#### 원인 1: 탭 시스템이 컴포넌트를 완전히 언마운트

```typescript
// TabContent.tsx
export default function TabContent() {
  const activeTab = useAppStore(s => s.activeTab);
  const Component = TAB_MAP[activeTab]; // ← 활성 탭의 컴포넌트만 렌더
  return (
    <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
      {Component ? <Component /> : <div>...</div>}
    </div>
  );
}
```

`TAB_MAP[activeTab]`로 **현재 탭의 컴포넌트만** 렌더링.
다른 탭으로 전환하면 이전 탭 컴포넌트는 **완전히 언마운트**됨.

#### 원인 2: 채팅 메시지가 컴포넌트 로컬 `useState`에 저장

```typescript
// VTuberChatPanel.tsx
export default function VTuberChatPanel({ sessionId }: { sessionId: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);  // ← 여기!
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
```

`messages`는 컴포넌트의 로컬 상태(`useState`)에만 존재.
컴포넌트가 언마운트되면 → state 파괴 → 채팅 내역 영구 소실.

#### 상태 생존 분석

| 상태 | 저장 위치 | 탭 전환 시 생존? |
|---|---|---|
| **채팅 메시지** | `useState` (VTuberChatPanel) | **❌ 소멸** |
| 채팅 입력 텍스트 | `useState` (VTuberChatPanel) | ❌ 소멸 |
| 전송 중 상태 | `useState` (VTuberChatPanel) | ❌ 소멸 |
| VTuber 로그 | `useVTuberStore` (Zustand) | ✅ 생존 |
| 아바타 상태 | `useVTuberStore` (Zustand) | ✅ 생존 |
| 모델 할당 | `useVTuberStore` (Zustand) | ✅ 생존 |
| SSE 구독 | `useEffect` cleanup | ❌ 해제/재연결 |
| 로그 패널 열림 | `useState` (VTuberTab) | ❌ 소멸 |
| 로그 패널 높이 | `useState` (VTuberTab) | ❌ 소멸 |

### 2.3 해결 방안

#### 방안 A: 채팅 메시지를 Zustand 스토어로 이동 (권장 ⭐)

`useVTuberStore`에 채팅 메시지 상태를 추가:

```typescript
// useVTuberStore.ts에 추가

interface VTuberState {
  // ... 기존 필드들
  chatMessages: Record<string, ChatMessage[]>;  // sessionId → messages
  chatSending: Record<string, boolean>;         // sessionId → sending

  // Actions
  addChatMessage: (sessionId: string, msg: ChatMessage) => void;
  setChatSending: (sessionId: string, sending: boolean) => void;
  clearChatMessages: (sessionId: string) => void;
}
```

`VTuberChatPanel`에서 `useState` 대신 스토어 읽기/쓰기:

```typescript
// VTuberChatPanel.tsx
const messages = useVTuberStore(s => s.chatMessages[sessionId] ?? []);
const sending = useVTuberStore(s => s.chatSending[sessionId] ?? false);
const addChatMessage = useVTuberStore(s => s.addChatMessage);
```

**장점:**
- 탭 전환 시 채팅 내역 보존
- 같은 세션을 다시 선택해도 이전 대화 유지
- 기존 로그 저장 패턴과 일관성 유지
- 변경 범위 최소화 (store 추가 + ChatPanel 수정)

#### 방안 B: 비활성 탭을 DOM에 유지 (CSS hidden)

`TabContent`에서 모든 탭을 렌더링하되 비활성 탭을 `display: none`으로 숨김:

```typescript
// TabContent.tsx
export default function TabContent() {
  const activeTab = useAppStore(s => s.activeTab);
  return (
    <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
      {Object.entries(TAB_MAP).map(([key, Component]) => (
        <div key={key} style={{ display: key === activeTab ? 'flex' : 'none' }}
             className="flex-1 min-h-0 flex-col">
          <Component />
        </div>
      ))}
    </div>
  );
}
```

**장점:**
- 모든 상태(채팅, SSE, 스크롤 위치) 완벽 보존
- 코드 변경 최소화

**단점:**
- 모든 탭이 항상 메모리에 존재 → 리소스 증가
- SSE 연결 등 부수 효과가 계속 실행
- Live2D Canvas가 비활성 상태에서도 렌더링 (성능)
- 모든 탭의 dynamic import가 한꺼번에 실행

#### 방안 C: 선택적 KeepAlive (최적 ⭐⭐)

VTuber 탭만 마운트 상태 유지하고 나머지는 기존처럼 조건부 렌더링:

```typescript
// TabContent.tsx
const KEEP_ALIVE_TABS = new Set(['vtuber']);

export default function TabContent() {
  const activeTab = useAppStore(s => s.activeTab);
  const [mountedTabs, setMountedTabs] = useState(new Set<string>());

  useEffect(() => {
    setMountedTabs(prev => new Set([...prev, activeTab]));
  }, [activeTab]);

  return (
    <div className="flex-1 min-h-0 overflow-hidden flex flex-col relative">
      {Object.entries(TAB_MAP).map(([key, Component]) => {
        const isActive = key === activeTab;
        const isKeepAlive = KEEP_ALIVE_TABS.has(key);
        const shouldMount = isActive || (isKeepAlive && mountedTabs.has(key));

        if (!shouldMount) return null;
        return (
          <div key={key}
               className={`absolute inset-0 flex flex-col ${isActive ? '' : 'invisible pointer-events-none'}`}>
            <Component />
          </div>
        );
      })}
    </div>
  );
}
```

**장점:**
- VTuber 탭만 유지하므로 리소스 영향 최소
- SSE 연결, Live2D Canvas, 채팅 상태 모두 보존
- 다른 탭은 영향 없음

**단점:**
- `invisible`일 때도 Live2D 애니메이션이 실행 (CPU/GPU)
- 약간 복잡한 로직

### 2.4 권장 해결 전략

**방안 A (Zustand 이동) + 방안 C (선택적 KeepAlive) 조합**

1. **채팅 메시지를 Zustand 스토어로 이동** → 핵심 데이터 보존
2. **VTuber 탭을 KeepAlive** → SSE 연결, Canvas, UI 상태 보존
3. KeepAlive 시 `visibility: hidden` 상태에서는 **requestAnimationFrame 일시정지** 처리

---

## BUG-3: 탭 전환 시 SSE 연결 끊김

### 3.1 현상
VTuber 탭을 떠나면 SSE 연결이 해제되고, 돌아오면 재연결.
그 사이에 발생한 아바타 상태 변경 이벤트를 놓침.

### 3.2 원인

```typescript
// VTuberTab.tsx
useEffect(() => {
  if (!sessionId || !assignedModelName) return;
  subscribeAvatar(sessionId);
  return () => unsubscribeAvatar(sessionId);  // ← 언마운트 시 SSE 해제
}, [sessionId, assignedModelName, subscribeAvatar, unsubscribeAvatar]);
```

VTuberTab이 언마운트되면 `useEffect` cleanup 함수가 실행 → SSE 해제.
재마운트 시 새 SSE 연결 생성.

### 3.3 해결 방안

SSE 구독/해제 로직을 VTuberTab 컴포넌트가 아닌 **스토어 레벨**로 이동:

```typescript
// useVTuberStore.ts에서 관리
// 세션 선택 시 subscribeAvatar() 호출
// 세션 삭제/해제 시에만 unsubscribeAvatar() 호출
// 탭 전환과 무관하게 연결 유지
```

또는 **방안 C (KeepAlive)**를 적용하면 자동으로 해결됨.

---

## BUG-4: 로그 패널 UI 상태 초기화

### 4.1 현상
로그 패널을 열어두고 높이를 조절한 뒤 다른 탭으로 갔다 오면
패널이 닫히고 높이가 기본값(180px)으로 초기화됨.

### 4.2 원인
```typescript
// VTuberTab.tsx
const [logsOpen, setLogsOpen] = useState(false);          // ← 컴포넌트 로컬
const [logHeight, setLogHeight] = useState(DEFAULT_LOG_HEIGHT);  // ← 컴포넌트 로컬
```

### 4.3 해결 방안
BUG-2의 KeepAlive 적용 시 자동 해결.
또는 `useVTuberStore`에 `logsOpen`, `logHeight`를 per-session으로 저장.

---

## 수정 계획

### Phase 1: 핵심 데이터 보존 (BUG-2 해결)

#### 1-1. `useVTuberStore`에 채팅 메시지 상태 추가

**파일:** `frontend/src/store/useVTuberStore.ts`

추가 필드:
```typescript
chatMessages: Record<string, ChatMessage[]>;
chatSending: Record<string, boolean>;
```

추가 액션:
```typescript
addChatMessage: (sessionId: string, msg: ChatMessage) => void;
setChatSending: (sessionId: string, sending: boolean) => void;
clearChatMessages: (sessionId: string) => void;
```

#### 1-2. `VTuberChatPanel`에서 스토어 사용

**파일:** `frontend/src/components/live2d/VTuberChatPanel.tsx`

- `useState<ChatMessage[]>([])` → `useVTuberStore(s => s.chatMessages[sessionId])`
- `setMessages(...)` → `addChatMessage(sessionId, msg)`
- `useState(false)` (sending) → `useVTuberStore(s => s.chatSending[sessionId])`

`ChatMessage` 인터페이스를 `types/index.ts`로 이동하여 공유.

### Phase 2: 컴포넌트 생존 (BUG-2, BUG-3, BUG-4 해결)

#### 2-1. TabContent에 선택적 KeepAlive 적용

**파일:** `frontend/src/components/TabContent.tsx`

VTuber 탭을 한 번 마운트한 후 언마운트하지 않고 CSS로 숨김 처리.
다른 탭은 기존처럼 조건부 렌더링 유지.

#### 2-2. SSE 구독 해제 로직 조건부 처리

**파일:** `frontend/src/components/tabs/VTuberTab.tsx`

KeepAlive 적용 시 `useEffect` cleanup에서 SSE 해제하지 않도록 변경.
또는 SSE 구독을 스토어 레벨로 이동하여 컴포넌트 생명주기와 분리.

### Phase 3: 사이드바 필터링 강화 (BUG-1 해결)

#### 3-1. 프론트엔드 방어적 필터링

**파일:** `frontend/src/components/Sidebar.tsx`

`session_type` 외에 이름 패턴/role + linked_session_id 조합으로 추가 필터링.

#### 3-2. 백엔드 세션 생성 순서 개선

**파일:** `backend/service/executor/agent_session_manager.py`

`_store.register()` 호출 전에 `session_type`, `linked_session_id` 설정.
이를 통해 레이스 컨디션 제거.

---

## 예상 변경 파일 목록

| 파일 | 변경 내용 | Phase |
|---|---|---|
| `frontend/src/store/useVTuberStore.ts` | 채팅 메시지 상태/액션 추가 | 1 |
| `frontend/src/components/live2d/VTuberChatPanel.tsx` | useState → 스토어 읽기/쓰기 | 1 |
| `frontend/src/types/index.ts` | `ChatMessage` 인터페이스 추가 | 1 |
| `frontend/src/components/TabContent.tsx` | VTuber 탭 KeepAlive 적용 | 2 |
| `frontend/src/components/tabs/VTuberTab.tsx` | SSE cleanup 조건 변경 | 2 |
| `frontend/src/components/Sidebar.tsx` | 방어적 Sub-Worker 필터링 | 3 |
| `backend/service/executor/agent_session_manager.py` | register 전 type 설정 | 3 |

---

## 우선순위

1. **BUG-2 (채팅 소실)** — 사용자 경험에 가장 치명적. Phase 1 + 2로 해결.
2. **BUG-1 (사이드바)** — 혼란 유발. Phase 3으로 해결.
3. **BUG-3 (SSE)** — Phase 2에서 자동 해결.
4. **BUG-4 (UI 상태)** — Phase 2에서 자동 해결.
