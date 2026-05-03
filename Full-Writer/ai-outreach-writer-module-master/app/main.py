from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from typing import List, Dict
import logging

from .models import AgentState, GenerateRequest, Status, HumanDecision, ReviewResponse
from .pending_review import pending_review
from .orchestrator import PipelineOrchestrator
from .config import settings
from .mcp_server import app as mcp_app
from .send_tools import send_email, send_linkedin_dm
from .graph import run_pipeline
from .memory import MemoryService
from mcp.server.sse import SseServerTransport

# Configuration du Logging
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper()))
logger = logging.getLogger(__name__)

from .a2a import router as a2a_router

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Multi-agent AI system for generating personalized outreach messages"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialisation du transport SSE pour MCP
sse_transport = SseServerTransport("/mcp/messages")

# A2A facade
app.include_router(a2a_router)

# --- ENDPOINTS MCP (CORRIGÉS) ---

@app.get("/mcp")
async def mcp_sse_endpoint(request: Request):
    """
    Établit la connexion SSE pour le protocole MCP.
    """
    async with sse_transport.connect_sse(
        request.scope, 
        request.receive, 
        request._send
    ) as (read_stream, write_stream):
        await mcp_app.run(
            read_stream, 
            write_stream, 
            mcp_app.create_initialization_options()
        )

@app.post("/mcp/messages")
async def mcp_messages(request: Request):
    """Point d'entrée pour les messages envoyés par le client MCP via SSE."""
    await sse_transport.handle_post_message(
        request.scope, 
        request.receive, 
        request._send
    )
    return Response()

# --- LIFECYCLE ---

@app.on_event("startup")
async def startup():
    import httpx
    import asyncio
    from .subscriber import start_writer_subscriber
    
    # Fetch global config from Worker module
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{settings.WORKER_URL}/v1/config", timeout=5.0)
            if resp.status_code == 200:
                worker_config = resp.json()
                settings.update_from_worker(worker_config)
                logger.info("Writer synced dynamic configuration from Worker module")
    except Exception as exc:
        logger.warning(f"Could not fetch dynamic configuration on startup: {exc}")
        
    # Start Redis subscriber for hot-reloads
    app.state.subscriber_task = asyncio.create_task(start_writer_subscriber())

@app.on_event("shutdown")
async def shutdown():
    import asyncio
    if hasattr(app.state, "subscriber_task"):
        app.state.subscriber_task.cancel()
        try:
            await app.state.subscriber_task
        except asyncio.CancelledError:
            pass

# --- ENDPOINTS STANDARDS ---

@app.get("/")
async def root():
    return {
        "status": "online",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "using_mock_data": settings.USE_MOCK_DATA
    }

@app.post("/api/generate", response_model=List[AgentState])
async def generate_outreach(request: GenerateRequest):
    """Pipeline complet : Retourne l'historique de tous les états."""
    try:
        logger.info(f"Generating for {request.target_prospect} @ {request.target_company}")
        orchestrator = PipelineOrchestrator(
            target_prospect=request.target_prospect,
            target_company=request.target_company,
            prospect_role=request.prospect_role,
            channel=request.channel,
            intent=request.intent,
            stage=request.stage,
            personality=request.personality,
            company_details=request.company_details,
            selected_offer=request.selected_offer
        )
        # Inject Detective enrichment data into pipeline state if available
        if request.detective_context:
            orchestrator.initial_state.memory["detective_context"] = request.detective_context
            orchestrator.initial_state.memory["correlation_id"] = request.detective_context.get("correlation_id", "")
        history = orchestrator.run_full_pipeline()
        return history
    except Exception as e:
        logger.error(f"Pipeline failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate/simple")
async def generate_simple(request: GenerateRequest):
    """Pipeline simplifié : Retourne uniquement le message final ou l'URL de revue."""
    try:
        # Exclude detective_context from PipelineOrchestrator kwargs (it's not a constructor param)
        orch_kwargs = request.dict(exclude={"detective_context"})
        orchestrator = PipelineOrchestrator(**orch_kwargs)
        # Inject Detective enrichment data into pipeline state if available
        if request.detective_context:
            orchestrator.initial_state.memory["detective_context"] = request.detective_context
            orchestrator.initial_state.memory["correlation_id"] = request.detective_context.get("correlation_id", "")
        history = orchestrator.run_full_pipeline()
        final = history[-1]

        if final.status == Status.COMPLETE and final.draft:
            return {
                "success": True,
                "task_id": final.task_id,
                "message": final.draft.body,
                "subject": final.draft.subject,
                "score": final.validation.score if final.validation else None
            }
        elif final.status == Status.AWAITING_HUMAN and final.draft:
            pending_review.set(final.task_id, final)
            return {
                "success": True,
                "awaiting_human": True,
                "task_id": final.task_id,
                "review_url": f"/api/review/{final.task_id}"
            }
        else:
            return {"success": False, "error": "Generation incomplete", "status": final.status}
    except Exception as e:
        logger.error(f"Simple generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/review/{task_id}", response_model=ReviewResponse)
async def get_review(task_id: str):
    state = pending_review.get(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Draft not found")
    return ReviewResponse(
        task_id=state.task_id,
        prospect=state.target_prospect,
        company=state.target_company,
        channel=state.channel.value,
        message=state.draft.body,
        subject=state.draft.subject or "",
        score=state.validation.score if state.validation else 0,
        warnings=state.validation.warnings if state.validation else []
    )

@app.post("/api/review/{task_id}/decision")
async def submit_decision(task_id: str, decision: HumanDecision):
    state = pending_review.get(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Draft not found")

    if decision.approved:
        # Logique d'envoi selon le canal
        if state.channel.value == "email":
            res = send_email(to_address=decision.prospect_email, subject=state.draft.subject, body=state.draft.body)
        else:
            res = send_linkedin_dm(
                account_id=settings.UNIPILE_DEFAULT_ACCOUNT_ID,
                message=state.draft.body,
                attendee_provider_id=decision.prospect_linkedin_id,
                attendee_name=state.target_prospect
            )
        
        if res.get("success"):
            _pending_review.pop(task_id)
            # NEW: Emit message_sent event
            try:
                from app.event_emitter import get_writer_emitter
                emitter = get_writer_emitter()
                recipient = decision.prospect_email if state.channel.value == "email" else decision.prospect_linkedin_id
                emitter.emit_message_sent(
                    correlation_id=state.memory.get("correlation_id", ""),
                    channel=state.channel.value,
                    recipient=recipient,
                    send_result=res
                )
            except Exception as e:
                logger.error(f"Failed to emit message_sent event: {e}")

            return {"success": True, "sent": True}
        raise HTTPException(status_code=500, detail="Send failed")
    
    else:
        # Logique de révision/retry
        state.status = Status.REVISING
        state.next_action = {"type": "retry", "feedback": decision.feedback}
        _pending_review.pop(task_id)
        new_history = run_pipeline(state)
        return {"success": True, "rewritten": True, "new_state": new_history[-1]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)