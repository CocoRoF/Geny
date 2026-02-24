"""
Internal Proxy Client

Proxy client for forwarding requests to other Pods in multi-pod environments
"""
from logging import getLogger
from typing import Optional, Dict, Any, Tuple
import httpx
from fastapi import Request, Response

logger = getLogger(__name__)

# Proxy request timeout (seconds)
PROXY_TIMEOUT = 60.0

# Proxy header (prevent infinite loop)
PROXY_HEADER = "X-Claude-Control-Proxied"
PROXY_SOURCE_HEADER = "X-Claude-Control-Source-Pod"


class InternalProxy:
    """
    Internal inter-Pod proxy client

    Forwards requests to the appropriate Pod when session is on a different Pod
    """

    _instance: Optional['InternalProxy'] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, timeout: float = PROXY_TIMEOUT):
        if hasattr(self, '_initialized') and self._initialized:
            return

        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._initialized = True

        logger.info("✅ Internal Proxy initialized")

    async def _get_client(self) -> httpx.AsyncClient:
        """Get HTTP client (lazy initialization)"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                follow_redirects=True
            )
        return self._client

    async def close(self):
        """Close client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def is_proxied_request(self, request: Request) -> bool:
        """
        Check if request is already proxied (prevent infinite loop)
        """
        return request.headers.get(PROXY_HEADER) == "true"

    async def proxy_request(
        self,
        target_pod_ip: str,
        target_port: int,
        request: Request,
        source_pod_name: str
    ) -> Response:
        """
        Proxy request to another Pod

        Args:
            target_pod_ip: Target Pod's IP address
            target_port: Target Pod's port
            request: Original FastAPI Request
            source_pod_name: Current Pod name (for logging)

        Returns:
            Proxied response
        """
        client = await self._get_client()

        # Build target URL
        target_url = f"http://{target_pod_ip}:{target_port}{request.url.path}"
        if request.url.query:
            target_url += f"?{request.url.query}"

        logger.info(f"🔀 Proxying request: {request.method} {request.url.path} -> {target_pod_ip}:{target_port}")

        # Copy headers and add proxy header
        headers = dict(request.headers)
        headers[PROXY_HEADER] = "true"
        headers[PROXY_SOURCE_HEADER] = source_pod_name

        # Remove host header (let target server set it)
        headers.pop("host", None)

        try:
            # Read request body
            body = await request.body()

            # Send proxy request
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body
            )

            logger.info(f"✅ Proxy response: {response.status_code}")

            # Convert to FastAPI Response
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type")
            )

        except httpx.TimeoutException:
            logger.error(f"❌ Proxy timeout: {target_url}")
            return Response(
                content='{"error": "Proxy timeout"}',
                status_code=504,
                media_type="application/json"
            )

        except httpx.ConnectError as e:
            logger.error(f"❌ Proxy connection error: {target_url} - {e}")
            return Response(
                content='{"error": "Target pod unreachable"}',
                status_code=502,
                media_type="application/json"
            )

        except Exception as e:
            logger.error(f"❌ Proxy error: {e}", exc_info=True)
            return Response(
                content=f'{{"error": "Proxy error: {str(e)}"}}',
                status_code=500,
                media_type="application/json"
            )

    async def check_pod_health(self, pod_ip: str, port: int) -> bool:
        """
        Check target Pod's health status

        Args:
            pod_ip: Pod IP
            port: Port

        Returns:
            Whether the Pod is alive
        """
        try:
            client = await self._get_client()
            response = await client.get(
                f"http://{pod_ip}:{port}/health",
                timeout=5.0
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Pod health check failed: {pod_ip}:{port} - {e}")
            return False


# Singleton instance
_proxy: Optional[InternalProxy] = None


def get_internal_proxy() -> InternalProxy:
    """Return Internal Proxy singleton instance"""
    global _proxy
    if _proxy is None:
        _proxy = InternalProxy()
    return _proxy
