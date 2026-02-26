"""
Node i18n & Help Content — centralised Korean/English translations for all nodes.

Each built-in node type has:
  - Localised label, description
  - Localised parameter labels & descriptions
  - Localised output port labels
  - Localised group names
  - Detailed help guide with multiple sections

This module is imported by each node file to attach translations.
"""

from __future__ import annotations

from service.workflow.nodes.base import (
    HelpSection,
    NodeHelp,
    NodeI18n,
)


# ====================================================================
#  Helper — shorthand constructors
# ====================================================================

def _help(title: str, summary: str, sections: list[tuple[str, str]]) -> NodeHelp:
    return NodeHelp(
        title=title,
        summary=summary,
        sections=[HelpSection(t, c) for t, c in sections],
    )


# ====================================================================
#  MODEL NODES
# ====================================================================

LLM_CALL_I18N = {
    "en": NodeI18n(
        label="LLM Call",
        description="Universal LLM invocation node. Sends a configurable prompt template to the model with {field} state variable substitution. Supports conditional prompt switching, multiple output field mappings, and an optional completion flag.",
        parameters={
            "prompt_template": {
                "label": "Prompt Template",
                "description": (
                    "Prompt sent to the model. Use {field_name} for state variable substitution. "
                    "Available fields: input, answer, review_feedback, last_output, etc."
                ),
            },
            "conditional_field": {
                "label": "Conditional Prompt Field",
                "description": "State field to check for prompt switching. When set and condition is met, the Alternative Prompt is used.",
            },
            "conditional_check": {
                "label": "Conditional Check",
                "description": "How to evaluate the conditional field.",
            },
            "alternative_prompt": {
                "label": "Alternative Prompt",
                "description": "Prompt used when the conditional field check passes.",
            },
            "output_field": {
                "label": "Output State Field",
                "description": "State field to store the model response in.",
            },
            "output_mappings": {
                "label": "Additional Output Mappings (JSON)",
                "description": "Additional state fields to set from the response. Keys are field names, values are true to copy.",
            },
            "set_complete": {
                "label": "Mark Complete After",
                "description": "Set is_complete=True after execution.",
            },
        },
        output_ports={"default": {"label": "Next"}},
        groups={"prompt": "Prompt", "output": "Output"},
        help=_help(
            "LLM Call Node",
            "A generic LLM invocation node that sends a configurable prompt to the Claude model and stores the response.",
            [
                ("Overview", (
                    "The LLM Call node is the most fundamental model node. "
                    "It sends a prompt to Claude and stores the response in a configurable state field.\n\n"
                    "Use this node whenever you need a flexible, general-purpose model call "
                    "that doesn't fit into a specialised category like classification or review."
                )),
                ("Prompt Template", (
                    "The prompt template supports **state variable substitution** using `{field_name}` syntax.\n\n"
                    "**Available variables:**\n"
                    "- `{input}` — The original user request\n"
                    "- `{answer}` — The latest generated answer\n"
                    "- `{review_feedback}` — Feedback from a review node\n"
                    "- `{last_output}` — The most recent model output\n\n"
                    "**Example:**\n"
                    "```\nSummarise the following request:\n{input}\n```"
                )),
                ("Output Configuration", (
                    "- **Output State Field**: Choose which state field receives the model response. "
                    "Default is `last_output`. You can set it to `answer`, `final_answer`, or any custom field.\n"
                    "- **Mark Complete After**: When enabled, the workflow marks `is_complete=True` after this node runs, "
                    "which signals downstream gates and the executor to finish."
                )),
                ("Usage Tips", (
                    "1. Chain multiple LLM Call nodes for multi-step reasoning.\n"
                    "2. Use different `output_field` values to keep intermediate results separate.\n"
                    "3. Place a Context Guard before this node to prevent context overflow.\n"
                    "4. Place a Post Model node after to detect completion signals and record transcripts."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="LLM 호출",
        description="범용 LLM 호출 노드. {field} 상태 변수 치환이 가능한 프롬프트 템플릿을 모델에 전송합니다. 조건부 프롬프트 전환, 다중 출력 필드 매핑, 완료 플래그를 지원합니다.",
        parameters={
            "prompt_template": {
                "label": "프롬프트 템플릿",
                "description": (
                    "모델에 전송할 프롬프트입니다. 상태 변수 치환을 위해 {필드명}을 사용하세요. "
                    "사용 가능한 필드: input, answer, review_feedback, last_output 등"
                ),
            },
            "conditional_field": {
                "label": "조건부 프롬프트 필드",
                "description": "프롬프트 전환을 위해 확인할 상태 필드입니다. 설정되고 조건이 충족되면 대체 프롬프트가 사용됩니다.",
            },
            "conditional_check": {
                "label": "조건부 확인",
                "description": "조건부 필드를 어떻게 평가할지 설정합니다.",
            },
            "alternative_prompt": {
                "label": "대체 프롬프트",
                "description": "조건부 필드 확인을 통과했을 때 사용되는 프롬프트입니다.",
            },
            "output_field": {
                "label": "출력 상태 필드",
                "description": "모델 응답을 저장할 상태 필드를 지정합니다.",
            },
            "output_mappings": {
                "label": "추가 출력 매핑 (JSON)",
                "description": "응답에서 설정할 추가 상태 필드입니다. 키는 필드명, 값은 응답 복사 여부(true)입니다.",
            },
            "set_complete": {
                "label": "실행 후 완료 처리",
                "description": "실행 후 is_complete=True로 설정합니다.",
            },
        },
        output_ports={"default": {"label": "다음"}},
        groups={"prompt": "프롬프트", "output": "출력"},
        help=_help(
            "LLM 호출 노드",
            "구성 가능한 프롬프트를 Claude 모델에 전송하고 응답을 저장하는 범용 LLM 호출 노드입니다.",
            [
                ("개요", (
                    "LLM 호출 노드는 가장 기본적인 모델 노드입니다. "
                    "Claude에 프롬프트를 전송하고 응답을 구성 가능한 상태 필드에 저장합니다.\n\n"
                    "분류나 리뷰 같은 특수 카테고리에 해당하지 않는 유연한 범용 모델 호출이 필요할 때 사용하세요."
                )),
                ("프롬프트 템플릿", (
                    "프롬프트 템플릿은 `{필드명}` 문법을 사용한 **상태 변수 치환**을 지원합니다.\n\n"
                    "**사용 가능한 변수:**\n"
                    "- `{input}` — 원본 사용자 요청\n"
                    "- `{answer}` — 최신 생성된 답변\n"
                    "- `{review_feedback}` — 리뷰 노드의 피드백\n"
                    "- `{last_output}` — 가장 최근 모델 출력\n\n"
                    "**예시:**\n"
                    "```\n다음 요청을 요약하세요:\n{input}\n```"
                )),
                ("출력 구성", (
                    "- **출력 상태 필드**: 모델 응답을 받을 상태 필드를 선택합니다. "
                    "기본값은 `last_output`입니다. `answer`, `final_answer` 또는 커스텀 필드로 설정할 수 있습니다.\n"
                    "- **실행 후 완료 처리**: 활성화하면 이 노드 실행 후 `is_complete=True`로 설정되어 "
                    "하류 게이트와 실행기에 완료 신호를 보냅니다."
                )),
                ("사용 팁", (
                    "1. 여러 LLM 호출 노드를 체이닝하여 다단계 추론을 수행하세요.\n"
                    "2. 서로 다른 `output_field` 값을 사용하여 중간 결과를 분리 보관하세요.\n"
                    "3. 이 노드 앞에 컨텍스트 가드를 배치하여 컨텍스트 오버플로를 방지하세요.\n"
                    "4. 뒤에 후처리 노드를 배치하여 완료 신호 감지 및 트랜스크립트 기록을 수행하세요."
                )),
            ],
        ),
    ),
}

CLASSIFY_I18N = {
    "en": NodeI18n(
        label="Classify",
        description="General-purpose LLM classification node. Sends a prompt to the model, parses the response into a configured category, and routes execution directly through the matching output port.",
        parameters={
            "prompt_template": {
                "label": "Classification Prompt",
                "description": "Prompt sent to the model for classification. Use {input} for the user request.",
            },
            "categories": {
                "label": "Categories",
                "description": "Category names for classification (comma-separated). Each becomes an output port for routing.",
            },
            "default_category": {
                "label": "Default Category",
                "description": "Fallback category when the model response doesn't match any configured category.",
            },
            "output_field": {
                "label": "Output State Field",
                "description": "State field to store the classification result in.",
            },
        },
        output_ports={
            "easy": {"label": "Easy", "description": "Simple, direct tasks"},
            "medium": {"label": "Medium", "description": "Moderate complexity"},
            "hard": {"label": "Hard", "description": "Complex, multi-step tasks"},
            "end": {"label": "End", "description": "Error / early termination"},
        },
        groups={"prompt": "Prompt", "routing": "Routing", "output": "Output"},
        help=_help(
            "Classify Node",
            "Classifies input into configurable categories via LLM analysis and routes execution through the matching output port.",
            [
                ("Overview", (
                    "This is a **conditional model node** that acts as a decision hub. "
                    "It sends the user's input to the model with a classification prompt, "
                    "parses the response for category keywords, and routes execution "
                    "directly through the matching output port.\n\n"
                    "Default categories (easy/medium/hard) map to difficulty-based routing, "
                    "but you can configure **any set of categories** for any classification task:\n"
                    "- Sentiment: positive / negative / neutral\n"
                    "- Priority: low / medium / high / critical\n"
                    "- Type: question / request / complaint / feedback"
                )),
                ("How Classification Works", (
                    "1. The configured prompt is sent to the model (with `{input}` substitution).\n"
                    "2. The model's response is scanned for category keywords (case-insensitive).\n"
                    "3. The first matching category determines the output port.\n"
                    "4. If no keyword matches, the **Default Category** is used.\n"
                    "5. On error, execution routes to the **end** port.\n\n"
                    "The classification result is stored in the configured state field "
                    "(default: `difficulty`)."
                )),
                ("Customisation", (
                    "- **Categories**: Enter comma-separated category names (e.g. `low, medium, high, critical`). "
                    "Each category automatically becomes an output port.\n"
                    "- **Prompt**: Write a domain-specific prompt that asks the model "
                    "to respond with exactly one of your category names.\n"
                    "- **Output Field**: Store the result in any state field, not just `difficulty`.\n"
                    "- **Default**: Set which category to fall back to on ambiguous responses."
                )),
                ("Usage Tips", (
                    "1. Connect **all output ports** to valid downstream nodes (including 'end').\n"
                    "2. This node routes directly — no separate ConditionalRouter is needed.\n"
                    "3. Place a Context Guard before this node to check token budget.\n"
                    "4. Place Memory Inject before this node to provide context to the classifier."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="분류",
        description="범용 LLM 분류 노드. 모델에 프롬프트를 전송하고, 응답을 구성된 카테고리로 파싱한 후, 해당 출력 포트를 통해 실행을 직접 라우팅합니다.",
        parameters={
            "prompt_template": {
                "label": "분류 프롬프트",
                "description": "분류를 위해 모델에 전송하는 프롬프트입니다. {input}은 사용자 요청입니다.",
            },
            "categories": {
                "label": "카테고리",
                "description": "분류 카테고리 이름 (쉼표로 구분). 각각 라우팅을 위한 출력 포트가 됩니다.",
            },
            "default_category": {
                "label": "기본 카테고리",
                "description": "모델 응답이 구성된 카테고리와 일치하지 않을 때 사용하는 대체 카테고리입니다.",
            },
            "output_field": {
                "label": "출력 상태 필드",
                "description": "분류 결과를 저장할 상태 필드입니다.",
            },
        },
        output_ports={
            "easy": {"label": "쉬움", "description": "단순하고 직접적인 작업"},
            "medium": {"label": "보통", "description": "중간 수준의 복잡도"},
            "hard": {"label": "어려움", "description": "복잡한 다단계 작업"},
            "end": {"label": "종료", "description": "오류 / 조기 종료"},
        },
        groups={"prompt": "프롬프트", "routing": "라우팅", "output": "출력"},
        help=_help(
            "분류 노드",
            "LLM 분석을 통해 입력을 구성 가능한 카테고리로 분류하고 해당 출력 포트를 통해 실행을 라우팅합니다.",
            [
                ("개요", (
                    "이것은 결정 허브 역할을 하는 **조건부 모델 노드**입니다. "
                    "사용자의 입력을 분류 프롬프트와 함께 모델에 전송하고, "
                    "응답에서 카테고리 키워드를 파싱하여 해당 출력 포트로 "
                    "실행을 직접 라우팅합니다.\n\n"
                    "기본 카테고리(easy/medium/hard)는 난이도 기반 라우팅에 사용되지만, "
                    "**모든 분류 작업**에 대해 임의의 카테고리를 구성할 수 있습니다:\n"
                    "- 감성 분석: positive / negative / neutral\n"
                    "- 우선도: low / medium / high / critical\n"
                    "- 유형: question / request / complaint / feedback"
                )),
                ("분류 작동 방식", (
                    "1. 구성된 프롬프트가 모델에 전송됩니다 (`{input}` 치환 포함).\n"
                    "2. 모델 응답에서 카테고리 키워드를 검색합니다 (대소문자 구분 없음).\n"
                    "3. 첫 번째 일치하는 카테고리가 출력 포트를 결정합니다.\n"
                    "4. 키워드가 일치하지 않으면 **기본 카테고리**가 사용됩니다.\n"
                    "5. 오류 발생 시 **종료** 포트로 라우팅됩니다.\n\n"
                    "분류 결과는 구성된 상태 필드(기본값: `difficulty`)에 저장됩니다."
                )),
                ("커스터마이즈", (
                    "- **카테고리**: 쉼표로 구분하여 입력하세요 (예: `low, medium, high, critical`). "
                    "각 카테고리가 자동으로 출력 포트가 됩니다.\n"
                    "- **프롬프트**: 모델이 카테고리 이름 중 정확히 하나로 응답하도록 "
                    "도메인별 프롬프트를 작성하세요.\n"
                    "- **출력 필드**: `difficulty`뿐 아니라 모든 상태 필드에 결과를 저장 가능.\n"
                    "- **기본값**: 모호한 응답 시 어떤 카테고리로 대체할지 설정하세요."
                )),
                ("사용 팁", (
                    "1. **모든 출력 포트**를 유효한 하류 노드에 연결하세요 ('종료' 포함).\n"
                    "2. 이 노드는 직접 라우팅합니다 — 별도의 ConditionalRouter가 필요 없습니다.\n"
                    "3. 토큰 예산을 확인하려면 이 노드 앞에 컨텍스트 가드를 배치하세요.\n"
                    "4. 분류기에 컨텍스트를 제공하려면 메모리 주입 노드를 앞에 배치하세요."
                )),
            ],
        ),
    ),
}

# Backward‐compatibility alias
CLASSIFY_DIFFICULTY_I18N = CLASSIFY_I18N

DIRECT_ANSWER_I18N = {
    "en": NodeI18n(
        label="Direct Answer",
        description="Generates a single-shot direct answer without review. Best for easy tasks that need no quality checking. Writes the response to configurable output fields and can mark the workflow as complete.",
        parameters={
            "prompt_template": {
                "label": "Prompt Template",
                "description": "Prompt template. {input} is the user request.",
            },
            "output_fields": {
                "label": "Output Fields (JSON)",
                "description": "State fields to store the response in. Example: [\"answer\", \"final_answer\"]",
            },
            "mark_complete": {
                "label": "Mark Complete",
                "description": "Set is_complete=True after execution.",
            },
        },
        output_ports={"default": {"label": "Next"}},
        groups={"prompt": "Prompt", "output": "Output"},
        help=_help(
            "Direct Answer Node",
            "Generates a single-shot answer for simple tasks without review or iteration.",
            [
                ("Overview", (
                    "The Direct Answer node handles the **easy path** of the autonomous workflow. "
                    "It generates a single response and immediately marks the task as complete.\n\n"
                    "This is the fastest execution path — no review loop, no TODO decomposition. "
                    "Ideal for straightforward questions, lookups, and simple requests."
                )),
                ("Prompt Configuration", (
                    "The prompt template receives `{input}` — the user's original request.\n\n"
                    "Since there is no review step, make your prompt as clear and complete as possible. "
                    "Consider including output format instructions if needed.\n\n"
                    "**Example:**\n"
                    "```\nProvide a clear, concise answer:\n{input}\n```"
                )),
                ("State Updates", (
                    "After execution, this node sets:\n"
                    "- `answer` — the generated response\n"
                    "- `final_answer` — same as answer (since no review)\n"
                    "- `is_complete = True` — signals workflow completion\n"
                    "- `last_output` — the raw model response"
                )),
                ("Usage Tips", (
                    "1. Connect from the 'Easy' port of Classify Difficulty.\n"
                    "2. Follow with a Post Model node for transcript recording.\n"
                    "3. No need for a review loop — this path is designed for speed.\n"
                    "4. If quality is important, route to Medium path instead."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="직접 답변",
        description="리뷰 없이 단일 직접 답변을 생성합니다. 품질 검토가 필요 없는 쉬운 작업에 최적입니다. 구성 가능한 출력 필드에 응답을 저장하고 워크플로우를 완료로 표시할 수 있습니다.",
        parameters={
            "prompt_template": {
                "label": "프롬프트 템플릿",
                "description": "프롬프트 템플릿입니다. {input}은 사용자 요청입니다.",
            },
            "output_fields": {
                "label": "출력 필드 (JSON)",
                "description": "응답을 저장할 상태 필드 목록입니다. 예: [\"answer\", \"final_answer\"]",
            },
            "mark_complete": {
                "label": "완료 표시",
                "description": "실행 후 is_complete=True로 설정합니다.",
            },
        },
        output_ports={"default": {"label": "다음"}},
        groups={"prompt": "프롬프트", "output": "출력"},
        help=_help(
            "직접 답변 노드",
            "리뷰나 반복 없이 단순 작업에 대해 단일 응답을 생성합니다.",
            [
                ("개요", (
                    "직접 답변 노드는 자율 워크플로우의 **쉬움 경로**를 처리합니다. "
                    "단일 응답을 생성하고 즉시 작업을 완료로 표시합니다.\n\n"
                    "이것은 가장 빠른 실행 경로입니다 — 리뷰 루프도, TODO 분해도 없습니다. "
                    "단순한 질문, 조회, 간단한 요청에 이상적입니다."
                )),
                ("프롬프트 구성", (
                    "프롬프트 템플릿은 `{input}` — 사용자의 원본 요청을 받습니다.\n\n"
                    "리뷰 단계가 없으므로 프롬프트를 가능한 한 명확하고 완전하게 작성하세요. "
                    "필요한 경우 출력 형식 지시사항을 포함하세요.\n\n"
                    "**예시:**\n"
                    "```\n명확하고 간결한 답변을 제공하세요:\n{input}\n```"
                )),
                ("상태 업데이트", (
                    "실행 후 이 노드는 다음을 설정합니다:\n"
                    "- `answer` — 생성된 응답\n"
                    "- `final_answer` — answer와 동일 (리뷰가 없으므로)\n"
                    "- `is_complete = True` — 워크플로우 완료 신호\n"
                    "- `last_output` — 원시 모델 응답"
                )),
                ("사용 팁", (
                    "1. 난이도 분류의 '쉬움' 포트에서 연결하세요.\n"
                    "2. 트랜스크립트 기록을 위해 후처리 노드를 뒤에 배치하세요.\n"
                    "3. 리뷰 루프가 필요 없습니다 — 이 경로는 속도에 최적화되어 있습니다.\n"
                    "4. 품질이 중요한 경우 보통 경로로 라우팅하세요."
                )),
            ],
        ),
    ),
}

ANSWER_I18N = {
    "en": NodeI18n(
        label="Answer",
        description="Generates an answer with optional review feedback integration for iterative improvement. Automatically switches to the retry template with feedback context on retries. Budget-aware prompt compaction.",
        parameters={
            "prompt_template": {
                "label": "Prompt Template",
                "description": "Prompt for the initial answer.",
            },
            "retry_template": {
                "label": "Retry Prompt Template",
                "description": "Prompt template when retrying after review rejection.",
            },
            "feedback_field": {
                "label": "Feedback State Field",
                "description": "State field containing review feedback.",
            },
            "count_field": {
                "label": "Review Count State Field",
                "description": "State field tracking the number of review cycles.",
            },
            "output_fields": {
                "label": "Output Fields (JSON)",
                "description": "State fields to store the response in.",
            },
        },
        output_ports={"default": {"label": "Next"}},
        groups={"prompt": "Prompt", "state_fields": "State Fields", "output": "Output"},
        help=_help(
            "Answer Node",
            "Generates answers for medium-complexity tasks, incorporating review feedback on retries.",
            [
                ("Overview", (
                    "The Answer node handles the **medium path** of the autonomous workflow. "
                    "It generates an answer that can be reviewed and refined through a feedback loop.\n\n"
                    "On the first run, it uses the main prompt template. "
                    "On subsequent retries (after review rejection), it switches to the retry template "
                    "which includes the review feedback."
                )),
                ("Prompt Templates", (
                    "**Initial Prompt**: Used for the first answer attempt. Receives `{input}`.\n\n"
                    "**Retry Prompt**: Used when the review node rejects the answer. Receives:\n"
                    "- `{input_text}` — the original request\n"
                    "- `{previous_feedback}` — the review feedback\n\n"
                    "The retry template is automatically activated when `review_count > 0`."
                )),
                ("Review Integration", (
                    "This node is designed to work with the **Review** node:\n\n"
                    "1. Answer generates a response\n"
                    "2. Review evaluates the response\n"
                    "3. If rejected, Answer is called again with feedback\n"
                    "4. Cycle repeats until approved or max retries reached"
                )),
                ("Usage Tips", (
                    "1. Connect to the 'Medium' port of Classify Difficulty.\n"
                    "2. Follow with a Review node for quality assurance.\n"
                    "3. Loop the Review's 'Retry' port back to this node.\n"
                    "4. The answer is stored in the `answer` state field."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="답변",
        description="반복적 개선을 위한 선택적 리뷰 피드백 통합과 함께 답변을 생성합니다. 재시도 시 피드백 컨텍스트가 포함된 재시도 템플릿으로 자동 전환됩니다. 예산 인식 프롬프트 압축을 지원합니다.",
        parameters={
            "prompt_template": {
                "label": "프롬프트 템플릿",
                "description": "초기 답변을 위한 프롬프트입니다.",
            },
            "retry_template": {
                "label": "재시도 프롬프트 템플릿",
                "description": "리뷰 거부 후 재시도 시 사용하는 프롬프트 템플릿입니다.",
            },
            "feedback_field": {
                "label": "피드백 상태 필드",
                "description": "리뷰 피드백이 포함된 상태 필드입니다.",
            },
            "count_field": {
                "label": "리뷰 횟수 상태 필드",
                "description": "리뷰 사이클 수를 추적하는 상태 필드입니다.",
            },
            "output_fields": {
                "label": "출력 필드 (JSON)",
                "description": "응답을 저장할 상태 필드 목록입니다.",
            },
        },
        output_ports={"default": {"label": "다음"}},
        groups={"prompt": "프롬프트", "state_fields": "상태 필드", "output": "출력"},
        help=_help(
            "답변 노드",
            "중간 복잡도 작업에 대한 답변을 생성하며, 재시도 시 리뷰 피드백을 반영합니다.",
            [
                ("개요", (
                    "답변 노드는 자율 워크플로우의 **보통 경로**를 처리합니다. "
                    "피드백 루프를 통해 리뷰되고 개선될 수 있는 답변을 생성합니다.\n\n"
                    "첫 번째 실행에서는 메인 프롬프트 템플릿을 사용합니다. "
                    "이후 재시도 시(리뷰 거부 후)에는 리뷰 피드백이 포함된 "
                    "재시도 템플릿으로 전환됩니다."
                )),
                ("프롬프트 템플릿", (
                    "**초기 프롬프트**: 첫 번째 답변 시도에 사용됩니다. `{input}`을 받습니다.\n\n"
                    "**재시도 프롬프트**: 리뷰 노드가 답변을 거부했을 때 사용됩니다. 수신 변수:\n"
                    "- `{input_text}` — 원본 요청\n"
                    "- `{previous_feedback}` — 리뷰 피드백\n\n"
                    "재시도 템플릿은 `review_count > 0`일 때 자동으로 활성화됩니다."
                )),
                ("리뷰 연동", (
                    "이 노드는 **리뷰** 노드와 함께 작동하도록 설계되었습니다:\n\n"
                    "1. 답변이 응답을 생성합니다\n"
                    "2. 리뷰가 응답을 평가합니다\n"
                    "3. 거부되면 피드백과 함께 답변이 다시 호출됩니다\n"
                    "4. 승인될 때까지 또는 최대 재시도 횟수에 도달할 때까지 반복됩니다"
                )),
                ("사용 팁", (
                    "1. 난이도 분류의 '보통' 포트에서 연결하세요.\n"
                    "2. 품질 보증을 위해 리뷰 노드를 뒤에 배치하세요.\n"
                    "3. 리뷰의 '재시도' 포트를 이 노드로 다시 루프하세요.\n"
                    "4. 답변은 `answer` 상태 필드에 저장됩니다."
                )),
            ],
        ),
    ),
}

REVIEW_I18N = {
    "en": NodeI18n(
        label="Review",
        description=(
            "Self-routing quality gate that reviews a generated answer via LLM "
            "and routes to a configurable set of verdict ports. "
            "Parses structured VERDICT/FEEDBACK lines from the model response. "
            "Each configured verdict becomes an output port. "
            "Forces the first verdict after max retries to prevent infinite loops."
        ),
        parameters={
            "prompt_template": {
                "label": "Review Prompt",
                "description": "Prompt template for the quality review.",
            },
            "verdicts": {
                "label": "Verdicts (JSON)",
                "description": (
                    "List of verdict names the LLM may emit. Each becomes an output port. "
                    'Example: ["approved", "retry"] or ["pass", "minor_fix", "major_rewrite"]'
                ),
            },
            "default_verdict": {
                "label": "Default Verdict",
                "description": "Verdict to use when the model's response doesn't match any configured verdict.",
            },
            "output_field": {
                "label": "Output State Field",
                "description": "State field to store the matched verdict string.",
            },
            "max_retries": {
                "label": "Max Review Retries",
                "description": "Force the first verdict (typically 'approved') after this many review cycles.",
            },
            "answer_field": {
                "label": "Answer State Field",
                "description": "State field containing the answer to review.",
            },
            "count_field": {
                "label": "Review Count State Field",
                "description": "State field tracking the review cycle count.",
            },
        },
        output_ports={
            "approved": {"label": "Approved", "description": "Answer passed review"},
            "retry": {"label": "Retry", "description": "Answer needs improvement"},
            "end": {"label": "End", "description": "Error or early termination"},
        },
        groups={
            "prompt": "Prompt",
            "routing": "Routing",
            "behavior": "Behavior",
            "output": "Output",
            "state_fields": "State Fields",
        },
        help=_help(
            "Review Node",
            "Self-routing quality gate that reviews answers and routes by verdict — like Classify, each verdict becomes a port.",
            [
                ("Overview", (
                    "The Review node is a **self-routing conditional node** that evaluates the quality of a generated answer. "
                    "It sends the question and answer to the model for assessment, "
                    "then parses a structured VERDICT/FEEDBACK response.\n\n"
                    "Like the Classify node, the **Verdicts** parameter uses ``generates_ports``: "
                    "each configured verdict becomes a named output port. "
                    "An additional **End** port is always present for errors.\n\n"
                    "**Default ports (with default verdicts):**\n"
                    "- **Approved** — answer meets quality standards\n"
                    "- **Retry** — answer needs improvement (feedback provided)\n"
                    "- **End** — error or early termination"
                )),
                ("Configurable Verdicts", (
                    "The **Verdicts** parameter accepts a JSON list of verdict names:\n\n"
                    '- Default: ``["approved", "retry"]``\n'
                    '- Custom: ``["pass", "minor_fix", "major_rewrite"]``\n\n'
                    "Each verdict becomes an output port. The LLM's ``VERDICT:`` line "
                    "is matched against these keywords. If no match, the **Default Verdict** is used."
                )),
                ("Review Format", (
                    "The model is required to respond with a **structured JSON output** "
                    "containing ``verdict`` and ``feedback`` fields:\n\n"
                    '```json\n{"verdict": "approved", "feedback": "Good answer."}\n```\n\n'
                    "The node uses Pydantic schema validation to enforce the output format. "
                    "If the initial response fails validation, an automatic correction retry is attempted."
                )),
                ("Max Retries", (
                    "The **Max Review Retries** parameter prevents infinite review loops. "
                    "After this many cycles, the **first verdict** in the list "
                    "(typically 'approved') is forced regardless of model output.\n\n"
                    "Default: 3 cycles. Range: 1–10."
                )),
                ("Usage Tips", (
                    "1. Connect after an Answer node (optionally via a Guard).\n"
                    "2. Wire verdict ports directly — no separate router node needed.\n"
                    "3. Loop 'Retry' back to a Guard node to re-enter the answer loop.\n"
                    "4. Review feedback is stored in ``review_feedback`` state field.\n"
                    "5. Review cycle count is tracked in the configured Count Field."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="리뷰",
        description=(
            "LLM을 통해 생성된 답변을 리뷰하고 구성 가능한 판정 포트로 라우팅하는 "
            "자체 라우팅 품질 게이트입니다. 모델 응답에서 구조화된 VERDICT/FEEDBACK 라인을 파싱합니다. "
            "각 구성된 판정은 출력 포트가 됩니다. "
            "무한 루프 방지를 위해 최대 재시도 후 첫 번째 판정을 강제합니다."
        ),
        parameters={
            "prompt_template": {
                "label": "리뷰 프롬프트",
                "description": "품질 리뷰를 위한 프롬프트 템플릿입니다.",
            },
            "verdicts": {
                "label": "판정 목록 (JSON)",
                "description": (
                    "LLM이 출력할 수 있는 판정 이름 목록입니다. 각 판정이 출력 포트가 됩니다. "
                    '예: ["approved", "retry"] 또는 ["pass", "minor_fix", "major_rewrite"]'
                ),
            },
            "default_verdict": {
                "label": "기본 판정",
                "description": "모델 응답이 어떤 판정과도 일치하지 않을 때 사용할 판정입니다.",
            },
            "output_field": {
                "label": "출력 상태 필드",
                "description": "일치된 판정 문자열을 저장할 상태 필드입니다.",
            },
            "max_retries": {
                "label": "최대 리뷰 재시도",
                "description": "이 횟수만큼 리뷰 사이클 후 첫 번째 판정(보통 'approved')을 강제합니다.",
            },
            "answer_field": {
                "label": "답변 상태 필드",
                "description": "리뷰할 답변이 포함된 상태 필드입니다.",
            },
            "count_field": {
                "label": "리뷰 횟수 상태 필드",
                "description": "리뷰 사이클 횟수를 추적하는 상태 필드입니다.",
            },
        },
        output_ports={
            "approved": {"label": "승인", "description": "답변이 리뷰를 통과함"},
            "retry": {"label": "재시도", "description": "답변 개선 필요"},
            "end": {"label": "종료", "description": "오류 또는 조기 종료"},
        },
        groups={
            "prompt": "프롬프트",
            "routing": "라우팅",
            "behavior": "동작",
            "parsing": "파싱",
            "output": "출력",
            "state_fields": "상태 필드",
        },
        help=_help(
            "리뷰 노드",
            "답변을 리뷰하고 판정별로 라우팅하는 자체 라우팅 품질 게이트 — Classify처럼 각 판정이 포트가 됩니다.",
            [
                ("개요", (
                    "리뷰 노드는 생성된 답변의 품질을 평가하는 **자체 라우팅 조건부 노드**입니다. "
                    "질문과 답변을 모델에 전송하여 평가하고, "
                    "구조화된 VERDICT/FEEDBACK 응답을 파싱합니다.\n\n"
                    "Classify 노드처럼 **판정 목록** 파라미터가 ``generates_ports``를 사용합니다: "
                    "각 구성된 판정이 이름 있는 출력 포트가 됩니다. "
                    "추가로 **종료** 포트가 항상 오류용으로 존재합니다.\n\n"
                    "**기본 포트 (기본 판정 사용 시):**\n"
                    "- **승인** — 답변이 품질 기준을 충족함\n"
                    "- **재시도** — 답변 개선 필요 (피드백 제공)\n"
                    "- **종료** — 오류 또는 조기 종료"
                )),
                ("구성 가능한 판정", (
                    "**판정 목록** 파라미터는 판정 이름의 JSON 목록을 받습니다:\n\n"
                    '- 기본값: ``["approved", "retry"]``\n'
                    '- 커스텀: ``["pass", "minor_fix", "major_rewrite"]``\n\n'
                    "각 판정이 출력 포트가 됩니다. LLM의 ``VERDICT:`` 줄이 "
                    "이 키워드와 매칭됩니다. 일치하지 않으면 **기본 판정**이 사용됩니다."
                )),
                ("리뷰 형식", (
                    "모델은 구조화된 형식으로 응답해야 합니다:\n\n"
                    "```\nVERDICT: approved\nFEEDBACK: <개선 제안>\n```\n\n"
                    "노드는 이를 파싱하여 라우팅을 결정합니다. "
                    "형식이 감지되지 않으면 전체 응답이 피드백으로 처리되고 "
                    "전체 텍스트에서 키워드 매칭이 시도됩니다."
                )),
                ("최대 재시도", (
                    "**최대 리뷰 재시도** 파라미터는 무한 리뷰 루프를 방지합니다. "
                    "이 횟수만큼 사이클 후에는 목록의 **첫 번째 판정** "
                    "(보통 'approved')이 모델 출력에 관계없이 강제됩니다.\n\n"
                    "기본값: 3회 사이클. 범위: 1~10."
                )),
                ("사용 팁", (
                    "1. 답변 노드 뒤에 연결하세요 (선택적으로 가드를 통해).\n"
                    "2. 판정 포트를 직접 연결하세요 — 별도의 라우터 노드가 필요 없습니다.\n"
                    "3. '재시도'를 가드 노드로 루프하여 답변 루프에 재진입하세요.\n"
                    "4. 리뷰 피드백은 ``review_feedback`` 상태 필드에 저장됩니다.\n"
                    "5. 리뷰 사이클 횟수는 구성된 횟수 필드에서 추적됩니다."
                )),
            ],
        ),
    ),
}


# ====================================================================
#  LOGIC NODES
# ====================================================================

CONDITIONAL_ROUTER_I18N = {
    "en": NodeI18n(
        label="Conditional Router",
        description="Pure state-based routing node. Reads a specified state field and maps its value to output ports via a configurable JSON route map. Handles enums, strings, and other types with automatic normalization.",
        parameters={
            "routing_field": {
                "label": "Routing State Field",
                "description": "Name of the state field to read for routing decisions.",
            },
            "route_map": {
                "label": "Route Mapping (JSON)",
                "description": (
                    "JSON object mapping field values to output port IDs. "
                    'Example: {"value1": "port_a", "value2": "port_b"}'
                ),
            },
            "default_port": {
                "label": "Default Port",
                "description": "Port to use when the field value doesn't match any route.",
            },
        },
        output_ports={"default": {"label": "Default", "description": "Fallback route"}},
        groups={"routing": "Routing"},
        help=_help(
            "Conditional Router Node",
            "A flexible routing node that reads a state field and routes to different output ports based on its value.",
            [
                ("Overview", (
                    "The Conditional Router is a **generic branching node** for building custom control flow. "
                    "It reads a configurable state field and maps its value to one of several output ports.\n\n"
                    "Unlike specialised conditional nodes (Classify Difficulty, Review), this router "
                    "lets you define your own routing logic for any state field."
                )),
                ("Route Mapping", (
                    "Define the routing rules as a JSON object:\n\n"
                    "```json\n{\n  \"easy\": \"simple_path\",\n  \"medium\": \"standard_path\",\n  \"hard\": \"complex_path\"\n}\n```\n\n"
                    "**Keys** are the possible values of the routing field.\n"
                    "**Values** are the output port IDs to route to.\n\n"
                    "Output ports are automatically generated from the route map values."
                )),
                ("Default Port", (
                    "When the state field value doesn't match any route in the map, "
                    "execution is sent to the **Default Port**.\n\n"
                    "Always ensure the default port connects to a valid node to prevent dead ends."
                )),
                ("Usage Tips", (
                    "1. Use for custom branching beyond the built-in difficulty classification.\n"
                    "2. The routing field can be any state field (e.g., `difficulty`, `status`, custom fields).\n"
                    "3. Enum values are automatically converted to their string representation.\n"
                    "4. All comparisons are case-insensitive."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="조건부 라우터",
        description="순수 상태 기반 라우팅 노드. 지정된 상태 필드를 읽고 JSON 라우트 맵을 통해 값을 출력 포트에 매핑합니다. 열거형, 문자열 등을 자동 정규화하여 처리합니다.",
        parameters={
            "routing_field": {
                "label": "라우팅 상태 필드",
                "description": "라우팅 결정을 위해 읽을 상태 필드의 이름입니다.",
            },
            "route_map": {
                "label": "라우트 매핑 (JSON)",
                "description": (
                    "필드 값을 출력 포트 ID에 매핑하는 JSON 객체입니다. "
                    '예시: {"value1": "port_a", "value2": "port_b"}'
                ),
            },
            "default_port": {
                "label": "기본 포트",
                "description": "필드 값이 어떤 라우트와도 일치하지 않을 때 사용할 포트입니다.",
            },
        },
        output_ports={"default": {"label": "기본", "description": "대체 경로"}},
        groups={"routing": "라우팅"},
        help=_help(
            "조건부 라우터 노드",
            "상태 필드를 읽고 값에 따라 다른 출력 포트로 라우팅하는 유연한 라우팅 노드입니다.",
            [
                ("개요", (
                    "조건부 라우터는 커스텀 제어 흐름을 구축하기 위한 **범용 분기 노드**입니다. "
                    "구성 가능한 상태 필드를 읽고 값을 여러 출력 포트 중 하나에 매핑합니다.\n\n"
                    "특수 조건부 노드(난이도 분류, 리뷰)와 달리 이 라우터는 "
                    "모든 상태 필드에 대해 자체 라우팅 로직을 정의할 수 있습니다."
                )),
                ("라우트 매핑", (
                    "라우팅 규칙을 JSON 객체로 정의하세요:\n\n"
                    "```json\n{\n  \"easy\": \"simple_path\",\n  \"medium\": \"standard_path\",\n  \"hard\": \"complex_path\"\n}\n```\n\n"
                    "**키**는 라우팅 필드의 가능한 값입니다.\n"
                    "**값**은 라우팅할 출력 포트 ID입니다.\n\n"
                    "출력 포트는 라우트 맵 값에서 자동으로 생성됩니다."
                )),
                ("기본 포트", (
                    "상태 필드 값이 맵의 어떤 라우트와도 일치하지 않으면 "
                    "실행이 **기본 포트**로 전송됩니다.\n\n"
                    "데드 엔드를 방지하기 위해 기본 포트가 항상 유효한 노드에 연결되어 있는지 확인하세요."
                )),
                ("사용 팁", (
                    "1. 내장 난이도 분류를 넘어서는 커스텀 분기에 사용하세요.\n"
                    "2. 라우팅 필드는 모든 상태 필드가 될 수 있습니다 (예: `difficulty`, `status`, 커스텀 필드).\n"
                    "3. 열거형 값은 자동으로 문자열 표현으로 변환됩니다.\n"
                    "4. 모든 비교는 대소문자를 구분하지 않습니다."
                )),
            ],
        ),
    ),
}

ITERATION_GATE_I18N = {
    "en": NodeI18n(
        label="Iteration Gate",
        description="Loop prevention guard that checks multiple stop conditions: iteration count, context budget, completion signals, and an optional custom field. Sets is_complete=True when any limit is exceeded.",
        parameters={
            "max_iterations_override": {
                "label": "Max Iterations Override",
                "description": "Override the global max iterations. 0 = use default.",
            },
            "check_iteration": {
                "label": "Check Iteration Limit",
                "description": "Enable checking against the iteration counter.",
            },
            "check_budget": {
                "label": "Check Context Budget",
                "description": "Enable checking context window budget status.",
            },
            "check_completion": {
                "label": "Check Completion Signals",
                "description": "Enable checking for structured completion signals.",
            },
            "custom_stop_field": {
                "label": "Custom Stop Field",
                "description": "Additional state field to check. If truthy, the gate will stop. Leave empty to disable.",
            },
        },
        output_ports={
            "continue": {"label": "Continue", "description": "Loop can proceed"},
            "stop": {"label": "Stop", "description": "Limit exceeded, exit loop"},
        },
        groups={"behavior": "Behavior", "checks": "Checks"},
        help=_help(
            "Iteration Gate Node",
            "Safety gate that prevents infinite loops by checking iteration count, context budget, and completion signals.",
            [
                ("Overview", (
                    "The Iteration Gate is a critical **safety node** that prevents runaway execution. "
                    "It checks three conditions:\n\n"
                    "1. **Iteration limit** — has the loop exceeded the maximum allowed iterations?\n"
                    "2. **Context budget** — is the context window overflowing or blocked?\n"
                    "3. **Completion signal** — did a previous node signal completion?\n\n"
                    "If any condition triggers, execution routes to the **Stop** port."
                )),
                ("Iteration Tracking", (
                    "Each loop iteration increments the `iteration` state counter. "
                    "The gate compares this against the configured maximum.\n\n"
                    "- **Override = 0**: Uses the global `max_iterations` from state (default: 50)\n"
                    "- **Override > 0**: Uses the override value instead"
                )),
                ("Context Budget Check", (
                    "The gate reads `context_budget.status` from state. "
                    "If the status is `block` or `overflow`, the loop is stopped to prevent errors.\n\n"
                    "This works in conjunction with the Context Guard node."
                )),
                ("Usage Tips", (
                    "1. Place at the start of any loop to prevent infinite execution.\n"
                    "2. Essential in the hard path where TODO execution loops.\n"
                    "3. The 'Stop' port should connect to an end or synthesis node.\n"
                    "4. The 'Continue' port continues the loop."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="반복 게이트",
        description="다중 정지 조건을 확인하는 루프 방지 가드: 반복 횟수, 컨텍스트 예산, 완료 신호, 선택적 사용자 정의 필드. 제한 초과 시 is_complete=True를 설정합니다.",
        parameters={
            "max_iterations_override": {
                "label": "최대 반복 횟수 오버라이드",
                "description": "전역 최대 반복 횟수를 오버라이드합니다. 0 = 기본값 사용.",
            },
            "check_iteration": {
                "label": "반복 제한 확인",
                "description": "반복 카운터에 대한 확인을 활성화합니다.",
            },
            "check_budget": {
                "label": "컨텍스트 예산 확인",
                "description": "컨텍스트 윈도우 예산 상태 확인을 활성화합니다.",
            },
            "check_completion": {
                "label": "완료 신호 확인",
                "description": "구조화된 완료 신호 확인을 활성화합니다.",
            },
            "custom_stop_field": {
                "label": "사용자 정의 정지 필드",
                "description": "추가로 확인할 상태 필드입니다. 참이면 게이트가 정지합니다. 비워두면 비활성화됩니다.",
            },
        },
        output_ports={
            "continue": {"label": "계속", "description": "루프 계속 진행 가능"},
            "stop": {"label": "중지", "description": "제한 초과, 루프 종료"},
        },
        groups={"behavior": "동작", "checks": "확인 조건"},
        help=_help(
            "반복 게이트 노드",
            "반복 횟수, 컨텍스트 예산, 완료 신호를 확인하여 무한 루프를 방지하는 안전 게이트입니다.",
            [
                ("개요", (
                    "반복 게이트는 무한 실행을 방지하는 핵심 **안전 노드**입니다. "
                    "세 가지 조건을 확인합니다:\n\n"
                    "1. **반복 제한** — 루프가 최대 허용 반복 횟수를 초과했는가?\n"
                    "2. **컨텍스트 예산** — 컨텍스트 윈도우가 오버플로우 또는 차단 상태인가?\n"
                    "3. **완료 신호** — 이전 노드가 완료 신호를 보냈는가?\n\n"
                    "어떤 조건이든 트리거되면 실행이 **중지** 포트로 라우팅됩니다."
                )),
                ("반복 추적", (
                    "각 루프 반복은 `iteration` 상태 카운터를 증가시킵니다. "
                    "게이트는 이를 구성된 최대값과 비교합니다.\n\n"
                    "- **오버라이드 = 0**: 상태의 전역 `max_iterations` 사용 (기본값: 50)\n"
                    "- **오버라이드 > 0**: 오버라이드 값을 대신 사용"
                )),
                ("컨텍스트 예산 확인", (
                    "게이트는 상태에서 `context_budget.status`를 읽습니다. "
                    "상태가 `block` 또는 `overflow`이면 오류 방지를 위해 루프가 중지됩니다.\n\n"
                    "이것은 컨텍스트 가드 노드와 연동됩니다."
                )),
                ("사용 팁", (
                    "1. 무한 실행을 방지하기 위해 모든 루프의 시작 부분에 배치하세요.\n"
                    "2. TODO 실행이 루프하는 어려움 경로에서 필수적입니다.\n"
                    "3. '중지' 포트는 종료 또는 합성 노드에 연결해야 합니다.\n"
                    "4. '계속' 포트는 루프를 계속합니다."
                )),
            ],
        ),
    ),
}

CHECK_PROGRESS_I18N = {
    "en": NodeI18n(
        label="Check Progress",
        description="Checks completion progress of a configurable list field. Routes to 'continue' when items remain or 'complete' when all items are processed. Respects completion signals and error flags.",
        parameters={
            "list_field": {
                "label": "List State Field",
                "description": "State field containing the list to check progress on.",
            },
            "index_field": {
                "label": "Index State Field",
                "description": "State field tracking the current index in the list.",
            },
            "completed_status": {
                "label": "Completed Status Value",
                "description": "Status value that counts an item as completed.",
            },
            "failed_status": {
                "label": "Failed Status Value",
                "description": "Status value that counts an item as failed.",
            },
        },
        output_ports={
            "continue": {"label": "Continue", "description": "More TODOs remaining"},
            "complete": {"label": "Complete", "description": "All TODOs done"},
        },
        groups={"state_fields": "State Fields", "behavior": "Behavior"},
        help=_help(
            "Check Progress Node",
            "Checks TODO list completion and routes to continue or complete.",
            [
                ("Overview", (
                    "The Check Progress node is a **conditional node** used in the hard path "
                    "to track TODO list completion. It examines the TODO list state "
                    "and determines whether there are more items to execute.\n\n"
                    "**Routes:**\n"
                    "- **Continue** — more TODO items remain\n"
                    "- **Complete** — all TODOs are done (or a completion signal was received)"
                )),
                ("Progress Tracking", (
                    "The node reads:\n"
                    "- `current_todo_index` — which TODO is next\n"
                    "- `todos` — the full TODO list\n"
                    "- `completion_signal` — any external completion signal\n\n"
                    "It also records progress metrics in the `metadata` state field."
                )),
                ("Usage Tips", (
                    "1. Place after Execute TODO and its Post Model node.\n"
                    "2. Loop 'Continue' back to the Execute TODO sequence.\n"
                    "3. Connect 'Complete' to Final Review or Final Answer.\n"
                    "4. No parameters needed — works entirely from state."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="진행 확인",
        description="구성 가능한 목록 필드의 완료 진행률을 확인합니다. 항목이 남아있으면 'continue', 모두 처리되면 'complete'로 라우팅합니다. 완료 신호와 오류 플래그를 존중합니다.",
        parameters={
            "list_field": {
                "label": "목록 상태 필드",
                "description": "진행률을 확인할 목록이 포함된 상태 필드입니다.",
            },
            "index_field": {
                "label": "인덱스 상태 필드",
                "description": "목록의 현재 인덱스를 추적하는 상태 필드입니다.",
            },
            "completed_status": {
                "label": "완료 상태 값",
                "description": "항목을 완료로 계산하는 상태 값입니다.",
            },
            "failed_status": {
                "label": "실패 상태 값",
                "description": "항목을 실패로 계산하는 상태 값입니다.",
            },
        },
        output_ports={
            "continue": {"label": "계속", "description": "더 많은 TODO가 남아있음"},
            "complete": {"label": "완료", "description": "모든 TODO 완료"},
        },
        groups={"state_fields": "상태 필드", "behavior": "동작"},
        help=_help(
            "진행 확인 노드",
            "TODO 목록 완료를 확인하고 계속 또는 완료로 라우팅합니다.",
            [
                ("개요", (
                    "진행 확인 노드는 어려움 경로에서 TODO 목록 완료를 추적하는 데 사용되는 "
                    "**조건부 노드**입니다. TODO 목록 상태를 검사하고 "
                    "더 많은 항목을 실행해야 하는지 결정합니다.\n\n"
                    "**경로:**\n"
                    "- **계속** — 더 많은 TODO 항목이 남아있음\n"
                    "- **완료** — 모든 TODO가 완료됨 (또는 완료 신호가 수신됨)"
                )),
                ("진행 추적", (
                    "노드가 읽는 상태:\n"
                    "- `current_todo_index` — 다음 TODO 인덱스\n"
                    "- `todos` — 전체 TODO 목록\n"
                    "- `completion_signal` — 외부 완료 신호\n\n"
                    "진행 메트릭도 `metadata` 상태 필드에 기록합니다."
                )),
                ("사용 팁", (
                    "1. TODO 실행 및 후처리 노드 뒤에 배치하세요.\n"
                    "2. '계속'을 TODO 실행 시퀀스로 다시 루프하세요.\n"
                    "3. '완료'를 최종 리뷰 또는 최종 답변에 연결하세요.\n"
                    "4. 파라미터가 필요 없습니다 — 상태에서만 작동합니다."
                )),
            ],
        ),
    ),
}

STATE_SETTER_I18N = {
    "en": NodeI18n(
        label="State Setter",
        description="Directly manipulates state fields by setting them to configured JSON values. Useful for initializing state, resetting counters, or injecting static configuration.",
        parameters={
            "state_updates": {
                "label": "State Updates (JSON)",
                "description": 'JSON object of state field updates. Example: {"is_complete": true, "review_count": 0}',
            },
        },
        output_ports={"default": {"label": "Next"}},
        groups={"general": "General"},
        help=_help(
            "State Setter Node",
            "Directly manipulates state fields by setting them to configured values.",
            [
                ("Overview", (
                    "The State Setter is a utility node that sets specific state fields "
                    "to configured values. It doesn't involve the model — it's a pure "
                    "state manipulation node.\n\n"
                    "Useful for initialising state, resetting counters, or setting flags."
                )),
                ("State Updates JSON", (
                    "Provide a JSON object where each key is a state field name "
                    "and each value is what to set it to:\n\n"
                    "```json\n{\n  \"is_complete\": true,\n  \"review_count\": 0,\n  \"current_step\": \"reset\"\n}\n```\n\n"
                    "Supported value types: string, number, boolean, null, arrays, objects."
                )),
                ("Usage Tips", (
                    "1. Use at the start of a workflow to initialise state.\n"
                    "2. Use before a loop to reset counters.\n"
                    "3. Use to set `is_complete = true` to force workflow completion.\n"
                    "4. Any valid JSON object will be merged into the state."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="상태 설정",
        description="구성된 JSON 값으로 상태 필드를 직접 조작합니다. 상태 초기화, 카운터 리셋, 정적 구성 주입에 유용합니다.",
        parameters={
            "state_updates": {
                "label": "상태 업데이트 (JSON)",
                "description": '상태 필드 업데이트의 JSON 객체입니다. 예: {"is_complete": true, "review_count": 0}',
            },
        },
        output_ports={"default": {"label": "다음"}},
        groups={"general": "일반"},
        help=_help(
            "상태 설정 노드",
            "상태 필드를 구성된 값으로 직접 조작합니다.",
            [
                ("개요", (
                    "상태 설정은 특정 상태 필드를 구성된 값으로 설정하는 유틸리티 노드입니다. "
                    "모델을 사용하지 않습니다 — 순수한 상태 조작 노드입니다.\n\n"
                    "상태 초기화, 카운터 리셋, 또는 플래그 설정에 유용합니다."
                )),
                ("상태 업데이트 JSON", (
                    "각 키가 상태 필드 이름이고 각 값이 설정할 값인 JSON 객체를 제공하세요:\n\n"
                    "```json\n{\n  \"is_complete\": true,\n  \"review_count\": 0,\n  \"current_step\": \"reset\"\n}\n```\n\n"
                    "지원되는 값 타입: 문자열, 숫자, 불리언, null, 배열, 객체."
                )),
                ("사용 팁", (
                    "1. 워크플로우 시작 부분에서 상태를 초기화하는 데 사용하세요.\n"
                    "2. 루프 전에 카운터를 리셋하는 데 사용하세요.\n"
                    "3. `is_complete = true`를 설정하여 워크플로우 완료를 강제할 수 있습니다.\n"
                    "4. 유효한 모든 JSON 객체가 상태에 병합됩니다."
                )),
            ],
        ),
    ),
}


# ====================================================================
#  MEMORY NODES
# ====================================================================

MEMORY_INJECT_I18N = {
    "en": NodeI18n(
        label="Memory Inject",
        description="Loads relevant memories from the session memory manager at workflow start. Searches for memories related to the input and injects MemoryRef entries into state. Optionally records user input to transcript.",
        parameters={
            "max_results": {
                "label": "Max Memory Results",
                "description": "Maximum number of memory chunks to load.",
            },
            "search_chars": {
                "label": "Search Input Length",
                "description": "Character limit of input text used for memory search.",
            },
            "search_field": {
                "label": "Search Source Field",
                "description": "State field whose value is used as the memory search query.",
            },
            "record_input": {
                "label": "Record Input to Transcript",
                "description": "Record the search text to the short-term transcript.",
            },
        },
        output_ports={"default": {"label": "Next"}},
        groups={"behavior": "Behavior", "state_fields": "State Fields"},
        help=_help(
            "Memory Inject Node",
            "Searches the session memory for relevant context and loads it into the graph state.",
            [
                ("Overview", (
                    "The Memory Inject node connects the workflow to the session's **long-term and short-term memory**. "
                    "It searches for memories related to the current input and loads references into state.\n\n"
                    "This gives downstream model nodes access to relevant prior context, "
                    "improving the quality and consistency of responses."
                )),
                ("Memory Search", (
                    "The node performs a similarity search using the input text:\n\n"
                    "- **Max Results**: How many memory chunks to retrieve (default: 5)\n"
                    "- **Search Input Length**: How many characters of the input to use for the search (default: 500)\n\n"
                    "Results are stored as `memory_refs` in the graph state."
                )),
                ("Transcript Recording", (
                    "In addition to memory search, this node also records the user's input "
                    "to the conversation transcript for future reference."
                )),
                ("Usage Tips", (
                    "1. Place at the very beginning of the workflow, right after Start.\n"
                    "2. The memory manager must be configured for the session.\n"
                    "3. If no memories match, the node silently produces no updates.\n"
                    "4. Increase max_results for tasks that benefit from more context.\n"
                    "5. Decrease search_chars if you only want to match on the beginning of input."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="메모리 주입",
        description="워크플로우 시작 시 세션 메모리 관리자에서 관련 메모리를 로드합니다. 입력과 관련된 메모리를 검색하여 MemoryRef 항목을 상태에 주입합니다. 선택적으로 사용자 입력을 트랜스크립트에 기록합니다.",
        parameters={
            "max_results": {
                "label": "최대 메모리 결과",
                "description": "로드할 최대 메모리 청크 수입니다.",
            },
            "search_chars": {
                "label": "검색 입력 길이",
                "description": "메모리 검색에 사용되는 입력 텍스트의 문자 수 제한입니다.",
            },
            "search_field": {
                "label": "검색 소스 필드",
                "description": "메모리 검색 쿼리로 사용되는 상태 필드입니다.",
            },
            "record_input": {
                "label": "입력 트랜스크립트 기록",
                "description": "검색 텍스트를 단기 트랜스크립트에 기록합니다.",
            },
        },
        output_ports={"default": {"label": "다음"}},
        groups={"behavior": "동작", "state_fields": "상태 필드"},
        help=_help(
            "메모리 주입 노드",
            "세션 메모리에서 관련 컨텍스트를 검색하여 그래프 상태에 로드합니다.",
            [
                ("개요", (
                    "메모리 주입 노드는 워크플로우를 세션의 **장기 및 단기 메모리**에 연결합니다. "
                    "현재 입력과 관련된 메모리를 검색하고 참조를 상태에 로드합니다.\n\n"
                    "이를 통해 하류 모델 노드가 관련 이전 컨텍스트에 접근할 수 있어 "
                    "응답의 품질과 일관성이 향상됩니다."
                )),
                ("메모리 검색", (
                    "노드는 입력 텍스트를 사용하여 유사도 검색을 수행합니다:\n\n"
                    "- **최대 결과**: 검색할 메모리 청크 수 (기본값: 5)\n"
                    "- **검색 입력 길이**: 검색에 사용할 입력 문자 수 (기본값: 500)\n\n"
                    "결과는 그래프 상태에 `memory_refs`로 저장됩니다."
                )),
                ("트랜스크립트 기록", (
                    "메모리 검색 외에도 이 노드는 향후 참조를 위해 "
                    "사용자의 입력을 대화 트랜스크립트에 기록합니다."
                )),
                ("사용 팁", (
                    "1. 워크플로우의 가장 처음, 시작 노드 바로 뒤에 배치하세요.\n"
                    "2. 세션에 메모리 관리자가 구성되어 있어야 합니다.\n"
                    "3. 일치하는 메모리가 없으면 노드는 조용히 업데이트를 생성하지 않습니다.\n"
                    "4. 더 많은 컨텍스트가 필요한 작업에는 max_results를 늘리세요.\n"
                    "5. 입력의 시작 부분만 매칭하려면 search_chars를 줄이세요."
                )),
            ],
        ),
    ),
}

TRANSCRIPT_RECORD_I18N = {
    "en": NodeI18n(
        label="Transcript Record",
        description="Records a state field's content to the short-term memory transcript with a configurable message role. Use for explicit transcript control when PostModel's built-in recording is insufficient.",
        parameters={
            "max_length": {
                "label": "Max Content Length",
                "description": "Maximum characters to record from the output.",
            },
            "source_field": {
                "label": "Source State Field",
                "description": "State field whose content is recorded to the transcript.",
            },
            "role": {
                "label": "Message Role",
                "description": "Role label for the transcript entry.",
            },
        },
        output_ports={"default": {"label": "Next"}},
        groups={"behavior": "Behavior", "state_fields": "State Fields"},
        help=_help(
            "Transcript Record Node",
            "Records the latest model output to the session's short-term memory transcript.",
            [
                ("Overview", (
                    "The Transcript Record node saves the latest model output to the session's "
                    "short-term memory. This builds up a conversation history that can be used "
                    "by Memory Inject in future turns.\n\n"
                    "This is a standalone node version of the transcript recording "
                    "that Post Model does automatically."
                )),
                ("Content Length", (
                    "The **Max Content Length** parameter limits how many characters are recorded.\n\n"
                    "Default: 5000 characters. For long outputs, only the first N characters are saved. "
                    "Increase this for tasks that produce detailed, important outputs."
                )),
                ("Usage Tips", (
                    "1. Use when you want explicit transcript recording without Post Model.\n"
                    "2. Place after any model node to record its output.\n"
                    "3. The memory manager must be configured for the session.\n"
                    "4. If no memory manager is present, the node silently does nothing."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="트랜스크립트 기록",
        description="구성 가능한 메시지 역할로 상태 필드의 콘텐츠를 단기 메모리 트랜스크립트에 기록합니다. PostModel의 내장 기록이 부족할 때 몥시적 트랜스크립트 제어에 사용합니다.",
        parameters={
            "max_length": {
                "label": "최대 콘텐츠 길이",
                "description": "출력에서 기록할 최대 문자 수입니다.",
            },
            "source_field": {
                "label": "소스 상태 필드",
                "description": "트랜스크립트에 기록할 콘텐츠가 포함된 상태 필드입니다.",
            },
            "role": {
                "label": "메시지 역할",
                "description": "트랜스크립트 항목의 역할 레이블입니다.",
            },
        },
        output_ports={"default": {"label": "다음"}},
        groups={"behavior": "동작", "state_fields": "상태 필드"},
        help=_help(
            "트랜스크립트 기록 노드",
            "최신 모델 출력을 세션의 단기 메모리 트랜스크립트에 기록합니다.",
            [
                ("개요", (
                    "트랜스크립트 기록 노드는 최신 모델 출력을 세션의 단기 메모리에 저장합니다. "
                    "이를 통해 향후 턴에서 메모리 주입이 사용할 수 있는 대화 이력이 구축됩니다.\n\n"
                    "이것은 후처리 노드가 자동으로 수행하는 트랜스크립트 기록의 독립형 노드 버전입니다."
                )),
                ("콘텐츠 길이", (
                    "**최대 콘텐츠 길이** 파라미터는 기록할 문자 수를 제한합니다.\n\n"
                    "기본값: 5000 문자. 긴 출력의 경우 처음 N 문자만 저장됩니다. "
                    "상세한 중요 출력을 생성하는 작업에는 이 값을 늘리세요."
                )),
                ("사용 팁", (
                    "1. 후처리 없이 명시적 트랜스크립트 기록이 필요할 때 사용하세요.\n"
                    "2. 모든 모델 노드 뒤에 배치하여 출력을 기록하세요.\n"
                    "3. 세션에 메모리 관리자가 구성되어 있어야 합니다.\n"
                    "4. 메모리 관리자가 없으면 노드는 조용히 아무 작업도 하지 않습니다."
                )),
            ],
        ),
    ),
}


# ====================================================================
#  GUARD / RESILIENCE NODES
# ====================================================================

CONTEXT_GUARD_I18N = {
    "en": NodeI18n(
        label="Context Guard",
        description="Checks context window token budget before model calls. Estimates token usage from accumulated messages and writes budget status to state. Downstream nodes read this to compact prompts when tight.",
        parameters={
            "position_label": {
                "label": "Position Label",
                "description": "Descriptive label for logging (e.g. 'classify', 'execute').",
            },
            "messages_field": {
                "label": "Messages State Field",
                "description": "State field containing the message list to measure.",
            },
        },
        output_ports={"default": {"label": "Next"}},
        groups={"general": "General", "state_fields": "State Fields"},
        help=_help(
            "Context Guard Node",
            "Monitors the context window token budget and warns or blocks when limits are approached.",
            [
                ("Overview", (
                    "The Context Guard node is a **resilience infrastructure** node that monitors "
                    "how much of the model's context window has been consumed.\n\n"
                    "It estimates token usage from accumulated messages and writes a budget status "
                    "to state. Downstream nodes can read this to compact prompts, "
                    "truncate content, or skip calls entirely."
                )),
                ("Budget Status", (
                    "The node writes a `context_budget` object to state with:\n\n"
                    "- `estimated_tokens` — estimated token count\n"
                    "- `context_limit` — the model's context window size\n"
                    "- `usage_ratio` — how full the context window is (0.0 to 1.0)\n"
                    "- `status` — 'ok', 'warning', 'overflow', or 'block'\n"
                    "- `compaction_count` — how many times compaction was triggered"
                )),
                ("Position Label", (
                    "The position label is used for logging only. It helps identify "
                    "which guard node triggered in the logs.\n\n"
                    "Example labels: 'classify', 'answer', 'execute', 'review'"
                )),
                ("Usage Tips", (
                    "1. Place before every model node to monitor context usage.\n"
                    "2. Multiple guards can be placed at different points in the workflow.\n"
                    "3. The Iteration Gate also checks context_budget — they work together.\n"
                    "4. Use different position labels to identify which guard triggered."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="컨텍스트 가드",
        description="모델 호출 전 컨텍스트 윈도우 토큰 예산을 확인합니다. 누적된 메시지에서 토큰 사용량을 추정하고 예산 상태를 기록합니다. 하위 노드들이 이를 읽어 프롬프트를 압축합니다.",
        parameters={
            "position_label": {
                "label": "위치 레이블",
                "description": "로깅을 위한 설명 레이블입니다 (예: 'classify', 'execute').",
            },
            "messages_field": {
                "label": "메시지 상태 필드",
                "description": "측정할 메시지 목록이 포함된 상태 필드입니다.",
            },
        },
        output_ports={"default": {"label": "다음"}},
        groups={"general": "일반", "state_fields": "상태 필드"},
        help=_help(
            "컨텍스트 가드 노드",
            "컨텍스트 윈도우 토큰 예산을 모니터링하고 한계에 도달하면 경고 또는 차단합니다.",
            [
                ("개요", (
                    "컨텍스트 가드 노드는 모델의 컨텍스트 윈도우가 얼마나 소비되었는지 "
                    "모니터링하는 **복원력 인프라** 노드입니다.\n\n"
                    "축적된 메시지에서 토큰 사용량을 추정하고 예산 상태를 상태에 기록합니다. "
                    "하류 노드는 이를 읽어 프롬프트를 압축하거나, "
                    "콘텐츠를 잘라내거나, 호출을 완전히 건너뛸 수 있습니다."
                )),
                ("예산 상태", (
                    "노드는 `context_budget` 객체를 상태에 기록합니다:\n\n"
                    "- `estimated_tokens` — 추정된 토큰 수\n"
                    "- `context_limit` — 모델의 컨텍스트 윈도우 크기\n"
                    "- `usage_ratio` — 컨텍스트 윈도우 사용률 (0.0 ~ 1.0)\n"
                    "- `status` — 'ok', 'warning', 'overflow', 또는 'block'\n"
                    "- `compaction_count` — 압축이 트리거된 횟수"
                )),
                ("위치 레이블", (
                    "위치 레이블은 로깅에만 사용됩니다. 로그에서 어떤 가드 노드가 "
                    "트리거되었는지 식별하는 데 도움이 됩니다.\n\n"
                    "예시 레이블: 'classify', 'answer', 'execute', 'review'"
                )),
                ("사용 팁", (
                    "1. 컨텍스트 사용량을 모니터링하기 위해 모든 모델 노드 앞에 배치하세요.\n"
                    "2. 워크플로우의 여러 지점에 여러 가드를 배치할 수 있습니다.\n"
                    "3. 반복 게이트도 context_budget를 확인합니다 — 함께 작동합니다.\n"
                    "4. 어떤 가드가 트리거되었는지 식별하기 위해 다른 위치 레이블을 사용하세요."
                )),
            ],
        ),
    ),
}

POST_MODEL_I18N = {
    "en": NodeI18n(
        label="Post Model",
        description="Post-processing node placed after every model call. Performs: (1) iteration counter increment, (2) optional completion signal detection, (3) optional transcript recording. Essential resilience infrastructure.",
        parameters={
            "detect_completion": {
                "label": "Detect Completion Signals",
                "description": "Parse structured completion signals from the output.",
            },
            "record_transcript": {
                "label": "Record Transcript",
                "description": "Record the output to short-term memory.",
            },
            "increment_field": {
                "label": "Iteration Counter Field",
                "description": "State field to increment as the iteration counter.",
            },
            "source_field": {
                "label": "Source State Field",
                "description": "State field to read for signal detection and transcript recording.",
            },
        },
        output_ports={"default": {"label": "Next"}},
        groups={"behavior": "Behavior", "state_fields": "State Fields"},
        help=_help(
            "Post Model Node",
            "Performs essential post-processing after every model call: iteration tracking, signal detection, and transcript recording.",
            [
                ("Overview", (
                    "The Post Model node is a **resilience infrastructure** node that should be placed "
                    "after every model node. It handles three concerns:\n\n"
                    "1. **Iteration increment** — tracks how many model calls have been made\n"
                    "2. **Completion signal detection** — parses structured signals from the output\n"
                    "3. **Transcript recording** — saves the output to short-term memory"
                )),
                ("Completion Signals", (
                    "The node scans the model output for structured completion signals:\n\n"
                    "- `COMPLETE` — task is fully done\n"
                    "- `BLOCKED` — cannot proceed (missing info, permissions, etc.)\n"
                    "- `ERROR` — an error was encountered\n\n"
                    "Detected signals are written to `completion_signal` and `completion_detail` state fields."
                )),
                ("Transcript Recording", (
                    "When enabled, the node records the model output to the session's "
                    "short-term memory transcript. Up to 5000 characters are saved.\n\n"
                    "This builds the conversation history for Memory Inject to use."
                )),
                ("Usage Tips", (
                    "1. Place after every model node (LLM Call, Answer, Direct Answer, etc.).\n"
                    "2. Keep both features enabled for full resilience.\n"
                    "3. Disable transcript recording for intermediate steps to save memory.\n"
                    "4. The iteration count is critical for Iteration Gate to work correctly."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="후처리",
        description="모든 모델 호출 후에 배치되는 후처리 노드. (1) 반복 카운터 증가, (2) 선택적 완료 신호 감지, (3) 선택적 트랜스크립트 기록을 수행합니다. 필수 복원력 인프라입니다.",
        parameters={
            "detect_completion": {
                "label": "완료 신호 감지",
                "description": "출력에서 구조화된 완료 신호를 파싱합니다.",
            },
            "record_transcript": {
                "label": "트랜스크립트 기록",
                "description": "출력을 단기 메모리에 기록합니다.",
            },
            "increment_field": {
                "label": "반복 카운터 필드",
                "description": "반복 카운터로 증가시킬 상태 필드입니다.",
            },
            "source_field": {
                "label": "소스 상태 필드",
                "description": "신호 감지 및 트랜스크립트 기록을 위해 읽을 상태 필드입니다.",
            },
        },
        output_ports={"default": {"label": "다음"}},
        groups={"behavior": "동작", "state_fields": "상태 필드"},
        help=_help(
            "후처리 노드",
            "모든 모델 호출 후 필수 후처리를 수행합니다: 반복 추적, 신호 감지, 트랜스크립트 기록.",
            [
                ("개요", (
                    "후처리 노드는 모든 모델 노드 뒤에 배치해야 하는 **복원력 인프라** 노드입니다. "
                    "세 가지 관심사를 처리합니다:\n\n"
                    "1. **반복 증가** — 모델 호출 횟수를 추적합니다\n"
                    "2. **완료 신호 감지** — 출력에서 구조화된 신호를 파싱합니다\n"
                    "3. **트랜스크립트 기록** — 출력을 단기 메모리에 저장합니다"
                )),
                ("완료 신호", (
                    "노드는 모델 출력에서 구조화된 완료 신호를 스캔합니다:\n\n"
                    "- `COMPLETE` — 작업이 완전히 완료됨\n"
                    "- `BLOCKED` — 진행 불가 (정보 부족, 권한 등)\n"
                    "- `ERROR` — 오류 발생\n\n"
                    "감지된 신호는 `completion_signal`과 `completion_detail` 상태 필드에 기록됩니다."
                )),
                ("트랜스크립트 기록", (
                    "활성화되면 노드는 모델 출력을 세션의 단기 메모리 트랜스크립트에 기록합니다. "
                    "최대 5000 문자가 저장됩니다.\n\n"
                    "이를 통해 메모리 주입이 사용할 대화 이력이 구축됩니다."
                )),
                ("사용 팁", (
                    "1. 모든 모델 노드(LLM 호출, 답변, 직접 답변 등) 뒤에 배치하세요.\n"
                    "2. 완전한 복원력을 위해 두 기능 모두 활성화된 상태로 유지하세요.\n"
                    "3. 메모리를 절약하려면 중간 단계에서 트랜스크립트 기록을 비활성화하세요.\n"
                    "4. 반복 카운트는 반복 게이트가 올바르게 작동하는 데 필수적입니다."
                )),
            ],
        ),
    ),
}


# ====================================================================
#  TASK NODES
# ====================================================================

CREATE_TODOS_I18N = {
    "en": NodeI18n(
        label="Create TODOs",
        description="Breaks a complex task into a structured JSON TODO list via LLM. Parses the response as JSON (handles markdown code blocks), converts to TodoItem format, and caps item count to prevent runaway execution.",
        parameters={
            "prompt_template": {
                "label": "Prompt Template",
                "description": "Prompt template for generating the TODO list.",
            },
            "max_todos": {
                "label": "Max TODO Items",
                "description": "Maximum number of TODO items to prevent runaway execution.",
            },
            "output_list_field": {
                "label": "Output List Field",
                "description": "State field to store the generated list in.",
            },
            "output_index_field": {
                "label": "Output Index Field",
                "description": "State field for the current index (reset to 0).",
            },
        },
        output_ports={"default": {"label": "Next"}},
        groups={"prompt": "Prompt", "behavior": "Behavior", "state_fields": "State Fields"},
        help=_help(
            "Create TODOs Node",
            "Decomposes complex tasks into a structured TODO list for step-by-step execution.",
            [
                ("Overview", (
                    "The Create TODOs node handles the entry point of the **hard path**. "
                    "It sends the user's complex task to the model, which breaks it down "
                    "into a structured JSON TODO list.\n\n"
                    "Each TODO item has an ID, title, and description. "
                    "The items are then executed sequentially by Execute TODO nodes."
                )),
                ("TODO Format", (
                    "The model is expected to produce a JSON array:\n\n"
                    "```json\n[\n  {\"id\": 1, \"title\": \"Step 1\", \"description\": \"Do X\"},\n  {\"id\": 2, \"title\": \"Step 2\", \"description\": \"Do Y\"}\n]\n```\n\n"
                    "The node handles JSON in plain text or wrapped in markdown code blocks."
                )),
                ("Max TODO Items", (
                    "The **Max TODO Items** parameter caps the list to prevent runaway execution.\n\n"
                    "Default: 20. If the model generates more items than the limit, "
                    "only the first N are kept."
                )),
                ("Usage Tips", (
                    "1. Connect from the 'Hard' port of Classify Difficulty.\n"
                    "2. Follow with an Iteration Gate → Execute TODO loop.\n"
                    "3. The TODO list is stored in the `todos` state field.\n"
                    "4. Customize the prompt to get domain-specific decomposition.\n"
                    "5. `current_todo_index` is set to 0 after creation."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="TODO 생성",
        description="LLM을 통해 복잡한 작업을 구조화된 JSON TODO 목록으로 분해합니다. 응답을 JSON으로 파싱하고(markdown 코드 블록 처리), TodoItem 형식으로 변환하며, 수량을 제한합니다.",
        parameters={
            "prompt_template": {
                "label": "프롬프트 템플릿",
                "description": "TODO 목록 생성을 위한 프롬프트 템플릿입니다.",
            },
            "max_todos": {
                "label": "최대 TODO 항목 수",
                "description": "과도한 실행을 방지하기 위한 최대 TODO 항목 수입니다.",
            },
            "output_list_field": {
                "label": "출력 목록 필드",
                "description": "생성된 목록을 저장할 상태 필드입니다.",
            },
            "output_index_field": {
                "label": "출력 인덱스 필드",
                "description": "현재 인덱스용 상태 필드입니다 (0으로 리셋).",
            },
        },
        output_ports={"default": {"label": "다음"}},
        groups={"prompt": "프롬프트", "behavior": "동작", "state_fields": "상태 필드"},
        help=_help(
            "TODO 생성 노드",
            "복잡한 작업을 구조화된 TODO 목록으로 분해하여 단계별 실행이 가능하도록 합니다.",
            [
                ("개요", (
                    "TODO 생성 노드는 **어려움 경로**의 진입점을 처리합니다. "
                    "사용자의 복잡한 작업을 모델에 전송하여 "
                    "구조화된 JSON TODO 목록으로 분해합니다.\n\n"
                    "각 TODO 항목에는 ID, 제목, 설명이 있습니다. "
                    "항목들은 TODO 실행 노드에 의해 순차적으로 실행됩니다."
                )),
                ("TODO 형식", (
                    "모델은 JSON 배열을 생성해야 합니다:\n\n"
                    "```json\n[\n  {\"id\": 1, \"title\": \"1단계\", \"description\": \"X 수행\"},\n  {\"id\": 2, \"title\": \"2단계\", \"description\": \"Y 수행\"}\n]\n```\n\n"
                    "노드는 일반 텍스트 또는 마크다운 코드 블록으로 감싼 JSON을 처리합니다."
                )),
                ("최대 TODO 항목 수", (
                    "**최대 TODO 항목 수** 파라미터는 과도한 실행을 방지하기 위해 목록을 제한합니다.\n\n"
                    "기본값: 20. 모델이 제한보다 많은 항목을 생성하면 처음 N개만 유지됩니다."
                )),
                ("사용 팁", (
                    "1. 난이도 분류의 '어려움' 포트에서 연결하세요.\n"
                    "2. 반복 게이트 → TODO 실행 루프를 뒤에 배치하세요.\n"
                    "3. TODO 목록은 `todos` 상태 필드에 저장됩니다.\n"
                    "4. 도메인별 분해를 위해 프롬프트를 커스터마이즈하세요.\n"
                    "5. 생성 후 `current_todo_index`가 0으로 설정됩니다."
                )),
            ],
        ),
    ),
}

EXECUTE_TODO_I18N = {
    "en": NodeI18n(
        label="Execute TODO",
        description="Executes a single TODO item from the plan. Builds a prompt with the item's context and budget-aware previous results. Marks the item as completed or failed and advances the index. Designed for loop use with CheckProgress.",
        parameters={
            "prompt_template": {
                "label": "Prompt Template",
                "description": "Prompt for executing a TODO item.",
            },
            "list_field": {
                "label": "List State Field",
                "description": "State field containing the TODO list.",
            },
            "index_field": {
                "label": "Index State Field",
                "description": "State field tracking the current TODO index.",
            },
            "max_context_chars": {
                "label": "Max Context Chars",
                "description": "Max characters per previous result in the context window.",
            },
            "compact_context_chars": {
                "label": "Compact Context Chars",
                "description": "Max characters per previous result when context budget is tight.",
            },
        },
        output_ports={"default": {"label": "Next"}},
        groups={"prompt": "Prompt", "state_fields": "State Fields", "behavior": "Behavior"},
        help=_help(
            "Execute TODO Node",
            "Executes one TODO item at a time, incorporating results from previously completed items.",
            [
                ("Overview", (
                    "The Execute TODO node processes individual items from the TODO list "
                    "created by Create TODOs. It executes one item per invocation "
                    "and advances the `current_todo_index`.\n\n"
                    "Each execution includes context from previously completed items "
                    "to ensure coherent, progressive work."
                )),
                ("Execution Context", (
                    "The prompt includes:\n"
                    "- `{goal}` — the original user request\n"
                    "- `{title}` — the current TODO item title\n"
                    "- `{description}` — the current TODO item description\n"
                    "- `{previous_results}` — results from already-completed items\n\n"
                    "If the context budget is strained, previous results are truncated."
                )),
                ("State Updates", (
                    "After execution:\n"
                    "- The TODO item's status is set to `completed` (or `failed` on error)\n"
                    "- `current_todo_index` is incremented\n"
                    "- The result is stored in the TODO item's `result` field"
                )),
                ("Usage Tips", (
                    "1. Place inside a loop: Iteration Gate → Context Guard → Execute TODO → Post Model → Check Progress.\n"
                    "2. Check Progress routes back to Iteration Gate (continue) or to Final Review (complete).\n"
                    "3. If the context budget is tight, previous results are automatically truncated.\n"
                    "4. Failed TODO items are recorded but execution continues with the next item."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="TODO 실행",
        description="계획에서 단일 TODO 항목을 실행합니다. 항목의 컨텍스트와 예산 인식 이전 결과로 프롬프트를 구성합니다. 항목을 완료/실패로 표시하고 인덱스를 전진합니다. CheckProgress와 루프 사용용.",
        parameters={
            "prompt_template": {
                "label": "프롬프트 템플릿",
                "description": "TODO 항목 실행을 위한 프롬프트입니다.",
            },
            "list_field": {
                "label": "목록 상태 필드",
                "description": "TODO 목록이 포함된 상태 필드입니다.",
            },
            "index_field": {
                "label": "인덱스 상태 필드",
                "description": "현재 TODO 인덱스를 추적하는 상태 필드입니다.",
            },
            "max_context_chars": {
                "label": "최대 컨텍스트 문자 수",
                "description": "컨텍스트 윈도우에서 이전 결과당 최대 문자 수입니다.",
            },
            "compact_context_chars": {
                "label": "압축 컨텍스트 문자 수",
                "description": "컨텍스트 예산이 부족할 때 이전 결과당 최대 문자 수입니다.",
            },
        },
        output_ports={"default": {"label": "다음"}},
        groups={"prompt": "프롬프트", "state_fields": "상태 필드", "behavior": "동작"},
        help=_help(
            "TODO 실행 노드",
            "이전에 완료된 항목의 결과를 반영하면서 하나의 TODO 항목을 실행합니다.",
            [
                ("개요", (
                    "TODO 실행 노드는 TODO 생성에 의해 만들어진 TODO 목록의 개별 항목을 처리합니다. "
                    "호출당 하나의 항목을 실행하고 `current_todo_index`를 진행합니다.\n\n"
                    "각 실행에는 이전에 완료된 항목의 결과가 포함되어 "
                    "일관되고 진행적인 작업이 보장됩니다."
                )),
                ("실행 컨텍스트", (
                    "프롬프트에 포함되는 정보:\n"
                    "- `{goal}` — 원본 사용자 요청\n"
                    "- `{title}` — 현재 TODO 항목 제목\n"
                    "- `{description}` — 현재 TODO 항목 설명\n"
                    "- `{previous_results}` — 이미 완료된 항목들의 결과\n\n"
                    "컨텍스트 예산이 부족하면 이전 결과가 잘립니다."
                )),
                ("상태 업데이트", (
                    "실행 후:\n"
                    "- TODO 항목의 상태가 `completed`로 설정됨 (오류 시 `failed`)\n"
                    "- `current_todo_index`가 증가함\n"
                    "- 결과가 TODO 항목의 `result` 필드에 저장됨"
                )),
                ("사용 팁", (
                    "1. 루프 내에 배치: 반복 게이트 → 컨텍스트 가드 → TODO 실행 → 후처리 → 진행 확인.\n"
                    "2. 진행 확인은 반복 게이트(계속) 또는 최종 리뷰(완료)로 다시 라우팅합니다.\n"
                    "3. 컨텍스트 예산이 부족하면 이전 결과가 자동으로 잘립니다.\n"
                    "4. 실패한 TODO 항목은 기록되지만 다음 항목으로 실행을 계속합니다."
                )),
            ],
        ),
    ),
}

FINAL_REVIEW_I18N = {
    "en": NodeI18n(
        label="Final Review",
        description="Comprehensive review of all completed list item results. Presents all items to the LLM with budget-aware character truncation. Stores the review output for final answer synthesis.",
        parameters={
            "prompt_template": {
                "label": "Prompt Template",
                "description": "Prompt for the final review of all work.",
            },
            "list_field": {
                "label": "List State Field",
                "description": "State field containing the list to review.",
            },
            "output_field": {
                "label": "Output State Field",
                "description": "State field to store the review output.",
            },
            "max_item_chars": {
                "label": "Max Chars per Item",
                "description": "Maximum characters per list item result in the prompt.",
            },
            "compact_item_chars": {
                "label": "Compact Chars per Item",
                "description": "Maximum characters per item when context budget is tight.",
            },
        },
        output_ports={"default": {"label": "Next"}},
        groups={"prompt": "Prompt", "state_fields": "State Fields", "output": "Output", "behavior": "Behavior"},
        help=_help(
            "Final Review Node",
            "Performs a comprehensive review of all completed TODO items before synthesis.",
            [
                ("Overview", (
                    "The Final Review node is part of the **hard path** completion sequence. "
                    "It reviews all TODO results together, providing an overall assessment "
                    "and feedback before the final answer is synthesised.\n\n"
                    "This ensures the final answer considers the quality and completeness "
                    "of all individual TODO results."
                )),
                ("Review Content", (
                    "The prompt includes:\n"
                    "- `{input}` — the original user request\n"
                    "- `{todo_results}` — all TODO results with their status\n\n"
                    "If the context budget is strained, individual results are truncated."
                )),
                ("Usage Tips", (
                    "1. Place after Check Progress routes to 'Complete'.\n"
                    "2. Follow with Final Answer for synthesis.\n"
                    "3. The review feedback is stored in `review_feedback` state field.\n"
                    "4. This is different from the Review node — it reviews ALL results, not one answer."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="최종 리뷰",
        description="완료된 모든 목록 항목 결과의 종합 리뷰. 예산 인식 문자 절단과 함께 모든 항목을 LLM에 제시합니다. 최종 답변 합성을 위해 리뷰 출력을 저장합니다.",
        parameters={
            "prompt_template": {
                "label": "프롬프트 템플릿",
                "description": "전체 작업의 최종 리뷰를 위한 프롬프트입니다.",
            },
            "list_field": {
                "label": "목록 상태 필드",
                "description": "리뷰할 목록이 포함된 상태 필드입니다.",
            },
            "output_field": {
                "label": "출력 상태 필드",
                "description": "리뷰 출력을 저장할 상태 필드입니다.",
            },
            "max_item_chars": {
                "label": "항목당 최대 문자 수",
                "description": "프롬프트에서 목록 항목 결과당 최대 문자 수입니다.",
            },
            "compact_item_chars": {
                "label": "압축 항목당 문자 수",
                "description": "컨텍스트 예산이 부족할 때 항목당 최대 문자 수입니다.",
            },
        },
        output_ports={"default": {"label": "다음"}},
        groups={"prompt": "프롬프트", "state_fields": "상태 필드", "output": "출력", "behavior": "동작"},
        help=_help(
            "최종 리뷰 노드",
            "합성 전에 완료된 모든 TODO 항목에 대한 종합 리뷰를 수행합니다.",
            [
                ("개요", (
                    "최종 리뷰 노드는 **어려움 경로** 완료 시퀀스의 일부입니다. "
                    "모든 TODO 결과를 함께 리뷰하여 최종 답변이 합성되기 전에 "
                    "전반적인 평가와 피드백을 제공합니다.\n\n"
                    "이를 통해 최종 답변이 모든 개별 TODO 결과의 "
                    "품질과 완전성을 고려하도록 보장합니다."
                )),
                ("리뷰 내용", (
                    "프롬프트에 포함되는 정보:\n"
                    "- `{input}` — 원본 사용자 요청\n"
                    "- `{todo_results}` — 상태와 함께 모든 TODO 결과\n\n"
                    "컨텍스트 예산이 부족하면 개별 결과가 잘립니다."
                )),
                ("사용 팁", (
                    "1. 진행 확인이 '완료'로 라우팅된 후에 배치하세요.\n"
                    "2. 합성을 위해 최종 답변 노드를 뒤에 배치하세요.\n"
                    "3. 리뷰 피드백은 `review_feedback` 상태 필드에 저장됩니다.\n"
                    "4. 리뷰 노드와 다릅니다 — 하나의 답변이 아닌 모든 결과를 리뷰합니다."
                )),
            ],
        ),
    ),
}

FINAL_ANSWER_I18N = {
    "en": NodeI18n(
        label="Final Answer",
        description="Synthesizes the final comprehensive answer from all list item results and review feedback. Combines completed work with budget-aware truncation. Marks the workflow as complete upon success.",
        parameters={
            "prompt_template": {
                "label": "Prompt Template",
                "description": "Prompt for synthesizing the final answer.",
            },
            "list_field": {
                "label": "List State Field",
                "description": "State field containing the list of results.",
            },
            "feedback_field": {
                "label": "Feedback State Field",
                "description": "State field containing review feedback to incorporate.",
            },
            "output_field": {
                "label": "Output State Field",
                "description": "State field to store the synthesized answer.",
            },
            "max_item_chars": {
                "label": "Max Chars per Item",
                "description": "Maximum characters per list item result in the prompt.",
            },
            "compact_item_chars": {
                "label": "Compact Chars per Item",
                "description": "Maximum characters per item when context budget is tight.",
            },
        },
        output_ports={"default": {"label": "Next"}},
        groups={"prompt": "Prompt", "state_fields": "State Fields", "output": "Output", "behavior": "Behavior"},
        help=_help(
            "Final Answer Node",
            "Synthesizes all TODO results and review feedback into a single comprehensive final answer.",
            [
                ("Overview", (
                    "The Final Answer node is the **terminal node** of the hard path. "
                    "It takes all TODO results and the final review feedback, "
                    "then synthesizes them into a single comprehensive response.\n\n"
                    "After execution, `is_complete` is set to True, ending the workflow."
                )),
                ("Synthesis Content", (
                    "The prompt includes:\n"
                    "- `{input}` — the original user request\n"
                    "- `{todo_results}` — all TODO results with their status\n"
                    "- `{review_feedback}` — feedback from the final review\n\n"
                    "The model combines all this information into a cohesive final answer."
                )),
                ("State Updates", (
                    "After execution:\n"
                    "- `final_answer` — the synthesized answer\n"
                    "- `is_complete = True` — signals workflow completion\n"
                    "- `current_step = 'complete'`"
                )),
                ("Usage Tips", (
                    "1. Place after Final Review.\n"
                    "2. Connect to End node (or Post Model → End).\n"
                    "3. If the Final Review failed, the node still attempts synthesis from TODO results.\n"
                    "4. On error, it provides a fallback answer with raw TODO results."
                )),
            ],
        ),
    ),
    "ko": NodeI18n(
        label="최종 답변",
        description="모든 목록 항목 결과와 리뷰 피드백에서 최종 종합 답변을 합성합니다. 예산 인식 절단을 적용하여 완료된 작업을 결합합니다. 성공 시 워크플로우를 완료로 표시합니다.",
        parameters={
            "prompt_template": {
                "label": "프롬프트 템플릿",
                "description": "최종 답변 합성을 위한 프롬프트입니다.",
            },
            "list_field": {
                "label": "목록 상태 필드",
                "description": "결과 목록이 포함된 상태 필드입니다.",
            },
            "feedback_field": {
                "label": "피드백 상태 필드",
                "description": "반영할 리뷰 피드백이 포함된 상태 필드입니다.",
            },
            "output_field": {
                "label": "출력 상태 필드",
                "description": "합성된 답변을 저장할 상태 필드입니다.",
            },
            "max_item_chars": {
                "label": "항목당 최대 문자 수",
                "description": "프롬프트에서 목록 항목 결과당 최대 문자 수입니다.",
            },
            "compact_item_chars": {
                "label": "압축 항목당 문자 수",
                "description": "컨텍스트 예산이 부족할 때 항목당 최대 문자 수입니다.",
            },
        },
        output_ports={"default": {"label": "다음"}},
        groups={"prompt": "프롬프트", "state_fields": "상태 필드", "output": "출력", "behavior": "동작"},
        help=_help(
            "최종 답변 노드",
            "모든 TODO 결과와 리뷰 피드백을 단일 종합 최종 답변으로 합성합니다.",
            [
                ("개요", (
                    "최종 답변 노드는 어려움 경로의 **터미널 노드**입니다. "
                    "모든 TODO 결과와 최종 리뷰 피드백을 가져와 "
                    "단일 종합 응답으로 합성합니다.\n\n"
                    "실행 후 `is_complete`가 True로 설정되어 워크플로우를 종료합니다."
                )),
                ("합성 내용", (
                    "프롬프트에 포함되는 정보:\n"
                    "- `{input}` — 원본 사용자 요청\n"
                    "- `{todo_results}` — 상태와 함께 모든 TODO 결과\n"
                    "- `{review_feedback}` — 최종 리뷰의 피드백\n\n"
                    "모델은 이 모든 정보를 일관된 최종 답변으로 결합합니다."
                )),
                ("상태 업데이트", (
                    "실행 후:\n"
                    "- `final_answer` — 합성된 답변\n"
                    "- `is_complete = True` — 워크플로우 완료 신호\n"
                    "- `current_step = 'complete'`"
                )),
                ("사용 팁", (
                    "1. 최종 리뷰 뒤에 배치하세요.\n"
                    "2. 종료 노드(또는 후처리 → 종료)에 연결하세요.\n"
                    "3. 최종 리뷰가 실패해도 TODO 결과에서 합성을 시도합니다.\n"
                    "4. 오류 시 원시 TODO 결과와 함께 대체 답변을 제공합니다."
                )),
            ],
        ),
    ),
}
