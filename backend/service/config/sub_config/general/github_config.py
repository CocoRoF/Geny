"""
GitHub Configuration.

Controls GitHub personal access token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config
from service.config.sub_config.general.env_utils import env_sync, read_env_defaults


@register_config
@dataclass
class GitHubConfig(BaseConfig):
    """GitHub credentials."""

    github_token: str = ""

    _ENV_MAP = {
        "github_token": "GITHUB_TOKEN",
    }

    @classmethod
    def get_default_instance(cls) -> "GitHubConfig":
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        return cls(**defaults)

    @classmethod
    def get_config_name(cls) -> str:
        return "github"

    @classmethod
    def get_display_name(cls) -> str:
        return "GitHub"

    @classmethod
    def get_description(cls) -> str:
        return "GitHub personal access token for git push / PR creation."

    @classmethod
    def get_category(cls) -> str:
        return "general"

    @classmethod
    def get_icon(cls) -> str:
        return "github"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "GitHub",
                "description": "Git Push 및 PR 생성을 위한 GitHub 개인 액세스 토큰.",
                "groups": {
                    "github": "GitHub 설정",
                },
                "fields": {
                    "github_token": {
                        "label": "GitHub 토큰",
                        "description": "Git Push 및 PR 생성을 위한 개인 액세스 토큰",
                    },
                },
            }
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            ConfigField(
                name="github_token",
                field_type=FieldType.PASSWORD,
                label="GitHub Token",
                description="Personal Access Token for git push / PR creation",
                placeholder="ghp_xxxxxxxxxxxx",
                group="github",
                secure=True,
                apply_change=env_sync("GITHUB_TOKEN"),
            ),
        ]
