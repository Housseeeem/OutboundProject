import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.graph import get_db_pool
from app.routers.orchestrate import router as orchestrate_router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(orchestrate_router)
    return app


def _make_payload(correlation_id: str) -> dict:
    return {
        "correlation_id": correlation_id,
        "lead": {
            "company_id": "acme-123",
            "readiness_flags": {"ready_for_outreach": True},
        },
        "writer_request": {
            "target_prospect": "Jane Doe",
            "target_company": "Acme Corp",
            "company_details": {"company_name": "Sender Co"},
            "selected_offer": {"offer_name": "Product Demo"},
        },
    }


def test_orchestrate_generate_returns_202_and_artifacts():
    app = _make_app()
    mock_pool = MagicMock()
    app.dependency_overrides[get_db_pool] = lambda: mock_pool

    saved_events: list[dict] = []

    async def mock_save_event(pool, event):
        saved_events.append(event)
        return True

    async def mock_publish_event(channel, envelope):
        return True

    detective_instance = MagicMock()
    detective_instance.score_lead = AsyncMock(
        return_value={"final_score": 0.91, "qualified_for_outreach": True}
    )

    writer_instance = MagicMock()
    writer_instance.generate_message = AsyncMock(
        return_value={"success": True, "task_id": str(uuid.uuid4())}
    )

    with patch("app.routers.orchestrate.save_event", side_effect=mock_save_event), \
         patch("app.routers.orchestrate.publish_event", side_effect=mock_publish_event), \
         patch("app.routers.orchestrate.DetectiveA2AClient", return_value=detective_instance), \
         patch("app.routers.orchestrate.WriterA2AClient", return_value=writer_instance):

        client = TestClient(app, raise_server_exceptions=True)
        correlation_id = str(uuid.uuid4())
        response = client.post("/v1/orchestrate/generate", json=_make_payload(correlation_id))

        assert response.status_code == 202
        body = response.json()
        assert body["accepted"] is True
        assert body["correlation_id"] == correlation_id
        assert body["detective"]["qualified_for_outreach"] is True
        assert body["writer"]["success"] is True

    assert saved_events
    stored = saved_events[0]
    assert stored["event_type"] == "lead_ingested"
    assert stored["module"] == "worker"
    assert stored["correlation_id"] == correlation_id
    assert stored["timestamp"]
