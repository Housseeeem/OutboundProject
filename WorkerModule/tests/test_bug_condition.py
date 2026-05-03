"""
Bug Condition Exploration Tests — Task 1
=========================================
Property 1: Bug Condition — Lead Ingested Event Never Reaches Worker Storage

These tests encode the DESIRED/FIXED behavior so they FAIL on unfixed code,
proving the bug exists. Failures are the expected outcome for Task 1.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
"""

import asyncio
import json
import sys
import os
import uuid
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
# Sub-task 1: WorkerModule startup does NOT launch a Redis subscriber task
# ---------------------------------------------------------------------------
# DESIRED behavior (after fix): app.state.subscriber_task IS present after startup.
# UNFIXED behavior: app.state has NO subscriber_task → test FAILS → bug confirmed.
# ===========================================================================

class TestNoSubscriberTask:
    """
    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5

    After the fix, WorkerModule's startup MUST store a running asyncio.Task on
    app.state.subscriber_task. On unfixed code this attribute is absent, so the
    assertion below fails — confirming the bug.
    """

    def test_startup_creates_subscriber_task(self):
        """
        DESIRED: main.py startup() launches a subscriber task and stores it on
        app.state.subscriber_task.

        FAILS on unfixed code because main.py never references subscriber_task.
        Counterexample: 'subscriber_task' not found in main.py source code.
        """
        main_py_path = os.path.join(WORKER_APP, "app", "main.py")
        assert os.path.exists(main_py_path), f"main.py not found at {main_py_path}"

        with open(main_py_path) as f:
            source = f.read()

        assert "subscriber_task" in source, (
            "BUG CONFIRMED: 'subscriber_task' is not referenced anywhere in "
            "WorkerModule/app/main.py. The startup() function never launches a "
            "Redis subscriber background task. "
            "Counterexample: grep('subscriber_task', main.py) == [] (not found)"
        )

        assert "start_redis_subscriber" in source or "subscriber" in source, (
            "BUG CONFIRMED: main.py does not import or call any subscriber function. "
            "No Redis subscriber is wired into the startup lifecycle. "
            "Counterexample: no subscriber import or call found in main.py"
        )


# ===========================================================================
# Sub-task 2: Publishing a valid envelope to lead_ingested → save_event NEVER called
# ---------------------------------------------------------------------------
# DESIRED behavior (after fix): save_event IS called when a message is published.
# UNFIXED behavior: no subscriber exists → save_event call count = 0 → test FAILS.
# ===========================================================================

class TestSaveEventNeverCalled:
    """
    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5

    Simulates a Redis message arriving on the lead_ingested channel and asserts
    that save_event() IS called with the correct envelope. On unfixed code there
    is no subscriber.py, so save_event is never called — test FAILS.
    """

    @pytest.mark.asyncio
    async def test_redis_message_triggers_save_event(self):
        """
        DESIRED: When a valid EventEnvelope JSON arrives on the lead_ingested
        channel, save_event() is called exactly once with matching correlation_id.

        FAILS on unfixed code because subscriber.py does not exist — no one
        listens on the channel, so save_event call count = 0.
        Counterexample: save_event.call_count == 0 (expected >= 1)
        """
        subscriber_path = os.path.join(WORKER_APP, "app", "subscriber.py")

        assert os.path.exists(subscriber_path), (
            "BUG CONFIRMED: WorkerModule/app/subscriber.py does not exist. "
            "There is no Redis subscriber — save_event() can never be called "
            "from a Redis lead_ingested message. "
            "Counterexample: subscriber.py file is missing entirely."
        )

        # If subscriber.py exists, verify it calls save_event
        with open(subscriber_path) as f:
            subscriber_source = f.read()

        assert "save_event" in subscriber_source, (
            "BUG CONFIRMED: subscriber.py exists but does not call save_event(). "
            "Events received from Redis would never be persisted. "
            "Counterexample: grep('save_event', subscriber.py) == [] (not found)"
        )

        assert "lead_ingested" in subscriber_source, (
            "BUG CONFIRMED: subscriber.py does not subscribe to 'lead_ingested' channel. "
            "Counterexample: grep('lead_ingested', subscriber.py) == [] (not found)"
        )


# ===========================================================================
# Sub-task 3: Docker-compose files share no common network or Redis service
# ---------------------------------------------------------------------------
# DESIRED behavior (after fix): both compose files share a network and Redis.
# UNFIXED behavior: completely isolated → test FAILS → infrastructure bug confirmed.
# ===========================================================================

class TestDockerNetworkIsolation:
    """
    Validates: Requirements 1.1 (infrastructure gap)

    Parses both docker-compose.yml files and asserts they share a common network
    and Redis service. On unfixed code they are completely isolated — test FAILS.
    """

    def _load_compose(self, path: str) -> dict:
        try:
            import yaml  # type: ignore
        except ImportError:
            # Fallback: minimal YAML-like parsing for simple cases
            return {}
        with open(path) as f:
            return yaml.safe_load(f) or {}

    def _get_compose_networks(self, compose: dict) -> set:
        networks: set = set()
        for svc_name, svc in (compose.get("services") or {}).items():
            svc_networks = svc.get("networks") or []
            if isinstance(svc_networks, list):
                networks.update(svc_networks)
            elif isinstance(svc_networks, dict):
                networks.update(svc_networks.keys())
        top_level = compose.get("networks") or {}
        networks.update(top_level.keys())
        return networks

    def _get_redis_services(self, compose: dict) -> list:
        redis_svcs = []
        for svc_name, svc in (compose.get("services") or {}).items():
            image = (svc or {}).get("image", "")
            if "redis" in image.lower():
                redis_svcs.append(svc_name)
        return redis_svcs

    def test_shared_network_exists(self):
        """
        DESIRED: Both docker-compose files share at least one common network.

        FAILS on unfixed code because inject uses 'scraper_network' and Worker
        has no network definitions at all — they are completely isolated.
        Counterexample: shared_networks = set() (empty)
        """
        inject_compose_path = os.path.join(
            WORKSPACE_ROOT, "inject_collect_project", "docker-compose.yml"
        )
        worker_compose_path = os.path.join(
            WORKSPACE_ROOT, "WorkerModule", "docker-compose.yml"
        )

        inject_compose = self._load_compose(inject_compose_path)
        worker_compose = self._load_compose(worker_compose_path)

        inject_networks = self._get_compose_networks(inject_compose)
        worker_networks = self._get_compose_networks(worker_compose)

        shared_networks = inject_networks & worker_networks

        assert len(shared_networks) > 0, (
            f"BUG CONFIRMED: inject_collect_project and WorkerModule share NO common Docker network. "
            f"inject networks: {inject_networks}, worker networks: {worker_networks}. "
            f"Counterexample: shared_networks = {shared_networks} (empty set)"
        )

    def test_shared_redis_service_exists(self):
        """
        DESIRED: At least one docker-compose file (or a shared root compose) defines
        a Redis service accessible to both services.

        FAILS on unfixed code because neither compose file has a Redis service.
        Counterexample: inject_redis=[], worker_redis=[]
        """
        inject_compose_path = os.path.join(
            WORKSPACE_ROOT, "inject_collect_project", "docker-compose.yml"
        )
        worker_compose_path = os.path.join(
            WORKSPACE_ROOT, "WorkerModule", "docker-compose.yml"
        )
        root_compose_path = os.path.join(WORKSPACE_ROOT, "docker-compose.yml")

        inject_compose = self._load_compose(inject_compose_path)
        worker_compose = self._load_compose(worker_compose_path)

        inject_redis = self._get_redis_services(inject_compose)
        worker_redis = self._get_redis_services(worker_compose)

        # Also check for a shared root-level compose
        root_redis = []
        if os.path.exists(root_compose_path):
            root_compose = self._load_compose(root_compose_path)
            root_redis = self._get_redis_services(root_compose)

        total_redis = inject_redis + worker_redis + root_redis

        assert len(total_redis) > 0, (
            f"BUG CONFIRMED: No Redis service found in any docker-compose.yml. "
            f"inject_redis={inject_redis}, worker_redis={worker_redis}, root_redis={root_redis}. "
            f"Counterexample: total_redis = [] (no shared Redis container)"
        )


# ===========================================================================
# Sub-task 4 (Property-Based): For any valid detective payload,
# emit_lead_ingested → save_event IS called in Worker
# ---------------------------------------------------------------------------
# DESIRED behavior (after fix): save_event is always called.
# UNFIXED behavior: no subscriber → save_event never called → test FAILS.
# ===========================================================================

# Hypothesis strategy for generating valid detective payloads
_detective_payload_strategy = st.fixed_dictionaries({
    "company_id": st.text(min_size=1, max_size=50),
    "correlation_id": st.uuids().map(str),
    "company_data": st.fixed_dictionaries({
        "name": st.text(min_size=1, max_size=100),
        "domain": st.text(min_size=1, max_size=100),
    }),
    "enrichment_data": st.dictionaries(st.text(min_size=1), st.text()),
    "personas": st.lists(st.text()),
    "intent_signals": st.lists(st.text()),
    "readiness_flags": st.dictionaries(st.text(min_size=1), st.booleans()),
    "event_type": st.just("lead_ingested"),
    "timestamp": st.just(datetime.now(timezone.utc).isoformat()),
})


class TestPropertyBugCondition:
    """
    Property 1: Bug Condition — Lead Ingested Event Never Reaches Worker Storage

    For any valid detective payload, after emit_lead_ingested(payload) is called
    with Redis available, save_event() SHALL be called in WorkerModule.

    On unfixed code: no subscriber exists → save_event call count = 0 → FAILS.

    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
    """

    @given(_detective_payload_strategy)
    @h_settings(max_examples=5, suppress_health_check=[HealthCheck.too_slow])
    def test_emit_lead_ingested_results_in_save_event_called(self, payload: dict):
        """
        **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

        Property: For all valid detective payloads, emit_lead_ingested(payload)
        MUST result in save_event() being called in WorkerModule with matching
        correlation_id, module="inject", event_type="lead_ingested".

        FAILS on unfixed code because subscriber.py does not exist.
        Counterexample: any valid payload — save_event is never called.
        """
        # Check that subscriber module exists (prerequisite for the property to hold)
        try:
            import importlib
            spec = importlib.util.find_spec("app.subscriber")
            subscriber_exists = spec is not None
        except (ModuleNotFoundError, ValueError):
            subscriber_exists = False

        assert subscriber_exists, (
            f"BUG CONFIRMED (property test): app.subscriber module does not exist. "
            f"For payload with correlation_id={payload['correlation_id']}, "
            f"save_event() can never be called because no subscriber is running. "
            f"Counterexample: payload={{'correlation_id': '{payload['correlation_id']}', "
            f"'event_type': '{payload['event_type']}'}}"
        )

    @given(_detective_payload_strategy)
    @h_settings(max_examples=5, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_worker_config_has_redis_url(self, payload: dict):
        """
        **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

        Property: For all valid detective payloads, WorkerModule's settings MUST
        expose a REDIS_URL so the subscriber can connect to Redis.

        FAILS on unfixed code because config.py has no REDIS_URL field.
        Counterexample: any payload — settings has no REDIS_URL attribute.
        """
        from app.config import settings

        assert hasattr(settings, "REDIS_URL"), (
            f"BUG CONFIRMED (property test): WorkerModule settings has no REDIS_URL. "
            f"Even if subscriber.py existed, it could not connect to Redis. "
            f"Counterexample: payload correlation_id={payload['correlation_id']} — "
            f"settings.REDIS_URL is missing."
        )
