"""
Graph sync pipeline for WorkerModule.

Projects Postgres events and outcomes into the graph store.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .graph import (
    build_correlation_node,
    build_event_node,
    build_lead_node,
    build_outcome_node,
    event_edge_specs,
    outcome_edge_specs,
)
from .storage import (
    get_events_by_correlation_id,
    get_outcomes_by_correlation_id,
    record_graph_sync_checkpoint,
    verify_graph_parity,
)

logger = logging.getLogger(__name__)


async def project_correlation_to_graph(db_pool, graph_adapter, correlation_id: str) -> Dict[str, int]:
    """Project a correlation's events/outcomes into graph nodes and edges."""
    events = await get_events_by_correlation_id(db_pool, correlation_id)
    outcomes = await get_outcomes_by_correlation_id(db_pool, correlation_id)

    created_nodes = 0
    created_edges = 0

    await graph_adapter.add_node("GraphEntity", build_correlation_node(correlation_id))
    created_nodes += 1

    previous_event_id: str | None = None
    for event in events:
        await graph_adapter.add_node("GraphEntity", build_event_node(event))
        created_nodes += 1

        for edge_spec in event_edge_specs(event):
            await graph_adapter.add_edge(**edge_spec)
            created_edges += 1

        if previous_event_id:
            await graph_adapter.add_edge(
                from_node=previous_event_id,
                to_node=str(event["event_id"]),
                relation_type="NEXT_EVENT",
                properties={"correlation_id": correlation_id},
            )
            created_edges += 1
        previous_event_id = str(event["event_id"])

        for lead_id in extract_lead_ids_from_event(event):
            await graph_adapter.add_node("GraphEntity", build_lead_node(lead_id, {"correlation_id": correlation_id}))
            created_nodes += 1
            await graph_adapter.add_edge(
                from_node=correlation_id,
                to_node=lead_id,
                relation_type="TRACKS_LEAD",
                properties={"correlation_id": correlation_id, "lead_id": lead_id},
            )
            created_edges += 1

    for outcome in outcomes:
        await graph_adapter.add_node("GraphEntity", build_outcome_node(outcome))
        created_nodes += 1
        for edge_spec in outcome_edge_specs(outcome):
            await graph_adapter.add_edge(**edge_spec)
            created_edges += 1

    last_event_id = str(events[-1]["event_id"]) if events else None
    last_event_timestamp = None
    if events and events[-1].get("timestamp"):
        timestamp_value = events[-1]["timestamp"]
        last_event_timestamp = (
            timestamp_value.isoformat() if hasattr(timestamp_value, "isoformat") else str(timestamp_value)
        )
    await record_graph_sync_checkpoint(
        db_pool,
        correlation_id=correlation_id,
        last_event_id=last_event_id,
        last_event_timestamp=last_event_timestamp,
        projected_nodes=created_nodes,
        projected_edges=created_edges,
        sync_status="synced",
    )

    return {"nodes": created_nodes, "edges": created_edges}


async def build_correlation_trace_payload(db_pool, correlation_id: str) -> Dict[str, Any]:
    """Builds a graph-like trace payload directly from Postgres rows.

    Used as a safe fallback when Neo4j is unavailable.
    """
    events = await get_events_by_correlation_id(db_pool, correlation_id)
    outcomes = await get_outcomes_by_correlation_id(db_pool, correlation_id)

    nodes: List[Dict[str, Any]] = [build_correlation_node(correlation_id)]
    relationships: List[Dict[str, Any]] = []

    previous_event_id: str | None = None
    for event in events:
        nodes.append(build_event_node(event))
        relationships.append(
            {
                "from_node": correlation_id,
                "to_node": str(event["event_id"]),
                "relation_type": "HAS_EVENT",
                "properties": {"event_type": event.get("event_type")},
            }
        )
        if previous_event_id:
            relationships.append(
                {
                    "from_node": previous_event_id,
                    "to_node": str(event["event_id"]),
                    "relation_type": "NEXT_EVENT",
                    "properties": {"correlation_id": correlation_id},
                }
            )
        previous_event_id = str(event["event_id"])

        for lead_id in extract_lead_ids_from_event(event):
            nodes.append(build_lead_node(lead_id, {"correlation_id": correlation_id}))
            relationships.append(
                {
                    "from_node": str(event["event_id"]),
                    "to_node": lead_id,
                    "relation_type": "TARGETS_LEAD",
                    "properties": {"lead_id": lead_id},
                }
            )

    for outcome in outcomes:
        nodes.append(build_outcome_node(outcome))
        relationships.append(
            {
                "from_node": str(outcome["linked_event_id"]),
                "to_node": str(outcome["outcome_id"]),
                "relation_type": "RESULTED_IN",
                "properties": {"outcome_type": outcome.get("outcome_type")},
            }
        )

    return {"nodes": nodes, "relationships": relationships}


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


async def sync_and_verify_correlation_graph(db_pool, graph_adapter, correlation_id: str) -> Dict[str, Any]:
    """Projects a correlation and returns parity information."""
    projected = await project_correlation_to_graph(db_pool, graph_adapter, correlation_id)
    parity = await verify_graph_parity(db_pool, graph_adapter, correlation_id)
    return {"projected": projected, "parity": parity}