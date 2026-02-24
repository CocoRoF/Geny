"""
Pod Information Manager

Module for automatically detecting Kubernetes Pod information
Used for session routing in multi-pod environments

Works automatically without environment variable settings:
- Pod Name: Automatically extracted from hostname
- Pod IP: Automatically detected from network interface
"""
import os
import socket
from logging import getLogger
from typing import Optional, List
from dataclasses import dataclass

logger = getLogger(__name__)


@dataclass
class PodInfo:
    """Pod information"""
    pod_name: str
    pod_ip: str
    pod_namespace: str
    node_name: str
    service_port: int

    def get_internal_url(self, path: str = "") -> str:
        """Generate internal communication URL"""
        return f"http://{self.pod_ip}:{self.service_port}{path}"

    def __str__(self) -> str:
        return f"Pod({self.pod_name}@{self.pod_ip}:{self.service_port})"


# Singleton instance
_pod_info: Optional[PodInfo] = None


def _get_all_local_ips() -> List[str]:
    """Get all local IP addresses"""
    ips = []
    try:
        # Get IPs from all network interfaces
        hostname = socket.gethostname()
        ips = socket.gethostbyname_ex(hostname)[2]
        # Exclude 127.0.0.1
        ips = [ip for ip in ips if not ip.startswith('127.')]
    except Exception:
        pass
    return ips


def _get_local_ip() -> str:
    """
    Automatically detect local IP address

    Tries multiple methods:
    1. Check default interface IP by external connection attempt
    2. IP lookup by hostname
    3. Find non-localhost IP from all interfaces
    """
    # Method 1: UDP socket external connection attempt (doesn't actually send packets)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        # Only check local IP without actual connection
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass

    # Method 2: IP lookup by hostname
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith('127.'):
            return ip
    except Exception:
        pass

    # Method 3: Find from all interfaces
    ips = _get_all_local_ips()
    if ips:
        return ips[0]

    # Last resort
    return "127.0.0.1"


def _get_pod_name() -> str:
    """
    Automatically detect Pod name

    In Kubernetes, hostname is the same as Pod name
    """
    # Environment variable takes priority (if set)
    if os.getenv('POD_NAME'):
        return os.getenv('POD_NAME')

    if os.getenv('HOSTNAME'):
        return os.getenv('HOSTNAME')

    # Use hostname (Pod name in Kubernetes)
    try:
        return socket.gethostname()
    except Exception:
        pass

    # Fallback
    import uuid
    return f"mcp-station-{uuid.uuid4().hex[:8]}"


def _get_namespace() -> str:
    """
    Automatically detect Kubernetes namespace

    Read from ServiceAccount mount path
    """
    # Environment variable takes priority
    if os.getenv('POD_NAMESPACE'):
        return os.getenv('POD_NAMESPACE')

    # Read from Kubernetes ServiceAccount mount
    namespace_file = '/var/run/secrets/kubernetes.io/serviceaccount/namespace'
    try:
        if os.path.exists(namespace_file):
            with open(namespace_file, 'r') as f:
                return f.read().strip()
    except Exception:
        pass

    return 'default'


def init_pod_info(
    pod_name: Optional[str] = None,
    pod_ip: Optional[str] = None,
    pod_namespace: Optional[str] = None,
    node_name: Optional[str] = None,
    service_port: Optional[int] = None
) -> PodInfo:
    """
    Auto-initialize Pod information

    Automatically detects without environment variable settings:
    - pod_name: hostname (Pod name in Kubernetes)
    - pod_ip: Automatically detected from network interface
    - pod_namespace: Read from ServiceAccount mount

    Args:
        pod_name: Pod name (auto-detect if not specified)
        pod_ip: Pod IP (auto-detect if not specified)
        pod_namespace: Namespace (auto-detect if not specified)
        node_name: Node name
        service_port: Service port (default: APP_PORT or 8000)

    Returns:
        PodInfo instance
    """
    global _pod_info

    detected_name = pod_name or _get_pod_name()
    detected_ip = pod_ip or os.getenv('POD_IP') or _get_local_ip()
    detected_namespace = pod_namespace or _get_namespace()
    detected_port = service_port or int(os.getenv('APP_PORT', '8000'))

    _pod_info = PodInfo(
        pod_name=detected_name,
        pod_ip=detected_ip,
        pod_namespace=detected_namespace,
        node_name=node_name or os.getenv('NODE_NAME', 'unknown'),
        service_port=detected_port
    )

    logger.info(f"✅ Pod info auto-detected: {_pod_info}")
    logger.info(f"   - Name: {detected_name} (auto-detected)")
    logger.info(f"   - IP: {detected_ip} (auto-detected)")
    logger.info(f"   - Namespace: {detected_namespace}")
    logger.info(f"   - Port: {detected_port}")

    return _pod_info


def get_pod_info() -> PodInfo:
    """
    Get Pod information (singleton)

    Auto-initializes if not initialized
    """
    global _pod_info

    if _pod_info is None:
        _pod_info = init_pod_info()

    return _pod_info


def is_same_pod(target_pod_name: str) -> bool:
    """Check if target is the same Pod as current"""
    pod_info = get_pod_info()
    return pod_info.pod_name == target_pod_name


def is_same_pod_ip(target_pod_ip: str) -> bool:
    """Check if target Pod IP is the same as current"""
    pod_info = get_pod_info()
    return pod_info.pod_ip == target_pod_ip
