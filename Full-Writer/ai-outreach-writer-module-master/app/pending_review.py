from typing import Dict

from .models import AgentState


class PendingReviewStore:
    """Simple in-process store for drafts awaiting human review.

    Interface is intentionally minimal so it can be swapped for a Redis
    implementation without touching any call sites.
    """

    def __init__(self) -> None:
        self._data: Dict[str, AgentState] = {}

    def get(self, task_id: str) -> AgentState | None:
        return self._data.get(task_id)

    def set(self, task_id: str, state: AgentState) -> None:
        self._data[task_id] = state

    def pop(self, task_id: str) -> None:
        self._data.pop(task_id, None)


pending_review = PendingReviewStore()
