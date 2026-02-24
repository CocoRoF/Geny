# Tools Folder

Add **Python tool files** to this folder to automatically convert them into MCP servers that are **available in all Claude Code sessions**.

## Quick Start

### 1. Create Tool File

Create a file with the pattern `{name}_tool.py` or `{name}_tools.py`.

### 2. Define Tools

#### Method 1: Using `@tool` Decorator (Recommended)

```python
# my_tool.py
from tools.base import tool

@tool
def search_web(query: str) -> str:
    """
    Search the web for information.

    Args:
        query: The search query string

    Returns:
        Search results as text
    """
    # Actual implementation
    return f"Search results for: {query}"

@tool
def calculate(expression: str) -> str:
    """
    Calculate a mathematical expression.

    Args:
        expression: Math expression to evaluate (e.g., "2 + 3 * 4")

    Returns:
        Calculation result
    """
    try:
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {e}"
```

#### Method 2: Subclass `BaseTool`

```python
# advanced_tool.py
from tools.base import BaseTool

class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for information"

    def run(self, query: str) -> str:
        # Actual implementation
        return f"Results for: {query}"

class DatabaseQueryTool(BaseTool):
    name = "query_database"
    description = "Execute SQL query on the database"

    def run(self, sql: str, database: str = "main") -> str:
        # Actual implementation
        return f"Query result from {database}"
```

### 3. Export Tools

Define a `TOOLS` list at the end of the file to specify which tools to export:

```python
# Decorator approach
TOOLS = [search_web, calculate]

# Or class approach
TOOLS = [WebSearchTool(), DatabaseQueryTool()]
```

If `TOOLS` is not defined, all `@tool` functions and `BaseTool` instances in the file are automatically collected.

## Complete Example

```python
# api_tools.py
"""
External API integration tools
"""
import httpx
from tools.base import tool

@tool
def get_weather(city: str) -> str:
    """
    Get current weather for a city.

    Args:
        city: City name (e.g., "Seoul", "New York")

    Returns:
        Current weather information
    """
    # In practice, call actual API
    return f"Weather in {city}: Sunny, 22°C"

@tool
def translate_text(text: str, target_lang: str = "en") -> str:
    """
    Translate text to target language.

    Args:
        text: Text to translate
        target_lang: Target language code (default: "en")

    Returns:
        Translated text
    """
    # In practice, call translation API
    return f"[{target_lang}] {text}"

@tool
async def fetch_url(url: str) -> str:
    """
    Fetch content from a URL.

    Args:
        url: URL to fetch

    Returns:
        Response content
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.text[:1000]  # First 1000 chars only

# List of tools to export
TOOLS = [get_weather, translate_text, fetch_url]
```

## Auto-Loading

1. When `main.py` runs, scans all `*_tool.py` and `*_tools.py` files in `tools/`
2. Collects tools from each file and wraps them as MCP servers
3. Wrapped MCP servers are **available in all sessions by default**

## File Structure

```
tools/
├── README.md           # This file
├── base.py             # BaseTool interface, @tool decorator
├── __init__.py         # Package initialization
├── _mcp_server.py      # MCP server wrapper (internal)
├── example_tool.py     # Example tool (copy and modify)
└── my_custom_tool.py   # Your custom tools
```

## Important Notes

1. **Filename**: Only `*_tool.py` or `*_tools.py` patterns are auto-loaded
2. **Docstring Required**: Used as the tool's `description`
3. **Type Hints Recommended**: Used for automatic parameter schema generation
4. **Async Support**: `async def` functions are fully supported
5. **Error Handling**: Exceptions are caught and returned as error messages

## Debugging

Verify that tools are loaded correctly:

```bash
# Check logs when server starts
python main.py

# Example output:
# [MCP Loader] Loaded tools from: api_tools.py
# [MCP Loader]   - get_weather
# [MCP Loader]   - translate_text
# [MCP Loader]   - fetch_url
```

## Advanced: Tool Parameters Schema

The `@tool` decorator automatically generates JSON Schema from type hints:

```python
from typing import Optional, List
from tools.base import tool

@tool
def advanced_search(
    query: str,
    max_results: int = 10,
    filters: Optional[List[str]] = None,
    exact_match: bool = False
) -> str:
    """
    Advanced search with filters.

    Args:
        query: Search query
        max_results: Maximum number of results (default: 10)
        filters: Optional list of filters to apply
        exact_match: If True, only return exact matches

    Returns:
        Search results
    """
    pass
```

This generates the schema:
```json
{
  "properties": {
    "query": {"type": "string"},
    "max_results": {"type": "integer", "default": 10},
    "filters": {"type": "array", "items": {"type": "string"}},
    "exact_match": {"type": "boolean", "default": false}
  },
  "required": ["query"]
}
```
