from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.a2a import router as a2a_router
from app.models import AgentState, MessageDraft, Status, Validation


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(a2a_router)
    return app


def _make_generate_request() -> dict:
    return {
        "target_prospect": "Jane Doe",
        "target_company": "Acme Corp",
        "company_details": {"company_name": "Sender Co"},
        "selected_offer": {"offer_name": "Product Demo"},
    }


def test_tasks_send_generate_message_completes():
    app = _make_app()

    fake_state = AgentState(
        task_id="task-1",
        status=Status.COMPLETE,
        target_prospect="Jane Doe",
        target_company="Acme Corp",
    )
    fake_state.draft = MessageDraft(body="Hello Jane", subject="Quick note")
    fake_state.validation = Validation(valid=True, score=90, warnings=[])

    fake_orchestrator = MagicMock()
    fake_orchestrator.run_full_pipeline.return_value = [fake_state]

    task = {
        "id": "task-1",
        "message": {
            "role": "user",
            "parts": [
                {
                    "type": "data",
                    "data": {
                        "skill": "generate_message",
                        "generate_request": _make_generate_request(),
                    },
                }
            ],
        },
    }

    with patch("app.a2a.PipelineOrchestrator", return_value=fake_orchestrator):
        client = TestClient(app, raise_server_exceptions=True)
        response = client.post("/tasks/send", json=task)

    assert response.status_code == 200
    body = response.json()
    assert body["status"]["state"] == "completed"

    artifact = body["artifacts"][0]["parts"][0]["data"]
    assert artifact["success"] is True
    assert artifact["message"] == "Hello Jane"
    assert artifact["score"] == 90
