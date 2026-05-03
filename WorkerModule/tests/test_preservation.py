"""
Preservation Property Tests — Task 2
======================================
Property 2: Preservation — Existing Emit and Ingest Behavior Unchanged

These tests capture BASELINE behavior that MUST NOT be broken by the fix.
They MUST PASS on unfixed code.

Validates: Requirements 3.1, 3.2, 3.3, 3.4
"""

import asyncio
import json
import sys
import os
import uuid
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup — allow imports from WorkerModule/app and inject_collect_project
# ---------------------------------------------------------------------------
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORKER_APP = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, WORKSPACE_ROOT)
sys.path.insert(0, WORKER_APP)


# ===========================================================================
# Observation 1: emit_lead_ingested publishes to "lead_ingested" when Redis available
# Validates: Requirement 3.1
# ===========================================================================

class TestEmitPublishesToRedisWhenAvailable:
    """
    Validates: Requirement 3.1

    WHEN Redis is available THEN emit_lead_ingested() SHALL CONTINUE TO publish
    to the "lead_ingested" channel.
    """

    @pytest.mark.asyncio
    async def test_emit_publishes_to_lead_ingested_channel(self):
        """
        Observe: emit_lead_ingested(payload) publishes to "lead_ingested" channel
        when Redis is available (unfixed code).
        """
        from inject_collect_project.event_emitter import EventEmitter

        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(return_value=1)

        emitter = EventEmitter.__new__(EventEmitter)
        emitter._redis = mock_redis
        emitter._queue = None

        payload = {
            "company_id": "test-company",
            "correlation_id": str(uuid.uuid4()),
            "company_data": {"name": "Acme", "domain": "acme.com"},
            "enrichment_data": {},
            "personas": [],
            "intent_signals": [],
            "readiness_flags": {},
            "event_type": "lead_ingested",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        await emitter.emit_lead_ingested(payload)

        mock_redis.publish.assert_called_once()
        channel_arg = mock_redis.publish.call_args[0][0]
        assert channel_arg == "lead_ingested", (
            f"Expected publish to 'lead_ingested' channel, got '{channel_arg}'"
        )

    @pytest.mark.asyncio
    async def test_emit_publishes_valid_json_envelope(self):
        """
        Observe: the published message is valid JSON containing the envelope fields.
        """
        from inject_collect_project.event_emitter import EventEmitter

        published_messages = []

        async def capture_publish(channel, message):
            published_messages.append((channel, message))
            return 1

        mock_redis = AsyncMock()
        mock_redis.publish = capture_publish

        emitter = EventEmitter.__new__(EventEmitter)
        emitter._redis = mock_redis
        emitter._queue = None

        correlation_id = str(uuid.uuid4())
        payload = {
            "company_id": "test-company",
            "correlation_id": correlation_id,
            "company_data": {"name": "Acme", "domain": "acme.com"},
            "enrichment_data": {},
            "personas": [],
            "intent_signals": [],
            "readiness_flags": {},
            "event_type": "lead_ingested",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        await emitter.emit_lead_ingested(payload)

        assert len(published_messages) == 1
        channel, message = published_messages[0]
        assert channel == "lead_ingested"

        envelope = json.loads(message)
        assert "event_id" in envelope
        assert "correlation_id" in envelope
        assert "module" in envelope
        assert "event_type" in envelope
        assert "timestamp" in envelope
        assert "payload" in envelope
        assert "metadata" in envelope


# ===========================================================================
# Observation 2: emit_lead_ingested pushes to in-memory queue when Redis unavailable
# Validates: Requirement 3.2
# ===========================================================================

class TestEmitFallsBackToQueueWhenRedisUnavailable:
    """
    Validates: Requirement 3.2

    WHEN Redis is unavailable THEN emit_lead_ingested() SHALL CONTINUE TO fall
    back to the in-memory queue without raising an exception.
    """

    @pytest.mark.asyncio
    async def test_emit_pushes_to_queue_when_redis_none(self):
        """
        Observe: emit_lead_ingested(payload) pushes to in-memory queue when
        Redis is unavailable (unfixed code).
        """
        from inject_collect_project.event_emitter import EventEmitter

        queue = asyncio.Queue()

        emitter = EventEmitter.__new__(EventEmitter)
        emitter._redis = None
        emitter._queue = queue

        payload = {
            "company_id": "test-company",
            "correlation_id": str(uuid.uuid4()),
            "company_data": {"name": "Acme", "domain": "acme.com"},
            "enrichment_data": {},
            "personas": [],
            "intent_signals": [],
            "readiness_flags": {},
            "event_type": "lead_ingested",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        await emitter.emit_lead_ingested(payload)

        assert queue.qsize() == 1, (
            f"Expected 1 item in in-memory queue, got {queue.qsize()}"
        )

        item = await queue.get()
        envelope = json.loads(item)
        assert envelope["module"] == "inject"
        assert envelope["correlation_id"] == payload["correlation_id"]

    @pytest.mark.asyncio
    async def test_emit_does_not_raise_when_redis_unavailable(self):
        """
        Observe: emit_lead_ingested() does NOT raise an exception when Redis is None.
        """
        from inject_collect_project.event_emitter import EventEmitter

        emitter = EventEmitter.__new__(EventEmitter)
        emitter._redis = None
        emitter._queue = asyncio.Queue()

        payload = {
            "company_id": "test-company",
            "correlation_id": str(uuid.uuid4()),
            "company_data": {},
            "enrichment_data": {},
            "personas": [],
            "intent_signals": [],
            "readiness_flags": {},
            "event_type": "lead_ingested",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Must not raise
        await emitter.emit_lead_ingested(payload)


# ===========================================================================
# Observation 3: emit_lead_ingested logs warning and swallows exceptions on failure
# Validates: Requirement 3.3
# ===========================================================================

class TestEmitSwallowsExceptionsOnFailure:
    """
    Validates: Requirement 3.3

    WHEN emission fails THEN emit_lead_ingested() SHALL CONTINUE TO log a warning
    without raising an exception.
    """

    @pytest.mark.asyncio
    async def test_emit_swallows_redis_exception(self):
        """
        Observe: emit_lead_ingested() logs a warning and swallows exceptions on failure.
        """
        from inject_collect_project.event_emitter import EventEmitter

        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(side_effect=ConnectionError("Redis connection refused"))

        emitter = EventEmitter.__new__(EventEmitter)
        emitter._redis = mock_redis
        emitter._queue = None

        payload = {
            "company_id": "test-company",
            "correlation_id": str(uuid.uuid4()),
            "company_data": {},
            "enrichment_data": {},
            "personas": [],
            "intent_signals": [],
            "readiness_flags": {},
            "event_type": "lead_ingested",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Must not raise — exception must be swallowed
        await emitter.emit_lead_ingested(payload)

    @pytest.mark.asyncio
    async def test_emit_logs_warning_on_failure(self):
        """
        Observe: emit_lead_ingested() logs a warning when emission fails.
        """
        from inject_collect_project.event_emitter import EventEmitter

        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(side_effect=RuntimeError("unexpected error"))

        emitter = EventEmitter.__new__(EventEmitter)
        emitter._redis = mock_redis
        emitter._queue = None

        payload = {
            "company_id": "test-company",
            "correlation_id": str(uuid.uuid4()),
            "company_data": {},
            "enrichment_data": {},
            "personas": [],
            "intent_signals": [],
            "readiness_flags": {},
            "event_type": "lead_ingested",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with patch("inject_collect_project.event_emitter.logger") as mock_logger:
            await emitter.emit_lead_ingested(payload)
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "Failed to emit" in warning_msg or "lead_ingested" in warning_msg.lower() or "%" in warning_msg


# ===========================================================================
# Observation 4: POST /v1/events/ingest HTTP endpoint accepts and stores events
# Validates: Requirement 3.4 (HTTP ingest path unchanged)
# ===========================================================================

def _make_app_with_mocks():
    """
    Build a minimal FastAPI test app that includes only the ingest router,
    with all heavy dependencies (asyncpg, google.genai, langchain_core, neo4j)
    mocked out. This avoids importing app.main which pulls in the full dependency
    chain.
    Returns (app, get_db_pool) tuple.
    """
    import sys

    # Mock asyncpg if not installed
    if "asyncpg" not in sys.modules:
        asyncpg_mock = MagicMock()
        asyncpg_mock.create_pool = AsyncMock(return_value=MagicMock())
        asyncpg_mock.PostgresConnectionError = Exception
        asyncpg_mock.PostgresError = Exception
        asyncpg_mock.exceptions = MagicMock()
        asyncpg_mock.exceptions.UndefinedTableError = Exception
        sys.modules["asyncpg"] = asyncpg_mock

    # Mock google.genai if not installed
    if "google.genai" not in sys.modules:
        google_mock = sys.modules.get("google", MagicMock())
        google_mock.genai = MagicMock()
        sys.modules["google"] = google_mock
        sys.modules["google.genai"] = MagicMock()
        sys.modules["google.genai.types"] = MagicMock()

    # Mock langchain_core if not installed
    for mod in ["langchain_core", "langchain_core.documents", "langchain_core.embeddings",
                "langchain_core.vectorstores", "langchain_community", "langchain_community.vectorstores"]:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()

    # Mock neo4j if not installed
    if "neo4j" not in sys.modules:
        sys.modules["neo4j"] = MagicMock()

    from fastapi import FastAPI
    from app.routers.ingest import router as ingest_router
    from app.adapters.graph import get_db_pool

    test_app = FastAPI()
    test_app.include_router(ingest_router)
    return test_app, get_db_pool


class TestHTTPIngestEndpointPreservation:
    """
    Validates: Requirement 3.4 (HTTP ingest path must remain unchanged)

    WorkerModule's existing POST /v1/events/ingest HTTP endpoint MUST continue
    to work exactly as before.
    """

    def _make_valid_envelope(self, event_type: str = "lead_ingested") -> dict:
        return {
            "event_id": str(uuid.uuid4()),
            "correlation_id": str(uuid.uuid4()),
            "module": "inject",
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"company_id": "test", "data": "value"},
            "metadata": {},
        }

    def test_ingest_endpoint_returns_202_for_valid_envelope(self):
        """
        Observe: POST /v1/events/ingest returns 202 Accepted for a valid envelope.
        """
        from fastapi.testclient import TestClient

        app, get_db_pool = _make_app_with_mocks()
        mock_pool = MagicMock()

        async def mock_save_event(pool, event):
            return True

        async def mock_find_near_dup(pool, **kwargs):
            return None

        app.dependency_overrides[get_db_pool] = lambda: mock_pool

        try:
            with patch("app.routers.ingest.save_event", side_effect=mock_save_event), \
                 patch("app.routers.ingest.find_near_duplicate_event", side_effect=mock_find_near_dup):

                client = TestClient(app, raise_server_exceptions=True)
                envelope = self._make_valid_envelope()
                response = client.post("/v1/events/ingest", json=envelope)
                assert response.status_code == 202, (
                    f"Expected 202 Accepted, got {response.status_code}: {response.text}"
                )
                body = response.json()
                assert body["accepted"] is True
        finally:
            app.dependency_overrides.clear()

    def test_ingest_endpoint_calls_save_event(self):
        """
        Observe: POST /v1/events/ingest calls save_event() to persist the event.
        """
        from fastapi.testclient import TestClient

        app, get_db_pool = _make_app_with_mocks()
        mock_pool = MagicMock()
        save_event_calls = []

        async def mock_save_event(pool, event):
            save_event_calls.append(event)
            return True

        async def mock_find_near_dup(pool, **kwargs):
            return None

        app.dependency_overrides[get_db_pool] = lambda: mock_pool

        try:
            with patch("app.routers.ingest.save_event", side_effect=mock_save_event), \
                 patch("app.routers.ingest.find_near_duplicate_event", side_effect=mock_find_near_dup):

                client = TestClient(app, raise_server_exceptions=True)
                envelope = self._make_valid_envelope()
                response = client.post("/v1/events/ingest", json=envelope)

                assert response.status_code == 202
                assert len(save_event_calls) == 1
                stored = save_event_calls[0]
                assert str(stored["correlation_id"]) == envelope["correlation_id"]
                assert stored["module"] == "inject"
        finally:
            app.dependency_overrides.clear()


# ===========================================================================
# Property-Based Test 1: For all valid Detective payloads,
# emit_lead_ingested() always produces envelope where
# envelope["correlation_id"] == payload["correlation_id"] AND
# envelope["module"] == "inject"
# Validates: Requirements 3.1, 3.4
# ===========================================================================

# Hypothesis strategy for generating valid detective payloads
_detective_payload_strategy = st.fixed_dictionaries({
    "company_id": st.text(min_size=1, max_size=50),
    "correlation_id": st.uuids().map(str),
    "company_data": st.fixed_dictionaries({
        "name": st.text(min_size=1, max_size=100),
        "domain": st.text(min_size=1, max_size=100),
    }),
    "enrichment_data": st.dictionaries(
        st.text(min_size=1, max_size=20),
        st.text(max_size=50),
        max_size=5,
    ),
    "personas": st.lists(st.text(max_size=50), max_size=5),
    "intent_signals": st.lists(st.text(max_size=50), max_size=5),
    "readiness_flags": st.dictionaries(
        st.text(min_size=1, max_size=20),
        st.booleans(),
        max_size=5,
    ),
    "event_type": st.just("lead_ingested"),
    "timestamp": st.just(datetime.now(timezone.utc).isoformat()),
})


class TestPropertyEnvelopePreservation:
    """
    Property 2: Preservation — Existing Emit and Ingest Behavior Unchanged

    For all valid Detective payloads, emit_lead_ingested() always produces an
    envelope where:
      - envelope["correlation_id"] == payload["correlation_id"]
      - envelope["module"] == "inject"

    Validates: Requirements 3.1, 3.4
    """

    @given(_detective_payload_strategy)
    @h_settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_envelope_correlation_id_matches_payload(self, payload: dict):
        """
        **Validates: Requirements 3.1, 3.4**

        Property: For all valid Detective payloads, emit_lead_ingested() always
        produces an envelope where envelope["correlation_id"] == payload["correlation_id"]
        and envelope["module"] == "inject".
        """
        from inject_collect_project.event_emitter import EventEmitter

        published_envelopes = []

        async def run():
            async def capture_publish(channel, message):
                published_envelopes.append(json.loads(message))
                return 1

            mock_redis = AsyncMock()
            mock_redis.publish = capture_publish

            emitter = EventEmitter.__new__(EventEmitter)
            emitter._redis = mock_redis
            emitter._queue = None

            await emitter.emit_lead_ingested(payload)

        asyncio.get_event_loop().run_until_complete(run())

        assert len(published_envelopes) == 1, (
            f"Expected exactly 1 envelope published, got {len(published_envelopes)}"
        )

        envelope = published_envelopes[0]

        assert envelope["correlation_id"] == payload["correlation_id"], (
            f"Envelope correlation_id '{envelope['correlation_id']}' does not match "
            f"payload correlation_id '{payload['correlation_id']}'"
        )

        assert envelope["module"] == "inject", (
            f"Envelope module '{envelope['module']}' is not 'inject'"
        )

    @given(_detective_payload_strategy)
    @h_settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_envelope_has_all_required_fields(self, payload: dict):
        """
        **Validates: Requirements 3.1, 3.4**

        Property: For all valid Detective payloads, emit_lead_ingested() always
        produces an envelope containing all seven required EventEnvelope fields.
        """
        from inject_collect_project.event_emitter import EventEmitter

        published_envelopes = []

        async def run():
            async def capture_publish(channel, message):
                published_envelopes.append(json.loads(message))
                return 1

            mock_redis = AsyncMock()
            mock_redis.publish = capture_publish

            emitter = EventEmitter.__new__(EventEmitter)
            emitter._redis = mock_redis
            emitter._queue = None

            await emitter.emit_lead_ingested(payload)

        asyncio.get_event_loop().run_until_complete(run())

        assert len(published_envelopes) == 1
        envelope = published_envelopes[0]

        required_fields = {"event_id", "correlation_id", "module", "event_type", "timestamp", "payload", "metadata"}
        missing = required_fields - set(envelope.keys())
        assert not missing, (
            f"Envelope is missing required fields: {missing}. "
            f"Envelope keys: {set(envelope.keys())}"
        )

        assert isinstance(envelope["payload"], dict), (
            f"envelope['payload'] must be a dict, got {type(envelope['payload'])}"
        )
        assert isinstance(envelope["metadata"], dict), (
            f"envelope['metadata'] must be a dict, got {type(envelope['metadata'])}"
        )


# ===========================================================================
# Property-Based Test 2: For all non-lead_ingested HTTP ingest requests,
# POST /v1/events/ingest returns 202 Accepted regardless of subscriber state
# Validates: Requirements 3.1, 3.4
# ===========================================================================

# Strategy for non-lead_ingested event types
_non_lead_ingested_event_type_strategy = st.text(
    min_size=1, max_size=50,
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_")
).filter(lambda s: s != "lead_ingested" and s.strip() != "")

_allowed_modules = ["inject", "detective", "writer", "worker"]

_http_envelope_strategy = st.fixed_dictionaries({
    "event_id": st.uuids().map(str),
    "correlation_id": st.uuids().map(str),
    "module": st.sampled_from(_allowed_modules),
    "event_type": _non_lead_ingested_event_type_strategy,
    "timestamp": st.just(datetime.now(timezone.utc).isoformat()),
    "payload": st.fixed_dictionaries({
        "key": st.text(max_size=20),
    }),
    "metadata": st.just({}),
})


class TestPropertyHTTPIngestPreservation:
    """
    Property 2: Preservation — HTTP Ingest Endpoint Unchanged

    For all non-lead_ingested HTTP ingest requests, POST /v1/events/ingest
    returns 202 Accepted regardless of subscriber state.

    Validates: Requirements 3.1, 3.4
    """

    @given(_http_envelope_strategy)
    @h_settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow])
    def test_non_lead_ingested_ingest_returns_202(self, envelope: dict):
        """
        **Validates: Requirements 3.1, 3.4**

        Property: For all non-lead_ingested HTTP ingest requests,
        POST /v1/events/ingest returns 202 Accepted regardless of subscriber state.
        """
        from fastapi.testclient import TestClient

        app, get_db_pool = _make_app_with_mocks()
        mock_pool = MagicMock()

        async def mock_save_event(pool, event):
            return True

        async def mock_find_near_dup(pool, **kwargs):
            return None

        app.dependency_overrides[get_db_pool] = lambda: mock_pool

        try:
            with patch("app.routers.ingest.save_event", side_effect=mock_save_event), \
                 patch("app.routers.ingest.find_near_duplicate_event", side_effect=mock_find_near_dup):

                client = TestClient(app, raise_server_exceptions=True)
                response = client.post("/v1/events/ingest", json=envelope)

                assert response.status_code == 202, (
                    f"Expected 202 Accepted for event_type='{envelope['event_type']}', "
                    f"got {response.status_code}: {response.text}"
                )
                body = response.json()
                assert body["accepted"] is True
        finally:
            app.dependency_overrides.clear()
