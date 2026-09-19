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

    #: Shown expanded in its family, rather than folded into "more".
    #:
    #: Every provider stays on the page whether or not it is set up — a
    #: server with a working Codex login must not read as a server without
    #: one. That principle was written when there were nine of these. At
    #: twenty-one it turns the page into a scroll of empty sections and
    #: buries the five anyone uses, so the long tail folds into one group
    #: that opens in a click. Folded is not hidden; a vendor with an account
    #: on it is never folded.
    primary: bool = True

    #: What the ENDPOINT serves, for kinds that share one client class.
    #:
    #: ``openrouter`` and a laptop's llama.cpp are both ``engine_provider=
    #: "custom"``: same wire format, nothing alike behind it. The executor's
    #: class-level flags have to assume the weaker one, so a kind that knows
    #: better says so here and the declaration rides to the client through
    #: the hop's options. Vision is the one that matters in practice — an
    #: undeclared image is either a 400 or a picture the model never saw.
    #:
    #: Conservative by default, and an ACCOUNT may raise it
    #: (``capabilities_json`` on the row): which model sits behind one
    #: OpenAI-compatible address is the operator's knowledge, not ours.
    capabilities: Dict[str, bool] = field(default_factory=dict)

    #: The cheap tier for background work — memory curation, summarising,
    #: classification. It lives HERE, beside the models it is chosen from,
    #: because the alternative rots: a model id pinned in a settings row goes
    #: stale the day the provider retires it, and every background call then
    #: spends a round trip 404ing. An id in this list moves when the list
    #: moves. Empty means "use the account's own model".
    aux_model: str = ""

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
            "capabilities": dict(self.capabilities),
            "primary": self.primary,
        }


KINDS: Dict[str, KindInfo] = {
    "claude_code": KindInfo(
        aux_model="haiku",
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
        aux_model="gpt-5.6-luna",
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
        aux_model="claude-haiku-4-5-20251001",
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
        aux_model="gpt-5.6-luna",
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
        # An aggregator in front of Claude and GPT — the one OpenAI-compatible
        # kind whose catalogue is multimodal end to end. Without this the
        # shared ``custom`` class assumes a text-only local server and every
        # attached image arrives as "[an image was attached here]".
        capabilities={"supports_vision": True},
        models=(
            ModelChoice("anthropic/claude-sonnet-5", "Claude Sonnet 5 (OpenRouter)"),
            ModelChoice("openai/gpt-5.6-terra", "GPT-5.6 Terra (OpenRouter)"),
        ),
    ),
    # ── Other OpenAI-compatible vendors ──────────────────────────────
    #
    # Each of these is one address and a label. They exist as their own kind
    # rather than as "OpenAI 호환 엔드포인트 + paste a URL" for the reason
    # hermes-agent keeps 33 one-file provider profiles: the address is the
    # part a user gets wrong, and the kind is where a vendor's quirks get
    # recorded once we learn them. The model list stays empty on purpose —
    # every one of these serves ``GET /v1/models``, so [모델 불러오기] is
    # more current than any catalogue shipped in a release.
    "deepseek": KindInfo(
        primary=False,
        family="api",
        label="DeepSeek",
        short="DeepSeek",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://api.deepseek.com/v1",
        hint="platform.deepseek.com 에서 발급한 키",
    ),
    "xai": KindInfo(
        primary=False,
        family="api",
        label="xAI (Grok)",
        short="xAI",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://api.x.ai/v1",
        hint="console.x.ai 에서 발급한 키",
        capabilities={"supports_vision": True},
    ),
    "groq": KindInfo(
        primary=False,
        family="api",
        label="Groq",
        short="Groq",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://api.groq.com/openai/v1",
        hint="console.groq.com 에서 발급한 키 · 매우 빠른 추론",
    ),
    "together": KindInfo(
        primary=False,
        family="api",
        label="Together AI",
        short="Together",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://api.together.xyz/v1",
        hint="api.together.ai 에서 발급한 키 · 오픈 모델 호스팅",
    ),
    "fireworks": KindInfo(
        primary=False,
        family="api",
        label="Fireworks AI",
        short="Fireworks",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://api.fireworks.ai/inference/v1",
        hint="fireworks.ai 에서 발급한 키",
    ),
    "mistral": KindInfo(
        primary=False,
        family="api",
        label="Mistral AI",
        short="Mistral",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://api.mistral.ai/v1",
        hint="console.mistral.ai 에서 발급한 키",
    ),
    "moonshot": KindInfo(
        primary=False,
        family="api",
        label="Moonshot (Kimi)",
        short="Kimi",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://api.moonshot.ai/v1",
        hint="platform.moonshot.ai 에서 발급한 키",
    ),
    "zai": KindInfo(
        primary=False,
        family="api",
        label="Z.AI (GLM)",
        short="GLM",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://api.z.ai/api/paas/v4",
        hint="z.ai 에서 발급한 키",
    ),
    "alibaba": KindInfo(
        primary=False,
        family="api",
        label="Alibaba (Qwen)",
        short="Qwen",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        hint="DashScope 키 · 국내 리전은 주소를 바꿔 주세요",
    ),
    "nvidia": KindInfo(
        primary=False,
        family="api",
        label="NVIDIA NIM",
        short="NVIDIA",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://integrate.api.nvidia.com/v1",
        hint="build.nvidia.com 에서 발급한 키",
    ),
    "deepinfra": KindInfo(
        primary=False,
        family="api",
        label="DeepInfra",
        short="DeepInfra",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://api.deepinfra.com/v1/openai",
        hint="deepinfra.com 에서 발급한 키",
    ),
    "huggingface": KindInfo(
        primary=False,
        family="api",
        label="HuggingFace",
        short="HF",
        engine_provider="custom",
        secret="api_key",
        default_base_url="https://router.huggingface.co/v1",
        hint="HF 토큰 · Inference Providers 라우터",
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
        hint="자체 호스팅한 vLLM 엔드포인트 · 도구를 쓰려면 --enable-auto-tool-choice",
        # The executor's VLLMClient defaults say "no tools" because a vLLM
        # server is whatever model it loaded. For an ACCOUNT in this list the
        # answer is not open: it is being added to run this harness, and a hop
        # with no tools cannot. Declaring it here is what keeps a vLLM account
        # from joining a route as a model that silently ignores every tool.
        capabilities={
            "supports_tools": True,
            "supports_tool_choice": True,
            "supports_structured_output": True,
        },
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


def aux_model_for(kind: str) -> str:
    """The cheap tier for background work on this kind, or ``""``.

    Background work (memory curation, summarising) should not run on the
    model the user chose for the conversation — it is cheaper and just as
    good on the small one. Returning ``""`` means the caller keeps the
    account's own model rather than guessing an id the provider may not
    serve.
    """
    info = KINDS.get(kind)
    return info.aux_model if info else ""


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
