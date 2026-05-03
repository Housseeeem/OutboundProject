import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

from ..modules.worker.storage import save_event
from ..adapters.graph import get_db_pool
from ..event_emitter import publish_event

router = APIRouter()
logger = logging.getLogger(__name__)

class FeedbackRequest(BaseModel):
    correlation_id: str
    target_module: str  # e.g., 'writer'
    feedback_type: str  # e.g., 'thumbs_down', 'rewrite_required'
    details: Dict[str, Any] = Field(default_factory=dict)
    target_event_id: Optional[str] = None
    decision: Optional[str] = None
    rating: Optional[float] = None
    suggested_changes: Optional[str] = None
    reviewer: Optional[str] = None
    source: Optional[str] = "human_in_the_loop"

@router.post("/v1/feedback", status_code=status.HTTP_202_ACCEPTED)
async def submit_feedback(request: FeedbackRequest, db_pool=Depends(get_db_pool)):
    """Logs human or system feedback as a canonical event."""
    try:
        event = {
            "event_id": str(uuid.uuid4()),
            "correlation_id": request.correlation_id,
            "module": "worker",
            "event_type": "feedback_submitted",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "target_module": request.target_module,
                "feedback_type": request.feedback_type,
                "details": request.details,
                "target_event_id": request.target_event_id,
                "decision": request.decision,
                "rating": request.rating,
                "suggested_changes": request.suggested_changes,
                "reviewer": request.reviewer,
            },
            "metadata": {
                "source": request.source or "human_in_the_loop",
            }
        }

        await save_event(db_pool, event)
        try:
            await publish_event("feedback_submitted", event)
        except Exception as exc:
            logger.warning("Failed to publish feedback_submitted to Redis: %s", exc)
        return {"accepted": True, "event_id": event["event_id"]}

    except Exception as e:
        logger.error(f"Failed to save feedback event: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
