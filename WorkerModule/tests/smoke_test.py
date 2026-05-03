import json
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, cast

BASE_URL = "http://localhost:8000"


@dataclass
class CheckResult:
    name: str
    ok: bool
    status: Any
    detail: str = ""


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[Any, Any]:
    url = f"{BASE_URL}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            payload: Any = json.loads(raw) if raw else None
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload
    except Exception as exc:  # noqa: BLE001
        return None, {"error": str(exc)}


def main() -> None:
    results: list[CheckResult] = []

    status, body = _request("GET", "/health")
    results.append(CheckResult("GET /health", status == 200, status, str(body)))

    status, body = _request("GET", "/ready")
    results.append(CheckResult("GET /ready", status in (200, 503), status, str(body)))

    correlation_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    event: dict[str, Any] = {
        "event_id": event_id,
        "correlation_id": correlation_id,
        "module": "inject",
        "event_type": "lead_ingested",
        "timestamp": "2026-04-01T00:00:00+00:00",
        "payload": {},
        "metadata": {},
    }

    status, body = _request("POST", "/v1/events/ingest", event)
    ok = (
        status == 202
        and isinstance(body, dict)
        and "schema_warnings" in body
        and isinstance(body.get("schema_warnings"), list)
        and len(cast(list[Any], body.get("schema_warnings"))) >= 1
    )
    results.append(CheckResult("POST /v1/events/ingest", ok, status, str(body)))

    unknown_event = dict(event)
    unknown_event["event_id"] = str(uuid.uuid4())
    unknown_event["event_type"] = "custom_event_type"
    status, body = _request("POST", "/v1/events/ingest", unknown_event)
    ok = (
        status == 202
        and isinstance(body, dict)
        and "schema_warnings" in body
        and isinstance(body.get("schema_warnings"), list)
        and any("not in canonical schema registry" in str(w) for w in cast(list[Any], body.get("schema_warnings")))
    )
    results.append(CheckResult("POST /v1/events/ingest (unknown event_type)", ok, status, str(body)))

    message_sent_event: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "correlation_id": correlation_id,
        "module": "writer",
        "event_type": "message_sent",
        "timestamp": "2026-04-01T00:00:01+00:00",
        "payload": {"channel": "email"},
        "metadata": {},
    }
    status, body = _request("POST", "/v1/events/ingest", message_sent_event)
    results.append(CheckResult("POST /v1/events/ingest (message_sent)", status == 202, status, str(body)))

    invalid_event = dict(event)
    invalid_event["event_id"] = str(uuid.uuid4())
    invalid_event["module"] = "invalid-module"
    status, body = _request("POST", "/v1/events/ingest", invalid_event)
    ok = (
        status == 400
        and isinstance(body, dict)
        and isinstance(body.get("detail"), dict)
        and body["detail"].get("code") == "INVALID_MODULE"
    )
    results.append(CheckResult("POST /v1/events/ingest (invalid module)", ok, status, str(body)))

    # Phase 3: Burst ingest behavior (accepts 202 and tolerates 429 backpressure)
    burst_statuses: list[Any] = []
    for i in range(20):
        burst_event = {
            "event_id": str(uuid.uuid4()),
            "correlation_id": correlation_id,
            "module": "inject",
            "event_type": "lead_ingested",
            "timestamp": f"2026-04-01T00:00:{10 + i:02d}+00:00",
            "payload": {"idx": i},
            "metadata": {},
        }
        b_status, _ = _request("POST", "/v1/events/ingest", burst_event)
        burst_statuses.append(b_status)
    ok = all(s in (202, 429) for s in burst_statuses) and any(s == 202 for s in burst_statuses)
    results.append(CheckResult("POST /v1/events/ingest burst", ok, burst_statuses.count(202), str(burst_statuses)))

    status, body = _request("GET", f"/v1/events?correlation_id={correlation_id}&limit=5")
    ok = status == 200 and isinstance(body, dict) and "items" in body
    results.append(CheckResult("GET /v1/events", ok, status, str(body)))

    status, body = _request("GET", f"/v1/events/trace/{correlation_id}")
    ok = status == 200 and isinstance(body, list)
    results.append(CheckResult("GET /v1/events/trace/{correlation_id}", ok, status, str(body)))

    # Test Phase 1: Outcome linking
    outcome_id = str(uuid.uuid4())
    outcome: dict[str, Any] = {
        "outcome_id": outcome_id,
        "correlation_id": correlation_id,
        "linked_event_id": event_id,
        "outcome_type": "reply",
        "value": {"sentiment": "positive"},
        "timestamp": "2026-04-01T00:01:00+00:00",
    }
    status, body = _request("POST", "/v1/outcomes/link", outcome)
    results.append(CheckResult("POST /v1/outcomes/link", status == 202, status, str(body)))

    # Test Phase 1: Metrics endpoint
    status, body = _request("GET", f"/v1/metrics?correlation_id={correlation_id}")
    ok = status == 200 and isinstance(body, dict) and "reply_rate" in body
    results.append(CheckResult("GET /v1/metrics", ok, status, str(body)))

    # Test Phase 1: KPIs endpoint
    status, body = _request("GET", "/v1/kpis")
    ok = status == 200 and isinstance(body, dict) and "average_reply_rate" in body
    results.append(CheckResult("GET /v1/kpis", ok, status, str(body)))

    # Test Phase 1: Integrity audit endpoint
    status, body = _request("GET", f"/v1/integrity/audit?correlation_id={correlation_id}")
    ok = status == 200 and isinstance(body, dict) and "is_healthy" in body
    results.append(CheckResult("GET /v1/integrity/audit", ok, status, str(body)))

    # Phase 3: Alert lifecycle endpoints
    status, body = _request("GET", f"/v1/alerts?correlation_id={correlation_id}&status=open&limit=10")
    ok = status == 200 and isinstance(body, dict) and "items" in body
    results.append(CheckResult("GET /v1/alerts", ok, status, str(body)))

    alert_id = None
    if ok and isinstance(body, dict) and body.get("items"):
        alert_id = body["items"][0].get("alert_id")

    if alert_id:
        status, body = _request("POST", f"/v1/alerts/{alert_id}/acknowledge")
        ok = status == 200 and isinstance(body, dict) and body.get("status") == "acknowledged"
        results.append(CheckResult("POST /v1/alerts/{alert_id}/acknowledge", ok, status, str(body)))

        status, body = _request("POST", f"/v1/alerts/{alert_id}/resolve")
        ok = status == 200 and isinstance(body, dict) and body.get("status") == "resolved"
        results.append(CheckResult("POST /v1/alerts/{alert_id}/resolve", ok, status, str(body)))

        status, body = _request("DELETE", f"/v1/alerts/{alert_id}")
        ok = status == 200 and isinstance(body, dict) and body.get("archived") is True
        results.append(CheckResult("DELETE /v1/alerts/{alert_id}", ok, status, str(body)))
    else:
        results.append(CheckResult("POST /v1/alerts/{alert_id}/acknowledge", True, "SKIPPED", "No alert created"))
        results.append(CheckResult("POST /v1/alerts/{alert_id}/resolve", True, "SKIPPED", "No alert created"))
        results.append(CheckResult("DELETE /v1/alerts/{alert_id}", True, "SKIPPED", "No alert created"))

    # Test Phase 2: Outcome list endpoint
    status, body = _request("GET", f"/v1/outcomes?correlation_id={correlation_id}&limit=10")
    ok = status == 200 and isinstance(body, dict) and "items" in body and "total" in body
    results.append(CheckResult("GET /v1/outcomes", ok, status, str(body)))

    # Test Phase 2: Single outcome endpoint
    status, body = _request("GET", f"/v1/outcomes/{outcome_id}")
    ok = status == 200 and isinstance(body, dict) and body.get("outcome_id") == outcome_id
    results.append(CheckResult("GET /v1/outcomes/{outcome_id}", ok, status, str(body)))

    # Test Phase 2: Event-outcome correlation endpoint
    status, body = _request("GET", f"/v1/events_outcomes/{correlation_id}")
    ok = status == 200 and isinstance(body, dict) and "events_with_outcomes" in body
    results.append(CheckResult("GET /v1/events_outcomes/{correlation_id}", ok, status, str(body)))

    # Phase 4: Graph trace endpoint (Neo4j or fallback payload)
    status, body = _request("GET", f"/v1/trace/correlation/{correlation_id}")
    ok = status == 200 and isinstance(body, dict) and "nodes" in body and "relationships" in body
    results.append(CheckResult("GET /v1/trace/correlation/{correlation_id}", ok, status, str(body)))

    # Phase 4: Graph checkpoint/parity endpoint
    status, body = _request("GET", f"/v1/trace/correlation/{correlation_id}/checkpoint")
    ok = status == 200 and isinstance(body, dict) and "checkpoint" in body and "parity" in body
    results.append(CheckResult("GET /v1/trace/correlation/{correlation_id}/checkpoint", ok, status, str(body)))

    # Phase 5: Optimization dry-run and recommendation history/approval
    status, body = _request("POST", "/v1/optimization/run", {"correlation_id": correlation_id, "max_change_pct": 10.0, "cooldown_hours": 24})
    ok = (
        status == 200
        and isinstance(body, dict)
        and "items" in body
        and "run_id" in body
        and body.get("created_count", 0) >= 1
    )
    results.append(CheckResult("POST /v1/optimization/run", ok, status, str(body)))

    recommendation_id = None
    reject_recommendation_id = None
    if ok and isinstance(body, dict) and body.get("items"):
        recommendation_id = body["items"][0].get("recommendation_id")

    status, body = _request("GET", "/v1/optimization/recommendations?limit=10")
    ok = status == 200 and isinstance(body, dict) and "items" in body and "total" in body
    results.append(CheckResult("GET /v1/optimization/recommendations", ok, status, str(body)))

    status, body = _request("POST", "/v1/optimization/run", {"correlation_id": correlation_id, "max_change_pct": 10.0, "cooldown_hours": 24})
    ok = (
        status == 200
        and isinstance(body, dict)
        and body.get("created_count") == 0
        and body.get("skipped_due_cooldown", 0) >= 1
    )
    results.append(CheckResult("POST /v1/optimization/run (cooldown)", ok, status, str(body)))

    status, body = _request("POST", "/v1/optimization/run", {"correlation_id": correlation_id, "max_change_pct": 10.0, "cooldown_hours": 0})
    ok = (
        status == 200
        and isinstance(body, dict)
        and body.get("created_count", 0) >= 1
    )
    results.append(CheckResult("POST /v1/optimization/run (cooldown bypass)", ok, status, str(body)))

    if ok and isinstance(body, dict) and body.get("items"):
        reject_recommendation_id = body["items"][0].get("recommendation_id")

    if recommendation_id:
        status, body = _request(
            "POST",
            f"/v1/optimization/recommendations/{recommendation_id}/approve",
            {"approved_by": "smoke_test"},
        )
        ok = status == 200 and isinstance(body, dict) and body.get("status") == "approved"
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/approve", ok, status, str(body)))
        recommendation_type = body.get("recommendation_type") if isinstance(body, dict) else None

        status, body = _request(
            "POST",
            f"/v1/optimization/recommendations/{recommendation_id}/execute",
            {"apply": True, "acted_by": "smoke_test", "override_apply_enabled": False},
        )
        ok = (
            status == 409
            and isinstance(body, dict)
            and isinstance(body.get("detail"), dict)
            and body["detail"].get("code") == "GLOBAL_KILL_SWITCH"
        )
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (global switch blocked)", ok, status, str(body)))

        if recommendation_type:
            status, body = _request(
                "POST",
                f"/v1/optimization/recommendations/{recommendation_id}/execute",
                {
                    "apply": True,
                    "acted_by": "smoke_test",
                    "override_disabled_recommendation_types": [recommendation_type],
                },
            )
            ok = (
                status == 409
                and isinstance(body, dict)
                and isinstance(body.get("detail"), dict)
                and body["detail"].get("code") == "TYPE_KILL_SWITCH"
            )
            results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (type switch blocked)", ok, status, str(body)))
        else:
            results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (type switch blocked)", True, "SKIPPED", "No recommendation_type on approved payload"))

        status, body = _request(
            "POST",
            f"/v1/optimization/recommendations/{recommendation_id}/execute",
            {"apply": True, "acted_by": "smoke_test", "policy_max_change_pct": 1.0},
        )
        ok = (
            status == 422
            and isinstance(body, dict)
            and isinstance(body.get("detail"), dict)
            and body["detail"].get("code") == "APPLY_POLICY_BLOCKED"
        )
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (apply policy blocked)", ok, status, str(body)))

        status, body = _request(
            "POST",
            f"/v1/optimization/recommendations/{recommendation_id}/execute",
            {"acted_by": "smoke_test"},
        )
        ok = (
            status == 200
            and isinstance(body, dict)
            and body.get("mode") == "dry_run"
            and body.get("applied") is False
        )
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (dry_run)", ok, status, str(body)))

        status, body = _request(
            "POST",
            f"/v1/optimization/recommendations/{recommendation_id}/execute",
            {"apply": True, "acted_by": "smoke_test"},
        )
        ok = (
            status == 200
            and isinstance(body, dict)
            and body.get("mode") == "apply"
            and body.get("applied") is True
            and isinstance(body.get("recommendation"), dict)
            and body["recommendation"].get("status") == "applied"
        )
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (apply)", ok, status, str(body)))

        status, body = _request(
            "POST",
            f"/v1/optimization/recommendations/{recommendation_id}/execute",
            {"apply": True, "acted_by": "smoke_test"},
        )
        ok = status == 200 and isinstance(body, dict) and body.get("applied") is True
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (apply idempotent)", ok, status, str(body)))

        status, body = _request(
            "POST",
            f"/v1/optimization/recommendations/{recommendation_id}/rollback",
            {"acted_by": "smoke_test"},
        )
        ok = status == 200 and isinstance(body, dict) and body.get("status") == "rolled_back"
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/rollback", ok, status, str(body)))

        status, body = _request(
            "POST",
            f"/v1/optimization/recommendations/{recommendation_id}/rollback",
            {"acted_by": "smoke_test"},
        )
        ok = status == 200 and isinstance(body, dict) and body.get("status") == "rolled_back"
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/rollback (idempotent)", ok, status, str(body)))

        if reject_recommendation_id:
            status, body = _request(
                "POST",
                f"/v1/optimization/recommendations/{reject_recommendation_id}/reject",
                {"acted_by": "smoke_test"},
            )
            ok = status == 200 and isinstance(body, dict) and body.get("status") == "rejected"
            results.append(CheckResult("POST /v1/optimization/recommendations/{id}/reject", ok, status, str(body)))

            status, body = _request(
                "POST",
                f"/v1/optimization/recommendations/{reject_recommendation_id}/reject",
                {"acted_by": "smoke_test"},
            )
            ok = status == 200 and isinstance(body, dict) and body.get("status") == "rejected"
            results.append(CheckResult("POST /v1/optimization/recommendations/{id}/reject (idempotent)", ok, status, str(body)))

            status, body = _request(
                "POST",
                f"/v1/optimization/recommendations/{reject_recommendation_id}/execute",
                {"apply": True, "acted_by": "smoke_test"},
            )
            ok = status == 409
            results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (apply blocked)", ok, status, str(body)))
        else:
            results.append(CheckResult("POST /v1/optimization/recommendations/{id}/reject", True, "SKIPPED", "No recommendation generated for rejection"))
            results.append(CheckResult("POST /v1/optimization/recommendations/{id}/reject (idempotent)", True, "SKIPPED", "No recommendation generated for rejection"))
            results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (apply blocked)", True, "SKIPPED", "No recommendation generated for rejection"))

        status, body = _request(
            "GET",
            f"/v1/optimization/audit?recommendation_id={recommendation_id}&limit=10",
        )
        ok = (
            status == 200
            and isinstance(body, dict)
            and "items" in body
            and body.get("total", 0) >= 1
        )
        results.append(CheckResult("GET /v1/optimization/audit", ok, status, str(body)))

        status, body = _request(
            "GET",
            "/v1/optimization/audit?approved_by=smoke_test&start_time=2026-01-01T00:00:00Z&end_time=2030-01-01T00:00:00Z&limit=1",
        )
        ok = (
            status == 200
            and isinstance(body, dict)
            and "items" in body
            and "next_cursor" in body
            and "prev_cursor" in body
        )
        results.append(CheckResult("GET /v1/optimization/audit (filters+cursor)", ok, status, str(body)))

        if ok and isinstance(body, dict) and body.get("next_cursor") is not None:
            cursor = body.get("next_cursor")
            status, body = _request(
                "GET",
                f"/v1/optimization/audit?approved_by=smoke_test&limit=1&cursor={cursor}",
            )
            ok = status == 200 and isinstance(body, dict) and "items" in body
            results.append(CheckResult("GET /v1/optimization/audit (next_cursor)", ok, status, str(body)))
        else:
            results.append(CheckResult("GET /v1/optimization/audit (next_cursor)", True, "SKIPPED", "No next_cursor"))

        status, body = _request(
            "GET",
            "/v1/optimization/audit?event_type=optimization_recommendation_rolled_back&status=rolled_back&approved_by=smoke_test&limit=10",
        )
        ok = (
            status == 200
            and isinstance(body, dict)
            and "items" in body
            and all(item.get("event_type") == "optimization_recommendation_rolled_back" for item in body.get("items", []))
        )
        results.append(CheckResult("GET /v1/optimization/audit (event_type+status)", ok, status, str(body)))

        status, body = _request(
            "GET",
            "/v1/optimization/audit?event_type=optimization_recommendation_rejected&status=rejected&approved_by=smoke_test&limit=10",
        )
        ok = status == 200 and isinstance(body, dict) and "items" in body
        results.append(CheckResult("GET /v1/optimization/audit (rejected filter)", ok, status, str(body)))

        status, body = _request(
            "GET",
            f"/v1/optimization/audit?recommendation_id={recommendation_id}&event_type=optimization_apply_allowed&limit=10",
        )
        ok = status == 200 and isinstance(body, dict) and body.get("total", 0) >= 1
        results.append(CheckResult("GET /v1/optimization/audit (apply allowed events)", ok, status, str(body)))

        status, body = _request(
            "GET",
            f"/v1/optimization/audit?recommendation_id={recommendation_id}&event_type=optimization_apply_blocked&limit=10",
        )
        ok = status == 200 and isinstance(body, dict) and body.get("total", 0) >= 1
        results.append(CheckResult("GET /v1/optimization/audit (apply blocked events)", ok, status, str(body)))

        status, body = _request(
            "GET",
            f"/v1/optimization/audit?recommendation_id={recommendation_id}&event_type=optimization_recommendation_applied&status=applied&limit=10",
        )
        ok = status == 200 and isinstance(body, dict) and body.get("total", 0) >= 1
        results.append(CheckResult("GET /v1/optimization/audit (applied consistency)", ok, status, str(body)))

        status, body = _request(
            "GET",
            f"/v1/optimization/audit?recommendation_id={recommendation_id}&event_type=optimization_recommendation_rolled_back&status=rolled_back&limit=10",
        )
        ok = status == 200 and isinstance(body, dict) and body.get("total", 0) >= 1
        results.append(CheckResult("GET /v1/optimization/audit (rollback consistency)", ok, status, str(body)))
    else:
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/approve", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (global switch blocked)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (type switch blocked)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (apply policy blocked)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (dry_run)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (apply)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (apply idempotent)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/rollback", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/rollback (idempotent)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/reject", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/reject (idempotent)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("POST /v1/optimization/recommendations/{id}/execute (apply blocked)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("GET /v1/optimization/audit", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("GET /v1/optimization/audit (filters+cursor)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("GET /v1/optimization/audit (next_cursor)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("GET /v1/optimization/audit (event_type+status)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("GET /v1/optimization/audit (rejected filter)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("GET /v1/optimization/audit (apply allowed events)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("GET /v1/optimization/audit (apply blocked events)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("GET /v1/optimization/audit (applied consistency)", True, "SKIPPED", "No recommendation generated"))
        results.append(CheckResult("GET /v1/optimization/audit (rollback consistency)", True, "SKIPPED", "No recommendation generated"))

    status, body = _request("POST", "/v1/optimization/run", {"correlation_id": correlation_id, "max_change_pct": 10.0, "cooldown_hours": -1})
    ok = status == 422
    results.append(CheckResult("POST /v1/optimization/run (invalid cooldown)", ok, status, str(body)))

    status, body = _request(
        "POST",
        "/v1/agent/runs",
        {"objective": "smoke test agent run", "max_steps": 20},
    )
    body_map = cast(dict[str, Any], body) if isinstance(body, dict) else None
    run_id = body_map.get("run_id") if body_map else None
    # 200 is expected success; 503 is tolerated when agent service is unavailable.
    results.append(CheckResult("POST /v1/agent/runs", status in (200, 503), status, str(body)))

    if run_id:
        status, body = _request("GET", f"/v1/agent/runs/{run_id}")
        results.append(CheckResult("GET /v1/agent/runs/{run_id}", status == 200, status, str(body)))
        
        eval_status, eval_body = _request("GET", f"/v1/agent/runs/{run_id}/evaluation")
        results.append(CheckResult("GET /v1/agent/runs/{run_id}/evaluation", eval_status == 200, eval_status, str(eval_body)))
    else:
        results.append(CheckResult("GET /v1/agent/runs/{run_id}", True, "SKIPPED", "No run_id returned"))
        results.append(CheckResult("GET /v1/agent/runs/{run_id}/evaluation", True, "SKIPPED", "No run_id returned"))

    print("SMOKE TEST SUMMARY")
    passed = 0
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"- {marker} | {result.name} | status={result.status}")
        if result.ok:
            passed += 1

    print(f"TOTAL: {passed}/{len(results)} PASS")

    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
