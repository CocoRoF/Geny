"""The ways this server can reach a model, and what each one needs.

One catalogue, read by the API, the web UI and the connector, so "which
models can I pick for this account" has a single answer. ``engine_provider``
is the geny-executor client a route hop built from this account talks to.

Model lists are a starting point, not a limit: an account also carries
whatever ``models`` discovery found, and a user may type any id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = [
    "ACCOUNT_KINDS",
    "FAMILIES",
    "EFFORTS",
    "KINDS",
    "KindInfo",
    "ModelChoice",
    "default_model_for",
    "model_choices",
]

#: Reasoning effort a route hop may request. Backends that do not reason
#: ignore it rather than failing.
EFFORTS: Tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class ModelChoice:
    id: str
    label: str
    hint: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"id": self.id, "label": self.label, "hint": self.hint}


#: How a kind is reached, which is also how the settings page groups them.
#: A subscription is signed into; an API kind takes a key; a self-hosted one
#: is an address you run yourself. Three different conversations, and a page
#: that mixes them is the page where nobody finds the Codex login.
FAMILIES: Tuple[Tuple[str, str], ...] = (
    ("subscription", "구독 로그인"),
    ("api", "API 키"),
    ("self_hosted", "직접 띄운 엔드포인트"),
)


@dataclass(frozen=True)
class KindInfo:
    label: str
    short: str
    engine_provider: str
    #: subscription | api | self_hosted — see FAMILIES.
    family: str
    #: what the user has to supply: api_key | optional_key | none | oauth
    secret: str
    hint: str
    models: Tuple[ModelChoice, ...] = ()
    default_base_url: str = ""
    needs_base_url: bool = False
    #: the account owns a private CLAUDE_CONFIG_DIR (many logins side by side)
    owns_config_dir: bool = False

    def to_dict(self) -> Dict[str, object]:
        return {
            "label": self.label,
            "short": self.short,
            "engineProvider": self.engine_provider,
            "family": self.family,
            "secret": self.secret,
            "hint": self.hint,
            "models": [m.to_dict() for m in self.models],
            "defaultBaseUrl": self.default_base_url,
            "needsBaseUrl": self.needs_base_url,
            "ownsConfigDir": self.owns_config_dir,
        }


KINDS: Dict[str, KindInfo] = {
    "claude_code": KindInfo(
        family="subscription",
        label="Claude Code",
        short="Claude Code",
        engine_provider="geny_claude_code",
        secret="none",
        hint="Pro/Max 로그인 · setup-token · Console 키. 계정을 원하는 만큼 나란히 둘 수 있습니다.",
        owns_config_dir=True,
        models=(
            ModelChoice("sonnet", "Sonnet (최신)", "CLI 가 현재 세대로 해석합니다"),
            ModelChoice("opus", "Opus (최신)"),
            ModelChoice("fable", "Fable (최신)", "가장 깊은 추론"),
            ModelChoice("haiku", "Haiku (최신)", "빠르고 저렴"),
            ModelChoice("claude-fable-5-1", "Claude Fable 5.1"),
            ModelChoice("claude-opus-5", "Claude Opus 5"),
            ModelChoice("claude-sonnet-5", "Claude Sonnet 5"),
        ),
    ),
    "codex": KindInfo(
        family="subscription",
        label="ChatGPT · Codex",
        short="Codex",
        engine_provider="geny_codex",
        secret="oauth",
        default_base_url="https://chatgpt.com/backend-api/codex",
        hint="ChatGPT 계정으로 로그인합니다 (Plus/Pro/Business).",
        models=(
            ModelChoice("gpt-5.6-terra", "GPT-5.6 Terra", "일상 작업 기본값"),
            ModelChoice("gpt-5.6-sol", "GPT-5.6 Sol", "복잡한 코딩·리서치"),
            ModelChoice("gpt-6-astra", "GPT-6 Astra", "가장 강력"),
            ModelChoice("gpt-5.6-luna", "GPT-5.6 Luna", "빠르고 저렴"),
            ModelChoice("gpt-5.3-codex-spark", "GPT-5.3 Codex Spark", "실시간 코딩 (Pro)"),
        ),
    ),
    "anthropic": KindInfo(
        family="api",
        label="Anthropic API",
        short="Anthropic",
        engine_provider="anthropic",
        secret="api_key",
        hint="console.anthropic.com 에서 발급한 API 키",
        models=(
            ModelChoice("claude-sonnet-5", "Claude Sonnet 5"),
            ModelChoice("claude-opus-5", "Claude Opus 5"),
            ModelChoice("claude-fable-5-1", "Claude Fable 5.1"),
            ModelChoice("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
        ),
    ),
    "openai": KindInfo(
        family="api",
        label="OpenAI API",
        short="OpenAI",
        engine_provider="openai",
        secret="api_key",
        hint="platform.openai.com 에서 발급한 API 키",
        models=(
            ModelChoice("gpt-5.6-terra", "GPT-5.6 Terra"),
            ModelChoice("gpt-5.6-sol", "GPT-5.6 Sol"),
            ModelChoice("gpt-6-astra", "GPT-6 Astra"),
            ModelChoice("gpt-5.6-luna", "GPT-5.6 Luna"),
        ),
    ),
    "google": KindInfo(
        family="api",
        label="Google Gemini API",
        short="Gemini",
        engine_provider="google",
        secret="api_key",
        hint="aistudio.google.com 에서 발급한 키",
        models=(
            ModelChoice("gemini-2.5-pro", "Gemini 2.5 Pro"),
            ModelChoice("gemini-2.5-flash", "Gemini 2.5 Flash"),
        ),
    ),
    "openrouter": KindInfo(
        family="api",
        label="OpenRouter",
        short="OpenRouter",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://openrouter.ai/api/v1",
        hint="키 하나로 여러 회사의 모델을 씁니다",
        models=(
            ModelChoice("anthropic/claude-sonnet-5", "Claude Sonnet 5 (OpenRouter)"),
            ModelChoice("openai/gpt-5.6-terra", "GPT-5.6 Terra (OpenRouter)"),
        ),
    ),
    "ollama": KindInfo(
        family="self_hosted",
        label="Ollama (로컬)",
        short="Ollama",
        engine_provider="ollama",
        secret="none",
        default_base_url="http://localhost:11434/v1",
        hint="이 서버의 Ollama — 도구를 호출할 수 있는 모델을 권합니다",
        models=(
            ModelChoice("qwen3-coder", "qwen3-coder"),
            ModelChoice("llama3.1", "llama3.1"),
        ),
    ),
    "vllm": KindInfo(
        family="self_hosted",
        label="vLLM",
        short="vLLM",
        engine_provider="vllm",
        secret="optional_key",
        needs_base_url=True,
        hint="자체 호스팅한 vLLM 엔드포인트",
    ),
    "openai_compatible": KindInfo(
        family="self_hosted",
        label="OpenAI 호환 엔드포인트",
        short="호환",
        engine_provider="custom",
        secret="optional_key",
        needs_base_url=True,
        hint="LM Studio · LiteLLM · 사내 게이트웨이 등",
    ),
}

ACCOUNT_KINDS: List[str] = list(KINDS)


def default_model_for(kind: str, discovered: Optional[List[str]] = None) -> str:
    info = KINDS.get(kind)
    if info and info.models:
        return info.models[0].id
    return (discovered or [""])[0]


def model_choices(kind: str, discovered: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """The catalogue first, then anything discovery found that it misses."""
    info = KINDS.get(kind)
    known = list(info.models) if info else []
    seen = {m.id for m in known}
    extra = [ModelChoice(m, m) for m in (discovered or []) if m and m not in seen]
    return [m.to_dict() for m in [*known, *extra]]
