import json
import logging
from typing import Any, Dict

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)


async def publish_event(channel: str, envelope: Dict[str, Any]) -> bool:
    """Publish a canonical EventEnvelope to Redis pub/sub.

    Returns True when published, False when Redis is not configured.
    Raises on unexpected Redis errors.
    """

    if not settings.REDIS_URL:
        return False

    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        payload = json.dumps(envelope, default=str)
        await client.publish(channel, payload)
        return True
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
