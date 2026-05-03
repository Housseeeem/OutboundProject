import uuid
from typing import Any, Dict, Optional

import httpx

from app.config import settings


class DetectiveClientError(Exception):
    pass


class DetectiveA2AClient:
    """Command-plane client for the Detective agent (A2A /tasks/send)."""

    def __init__(self, base_url: Optional[str] = None, timeout_s: float = 30.0) -> None:
        self.base_url = (base_url or settings.DETECTIVE_A2A_URL).rstrip("/")
        self.timeout_s = timeout_s

    def _build_task(self, envelope: Dict[str, Any]) -> Dict[str, Any]:
        return {
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

    async def score_lead(self, *, envelope: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke Detective scoring and return the scored artifact payload."""
        task = self._build_task(envelope)

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(f"{self.base_url}/tasks/send", json=task)
                resp.raise_for_status()
                result = resp.json()
        except Exception as exc:
            raise DetectiveClientError(f"Detective A2A call failed: {exc}") from exc

        state = (result.get("status") or {}).get("state")
        if state != "completed":
            msg = (result.get("status") or {}).get("message") or "unknown"
            raise DetectiveClientError(f"Detective task not completed: state={state} message={msg}")

        artifacts = result.get("artifacts") or []
        if not artifacts:
            return result

        first_artifact = artifacts[0] or {}
        parts = first_artifact.get("parts") or []
        if not parts:
            return result

        return parts[0].get("data") or result
