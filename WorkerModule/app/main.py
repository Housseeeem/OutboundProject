import asyncio
import asyncpg
import logging
from fastapi import FastAPI

from app.adapters.graph import GraphAdapter
from app.config import settings
from app.middleware.correlation import CorrelationIDMiddleware
from app.modules.agent.service import AgentService
from app.modules.worker.storage import create_events_table
from app.routers import agent, health, ready, ingest, trace, a2a, config, feedback, orchestrate
from app.subscriber import start_redis_subscriber

logger = logging.getLogger(__name__)

app = FastAPI(title="AgenticOutbound API")

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(CorrelationIDMiddleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(health.router)
app.include_router(ready.router)
app.include_router(ingest.router)
app.include_router(trace.router)
app.include_router(agent.router)
app.include_router(a2a.router)
app.include_router(config.router)
app.include_router(feedback.router)
app.include_router(orchestrate.router)

# ---------------------------------------------------------------------------
# Graph adapter (singleton)
# ---------------------------------------------------------------------------
graph_adapter = GraphAdapter(
    url=settings.GRAPH_DB_URL,
    user=settings.GRAPH_DB_USER,
    password=settings.GRAPH_DB_PASSWORD,
)

# ---------------------------------------------------------------------------
# Database lifecycle
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup() -> None:
    app.state.db_pool = await asyncpg.create_pool(settings.DATABASE_URL)
    await create_events_table(app.state.db_pool)
    app.state.graph_adapter = graph_adapter
    try:
        await app.state.graph_adapter.connect()
        logger.info("Graph adapter connected")
    except Exception as exc:
        logger.warning("Graph adapter unavailable at startup: %s", exc)
    app.state.agent_service = AgentService(app.state.db_pool)
    await app.state.agent_service.ensure_tables()
    mode = app.state.agent_service.provider_status()
    logger.info("Agent LLM mode: %s", mode)
    logger.info("A2A router active — /.well-known/agent.json, /tasks/send, /tasks/sendSubscribe")
    print(f"Agent LLM mode: {mode}")
    print("Postgres pool created")
    app.state.subscriber_task = asyncio.create_task(
        start_redis_subscriber(app.state.db_pool)
    )
    from app.optimizer import run_optimizer_loop
    app.state.optimizer_task = asyncio.create_task(run_optimizer_loop(app.state.db_pool))


@app.on_event("shutdown")
async def shutdown() -> None:
    if hasattr(app.state, "subscriber_task"):
        app.state.subscriber_task.cancel()
        try:
            await app.state.subscriber_task
        except asyncio.CancelledError:
            pass
    if hasattr(app.state, "optimizer_task"):
        app.state.optimizer_task.cancel()
        try:
            await app.state.optimizer_task
        except asyncio.CancelledError:
            pass
    await graph_adapter.close()
    await app.state.db_pool.close()
    print("Postgres pool closed")
