"""
KakaoTalk Chatbot Configuration.

Enables Claude Control integration with KakaoTalk via 카카오 i 오픈빌더 (챗봇 관리자센터).
Users interact with Claude sessions through KakaoTalk channel chatbot messages.

Architecture:
    KakaoTalk User → 카카오톡 채널 → 챗봇 관리자센터 → Skill(POST) → Claude Control → SkillResponse

References:
    - 챗봇 관리자센터: https://chatbot.kakao.com
    - 스킬 개발 가이드: https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide
    - 응답 타입별 JSON 포맷: https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/answer_json_format
    - 카카오 디벨로퍼스: https://developers.kakao.com
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from service.config.base import BaseConfig, ConfigField, FieldType, register_config


@register_config
@dataclass
class KakaoConfig(BaseConfig):
    """
    KakaoTalk Chatbot Configuration.

    Enables Claude Control integration with KakaoTalk via 카카오 i 오픈빌더.
    The chatbot receives user messages as Skill Payload (HTTP POST)
    and returns Claude responses as SkillResponse JSON.
    """

    # ── Connection settings ─────────────────────────────────────────────
    enabled: bool = False
    rest_api_key: str = ""          # Kakao Developers > 앱 키 > REST API 키
    admin_key: str = ""             # Kakao Developers > 앱 키 > Admin 키 (서버 전용)
    bot_id: str = ""                # 챗봇 관리자센터 봇 ID
    channel_public_id: str = ""     # 카카오톡 채널 프로필 ID (예: _ZeUTxl)

    # ── Skill Server settings ───────────────────────────────────────────
    skill_endpoint_path: str = "/api/kakao/skill"   # 스킬 서버 엔드포인트 경로
    skill_verify_header_key: str = "X-Kakao-Skill-Token"  # 스킬 요청 검증 헤더 키
    skill_verify_token: str = ""    # 스킬 요청 검증 토큰값 (챗봇 관리자센터 > 스킬 > 헤더값 입력)

    # ── Callback settings (AI 챗봇 콜백) ──────────────────────────────────
    # 스킬 응답 타임아웃은 5초. Claude 응답이 5초를 초과하면 콜백 사용 필요.
    use_callback: bool = True       # AI 챗봇 콜백 사용 여부
    callback_timeout_seconds: int = 60  # 콜백 응답 최대 대기 시간 (초)

    # ── Permissions ────────────────────────────────────────────────────
    admin_user_ids: List[str] = field(default_factory=list)     # 관리자 botUserKey 목록
    allowed_user_ids: List[str] = field(default_factory=list)   # 허용 사용자 botUserKey (빈 값 = 전체 허용)
    block_user_ids: List[str] = field(default_factory=list)     # 차단 사용자 botUserKey

    # ── Response settings ──────────────────────────────────────────────
    max_message_length: int = 1000  # simpleText 최대 글자수 (카카오 제한: 1000자, 500자 초과시 전체보기)
    response_format: str = "simpleText"  # 기본 응답 포맷: simpleText | textCard
    show_quick_replies: bool = True      # 바로가기 응답(quickReplies) 표시
    quick_reply_labels: List[str] = field(default_factory=lambda: [
        "계속", "새 대화", "도움말"
    ])

    # ── Session settings ───────────────────────────────────────────────
    session_timeout_minutes: int = 30   # 비활성 세션 자동 종료 (분)
    max_sessions_per_user: int = 1      # 사용자 당 최대 동시 세션 수
    default_prompt: str = ""            # 카카오톡 세션 기본 시스템 프롬프트

    @classmethod
    def get_config_name(cls) -> str:
        return "kakao"

    @classmethod
    def get_display_name(cls) -> str:
        return "KakaoTalk"

    @classmethod
    def get_description(cls) -> str:
        return (
            "Configure KakaoTalk chatbot integration via 카카오 i 오픈빌더. "
            "Users interact with Claude sessions through KakaoTalk channel messages. "
            "The chatbot calls your Skill server endpoint, which processes user input "
            "and returns Claude responses as SkillResponse JSON."
        )

    @classmethod
    def get_category(cls) -> str:
        return "channels"

    @classmethod
    def get_icon(cls) -> str:
        return "kakaotalk"

    @classmethod
    def get_i18n(cls) -> Dict[str, Dict[str, Any]]:
        return {
            "ko": {
                "display_name": "카카오톡",
                "description": (
                    "카카오 i 오픈빌더를 통한 카카오톡 챗봇 연동 설정. "
                    "사용자가 카카오톡 채널 메시지를 통해 Claude 세션과 대화할 수 있습니다."
                ),
                "groups": {
                    "connection": "연결 설정",
                    "skill_server": "스킬 서버",
                    "callback": "콜백 설정",
                    "permissions": "권한",
                    "response": "응답 설정",
                    "session": "세션 설정",
                },
                "fields": {
                    "enabled": {
                        "label": "카카오톡 연동 활성화",
                        "description": "카카오톡 챗봇 연동 활성화 또는 비활성화",
                    },
                    "rest_api_key": {
                        "label": "REST API 키",
                        "description": (
                            "카카오 디벨로퍼스 콘솔의 REST API 키. "
                            "경로: 카카오 디벨로퍼스 > 내 애플리케이션 > 앱 키 > REST API 키"
                        ),
                    },
                    "admin_key": {
                        "label": "Admin 키",
                        "description": (
                            "서버 측 API 호출을 위한 Admin 키. "
                            "경로: 카카오 디벨로퍼스 > 내 애플리케이션 > 앱 키 > Admin 키. "
                            "경고: 서버 측에서만 사용, 클라이언트에 노출 금지."
                        ),
                    },
                    "bot_id": {
                        "label": "챗봇 Bot ID",
                        "description": (
                            "챗봇 관리자센터의 Bot ID. "
                            "경로: chatbot.kakao.com > 봇 선택 > 설정 > 봇 정보"
                        ),
                    },
                    "channel_public_id": {
                        "label": "채널 프로필 ID",
                        "description": (
                            "카카오톡 채널 프로필 ID. "
                            "경로: 카카오톡 채널 파트너센터 > 채널 정보 > 채널 URL"
                        ),
                    },
                    "skill_endpoint_path": {
                        "label": "스킬 엔드포인트 경로",
                        "description": (
                            "카카오 챗봇이 스킬 POST 요청을 보내는 URL 경로. "
                            "챗봇 관리자센터 > 스킬 > 스킬 추가 > URL에 등록"
                        ),
                    },
                    "skill_verify_header_key": {
                        "label": "스킬 검증 헤더 키",
                        "description": (
                            "수신 스킬 요청 검증에 사용되는 커스텀 HTTP 헤더 키. "
                            "챗봇 관리자센터 > 스킬 > 헤더값 입력에 설정"
                        ),
                    },
                    "skill_verify_token": {
                        "label": "스킬 검증 토큰",
                        "description": (
                            "검증 헤더의 시크릿 토큰 값. "
                            "챗봇 관리자센터 > 스킬 > 헤더값 입력에 설정"
                        ),
                    },
                    "use_callback": {
                        "label": "AI 챗봇 콜백 사용",
                        "description": (
                            "비동기 응답을 위한 AI 챗봇 콜백 활성화. "
                            "스킬 타임아웃 5초 초과 시 '처리 중...' 메시지를 먼저 보내고 "
                            "준비되면 콜백으로 실제 응답 전달."
                        ),
                    },
                    "callback_timeout_seconds": {
                        "label": "콜백 타임아웃 (초)",
                        "description": "콜백으로 Claude 응답을 기다리는 최대 시간 (초). 초과 시 오류 메시지 전송.",
                    },
                    "admin_user_ids": {
                        "label": "관리자 사용자 ID (botUserKey)",
                        "description": "쉼표로 구분된 관리자 botUserKey 목록. 관리자는 세션 제어 등의 관리 명령 사용 가능.",
                    },
                    "allowed_user_ids": {
                        "label": "허용된 사용자 ID (선택)",
                        "description": "쉼표로 구분된 허용 botUserKey 목록. 비워두면 모든 사용자 허용.",
                    },
                    "block_user_ids": {
                        "label": "차단된 사용자 ID",
                        "description": "쉼표로 구분된 차단할 botUserKey 목록.",
                    },
                    "max_message_length": {
                        "label": "최대 메시지 길이",
                        "description": "메시지당 최대 글자 수. 카카오톡 simpleText 제한: 1000자.",
                    },
                    "response_format": {
                        "label": "응답 포맷",
                        "description": "챗봇 응답 출력 포맷. simpleText: 텍스트 말풍선, textCard: 버튼 포함 카드.",
                    },
                    "show_quick_replies": {
                        "label": "바로가기 응답 표시",
                        "description": "각 응답 아래에 '계속', '새 대화', '도움말' 등의 바로가기 응답 버튼 표시.",
                    },
                    "quick_reply_labels": {
                        "label": "바로가기 응답 라벨",
                        "description": "쉼표로 구분된 바로가기 응답 버튼 라벨.",
                    },
                    "session_timeout_minutes": {
                        "label": "세션 타임아웃 (분)",
                        "description": "비활성 세션을 지정 시간 후 자동 종료",
                    },
                    "max_sessions_per_user": {
                        "label": "사용자당 최대 세션 수",
                        "description": "사용자당 최대 동시 세션 수",
                    },
                    "default_prompt": {
                        "label": "기본 시스템 프롬프트",
                        "description": "카카오톡에서 시작된 세션의 기본 시스템 프롬프트",
                    },
                },
            }
        }

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        return [
            # ── Connection group ────────────────────────────────────────
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="Enable KakaoTalk Integration",
                description="Enable or disable KakaoTalk chatbot integration",
                default=False,
                group="connection"
            ),
            ConfigField(
                name="rest_api_key",
                field_type=FieldType.STRING,
                label="REST API Key",
                description=(
                    "REST API key from Kakao Developers console. "
                    "Navigate to: 카카오 디벨로퍼스 > 내 애플리케이션 > 앱 키 > REST API 키"
                ),
                required=True,
                placeholder="abcdef1234567890abcdef1234567890",
                group="connection",
                secure=True
            ),
            ConfigField(
                name="admin_key",
                field_type=FieldType.STRING,
                label="Admin Key",
                description=(
                    "Admin key for server-side API calls (sending messages, managing customer files). "
                    "Navigate to: 카카오 디벨로퍼스 > 내 애플리케이션 > 앱 키 > Admin 키. "
                    "WARNING: Must be used only from server-side, never exposed to client."
                ),
                placeholder="abcdef1234567890abcdef1234567890",
                group="connection",
                secure=True
            ),
            ConfigField(
                name="bot_id",
                field_type=FieldType.STRING,
                label="Chatbot Bot ID",
                description=(
                    "Bot ID from 챗봇 관리자센터. "
                    "Navigate to: chatbot.kakao.com > 봇 선택 > 설정 > 봇 정보에서 확인"
                ),
                placeholder="64xxxxxxxxxxxxxxxxxx",
                group="connection"
            ),
            ConfigField(
                name="channel_public_id",
                field_type=FieldType.STRING,
                label="Channel Public ID (프로필 ID)",
                description=(
                    "KakaoTalk channel profile ID. "
                    "Navigate to: 카카오톡 채널 파트너센터 > 채널 정보 > 채널 URL. "
                    "Example: URL이 https://pf.kakao.com/_ZeUTxl 이면, 프로필 ID는 _ZeUTxl"
                ),
                required=True,
                placeholder="_ZeUTxl",
                group="connection"
            ),

            # ── Skill Server group ──────────────────────────────────────
            ConfigField(
                name="skill_endpoint_path",
                field_type=FieldType.STRING,
                label="Skill Endpoint Path",
                description=(
                    "URL path where Kakao chatbot sends Skill POST requests. "
                    "Register this full URL (https://your-domain:port + path) in "
                    "챗봇 관리자센터 > 스킬 > 스킬 추가 > URL"
                ),
                default="/api/kakao/skill",
                placeholder="/api/kakao/skill",
                group="skill_server"
            ),
            ConfigField(
                name="skill_verify_header_key",
                field_type=FieldType.STRING,
                label="Skill Verify Header Key",
                description=(
                    "Custom HTTP header key used to verify incoming Skill requests. "
                    "Set this in 챗봇 관리자센터 > 스킬 > 헤더값 입력 as the header key."
                ),
                default="X-Kakao-Skill-Token",
                placeholder="X-Kakao-Skill-Token",
                group="skill_server"
            ),
            ConfigField(
                name="skill_verify_token",
                field_type=FieldType.STRING,
                label="Skill Verify Token",
                description=(
                    "Secret token value for the verification header. "
                    "Set this in 챗봇 관리자센터 > 스킬 > 헤더값 입력 as the header value. "
                    "Claude Control will reject requests without a matching token."
                ),
                placeholder="your-secret-token-value",
                group="skill_server",
                secure=True
            ),

            # ── Callback group ──────────────────────────────────────────
            ConfigField(
                name="use_callback",
                field_type=FieldType.BOOLEAN,
                label="Use AI Chatbot Callback",
                description=(
                    "Enable AI Chatbot Callback for asynchronous responses. "
                    "Kakao skill timeout is 5 seconds. Since Claude responses often take longer, "
                    "enabling callback sends a 'processing...' message first and delivers "
                    "the actual response via callback when ready."
                ),
                default=True,
                group="callback"
            ),
            ConfigField(
                name="callback_timeout_seconds",
                field_type=FieldType.NUMBER,
                label="Callback Timeout (seconds)",
                description=(
                    "Maximum seconds to wait for Claude response via callback. "
                    "After timeout, a fallback error message is sent."
                ),
                default=60,
                min_value=5,
                max_value=120,
                group="callback"
            ),

            # ── Permissions group ───────────────────────────────────────
            ConfigField(
                name="admin_user_ids",
                field_type=FieldType.TEXTAREA,
                label="Admin User IDs (botUserKey)",
                description=(
                    "Comma-separated list of botUserKey values for admin users. "
                    "Admins can use management commands (e.g., session control, config reload). "
                    "botUserKey is found in Skill Payload: userRequest.user.properties.botUserKey"
                ),
                placeholder="abc123def456, ghi789jkl012",
                group="permissions"
            ),
            ConfigField(
                name="allowed_user_ids",
                field_type=FieldType.TEXTAREA,
                label="Allowed User IDs (Optional)",
                description=(
                    "Comma-separated list of botUserKey values allowed to use the bot. "
                    "Leave empty to allow all users."
                ),
                placeholder="abc123def456, ghi789jkl012",
                group="permissions"
            ),
            ConfigField(
                name="block_user_ids",
                field_type=FieldType.TEXTAREA,
                label="Blocked User IDs",
                description="Comma-separated list of botUserKey values to block from using the bot.",
                placeholder="abc123def456",
                group="permissions"
            ),

            # ── Response group ──────────────────────────────────────────
            ConfigField(
                name="max_message_length",
                field_type=FieldType.NUMBER,
                label="Max Message Length",
                description=(
                    "Maximum characters per message. "
                    "KakaoTalk simpleText limit is 1000 characters. "
                    "Messages over 500 characters show a 'View All' button."
                ),
                default=1000,
                min_value=100,
                max_value=1000,
                group="response"
            ),
            ConfigField(
                name="response_format",
                field_type=FieldType.SELECT,
                label="Response Format",
                description=(
                    "Output format for chatbot responses. "
                    "simpleText: Plain text bubble. "
                    "textCard: Card with optional buttons."
                ),
                default="simpleText",
                options=[
                    {"value": "simpleText", "label": "Simple Text (텍스트형)"},
                    {"value": "textCard", "label": "Text Card (텍스트 카드형)"},
                ],
                group="response"
            ),
            ConfigField(
                name="show_quick_replies",
                field_type=FieldType.BOOLEAN,
                label="Show Quick Replies",
                description=(
                    "Display quickReplies (바로가기 응답) buttons below each response "
                    "for common actions like 'Continue', 'New Chat', 'Help'."
                ),
                default=True,
                group="response"
            ),
            ConfigField(
                name="quick_reply_labels",
                field_type=FieldType.TEXTAREA,
                label="Quick Reply Labels",
                description=(
                    "Comma-separated labels for quick reply buttons. "
                    "Each label becomes a clickable button below the response."
                ),
                placeholder="계속, 새 대화, 도움말",
                group="response"
            ),

            # ── Session group ───────────────────────────────────────────
            ConfigField(
                name="session_timeout_minutes",
                field_type=FieldType.NUMBER,
                label="Session Timeout (minutes)",
                description="Auto-close inactive sessions after this many minutes",
                default=30,
                min_value=5,
                max_value=1440,
                group="session"
            ),
            ConfigField(
                name="max_sessions_per_user",
                field_type=FieldType.NUMBER,
                label="Max Sessions Per User",
                description="Maximum concurrent sessions per user",
                default=1,
                min_value=1,
                max_value=5,
                group="session"
            ),
            ConfigField(
                name="default_prompt",
                field_type=FieldType.TEXTAREA,
                label="Default System Prompt",
                description="Default system prompt for KakaoTalk-initiated sessions",
                placeholder="You are a helpful assistant...",
                group="session"
            ),
        ]
