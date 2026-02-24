# Sub-Config 구성 정책

## 개요

Claude Control의 모든 설정 클래스는 `sub_config/` 디렉토리 아래 **카테고리 기반 폴더 구조**로 관리됩니다. 각 폴더 이름이 곧 Settings UI에 표시되는 **카테고리 이름**이 됩니다.

## 디렉토리 구조

```
service/config/
├── base.py                  # BaseConfig, ConfigField, FieldType, @register_config
├── manager.py               # ConfigManager (로드/저장/검증)
├── __init__.py              # 패키지 진입점 (자동 탐색 트리거)
├── variables/               # 런타임 JSON 저장소 (자동 생성, 직접 수정 금지)
│   ├── discord.json
│   ├── slack.json
│   └── teams.json
└── sub_config/              # 모든 설정 정의가 위치하는 곳
    ├── __init__.py           # 자동 탐색 메커니즘
    └── <카테고리명>/          # 폴더명 = 카테고리명
        ├── __init__.py       # 카테고리 설명 (선택사항)
        └── <이름>_config.py  # 파일당 하나의 설정 클래스
```

### 예시

```
sub_config/
├── channels/                 # 카테고리: "channels"
│   ├── __init__.py
│   ├── discord_config.py     # DiscordConfig
│   ├── slack_config.py       # SlackConfig
│   └── teams_config.py       # TeamsConfig
├── security/                 # 카테고리: "security"
│   ├── __init__.py
│   └── auth_config.py        # AuthConfig
└── general/                  # 카테고리: "general"
    ├── __init__.py
    └── app_config.py         # AppConfig
```

## 규칙

### 1. 파일당 하나의 Config

각 `*_config.py` 파일에는 `BaseConfig`을 상속하는 `@register_config` 데이터클래스가 **정확히 하나**만 포함되어야 합니다.

```python
# sub_config/channels/discord_config.py

from ...base import BaseConfig, ConfigField, FieldType, register_config

@register_config
@dataclass
class DiscordConfig(BaseConfig):
    ...
```

### 2. 파일 명명 규칙

- 설정 파일은 반드시 `_config.py`로 끝나야 합니다 (예: `discord_config.py`, `auth_config.py`)
- 소문자와 밑줄을 사용합니다 (snake_case)
- 접두사는 해당 연동 또는 기능을 명확히 식별할 수 있어야 합니다

### 3. 카테고리 = 폴더명

- 상위 폴더 이름이 카테고리입니다 (예: `channels/`, `security/`, `general/`)
- 각 카테고리 폴더에는 `__init__.py`가 반드시 있어야 합니다 (빈 파일 또는 독스트링 포함 가능)
- 설정 클래스의 `get_category()` 메서드는 폴더명과 동일한 카테고리명을 반환해야 합니다

### 4. Import 경로

설정 파일은 상대 임포트를 사용하여 `BaseConfig`에 접근합니다:

```python
from ...base import BaseConfig, ConfigField, FieldType, register_config
```

이는 `service.config.sub_config.<카테고리>.<파일>`에서 `service.config.base`로 해석됩니다.

### 5. 자동 탐색

`sub_config/__init__.py` 모듈이 자동으로:
1. `sub_config/`의 모든 하위 디렉토리를 순회합니다
2. `*_config.py` 패턴에 맞는 모든 모듈을 임포트합니다
3. `@register_config` 데코레이터가 해당 클래스를 전역 레지스트리에 등록합니다

**수동 등록이 필요 없습니다.** 데코레이터가 적용된 파일을 생성하기만 하면 자동으로 탐색됩니다.

### 6. 하위 호환성

설정 클래스를 직접 임포트하는 기존 코드를 위해 `service/config/__init__.py`에서 재수출합니다:

```python
from .sub_config.channels.discord_config import DiscordConfig
```

새로운 설정을 추가할 때, 외부 코드에서 직접 접근이 필요하다면 유사한 재수출 라인을 추가하세요.

## 새 Config 추가 방법

1. `sub_config/` 아래에 **카테고리 폴더를 선택하거나 생성**합니다
2. 카테고리 폴더에 **`__init__.py`를 생성**합니다 (없는 경우)
3. `@register_config` 데이터클래스가 포함된 **`<이름>_config.py`를 생성**합니다
4. `get_category()`가 **폴더명과 일치하도록 설정**합니다
5. **(선택사항)** `service/config/__init__.py`에 재수출 라인을 추가합니다

이것으로 끝입니다 — 해당 설정은 자동으로 탐색되며, `ConfigManager`를 통해 로드 가능하고, Settings UI에 렌더링됩니다.

## Config 클래스 작성법

각 설정 파일은 일관된 패턴을 따릅니다. 아래는 전체 주석이 포함된 예시입니다:

```python
"""설정에 대한 간단한 설명."""

from dataclasses import dataclass, field
from typing import List

from ...base import BaseConfig, ConfigField, FieldType, register_config


@register_config          # import 시 글로벌 레지스트리에 등록
@dataclass                # 필수 — to_dict() / from_dict() 직렬화 지원
class ExampleConfig(BaseConfig):
    """설정 클래스 독스트링."""

    # --- 인스턴스 필드 (실제 설정값) ---
    enabled: bool = False
    api_key: str = ""
    max_retries: int = 3
    allowed_ids: List[str] = field(default_factory=list)

    # --- 필수 클래스 메서드 ---

    @classmethod
    def get_config_name(cls) -> str:
        """고유 식별자. JSON 파일명으로 사용 (예: 'example' -> example.json)"""
        return "example"

    @classmethod
    def get_display_name(cls) -> str:
        """Settings UI 카드에 표시되는 사람이 읽을 수 있는 이름."""
        return "Example Integration"

    @classmethod
    def get_description(cls) -> str:
        """표시 이름 아래에 표시되는 간단한 설명."""
        return "예시 연동을 설정합니다."

    @classmethod
    def get_category(cls) -> str:
        """상위 폴더명과 일치해야 함 (예: 'channels')."""
        return "channels"

    @classmethod
    def get_icon(cls) -> str:
        """프론트엔드에서 사용하는 아이콘 키 (선택사항, 기본값: 'settings')."""
        return "settings"

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        """각 필드의 UI 메타데이터를 정의."""
        return [
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="연동 활성화",
                description="이 연동을 켜거나 끕니다",
                default=False,
                group="connection"
            ),
            ConfigField(
                name="api_key",
                field_type=FieldType.STRING,
                label="API Key",
                description="인증을 위한 비밀 API 키",
                required=True,
                placeholder="API 키를 입력하세요",
                group="connection",
                secure=True          # 비밀번호 마스킹 + 눈 토글로 렌더링
            ),
            ConfigField(
                name="max_retries",
                field_type=FieldType.NUMBER,
                label="최대 재시도",
                description="실패 시 재시도 횟수",
                default=3,
                min_value=0,
                max_value=10,
                group="behavior"
            ),
            ConfigField(
                name="allowed_ids",
                field_type=FieldType.TEXTAREA,
                label="허용 ID 목록",
                description="쉼표로 구분된 허용 ID 목록",
                placeholder="id1, id2, id3",
                group="permissions"
            ),
        ]
```

## ConfigField 파라미터 레퍼런스

`get_fields_metadata()`의 각 필드는 `ConfigField` 인스턴스입니다. 전체 파라미터 목록:

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `name` | `str` | *(필수)* | 데이터클래스 필드명과 정확히 일치해야 합니다. JSON 키로 사용됩니다. |
| `field_type` | `FieldType` | *(필수)* | UI에서 렌더링되는 입력 위젯을 결정합니다. 아래 **FieldType** 표를 참조하세요. |
| `label` | `str` | *(필수)* | 입력 옆에 표시되는 사람이 읽을 수 있는 레이블. |
| `description` | `str` | `""` | UI에서 `?` 아이콘 호버 시 툴팁으로 표시되는 설명. |
| `required` | `bool` | `False` | `True`이면 필드가 비어있을 때 유효성 검사 실패. 레이블 옆에 빨간 `*` 표시. |
| `default` | `Any` | `None` | 기본값. 데이터클래스 필드의 기본값과 일치해야 합니다. |
| `placeholder` | `str` | `""` | 입력이 비어있을 때 표시되는 플레이스홀더 텍스트. |
| `options` | `List[Dict]` | `[]` | `SELECT` / `MULTISELECT` 전용. 각 항목: `{"value": "...", "label": "..."}`. |
| `min_value` | `float?` | `None` | `NUMBER` 필드의 최솟값. |
| `max_value` | `float?` | `None` | `NUMBER` 필드의 최댓값. |
| `pattern` | `str?` | `None` | 서버측 유효성 검사를 위한 정규식 패턴. |
| `group` | `str` | `"general"` | 편집 모달에서 필드를 시각적으로 그룹화 (예: `"connection"`, `"behavior"`). |
| `secure` | `bool` | `False` | `True`이면 `field_type`에 관계없이 비밀번호 마스킹과 보기/숨기기 눈 토글로 렌더링됩니다. 토큰, 시크릿, 비밀번호 등 민감한 값에 사용하세요. |

## FieldType 레퍼런스

| FieldType | UI 위젯 | 비고 |
|-----------|---------|------|
| `STRING` | 텍스트 입력 | 대부분의 텍스트 필드에 기본 사용. |
| `PASSWORD` | 텍스트 입력 | 의미론적 힌트. 실제 마스킹은 `secure=True`로 제어. |
| `NUMBER` | 숫자 입력 (스피너 숨김) | `min_value` / `max_value`로 범위 검증. |
| `BOOLEAN` | 토글 스위치 | 가로 행으로 렌더링: 레이블 좌측, 토글 우측. |
| `SELECT` | 드롭다운 | `options` 파라미터 필수. |
| `MULTISELECT` | 다중 선택 | `options` 파라미터 필수. |
| `TEXTAREA` | 여러 줄 텍스트 | 목록(쉼표 구분 ID) 및 긴 텍스트에 적합. |
| `URL` | URL 입력 | `http://` 또는 `https://` 접두사 검증. |
| `EMAIL` | 이메일 입력 | `@` 포함 여부 검증. |

> **중요:** `PASSWORD` FieldType은 의미론적 마커입니다. 실제로 UI에서 필드를 마스킹하려면 `ConfigField`에 `secure=True`를 설정해야 합니다. 이를 통해 어떤 필드 타입(STRING, TEXTAREA 등)이든 민감한 데이터를 포함할 때 마스킹 처리할 수 있습니다.
