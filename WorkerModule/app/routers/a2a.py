import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from ..adapters.graph import get_db_pool
from ..modules.worker.storage import (
    save_event,
    get_events_by_correlation_id,
    get_events_for_metrics,
    get_outcome_statistics,
)
from ..modules.worker.optimization import build_dry_run_recommendations

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class DataPart(BaseModel):
    type: Literal["data"] = "data"
    data: Dict[str, Any]


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class A2AMessage(BaseModel):
    role: str = "user"
    parts: List[Union[DataPart, TextPart]]


class A2ATask(BaseModel):
    id: str
    message: A2AMessage
    model_config = ConfigDict(extra="allow")


class TaskStatus(BaseModel):
    state: Literal["submitted", "working", "completed", "failed"]
    message: Optional[str] = None


class ArtifactPart(BaseModel):
    type: str
    data: Any


class Artifact(BaseModel):
    parts: List[ArtifactPart]


class TaskResult(BaseModel):
    id: str
    status: TaskStatus
    artifacts: List[Artifact] = []


class TaskStatusUpdateEvent(BaseModel):
    id: str
    status: TaskStatus
    artifacts: List[Artifact] = []
    final: bool = False


# ---------------------------------------------------------------------------
# Worker AgentCard constant
# ---------------------------------------------------------------------------

WORKER_AGENT_CARD: Dict[str, Any] = {
    "name": "Worker Agent",
    "description": "Telemetry, traceability, outcome linking, and optimization engine for AgenticOutbound.",
    "url": "http://api:8000",
    "version": "1.0.0",
    "skills": [
        {
            "id": "ingest_event",
            "name": "Ingest Event",
            "description": "Persists an EventEnvelope to the telemetry store.",
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
        },
        {
            "id": "trace_correlation",
            "name": "Trace Correlation Timeline",
            "description": "Returns all events for a given correlation_id in chronological order.",
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
        },
        {
            "id": "run_optimization",
            "name": "Run Optimization Dry-Run",
            "description": "Computes optimization recommendations from telemetry without applying them.",
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
        },
    ],
    "authentication": {"schemes": ["ApiKey"]},
}

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()


@router.get("/.well-known/agent.json")
async def get_agent_card() -> JSONResponse:
    return JSONResponse(content=WORKER_AGENT_CARD)


# ---------------------------------------------------------------------------
# POST /tasks/send
# ---------------------------------------------------------------------------

_REQUIRED_ENVELOPE_FIELDS = [
    "event_id", "correlation_id", "module", "event_type",
    "timestamp", "payload", "metadata",
]


def _failed(task_id: str, message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=TaskResult(
            id=task_id,
            status=TaskStatus(state="failed", message=message),
            artifacts=[],
        ).model_dump(),
    )


async def _artifacts_ingest_event(task_id: str, data: Dict[str, Any], db_pool) -> List[Artifact]:
    """Run ingest_event skill and return artifacts. Raises ValueError on bad input, Exception on DB error."""
    envelope = data.get("envelope")
    if not isinstance(envelope, dict):
        raise ValueError("Missing or invalid 'envelope' in data")

    missing = [f for f in _REQUIRED_ENVELOPE_FIELDS if f not in envelope]
    if missing:
        raise ValueError(f"Envelope missing required fields: {', '.join(missing)}")

    await save_event(db_pool, envelope)
    return [Artifact(parts=[ArtifactPart(type="data", data={"ingested": True, "event_id": envelope.get("event_id")})])]


async def _artifacts_trace_correlation(task_id: str, data: Dict[str, Any], db_pool) -> List[Artifact]:
    """Run trace_correlation skill and return artifacts. Raises ValueError on bad input, Exception on DB error."""
    correlation_id = data.get("correlation_id")
    if not correlation_id:
        raise ValueError("Missing 'correlation_id' in data")

    events = await get_events_by_correlation_id(db_pool, str(correlation_id))
    return [Artifact(parts=[ArtifactPart(type="data", data={"events": events})])]


async def _artifacts_run_optimization(task_id: str, data: Dict[str, Any], db_pool) -> List[Artifact]:
    """Run run_optimization skill and return artifacts. Raises Exception on DB error."""
    max_change_pct: float = float(data.get("max_change_pct", 20.0))
    cooldown_hours: float = float(data.get("cooldown_hours", 24.0))

    event_counts = await get_events_for_metrics(db_pool)
    outcome_counts = await get_outcome_statistics(db_pool)
    recommendations = build_dry_run_recommendations(
        event_counts, outcome_counts, max_change_pct, cooldown_hours
    )
    return [Artifact(parts=[ArtifactPart(type="data", data={"recommendations": recommendations})])]


async def _handle_ingest_event(task: A2ATask, data: Dict[str, Any], db_pool) -> JSONResponse:
    try:
        artifacts = await _artifacts_ingest_event(task.id, data, db_pool)
    except ValueError as e:
        return _failed(task.id, str(e))
    except Exception as e:
        logger.error("ingest_event: DB error saving event: %s", e)
        return _failed(task.id, "Database error during event ingestion", status_code=500)

    return JSONResponse(
        content=TaskResult(
            id=task.id,
            status=TaskStatus(state="completed"),
            artifacts=artifacts,
        ).model_dump()
    )


async def _handle_trace_correlation(task: A2ATask, data: Dict[str, Any], db_pool) -> JSONResponse:
    try:
        artifacts = await _artifacts_trace_correlation(task.id, data, db_pool)
    except ValueError as e:
        return _failed(task.id, str(e))
    except Exception as e:
        logger.error("trace_correlation: DB error fetching events: %s", e)
        return _failed(task.id, "Database error during correlation trace", status_code=500)

    return JSONResponse(
        content=TaskResult(
            id=task.id,
            status=TaskStatus(state="completed"),
            artifacts=artifacts,
        ).model_dump()
    )


async def _handle_run_optimization(task: A2ATask, data: Dict[str, Any], db_pool) -> JSONResponse:
    try:
        artifacts = await _artifacts_run_optimization(task.id, data, db_pool)
    except Exception as e:
        logger.error("run_optimization: DB error fetching metrics: %s", e)
        return _failed(task.id, "Database error during optimization", status_code=500)

    return JSONResponse(
        content=TaskResult(
            id=task.id,
            status=TaskStatus(state="completed"),
            artifacts=artifacts,
        ).model_dump()
    )


@router.post("/tasks/send")
async def tasks_send(task: A2ATask, db_pool=Depends(get_db_pool)) -> JSONResponse:
    if not task.message.parts:
        return _failed(task.id, "message.parts must not be empty")

    first_part = task.message.parts[0]
    if not isinstance(first_part, DataPart):
        return _failed(task.id, "First part must be a DataPart")

    data = first_part.data
    skill = data.get("skill")

    if skill == "ingest_event":
        return await _handle_ingest_event(task, data, db_pool)
    elif skill == "trace_correlation":
        return await _handle_trace_correlation(task, data, db_pool)
    elif skill == "run_optimization":
        return await _handle_run_optimization(task, data, db_pool)
    else:
        return _failed(task.id, f"Unknown skill: '{skill}'")


# ---------------------------------------------------------------------------
# POST /tasks/sendSubscribe  (SSE streaming)
# ---------------------------------------------------------------------------

async def _sse_generator(task: A2ATask, db_pool) -> AsyncGenerator[str, None]:
    # Frame 1: working
    working = TaskStatusUpdateEvent(id=task.id, status=TaskStatus(state="working"), final=False)
    yield f"data: {working.model_dump_json()}\n\n"

    if not task.message.parts or not isinstance(task.message.parts[0], DataPart):
        failed = TaskStatusUpdateEvent(
            id=task.id,
            status=TaskStatus(state="failed", message="First part must be a non-empty DataPart"),
            final=True,
        )
        yield f"data: {failed.model_dump_json()}\n\n"
        return

    data = task.message.parts[0].data
    skill = data.get("skill")

    _skill_handlers = {
        "ingest_event": _artifacts_ingest_event,
        "trace_correlation": _artifacts_trace_correlation,
        "run_optimization": _artifacts_run_optimization,
    }

    handler = _skill_handlers.get(skill)
    if handler is None:
        failed = TaskStatusUpdateEvent(
            id=task.id,
            status=TaskStatus(state="failed", message=f"Unknown skill: '{skill}'"),
            final=True,
        )
        yield f"data: {failed.model_dump_json()}\n\n"
        return

    try:
        artifacts = await handler(task.id, data, db_pool)
        final = TaskStatusUpdateEvent(
            id=task.id,
            status=TaskStatus(state="completed"),
            artifacts=artifacts,
            final=True,
        )
        yield f"data: {final.model_dump_json()}\n\n"
    except Exception as e:
        logger.error("SSE streaming error: %s", e)
        failed = TaskStatusUpdateEvent(
            id=task.id,
            status=TaskStatus(state="failed", message=str(e)),
            final=True,
        )
        yield f"data: {failed.model_dump_json()}\n\n"


@router.post("/tasks/sendSubscribe")
async def tasks_send_subscribe(task: A2ATask, db_pool=Depends(get_db_pool)) -> StreamingResponse:
    return StreamingResponse(_sse_generator(task, db_pool), media_type="text/event-stream")
