"""WorkerModule -> Writer integration.

This package provides a command-plane client for invoking Writer over A2A.
Writer is expected to emit `message_generated` / `message_sent` events to Redis
with the same `correlation_id`.
"""

from .client import WriterA2AClient, WriterClientError

__all__ = [
	"WriterA2AClient",
	"WriterClientError",
]
