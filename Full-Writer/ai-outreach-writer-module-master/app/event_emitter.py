"""
Event emitter for the Writer module.

Publishes message_generated and message_sent EventEnvelopes to Redis (primary)
with HTTP POST to Worker's /v1/events/ingest as fallback.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _build_envelope(
    event_type: str,
    correlation_id: str,
    payload: dict,
    metadata: Optional[dict] = None,
) -> Dict[str, Any]:
    """Build a canonical EventEnvelope."""
    return {
        "event_id": str(uuid.uuid4()),
        "correlation_id": correlation_id,
        "module": "writer",
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "metadata": metadata or {},
    }


class WriterEventEmitter:
    """Publishes Writer events to Redis pub/sub with HTTP fallback."""

    def __init__(self, redis_url: str = "", worker_url: str = ""):
        self._redis = None
        self._worker_url = worker_url or os.environ.get("WORKER_URL", "http://api:8000")

        try:
            import redis as sync_redis

            url = redis_url or os.environ.get("REDIS_URL", "")
            if url:
                self._redis = sync_redis.from_url(url)
        except Exception as exc:
            logger.warning("Redis unavailable (%s); will use HTTP fallback only.", exc)

    def emit_message_generated(
        self,
        correlation_id: str,
        message_body: str,
        subject: Optional[str],
        quality_score: int,
        channel: str = "",
        prospect_name: str = "",
        company_name: str = "",
    ) -> None:
        """Emit a message_generated event synchronously."""
        if not correlation_id:
            logger.debug("No correlation_id — skipping message_generated event")
            return

        envelope = _build_envelope(
            event_type="message_generated",
            correlation_id=correlation_id,
            payload={
                "body": message_body,
                "subject": subject,
                "quality_score": quality_score,
                "channel": channel,
                "prospect_name": prospect_name,
                "company_name": company_name,
            },
        )
        self._publish(envelope, channel="message_generated")

    def emit_message_sent(
        self,
        correlation_id: str,
        channel: str,
        recipient: str,
        send_result: Optional[dict] = None,
    ) -> None:
        """Emit a message_sent event synchronously."""
        if not correlation_id:
            logger.debug("No correlation_id — skipping message_sent event")
            return

        envelope = _build_envelope(
            event_type="message_sent",
            correlation_id=correlation_id,
            payload={
                "channel": channel,
                "recipient": recipient,
                "send_result": send_result or {},
            },
        )
        self._publish(envelope, channel="message_sent")

    def _publish(self, envelope: dict, channel: str) -> None:
        """Publish to Redis; fall back to HTTP POST on failure."""
        json_payload = json.dumps(envelope, default=str)

        # Try Redis first
        if self._redis is not None:
            try:
                self._redis.publish(channel, json_payload)
                logger.info(
                    "Published %s event_id=%s to Redis channel '%s'",
                    envelope["event_type"],
                    envelope["event_id"],
                    channel,
                )
                return
            except Exception as exc:
                logger.warning("Redis publish failed: %s — falling back to HTTP", exc)

        # HTTP fallback
        try:
            import httpx

            with httpx.Client(timeout=5.0) as client:
                response = client.post(
                    f"{self._worker_url}/v1/events/ingest",
                    json=envelope,
                )
                response.raise_for_status()
                logger.info(
                    "Published %s event_id=%s via HTTP to Worker",
                    envelope["event_type"],
                    envelope["event_id"],
                )
        except Exception as exc:
            logger.error(
                "Failed to publish %s event: %s",
                envelope["event_type"],
                exc,
            )


# Module-level singleton (lazy init)
_writer_emitter: Optional[WriterEventEmitter] = None


def get_writer_emitter() -> WriterEventEmitter:
    """Get or create the module-level WriterEventEmitter singleton."""
    global _writer_emitter
    if _writer_emitter is None:
        _writer_emitter = WriterEventEmitter()
    return _writer_emitter
