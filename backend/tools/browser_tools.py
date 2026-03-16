"""
Browser Tools — full browser automation powered by Playwright.

Provides real browser control: navigate to pages, click elements, fill forms,
take screenshots, extract content from JavaScript-rendered SPAs, and more.
Uses a persistent browser context so cookies/sessions carry across calls.

For simple static page fetching, prefer ``web_fetch`` (faster, no browser overhead).
Use these browser tools when you need:
  - JavaScript-rendered content (SPAs, dynamic pages)
  - Form filling and submission
  - Element clicking and interaction
  - Screenshots for visual inspection
  - Cookie/session persistence across multiple pages

Requires:
    pip install playwright
    playwright install chromium

This file is auto-loaded by MCPLoader (matches *_tools.py pattern).
"""

import asyncio
import base64
import json
import re
from typing import Optional
from tools.base import BaseTool


# ── Lazy singleton browser manager ──

class _BrowserManager:
    """Manages a single persistent Playwright browser instance.

    Lazily initialized on first use. The browser stays alive across
    tool calls so cookies, sessions, and page state persist.
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def _ensure_browser(self):
        """Start browser if not already running."""
        if self._page is not None:
            try:
                # Check if page is still usable
                await self._page.title()
                return
            except Exception:
                # Page/browser died — restart
                await self._cleanup()

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise ImportError(
                "playwright package is required for browser tools. "
                "Install with: pip install playwright && playwright install chromium"
            ) from exc

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        self._page = await self._context.new_page()

    async def get_page(self):
        """Get the active page (starts browser if needed)."""
        await self._ensure_browser()
        return self._page

    async def _cleanup(self):
        """Close everything."""
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def close(self):
        """Explicitly shut down the browser."""
        await self._cleanup()


# Global singleton
_manager = _BrowserManager()


def _run_async(coro):
    """Bridge async → sync for BaseTool.run()."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result(timeout=120)
    else:
        return asyncio.run(coro)


def _truncate(text: str, max_len: int = 50000) -> tuple:
    """Truncate text and return (text, was_truncated)."""
    if len(text) <= max_len:
        return text, False
    return text[:max_len], True


def _clean_text(html: str) -> str:
    """Extract readable text from HTML."""
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    html = re.sub(r"<(?:br|hr|p|div|h[1-6]|li|tr|blockquote)[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", "", html)
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = html.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    lines = [line.strip() for line in html.splitlines()]
    text = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# =============================================================================
# Tool 1: Navigate to a URL
# =============================================================================

class BrowserNavigateTool(BaseTool):
    """Navigate the browser to a URL and return the page content.

    Opens a real Chromium browser (headless) and navigates to the URL.
    Waits for page load including JavaScript execution, then extracts
    the rendered text content.

    The browser session persists — cookies, localStorage, and login
    state carry over between calls. Use this for:
      - JavaScript-rendered SPAs (React, Vue, Angular)
      - Pages that require prior navigation/login
      - Dynamic content that loads after initial HTML
    """

    name = "browser_navigate"
    description = (
        "Navigate a real browser to a URL and return the rendered page content. "
        "Executes JavaScript and waits for dynamic content to load. "
        "Use for SPAs, JS-rendered pages, or when web_fetch returns incomplete content. "
        "Browser session persists across calls (cookies, login state retained)."
    )

    def run(
        self,
        url: str,
        wait_for: Optional[str] = None,
        max_length: int = 50000,
    ) -> str:
        """Navigate to a URL.

        Args:
            url: Full URL to navigate to (e.g. "https://example.com")
            wait_for: Optional CSS selector to wait for before extracting content.
                      Use when page content loads dynamically (e.g. "main", "#content", ".article-body").
            max_length: Maximum characters of text to return (default: 50000).
        """
        return _run_async(self.arun(url, wait_for, max_length))

    async def arun(
        self,
        url: str,
        wait_for: Optional[str] = None,
        max_length: int = 50000,
    ) -> str:
        try:
            page = await _manager.get_page()

            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Wait a bit for JS to render
            await page.wait_for_timeout(1500)

            if wait_for:
                try:
                    await page.wait_for_selector(wait_for, timeout=10000)
                except Exception:
                    pass  # Continue even if selector not found

            title = await page.title()
            current_url = page.url
            html = await page.content()
            text = _clean_text(html)
            text, truncated = _truncate(text, max_length)

            return json.dumps({
                "url": current_url,
                "title": title,
                "status": response.status if response else None,
                "length": len(text),
                "truncated": truncated,
                "content": text,
            }, indent=2, ensure_ascii=False)

        except ImportError as e:
            return json.dumps({"error": str(e)}, indent=2)
        except Exception as e:
            return json.dumps({"error": f"Navigation failed: {e}", "url": url}, indent=2)


# =============================================================================
# Tool 2: Click an element
# =============================================================================

class BrowserClickTool(BaseTool):
    """Click an element on the current page.

    Finds an element by CSS selector and clicks it. Useful for:
      - Buttons and links
      - Menu items and dropdowns
      - "Load more" / pagination
      - Any interactive element

    After clicking, waits briefly for navigation or content updates.
    Returns the updated page state.
    """

    name = "browser_click"
    description = (
        "Click an element on the current browser page using a CSS selector. "
        "Use after browser_navigate to interact with buttons, links, menus, etc. "
        "Returns the updated page content after clicking."
    )

    def run(self, selector: str, max_length: int = 50000) -> str:
        """Click an element.

        Args:
            selector: CSS selector of the element to click (e.g. "button.submit", "#login-btn", "a[href='/next']")
            max_length: Maximum characters of text to return after clicking.
        """
        return _run_async(self.arun(selector, max_length))

    async def arun(self, selector: str, max_length: int = 50000) -> str:
        try:
            page = await _manager.get_page()

            await page.click(selector, timeout=10000)
            await page.wait_for_timeout(2000)  # Wait for any navigation/update

            title = await page.title()
            html = await page.content()
            text = _clean_text(html)
            text, truncated = _truncate(text, max_length)

            return json.dumps({
                "action": "click",
                "selector": selector,
                "url": page.url,
                "title": title,
                "length": len(text),
                "truncated": truncated,
                "content": text,
            }, indent=2, ensure_ascii=False)

        except Exception as e:
            return json.dumps({
                "error": f"Click failed: {e}",
                "selector": selector,
                "hint": "Verify the selector exists. Use browser_evaluate with document.querySelector() to test.",
            }, indent=2)


# =============================================================================
# Tool 3: Fill a form field
# =============================================================================

class BrowserFillTool(BaseTool):
    """Fill text into a form field on the current page.

    Finds an input/textarea by CSS selector and types text into it.
    Optionally submits the form by pressing Enter afterward.

    Use for:
      - Search boxes
      - Login forms
      - Any text input
    """

    name = "browser_fill"
    description = (
        "Fill text into a form field (input, textarea) on the current page. "
        "Use a CSS selector to target the field. "
        "Optionally press Enter to submit after filling."
    )

    def run(
        self,
        selector: str,
        value: str,
        press_enter: bool = False,
    ) -> str:
        """Fill a form field.

        Args:
            selector: CSS selector of the input field (e.g. "input[name='q']", "#search-box")
            value: Text to type into the field
            press_enter: Press Enter after filling (e.g. to submit a search form)
        """
        return _run_async(self.arun(selector, value, press_enter))

    async def arun(
        self,
        selector: str,
        value: str,
        press_enter: bool = False,
    ) -> str:
        try:
            page = await _manager.get_page()

            await page.fill(selector, value, timeout=10000)

            if press_enter:
                await page.press(selector, "Enter")
                await page.wait_for_timeout(2000)

            title = await page.title()

            return json.dumps({
                "action": "fill",
                "selector": selector,
                "value": value,
                "pressed_enter": press_enter,
                "url": page.url,
                "title": title,
                "status": "success",
            }, indent=2, ensure_ascii=False)

        except Exception as e:
            return json.dumps({
                "error": f"Fill failed: {e}",
                "selector": selector,
            }, indent=2)


# =============================================================================
# Tool 4: Take a screenshot
# =============================================================================

class BrowserScreenshotTool(BaseTool):
    """Take a screenshot of the current page.

    Captures the visible viewport (or a specific element) and returns
    it as a base64-encoded PNG. Useful for:
      - Visual verification of page state
      - Capturing error screens
      - Documenting UI state
    """

    name = "browser_screenshot"
    description = (
        "Take a screenshot of the current browser page. "
        "Returns a base64-encoded PNG image. "
        "Use for visual inspection of page state or capturing errors."
    )

    def run(
        self,
        selector: Optional[str] = None,
        full_page: bool = False,
    ) -> str:
        """Take a screenshot.

        Args:
            selector: Optional CSS selector to screenshot a specific element instead of the viewport.
            full_page: If True, capture the entire scrollable page (not just the viewport).
        """
        return _run_async(self.arun(selector, full_page))

    async def arun(
        self,
        selector: Optional[str] = None,
        full_page: bool = False,
    ) -> str:
        try:
            page = await _manager.get_page()
            title = await page.title()

            if selector:
                element = await page.query_selector(selector)
                if not element:
                    return json.dumps({
                        "error": f"Element not found: {selector}",
                    }, indent=2)
                png_bytes = await element.screenshot()
            else:
                png_bytes = await page.screenshot(full_page=full_page)

            b64 = base64.b64encode(png_bytes).decode("ascii")

            return json.dumps({
                "action": "screenshot",
                "url": page.url,
                "title": title,
                "selector": selector,
                "full_page": full_page,
                "format": "png",
                "size_bytes": len(png_bytes),
                "image_base64": b64,
            }, indent=2)

        except Exception as e:
            return json.dumps({"error": f"Screenshot failed: {e}"}, indent=2)


# =============================================================================
# Tool 5: Execute JavaScript
# =============================================================================

class BrowserEvaluateTool(BaseTool):
    """Execute JavaScript code in the browser page context.

    Runs arbitrary JavaScript and returns the result. Use for:
      - Extracting specific data (e.g. ``document.querySelector('.price').textContent``)
      - Checking page state (e.g. ``document.querySelectorAll('.item').length``)
      - Scrolling (e.g. ``window.scrollTo(0, document.body.scrollHeight)``)
      - Any DOM manipulation or data extraction
    """

    name = "browser_evaluate"
    description = (
        "Execute JavaScript in the current browser page and return the result. "
        "Use for precise data extraction, DOM queries, scrolling, "
        "or any custom browser-side logic."
    )

    def run(self, expression: str) -> str:
        """Execute JavaScript.

        Args:
            expression: JavaScript expression or code to execute.
                        The return value is serialized to JSON.
                        Examples:
                          - "document.title"
                          - "document.querySelector('.price').textContent"
                          - "[...document.querySelectorAll('a')].map(a => ({text: a.textContent, href: a.href}))"
                          - "window.scrollTo(0, document.body.scrollHeight)"
        """
        return _run_async(self.arun(expression))

    async def arun(self, expression: str) -> str:
        try:
            page = await _manager.get_page()
            result = await page.evaluate(expression)

            return json.dumps({
                "action": "evaluate",
                "expression": expression,
                "result": result,
            }, indent=2, ensure_ascii=False)

        except Exception as e:
            return json.dumps({
                "error": f"JavaScript evaluation failed: {e}",
                "expression": expression,
            }, indent=2)


# =============================================================================
# Tool 6: Get current page info
# =============================================================================

class BrowserGetPageInfoTool(BaseTool):
    """Get information about the current browser page state.

    Returns the current URL, title, and optionally a list of
    interactive elements (links, buttons, inputs) visible on the page.
    Use to understand the current page before deciding what to click or fill.
    """

    name = "browser_page_info"
    description = (
        "Get the current browser page URL, title, and list of interactive elements "
        "(links, buttons, inputs). Use to inspect page state before interacting."
    )

    def run(self, include_elements: bool = True) -> str:
        """Get page information.

        Args:
            include_elements: If True, include lists of links, buttons, and form fields on the page.
        """
        return _run_async(self.arun(include_elements))

    async def arun(self, include_elements: bool = True) -> str:
        try:
            page = await _manager.get_page()
            title = await page.title()
            url = page.url

            result = {
                "url": url,
                "title": title,
            }

            if include_elements:
                # Extract interactive elements via JS
                elements = await page.evaluate("""() => {
                    const links = [...document.querySelectorAll('a[href]')].slice(0, 30).map(a => ({
                        text: (a.textContent || '').trim().slice(0, 80),
                        href: a.href,
                    })).filter(l => l.text);

                    const buttons = [...document.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"]')]
                        .slice(0, 20).map(b => ({
                            text: (b.textContent || b.value || '').trim().slice(0, 80),
                            selector: b.id ? '#' + b.id : b.className ? '.' + b.className.split(' ')[0] : b.tagName.toLowerCase(),
                        })).filter(b => b.text);

                    const inputs = [...document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select')]
                        .slice(0, 20).map(el => ({
                            type: el.type || el.tagName.toLowerCase(),
                            name: el.name || el.id || '',
                            placeholder: el.placeholder || '',
                            selector: el.id ? '#' + el.id : el.name ? `[name="${el.name}"]` : el.tagName.toLowerCase(),
                            value: el.value ? el.value.slice(0, 50) : '',
                        }));

                    return { links, buttons, inputs };
                }""")
                result["links"] = elements.get("links", [])
                result["buttons"] = elements.get("buttons", [])
                result["inputs"] = elements.get("inputs", [])
                result["element_summary"] = (
                    f"{len(result['links'])} links, "
                    f"{len(result['buttons'])} buttons, "
                    f"{len(result['inputs'])} inputs"
                )

            return json.dumps(result, indent=2, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"error": f"Page info failed: {e}"}, indent=2)


# =============================================================================
# Tool 7: Close the browser
# =============================================================================

class BrowserCloseTool(BaseTool):
    """Close the browser and release resources.

    Shuts down the Chromium instance and clears all session state
    (cookies, localStorage, open pages). A new browser will be
    started automatically on the next browser_navigate call.
    """

    name = "browser_close"
    description = (
        "Close the browser and release all resources. "
        "Clears cookies, session, and page state. "
        "A fresh browser starts on the next browser_navigate call."
    )

    def run(self) -> str:
        """Close the browser."""
        return _run_async(self.arun())

    async def arun(self) -> str:
        try:
            await _manager.close()
            return json.dumps({
                "action": "close",
                "status": "Browser closed successfully.",
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": f"Close failed: {e}"}, indent=2)


# =============================================================================
# Export list — MCPLoader auto-collects these
# =============================================================================

TOOLS = [
    BrowserNavigateTool(),
    BrowserClickTool(),
    BrowserFillTool(),
    BrowserScreenshotTool(),
    BrowserEvaluateTool(),
    BrowserGetPageInfoTool(),
    BrowserCloseTool(),
]
