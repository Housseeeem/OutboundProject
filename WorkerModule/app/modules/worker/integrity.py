"""
Integrity Checking Service for WorkerModule.

Detects data quality issues: missing events, orphaned outcomes, duplicates, etc.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


async def check_correlation_integrity(db_pool, correlation_id: str) -> Dict[str, Any]:
    """
    Comprehensive integrity check for a correlation.
    Returns a report with detected issues.
    """
    issues = []
    
    # Check for orphaned outcomes (outcomes without linked events)
    query_orphans = """
        SELECT o.outcome_id, o.linked_event_id
        FROM outcomes o
        LEFT JOIN events e ON o.linked_event_id = e.event_id
        WHERE o.correlation_id = $1 AND e.event_id IS NULL;
    """
    
    try:
        async with db_pool.acquire() as connection:
            orphans = await connection.fetch(query_orphans, correlation_id)
        
        if orphans:
            for orphan in orphans:
                issues.append({
                    "type": "orphaned_outcome",
                    "outcome_id": str(orphan['outcome_id']),
                    "linked_event_id": str(orphan['linked_event_id']),
                })
    except Exception as e:
        logger.error(f"Failed to check for orphaned outcomes: {e}")
    
    # Check for duplicate events
    query_dups = """
        SELECT event_type, COUNT(*) as count, ARRAY_AGG(event_id) as event_ids
        FROM events
        WHERE correlation_id = $1
        GROUP BY event_type, DATE_TRUNC('second', timestamp)
        HAVING COUNT(*) > 1;
    """
    
    try:
        async with db_pool.acquire() as connection:
            dups = await connection.fetch(query_dups, correlation_id)
        
        if dups:
            for dup in dups:
                issues.append({
                    "type": "duplicate_event",
                    "event_type": dup['event_type'],
                    "count": dup['count'],
                    "event_ids": [str(eid) for eid in dup['event_ids']],
                })
    except Exception as e:
        logger.error(f"Failed to check for duplicates: {e}")
    
    # Check event sequence
    query_sequence = """
        SELECT event_type, timestamp
        FROM events
        WHERE correlation_id = $1
        ORDER BY timestamp ASC;
    """
    
    try:
        async with db_pool.acquire() as connection:
            events = await connection.fetch(query_sequence, correlation_id)
        
        # Expected sequence for standard workflow
        expected_sequence = ["lead_ingested", "lead_scored", "message_generated", "message_sent"]
        event_types = [e['event_type'] for e in events]
        
        # Check if all expected events are present
        missing = [et for et in expected_sequence if et not in event_types]
        if missing:
            issues.append({
                "type": "missing_events",
                "missing": missing,
                "actual": event_types,
            })
    except Exception as e:
        logger.error(f"Failed to check event sequence: {e}")
    
    return {
        "correlation_id": correlation_id,
        "is_healthy": len(issues) == 0,
        "issue_count": len(issues),
        "issues": issues,
    }


async def detect_suspicious_patterns(db_pool, correlation_id: str) -> List[Dict[str, Any]]:
    """
    Detects suspicious patterns that may indicate data quality issues.
    Examples: excessive delays, unusual event sequences, etc.
    """
    patterns = []
    
    # Check for excessive time gaps between events
    query_gaps = """
        SELECT 
            LEAD(event_type) OVER (ORDER BY timestamp) as next_event,
            EXTRACT(EPOCH FROM (LEAD(timestamp) OVER (ORDER BY timestamp) - timestamp)) as gap_seconds
        FROM events
        WHERE correlation_id = $1
        ORDER BY timestamp ASC;
    """
    
    try:
        async with db_pool.acquire() as connection:
            gaps = await connection.fetch(query_gaps, correlation_id)
        
        for gap in gaps:
            if gap['gap_seconds'] and gap['gap_seconds'] > 3600:  # > 1 hour
                patterns.append({
                    "type": "excessive_time_gap",
                    "gap_seconds": gap['gap_seconds'],
                    "next_event": gap['next_event'],
                })
    except Exception as e:
        logger.error(f"Failed to detect time gaps: {e}")
    
    return patterns
