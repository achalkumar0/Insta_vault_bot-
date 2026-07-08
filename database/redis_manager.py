"""
Redis Manager
~~~~~~~~~~~~~
Handles Redis connection pooling, lifecycle, and acts as the singleton provider
for the Redis instance used by the bot.
"""
import logging
import json
import asyncio
from datetime import datetime
from typing import Optional, Any

from redis.asyncio import Redis

from config import REDIS_URL

logger = logging.getLogger(__name__)

# Global reference to the Redis connection pool/client
_redis_client: Optional[Redis] = None


async def init_redis() -> Optional[Redis]:
    """
    Initializes the Redis connection pool.
    """
    global _redis_client

    if _redis_client is not None:
        logger.warning("Redis is already initialized.")
        return _redis_client

    logger.info("Initializing Redis connection pool...")
    try:
        # Use a strict connection pool with robust timeouts
        # decode_responses=True ensures we get str instead of bytes
        _redis_client = Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            max_connections=10,
        )
        
        # Ping the server to verify the connection
        await _redis_client.ping()
        logger.info("✅ Redis connection established successfully.")
        return _redis_client
    except Exception as e:
        logger.critical("❌ Failed to connect to Redis: %s", e)
        _redis_client = None
        raise e


def get_redis() -> Redis:
    """
    Returns the initialized Redis client.
    Raises RuntimeError if accessed before initialization or if REDIS_URL wasn't provided.
    """
    if _redis_client is None:
        raise RuntimeError("Redis client is not initialized. Call init_redis() first.")
    return _redis_client


async def close_redis() -> None:
    """
    Gracefully closes the Redis connection pool.
    """
    global _redis_client
    if _redis_client is not None:
        logger.info("Closing Redis connection pool...")
        try:
            await _redis_client.aclose()
            logger.info("✅ Redis connection closed cleanly.")
        except AttributeError:
            # Fallback for older redis-py versions
            await _redis_client.close()
            logger.info("✅ Redis connection closed cleanly.")
        except Exception as e:
            logger.error("Error while closing Redis connection: %s", e)
        finally:
            _redis_client = None


# ===========================================================================
# CACHING LAYER (FAIL-SAFE)
# ===========================================================================

class _DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder to safely serialize datetime objects to ISO strings."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


async def cache_user_data(user_id: int | str, data: dict[str, Any], ttl_seconds: int = 86400) -> None:
    """Safely cache user profile data. Defaults to 24 hours (86400s). Silently fails and invalidates on error."""
    try:
        client = get_redis()
        json_data = json.dumps(data, cls=_DateTimeEncoder)
        await client.setex(f"user:{user_id}", ttl_seconds, json_data)
        logger.info("✅ Cached data for user %s", user_id)
    except Exception as e:
        logger.error("Failed to cache user data for %s: %s", user_id, e)
        # Attempt fail-safe invalidation to prevent stale data
        await invalidate_user_cache(user_id)


async def get_cached_user_data(user_id: int | str) -> dict[str, Any] | None:
    """Retrieve user data from cache. Returns None on miss or error."""
    try:
        client = get_redis()
        json_data = await client.get(f"user:{user_id}")
        if json_data:
            return json.loads(json_data)
        return None
    except Exception as e:
        logger.error("Failed to fetch cached user data for %s: %s", user_id, e)
        return None


async def invalidate_user_cache(user_id: int | str) -> None:
    """Delete a user's cache key to force a fresh read from DB."""
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            client = get_redis()
            await client.delete(f"user:{user_id}")
            logger.info("🗑️ Invalidated cache for user %s", user_id)
            return
        except Exception as e:
            if attempt < max_attempts:
                logger.warning("Failed to invalidate cache for %s on attempt %d: %s. Retrying...", user_id, attempt, e)
                await asyncio.sleep(0.15)
            else:
                logger.error("Failed to invalidate cache for %s after %d attempts: %s", user_id, max_attempts, e)
