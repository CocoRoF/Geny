# Geny Admin Authentication System — 구현 계획서

## 1. 개요

### 1.1 목표
Geny에 **단일 관리자 인증 시스템**을 도입한다. 최초 사용자만 계정을 생성할 수 있고, 이후 모든 관리 기능은 로그인 상태에서만 접근 가능하다.

### 1.2 핵심 원칙
- **초기 유저 전용 계정 생성**: Users 테이블이 비어있을 때만 Create User 가능
- **단일 관리자 모델**: 계정은 1개만 존재 (추가 생성 불가)
- **인증 필수 영역**: Workflows, Tool Sets, Settings, Sessions 조작, Dev/Users 모드 전환, TTS 설정
- **인증 불필요 영역**: 기본 대시보드 조회, 공개 정보

---

## 2. 현재 상태 분석

### 2.1 현재 보안 상태
| 항목 | 상태 |
|------|------|
| 프론트엔드 인증 | ❌ 없음 |
| 백엔드 인증 | ❌ 없음 (141개 엔드포인트 전부 오픈) |
| Dev/User 전환 | localStorage 기반 클라이언트 사이드만 |
| Users 테이블 | ❌ 없음 |
| 미들웨어 | ❌ 비어있음 |

### 2.2 보호 대상 영역

**프론트엔드 탭/라우트:**
| 영역 | 현재 접근 제어 | 변경 후 |
|------|--------------|--------|
| Workflows 탭 | devMode === true | **로그인 + devMode** |
| Tool Sets 탭 | devMode === true | **로그인 + devMode** |
| Settings 탭 | devMode === true | **로그인 + devMode** |
| Sessions 생성/삭제/복구 | 제한 없음 | **로그인 필수** |
| Dev/Users 모드 전환 | 제한 없음 | **로그인 필수** |
| TTS Studio (/tts-voice) | 제한 없음 | **로그인 필수** |
| TTS Voice 설정 | 제한 없음 | **로그인 필수** |

**백엔드 API 엔드포인트 (보호 대상):**
| 그룹 | 엔드포인트 패턴 | 보호 방식 |
|------|---------------|----------|
| Sessions CRUD | POST/DELETE /api/agents/* | JWT 토큰 검증 |
| Workflows CRUD | ALL /api/workflows/* | JWT 토큰 검증 |
| Tool Presets CRUD | ALL /api/tool-presets/* | JWT 토큰 검증 |
| Config 수정 | PUT/DELETE /api/config/* | JWT 토큰 검증 |
| TTS 프로필 관리 | POST/PUT/DELETE /api/tts/profiles/* | JWT 토큰 검증 |
| TTS 세션 프로필 | PUT/DELETE /api/tts/agents/*/profile | JWT 토큰 검증 |

**보호하지 않는 엔드포인트 (읽기 전용):**
| 그룹 | 엔드포인트 패턴 | 이유 |
|------|---------------|------|
| Sessions 목록/조회 | GET /api/agents, GET /api/agents/{id} | 대시보드 표시용 |
| Config 조회 | GET /api/config/* | 설정값 읽기 |
| TTS 조회 | GET /api/tts/voices, GET /api/tts/engines | 정보 조회 |
| VTuber 조회 | GET /api/vtuber/* | 아바타 표시용 |
| Health/Status | GET /api/agents/health | 모니터링 |
| Auth 자체 | ALL /api/auth/* | 인증 수행용 |

---

## 3. 아키텍처 설계

### 3.1 인증 흐름 다이어그램

```
┌──────────────────────────────────────────────────────┐
│                    시작 (앱 로드)                       │
└──────────────┬───────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  GET /api/auth/status            │
│  → { has_users, is_authenticated }│
└──────────────┬───────────────────┘
               │
        ┌──────┴──────┐
        │             │
   has_users=false  has_users=true
        │             │
        ▼             ▼
┌──────────────┐ ┌──────────────────┐
│ /setup 페이지  │ │ is_authenticated? │
│ (계정 생성)    │ └───────┬──────────┘
└──────┬───────┘    ┌────┴─────┐
       │          Yes          No
       │            │           │
       ▼            ▼           ▼
┌──────────────┐ ┌────────┐ ┌────────────┐
│ POST         │ │ 대시보드 │ │ Login 모달  │
│ /api/auth/   │ │ (Full)  │ │ (제한 모드)  │
│ setup        │ └────────┘ └──────┬─────┘
└──────┬───────┘                    │
       │            POST /api/auth/login
       ▼                    │
  자동 로그인                  ▼
       │            ┌────────────┐
       └───────────→│ JWT 발급    │
                    │ → 쿠키 저장  │
                    └──────┬─────┘
                           │
                           ▼
                    ┌────────────────┐
                    │ 대시보드 (Full)   │
                    │ 보호 기능 활성화   │
                    └────────────────┘
```

### 3.2 미인증 상태에서의 제한

```
┌─────────────────────────────────────────────────┐
│              미인증 (Guest) 모드                   │
├─────────────────────────────────────────────────┤
│ ✅ 허용:                                         │
│   - 대시보드 조회 (Sessions 목록 보기)              │
│   - Main 탭, Playground 탭                       │
│   - SharedFolder 탭 (읽기)                       │
│   - VTuber 탭 (조회)                              │
│   - Session 정보 조회 (InfoTab, LogsTab 등)       │
│                                                 │
│ 🔒 차단 (Login 버튼 → 로그인 모달):                │
│   - Sessions 생성/삭제/복구                        │
│   - Dev/Users 모드 전환 토글                       │
│   - Workflows 탭 진입                             │
│   - Tool Sets 탭 진입                             │
│   - Settings 탭 진입                              │
│   - TTS Studio 진입 (/tts-voice)                  │
│   - TTS 프로필 수정                                │
│   - Config 수정                                   │
└─────────────────────────────────────────────────┘
```

### 3.3 컴포넌트 구조

```
Backend (새로 생성)
├── service/auth/
│   ├── __init__.py
│   ├── auth_service.py          # 핵심 인증 로직
│   ├── auth_models.py           # Pydantic 요청/응답 모델
│   └── auth_middleware.py       # FastAPI 의존성 (require_auth)
├── service/database/models/
│   └── admin_user.py            # AdminUser DB 모델 (NEW)
└── controller/
    └── auth_controller.py       # /api/auth/* 라우터 (NEW)

Frontend (새로 생성/수정)
├── src/store/
│   └── useAuthStore.ts          # 인증 상태 관리 (NEW)
├── src/lib/
│   └── authApi.ts               # Auth API 클라이언트 (NEW)
├── src/components/
│   ├── auth/
│   │   ├── LoginModal.tsx       # 로그인 모달 (NEW)
│   │   ├── SetupPage.tsx        # 초기 계정 생성 페이지 (NEW)
│   │   └── AuthGuard.tsx        # 인증 보호 래퍼 (NEW)
│   ├── Header.tsx               # Dev/User 토글에 인증 체크 추가 (MODIFY)
│   ├── Sidebar.tsx              # Sessions CRUD에 인증 체크 추가 (MODIFY)
│   └── TabNavigation.tsx        # 탭 접근에 인증 체크 추가 (MODIFY)
├── src/app/
│   ├── page.tsx                 # AuthGuard 래핑 (MODIFY)
│   ├── setup/page.tsx           # 초기 설정 페이지 (NEW)
│   └── tts-voice/page.tsx       # 인증 체크 추가 (MODIFY)
```

---

## 4. 상세 구현 설계

### 4.1 백엔드 — Database Model

#### `AdminUserModel` (admin_users 테이블)
```python
class AdminUserModel(BaseModel):
    """Admin user account model."""

    def get_table_name(self) -> str:
        return "admin_users"

    def get_schema(self) -> Dict[str, str]:
        return {
            "username": "VARCHAR(100) NOT NULL UNIQUE",
            "password_hash": "VARCHAR(255) NOT NULL",
            "display_name": "VARCHAR(200) DEFAULT ''",
            "last_login_at": "TIMESTAMP",
        }

    def get_indexes(self) -> List[tuple]:
        return [("idx_admin_users_username", "username")]
```

> **설계 결정**: admin_users는 별도 테이블. 기존 sessions/config와 분리하여 권한 관리 독립성 확보.

### 4.2 백엔드 — Auth Service

```python
# service/auth/auth_service.py

class AuthService:
    """Singleton auth service managing admin user lifecycle."""

    def __init__(self, app_db: AppDatabaseManager):
        self.app_db = app_db
        self.SECRET_KEY = os.getenv("GENY_AUTH_SECRET", self._generate_secret())
        self.ALGORITHM = "HS256"
        self.TOKEN_EXPIRE_HOURS = 24

    async def has_users(self) -> bool:
        """Check if any admin user exists."""
        users = self.app_db.find_all(AdminUserModel)
        return len(users) > 0

    async def setup(self, username: str, password: str, display_name: str) -> dict:
        """
        Create initial admin user.
        FAILS if any user already exists (critical security check).
        """
        if await self.has_users():
            raise HTTPException(403, "Setup already completed. Cannot create additional users.")

        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user = AdminUserModel(
            username=username,
            password_hash=password_hash,
            display_name=display_name or username,
        )
        self.app_db.insert(user)
        return self._create_token(username)

    async def login(self, username: str, password: str) -> dict:
        """Authenticate and return JWT token."""
        users = self.app_db.find_by_condition(AdminUserModel, {"username": username})
        if not users:
            raise HTTPException(401, "Invalid credentials")

        user = users[0]
        if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            raise HTTPException(401, "Invalid credentials")

        # Update last login
        self.app_db.update_record("admin_users", user.id, {"last_login_at": datetime.now()})
        return self._create_token(username)

    def verify_token(self, token: str) -> dict:
        """Verify JWT token and return payload."""
        payload = jwt.decode(token, self.SECRET_KEY, algorithms=[self.ALGORITHM])
        return payload

    def _create_token(self, username: str) -> dict:
        """Generate JWT with expiry."""
        expire = datetime.utcnow() + timedelta(hours=self.TOKEN_EXPIRE_HOURS)
        token = jwt.encode(
            {"sub": username, "exp": expire},
            self.SECRET_KEY, algorithm=self.ALGORITHM
        )
        return {"access_token": token, "token_type": "bearer", "username": username}
```

### 4.3 백엔드 — Auth Middleware (FastAPI Dependency)

```python
# service/auth/auth_middleware.py

from fastapi import Depends, HTTPException, Request

async def require_auth(request: Request) -> dict:
    """
    FastAPI dependency to require authentication.
    Extracts JWT from:
      1. Authorization: Bearer <token> header
      2. geny_auth_token cookie
    """
    token = None

    # 1. Try Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]

    # 2. Try cookie
    if not token:
        token = request.cookies.get("geny_auth_token")

    if not token:
        raise HTTPException(401, "Authentication required")

    auth_service = get_auth_service()
    try:
        payload = auth_service.verify_token(token)
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
```

**적용 방식 — 기존 컨트롤러에 최소 침습적 적용:**
```python
# 기존 엔드포인트에 의존성 추가 (예: agent_controller.py)
@router.post("")
async def create_agent(request: CreateAgentRequest, auth: dict = Depends(require_auth)):
    # 기존 로직 그대로 — auth가 통과해야 실행됨
    ...

# 읽기 전용은 변경 없음
@router.get("")
async def list_agents():
    # 인증 없이 접근 가능 (기존 그대로)
    ...
```

### 4.4 백엔드 — Auth Controller

```python
# controller/auth_controller.py
# 새로운 라우터: /api/auth/*

router = APIRouter(prefix="/api/auth", tags=["auth"])

@router.get("/status")
async def get_auth_status(request: Request):
    """
    앱 초기 로드 시 호출.
    Returns:
        has_users: bool      — 유저가 존재하는지
        is_authenticated: bool — 현재 요청이 인증된 상태인지
        username: str | null — 인증된 경우 사용자명
    """

@router.post("/setup")
async def setup_admin(request: SetupRequest):
    """
    초기 관리자 계정 생성.
    조건: has_users === false 일 때만 동작.
    """

@router.post("/login")
async def login(request: LoginRequest):
    """
    로그인 → JWT 토큰 발급.
    토큰은 응답 body + Set-Cookie 양쪽으로 전달.
    """

@router.post("/logout")
async def logout():
    """
    로그아웃 → 쿠키 제거.
    """

@router.get("/me")
async def get_me(auth: dict = Depends(require_auth)):
    """
    현재 인증된 사용자 정보.
    """
```

### 4.5 보호 대상 엔드포인트 상세

#### 보호 추가할 엔드포인트 (Depends(require_auth) 적용):

**agent_controller.py:**
```
POST   /api/agents                    ← 세션 생성
PUT    /api/agents/{id}/system-prompt ← 시스템 프롬프트 수정
DELETE /api/agents/{id}               ← 세션 삭제
DELETE /api/agents/{id}/permanent     ← 영구 삭제
POST   /api/agents/{id}/restore       ← 세션 복구
PUT    /api/agents/{id}/thinking-trigger ← 설정 수정
POST   /api/agents/{id}/invoke        ← 실행
POST   /api/agents/{id}/execute       ← 실행
POST   /api/agents/{id}/execute/start ← 실행 시작
POST   /api/agents/{id}/stop          ← 실행 중지
POST   /api/agents/{id}/upgrade       ← 업그레이드
```

**workflow_controller.py:**
```
POST   /api/workflows                 ← 생성
PUT    /api/workflows/{id}            ← 수정
DELETE /api/workflows/{id}            ← 삭제
POST   /api/workflows/{id}/clone      ← 복제
POST   /api/workflows/{id}/execute    ← 실행
```

**tool_preset_controller.py:**
```
POST   /api/tool-presets              ← 생성
PUT    /api/tool-presets/{id}         ← 수정
DELETE /api/tool-presets/{id}         ← 삭제
POST   /api/tool-presets/{id}/clone   ← 복제
```

**config_controller.py:**
```
PUT    /api/config/{name}             ← 설정 수정
DELETE /api/config/{name}             ← 설정 초기화
POST   /api/config/import             ← 설정 가져오기
POST   /api/config/reload             ← 설정 리로드
```

**tts_controller.py:**
```
POST   /api/tts/profiles              ← 프로필 생성
PUT    /api/tts/profiles/{name}       ← 프로필 수정
DELETE /api/tts/profiles/{name}       ← 프로필 삭제
POST   /api/tts/profiles/{name}/ref   ← 레퍼런스 추가
DELETE /api/tts/profiles/{name}/ref/* ← 레퍼런스 삭제
PUT    /api/tts/profiles/{name}/ref/* ← 레퍼런스 수정
POST   /api/tts/profiles/{name}/activate ← 프로필 활성화
PUT    /api/tts/agents/{id}/profile   ← 세션 프로필 할당
DELETE /api/tts/agents/{id}/profile   ← 세션 프로필 해제
```

**shared_folder_controller.py:**
```
POST   /api/shared-folder/files       ← 파일 쓰기
DELETE /api/shared-folder/files/*     ← 파일 삭제
POST   /api/shared-folder/upload      ← 파일 업로드
POST   /api/shared-folder/directory   ← 디렉토리 생성
```

---

### 4.6 프론트엔드 — Auth Store (Zustand)

```typescript
// src/store/useAuthStore.ts

interface AuthState {
  // 상태
  isAuthenticated: boolean;
  hasUsers: boolean;
  username: string | null;
  isLoading: boolean;      // 초기 상태 확인 중

  // 액션
  checkAuthStatus: () => Promise<void>;   // GET /api/auth/status
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  setup: (username: string, password: string, displayName?: string) => Promise<boolean>;
}
```

**인증 상태 흐름:**
```
App 시작
  │
  ▼
checkAuthStatus() → GET /api/auth/status
  │
  ├─ { has_users: false } → isAuthenticated=false, hasUsers=false
  │   → Setup 페이지로 리다이렉트
  │
  ├─ { has_users: true, is_authenticated: false } → 제한 모드
  │   → Login 버튼 표시, 보호 기능 비활성화
  │
  └─ { has_users: true, is_authenticated: true, username: "admin" }
      → isAuthenticated=true, 전체 기능 활성화
```

### 4.7 프론트엔드 — Login Modal

```
┌───────────────────────────────────────┐
│              🔐 Admin Login           │
│                                       │
│  ┌─────────────────────────────────┐  │
│  │  Username                       │  │
│  └─────────────────────────────────┘  │
│  ┌─────────────────────────────────┐  │
│  │  Password                       │  │
│  └─────────────────────────────────┘  │
│                                       │
│  ┌──────────────────────────┐         │
│  │       Login              │         │
│  └──────────────────────────┘         │
│                                       │
│  ❌ Invalid credentials (에러 시)      │
└───────────────────────────────────────┘
```

- Header의 새로운 Login 버튼 클릭 시 표시
- 보호 기능 접근 시도 시 자동 표시
- 로그인 성공 시 자동 닫힘 + 상태 갱신

### 4.8 프론트엔드 — Setup Page (/setup)

```
┌───────────────────────────────────────────────────┐
│                                                   │
│       ██████╗ ███████╗███╗   ██╗██╗   ██╗        │
│      ██╔════╝ ██╔════╝████╗  ██║╚██╗ ██╔╝        │
│      ██║  ███╗█████╗  ██╔██╗ ██║ ╚████╔╝         │
│      ██║   ██║██╔══╝  ██║╚██╗██║  ╚██╔╝          │
│      ╚██████╔╝███████╗██║ ╚████║   ██║           │
│       ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝          │
│                                                   │
│          Initial Admin Account Setup              │
│                                                   │
│  ┌─────────────────────────────────────────────┐  │
│  │  Username                                   │  │
│  └─────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────┐  │
│  │  Display Name (optional)                    │  │
│  └─────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────┐  │
│  │  Password                                   │  │
│  └─────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────┐  │
│  │  Confirm Password                           │  │
│  └─────────────────────────────────────────────┘  │
│                                                   │
│  ┌─────────────────────────────────┐              │
│  │     Create Admin Account        │              │
│  └─────────────────────────────────┘              │
│                                                   │
│  ⚠️ This can only be done once.                   │
│  The first account becomes the admin.             │
└───────────────────────────────────────────────────┘
```

**보안 조건:**
- 서버에 유저가 0명일 때만 이 페이지 표시
- 유저가 1명 이상이면 자동으로 메인 페이지로 리다이렉트
- 프론트엔드 + 백엔드 양쪽에서 이중 검증

### 4.9 프론트엔드 — UI 변경 요약

#### Header.tsx 변경:
```
[기존]  Dev/User Toggle | TTS Studio | TTS Voice | Wiki
[변경]  Login/Logout 버튼 | Dev/User Toggle(인증시만) | TTS Studio(인증시만) | TTS Voice(인증시만) | Wiki
```

- 미인증 시: `🔒 Login` 버튼 표시
- 인증 시: `👤 {username}` + `Logout` 버튼 표시
- Dev/User 토글: 인증된 경우에만 표시/활성화
- TTS 버튼들: 인증된 경우에만 활성화 (클릭 시 로그인 모달)

#### TabNavigation.tsx 변경:
```
[기존]  devMode 기반 탭 필터링
[변경]  devMode + isAuthenticated 기반 탭 필터링
```

```typescript
// 기존
const DEV_ONLY_GLOBAL = new Set(['workflows', 'toolSets', 'settings']);

// 변경: 인증 필요 탭 추가 정의
const AUTH_REQUIRED_GLOBAL = new Set(['workflows', 'toolSets', 'settings']);

// 필터링 로직
const visibleGlobalTabs = GLOBAL_TAB_IDS.filter(id => {
  if (AUTH_REQUIRED_GLOBAL.has(id)) return isAuthenticated && devMode;
  if (DEV_ONLY_GLOBAL.has(id)) return devMode;
  return true;
});
```

#### Sidebar.tsx 변경:
```
- Create Session 버튼: 인증 필요 (미인증 시 로그인 모달)
- Delete Session 버튼: 인증 필요
- Restore Session 버튼: 인증 필요
```

#### page.tsx (메인 대시보드) 변경:
```
- 앱 로드 시 checkAuthStatus() 호출
- has_users === false → /setup 리다이렉트
```

#### tts-voice/page.tsx 변경:
```
- 페이지 로드 시 인증 체크
- 미인증 → 메인으로 리다이렉트 + "로그인 필요" 안내
```

---

## 5. 보안 설계

### 5.1 비밀번호 보안
- **해싱**: bcrypt (salt 자동 생성, rounds=12)
- **전송**: HTTPS 환경에서만 평문 전송 (production), 개발환경은 HTTP 허용
- **저장**: password_hash만 DB에 저장, 원문은 절대 저장하지 않음

### 5.2 토큰 보안
- **형식**: JWT (HS256)
- **만료**: 24시간 (설정 가능)
- **시크릿 키**: 환경변수 `GENY_AUTH_SECRET` (없으면 자동 생성 후 파일 저장)
- **저장**:
  - Cookie: `geny_auth_token` (HttpOnly=false — JS에서 읽어야 하므로, SameSite=Lax)
  - localStorage: `geny_auth_token` (백업)
- **전달**:
  - API 호출 시: `Authorization: Bearer <token>` 헤더
  - 쿠키 자동 전달

### 5.3 Setup 보안 (가장 중요)
```
POST /api/auth/setup 엔드포인트 보안:

1. DB 조회: admin_users 테이블 행 수 확인
2. count > 0 이면 → 즉시 403 Forbidden 반환
3. count === 0 이면 → 계정 생성 진행
4. 생성 후 → 자동 JWT 발급

* Race condition 방지:
  - DB INSERT 시 UNIQUE constraint on username
  - 서버 측에서 has_users 체크 후 즉시 INSERT (원자적)
```

### 5.4 CORS 설정
- 기존: 모든 Origin 허용 (변경 없음 — 로컬 개발 환경 특성)
- JWT 검증이 CORS 부재를 보상

---

## 6. 구현 순서 (단계별)

### Phase 1: 백엔드 인증 인프라 (가장 먼저)
1. `AdminUserModel` 생성 → APPLICATION_MODELS에 등록
2. `auth_service.py` 구현 (has_users, setup, login, verify)
3. `auth_middleware.py` 구현 (require_auth dependency)
4. `auth_controller.py` 구현 (/api/auth/* 라우터)
5. `main.py`에 auth 라우터 등록
6. requirements.txt에 `bcrypt`, `PyJWT` 추가

### Phase 2: 기존 컨트롤러에 인증 적용
7. `agent_controller.py` — 쓰기 엔드포인트에 `Depends(require_auth)` 추가
8. `workflow_controller.py` — 쓰기 엔드포인트에 적용
9. `tool_preset_controller.py` — 쓰기 엔드포인트에 적용
10. `config_controller.py` — 쓰기 엔드포인트에 적용
11. `tts_controller.py` — 프로필 관리 엔드포인트에 적용
12. `shared_folder_controller.py` — 쓰기 엔드포인트에 적용

### Phase 3: 프론트엔드 인증 인프라
13. `authApi.ts` — API 클라이언트 구현
14. `useAuthStore.ts` — Zustand 스토어 구현
15. API 인터셉터/래퍼에 토큰 자동 첨부 로직 추가

### Phase 4: 프론트엔드 UI 구현
16. `LoginModal.tsx` — 로그인 모달 컴포넌트
17. `SetupPage.tsx` (/setup) — 초기 설정 페이지
18. `AuthGuard.tsx` — 인증 보호 래퍼

### Phase 5: 기존 컴포넌트 수정
19. `Header.tsx` — Login/Logout 버튼, Dev 토글 인증 체크
20. `TabNavigation.tsx` — 탭 접근 인증 체크
21. `Sidebar.tsx` — Sessions CRUD 인증 체크
22. `page.tsx` — 초기 auth status 체크 + setup 리다이렉트
23. `tts-voice/page.tsx` — 인증 체크 추가

### Phase 6: 통합 테스트
24. 초기 상태 (유저 없음) → Setup 페이지 동작 확인
25. 계정 생성 후 → Setup 차단 확인
26. 미인증 상태 → 보호 기능 차단 확인
27. 로그인 → 전체 기능 활성화 확인
28. 토큰 만료 → 재로그인 요구 확인

---

## 7. 의존성 추가

### Backend (requirements.txt)
```
bcrypt>=4.0.0           # 비밀번호 해싱
PyJWT>=2.8.0            # JWT 토큰 생성/검증
```

### Frontend (package.json)
- 추가 패키지 없음 (fetch API + 기존 Zustand로 충분)

---

## 8. 파일 변경 목록 (총 20+ 파일)

### 신규 파일 (10개)
| 파일 | 설명 |
|------|------|
| `backend/service/database/models/admin_user.py` | AdminUser DB 모델 |
| `backend/service/auth/__init__.py` | Auth 모듈 초기화 |
| `backend/service/auth/auth_service.py` | 인증 핵심 로직 |
| `backend/service/auth/auth_models.py` | 요청/응답 스키마 |
| `backend/service/auth/auth_middleware.py` | require_auth 의존성 |
| `backend/controller/auth_controller.py` | /api/auth/* 라우터 |
| `frontend/src/lib/authApi.ts` | Auth API 클라이언트 |
| `frontend/src/store/useAuthStore.ts` | Auth Zustand 스토어 |
| `frontend/src/components/auth/LoginModal.tsx` | 로그인 모달 |
| `frontend/src/app/setup/page.tsx` | 초기 설정 페이지 |

### 수정 파일 (10+개)
| 파일 | 변경 내용 |
|------|----------|
| `backend/service/database/models/__init__.py` | AdminUserModel 등록 |
| `backend/requirements.txt` | bcrypt, PyJWT 추가 |
| `backend/main.py` | auth_router 등록, AuthService 초기화 |
| `backend/controller/agent_controller.py` | 쓰기 엔드포인트에 require_auth |
| `backend/controller/workflow_controller.py` | 쓰기 엔드포인트에 require_auth |
| `backend/controller/tool_preset_controller.py` | 쓰기 엔드포인트에 require_auth |
| `backend/controller/config_controller.py` | 쓰기 엔드포인트에 require_auth |
| `backend/controller/tts_controller.py` | 프로필 관리에 require_auth |
| `backend/controller/shared_folder_controller.py` | 쓰기에 require_auth |
| `frontend/src/components/Header.tsx` | Login/Logout, Dev 토글 인증 |
| `frontend/src/components/TabNavigation.tsx` | 탭 인증 필터링 |
| `frontend/src/components/Sidebar.tsx` | Sessions CRUD 인증 |
| `frontend/src/app/page.tsx` | Auth 초기화 + 리다이렉트 |
| `frontend/src/app/tts-voice/page.tsx` | 인증 체크 |
| `frontend/src/lib/api.ts` | 토큰 자동 첨부 |

---

## 9. 엣지 케이스 & 고려사항

### 9.1 DB 연결 실패 시
- Auth도 PostgreSQL에 의존 → DB 없으면 인증 불가
- **정책**: DB 없으면 모든 보호 기능 비활성화 (파일 모드에서는 인증 미적용)
- 이유: 로컬 개발 환경에서 DB 없이도 기본 기능 사용 가능해야 함

### 9.2 토큰 만료
- JWT 만료 시 401 응답 → 프론트엔드에서 자동 로그인 모달 표시
- 만료된 상태에서 보호 탭에 있으면 → Main 탭으로 이동 + 로그인 유도

### 9.3 브라우저 탭 간 동기화
- localStorage의 `geny_auth_token` 변경 감지 (storage event)
- 한 탭에서 로그아웃 → 다른 탭도 즉시 반영

### 9.4 비밀번호 분실
- 단일 관리자 모델이므로 비밀번호 재설정 UI 없음
- **복구 방법**: DB에서 직접 admin_users 레코드 삭제 → Setup 페이지 다시 활성화
- 이 복구 방법은 서버 접근 권한이 있는 사람만 가능 (의도된 보안)

### 9.5 환경변수
```bash
# .env에 추가 (선택사항)
GENY_AUTH_SECRET=your-secret-key-here    # JWT 서명 키. 미설정 시 자동 생성
GENY_AUTH_TOKEN_HOURS=24                 # 토큰 유효 시간 (기본 24시간)
```
