import logging
import os
import uuid

import httpx

from event_emitter import EventEmitter

logger = logging.getLogger(__name__)


class A2AClient:
    def __init__(
        self,
        worker_url: str = "",
        event_emitter: EventEmitter = None,
        timeout: float = 5.0,
        detective_url: str = "",
        writer_url: str = "",
    ):
        # If worker_url is empty/None, read from WORKER_A2A_URL env var, default "http://api:8000"
        self.worker_url = worker_url or os.environ.get("WORKER_A2A_URL", "http://api:8000")
        self.detective_url = detective_url or os.environ.get("DETECTIVE_A2A_URL", "http://detective:8002")
        self.writer_url = writer_url or os.environ.get("WRITER_A2A_URL", "http://writer:8003")
        self.event_emitter = event_emitter
        self.timeout = timeout

    def _build_task(self, envelope: dict) -> dict:
        """Wrap envelope in a DataPart with skill = "ingest_event"."""
        task_id = str(uuid.uuid4())
        correlation_id = envelope.get("correlation_id", "")
        return {
            "id": task_id,
            "message": {
                "role": "user",
                "parts": [
                    {
                        "type": "data",
                        "data": {
                            "skill": "ingest_event",
                            "correlation_id": correlation_id,
                            "envelope": envelope,
                        },
                    }
                ],
            },
        }

    async def send_lead_ingested(self, envelope: dict) -> None:
        task = self._build_task(envelope)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.worker_url}/tasks/send",
                    json=task,
                )
                response.raise_for_status()
                result = response.json()
                state = result.get("status", {}).get("state")
                if state == "completed":
                    logger.info(
                        "A2A ack: task_id=%s correlation_id=%s",
                        task["id"],
                        envelope.get("correlation_id"),
                    )
                    return  # SUCCESS — do NOT publish to Redis
                else:
                    error_msg = result.get("status", {}).get("message", "unknown")
                    logger.warning(
                        "A2A task failed: task_id=%s state=%s error=%s — falling back to Redis",
                        task["id"],
                        state,
                        error_msg,
                    )
                    await self.event_emitter.emit_lead_ingested(envelope["payload"])
        except httpx.TimeoutException as e:
            logger.warning(
                "A2A timeout: task_id=%s — falling back to Redis: %s", task["id"], e
            )
            await self.event_emitter.emit_lead_ingested(envelope["payload"])
        except httpx.ConnectError as e:
            logger.warning(
                "A2A connect error: task_id=%s — falling back to Redis: %s", task["id"], e
            )
            await self.event_emitter.emit_lead_ingested(envelope["payload"])
        except httpx.HTTPStatusError as e:
            logger.warning(
                "A2A HTTP error: task_id=%s status=%s — falling back to Redis",
                task["id"],
                e.response.status_code,
            )
            await self.event_emitter.emit_lead_ingested(envelope["payload"])
        except Exception as e:
            logger.error(
                "A2A unexpected error: task_id=%s — falling back to Redis: %s", task["id"], e
            )
            await self.event_emitter.emit_lead_ingested(envelope["payload"])

    async def send_to_detective(self, envelope: dict) -> dict | None:
        """Send lead to Detective for ICP scoring via A2A /tasks/send."""
        task = {
            "id": str(uuid.uuid4()),
            "message": {
                "role": "user",
                "parts": [
                    {
                        "type": "data",
                        "data": {
                            "skill": "score_lead",
                            "envelope": envelope,
                        },
                    }
                ],
            },
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.detective_url}/tasks/send",
                    json=task,
                )
                response.raise_for_status()
                result = response.json()
                state = result.get("status", {}).get("state")
                if state == "completed":
                    logger.info(
                        "Detective scored lead: correlation_id=%s",
                        envelope.get("correlation_id"),
                    )
                    # Extract scored result from artifacts
                    artifacts = result.get("artifacts", [])
                    if artifacts:
                        return artifacts[0].get("parts", [{}])[0].get("data")
                    return result
                else:
                    logger.warning(
                        "Detective scoring failed: state=%s", state
                    )
                    return None
        except Exception as e:
            logger.warning("Detective A2A call failed: %s", e)
            return None
