import asyncio
import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
import uuid
from datetime import datetime, timezone
import logging

from ..modules.worker.storage import (
    save_event,
    list_events,
    add_outcome,
    find_near_duplicate_event,
    event_exists,
)
from ..modules.worker.schemas import validate_event_payload
from ..adapters.graph import get_db_pool
from ..config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

_INGEST_CONCURRENCY = asyncio.Semaphore(settings.INGEST_MAX_INFLIGHT)
_ALLOWED_MODULES = {"inject", "detective", "writer", "worker"}


def _error_detail(code: str, message: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    detail: Dict[str, Any] = {"code": code, "message": message}
    if extra:
        detail.update(extra)
    return detail

class EventEnvelope(BaseModel):
    event_id: uuid.UUID
    correlation_id: uuid.UUID
    module: str
    event_type: str
    timestamp: datetime
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventListResponse(BaseModel):
    items: List[Dict[str, Any]]
    next_cursor: Optional[str] = None


class OutcomeLink(BaseModel):
    """Request model for linking an outcome to a decision/action event."""
    outcome_id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4)
    correlation_id: uuid.UUID
    linked_event_id: uuid.UUID
    outcome_type: str  # e.g., "reply", "conversion", "ignore"
    value: Dict[str, Any] = Field(default_factory=dict)
    timestamp: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))


class OutcomeResponse(BaseModel):
    """Response model for outcome linking."""
    accepted: bool
    outcome_id: str
    correlation_id: str
    linked_event_id: str
    linked_at: str
    idempotent: bool = False


class IngestResponse(BaseModel):
    accepted: bool
    event_id: str
    correlation_id: str
    ingested_at: str
    idempotent: bool
    duplicate_window: bool
    duplicate_of: Optional[str] = None
    schema_warnings: Optional[List[str]] = None

@router.post("/v1/events/ingest", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(event: EventEnvelope, db_pool=Depends(get_db_pool)):
    """
    Ingests a single canonical event and stores it.
    """
    if event.module not in _ALLOWED_MODULES:
        raise HTTPException(
            status_code=400,
            detail=_error_detail(
                "INVALID_MODULE",
                "module must be one of inject|detective|writer|worker",
                {"module": event.module},
            ),
        )

    validation = validate_event_payload(
        event_type=event.event_type,
        payload=event.payload,
        allow_unknown_event_type=settings.EVENT_SCHEMA_ALLOW_UNKNOWN_TYPES,
    )

    mode = (settings.EVENT_SCHEMA_VALIDATION_MODE or "warn").strip().lower()
    if mode not in {"warn", "enforce"}:
        mode = "warn"

    if not validation["is_valid"] and mode == "enforce":
        raise HTTPException(
            status_code=400,
            detail=_error_detail(
                "INGEST_SCHEMA_VALIDATION_FAILED",
                "payload does not conform to event schema",
                {
                    "event_type": event.event_type,
                    "errors": validation["errors"],
                    "warnings": validation["warnings"],
                },
            ),
        )

    schema_warnings: List[str] = []
    if validation["warnings"]:
        schema_warnings.extend(validation["warnings"])
    if validation["errors"] and mode == "warn":
        schema_warnings.extend(validation["errors"])

    if _INGEST_CONCURRENCY.locked():
        raise HTTPException(
            status_code=429,
            detail=_error_detail(
                "INGEST_BACKPRESSURE",
                "ingest capacity is currently saturated; retry later",
                {"retry_after_seconds": settings.INGEST_BACKPRESSURE_RETRY_AFTER_SECONDS},
            ),
            headers={"Retry-After": str(settings.INGEST_BACKPRESSURE_RETRY_AFTER_SECONDS)},
        )

    try:
        async with _INGEST_CONCURRENCY:
            near_dup = await asyncio.wait_for(
                find_near_duplicate_event(
                    db_pool,
                    correlation_id=str(event.correlation_id),
                    event_type=event.event_type,
                    timestamp=event.timestamp,
                    window_seconds=settings.INGEST_DUPLICATE_WINDOW_SECONDS,
                ),
                timeout=settings.INGEST_DB_TIMEOUT_SECONDS,
            )

            if near_dup and str(near_dup.get("event_id")) != str(event.event_id):
                return {
                    "accepted": True,
                    "event_id": str(event.event_id),
                    "correlation_id": str(event.correlation_id),
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                    "idempotent": True,
                    "duplicate_window": True,
                    "duplicate_of": str(near_dup.get("event_id")),
                    "schema_warnings": schema_warnings or None,
                }

            inserted = await asyncio.wait_for(
                save_event(db_pool, event.model_dump()),
                timeout=settings.INGEST_DB_TIMEOUT_SECONDS,
            )

        return {
            "accepted": True,
            "event_id": str(event.event_id),
            "correlation_id": str(event.correlation_id),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "idempotent": not inserted,
            "duplicate_window": False,
            "schema_warnings": schema_warnings or None,
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=_error_detail("INGEST_VALIDATION_FAILED", str(e)),
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=503,
            detail=_error_detail(
                "INGEST_DEPENDENCY_TIMEOUT",
                "database operation timed out during ingestion",
                {"retry_after_seconds": settings.INGEST_BACKPRESSURE_RETRY_AFTER_SECONDS},
            ),
            headers={"Retry-After": str(settings.INGEST_BACKPRESSURE_RETRY_AFTER_SECONDS)},
        )
    except asyncpg.PostgresConnectionError:
        raise HTTPException(
            status_code=503,
            detail=_error_detail(
                "INGEST_DEPENDENCY_UNAVAILABLE",
                "database connection is unavailable",
                {"retry_after_seconds": settings.INGEST_BACKPRESSURE_RETRY_AFTER_SECONDS},
            ),
            headers={"Retry-After": str(settings.INGEST_BACKPRESSURE_RETRY_AFTER_SECONDS)},
        )
    except asyncpg.PostgresError:
        raise HTTPException(
            status_code=503,
            detail=_error_detail(
                "INGEST_DEPENDENCY_ERROR",
                "database dependency error during ingestion",
                {"retry_after_seconds": settings.INGEST_BACKPRESSURE_RETRY_AFTER_SECONDS},
            ),
            headers={"Retry-After": str(settings.INGEST_BACKPRESSURE_RETRY_AFTER_SECONDS)},
        )
    except Exception as e:
        logger.error(f"Failed to ingest event {event.event_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=_error_detail("INGEST_INTERNAL_ERROR", "Internal Server Error"),
        )


@router.get("/v1/events", response_model=EventListResponse)
async def get_events(
    correlation_id: Optional[str] = None,
    module: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
    db_pool=Depends(get_db_pool),
):
    """Retrieves events with optional filters and deterministic ordering."""
    try:
        items = await list_events(
            db_pool,
            correlation_id=correlation_id,
            module=module,
            event_type=event_type,
            limit=limit,
        )
        return {"items": items, "next_cursor": None}
    except Exception as e:
        logger.error(
            "Failed to list events correlation_id=%s module=%s event_type=%s: %s",
            correlation_id,
            module,
            event_type,
            e,
        )
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/v1/outcomes/link", response_model=OutcomeResponse, status_code=status.HTTP_202_ACCEPTED)
async def link_outcome(outcome: OutcomeLink, db_pool=Depends(get_db_pool)):
    """
    Links an outcome (reply, conversion, etc.) to a decision/action event.
    Validates referential integrity and ensures idempotency.
    """
    try:
        outcome_id = str(outcome.outcome_id)
        linked_event_id = str(outcome.linked_event_id)
        linked_exists = await event_exists(db_pool, linked_event_id)

        if settings.OUTCOME_LINK_REQUIRES_EVENT and not linked_exists:
            raise HTTPException(
                status_code=400,
                detail=_error_detail(
                    "OUTCOME_LINKED_EVENT_NOT_FOUND",
                    "linked_event_id does not exist",
                    {"linked_event_id": linked_event_id},
                ),
            )

        inserted = await add_outcome(
            db_pool,
            outcome_id=outcome_id,
            correlation_id=str(outcome.correlation_id),
            linked_event_id=linked_event_id,
            outcome_type=outcome.outcome_type,
            value=outcome.value,
            timestamp=outcome.timestamp.isoformat(),
            linked_event_exists=linked_exists,
        )
        return {
            "accepted": True,
            "outcome_id": outcome_id,
            "correlation_id": str(outcome.correlation_id),
            "linked_event_id": linked_event_id,
            "linked_at": datetime.now(timezone.utc).isoformat(),
            "idempotent": not inserted,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to link outcome: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
