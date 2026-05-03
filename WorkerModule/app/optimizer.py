import logging
import asyncio
import json
import redis.asyncio as aioredis
from typing import Dict, Any

from .modules.worker.storage import get_global_config, update_global_config, create_events_table
from .config import settings

logger = logging.getLogger(__name__)

async def run_optimizer_loop(db_pool):
    """
    Background task that evaluates pipeline outcomes and autonomous feedback.
    If conditions are met, it autonomously adjusts the Global Configuration
    and broadcasts the update.
    """
    logger.info("Starting Autonomous Optimizer background loop")
    while True:
        try:
            await asyncio.sleep(60) # Run every 60 seconds
            
            # Simple heuristic: scan recent feedback_submitted events
            query = """
                SELECT payload 
                FROM events 
                WHERE event_type = 'feedback_submitted' 
                  AND timestamp > timezone('utc', now()) - interval '5 minutes'
            """
            
            async with db_pool.acquire() as connection:
                try:
                    rows = await connection.fetch(query)
                except Exception:
                    # Ignore if table not created yet
                    continue

            if not rows:
                continue
                
            thumbs_down_count = 0
            thumbs_up_count = 0
            
            for row in rows:
                try:
                    payload = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
                    if payload.get("feedback_type") == "thumbs_down":
                        thumbs_down_count += 1
                    elif payload.get("feedback_type") == "thumbs_up":
                        thumbs_up_count += 1
                except Exception:
                    pass

            config = await get_global_config(db_pool)
            current_threshold = float(config.get("QUALIFICATION_THRESHOLD", 0.6))
            updated = False
            
            # If we are getting a lot of negative feedback, the leads might be too broad.
            # Autonomously INCREASE the qualification threshold to be stricter.
            if thumbs_down_count >= 3 and thumbs_up_count == 0:
                new_threshold = min(0.9, current_threshold + 0.1)
                logger.warning(f"Autonomous Loop: High negative feedback. Adjusting QUALIFICATION_THRESHOLD '{current_threshold}' -> '{new_threshold}'")
                config["QUALIFICATION_THRESHOLD"] = new_threshold
                updated = True
            
            # If everything is going great, we might try expanding the aperture slightly.
            elif thumbs_up_count >= 5 and thumbs_down_count == 0:
                new_threshold = max(0.4, current_threshold - 0.05)
                logger.info(f"Autonomous Loop: Consistently positive feedback. Relaxing QUALIFICATION_THRESHOLD '{current_threshold}' -> '{new_threshold}'")
                config["QUALIFICATION_THRESHOLD"] = new_threshold
                updated = True

            if updated:
                await update_global_config(db_pool, {"QUALIFICATION_THRESHOLD": config["QUALIFICATION_THRESHOLD"]})
                
                # Broadcast
                if settings.REDIS_URL:
                    try:
                        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
                        new_config = await get_global_config(db_pool)
                        await r.publish("config_updated", json.dumps(new_config))
                        await r.aclose()
                        logger.info("Autonomous Loop -> Broadcasted config_updated")
                    except Exception as e:
                        logger.error(f"Autonomous loop failed to broadcast: {e}")

        except asyncio.CancelledError:
            logger.info("Optimizer background loop cancelled")
            break
        except Exception as e:
            logger.error(f"Error in Autonomous Optimizer Loop: {e}")
