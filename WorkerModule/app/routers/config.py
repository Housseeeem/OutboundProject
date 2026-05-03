import asyncio
import logging
import json
import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Any

from ..modules.worker.storage import get_global_config, update_global_config
from ..adapters.graph import get_db_pool
from ..config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

class ConfigUpdateRequest(BaseModel):
    updates: Dict[str, Any]

@router.get("/v1/config", response_model=Dict[str, Any])
async def get_config(db_pool=Depends(get_db_pool)):
    """Fetches the current global configuration state."""
    try:
        config = await get_global_config(db_pool)
        return config
    except Exception as e:
        logger.error(f"Failed to fetch global config: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/v1/config/update", response_model=Dict[str, Any], status_code=status.HTTP_200_OK)
async def update_config(request: ConfigUpdateRequest, db_pool=Depends(get_db_pool)):
    """Updates global configuration and broadcasts a Redis event."""
    try:
        success = await update_global_config(db_pool, request.updates)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update configuration")

        # Broadcast via Redis so other modules hot-reload
        if settings.REDIS_URL:
            r = redis.from_url(settings.REDIS_URL, decode_responses=True)
            new_config = await get_global_config(db_pool)
            await r.publish("config_updated", json.dumps(new_config))
            await r.aclose()
        else:
            logger.warning("REDIS_URL not set; config updates will not be broadcast.")

        return {"accepted": True, "updates": request.updates}

    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
