"""
Graph projection helpers for WorkerModule.

These helpers convert Postgres event/outcome rows into graph nodes and edges.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def build_correlation_node(correlation_id: str) -> Dict[str, Any]:
    return {
        "node_id": correlation_id,
        "correlation_id": correlation_id,
        "entity_type": "correlation",
    }


def build_event_node(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "node_id": str(event["event_id"]),
        "correlation_id": str(event["correlation_id"]),
        "entity_type": "event",
        "event_type": event.get("event_type"),
        "module": event.get("module"),
        "timestamp": event.get("timestamp").isoformat() if hasattr(event.get("timestamp"), "isoformat") else event.get("timestamp"),
        "payload": event.get("payload", {}),
        "metadata": event.get("metadata", {}),
    }


def build_outcome_node(outcome: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "node_id": str(outcome["outcome_id"]),
        "correlation_id": str(outcome["correlation_id"]),
        "entity_type": "outcome",
        "outcome_type": outcome.get("outcome_type"),
        "linked_event_id": str(outcome.get("linked_event_id")),
        "timestamp": outcome.get("timestamp").isoformat() if hasattr(outcome.get("timestamp"), "isoformat") else outcome.get("timestamp"),
        "value": outcome.get("value", {}),
    }


def build_lead_node(lead_id: str, properties: Dict[str, Any] | None = None) -> Dict[str, Any]:
    node = {
        "node_id": lead_id,
        "lead_id": lead_id,
        "entity_type": "lead",
    }
    if properties:
        node.update(properties)
    return node


def extract_lead_ids_from_event(event: Dict[str, Any]) -> List[str]:
    lead_ids: List[str] = []
    payload = event.get("payload") or {}
    metadata = event.get("metadata") or {}
    for container in (payload, metadata):
        if isinstance(container, dict):
            candidate = container.get("lead_id") or container.get("leadId")
            if candidate:
                lead_ids.append(str(candidate))
    return lead_ids


def event_edge_specs(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = [
        {
            "from_node": str(event["correlation_id"]),
            "to_node": str(event["event_id"]),
            "relation_type": "HAS_EVENT",
            "properties": {"event_type": event.get("event_type")},
        }
    ]

    for lead_id in extract_lead_ids_from_event(event):
        specs.append(
            {
                "from_node": str(event["event_id"]),
                "to_node": lead_id,
                "relation_type": "TARGETS_LEAD",
                "properties": {"lead_id": lead_id},
            }
        )

    return specs


def outcome_edge_specs(outcome: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "from_node": str(outcome["linked_event_id"]),
            "to_node": str(outcome["outcome_id"]),
            "relation_type": "RESULTED_IN",
            "properties": {"outcome_type": outcome.get("outcome_type")},
        }
    ]


def lead_event_edge_specs(lead_id: str, correlation_id: str) -> List[Dict[str, Any]]:
    return [
        {
            "from_node": correlation_id,
            "to_node": lead_id,
            "relation_type": "TRACKS_LEAD",
            "properties": {"correlation_id": correlation_id, "lead_id": lead_id},
        }
    ]