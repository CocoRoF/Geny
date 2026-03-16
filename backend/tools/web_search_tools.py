"""
Web Search Tools — built-in search tools powered by DDGS (DuckDuckGo Search).

Provides web text search, news search, and image search capabilities
using the ``ddgs`` metasearch library. These tools are automatically
loaded by MCPLoader (matches *_tools.py pattern) and registered as
built-in tools under the ``_builtin_tools`` MCP server.

Requires:
    pip install ddgs
"""

import json
from typing import Optional
from tools.base import BaseTool


def _safe_ddgs_import():
    """Import DDGS with a clear error if not installed."""
    try:
        from ddgs import DDGS
        return DDGS
    except ImportError as exc:
        raise ImportError(
            "ddgs package is required for web search tools. "
            "Install it with: pip install ddgs"
        ) from exc


class WebSearchTool(BaseTool):
    """Search the web using multiple search engines.

    Performs a metasearch across engines like Google, Bing, DuckDuckGo,
    Brave, and others. Returns titles, URLs, and snippets for each result.

    Use this to find current information, documentation, code examples,
    or any web-accessible content.
    """

    name = "web_search"
    description = (
        "Search the web for information. Returns titles, URLs, and snippets "
        "from multiple search engines. Use for finding documentation, articles, "
        "code examples, current events, or any web-accessible information."
    )

    def run(
        self,
        query: str,
        max_results: int = 5,
        region: str = "us-en",
        timelimit: Optional[str] = None,
    ) -> str:
        """Search the web.

        Args:
            query: Search query (e.g. "Python asyncio tutorial")
            max_results: Maximum number of results (default: 5, max: 20)
            region: Region code (e.g. "us-en", "ko-kr", "ja-jp"). Defaults to "us-en".
            timelimit: Time filter — "d" (day), "w" (week), "m" (month), "y" (year). None for all time.
        """
        DDGS = _safe_ddgs_import()

        max_results = min(max(1, max_results), 20)

        try:
            results = DDGS().text(
                query,
                region=region,
                safesearch="moderate",
                timelimit=timelimit,
                max_results=max_results,
                backend="auto",
            )
        except Exception as e:
            return json.dumps({"error": f"Search failed: {e}"}, indent=2)

        if not results:
            return json.dumps({
                "results": [],
                "message": f"No results found for '{query}'.",
            }, indent=2)

        formatted = []
        for i, r in enumerate(results, 1):
            entry = {
                "rank": i,
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            formatted.append(entry)

        return json.dumps({
            "query": query,
            "result_count": len(formatted),
            "results": formatted,
        }, indent=2, ensure_ascii=False)


class NewsSearchTool(BaseTool):
    """Search for recent news articles.

    Searches news sources across Bing, DuckDuckGo, and Yahoo for
    the latest news on a topic. Returns headlines, sources, dates,
    and article URLs.
    """

    name = "news_search"
    description = (
        "Search for recent news articles on a topic. Returns headlines, "
        "sources, publication dates, and URLs. Use for current events, "
        "industry news, or any time-sensitive information."
    )

    def run(
        self,
        query: str,
        max_results: int = 5,
        region: str = "us-en",
        timelimit: Optional[str] = None,
    ) -> str:
        """Search for news.

        Args:
            query: News search query (e.g. "AI regulation 2026")
            max_results: Maximum number of results (default: 5, max: 20)
            region: Region code (e.g. "us-en", "ko-kr"). Defaults to "us-en".
            timelimit: Time filter — "d" (day), "w" (week), "m" (month). None for all time.
        """
        DDGS = _safe_ddgs_import()

        max_results = min(max(1, max_results), 20)

        try:
            results = DDGS().news(
                query,
                region=region,
                safesearch="moderate",
                timelimit=timelimit,
                max_results=max_results,
                backend="auto",
            )
        except Exception as e:
            return json.dumps({"error": f"News search failed: {e}"}, indent=2)

        if not results:
            return json.dumps({
                "results": [],
                "message": f"No news found for '{query}'.",
            }, indent=2)

        formatted = []
        for i, r in enumerate(results, 1):
            entry = {
                "rank": i,
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "source": r.get("source", ""),
                "date": r.get("date", ""),
                "snippet": r.get("body", ""),
            }
            formatted.append(entry)

        return json.dumps({
            "query": query,
            "result_count": len(formatted),
            "results": formatted,
        }, indent=2, ensure_ascii=False)


# =============================================================================
# Export list — MCPLoader auto-collects these
# =============================================================================

TOOLS = [
    WebSearchTool(),
    NewsSearchTool(),
]
