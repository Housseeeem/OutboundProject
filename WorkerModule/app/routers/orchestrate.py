import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.adapters.graph import get_db_pool
from app.event_emitter import publish_event
from app.modules.detective import DetectiveA2AClient, DetectiveClientError
from app.modules.worker.storage import save_event
from app.modules.writer import WriterA2AClient, WriterClientError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/orchestrate", tags=["orchestrate"])


class OrchestrateGenerateRequest(BaseModel):
    lead: Dict[str, Any] = Field(description="Canonical lead_ingested payload")
    writer_request: Dict[str, Any] = Field(
        description="Writer GenerateRequest-compatible payload (will be enriched with detective_context)"
    )
    correlation_id: Optional[str] = None


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def orchestrate_generate(payload: OrchestrateGenerateRequest, request: Request, db_pool=Depends(get_db_pool)):
    """Worker control-plane entrypoint.

    - Emits lead_ingested (event plane + DB)
    - Calls Detective via A2A (command plane)
    - Calls Writer via A2A (command plane)

    This endpoint is intentionally minimal and synchronous: it returns quickly with
    correlation_id and the immediate A2A artifacts, while the full trace is available
    via /v1/events?correlation_id=... as modules emit events.
    """

    correlation_id = payload.correlation_id or str(uuid.uuid4())

    lead_envelope = {
        "event_id": str(uuid.uuid4()),
        "correlation_id": correlation_id,
        "module": "worker",
        "event_type": "lead_ingested",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload.lead,
        "metadata": {"source": "worker_api"},
    }

    # Persist + publish lead_ingested
    try:
        await save_event(db_pool, lead_envelope)
    except Exception as exc:
        logger.error("Failed to persist lead_ingested: %s", exc)
        raise HTTPException(status_code=503, detail="Failed to persist lead_ingested") from exc

    try:
        await publish_event("lead_ingested", lead_envelope)
    except Exception as exc:
        logger.warning("Failed to publish lead_ingested to Redis: %s", exc)

    # Command plane: Detective
    try:
        detective_client = DetectiveA2AClient()
        scored = await detective_client.score_lead(envelope=lead_envelope)
    except DetectiveClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Detective call failed") from exc

    # Command plane: Writer
    try:
        writer_client = WriterA2AClient()
        writer_req = dict(payload.writer_request)
        writer_req["detective_context"] = {
            **(writer_req.get("detective_context") or {}),
            **(scored or {}),
            "correlation_id": correlation_id,
        }
        writer_result = await writer_client.generate_message(generate_request=writer_req)
    except WriterClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Writer call failed") from exc

    return {
        "accepted": True,
        "correlation_id": correlation_id,
        "lead_ingested_event_id": lead_envelope["event_id"],
        "detective": scored,
        "writer": writer_result,
    }
