"""
Redis Client for Claude Control

Client for managing Claude sessions in Redis
In multi-pod environments, Redis acts as the source of truth
"""
import os
import json
from logging import getLogger
from typing import Dict, Any, Optional, List
from datetime import datetime

logger = getLogger(__name__)

# Check if Redis connection is available
import redis
REDIS_AVAILABLE = True

class RedisClient:
    """
    Redis client for Claude session management

    Implemented as singleton pattern - only one instance used across the application
    """

    _instance: Optional['RedisClient'] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        db: Optional[int] = None,
        password: Optional[str] = None,
        key_prefix: str = "claude-control"
    ):
        # Skip if already initialized (singleton)
        if RedisClient._initialized:
            return

        if not REDIS_AVAILABLE:
            logger.error("Cannot initialize - Redis package not installed")
            self._connection_available = False
            RedisClient._initialized = True
            return

        # Read Redis connection info from environment variables
        self._host = host or os.getenv('REDIS_HOST', 'redis')
        self._port = port or int(os.getenv('REDIS_PORT', '6379'))
        self._db = db or int(os.getenv('REDIS_DB', '0'))
        self._password = password or os.getenv('REDIS_PASSWORD')

        # Connection timeout settings
        self._socket_timeout = float(os.getenv('REDIS_SOCKET_TIMEOUT', '5'))
        self._socket_connect_timeout = float(os.getenv('REDIS_CONNECT_TIMEOUT', '3'))

        # Key prefix (multi-tenant support)
        self._key_prefix = key_prefix

        # Connection state
        self._connection_available = False
        self._redis_client: Optional['redis.Redis'] = None

        # Attempt Redis connection
        self._connect()

        RedisClient._initialized = True

    def _connect(self) -> bool:
        """Connect to Redis server"""
        try:
            self._redis_client = redis.Redis(
                host=self._host,
                port=self._port,
                db=self._db,
                password=self._password,
                decode_responses=True,
                socket_timeout=self._socket_timeout,
                socket_connect_timeout=self._socket_connect_timeout
            )

            # Test connection
            self._redis_client.ping()
            self._connection_available = True
            logger.info(f"✅ Redis connected: {self._host}:{self._port}")
            return True

        except redis.exceptions.ConnectionError as e:
            logger.warning(f"⚠️  Redis connection failed: {self._host}:{self._port}")
            logger.warning(f"   Reason: {e}")
            logger.warning(f"   💡 Check if Redis server is running")
            self._connection_available = False
            return False

        except redis.exceptions.TimeoutError as e:
            logger.warning(f"⚠️  Redis connection timeout: {self._host}:{self._port}")
            logger.warning(f"   💡 Check network connection")
            self._connection_available = False
            return False

        except Exception as e:
            logger.warning(f"⚠️  Redis initialization error: {e}")
            self._connection_available = False
            return False

    @classmethod
    def get_instance(cls) -> 'RedisClient':
        """Return singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset instance (for testing)"""
        cls._instance = None
        cls._initialized = False

    # ========== Connection Management ==========

    @property
    def is_connected(self) -> bool:
        """Check Redis connection status"""
        return self._connection_available

    def health_check(self) -> bool:
        """Check Redis connection health"""
        if not self._connection_available or not self._redis_client:
            return False
        try:
            return self._redis_client.ping()
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            self._connection_available = False
            return False

    def reconnect(self) -> bool:
        """Attempt Redis reconnection"""
        logger.info("Attempting Redis reconnection...")
        return self._connect()

    # ========== Key Management ==========

    def _make_key(self, *parts: str) -> str:
        """Generate key (with prefix)"""
        return f"{self._key_prefix}:{':'.join(parts)}"

    # ========== Session Management ==========

    def save_session(self, session_id: str, session_data: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """
        Save session information

        Args:
            session_id: Session ID
            session_data: Session data (dict)
            ttl: TTL (seconds), None for permanent storage

        Returns:
            Success status
        """
        if not self._connection_available:
            # Silent skip - caller should check is_connected before calling
            return False

        try:
            key = self._make_key("session", session_id)

            # Convert datetime objects to ISO format strings
            data_to_save = self._serialize_session_data(session_data)

            if ttl:
                self._redis_client.setex(key, ttl, json.dumps(data_to_save))
            else:
                self._redis_client.set(key, json.dumps(data_to_save))

            # Also add to session list
            sessions_set_key = self._make_key("sessions")
            self._redis_client.sadd(sessions_set_key, session_id)

            logger.debug(f"Session saved: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Session save failed: {session_id} - {e}")
            return False

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve session information

        Args:
            session_id: Session ID

        Returns:
            Session data or None
        """
        if not self._connection_available:
            return None

        try:
            key = self._make_key("session", session_id)
            data = self._redis_client.get(key)

            if data:
                session_data = json.loads(data)
                return self._deserialize_session_data(session_data)
            return None

        except Exception as e:
            logger.error(f"Session retrieval failed: {session_id} - {e}")
            return None

    def delete_session(self, session_id: str) -> bool:
        """
        Delete session

        Args:
            session_id: Session ID

        Returns:
            Success status
        """
        if not self._connection_available:
            return False

        try:
            key = self._make_key("session", session_id)
            self._redis_client.delete(key)

            # Also remove from session list
            sessions_set_key = self._make_key("sessions")
            self._redis_client.srem(sessions_set_key, session_id)

            logger.debug(f"Session deleted: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Session deletion failed: {session_id} - {e}")
            return False

    def list_sessions(self) -> List[str]:
        """
        Retrieve all session ID list

        Returns:
            List of session IDs
        """
        if not self._connection_available:
            return []

        try:
            sessions_set_key = self._make_key("sessions")
            return list(self._redis_client.smembers(sessions_set_key))

        except Exception as e:
            logger.error(f"Session list retrieval failed: {e}")
            return []

    def get_all_sessions(self) -> List[Dict[str, Any]]:
        """
        Retrieve all session data

        Returns:
            List of session data
        """
        if not self._connection_available:
            return []

        try:
            session_ids = self.list_sessions()
            sessions = []

            for session_id in session_ids:
                session_data = self.get_session(session_id)
                if session_data:
                    sessions.append(session_data)

            return sessions

        except Exception as e:
            logger.error(f"All sessions retrieval failed: {e}")
            return []

    def session_exists(self, session_id: str) -> bool:
        """
        Check if session exists

        Args:
            session_id: Session ID

        Returns:
            Existence status
        """
        if not self._connection_available:
            return False

        try:
            key = self._make_key("session", session_id)
            return self._redis_client.exists(key) > 0

        except Exception as e:
            logger.error(f"Session existence check failed: {session_id} - {e}")
            return False

    def update_session_field(self, session_id: str, field: str, value: Any) -> bool:
        """
        Update specific field of a session

        Args:
            session_id: Session ID
            field: Field name
            value: New value

        Returns:
            Success status
        """
        if not self._connection_available:
            return False

        try:
            session_data = self.get_session(session_id)
            if not session_data:
                logger.warning(f"Session not found for update: {session_id}")
                return False

            session_data[field] = value
            return self.save_session(session_id, session_data)

        except Exception as e:
            logger.error(f"Session field update failed: {session_id}.{field} - {e}")
            return False

    # ========== Utilities ==========

    def _serialize_session_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Serialize session data (datetime -> ISO string)"""
        result = {}
        for key, value in data.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, dict):
                result[key] = self._serialize_session_data(value)
            else:
                result[key] = value
        return result

    def _deserialize_session_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Deserialize session data (ISO string -> datetime)"""
        result = {}
        datetime_fields = ['created_at', 'updated_at', 'started_at', 'stopped_at']

        for key, value in data.items():
            if key in datetime_fields and isinstance(value, str):
                try:
                    result[key] = datetime.fromisoformat(value)
                except ValueError:
                    result[key] = value
            elif isinstance(value, dict):
                result[key] = self._deserialize_session_data(value)
            else:
                result[key] = value
        return result

    def clear_all_sessions(self) -> bool:
        """
        Delete all sessions (Caution: dangerous operation)

        Returns:
            Success status
        """
        if not self._connection_available:
            return False

        try:
            session_ids = self.list_sessions()
            for session_id in session_ids:
                self.delete_session(session_id)

            logger.info(f"All sessions deleted: {len(session_ids)} sessions")
            return True

        except Exception as e:
            logger.error(f"All sessions deletion failed: {e}")
            return False

    # ========== General Key-Value Storage ==========

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        Save general key-value pair

        Args:
            key: Key (prefix automatically added)
            value: Value (automatically JSON serialized)
            ttl: TTL (seconds)

        Returns:
            Success status
        """
        if not self._connection_available:
            return False

        try:
            full_key = self._make_key(key)
            data = json.dumps(value) if not isinstance(value, str) else value

            if ttl:
                self._redis_client.setex(full_key, ttl, data)
            else:
                self._redis_client.set(full_key, data)

            return True

        except Exception as e:
            logger.error(f"Redis set failed: {key} - {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve general key-value pair

        Args:
            key: Key (prefix automatically added)
            default: Default value

        Returns:
            Value or default value
        """
        if not self._connection_available:
            return default

        try:
            full_key = self._make_key(key)
            data = self._redis_client.get(full_key)

            if data is None:
                return default

            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return data

        except Exception as e:
            logger.error(f"Redis get failed: {key} - {e}")
            return default

    def delete(self, key: str) -> bool:
        """
        Delete general key

        Args:
            key: Key (prefix automatically added)

        Returns:
            Success status
        """
        if not self._connection_available:
            return False

        try:
            full_key = self._make_key(key)
            self._redis_client.delete(full_key)
            return True

        except Exception as e:
            logger.error(f"Redis delete failed: {key} - {e}")
            return False

    def exists(self, key: str) -> bool:
        """
        Check if key exists

        Args:
            key: Key (prefix automatically added)

        Returns:
            Existence status
        """
        if not self._connection_available:
            return False

        try:
            full_key = self._make_key(key)
            return self._redis_client.exists(full_key) > 0

        except Exception as e:
            logger.error(f"Redis exists failed: {key} - {e}")
            return False

    # ========== Statistics ==========

    def get_stats(self) -> Dict[str, Any]:
        """
        Return Redis status and session statistics

        Returns:
            Statistics information
        """
        stats = {
            "connected": self._connection_available,
            "host": self._host,
            "port": self._port,
            "db": self._db,
            "key_prefix": self._key_prefix,
            "session_count": 0,
            "redis_info": None
        }

        if not self._connection_available:
            return stats

        try:
            stats["session_count"] = len(self.list_sessions())

            # Redis server info
            info = self._redis_client.info()
            stats["redis_info"] = {
                "version": info.get("redis_version"),
                "connected_clients": info.get("connected_clients"),
                "used_memory_human": info.get("used_memory_human"),
                "uptime_in_days": info.get("uptime_in_days")
            }

        except Exception as e:
            logger.error(f"Redis stats retrieval failed: {e}")

        return stats


# Global function for convenience
def get_redis_client() -> Optional[RedisClient]:
    """Return Redis client singleton instance (None if USE_REDIS=false)"""
    use_redis = os.getenv('USE_REDIS', 'false').lower() == 'true'
    if not use_redis:
        return None
    return RedisClient.get_instance()
