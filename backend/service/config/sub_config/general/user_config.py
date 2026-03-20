"""
User Persona Configuration.

Defines the user's identity within the AI Agent organization.
All agents recognize and address the user based on these settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config
from service.config.sub_config.general.env_utils import env_sync, read_env_defaults

ROLE_OPTIONS = [
    {"value": "ceo", "label": "CEO"},
    {"value": "cto", "label": "CTO"},
    {"value": "cpo", "label": "CPO"},
    {"value": "team_lead", "label": "Team Lead"},
    {"value": "manager", "label": "Manager"},
    {"value": "engineer", "label": "Engineer"},
    {"value": "designer", "label": "Designer"},
    {"value": "analyst", "label": "Analyst"},
    {"value": "custom", "label": "Custom"},
]


@register_config
@dataclass
class UserConfig(BaseConfig):
    """User persona settings for the AI agent organization."""

    user_name: str = ""
    user_title: str = ""
    department: str = ""
    description: str = ""

    _ENV_MAP = {
        "user_name": "GENY_USER_NAME",
        "user_title": "GENY_USER_TITLE",
        "department": "GENY_USER_DEPARTMENT",
        "description": "GENY_USER_DESCRIPTION",
    }

    @classmethod
    def get_default_instance(cls) -> "UserConfig":
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        return cls(**defaults)

    @classmethod
    def get_config_name(cls) -> str:
        return "user"

    @classmethod
    def get_display_name(cls) -> str:
        return "User"

    @classmethod
    def get_description(cls) -> str:
        return "Your persona within the AI agent organization. Agents will recognize and address you based on these settings."

    @classmethod
    def get_category(cls) -> str:
        return "general"

    @classmethod
    def get_icon(cls) -> str:
        return "user"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "사용자",
                "description": "AI 에이전트 조직 내 사용자 페르소나. 에이전트는 이 설정에 따라 사용자를 인식하고 호칭합니다.",
                "groups": {
                    "identity": "신원 정보",
                    "organization": "조직 정보",
                },
                "fields": {
                    "user_name": {
                        "label": "이름",
                        "description": "에이전트가 호칭할 이름",
                        "placeholder": "홍길동",
                    },
                    "user_title": {
                        "label": "직책",
                        "description": "조직 내 직책 또는 역할",
                        "placeholder": "CTO",
                    },
                    "department": {
                        "label": "부서",
                        "description": "소속 부서 또는 팀",
                        "placeholder": "Engineering",
                    },
                    "description": {
                        "label": "소개",
                        "description": "에이전트에게 알려줄 추가 정보 (전문 분야, 선호하는 커뮤니케이션 스타일 등)",
                        "placeholder": "풀스택 개발 경험이 있으며 간결한 한국어 답변을 선호합니다.",
                    },
                },
            }
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            ConfigField(
                name="user_name",
                field_type=FieldType.STRING,
                label="Name",
                description="The name agents will use to address you",
                placeholder="John Doe",
                group="identity",
                apply_change=env_sync("GENY_USER_NAME"),
            ),
            ConfigField(
                name="user_title",
                field_type=FieldType.STRING,
                label="Title / Role",
                description="Your title or role in the organization",
                placeholder="CTO",
                group="identity",
                apply_change=env_sync("GENY_USER_TITLE"),
            ),
            ConfigField(
                name="department",
                field_type=FieldType.STRING,
                label="Department",
                description="Your department or team",
                placeholder="Engineering",
                group="organization",
                apply_change=env_sync("GENY_USER_DEPARTMENT"),
            ),
            ConfigField(
                name="description",
                field_type=FieldType.TEXTAREA,
                label="Bio",
                description="Additional context for agents (expertise, communication preferences, etc.)",
                placeholder="Full-stack developer who prefers concise answers in Korean.",
                group="organization",
                apply_change=env_sync("GENY_USER_DESCRIPTION"),
            ),
        ]

    # ── Public helpers for services ──

    @staticmethod
    def get_user_name() -> str:
        return os.environ.get("GENY_USER_NAME", "")

    @staticmethod
    def get_user_title() -> str:
        return os.environ.get("GENY_USER_TITLE", "")

    @staticmethod
    def get_department() -> str:
        return os.environ.get("GENY_USER_DEPARTMENT", "")

    @staticmethod
    def get_description() -> str:
        return os.environ.get("GENY_USER_DESCRIPTION", "")

    @staticmethod
    def get_user_context() -> str:
        """Build a concise user context string for injection into agent prompts.

        Returns empty string if no user info is configured.
        """
        name = UserConfig.get_user_name()
        if not name:
            return ""

        parts = [f"The user's name is \"{name}\"."]

        title = UserConfig.get_user_title()
        if title:
            parts.append(f"Title: {title}.")

        dept = UserConfig.get_department()
        if dept:
            parts.append(f"Department: {dept}.")

        desc = UserConfig.get_description()
        if desc:
            parts.append(f"About: {desc}")

        return " ".join(parts)
