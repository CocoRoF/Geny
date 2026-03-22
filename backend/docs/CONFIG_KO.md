# Config System

> 데이터클래스 기반 설정 관리 — 자동 탐색, DB+JSON 이중 저장, UI 스키마 자동 생성

## 아키텍처 개요

```
ConfigManager (싱글턴)
    │
    ├── 로드 우선순위:  캐시 → PostgreSQL → JSON 파일 → 기본값 생성
    ├── 저장:          PostgreSQL (primary) + JSON (backup)
    │
    ├── sub_config/
    │   ├── general/          ── APIConfig, LimitsConfig, LTMConfig, ...
    │   └── channels/         ── DiscordConfig, SlackConfig, ...
    │
    └── @register_config 데코레이터 + 자동 탐색 (pkgutil)
```

---

## 핵심 타입

### FieldType

| 값 | 설명 |
|----|------|
| `STRING` | 일반 텍스트 입력 |
| `PASSWORD` | 마스킹 입력 |
| `NUMBER` | 숫자 (min/max 지원) |
| `BOOLEAN` | 토글 |
| `SELECT` | 드롭다운 |
| `MULTISELECT` | 다중 선택 |
| `TEXTAREA` | 여러 줄 텍스트 |
| `URL` | URL 입력 (`http://` / `https://` 검증) |
| `EMAIL` | 이메일 (`@` 검증) |

### ConfigField

```python
@dataclass
class ConfigField:
    name: str                                      # 필드 식별자
    field_type: FieldType                          # UI 컨트롤 타입
    label: str                                     # 표시 라벨
    description: str = ""                          # 도움말 텍스트
    required: bool = False                         # 필수 여부
    default: Any = None                            # 기본값
    placeholder: str = ""                          # 입력 플레이스홀더
    options: List[Dict[str,str]] = []              # SELECT/MULTISELECT 옵션
    min_value: Optional[float] = None              # NUMBER 최솟값
    max_value: Optional[float] = None              # NUMBER 최댓값
    pattern: Optional[str] = None                  # 정규식 검증
    group: str = "general"                         # UI 그룹/섹션
    secure: bool = False                           # 마스킹 토글
    depends_on: Optional[str] = None               # 의존 필드 (옵션 필터링)
    apply_change: Optional[Callable] = None        # (old, new) 변경 콜백
```

---

## BaseConfig ABC

모든 설정 클래스의 추상 기반.

### 필수 구현 메서드

| 메서드 | 반환 | 설명 |
|--------|------|------|
| `get_config_name()` | `str` | 고유 식별자 (예: `"api"` → `api.json`) |
| `get_display_name()` | `str` | UI 표시명 |
| `get_description()` | `str` | 설정 카드 설명문 |
| `get_fields_metadata()` | `List[ConfigField]` | 필드 메타데이터 (UI 렌더링·검증) |

### 선택 오버라이드

| 메서드 | 기본값 | 설명 |
|--------|--------|------|
| `get_category()` | `"general"` | 카테고리 (폴더명과 일치) |
| `get_icon()` | `"settings"` | 프론트엔드 아이콘 |
| `get_i18n()` | `{}` | 국제화 번역 (`"ko"` 등) |

### 인스턴스 메서드

| 메서드 | 설명 |
|--------|------|
| `to_dict()` | 딕셔너리로 직렬화 |
| `validate()` → `List[str]` | 필드 검증, 에러 목록 반환 |
| `apply_field_changes(old_values)` | 변경된 필드의 `apply_change` 콜백 호출 |

### 클래스 메서드

| 메서드 | 설명 |
|--------|------|
| `from_dict(data)` | 딕셔너리에서 인스턴스 생성 (미지 필드 무시) |
| `get_default_instance()` | .env / 환경변수에서 기본값 로드 후 생성 |
| `get_schema()` | UI 빌드용 전체 스키마 딕셔너리 |

### 검증 규칙

- **required**: `None` 또는 빈 문자열이면 에러
- **NUMBER**: `min_value` / `max_value` 범위 확인
- **SELECT**: `options`에 포함된 값인지 확인
- **URL**: `http://` 또는 `https://` 시작
- **EMAIL**: `@` 포함
- **pattern**: 정규식 매칭

---

## @register_config 데코레이터

```python
_config_registry: Dict[str, Type[BaseConfig]] = {}

def register_config(cls):
    _config_registry[cls.get_config_name()] = cls
    return cls
```

클래스 임포트 시 자동 등록. **수동 등록 불필요** — `sub_config/` 안에 `*_config.py` 파일만 생성하면 됨.

### 자동 탐색

`sub_config/__init__.py`의 `_discover_configs()`:

1. `sub_config/` 하위 디렉토리 순회
2. 카테고리 패키지 임포트
3. `pkgutil.iter_modules`로 `*_config` 모듈 탐색·임포트
4. `@register_config` 발동 → 레지스트리 등록

---

## ConfigManager

스레드 안전 싱글턴. `RLock` 보호.

### 로드 우선순위 (`load_config`)

```
1. 인메모리 캐시 (_configs)
    ↓ miss
2. PostgreSQL DB (persistent_configs 테이블)
    ↓ miss
3. JSON 파일 (variables/*.json) — 발견 시 DB로 자동 마이그레이션
    ↓ miss
4. 기본값 생성 (get_default_instance()) → DB + JSON에 저장
```

### 저장 메커니즘 (`save_config`)

| 저장소 | 역할 |
|--------|------|
| PostgreSQL | **Primary** — 필드별 개별 행 (`config_name`, `config_key`, `config_value`, `data_type`) |
| JSON 파일 | **Backup** — `variables/{config_name}.json` |
| 인메모리 | **Cache** — 다음 조회 시 즉시 반환 |

### 주요 메서드

| 메서드 | 설명 |
|--------|------|
| `load_config(config_class)` | 우선순위 캐스케이드 로드 |
| `save_config(config)` | DB + JSON + 캐시에 저장 |
| `update_config(name, updates)` | 부분 업데이트 + 변경 감지 + 콜백 |
| `get_config(name)` | 이름으로 조회 |
| `get_config_value(name, field, default)` | 단일 필드 값 조회 |
| `get_all_configs()` | 전체 설정 목록 (스키마 + 값 + 검증) |
| `reload_all_configs()` | 캐시 무효화 + 전체 재로드 |
| `export_all_configs()` | 전체 백업 딕셔너리 |
| `import_configs(data)` | 백업에서 복원 |
| `migrate_all_to_db()` | JSON → DB 일괄 마이그레이션 |

### 글로벌 접근

```python
get_config_manager() → ConfigManager       # 지연 싱글턴
init_config_manager(config_dir, app_db)     # 커스텀 파라미터로 초기화
```

---

## env_utils — 환경변수 유틸리티

### 핵심 원칙

- `.env` 파일은 **읽기 전용 폴백** — 초기 기본값 설정용
- 설정 변경 시 `.env`에 쓰지 않음 — **Config JSON/DB가 진실의 원천**
- `os.environ`은 `env_sync` 콜백으로 실시간 갱신

### 함수

| 함수 | 설명 |
|------|------|
| `read_env(key)` | `.env` → `os.environ` → `None` 순서로 값 읽기 |
| `read_env_defaults(field_to_env, type_hints)` | `.env`에서 기본값 딕셔너리 구축 (자동 타입 캐스팅) |
| `env_sync(env_key)` | `apply_change` 콜백 팩토리 — 값 변경 시 `os.environ` 업데이트 |

### 사용 패턴

```python
@register_config
@dataclass
class MyConfig(BaseConfig):
    my_field: str = ""

    _ENV_MAP = {"my_field": "MY_ENV_VAR"}

    @classmethod
    def get_default_instance(cls):
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        return cls(**defaults)

    @staticmethod
    def get_fields_metadata():
        return [
            ConfigField(
                name="my_field",
                field_type=FieldType.STRING,
                label="My Field",
                apply_change=env_sync("MY_ENV_VAR"),
            )
        ]
```

---

## 전체 설정 클래스 목록

### General 카테고리

#### APIConfig (`"api"`)

| 필드 | 타입 | 기본값 | 환경변수 | 설명 |
|------|------|--------|---------|------|
| `anthropic_api_key` | PASSWORD | `""` | `ANTHROPIC_API_KEY` | Anthropic API 키 (required, secure) |
| `anthropic_model` | SELECT | `"claude-sonnet-4-6"` | `ANTHROPIC_MODEL` | 기본 Claude 모델 |
| `max_thinking_tokens` | NUMBER | `31999` | `MAX_THINKING_TOKENS` | Extended Thinking 예산 (0–128000) |
| `skip_permissions` | BOOLEAN | `True` | `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | 확인 대화상자 건너뛰기 |
| `app_port` | NUMBER | `8000` | `APP_PORT` | 백엔드 서버 포트 (1–65535) |

#### LimitsConfig (`"limits"`)

| 필드 | 타입 | 기본값 | 환경변수 | 설명 |
|------|------|--------|---------|------|
| `max_budget_usd` | NUMBER | `10.0` | `CLAUDE_MAX_BUDGET_USD` | 세션당 최대 API 비용 ($, 0–1000) |
| `max_turns` | NUMBER | `50` | `CLAUDE_MAX_TURNS` | 태스크당 최대 에이전트 턴 (1–500) |
| `bash_default_timeout_ms` | NUMBER | `30000` | `BASH_DEFAULT_TIMEOUT_MS` | 기본 bash 타임아웃 |
| `bash_max_timeout_ms` | NUMBER | `600000` | `BASH_MAX_TIMEOUT_MS` | 최대 bash 타임아웃 |
| `disallowed_tools` | STRING | `"ToolSearch"` | — | 비활성화할 Claude CLI 도구 (쉼표 구분) |

#### LTMConfig (`"ltm"`)

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `enabled` | BOOLEAN | `False` | FAISS 벡터 검색 활성화 |
| `embedding_provider` | SELECT | `"openai"` | 임베딩 제공자 (openai/google/anthropic) |
| `embedding_model` | SELECT | `"text-embedding-3-small"` | 모델 (`depends_on=embedding_provider`) |
| `embedding_api_key` | PASSWORD | `""` | API 키 |
| `chunk_size` | NUMBER | `1024` | 청크 크기 (128–4096) |
| `chunk_overlap` | NUMBER | `256` | 청크 겹침 (0–512) |
| `top_k` | NUMBER | `6` | 검색 결과 수 (1–30) |
| `score_threshold` | NUMBER | `0.35` | 최소 유사도 (0.0–1.0) |
| `max_inject_chars` | NUMBER | `10000` | 프롬프트 주입 최대 문자 (500–30000) |

#### LanguageConfig (`"language"`)

| 필드 | 타입 | 기본값 | 환경변수 | 설명 |
|------|------|--------|---------|------|
| `language` | SELECT | `"en"` | `GENY_LANGUAGE` | UI 언어 (en/ko) |

#### TelemetryConfig (`"telemetry"`)

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `disable_autoupdater` | BOOLEAN | `True` | 자동 업데이트 비활성화 |
| `disable_error_reporting` | BOOLEAN | `True` | 에러 리포팅 비활성화 |
| `disable_telemetry` | BOOLEAN | `True` | 텔레메트리 비활성화 |

#### GitHubConfig (`"github"`)

| 필드 | 타입 | 기본값 | 환경변수 | 설명 |
|------|------|--------|---------|------|
| `github_token` | PASSWORD | `""` | `GITHUB_TOKEN` + `GH_TOKEN` | PAT (secure, 양쪽 환경변수 동기화) |

#### SharedFolderConfig (`"shared_folder"`)

| 필드 | 타입 | 기본값 | 환경변수 | 설명 |
|------|------|--------|---------|------|
| `enabled` | BOOLEAN | `True` | `GENY_SHARED_FOLDER_ENABLED` | 공유 폴더 활성화 |
| `shared_folder_path` | STRING | `""` | `GENY_SHARED_FOLDER_PATH` | 절대 경로 (빈값 = `{STORAGE_ROOT}/_shared`) |
| `link_name` | STRING | `"_shared"` | `GENY_SHARED_FOLDER_LINK_NAME` | 세션 폴더 내 심볼릭 링크 이름 |

#### UserConfig (`"user"`)

| 필드 | 타입 | 기본값 | 환경변수 | 설명 |
|------|------|--------|---------|------|
| `user_name` | STRING | `""` | `GENY_USER_NAME` | 사용자 이름 |
| `user_title` | STRING | `""` | `GENY_USER_TITLE` | 직책/역할 |
| `department` | STRING | `""` | `GENY_USER_DEPARTMENT` | 부서/팀 |
| `description` | TEXTAREA | `""` | `GENY_USER_DESCRIPTION` | 자기소개/전문 분야 |

`get_user_context()` → 프롬프트에 주입할 사용자 정보 문자열 생성.

### Channels 카테고리

#### DiscordConfig (`"discord"`)

| 그룹 | 필드 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| connection | `enabled` | BOOLEAN | `False` | 활성화 |
| connection | `bot_token` | PASSWORD | `""` | 봇 토큰 |
| connection | `application_id` | STRING | `""` | 앱 ID |
| server | `guild_ids` | TEXTAREA | `[]` | 서버 ID 목록 |
| server | `allowed_channel_ids` | TEXTAREA | `[]` | 허용 채널 ID |
| server | `command_prefix` | STRING | `"!"` | 명령 접두사 |
| permissions | `admin_role_ids` | TEXTAREA | `[]` | 관리자 역할 ID |
| permissions | `allowed_user_ids` | TEXTAREA | `[]` | 허용 사용자 ID |
| behavior | `respond_to_mentions` | BOOLEAN | `True` | 멘션 응답 |
| behavior | `respond_to_dms` | BOOLEAN | `False` | DM 응답 |
| behavior | `auto_thread` | BOOLEAN | `True` | 스레드 자동 생성 |
| behavior | `max_message_length` | NUMBER | `2000` | 최대 메시지 길이 |
| session | `session_timeout_minutes` | NUMBER | `30` | 세션 타임아웃 (분) |
| session | `max_sessions_per_user` | NUMBER | `3` | 사용자당 최대 세션 |
| session | `default_prompt` | TEXTAREA | `""` | 기본 시스템 프롬프트 |

#### SlackConfig (`"slack"`)

| 그룹 | 필드 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| connection | `enabled` | BOOLEAN | `False` | 활성화 |
| connection | `bot_token` | PASSWORD | `""` | xoxb- 토큰 |
| connection | `app_token` | PASSWORD | `""` | xapp- 소켓 모드 토큰 |
| connection | `signing_secret` | PASSWORD | `""` | 서명 시크릿 |
| workspace | `workspace_id` | STRING | `""` | 워크스페이스 ID |
| workspace | `allowed_channel_ids` | TEXTAREA | `[]` | 채널 ID |
| workspace | `default_channel_id` | STRING | `""` | 기본 채널 |
| behavior | `respond_to_mentions` | BOOLEAN | `True` | 멘션 응답 |
| behavior | `respond_to_dms` | BOOLEAN | `True` | DM 응답 |
| behavior | `respond_in_thread` | BOOLEAN | `True` | 스레드 응답 |
| behavior | `use_blocks` | BOOLEAN | `True` | Block Kit 사용 |
| behavior | `max_message_length` | NUMBER | `4000` | 최대 메시지 길이 |
| commands | `enable_slash_commands` | BOOLEAN | `True` | 슬래시 명령 활성화 |
| commands | `slash_command_name` | STRING | `"/claude"` | 슬래시 명령 이름 |

#### TeamsConfig (`"teams"`)

| 그룹 | 필드 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| connection | `enabled` | BOOLEAN | `False` | 활성화 |
| connection | `app_id` | STRING | `""` | Microsoft App ID |
| connection | `app_password` | PASSWORD | `""` | 앱 비밀번호 |
| connection | `tenant_id` | STRING | `""` | Azure AD 테넌트 ID |
| connection | `bot_endpoint` | URL | `""` | 메시징 엔드포인트 URL |
| behavior | `use_adaptive_cards` | BOOLEAN | `True` | Adaptive Cards 사용 |
| behavior | `max_message_length` | NUMBER | `28000` | 최대 메시지 길이 |
| graph | `enable_graph_api` | BOOLEAN | `False` | Graph API 활성화 |
| graph | `graph_client_secret` | PASSWORD | `""` | Graph API 시크릿 |

#### KakaoConfig (`"kakao"`)

| 그룹 | 필드 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| connection | `enabled` | BOOLEAN | `False` | 활성화 |
| connection | `rest_api_key` | PASSWORD | `""` | REST API 키 |
| connection | `admin_key` | PASSWORD | `""` | 관리자 키 |
| connection | `bot_id` | STRING | `""` | 봇 ID |
| connection | `channel_public_id` | STRING | `""` | 채널 프로필 ID |
| skill_server | `skill_endpoint_path` | STRING | `"/api/kakao/skill"` | 스킬 엔드포인트 |
| callback | `use_callback` | BOOLEAN | `True` | AI 챗봇 콜백 사용 |
| response | `response_format` | SELECT | `"simpleText"` | 응답 형식 (simpleText/textCard) |
| response | `show_quick_replies` | BOOLEAN | `True` | 바로가기 버튼 표시 |
| response | `quick_reply_labels` | TEXTAREA | `["계속","새 대화","도움말"]` | 버튼 라벨 |

---

## REST API

라우터 접두사: `/api/config`

| Method | 엔드포인트 | 설명 |
|--------|-----------|------|
| `GET` | `/api/config` | 전체 설정 목록 (스키마 + 값 + 검증, 카테고리별 그룹) |
| `GET` | `/api/config/schemas` | 전체 스키마만 |
| `GET` | `/api/config/{name}` | 특정 설정 조회 |
| `PUT` | `/api/config/{name}` | 설정 업데이트 (`{"values": {...}}`) |
| `DELETE` | `/api/config/{name}` | 기본값으로 초기화 |
| `POST` | `/api/config/export` | 전체 백업 내보내기 |
| `POST` | `/api/config/import` | 백업 복원 (`{"configs": {...}}`) |
| `POST` | `/api/config/reload` | 전체 재로드 (캐시 무효화) |
| `GET` | `/api/config/{name}/validate` | 저장 없이 검증 |

---

## 설계 패턴

1. **진실의 원천**: Config DB/JSON — `.env`는 초기 기본값용 읽기 전용 폴백
2. **env_sync 콜백**: 설정 변경 → `os.environ` 즉시 갱신 (서비스 재시작 불필요)
3. **depends_on**: LTMConfig에서 `embedding_model` 옵션이 `embedding_provider` 값으로 필터링
4. **이중 저장**: DB primary + JSON backup — JSON에만 있으면 DB로 자동 마이그레이션
5. **i18n**: 모든 설정이 `get_i18n()`으로 한국어 번역 제공
6. **자동 탐색**: `sub_config/` 안에 `*_config.py` 파일 추가만으로 새 설정 등록 완료

---

## 관련 파일

```
service/config/
├── __init__.py              # 패키지 진입점, 자동 탐색 트리거
├── base.py                  # BaseConfig ABC, ConfigField, FieldType, @register_config
├── manager.py               # ConfigManager (싱글턴, 로드/저장/캐시/마이그레이션)
├── variables/               # 런타임 JSON 저장소 (자동 생성)
│   ├── api.json
│   ├── limits.json
│   └── ...
└── sub_config/
    ├── __init__.py           # auto-discovery walker
    ├── general/
    │   ├── api_config.py     # APIConfig
    │   ├── limits_config.py  # LimitsConfig
    │   ├── ltm_config.py     # LTMConfig
    │   ├── language_config.py
    │   ├── telemetry_config.py
    │   ├── github_config.py
    │   ├── shared_folder_config.py
    │   ├── user_config.py
    │   └── env_utils.py      # read_env, env_sync
    └── channels/
        ├── discord_config.py
        ├── slack_config.py
        ├── teams_config.py
        └── kakao_config.py

controller/config_controller.py  # REST API 라우터
```
