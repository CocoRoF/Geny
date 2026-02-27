"""
Structured Output — Pydantic-enforced LLM output parsing.

Provides a robust, multi-strategy JSON extraction + Pydantic validation
layer that sits between raw LLM text and the node's state updates.

Design goals:
    • Nodes declare their expected output as a Pydantic model
    • The prompt automatically includes the JSON schema constraint
    • Parsing uses a layered fallback: direct JSON → code-block → bracket-match → regex
    • Validation errors trigger a single automatic correction retry
    • Routing decisions are derived from typed fields, never from substring matching

Integration with ``ExecutionContext``:
    ``resilient_structured_invoke(messages, schema, node_name)``
    replaces ``resilient_invoke`` for nodes that need structured output.

Compatible with LangChain ``with_structured_output`` API contract
but implemented at the prompt-injection + parsing level to reuse
the shared ``ClaudeCLIChatModel`` session (avoids creating new
CLI processes per structured call).
"""

from __future__ import annotations

import json
import re
import textwrap
from logging import getLogger
from typing import (
    Any,
    Dict,
    Generic,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
)

from pydantic import BaseModel, ValidationError

logger = getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ============================================================================
# Pydantic schemas for each structured-output node
# ============================================================================


class ClassifyOutput(BaseModel):
    """Structured output for the ClassifyNode."""

    classification: str
    """The classification category (must be one of the configured categories)."""

    confidence: Optional[str] = None
    """Optional confidence level (low / medium / high)."""

    reasoning: Optional[str] = None
    """Optional brief reasoning for the classification."""


class ReviewOutput(BaseModel):
    """Structured output for the ReviewNode."""

    verdict: str
    """The review verdict (must be one of the configured verdicts)."""

    feedback: str = ""
    """Detailed feedback explaining the verdict."""

    issues: Optional[List[str]] = None
    """Optional list of specific issues found."""


class TodoItem(BaseModel):
    """A single TODO item in the structured plan."""

    id: int
    title: str
    description: str = ""


class CreateTodosOutput(BaseModel):
    """Structured output for the CreateTodosNode."""

    todos: List[TodoItem]
    """The list of TODO items."""


class FinalReviewOutput(BaseModel):
    """Structured output for the FinalReviewNode.

    Provides a structured quality assessment of all completed work,
    enabling downstream FinalAnswerNode to incorporate actionable
    review context rather than unstructured free-form text.
    """

    overall_quality: str = "good"
    """Overall quality assessment (excellent / good / needs_improvement / poor)."""

    completed_summary: str
    """Concise summary of what was accomplished across all items."""

    issues_found: Optional[List[str]] = None
    """Specific issues or gaps identified in the completed work."""

    recommendations: str = ""
    """Actionable suggestions for the final answer synthesis."""


# ============================================================================
# JSON extraction strategies (ordered by reliability)
# ============================================================================


def _try_direct_json(text: str) -> Optional[Any]:
    """Strategy 1: Parse the whole text as JSON."""
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _try_code_block(text: str) -> Optional[Any]:
    """Strategy 2: Extract from markdown code blocks."""
    for pattern in [
        r"```json\s*\n?(.*?)\n?\s*```",
        r"```\s*\n?(.*?)\n?\s*```",
    ]:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except (json.JSONDecodeError, TypeError):
                continue
    return None


def _try_bracket_match(text: str) -> Optional[Any]:
    """Strategy 3: Find the first well-formed JSON object or array.

    Uses bracket-depth tracking to handle nested structures correctly.
    """
    for open_ch, close_ch in [("{", "}"), ("[", "]")]:
        depth = 0
        start = None
        in_string = False
        escape_next = False

        for i, c in enumerate(text):
            if escape_next:
                escape_next = False
                continue
            if c == "\\":
                if in_string:
                    escape_next = True
                continue
            if c == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue

            if c == open_ch:
                if depth == 0:
                    start = i
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0 and start is not None:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except (json.JSONDecodeError, TypeError):
                        start = None
                        depth = 0
    return None


def extract_json(text: str) -> Tuple[Optional[Any], str]:
    """Extract JSON from LLM text using layered strategies.

    Returns:
        (parsed_value, method_name) — method_name is one of:
            "direct", "code_block", "bracket_match", or "none"
    """
    result = _try_direct_json(text)
    if result is not None:
        return result, "direct"

    result = _try_code_block(text)
    if result is not None:
        return result, "code_block"

    result = _try_bracket_match(text)
    if result is not None:
        return result, "bracket_match"

    return None, "none"


# ============================================================================
# Schema → prompt injection
# ============================================================================


def build_schema_instruction(
    schema_cls: Type[BaseModel],
    *,
    allowed_values: Optional[Dict[str, List[str]]] = None,
    extra_instruction: str = "",
) -> str:
    """Build a clear JSON schema instruction block for the LLM.

    Args:
        schema_cls: The Pydantic model class defining the output shape.
        allowed_values: Optional mapping of field_name → list of allowed values.
            This adds ``enum`` constraints to the instruction.
        extra_instruction: Additional instruction text appended after the schema.

    Returns:
        A multi-line string ready to append to any prompt.
    """
    schema = schema_cls.model_json_schema()

    # Enhance schema with enum constraints from allowed_values
    if allowed_values and "properties" in schema:
        for field_name, values in allowed_values.items():
            if field_name in schema["properties"]:
                schema["properties"][field_name]["enum"] = values

    schema_json = json.dumps(schema, indent=2, ensure_ascii=False)

    instruction = textwrap.dedent(f"""\

    ═══ RESPONSE FORMAT (MANDATORY) ═══
    You MUST respond with a single JSON object matching this schema.
    Do NOT include any text before or after the JSON.
    Do NOT wrap it in markdown code blocks.

    Schema:
    ```json
    {schema_json}
    ```
    """).strip()

    if extra_instruction:
        instruction += f"\n\n{extra_instruction}"

    return instruction


def build_correction_prompt(
    raw_text: str,
    schema_cls: Type[BaseModel],
    error: str,
) -> str:
    """Build a follow-up prompt when JSON parsing/validation fails.

    Asks the LLM to fix its output based on the error.
    """
    schema_json = json.dumps(
        schema_cls.model_json_schema(), indent=2, ensure_ascii=False,
    )
    return textwrap.dedent(f"""\
    Your previous response could not be parsed as valid JSON.

    Error: {error}

    Your response was:
    {raw_text[:1000]}

    Please respond ONLY with a valid JSON object matching this schema:
    ```json
    {schema_json}
    ```
    Do NOT include any other text.
    """).strip()


# ============================================================================
# Core parse + validate
# ============================================================================


class StructuredParseResult(BaseModel, Generic[T]):
    """Result of structured output extraction."""

    success: bool
    """Whether parsing and validation succeeded."""

    data: Optional[T] = None  # type: ignore[assignment]
    """The validated Pydantic model instance (None on failure)."""

    raw_text: str = ""
    """The original LLM output text."""

    method: str = "none"
    """Extraction method that succeeded: direct / code_block / bracket_match / none."""

    error: Optional[str] = None
    """Error message if parsing/validation failed."""

    class Config:
        arbitrary_types_allowed = True


def parse_structured_output(
    text: str,
    schema_cls: Type[T],
    *,
    allowed_values: Optional[Dict[str, List[str]]] = None,
    coerce_field: Optional[str] = None,
    coerce_values: Optional[List[str]] = None,
    coerce_default: Optional[str] = None,
) -> StructuredParseResult[T]:
    """Extract JSON from text and validate against a Pydantic schema.

    Args:
        text: Raw LLM output text.
        schema_cls: Pydantic model class to validate against.
        allowed_values: Optional dict of field → allowed values for post-validation.
        coerce_field: Optional field name whose value should be coerced to allowed_values.
        coerce_values: The set of allowed values for coerce_field.
        coerce_default: Default value if coerce_field doesn't match.

    Returns:
        StructuredParseResult with success/data/error.
    """
    extracted, method = extract_json(text)

    if extracted is None:
        return StructuredParseResult(
            success=False,
            raw_text=text,
            method="none",
            error="No JSON found in response",
        )

    # If the schema expects a wrapper but we got a raw list, wrap it
    if isinstance(extracted, list) and not _schema_is_list(schema_cls):
        # Heuristic: find the list field in the schema and wrap
        list_field = _find_list_field(schema_cls)
        if list_field:
            extracted = {list_field: extracted}

    if not isinstance(extracted, dict):
        return StructuredParseResult(
            success=False,
            raw_text=text,
            method=method,
            error=f"Expected JSON object, got {type(extracted).__name__}",
        )

    # Validate with Pydantic
    try:
        instance = schema_cls.model_validate(extracted)
    except ValidationError as e:
        return StructuredParseResult(
            success=False,
            raw_text=text,
            method=method,
            error=f"Validation error: {e}",
        )

    # Post-validation: coerce restricted field values
    if coerce_field and coerce_values is not None:
        current_val = getattr(instance, coerce_field, None)
        if isinstance(current_val, str):
            normalised = current_val.strip().lower()
            matched = None
            for v in coerce_values:
                if v.lower() == normalised:
                    matched = v
                    break
            if matched is None:
                # Try substring match as last resort
                for v in coerce_values:
                    if v.lower() in normalised:
                        matched = v
                        break
            if matched is None:
                matched = coerce_default or (coerce_values[0] if coerce_values else current_val)
            # Update the field
            object.__setattr__(instance, coerce_field, matched)

    return StructuredParseResult(
        success=True,
        data=instance,
        raw_text=text,
        method=method,
    )


def _schema_is_list(cls: Type[BaseModel]) -> bool:
    """Check if the schema's root is a list type."""
    return False  # Pydantic BaseModel is always an object


def _find_list_field(cls: Type[BaseModel]) -> Optional[str]:
    """Find the first List field in a Pydantic model."""
    for name, field_info in cls.model_fields.items():
        annotation = field_info.annotation
        origin = getattr(annotation, "__origin__", None)
        if origin is list:
            return name
    return None


# ============================================================================
# Frontend schema metadata builder
# ============================================================================


def build_frontend_schema(
    schema_cls: Type[BaseModel],
    *,
    description: Optional[str] = None,
    dynamic_fields: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build a frontend-friendly schema representation for display.

    Args:
        schema_cls: The Pydantic model class.
        description: Optional human-readable summary of the schema's purpose.
        dynamic_fields: Optional mapping of field_name → description of
            how the field values are determined (e.g. "configured categories").

    Returns:
        A dict suitable for serialization & frontend rendering:
        {
            "name": "ClassifyOutput",
            "description": "...",
            "fields": [
                {"name": "classification", "type": "string", "required": true,
                 "description": "...", "dynamic_note": "..."},
                ...
            ],
            "example": { ... }
        }
    """
    dynamic_fields = dynamic_fields or {}

    fields_info = []
    example = {}

    for name, field_info in schema_cls.model_fields.items():
        annotation = field_info.annotation
        type_str = _annotation_to_display(annotation)
        required = field_info.is_required()
        field_desc = field_info.description or ""

        # Build an example value — guard against PydanticUndefined
        default_val = field_info.default
        has_usable_default = (
            default_val is not None
            and not isinstance(default_val, type)
            and str(type(default_val)) != "<class 'pydantic_core.PydanticUndefinedType'>"
        )
        try:
            # Extra guard: PydanticUndefined is not JSON-serializable
            if has_usable_default:
                import json as _json
                _json.dumps(default_val)
                example_val = default_val
            else:
                example_val = _example_for_type(annotation, name)
        except (TypeError, ValueError):
            example_val = _example_for_type(annotation, name)

        entry: Dict[str, Any] = {
            "name": name,
            "type": type_str,
            "required": required,
            "description": field_desc,
        }
        if name in dynamic_fields:
            entry["dynamic_note"] = dynamic_fields[name]
        if example_val is not None:
            example[name] = example_val

        fields_info.append(entry)

    result: Dict[str, Any] = {
        "name": schema_cls.__name__,
        "description": description or schema_cls.__doc__ or "",
        "fields": fields_info,
    }
    if example:
        result["example"] = example

    return result


def _annotation_to_display(annotation: Any) -> str:
    """Convert a Python type annotation to a display string."""
    origin = getattr(annotation, "__origin__", None)

    if origin is list:
        args = getattr(annotation, "__args__", ())
        inner = _annotation_to_display(args[0]) if args else "any"
        return f"List[{inner}]"

    if origin is type(None):
        return "null"

    # Optional[X] is Union[X, None]
    import typing
    if origin is typing.Union:
        args = getattr(annotation, "__args__", ())
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return f"Optional[{_annotation_to_display(non_none[0])}]"
        return " | ".join(_annotation_to_display(a) for a in args)

    if annotation is str:
        return "string"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is bool:
        return "boolean"

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation.__name__

    return getattr(annotation, "__name__", str(annotation))


def _example_for_type(annotation: Any, field_name: str) -> Any:
    """Generate a reasonable example value for a type."""
    origin = getattr(annotation, "__origin__", None)

    if annotation is str:
        return f"<{field_name}>"
    if annotation is int:
        return 1
    if annotation is float:
        return 0.0
    if annotation is bool:
        return True

    if origin is list:
        args = getattr(annotation, "__args__", ())
        if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
            # Nested model — build a nested example
            nested = {}
            for n, fi in args[0].model_fields.items():
                val = _example_for_type(fi.annotation, n)
                if val is not None:
                    nested[n] = val
            return [nested]
        return []

    # Optional types
    import typing
    if origin is typing.Union:
        args = getattr(annotation, "__args__", ())
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _example_for_type(non_none[0], field_name)

    return None
