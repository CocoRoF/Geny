"""
BaseNode — Abstract interface for all workflow graph nodes.

Defines the node contract, parameter schema, output ports,
execution context, and the global node registry.

Every concrete node MUST:
    1.  Subclass ``BaseNode``
    2.  Set the class-level fields (node_type, label, category, …)
    3.  Implement ``execute()``
    4.  Decorate with ``@register_node`` or call ``NodeRegistry.register()``
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from logging import getLogger
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Type,
)

logger = getLogger(__name__)


# ============================================================================
# Parameter Schema — drives the frontend property editor
# ============================================================================


@dataclass
class NodeParameter:
    """A single configurable parameter for a workflow node.

    The frontend renders a form field using this schema.
    """

    name: str
    label: str
    type: Literal[
        "string", "number", "boolean", "select",
        "textarea", "json", "prompt_template",
    ]
    default: Any = None
    required: bool = False
    description: str = ""
    placeholder: str = ""
    options: List[Dict[str, str]] = field(default_factory=list)
    min: Optional[float] = None
    max: Optional[float] = None
    group: str = "general"
    generates_ports: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "default": self.default,
            "required": self.required,
            "description": self.description,
            "group": self.group,
        }
        if self.placeholder:
            d["placeholder"] = self.placeholder
        if self.options:
            d["options"] = self.options
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.generates_ports:
            d["generates_ports"] = True
        return d


# ============================================================================
# Help Content — structured help for the frontend help modal
# ============================================================================


@dataclass
class HelpSection:
    """A single section inside a node help guide."""

    title: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"title": self.title, "content": self.content}


@dataclass
class NodeHelp:
    """Complete help content for a node, in one locale."""

    title: str
    summary: str
    sections: List[HelpSection] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections],
        }


@dataclass
class NodeI18n:
    """Locale-specific translations for a node.

    Provides localised label, description, parameter labels/descriptions,
    output port labels, group names, and optional detailed help content.
    """

    label: str = ""
    description: str = ""
    parameters: Dict[str, Dict[str, str]] = field(default_factory=dict)
    output_ports: Dict[str, Dict[str, str]] = field(default_factory=dict)
    groups: Dict[str, str] = field(default_factory=dict)
    help: Optional[NodeHelp] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        if self.label:
            d["label"] = self.label
        if self.description:
            d["description"] = self.description
        if self.parameters:
            d["parameters"] = self.parameters
        if self.output_ports:
            d["output_ports"] = self.output_ports
        if self.groups:
            d["groups"] = self.groups
        if self.help:
            d["help"] = self.help.to_dict()
        return d


# ============================================================================
# Output Port — conditional branching definition
# ============================================================================


@dataclass
class OutputPort:
    """An output port on a node — represents a possible routing.

    Non-conditional nodes have a single ``default`` port.
    Conditional nodes (routers, gates) have multiple named ports.
    """

    id: str
    label: str
    description: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
        }


# ============================================================================
# Execution Context — runtime dependencies injected by the executor
# ============================================================================


@dataclass
class ExecutionContext:
    """Runtime context passed to every node during execution.

    Bundles model, session, memory, and resilience infrastructure
    so that nodes are decoupled from the wiring details.
    """

    model: Any  # ClaudeCLIChatModel
    session_id: str = "unknown"
    memory_manager: Any = None
    session_logger: Any = None
    context_guard: Any = None
    max_retries: int = 2
    model_name: Optional[str] = None

    async def resilient_invoke(
        self,
        messages: list,
        node_name: str,
    ) -> tuple:
        """Invoke model with retry on transient errors.

        Returns:
            (response, fallback_updates_dict)
        """
        from service.langgraph.model_fallback import (
            classify_error,
            is_recoverable,
            FailureReason,
        )

        last_error: Optional[Exception] = None
        model_label = self.model_name or "unknown"

        for attempt in range(self.max_retries + 1):
            try:
                start = time.time()
                response = await self.model.ainvoke(messages)
                duration_ms = int((time.time() - start) * 1000)

                if attempt > 0:
                    logger.info(
                        f"[{self.session_id}] {node_name}: "
                        f"succeeded on retry {attempt} ({duration_ms}ms)"
                    )
                    return response, {
                        "fallback": {
                            "original_model": model_label,
                            "current_model": model_label,
                            "attempts": attempt + 1,
                            "last_failure_reason": (
                                str(last_error)[:200] if last_error else ""
                            ),
                            "degraded": False,
                        }
                    }
                return response, {}

            except Exception as e:
                last_error = e
                reason = classify_error(e)
                logger.warning(
                    f"[{self.session_id}] {node_name}: "
                    f"attempt {attempt + 1}/{self.max_retries + 1} "
                    f"failed ({reason.value}): {str(e)[:100]}"
                )
                if not is_recoverable(reason) or attempt >= self.max_retries:
                    raise

                delay_map = {
                    FailureReason.RATE_LIMITED: 5.0,
                    FailureReason.OVERLOADED: 3.0,
                    FailureReason.TIMEOUT: 2.0,
                    FailureReason.NETWORK_ERROR: 2.0,
                }
                wait = delay_map.get(reason, 2.0) * (attempt + 1)
                logger.info(
                    f"[{self.session_id}] {node_name}: "
                    f"retrying in {wait:.1f}s…"
                )
                await asyncio.sleep(wait)

        raise last_error  # type: ignore[misc]

    async def resilient_structured_invoke(
        self,
        messages: list,
        node_name: str,
        schema_cls: Any,
        *,
        allowed_values: Optional[Dict[str, List[str]]] = None,
        coerce_field: Optional[str] = None,
        coerce_values: Optional[List[str]] = None,
        coerce_default: Optional[str] = None,
        extra_instruction: str = "",
    ) -> tuple:
        """Invoke model with structured output: parse + validate + retry.

        Appends a JSON schema instruction to the last human message,
        invokes the model, extracts JSON, and validates against
        ``schema_cls`` (a Pydantic BaseModel).

        If parsing or validation fails on the first attempt, sends
        a correction prompt and retries once.

        Returns:
            (parsed_pydantic_instance, fallback_updates_dict)

        Raises:
            ValueError  if structured output cannot be obtained
                        after the correction retry.
        """
        from service.workflow.nodes.structured_output import (
            build_schema_instruction,
            build_correction_prompt,
            parse_structured_output,
        )

        schema_instruction = build_schema_instruction(
            schema_cls,
            allowed_values=allowed_values,
            extra_instruction=extra_instruction,
        )

        # Clone messages and inject the schema instruction into the
        # last human message (or append as a new HumanMessage).
        augmented = list(messages)
        if augmented and hasattr(augmented[-1], "content"):
            from langchain_core.messages import HumanMessage

            last_msg = augmented[-1]
            augmented[-1] = HumanMessage(
                content=f"{last_msg.content}\n\n{schema_instruction}"
            )
        else:
            from langchain_core.messages import HumanMessage

            augmented.append(HumanMessage(content=schema_instruction))

        # ── First attempt ──
        response, fallback = await self.resilient_invoke(augmented, node_name)
        raw_text = (
            response.content
            if hasattr(response, "content")
            else str(response)
        )

        result = parse_structured_output(
            raw_text,
            schema_cls,
            allowed_values=allowed_values,
            coerce_field=coerce_field,
            coerce_values=coerce_values,
            coerce_default=coerce_default,
        )

        if result.success and result.data is not None:
            logger.info(
                f"[{self.session_id}] {node_name}: "
                f"structured output OK (method={result.method})"
            )
            return result.data, fallback

        # ── Correction retry ──
        logger.warning(
            f"[{self.session_id}] {node_name}: "
            f"structured parse failed ({result.error}), "
            f"sending correction prompt…"
        )
        from langchain_core.messages import HumanMessage

        correction = build_correction_prompt(
            raw_text, schema_cls, result.error or "unknown error",
        )
        correction_messages = list(messages) + [
            HumanMessage(content=correction),
        ]

        response2, fallback2 = await self.resilient_invoke(
            correction_messages, f"{node_name}_correction",
        )
        raw_text2 = (
            response2.content
            if hasattr(response2, "content")
            else str(response2)
        )

        result2 = parse_structured_output(
            raw_text2,
            schema_cls,
            allowed_values=allowed_values,
            coerce_field=coerce_field,
            coerce_values=coerce_values,
            coerce_default=coerce_default,
        )

        if result2.success and result2.data is not None:
            logger.info(
                f"[{self.session_id}] {node_name}: "
                f"structured output OK after correction (method={result2.method})"
            )
            merged = {**fallback, **fallback2} if fallback2 else fallback
            return result2.data, merged

        # ── Final failure ──
        error_msg = (
            f"Structured output parsing failed for {node_name} "
            f"after correction retry: {result2.error}"
        )
        logger.error(f"[{self.session_id}] {error_msg}")
        raise ValueError(error_msg)


# ============================================================================
# BaseNode — abstract interface every node must implement
# ============================================================================


class BaseNode(ABC):
    """Abstract base class for all workflow graph nodes.

    Subclasses MUST define:
        - ``node_type``   — unique string identifier (e.g. ``"llm_call"``)
        - ``label``       — human-readable display name
        - ``description`` — one-line description
        - ``category``    — grouping key for the node palette
        - ``icon``        — emoji or icon identifier
        - ``color``       — hex colour for the node card
        - ``parameters``  — list of ``NodeParameter``
        - ``output_ports``— list of ``OutputPort``

    And implement:
        - ``execute(state, context, config) -> dict``

    Optional override:
        - ``get_routing_function(config) -> Callable``
    """

    # ── Class-level metadata (override in subclasses) ──

    node_type: str = ""
    label: str = ""
    description: str = ""
    category: str = "general"
    icon: str = "⚡"
    color: str = "#3b82f6"

    parameters: List[NodeParameter] = []
    output_ports: List[OutputPort] = [
        OutputPort(id="default", label="Next"),
    ]

    # ── Structured output schema (override in subclasses that use it) ──
    structured_output_schema: Optional[Dict[str, Any]] = None

    # ── i18n translations keyed by locale (override in subclasses) ──
    i18n: Dict[str, NodeI18n] = {}

    # ── Properties ──

    @property
    def is_conditional(self) -> bool:
        """True if this node produces multiple routing paths."""
        return len(self.output_ports) > 1

    # ── Execution ──

    @abstractmethod
    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute node logic and return state updates.

        Args:
            state:   Current LangGraph state dict.
            context: Runtime dependencies (model, memory, etc.).
            config:  User-configured parameter values for this node instance.

        Returns:
            Dict of state field updates to merge into the graph state.
        """
        ...

    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        """Return a routing function for conditional nodes.

        The function takes the current state and returns an output
        port ID (matching one of ``output_ports``).

        Non-conditional nodes return ``None``.
        """
        return None

    def get_dynamic_output_ports(
        self, config: Dict[str, Any],
    ) -> Optional[List[OutputPort]]:
        """Compute output ports from instance config at runtime.

        Override this in nodes whose port set depends on user
        configuration (e.g. configurable categories, route maps).

        Returns ``None`` to use the class-level ``output_ports``.
        """
        return None

    # ── Serialization ──

    def to_dict(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Serialize the node *type* definition for the frontend.

        If *config* is provided, dynamic output ports are computed.
        """
        ports = self.output_ports
        if config is not None:
            dynamic = self.get_dynamic_output_ports(config)
            if dynamic is not None:
                ports = dynamic

        d: Dict[str, Any] = {
            "node_type": self.node_type,
            "label": self.label,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "color": self.color,
            "is_conditional": len(ports) > 1,
            "parameters": [p.to_dict() for p in self.parameters],
            "output_ports": [p.to_dict() for p in ports],
        }
        # Include structured output schema if present
        if self.structured_output_schema:
            d["structured_output_schema"] = self.structured_output_schema
        # Include i18n translations for all locales
        if self.i18n:
            d["i18n"] = {
                locale: i18n_data.to_dict()
                for locale, i18n_data in self.i18n.items()
            }
        return d

    def get_help(self, locale: str = "en") -> Optional[Dict[str, Any]]:
        """Return help content for the given locale.

        Falls back to English if the locale is not available.
        """
        i18n_data = self.i18n.get(locale) or self.i18n.get("en")
        if i18n_data and i18n_data.help:
            return i18n_data.help.to_dict()
        return None


# ============================================================================
# Node Registry — singleton that holds all registered node types
# ============================================================================


class NodeRegistry:
    """Global registry of available node type definitions.

    Node classes decorate themselves with ``@register_node`` or
    call ``registry.register(cls)`` to make themselves available.

    Supports **aliases**: when a node type is renamed, the old
    name can be registered as an alias so that existing templates
    and saved workflows continue to resolve correctly.
    """

    def __init__(self) -> None:
        self._registry: Dict[str, BaseNode] = {}
        self._aliases: Dict[str, str] = {}

    def register(self, node_class: Type[BaseNode]) -> Type[BaseNode]:
        """Register a node class (creates & stores a singleton instance)."""
        instance = node_class()
        node_type = instance.node_type
        if not node_type:
            raise ValueError(
                f"{node_class.__name__} has empty node_type"
            )
        if node_type in self._registry:
            logger.warning(
                f"Node type '{node_type}' re-registered "
                f"({self._registry[node_type].__class__.__name__} → "
                f"{node_class.__name__})"
            )
        self._registry[node_type] = instance
        return node_class

    def register_alias(self, alias: str, canonical: str) -> None:
        """Register *alias* as an alternative name for *canonical*.

        Lookup via ``get(alias)`` will transparently return the
        node registered under *canonical*.
        """
        self._aliases[alias] = canonical

    def get(self, node_type: str) -> Optional[BaseNode]:
        """Lookup a node by its type identifier (or alias)."""
        node = self._registry.get(node_type)
        if node is None:
            canonical = self._aliases.get(node_type)
            if canonical:
                node = self._registry.get(canonical)
        return node

    def list_all(self) -> Dict[str, BaseNode]:
        """Return all registered nodes."""
        return dict(self._registry)

    def list_by_category(self) -> Dict[str, List[BaseNode]]:
        """Group registered nodes by category."""
        categories: Dict[str, List[BaseNode]] = {}
        for node in self._registry.values():
            categories.setdefault(node.category, []).append(node)
        return categories

    def to_catalog(self) -> List[Dict[str, Any]]:
        """Return a serializable catalog for the frontend."""
        return [n.to_dict() for n in self._registry.values()]


# ── Singleton ──

_registry_instance: Optional[NodeRegistry] = None


def get_node_registry() -> NodeRegistry:
    """Return the global ``NodeRegistry`` singleton."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = NodeRegistry()
    return _registry_instance


def register_node(cls: Type[BaseNode]) -> Type[BaseNode]:
    """Decorator — register a ``BaseNode`` subclass in the global registry."""
    get_node_registry().register(cls)
    return cls
