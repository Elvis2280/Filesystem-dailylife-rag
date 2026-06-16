from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import redis

from app.core.config import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

logger = logging.getLogger(__name__)

# Sync Client (Workers, Celery, sync code)
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=0,
    decode_responses=True,
)

# Async Client (Async functions and endpoints)
_async_redis_client: AsyncRedis | None = None


async def get_async_redis_client() -> AsyncRedis:
    global _async_redis_client
    if _async_redis_client is None:
        from redis.asyncio import Redis as AsyncRedis

        _async_redis_client = AsyncRedis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=0,
            decode_responses=True,
        )

        try:
            await _async_redis_client.ping()
        except Exception:
            _async_redis_client = None
            raise
    return _async_redis_client


async def close_async_redis_client() -> None:
    """Close the async Redis client connection pool."""
    global _async_redis_client
    if _async_redis_client is not None:
        await _async_redis_client.aclose()
        _async_redis_client = None
