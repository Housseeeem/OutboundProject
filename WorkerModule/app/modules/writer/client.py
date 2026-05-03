import uuid
from typing import Any, Dict, Optional

import httpx

from app.config import settings


class WriterClientError(Exception):
    pass


class WriterA2AClient:
    """Command-plane client for the Writer agent (A2A /tasks/send)."""

    def __init__(self, base_url: Optional[str] = None, timeout_s: float = 60.0) -> None:
        self.base_url = (base_url or settings.WRITER_A2A_URL).rstrip("/")
        self.timeout_s = timeout_s

    def _build_task(self, skill: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "message": {
                "role": "user",
                "parts": [
                    {
                        "type": "data",
                        "data": {
                            "skill": skill,
                            **data,
                        },
                    }
                ],
            },
        }

    async def generate_message(self, *, generate_request: Dict[str, Any]) -> Dict[str, Any]:
        """Ask Writer to generate a draft.

        `generate_request` should be compatible with Writer's GenerateRequest model.
        Writer emits `message_generated` / `message_sent` via the event plane.
        """
        task = self._build_task("generate_message", {"generate_request": generate_request})

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(f"{self.base_url}/tasks/send", json=task)
                resp.raise_for_status()
                result = resp.json()
        except Exception as exc:
            raise WriterClientError(f"Writer A2A call failed: {exc}") from exc

        state = (result.get("status") or {}).get("state")
        if state != "completed":
            msg = (result.get("status") or {}).get("message") or "unknown"
            raise WriterClientError(f"Writer task not completed: state={state} message={msg}")

        artifacts = result.get("artifacts") or []
        if not artifacts:
            return result

        first_artifact = artifacts[0] or {}
        parts = first_artifact.get("parts") or []
        if not parts:
            return result

        return parts[0].get("data") or result
