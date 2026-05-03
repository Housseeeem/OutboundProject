import asyncio
import json
import logging
import redis.asyncio as aioredis
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)

async def start_writer_subscriber():
    """
    Connect to Redis, subscribe to 'config_updated', and hot-reload settings.
    """
    client: Optional[aioredis.Redis] = None
    pubsub: Optional[aioredis.client.PubSub] = None
    
    if not settings.REDIS_URL:
        logger.warning("No REDIS_URL configured for Writer; skipping config subscriber.")
        return

    try:
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe("config_updated")
        logger.info("Writer config subscriber started — listening on 'config_updated'")

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            raw = message.get("data", "")
            try:
                parsed_json = json.loads(raw)
                settings.update_from_worker(parsed_json)
                logger.info("Writer hot-reloaded configuration from Worker")
            except Exception as exc:
                logger.warning(f"Writer subscriber error: {exc}")

    except asyncio.CancelledError:
        logger.info("Writer subscriber shutting down")
    except Exception as exc:
        logger.error(f"Writer subscriber unexpected error: {exc}")
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe("config_updated")
                await pubsub.close()
            except Exception:
                pass
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass
