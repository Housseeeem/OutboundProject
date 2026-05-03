from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/ready")
async def ready(request: Request) -> dict:
    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool is None:
        raise HTTPException(status_code=503, detail="database pool not initialized")

    try:
        async with db_pool.acquire() as connection:
            await connection.execute("SELECT 1")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database not ready") from exc

    return {"status": "ready"}
