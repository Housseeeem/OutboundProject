from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from .models import GenerateRequest, Status
from .orchestrator import PipelineOrchestrator
from .pending_review import pending_review


router = APIRouter()


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


WRITER_AGENT_CARD: Dict[str, Any] = {
    "name": "Writer Agent",
    "description": "Generates outreach drafts and emits message_generated/message_sent events.",
    "url": "http://writer:8003",
    "version": "1.0.0",
    "skills": [
        {
            "id": "generate_message",
            "name": "Generate Message",
            "description": "Runs the writer pipeline with an explicit GenerateRequest.",
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
        }
    ],
}


def _failed(task_id: str, message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=TaskResult(id=task_id, status=TaskStatus(state="failed", message=message), artifacts=[]).model_dump(),
    )


@router.get("/.well-known/agent.json")
async def get_agent_card() -> JSONResponse:
    return JSONResponse(content=WRITER_AGENT_CARD)


@router.post("/tasks/send")
async def tasks_send(task: A2ATask) -> JSONResponse:
    if not task.message.parts:
        return _failed(task.id, "message.parts must not be empty")

    first_part = task.message.parts[0]
    if not isinstance(first_part, DataPart):
        return _failed(task.id, "First part must be a DataPart")

    data = first_part.data
    skill = data.get("skill")

    if skill != "generate_message":
        return _failed(task.id, f"Unknown skill: '{skill}'")

    generate_request = data.get("generate_request")
    if not isinstance(generate_request, dict):
        return _failed(task.id, "Missing or invalid 'generate_request' in data")

    try:
        req = GenerateRequest.model_validate(generate_request)
    except Exception as exc:
        return _failed(task.id, f"Invalid generate_request: {exc}")

    try:
        orchestrator = PipelineOrchestrator(
            target_prospect=req.target_prospect,
            target_company=req.target_company,
            prospect_role=req.prospect_role,
            channel=req.channel,
            intent=req.intent,
            stage=req.stage,
            personality=req.personality,
            company_details=req.company_details,
            selected_offer=req.selected_offer,
        )

        if req.detective_context:
            orchestrator.initial_state.memory["detective_context"] = req.detective_context
            orchestrator.initial_state.memory["correlation_id"] = req.detective_context.get("correlation_id", "")

        history = orchestrator.run_full_pipeline()
        final = history[-1]

        response: Dict[str, Any] = {
            "success": final.status in (Status.COMPLETE, Status.AWAITING_HUMAN),
            "task_id": final.task_id,
            "status": final.status,
            "awaiting_human": final.status == Status.AWAITING_HUMAN,
        }

        if final.draft:
            response.update({
                "message": final.draft.body,
                "subject": final.draft.subject,
            })
        if final.validation:
            response.update({
                "score": final.validation.score,
                "warnings": final.validation.warnings,
            })

        if final.status == Status.AWAITING_HUMAN:
            pending_review.set(final.task_id, final)
            response["review_url"] = f"/api/review/{final.task_id}"

        return JSONResponse(
            content=TaskResult(
                id=task.id,
                status=TaskStatus(state="completed"),
                artifacts=[Artifact(parts=[ArtifactPart(type="data", data=response)])],
            ).model_dump()
        )
    except Exception as exc:
        import logging
        logger = logging.getLogger("app.a2a")
        logger.error(f"Writer pipeline error: {exc}")
        return _failed(task.id, f"Writer pipeline error: {exc}", status_code=500)
