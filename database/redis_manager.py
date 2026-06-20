"""
Redis Manager
~~~~~~~~~~~~~
Handles Redis connection pooling, lifecycle, and acts as the singleton provider
for the Redis instance used by the bot.
"""
import logging
from typing import Optional

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
