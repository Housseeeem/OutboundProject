import asyncio
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.modules.agent.service import AgentServiceError, AgentTimeoutError

router = APIRouter(prefix="/v1/agent", tags=["agent"])


class AgentRunRequest(BaseModel):
    objective: str = Field(min_length=3)
    correlation_id: Optional[str] = None
    max_steps: int = Field(default=20, ge=1, le=200)
    external_enrichment_url: Optional[str] = None


class AgentRunsListResponse(BaseModel):
    items: list[Dict[str, Any]]

class ResumeRunRequest(BaseModel):
    action_type: str = Field(description="Action to perform (e.g., 'approve_message', 'select_companies')")
    payload: Optional[Dict[str, Any]] = None


@router.post("/runs", response_model=Dict[str, Any])
async def create_agent_run(payload: AgentRunRequest, request: Request):
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent service is not initialized")

    try:
        return await service.run_objective(
            objective=payload.objective,
            correlation_id=payload.correlation_id,
            max_steps=payload.max_steps,
            external_enrichment_url=payload.external_enrichment_url,
        )
    except AgentTimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "AGENT_TIMEOUT", "message": str(exc)},
        ) from exc
    except AgentServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Agent run failed") from exc


@router.post("/runs/async", response_model=Dict[str, Any])
async def create_agent_run_async(payload: AgentRunRequest, request: Request):
    """Start an agent run in the background and return immediately."""
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent service is not initialized")

    run_id = str(uuid.uuid4())
    correlation_id = payload.correlation_id or str(uuid.uuid4())

    # We kick off the task without waiting for it
    asyncio.create_task(
        service.run_objective(
            objective=payload.objective,
            correlation_id=correlation_id,
            max_steps=payload.max_steps,
            external_enrichment_url=payload.external_enrichment_url,
            run_id=run_id,
        )
    )

    return {
        "run_id": run_id,
        "correlation_id": correlation_id,
        "status": "running",
        "message": "Agent run started in the background",
    }


@router.post("/runs/{run_id}/resume", response_model=Dict[str, Any])
async def resume_agent_run(run_id: str, request_data: ResumeRunRequest, request: Request):
    """Resume a paused agent run after user interaction."""
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent service is not initialized")

    try:
        # Start resume process asynchronously if it takes time, but here it's fast or starts a background task.
        # Wait, if resume restarts the agent loop, it will block the HTTP response if we await it!
        # Let's run it in the background if it's 'select_companies' which restarts the loop.
        if request_data.action_type in ("select_companies", "select_personas"):
            asyncio.create_task(service.resume_run(run_id, request_data.action_type, request_data.payload))
            return {"run_id": run_id, "status": "resumed_in_background", "message": "Agent loop resumed"}
        else:
            return await service.resume_run(run_id, request_data.action_type, request_data.payload)
    except AgentServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to resume run") from exc


@router.get("/runs/{run_id}", response_model=Dict[str, Any])
async def get_agent_run(run_id: str, request: Request):
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent service is not initialized")

    run = await service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


@router.get("/runs/{run_id}/evaluation", response_model=Dict[str, Any])
async def get_agent_run_evaluation(run_id: str, request: Request):
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent service is not initialized")

    run = await service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    
    state = run.get("state", {})
    evaluation = state.get("evaluation")
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found for this run")
        
    return evaluation


@router.get("/runs", response_model=AgentRunsListResponse)
async def list_agent_runs(
    request: Request,
    limit: int = 50,
    status: Optional[str] = None,
):
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent service is not initialized")

    runs = await service.list_runs(limit=limit, status=status)
    return {"items": runs}


@router.get("/tools", response_model=Dict[str, Any])
async def list_agent_tools(request: Request):
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent service is not initialized")

    return {"tools": service.get_tool_contracts()}


@router.post("/runs/cleanup", response_model=Dict[str, Any])
async def cleanup_agent_runs(
    request: Request,
    older_than_days: Optional[int] = None,
):
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent service is not initialized")

    deleted = await service.cleanup_runs(older_than_days=older_than_days)
    return {"deleted": deleted}
