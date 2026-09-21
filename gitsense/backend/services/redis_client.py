import json
import logging
import redis.asyncio as aioredis
from backend.config import settings

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis | None:
    """
    Returns a shared async Redis client instance.
    Lazy initializes connection pool on first access.
    """
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
            )
        except Exception as e:
            logger.warning(f"Failed to initialize Redis client ({e}). Redis caching disabled.")
            return None
    return _redis_client


async def close_redis_client() -> None:
    """Closes the Redis client connection pool on app shutdown."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception as e:
            logger.debug(f"Error closing Redis client: {e}")
        finally:
            _redis_client = None


async def redis_get_json(key: str) -> dict | list | None:
    """GET key from Redis and deserialize JSON. Returns None on miss or failure."""
    client = get_redis_client()
    if client is None:
        return None
    try:
        val = await client.get(key)
        if val:
            return json.loads(val)
    except Exception as e:
        logger.warning(f"Redis get_json failed for key '{key}': {e}")
    return None


async def redis_set_json(key: str, data: dict | list, ttl: int | None = None) -> None:
    """Serialize data to JSON and SET in Redis with optional TTL in seconds."""
    client = get_redis_client()
    if client is None:
        return
    try:
        payload = json.dumps(data)
        if ttl:
            await client.set(key, payload, ex=ttl)
        else:
            await client.set(key, payload)
    except Exception as e:
        logger.warning(f"Redis set_json failed for key '{key}': {e}")
