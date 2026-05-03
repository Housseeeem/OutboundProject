"""
Redis pub/sub subscriber for WorkerModule.

Subscribes to all event channels and persists each valid
EventEnvelope directly via save_event() — no HTTP round-trip.
"""

import asyncio
import json
import logging
from typing import Any, Dict

import redis.asyncio as aioredis

from .config import settings
from .modules.worker.storage import save_event

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = {
    "event_id",
    "correlation_id",
    "module",
    "event_type",
    "timestamp",
    "payload",
    "metadata",
}

CHANNELS = [
    "lead_ingested",
    "lead_scored",
    "message_generated",
    "message_sent",
    "feedback_submitted",
    "reply_received",
    "conversion",
]


def _validate_envelope(data: Dict[str, Any]) -> bool:
    """Return True if all required EventEnvelope fields are present."""
    return _REQUIRED_FIELDS.issubset(data.keys())


async def start_redis_subscriber(db_pool) -> None:
    """
    Connect to Redis, subscribe to 'lead_ingested', and persist each valid
    envelope via save_event().

    Runs until cancelled (asyncio.CancelledError), which triggers a clean
    unsubscribe and connection close.
    """
    client: aioredis.Redis | None = None
    pubsub: aioredis.client.PubSub | None = None

    try:
        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(*CHANNELS)
        logger.info("Redis subscriber started — listening on channels: %s", CHANNELS)

        async for message in pubsub.listen():
            if message["type"] != "message":
                # Skip subscribe/unsubscribe confirmation messages
                continue

            raw = message.get("data", "")
            try:
                envelope = json.loads(raw)
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning(
                    "Skipping malformed JSON on channel '%s': %s — raw=%r",
                    message.get("channel", "unknown"),
                    exc,
                    raw,
                )
                continue

            if not isinstance(envelope, dict):
                logger.warning(
                    "Skipping non-dict message on channel '%s': type=%s",
                    message.get("channel", "unknown"),
                    type(envelope).__name__,
                )
                continue

            if not _validate_envelope(envelope):
                missing = _REQUIRED_FIELDS - envelope.keys()
                logger.warning(
                    "Skipping incomplete envelope on channel '%s': missing fields=%s",
                    message.get("channel", "unknown"),
                    missing,
                )
                continue

            try:
                await save_event(db_pool, envelope)
                logger.debug(
                    "Saved event event_id=%s correlation_id=%s",
                    envelope.get("event_id"),
                    envelope.get("correlation_id"),
                )
            except Exception as exc:
                logger.error(
                    "Failed to save event event_id=%s: %s",
                    envelope.get("event_id"),
                    exc,
                )
                # Continue the loop — do not crash on a single save failure

    except asyncio.CancelledError:
        logger.info("Redis subscriber shutting down gracefully")
        raise  # re-raise so the task is properly cancelled
    except Exception as exc:
        logger.error("Redis subscriber encountered an unexpected error: %s", exc)
        raise
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(*CHANNELS)
                await pubsub.close()
            except Exception:
                pass
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass
        logger.info("Redis subscriber connection closed")
