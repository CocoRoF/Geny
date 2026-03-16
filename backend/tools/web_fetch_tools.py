"""
Web Fetch Tools — built-in tools for fetching and extracting web page content.

Provides lightweight HTTP-based page fetching and content extraction
using ``httpx`` (already a project dependency). No browser engine needed —
ideal for static pages, APIs, and documentation sites.

For JavaScript-heavy SPAs or interactive pages, use the browser_tools
(Playwright-based) instead.

This file is auto-loaded by MCPLoader (matches *_tools.py pattern).
"""

import json
import re
import asyncio
from typing import Optional
from tools.base import BaseTool

import httpx

# ── Shared HTTP client defaults ──
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
}
_MAX_CONTENT_LENGTH = 100_000  # 100 KB text limit to avoid token explosion


def _html_to_text(html: str) -> str:
    """Extract readable text from HTML, stripping tags/scripts/styles."""
    # Remove script and style blocks
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<noscript[^>]*>.*?</noscript>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML comments
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    # Convert common block elements to newlines
    html = re.sub(r"<(?:br|hr|p|div|h[1-6]|li|tr|blockquote)[^>]*>", "\n", html, flags=re.IGNORECASE)
    # Strip remaining tags
    html = re.sub(r"<[^>]+>", "", html)
    # Decode common HTML entities
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = html.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # Collapse whitespace
    lines = [line.strip() for line in html.splitlines()]
    text = "\n".join(line for line in lines if line)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class WebFetchTool(BaseTool):
    """Fetch a web page and extract its text content.

    Makes an HTTP GET request to the given URL and returns the page
    content as clean text (HTML tags stripped). Supports following
    redirects and custom headers.

    Best for:
      - Documentation pages, articles, blog posts
      - API responses (JSON, XML, plain text)
      - Static web pages

    Not suitable for:
      - JavaScript-rendered SPAs (use browser_navigate instead)
      - Pages requiring login/cookies (use browser tools instead)
    """

    name = "web_fetch"
    description = (
        "Fetch a web page by URL and extract its text content. "
        "Strips HTML tags and returns clean readable text. "
        "Use for reading documentation, articles, API responses, "
        "or any static web page. Fast and lightweight."
    )

    def run(
        self,
        url: str,
        extract_text: bool = True,
        max_length: int = 50000,
        timeout: float = 30.0,
    ) -> str:
        """Fetch a web page.

        Args:
            url: Full URL to fetch (e.g. "https://docs.python.org/3/library/asyncio.html")
            extract_text: If True, strip HTML and return clean text. If False, return raw HTML.
            max_length: Maximum characters to return (default: 50000). Truncates if longer.
            timeout: Request timeout in seconds (default: 30).
        """
        max_length = min(max(1000, max_length), _MAX_CONTENT_LENGTH)
        timeout = min(max(5.0, timeout), 60.0)

        try:
            with httpx.Client(
                timeout=timeout,
                headers=_DEFAULT_HEADERS,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                response = client.get(url)
                response.raise_for_status()
        except httpx.TimeoutException:
            return json.dumps({
                "error": f"Request timed out after {timeout}s",
                "url": url,
            }, indent=2)
        except httpx.HTTPStatusError as e:
            return json.dumps({
                "error": f"HTTP {e.response.status_code}: {e.response.reason_phrase}",
                "url": url,
            }, indent=2)
        except Exception as e:
            return json.dumps({
                "error": f"Fetch failed: {e}",
                "url": url,
            }, indent=2)

        content_type = response.headers.get("content-type", "")
        raw_text = response.text

        # For non-HTML content (JSON, plain text, XML), return as-is
        if "text/html" not in content_type and extract_text:
            text = raw_text[:max_length]
            truncated = len(raw_text) > max_length
            return json.dumps({
                "url": str(response.url),
                "status": response.status_code,
                "content_type": content_type.split(";")[0].strip(),
                "length": len(raw_text),
                "truncated": truncated,
                "content": text,
            }, indent=2, ensure_ascii=False)

        # HTML content
        if extract_text:
            text = _html_to_text(raw_text)
        else:
            text = raw_text

        if len(text) > max_length:
            text = text[:max_length]
            truncated = True
        else:
            truncated = False

        return json.dumps({
            "url": str(response.url),
            "status": response.status_code,
            "content_type": content_type.split(";")[0].strip(),
            "length": len(text),
            "truncated": truncated,
            "content": text,
        }, indent=2, ensure_ascii=False)

    async def arun(
        self,
        url: str,
        extract_text: bool = True,
        max_length: int = 50000,
        timeout: float = 30.0,
    ) -> str:
        """Async fetch a web page.

        Args:
            url: Full URL to fetch
            extract_text: Strip HTML and return clean text
            max_length: Maximum characters to return
            timeout: Request timeout in seconds
        """
        max_length = min(max(1000, max_length), _MAX_CONTENT_LENGTH)
        timeout = min(max(5.0, timeout), 60.0)

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                headers=_DEFAULT_HEADERS,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.TimeoutException:
            return json.dumps({"error": f"Request timed out after {timeout}s", "url": url}, indent=2)
        except httpx.HTTPStatusError as e:
            return json.dumps({"error": f"HTTP {e.response.status_code}", "url": url}, indent=2)
        except Exception as e:
            return json.dumps({"error": f"Fetch failed: {e}", "url": url}, indent=2)

        content_type = response.headers.get("content-type", "")
        raw_text = response.text

        if "text/html" not in content_type and extract_text:
            text = raw_text[:max_length]
            return json.dumps({
                "url": str(response.url), "status": response.status_code,
                "content_type": content_type.split(";")[0].strip(),
                "length": len(raw_text), "truncated": len(raw_text) > max_length,
                "content": text,
            }, indent=2, ensure_ascii=False)

        text = _html_to_text(raw_text) if extract_text else raw_text
        truncated = len(text) > max_length
        if truncated:
            text = text[:max_length]

        return json.dumps({
            "url": str(response.url), "status": response.status_code,
            "content_type": content_type.split(";")[0].strip(),
            "length": len(text), "truncated": truncated,
            "content": text,
        }, indent=2, ensure_ascii=False)


class WebFetchMultipleTool(BaseTool):
    """Fetch multiple web pages in parallel.

    Fetches up to 5 URLs concurrently and returns the extracted text
    content from each. Useful when you need to compare information
    from several sources or gather data from multiple pages at once.
    """

    name = "web_fetch_multiple"
    description = (
        "Fetch multiple web pages in parallel (up to 5 URLs). "
        "Returns extracted text content from each page. "
        "Use when comparing sources or gathering data from multiple URLs."
    )

    def run(
        self,
        urls: list,
        extract_text: bool = True,
        max_length_per_page: int = 20000,
        timeout: float = 30.0,
    ) -> str:
        """Fetch multiple pages.

        Args:
            urls: List of URLs to fetch (max 5)
            extract_text: Strip HTML and return clean text (default: True)
            max_length_per_page: Max characters per page (default: 20000)
            timeout: Request timeout per page in seconds (default: 30)
        """
        urls = urls[:5]  # Cap at 5
        max_length_per_page = min(max(1000, max_length_per_page), 50000)

        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    results = pool.submit(
                        asyncio.run,
                        self._fetch_all(urls, extract_text, max_length_per_page, timeout),
                    ).result(timeout=timeout * 2)
            else:
                results = asyncio.run(
                    self._fetch_all(urls, extract_text, max_length_per_page, timeout)
                )
        except Exception as e:
            return json.dumps({"error": f"Parallel fetch failed: {e}"}, indent=2)

        return json.dumps({
            "fetched": len(results),
            "results": results,
        }, indent=2, ensure_ascii=False)

    async def _fetch_all(
        self, urls: list, extract_text: bool, max_length: int, timeout: float
    ) -> list:
        fetcher = WebFetchTool()
        tasks = [fetcher.arun(url, extract_text, max_length, timeout) for url in urls]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for url, raw in zip(urls, raw_results):
            if isinstance(raw, Exception):
                results.append({"url": url, "error": str(raw)})
            else:
                try:
                    results.append(json.loads(raw))
                except json.JSONDecodeError:
                    results.append({"url": url, "content": raw})
        return results


# =============================================================================
# Export list — MCPLoader auto-collects these
# =============================================================================

TOOLS = [
    WebFetchTool(),
    WebFetchMultipleTool(),
]
