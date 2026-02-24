"""
Example Tools

Example tool file. Use this as a reference for creating custom tools.
Files named *_tool.py or *_tools.py are automatically loaded.
"""
from tools.base import tool, BaseTool


# =============================================================================
# Method 1: Using @tool decorator (simple and recommended)
# =============================================================================

@tool
def add_numbers(a: int, b: int) -> str:
    """
    Add two numbers together.

    Args:
        a: First number
        b: Second number

    Returns:
        Sum of the two numbers
    """
    return str(a + b)


@tool
def multiply_numbers(a: int, b: int) -> str:
    """
    Multiply two numbers.

    Args:
        a: First number
        b: Second number

    Returns:
        Product of the two numbers
    """
    return str(a * b)


@tool
def reverse_string(text: str) -> str:
    """
    Reverse a string.

    Args:
        text: The string to reverse

    Returns:
        The reversed string
    """
    return text[::-1]


@tool
def count_words(text: str) -> str:
    """
    Count the number of words in a text.

    Args:
        text: The text to count words in

    Returns:
        Word count
    """
    words = text.split()
    return f"Word count: {len(words)}"


# =============================================================================
# Method 2: Subclass BaseTool (for complex logic)
# =============================================================================

class EchoTool(BaseTool):
    """Simple echo tool for testing."""

    name = "echo"
    description = "Echo back the input message"

    def run(self, message: str) -> str:
        return f"Echo: {message}"


class CalculatorTool(BaseTool):
    """Safe calculator that evaluates expressions."""

    name = "calculator"
    description = "Safely evaluate a mathematical expression"

    # Allowed operators and functions
    ALLOWED_NAMES = {
        'abs': abs,
        'round': round,
        'min': min,
        'max': max,
        'sum': sum,
        'pow': pow,
    }

    def run(self, expression: str) -> str:
        """
        Evaluate a math expression safely.

        Args:
            expression: Mathematical expression (e.g., "2 + 3 * 4")
        """
        try:
            # Use only allowed names for safe evaluation
            result = eval(expression, {"__builtins__": {}}, self.ALLOWED_NAMES)
            return str(result)
        except Exception as e:
            return f"Error: {e}"


# =============================================================================
# Tools to export (optional)
# If not defined, all tools in the file are automatically collected
# =============================================================================

TOOLS = [
    add_numbers,
    multiply_numbers,
    reverse_string,
    count_words,
    EchoTool(),
    CalculatorTool(),
]
