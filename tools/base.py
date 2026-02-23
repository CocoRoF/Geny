"""
Tools Base Module

Provides base interfaces and decorators for tool definition.

Usage:
    # Method 1: @tool decorator (for simple tools)
    from tools.base import tool

    @tool
    def my_function(param: str) -> str:
        '''Tool description here'''
        return result

    # Method 2: BaseTool class inheritance (for complex tools)
    from tools.base import BaseTool

    class MyTool(BaseTool):
        name = "my_tool"
        description = "Tool description"

        def run(self, param: str) -> str:
            return result
"""
import functools
import inspect
import json
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Union, get_type_hints


class BaseTool(ABC):
    """
    Base class for tools

    All custom tools should inherit from this class.

    Attributes:
        name: Tool name (must be unique)
        description: Tool description (used by Claude for tool selection)
        parameters: Parameter schema (can be auto-generated)

    Example:
        class MyTool(BaseTool):
            name = "my_tool"
            description = "Does something useful"

            def run(self, query: str, limit: int = 10) -> str:
                return f"Results for {query}, limit {limit}"
    """

    name: str = ""
    description: str = ""
    parameters: Optional[Dict[str, Any]] = None

    def __init__(self):
        if not self.name:
            self.name = self.__class__.__name__.lower().replace('tool', '')
        if not self.description:
            self.description = self.__doc__ or f"Tool: {self.name}"
        if self.parameters is None:
            self.parameters = self._generate_parameters_schema()

    def _generate_parameters_schema(self) -> Dict[str, Any]:
        """Generate parameter schema from run method signature"""
        schema = {
            "type": "object",
            "properties": {},
            "required": []
        }

        try:
            sig = inspect.signature(self.run)
            hints = get_type_hints(self.run) if hasattr(self.run, '__annotations__') else {}

            for param_name, param in sig.parameters.items():
                if param_name == 'self':
                    continue

                # Type inference
                param_type = hints.get(param_name, str)
                json_type = self._python_type_to_json(param_type)

                schema["properties"][param_name] = {
                    "type": json_type,
                    "description": f"Parameter: {param_name}"
                }

                # Check required parameters
                if param.default == inspect.Parameter.empty:
                    schema["required"].append(param_name)
                else:
                    schema["properties"][param_name]["default"] = param.default

        except Exception:
            pass

        return schema

    @staticmethod
    def _python_type_to_json(python_type: type) -> str:
        """Convert Python type to JSON schema type"""
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
            type(None): "null"
        }

        # Handle Optional, Union, etc.
        origin = getattr(python_type, '__origin__', None)
        if origin is Union:
            args = getattr(python_type, '__args__', ())
            for arg in args:
                if arg is not type(None):
                    return type_map.get(arg, "string")

        return type_map.get(python_type, "string")

    @abstractmethod
    def run(self, **kwargs) -> str:
        """
        Execute the tool

        Args:
            **kwargs: Tool parameters

        Returns:
            Execution result as string
        """
        pass

    async def arun(self, **kwargs) -> str:
        """
        Async tool execution (default: sync execution)

        Override to implement async behavior
        """
        return self.run(**kwargs)

    def __call__(self, **kwargs) -> str:
        """Call the tool like a function"""
        return self.run(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        """Convert tool info to dictionary"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters
        }


class ToolWrapper:
    """
    Function wrapper created by @tool decorator

    Wraps regular functions to be compatible with BaseTool interface.
    """

    def __init__(self, func: Callable, name: Optional[str] = None, description: Optional[str] = None):
        self.func = func
        self.name = name or func.__name__
        self.description = description or func.__doc__ or f"Tool: {self.name}"
        self.parameters = self._generate_parameters_schema()
        self.is_async = inspect.iscoroutinefunction(func)

        # Copy function metadata
        functools.update_wrapper(self, func)

    def _generate_parameters_schema(self) -> Dict[str, Any]:
        """Generate parameter schema from function signature"""
        schema = {
            "type": "object",
            "properties": {},
            "required": []
        }

        try:
            sig = inspect.signature(self.func)
            hints = get_type_hints(self.func) if hasattr(self.func, '__annotations__') else {}

            for param_name, param in sig.parameters.items():
                param_type = hints.get(param_name, str)
                json_type = BaseTool._python_type_to_json(param_type)

                # Try to extract parameter description from docstring
                param_desc = f"Parameter: {param_name}"
                if self.func.__doc__:
                    # Find parameter description in Args: section
                    import re
                    match = re.search(rf'{param_name}:\s*(.+?)(?:\n|$)', self.func.__doc__)
                    if match:
                        param_desc = match.group(1).strip()

                schema["properties"][param_name] = {
                    "type": json_type,
                    "description": param_desc
                }

                if param.default == inspect.Parameter.empty:
                    schema["required"].append(param_name)
                else:
                    if param.default is not None:
                        schema["properties"][param_name]["default"] = param.default

        except Exception:
            pass

        return schema

    def run(self, **kwargs) -> str:
        """Synchronous execution"""
        result = self.func(**kwargs)
        return self._format_result(result)

    async def arun(self, **kwargs) -> str:
        """Async execution"""
        if self.is_async:
            result = await self.func(**kwargs)
        else:
            result = self.func(**kwargs)
        return self._format_result(result)

    def _format_result(self, result: Any) -> str:
        """Convert result to string"""
        if isinstance(result, str):
            return result
        elif isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False, indent=2)
        else:
            return str(result)

    def __call__(self, *args, **kwargs):
        """Callable like the original function"""
        return self.func(*args, **kwargs)

    def to_dict(self) -> Dict[str, Any]:
        """Convert tool info to dictionary"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters
        }


def tool(
    func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None
) -> Union[ToolWrapper, Callable[[Callable], ToolWrapper]]:
    """
    Decorator to convert a function into a tool

    Args:
        func: Function to convert
        name: Tool name (default: function name)
        description: Tool description (default: docstring)

    Usage:
        @tool
        def my_func(param: str) -> str:
            '''Description here'''
            return result

        @tool(name="custom_name", description="Custom description")
        def another_func(param: str) -> str:
            return result
    """
    def decorator(f: Callable) -> ToolWrapper:
        return ToolWrapper(f, name=name, description=description)

    if func is not None:
        # Used as @tool
        return decorator(func)
    else:
        # Used as @tool(...)
        return decorator


def is_tool(obj: Any) -> bool:
    """Check if object is a tool"""
    return isinstance(obj, (BaseTool, ToolWrapper))


def get_tool_info(obj: Any) -> Optional[Dict[str, Any]]:
    """Extract tool information"""
    if isinstance(obj, (BaseTool, ToolWrapper)):
        return obj.to_dict()
    return None
