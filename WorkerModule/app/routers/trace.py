from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid
import logging

from ..modules.worker.storage import (
    get_events_by_correlation_id,
    get_outcomes_by_correlation_id,
    find_orphaned_outcomes,
    detect_duplicates,
    verify_event_sequence,
    record_integrity_alert,
    get_events_for_metrics,
    get_outcome_statistics,
    list_outcomes,
    get_outcome_by_id,
    correlate_events_to_outcomes,
    get_total_correlations,
    list_integrity_alerts,
    get_integrity_alert,
    update_integrity_alert_status,
    archive_integrity_alert,
    find_missing_expected_events,
    detect_correlation_chain_breaks,
    get_graph_sync_checkpoint,
    verify_graph_parity,
    create_optimization_recommendation,
    list_optimization_recommendations,
    get_optimization_recommendation,
    approve_optimization_recommendation,
    apply_optimization_recommendation,
    reject_optimization_recommendation,
    rollback_optimization_recommendation,
    is_recommendation_type_in_cooldown,
    list_optimization_audit_events,
    save_event,
)
from ..adapters.graph import get_db_pool, get_graph_adapter
from ..modules.worker.sync import sync_and_verify_correlation_graph, build_correlation_trace_payload
from ..modules.worker.optimization import build_dry_run_recommendations, evaluate_apply_policy
from ..config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# ============ REQUEST/RESPONSE MODELS ============

class MetricsResponse(BaseModel):
    """KPI metrics for a correlation or system-wide."""
    correlation_id: Optional[str] = None
    reply_rate: float = 0.0  # (count of reply_received outcomes) / (count of message_sent events)
    conversion_rate: float = 0.0  # (count of conversion outcomes) / (count of reply_received outcomes)
    event_counts: Dict[str, int]  # grouped by event_type
    outcome_counts: Dict[str, int]  # grouped by outcome_type


class KPIResponse(BaseModel):
    """High-level KPI summary."""
    average_reply_rate: float
    average_conversion_rate: float
    total_events_ingested: int
    total_correlations: int
    top_event_types: Dict[str, int]


class IntegrityIssue(BaseModel):
    """Single integrity issue."""
    issue_type: str  # e.g., "orphaned_outcome", "missing_event", "duplicate_event"
    message: str
    details: Dict[str, Any]


class IntegrityAuditResponse(BaseModel):
    """Result of integrity audit for a correlation."""
    correlation_id: str
    is_healthy: bool
    issues: List[IntegrityIssue]
    audit_timestamp: str


class OutcomeListResponse(BaseModel):
    items: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


class EventOutcomeMapResponse(BaseModel):
    correlation_id: str
    events_with_outcomes: Dict[str, Any]
    outcome_summary: Dict[str, int]


class IntegrityAlertItem(BaseModel):
    alert_id: str
    correlation_id: str
    issue_type: str
    message: str
    details: Dict[str, Any] | None = None
    severity: str
    status: str
    is_resolved: bool
    acknowledged_at: Optional[str] = None
    resolved_at: Optional[str] = None
    timestamp: str
    updated_at: Optional[str] = None
    created_at: Optional[str] = None


class IntegrityAlertListResponse(BaseModel):
    items: List[IntegrityAlertItem]
    total: int
    limit: int
    offset: int


class GraphTraceResponse(BaseModel):
    nodes: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    projected: Dict[str, int] | None = None
    parity: Dict[str, Any] | None = None


class GraphCheckpointResponse(BaseModel):
    checkpoint: Dict[str, Any] | None
    parity: Dict[str, Any]


class RecommendationRunRequest(BaseModel):
    correlation_id: Optional[str] = None
    max_change_pct: float = Field(default=10.0, gt=0, le=50)
    cooldown_hours: int = Field(default=24, ge=0, le=720)


class RecommendationItem(BaseModel):
    recommendation_id: str
    correlation_id: Optional[str] = None
    recommendation_type: str
    summary: str
    payload: Dict[str, Any]
    confidence: float
    status: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[str] = None
    applied_by: Optional[str] = None
    applied_at: Optional[str] = None
    rolled_back_by: Optional[str] = None
    rolled_back_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RecommendationRunResponse(BaseModel):
    run_id: str
    dry_run: bool = True
    created_count: int
    skipped_due_cooldown: int = 0
    items: List[RecommendationItem]
    generated_at: str


class RecommendationHistoryResponse(BaseModel):
    items: List[RecommendationItem]
    total: int
    limit: int
    offset: int


class OptimizationAuditEvent(BaseModel):
    event_id: str
    correlation_id: str
    module: str
    event_type: str
    timestamp: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class OptimizationAuditResponse(BaseModel):
    items: List[OptimizationAuditEvent]
    total: int
    limit: int
    offset: int
    next_cursor: Optional[str] = None
    prev_cursor: Optional[str] = None


class RecommendationApproveRequest(BaseModel):
    approved_by: Optional[str] = None


class RecommendationActionRequest(BaseModel):
    acted_by: Optional[str] = None


class RecommendationExecuteRequest(BaseModel):
    apply: bool = False
    acted_by: Optional[str] = None
    policy_max_change_pct: Optional[float] = Field(default=None, gt=0, le=50)
    override_apply_enabled: Optional[bool] = None
    override_disabled_recommendation_types: Optional[List[str]] = None


class RecommendationExecuteResponse(BaseModel):
    recommendation: RecommendationItem
    mode: str
    applied: bool


def _resolve_audit_correlation_uuid(correlation_raw: Optional[str], recommendation_id: str) -> uuid.UUID:
    if correlation_raw:
        try:
            return uuid.UUID(str(correlation_raw))
        except ValueError:
            pass
    return uuid.uuid5(uuid.NAMESPACE_URL, f"recommendation:{recommendation_id}")


async def _emit_recommendation_audit_event(
    db_pool,
    recommendation_id: str,
    item: Dict[str, Any],
    event_type: str,
    actor_key: str,
    actor_value: Optional[str] = None,
    payload_extra: Optional[Dict[str, Any]] = None,
    metadata_extra: Optional[Dict[str, Any]] = None,
):
    correlation_uuid = _resolve_audit_correlation_uuid(item.get("correlation_id"), recommendation_id)
    payload = {
        "recommendation_id": recommendation_id,
        "recommendation_type": item.get("recommendation_type"),
        "status": item.get("status"),
    }
    if payload_extra:
        payload.update(payload_extra)

    metadata = {
        actor_key: actor_value if actor_value is not None else item.get(actor_key),
        "source": "optimization_api",
    }
    if metadata_extra:
        metadata.update(metadata_extra)

    await save_event(
        db_pool,
        {
            "event_id": uuid.uuid4(),
            "correlation_id": correlation_uuid,
            "module": "worker",
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc),
            "payload": payload,
            "metadata": metadata,
        },
    )


# ============ TRACE AND METRICS ENDPOINTS ============

@router.get("/v1/events/trace/{correlation_id}", response_model=List[Dict[str, Any]])
async def trace_events(correlation_id: str, db_pool=Depends(get_db_pool)):
    """
    Retrieves all events associated with a specific correlation ID to reconstruct a timeline.
    """
    try:
        events = await get_events_by_correlation_id(db_pool, correlation_id)
        if not events:
            raise HTTPException(status_code=404, detail="No events found for this correlation ID")
        return events
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve trace for {correlation_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/metrics", response_model=MetricsResponse)
async def get_metrics(
    correlation_id: Optional[str] = None,
    db_pool=Depends(get_db_pool)
):
    """
    Computes KPI metrics for a specific correlation or system-wide.
    Metrics include reply_rate, conversion_rate, and event counts.
    """
    try:
        # Get event and outcome counts
        event_counts = await get_events_for_metrics(db_pool, correlation_id)
        outcome_counts = await get_outcome_statistics(db_pool, correlation_id)
        
        # Calculate rates from outcomes and events
        message_sent_count = event_counts.get("message_sent", 0)
        reply_count = outcome_counts.get("reply", 0)
        conversion_count = outcome_counts.get("conversion", 0)
        
        reply_rate = reply_count / message_sent_count if message_sent_count > 0 else 0.0
        conversion_rate = conversion_count / reply_count if reply_count > 0 else 0.0
        
        return {
            "correlation_id": correlation_id,
            "reply_rate": reply_rate,
            "conversion_rate": conversion_rate,
            "event_counts": event_counts,
            "outcome_counts": outcome_counts,
        }
    except Exception as e:
        logger.error(f"Failed to compute metrics: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/kpis", response_model=KPIResponse)
async def get_kpis(db_pool=Depends(get_db_pool)):
    """
    Retrieves system-wide KPI summary.
    Returns average reply/conversion rates and event distribution.
    """
    try:
        # Get system-wide event and outcome counts
        event_counts = await get_events_for_metrics(db_pool, correlation_id=None)
        outcome_counts = await get_outcome_statistics(db_pool, correlation_id=None)
        
        # Sort by count to get top event types
        top_event_types = dict(sorted(event_counts.items(), key=lambda x: x[1], reverse=True)[:5])
        
        # Calculate totals
        total_events = sum(event_counts.values())
        total_correlations = await get_total_correlations(db_pool)
        
        # Derive system-wide rates from aggregated counts
        total_message_sent = event_counts.get("message_sent", 0)
        total_replies = outcome_counts.get("reply", 0)
        total_conversions = outcome_counts.get("conversion", 0)

        average_reply_rate = total_replies / total_message_sent if total_message_sent > 0 else 0.0
        average_conversion_rate = total_conversions / total_replies if total_replies > 0 else 0.0
        
        return {
            "average_reply_rate": average_reply_rate,
            "average_conversion_rate": average_conversion_rate,
            "total_events_ingested": total_events,
            "total_correlations": total_correlations,
            "top_event_types": top_event_types,
        }
    except Exception as e:
        logger.error(f"Failed to compute KPIs: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/integrity/audit", response_model=IntegrityAuditResponse)
async def audit_integrity(
    correlation_id: str,
    db_pool=Depends(get_db_pool)
):
    """
    Audits data integrity for a correlation.
    Detects orphaned outcomes, missing events in sequence, and duplicates.
    """
    try:
        import uuid
        from datetime import datetime, timezone
        
        issues: List[IntegrityIssue] = []
        
        # Check for orphaned outcomes
        orphaned = await find_orphaned_outcomes(db_pool, correlation_id)
        if orphaned:
            for outcome in orphaned:
                issues.append(IntegrityIssue(
                    issue_type="orphaned_outcome",
                    message=f"Outcome {outcome['outcome_id']} has no linked event",
                    details=outcome,
                ))
        
        # Check for duplicates
        duplicates = await detect_duplicates(db_pool, correlation_id)
        if duplicates:
            for dup in duplicates:
                issues.append(IntegrityIssue(
                    issue_type="duplicate_event",
                    message=f"Duplicate {dup['event_type']} event(s) detected",
                    details=dict(dup),
                ))
        
        # Verify event sequence (expect: lead_ingested -> lead_scored -> message_generated -> message_sent)
        expected_sequence = ["lead_ingested", "lead_scored", "message_generated", "message_sent"]
        sequence_check = await verify_event_sequence(db_pool, correlation_id, expected_sequence)
        if not sequence_check.get("is_valid", False):
            if sequence_check.get("missing_events"):
                issues.append(IntegrityIssue(
                    issue_type="missing_event",
                    message=f"Expected events not found: {sequence_check['missing_events']}",
                    details=sequence_check,
                ))

        missing_steps = await find_missing_expected_events(db_pool, correlation_id, expected_sequence)
        if missing_steps:
            issues.append(IntegrityIssue(
                issue_type="missing_event",
                message=f"Missing required workflow steps: {missing_steps}",
                details={"missing_steps": missing_steps, "expected_sequence": expected_sequence},
            ))

        chain_breaks = await detect_correlation_chain_breaks(db_pool, correlation_id, expected_sequence)
        if chain_breaks:
            issues.append(IntegrityIssue(
                issue_type="chain_break",
                message=f"Detected {len(chain_breaks)} workflow ordering break(s)",
                details={"chain_breaks": chain_breaks},
            ))
        
        # Record alert if issues found
        if issues:
            alert_id = str(uuid.uuid4())
            await record_integrity_alert(
                db_pool,
                alert_id=alert_id,
                correlation_id=correlation_id,
                issue_type="integrity_violation",
                message=f"Found {len(issues)} integrity issues",
                details={"issue_count": len(issues), "issue_types": [i.issue_type for i in issues]},
                severity="warning" if len(issues) <= 2 else "critical",
            )
        
        return {
            "correlation_id": correlation_id,
            "is_healthy": len(issues) == 0,
            "issues": issues,
            "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Failed to audit integrity for {correlation_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/outcomes", response_model=OutcomeListResponse)
async def get_outcomes(
    correlation_id: Optional[str] = None,
    outcome_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db_pool=Depends(get_db_pool),
):
    """Retrieves outcomes with optional filtering and pagination."""
    try:
        items, total = await list_outcomes(
            db_pool,
            correlation_id=correlation_id,
            outcome_type=outcome_type,
            limit=limit,
            offset=offset,
        )
        return {
            "items": items,
            "total": total,
            "limit": max(1, min(limit, 500)),
            "offset": max(0, offset),
        }
    except Exception as e:
        logger.error(f"Failed to list outcomes: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/outcomes/{outcome_id}", response_model=Dict[str, Any])
async def get_outcome(outcome_id: str, db_pool=Depends(get_db_pool)):
    """Retrieves a single outcome by ID."""
    try:
        item = await get_outcome_by_id(db_pool, outcome_id)
        if not item:
            raise HTTPException(status_code=404, detail="Outcome not found")
        return item
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch outcome {outcome_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/events_outcomes/{correlation_id}", response_model=EventOutcomeMapResponse)
async def get_events_outcomes(correlation_id: str, db_pool=Depends(get_db_pool)):
    """Returns timeline events with all linked outcomes for the correlation."""
    try:
        mapped = await correlate_events_to_outcomes(db_pool, correlation_id)
        if not mapped:
            raise HTTPException(status_code=404, detail="No events found for this correlation ID")
        summary = await get_outcome_statistics(db_pool, correlation_id)
        return {
            "correlation_id": correlation_id,
            "events_with_outcomes": mapped,
            "outcome_summary": summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to build events_outcomes map for {correlation_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/alerts", response_model=IntegrityAlertListResponse)
async def get_alerts(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    correlation_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db_pool=Depends(get_db_pool),
):
    """Lists integrity alerts with optional filtering by status/severity/correlation."""
    try:
        items, total = await list_integrity_alerts(
            db_pool,
            status=status,
            severity=severity,
            correlation_id=correlation_id,
            limit=limit,
            offset=offset,
        )
        return {
            "items": items,
            "total": total,
            "limit": max(1, min(limit, 500)),
            "offset": max(0, offset),
        }
    except Exception as e:
        logger.error(f"Failed to list alerts: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/v1/alerts/{alert_id}/acknowledge", response_model=IntegrityAlertItem)
async def acknowledge_alert(alert_id: str, db_pool=Depends(get_db_pool)):
    """Acknowledges an open alert."""
    try:
        item = await update_integrity_alert_status(db_pool, alert_id, "acknowledged")
        if not item:
            raise HTTPException(status_code=404, detail="Alert not found")
        return item
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to acknowledge alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/v1/alerts/{alert_id}/resolve", response_model=IntegrityAlertItem)
async def resolve_alert(alert_id: str, db_pool=Depends(get_db_pool)):
    """Resolves an alert."""
    try:
        item = await update_integrity_alert_status(db_pool, alert_id, "resolved")
        if not item:
            raise HTTPException(status_code=404, detail="Alert not found")
        return item
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resolve alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.delete("/v1/alerts/{alert_id}")
async def delete_alert(alert_id: str, db_pool=Depends(get_db_pool)):
    """Archives an alert (soft-delete via status='archived')."""
    try:
        archived = await archive_integrity_alert(db_pool, alert_id)
        if not archived:
            raise HTTPException(status_code=404, detail="Alert not found")
        item = await get_integrity_alert(db_pool, alert_id)
        return {"archived": True, "alert": item}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to archive alert {alert_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/trace/correlation/{correlation_id}", response_model=GraphTraceResponse)
async def trace_correlation_graph(
    correlation_id: str,
    db_pool=Depends(get_db_pool),
    graph_adapter=Depends(get_graph_adapter),
):
    """Projects a correlation into graph storage and returns the graph trace."""
    try:
        if graph_adapter.available:
            sync_result = await sync_and_verify_correlation_graph(db_pool, graph_adapter, correlation_id)
            projected = sync_result.get("projected")
            parity = sync_result.get("parity")
            trace = await graph_adapter.trace_correlation(correlation_id)
        else:
            projected = {"nodes": 0, "edges": 0}
            parity = {"graph_available": False, "is_parity_ok": True}
            trace = await build_correlation_trace_payload(db_pool, correlation_id)
        return {
            "nodes": trace.get("nodes", []),
            "relationships": trace.get("relationships", []),
            "projected": projected,
            "parity": parity,
        }
    except Exception as e:
        logger.error(f"Failed to trace correlation graph for {correlation_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/trace/correlation/{correlation_id}/checkpoint", response_model=GraphCheckpointResponse)
async def get_correlation_checkpoint(
    correlation_id: str,
    db_pool=Depends(get_db_pool),
    graph_adapter=Depends(get_graph_adapter),
):
    """Returns replay-safe sync checkpoint and current parity report for a correlation."""
    try:
        checkpoint = await get_graph_sync_checkpoint(db_pool, correlation_id)
        parity = await verify_graph_parity(db_pool, graph_adapter, correlation_id)
        return {
            "checkpoint": checkpoint,
            "parity": parity,
        }
    except Exception as e:
        logger.error(f"Failed to fetch graph checkpoint/parity for {correlation_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/trace/lead/{lead_id}", response_model=GraphTraceResponse)
async def trace_lead_graph(
    lead_id: str,
    graph_adapter=Depends(get_graph_adapter),
):
    """Returns graph lineage for a lead node."""
    try:
        trace = await graph_adapter.trace_lead(lead_id) if graph_adapter.available else {"nodes": [], "relationships": []}
        return {
            "nodes": trace.get("nodes", []),
            "relationships": trace.get("relationships", []),
            "projected": None,
        }
    except Exception as e:
        logger.error(f"Failed to trace lead graph for {lead_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/trace/impact", response_model=GraphTraceResponse)
async def trace_impact_graph(
    metric: str,
    window: str = "30d",
    graph_adapter=Depends(get_graph_adapter),
):
    """Returns graph lineage for a business metric impact query."""
    try:
        trace = await graph_adapter.trace_impact(metric, window) if graph_adapter.available else {"nodes": [], "relationships": []}
        return {
            "nodes": trace.get("nodes", []),
            "relationships": trace.get("relationships", []),
            "projected": None,
        }
    except Exception as e:
        logger.error(f"Failed to trace impact graph for metric={metric} window={window}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/v1/optimization/run", response_model=RecommendationRunResponse)
async def run_optimization(
    request: RecommendationRunRequest,
    db_pool=Depends(get_db_pool),
):
    """Generates dry-run optimization recommendations from current telemetry signals."""
    try:
        event_counts = await get_events_for_metrics(db_pool, request.correlation_id)
        outcome_counts = await get_outcome_statistics(db_pool, request.correlation_id)

        generated = build_dry_run_recommendations(
            event_counts=event_counts,
            outcome_counts=outcome_counts,
            max_change_pct=request.max_change_pct,
            cooldown_hours=request.cooldown_hours,
        )

        created_items: List[Dict[str, Any]] = []
        skipped_due_cooldown = 0
        for rec in generated:
            if await is_recommendation_type_in_cooldown(
                db_pool,
                recommendation_type=rec["recommendation_type"],
                cooldown_hours=request.cooldown_hours,
                correlation_id=request.correlation_id,
            ):
                skipped_due_cooldown += 1
                continue

            recommendation_id = str(uuid.uuid4())
            await create_optimization_recommendation(
                db_pool,
                recommendation_id=recommendation_id,
                recommendation_type=rec["recommendation_type"],
                summary=rec["summary"],
                payload=rec["payload"],
                confidence=float(rec.get("confidence", 0.5)),
                correlation_id=request.correlation_id,
            )
            item = await get_optimization_recommendation(db_pool, recommendation_id)
            if item:
                created_items.append(item)

        run_id = str(uuid.uuid4())
        return {
            "run_id": run_id,
            "dry_run": True,
            "created_count": len(created_items),
            "skipped_due_cooldown": skipped_due_cooldown,
            "items": created_items,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Failed to run optimization recommendations: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/optimization/recommendations", response_model=RecommendationHistoryResponse)
async def get_recommendation_history(
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db_pool=Depends(get_db_pool),
):
    """Lists generated optimization recommendations with optional status filtering."""
    try:
        items, total = await list_optimization_recommendations(
            db_pool,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "items": items,
            "total": total,
            "limit": max(1, min(limit, 500)),
            "offset": max(0, offset),
        }
    except Exception as e:
        logger.error(f"Failed to list optimization recommendations: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.get("/v1/optimization/audit", response_model=OptimizationAuditResponse)
async def get_optimization_audit(
    recommendation_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    approved_by: Optional[str] = None,
    status: Optional[str] = None,
    event_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db_pool=Depends(get_db_pool),
):
    """Returns optimization approval audit events emitted by Worker."""
    try:
        if cursor is not None:
            try:
                offset = int(cursor)
            except ValueError:
                raise HTTPException(status_code=400, detail="cursor must be an integer string")

        bounded_limit = max(1, min(limit, 500))
        bounded_offset = max(0, offset)

        items, total = await list_optimization_audit_events(
            db_pool,
            recommendation_id=recommendation_id,
            correlation_id=correlation_id,
            approved_by=approved_by,
            status=status,
            event_type=event_type,
            start_time=start_time,
            end_time=end_time,
            limit=bounded_limit,
            offset=bounded_offset,
        )

        next_cursor = str(bounded_offset + bounded_limit) if (bounded_offset + bounded_limit) < total else None
        prev_cursor = str(max(0, bounded_offset - bounded_limit)) if bounded_offset > 0 else None

        return {
            "items": items,
            "total": total,
            "limit": bounded_limit,
            "offset": bounded_offset,
            "next_cursor": next_cursor,
            "prev_cursor": prev_cursor,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list optimization audit events: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/v1/optimization/recommendations/{recommendation_id}/approve", response_model=RecommendationItem)
async def approve_recommendation(
    recommendation_id: str,
    request: RecommendationApproveRequest,
    db_pool=Depends(get_db_pool),
):
    """Approves a recommendation for upstream consumption (no auto-apply)."""
    try:
        before = await get_optimization_recommendation(db_pool, recommendation_id)
        if not before:
            raise HTTPException(status_code=404, detail="Recommendation not found")

        item = await approve_optimization_recommendation(
            db_pool,
            recommendation_id=recommendation_id,
            approved_by=request.approved_by,
        )
        if not item:
            raise HTTPException(status_code=404, detail="Recommendation not found")

        if before.get("status") != "approved":
            await _emit_recommendation_audit_event(
                db_pool,
                recommendation_id=recommendation_id,
                item=item,
                event_type="optimization_recommendation_approved",
                actor_key="approved_by",
            )

        return item
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve optimization recommendation {recommendation_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/v1/optimization/recommendations/{recommendation_id}/execute", response_model=RecommendationExecuteResponse)
async def execute_recommendation(
    recommendation_id: str,
    request: RecommendationExecuteRequest,
    db_pool=Depends(get_db_pool),
):
    """Executes recommendation in dry-run by default; apply mode requires approved status."""
    try:
        before = await get_optimization_recommendation(db_pool, recommendation_id)
        if not before:
            raise HTTPException(status_code=404, detail="Recommendation not found")

        if not request.apply:
            await _emit_recommendation_audit_event(
                db_pool,
                recommendation_id=recommendation_id,
                item=before,
                event_type="optimization_recommendation_dry_run",
                actor_key="acted_by",
                actor_value=request.acted_by,
            )
            return {
                "recommendation": before,
                "mode": "dry_run",
                "applied": False,
            }

        recommendation_type = str(before.get("recommendation_type") or "")
        apply_enabled = request.override_apply_enabled
        if apply_enabled is None:
            apply_enabled = settings.OPTIMIZATION_APPLY_ENABLED

        disabled_types = (
            request.override_disabled_recommendation_types
            if request.override_disabled_recommendation_types is not None
            else settings.OPTIMIZATION_APPLY_DISABLED_RECOMMENDATION_TYPES
        )
        disabled_types = [str(item) for item in disabled_types]

        policy_max_change_pct = (
            request.policy_max_change_pct
            if request.policy_max_change_pct is not None
            else settings.OPTIMIZATION_APPLY_MAX_CHANGE_PCT
        )

        policy_metadata = {
            "policy_max_change_pct": policy_max_change_pct,
            "policy_allowed_actions": settings.OPTIMIZATION_APPLY_ALLOWED_ACTIONS,
            "policy_allowed_target_scopes": settings.OPTIMIZATION_APPLY_ALLOWED_TARGET_SCOPES,
            "apply_enabled": apply_enabled,
            "disabled_recommendation_types": disabled_types,
        }

        if not apply_enabled:
            await _emit_recommendation_audit_event(
                db_pool,
                recommendation_id=recommendation_id,
                item=before,
                event_type="optimization_apply_blocked",
                actor_key="acted_by",
                actor_value=request.acted_by,
                payload_extra={"decision": "blocked", "reason_code": "GLOBAL_KILL_SWITCH"},
                metadata_extra=policy_metadata,
            )
            raise HTTPException(
                status_code=409,
                detail={"code": "GLOBAL_KILL_SWITCH", "message": "Apply is disabled by control-plane switch"},
            )

        if recommendation_type in set(disabled_types):
            await _emit_recommendation_audit_event(
                db_pool,
                recommendation_id=recommendation_id,
                item=before,
                event_type="optimization_apply_blocked",
                actor_key="acted_by",
                actor_value=request.acted_by,
                payload_extra={"decision": "blocked", "reason_code": "TYPE_KILL_SWITCH"},
                metadata_extra=policy_metadata,
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "TYPE_KILL_SWITCH",
                    "message": f"Apply is disabled for recommendation type '{recommendation_type}'",
                },
            )

        if before.get("status") not in {"approved", "applied"}:
            await _emit_recommendation_audit_event(
                db_pool,
                recommendation_id=recommendation_id,
                item=before,
                event_type="optimization_apply_blocked",
                actor_key="acted_by",
                actor_value=request.acted_by,
                payload_extra={"decision": "blocked", "reason_code": "STATUS_NOT_APPROVED"},
                metadata_extra=policy_metadata,
            )
            raise HTTPException(status_code=409, detail="Only approved recommendations can be applied")

        if before.get("status") == "approved":
            payload = before.get("payload") if isinstance(before.get("payload"), dict) else {}
            policy_violations = evaluate_apply_policy(
                payload=payload,
                max_change_pct=policy_max_change_pct,
                allowed_actions=settings.OPTIMIZATION_APPLY_ALLOWED_ACTIONS,
                allowed_target_scopes=settings.OPTIMIZATION_APPLY_ALLOWED_TARGET_SCOPES,
            )
            if policy_violations:
                await _emit_recommendation_audit_event(
                    db_pool,
                    recommendation_id=recommendation_id,
                    item=before,
                    event_type="optimization_apply_blocked",
                    actor_key="acted_by",
                    actor_value=request.acted_by,
                    payload_extra={
                        "decision": "blocked",
                        "reason_code": "POLICY_VIOLATION",
                        "violations": policy_violations,
                    },
                    metadata_extra=policy_metadata,
                )
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "APPLY_POLICY_BLOCKED",
                        "message": "Apply request violates policy guardrails",
                        "violations": policy_violations,
                    },
                )

        await _emit_recommendation_audit_event(
            db_pool,
            recommendation_id=recommendation_id,
            item=before,
            event_type="optimization_apply_allowed",
            actor_key="acted_by",
            actor_value=request.acted_by,
            payload_extra={"decision": "allowed", "reason_code": "POLICY_PASSED"},
            metadata_extra=policy_metadata,
        )

        item = await apply_optimization_recommendation(
            db_pool,
            recommendation_id=recommendation_id,
            applied_by=request.acted_by,
        )
        if not item:
            raise HTTPException(status_code=404, detail="Recommendation not found")

        if before.get("status") != "applied":
            await _emit_recommendation_audit_event(
                db_pool,
                recommendation_id=recommendation_id,
                item=item,
                event_type="optimization_recommendation_applied",
                actor_key="applied_by",
            )

        return {
            "recommendation": item,
            "mode": "apply",
            "applied": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to execute optimization recommendation {recommendation_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/v1/optimization/recommendations/{recommendation_id}/reject", response_model=RecommendationItem)
async def reject_recommendation(
    recommendation_id: str,
    request: RecommendationActionRequest,
    db_pool=Depends(get_db_pool),
):
    """Rejects a recommendation to prevent it from being approved/applied."""
    try:
        before = await get_optimization_recommendation(db_pool, recommendation_id)
        if not before:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if before.get("status") not in {"proposed", "rejected"}:
            raise HTTPException(status_code=409, detail="Only proposed recommendations can be rejected")

        item = await reject_optimization_recommendation(
            db_pool,
            recommendation_id=recommendation_id,
            rejected_by=request.acted_by,
        )
        if not item:
            raise HTTPException(status_code=404, detail="Recommendation not found")

        if before.get("status") != "rejected":
            await _emit_recommendation_audit_event(
                db_pool,
                recommendation_id=recommendation_id,
                item=item,
                event_type="optimization_recommendation_rejected",
                actor_key="rejected_by",
            )

        return item
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reject optimization recommendation {recommendation_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/v1/optimization/recommendations/{recommendation_id}/rollback", response_model=RecommendationItem)
async def rollback_recommendation(
    recommendation_id: str,
    request: RecommendationActionRequest,
    db_pool=Depends(get_db_pool),
):
    """Rolls back an approved recommendation and records lifecycle audit state."""
    try:
        before = await get_optimization_recommendation(db_pool, recommendation_id)
        if not before:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if before.get("status") not in {"approved", "applied", "rolled_back"}:
            raise HTTPException(status_code=409, detail="Only approved recommendations can be rolled back")

        item = await rollback_optimization_recommendation(
            db_pool,
            recommendation_id=recommendation_id,
            rolled_back_by=request.acted_by,
        )
        if not item:
            raise HTTPException(status_code=404, detail="Recommendation not found")

        if before.get("status") != "rolled_back":
            await _emit_recommendation_audit_event(
                db_pool,
                recommendation_id=recommendation_id,
                item=item,
                event_type="optimization_recommendation_rolled_back",
                actor_key="rolled_back_by",
            )

        return item
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to roll back optimization recommendation {recommendation_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
