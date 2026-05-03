"""WorkerModule -> Detective integration.

This package provides a thin command-plane client for invoking Detective over A2A.
The event-plane (Redis pub/sub) is still the system of record for tracing; Detective
is expected to emit `lead_scored` events with the same `correlation_id`.
"""

from .client import DetectiveA2AClient, DetectiveClientError

__all__ = [
	"DetectiveA2AClient",
	"DetectiveClientError",
]
