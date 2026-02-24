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

    # ── Serialization ──

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the node *type* definition for the frontend."""
        return {
            "node_type": self.node_type,
            "label": self.label,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "color": self.color,
            "is_conditional": self.is_conditional,
            "parameters": [p.to_dict() for p in self.parameters],
            "output_ports": [p.to_dict() for p in self.output_ports],
        }


# ============================================================================
# Node Registry — singleton that holds all registered node types
# ============================================================================


class NodeRegistry:
    """Global registry of available node type definitions.

    Node classes decorate themselves with ``@register_node`` or
    call ``registry.register(cls)`` to make themselves available.
    """

    def __init__(self) -> None:
        self._registry: Dict[str, BaseNode] = {}

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

    def get(self, node_type: str) -> Optional[BaseNode]:
        """Lookup a node by its type identifier."""
        return self._registry.get(node_type)

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
