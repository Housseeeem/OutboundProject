import asyncpg
import logging
import json
import uuid
from datetime import date, datetime
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _normalize_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in value.items()}
    return value


def _normalize_event_row(row: asyncpg.Record) -> Dict[str, Any]:
    normalized = dict(row)
    if isinstance(normalized.get("payload"), str):
        normalized["payload"] = json.loads(normalized["payload"])
    if isinstance(normalized.get("metadata"), str):
        normalized["metadata"] = json.loads(normalized["metadata"])
    if isinstance(normalized.get("value"), str):
        normalized["value"] = json.loads(normalized["value"])
    if isinstance(normalized.get("details"), str):
        normalized["details"] = json.loads(normalized["details"])
    return {key: _normalize_value(value) for key, value in normalized.items()}

async def get_events_by_correlation_id(db_pool, correlation_id: str) -> List[Dict[str, Any]]:
    """
    Retrieves all events from the database for a given correlation_id, ordered by timestamp.
    """
    # This assumes a table named 'events' exists. We will need to create it.
    query = """
        SELECT event_id, correlation_id, module, event_type, timestamp, payload, metadata
        FROM events
        WHERE correlation_id = $1
        ORDER BY timestamp ASC;
    """
    try:
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, correlation_id)
            return [_normalize_event_row(row) for row in rows]
    except asyncpg.exceptions.UndefinedTableError:
        logger.error("The 'events' table does not exist. Please run migrations to create it.")
        # In a real application, you would have a migration system.
        # For now, we will create the table if it doesn't exist.
        await create_events_table(db_pool)
        # And retry the query
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, correlation_id)
            return [_normalize_event_row(row) for row in rows]
    except Exception as e:
        logger.error(f"Database error while fetching events for correlation ID {correlation_id}: {e}")
        return []

async def create_events_table(db_pool):
    """
    Creates the 'events', 'outcomes', and 'integrity_alerts' tables if they do not already exist.
    This is a temporary solution for development. A proper migration tool should be used.
    """
    logger.info("Attempting to create Worker schema tables...")
    queries = [
        # Events table
        """
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            event_id UUID UNIQUE NOT NULL,
            correlation_id UUID NOT NULL,
            module VARCHAR(50) NOT NULL,
            event_type VARCHAR(100) NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            payload JSONB,
            metadata JSONB,
            created_at TIMESTAMPTZ DEFAULT timezone('utc', now())
        );
        """,
        # Outcomes table: links decisions/actions to outcomes
        """
        CREATE TABLE IF NOT EXISTS outcomes (
            id SERIAL PRIMARY KEY,
            outcome_id UUID UNIQUE NOT NULL,
            correlation_id UUID NOT NULL,
            linked_event_id UUID NOT NULL,
            outcome_type VARCHAR(50) NOT NULL,
            value JSONB,
            timestamp TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ DEFAULT timezone('utc', now())
        );
        """,
        # Integrity alerts table: stores detected issues
        """
        CREATE TABLE IF NOT EXISTS integrity_alerts (
            id SERIAL PRIMARY KEY,
            alert_id UUID UNIQUE NOT NULL,
            correlation_id UUID NOT NULL,
            issue_type VARCHAR(50) NOT NULL,
            message TEXT NOT NULL,
            details JSONB,
            severity VARCHAR(20) DEFAULT 'warning',
            status VARCHAR(20) DEFAULT 'open',
            is_resolved BOOLEAN DEFAULT FALSE,
            acknowledged_at TIMESTAMPTZ,
            resolved_at TIMESTAMPTZ,
            timestamp TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT timezone('utc', now()),
            created_at TIMESTAMPTZ DEFAULT timezone('utc', now())
        );
        """,
        # Graph sync checkpoints table: tracks replay-safe projection progress
        """
        CREATE TABLE IF NOT EXISTS graph_sync_checkpoints (
            id SERIAL PRIMARY KEY,
            correlation_id UUID UNIQUE NOT NULL,
            last_event_id UUID,
            last_event_timestamp TIMESTAMPTZ,
            projected_nodes INTEGER DEFAULT 0,
            projected_edges INTEGER DEFAULT 0,
            sync_status VARCHAR(30) DEFAULT 'pending',
            synced_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ DEFAULT timezone('utc', now()),
            created_at TIMESTAMPTZ DEFAULT timezone('utc', now())
        );
        """,
        # Optimization recommendations table: stores dry-run suggestions and approvals
        """
        CREATE TABLE IF NOT EXISTS optimization_recommendations (
            id SERIAL PRIMARY KEY,
            recommendation_id UUID UNIQUE NOT NULL,
            correlation_id UUID,
            recommendation_type VARCHAR(80) NOT NULL,
            summary TEXT NOT NULL,
            payload JSONB,
            confidence DOUBLE PRECISION DEFAULT 0.5,
            status VARCHAR(20) DEFAULT 'proposed',
            approved_by VARCHAR(100),
            approved_at TIMESTAMPTZ,
            rejected_by VARCHAR(100),
            rejected_at TIMESTAMPTZ,
            applied_by VARCHAR(100),
            applied_at TIMESTAMPTZ,
            rolled_back_by VARCHAR(100),
            rolled_back_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT timezone('utc', now()),
            updated_at TIMESTAMPTZ DEFAULT timezone('utc', now())
        );
        """,
        # Global Config table: allows control over systemic settings
        """
        CREATE TABLE IF NOT EXISTS global_config (
            id SERIAL PRIMARY KEY,
            config_key VARCHAR(100) UNIQUE NOT NULL,
            config_value JSONB,
            updated_at TIMESTAMPTZ DEFAULT timezone('utc', now())
        );
        """,
        # Backward-compatible schema evolution for existing databases
        "ALTER TABLE integrity_alerts ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'open';",
        "ALTER TABLE integrity_alerts ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ;",
        "ALTER TABLE integrity_alerts ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;",
        "ALTER TABLE integrity_alerts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT timezone('utc', now());",
        "ALTER TABLE graph_sync_checkpoints ADD COLUMN IF NOT EXISTS sync_status VARCHAR(30) DEFAULT 'pending';",
        "ALTER TABLE graph_sync_checkpoints ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ;",
        "ALTER TABLE graph_sync_checkpoints ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT timezone('utc', now());",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'proposed';",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS approved_by VARCHAR(100);",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS rejected_by VARCHAR(100);",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ;",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS applied_by VARCHAR(100);",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ;",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS rolled_back_by VARCHAR(100);",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS rolled_back_at TIMESTAMPTZ;",
        "ALTER TABLE optimization_recommendations ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT timezone('utc', now());",
        # Create indexes for common queries
        "CREATE INDEX IF NOT EXISTS idx_correlation_id ON events (correlation_id);",
        "CREATE INDEX IF NOT EXISTS idx_event_type ON events (event_type);",
        "CREATE INDEX IF NOT EXISTS idx_outcomes_correlation_id ON outcomes (correlation_id);",
        "CREATE INDEX IF NOT EXISTS idx_outcomes_linked_event ON outcomes (linked_event_id);",
        "CREATE INDEX IF NOT EXISTS idx_alerts_correlation_id ON integrity_alerts (correlation_id);",
        "CREATE INDEX IF NOT EXISTS idx_alerts_issue_type ON integrity_alerts (issue_type);",
        "CREATE INDEX IF NOT EXISTS idx_alerts_status ON integrity_alerts (status);",
        "CREATE INDEX IF NOT EXISTS idx_graph_sync_checkpoints_correlation_id ON graph_sync_checkpoints (correlation_id);",
        "CREATE INDEX IF NOT EXISTS idx_optimization_recommendations_status ON optimization_recommendations (status);",
        "CREATE INDEX IF NOT EXISTS idx_optimization_recommendations_created_at ON optimization_recommendations (created_at DESC);",
    ]
    
    try:
        async with db_pool.acquire() as connection:
            for query in queries:
                await connection.execute(query)
        logger.info("Worker schema tables created or already exist.")
    except Exception as e:
        logger.error(f"Failed to create Worker schema tables: {e}")


async def list_events(
    db_pool,
    correlation_id: str | None = None,
    module: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """List events with optional filters for retrieval APIs."""
    bounded_limit = max(1, min(limit, 500))
    conditions: List[str] = []
    params: List[Any] = []

    if correlation_id:
        params.append(correlation_id)
        conditions.append(f"correlation_id = ${len(params)}")
    if module:
        params.append(module)
        conditions.append(f"module = ${len(params)}")
    if event_type:
        params.append(event_type)
        conditions.append(f"event_type = ${len(params)}")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    params.append(bounded_limit)
    query = f"""
        SELECT event_id, correlation_id, module, event_type, timestamp, payload, metadata
        FROM events
        {where_clause}
        ORDER BY timestamp ASC
        LIMIT ${len(params)};
    """

    try:
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, *params)
            return [_normalize_event_row(row) for row in rows]
    except asyncpg.exceptions.UndefinedTableError:
        logger.error("The 'events' table does not exist. Creating it now.")
        await create_events_table(db_pool)
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, *params)
            return [_normalize_event_row(row) for row in rows]
    except Exception as e:
        logger.error(f"Database error while listing events: {e}")
        return []

async def save_event(db_pool, event: Dict[str, Any]) -> bool:
    """
    Saves a single event to the database.
    """
    query = """
    INSERT INTO events (event_id, correlation_id, module, event_type, timestamp, payload, metadata)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
    ON CONFLICT (event_id) DO NOTHING;
    """
    try:
        async with db_pool.acquire() as connection:
            result = await connection.execute(
                query,
                event['event_id'],
                event['correlation_id'],
                event['module'],
                event['event_type'],
                _coerce_datetime(event['timestamp']) or event['timestamp'],
                json.dumps(event['payload']),
                json.dumps(event['metadata'])
            )
            return result.endswith("1")
    except asyncpg.exceptions.UndefinedTableError:
        logger.error("The 'events' table does not exist. Creating it now.")
        await create_events_table(db_pool)
        # Retry saving the event
        return await save_event(db_pool, event)
    except Exception as e:
        logger.error(f"Failed to save event {event['event_id']}: {e}")
        raise


async def event_exists(db_pool, event_id: str) -> bool:
    """Returns True when an event exists by ID."""
    query = "SELECT 1 FROM events WHERE event_id = $1 LIMIT 1;"
    try:
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(query, event_id)
            return row is not None
    except asyncpg.exceptions.UndefinedTableError:
        logger.error("The 'events' table does not exist. Creating it now.")
        await create_events_table(db_pool)
        return False
    except Exception as e:
        logger.error(f"Database error while checking event existence {event_id}: {e}")
        return False


async def find_near_duplicate_event(
    db_pool,
    correlation_id: str,
    event_type: str,
    timestamp: Any,
    window_seconds: int = 5,
) -> Dict[str, Any] | None:
    """
    Returns an existing event in the same correlation/event_type within +/- window_seconds.
    Useful for suppressing near-duplicate event floods during retries.
    """
    query = """
        SELECT event_id, correlation_id, module, event_type, timestamp, payload, metadata
        FROM events
        WHERE correlation_id = $1
          AND event_type = $2
          AND timestamp BETWEEN ($3::timestamptz - make_interval(secs => $4::int))
                            AND ($3::timestamptz + make_interval(secs => $4::int))
        ORDER BY ABS(EXTRACT(EPOCH FROM (timestamp - $3::timestamptz))) ASC
        LIMIT 1;
    """
    try:
        timestamp_value = _coerce_datetime(timestamp)
        if timestamp_value is None:
            return None
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(query, correlation_id, event_type, timestamp_value, window_seconds)
            return _normalize_event_row(row) if row else None
    except asyncpg.exceptions.UndefinedTableError:
        logger.error("The 'events' table does not exist. Creating it now.")
        await create_events_table(db_pool)
        return None
    except Exception as e:
        logger.error(f"Database error while finding near-duplicate event: {e}")
        return None


# ============ OUTCOME LINKING METHODS ============

async def add_outcome(
    db_pool,
    outcome_id: str,
    correlation_id: str,
    linked_event_id: str,
    outcome_type: str,
    value: Dict[str, Any],
    timestamp: Any,
    linked_event_exists: bool | None = None,
) -> bool:
    """
    Links an outcome to a decision/action event.
    Validates that the linked_event_id exists in the events table.
    Idempotent: returns True on new insert, False on conflict.
    """
    try:
        if linked_event_exists is None:
            linked_event_exists = await event_exists(db_pool, linked_event_id)

        async with db_pool.acquire() as connection:
            if not linked_event_exists:
                logger.warning(f"Linked event {linked_event_id} does not exist; storing outcome anyway with referential flag.")
            
            query = """
            INSERT INTO outcomes (outcome_id, correlation_id, linked_event_id, outcome_type, value, timestamp)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (outcome_id) DO NOTHING;
            """
            result = await connection.execute(
                query,
                outcome_id,
                correlation_id,
                linked_event_id,
                outcome_type,
                json.dumps(value),
                _coerce_datetime(timestamp) or timestamp
            )
            return result.endswith("1")
    except Exception as e:
        logger.error(f"Failed to add outcome {outcome_id}: {e}")
        raise


async def get_outcomes_by_correlation_id(db_pool, correlation_id: str) -> List[Dict[str, Any]]:
    """
    Retrieves all outcomes for a given correlation_id, ordered by timestamp.
    """
    query = """
        SELECT outcome_id, correlation_id, linked_event_id, outcome_type, value, timestamp
        FROM outcomes
        WHERE correlation_id = $1
        ORDER BY timestamp ASC;
    """
    try:
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, correlation_id)
            return [_normalize_event_row(row) for row in rows]
    except Exception as e:
        logger.error(f"Database error while fetching outcomes for correlation ID {correlation_id}: {e}")
        return []


# ============ INTEGRITY CHECK METHODS ============

async def find_orphaned_outcomes(db_pool, correlation_id: str) -> List[Dict[str, Any]]:
    """
    Finds outcomes without corresponding linked events (referential integrity issue).
    """
    query = """
        SELECT o.outcome_id, o.correlation_id, o.linked_event_id, o.outcome_type
        FROM outcomes o
        LEFT JOIN events e ON o.linked_event_id = e.event_id
        WHERE o.correlation_id = $1 AND e.event_id IS NULL;
    """
    try:
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, correlation_id)
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Database error while finding orphaned outcomes: {e}")
        return []


async def detect_duplicates(db_pool, correlation_id: str) -> List[Dict[str, Any]]:
    """
    Detects duplicate events within a correlation (same event_type + timestamp within 1 second).
    """
    query = """
        SELECT event_type, COUNT(*) as count, ARRAY_AGG(event_id) as event_ids
        FROM events
        WHERE correlation_id = $1
        GROUP BY event_type, DATE_TRUNC('second', timestamp)
        HAVING COUNT(*) > 1;
    """
    try:
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, correlation_id)
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Database error while detecting duplicates: {e}")
        return []


async def verify_event_sequence(db_pool, correlation_id: str, expected_sequence: List[str]) -> Dict[str, Any]:
    """
    Verifies that events follow the expected sequence order.
    Returns a report with missing and out-of-order events.
    """
    query = """
        SELECT event_type, timestamp, ROW_NUMBER() OVER (ORDER BY timestamp) as position
        FROM events
        WHERE correlation_id = $1
        ORDER BY timestamp ASC;
    """
    try:
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, correlation_id)
            event_types = [row['event_type'] for row in rows]
            
            missing = []
            out_of_order = []
            
            # Check for missing event types
            for expected in expected_sequence:
                if expected not in event_types:
                    missing.append(expected)
            
            # Check if event types are in expected order (allowing additional events)
            expected_idx = 0
            for event_type in event_types:
                if expected_idx < len(expected_sequence):
                    if event_type == expected_sequence[expected_idx]:
                        expected_idx += 1
                    # Allow other event types between expected ones
            
            if expected_idx < len(expected_sequence):
                out_of_order = expected_sequence[expected_idx:]
            
            return {
                "is_valid": len(missing) == 0 and len(out_of_order) == 0,
                "missing_events": missing,
                "incomplete_sequence": out_of_order,
                "actual_sequence": event_types,
            }
    except Exception as e:
        logger.error(f"Database error while verifying event sequence: {e}")
        return {"is_valid": False, "error": str(e)}


async def find_missing_expected_events(db_pool, correlation_id: str, expected_sequence: List[str]) -> List[str]:
    """Returns expected event types that do not exist in the correlation timeline."""
    query = """
        SELECT DISTINCT event_type
        FROM events
        WHERE correlation_id = $1;
    """
    try:
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, correlation_id)
            present = {row["event_type"] for row in rows}
            return [event_type for event_type in expected_sequence if event_type not in present]
    except Exception as e:
        logger.error(f"Database error while finding missing expected events: {e}")
        return expected_sequence


async def detect_correlation_chain_breaks(
    db_pool,
    correlation_id: str,
    expected_sequence: List[str],
) -> List[Dict[str, Any]]:
    """
    Detects ordering inversions relative to expected sequence.
    Example break: message_sent appears before lead_scored.
    """
    query = """
        SELECT event_type, timestamp
        FROM events
        WHERE correlation_id = $1
        ORDER BY timestamp ASC;
    """
    try:
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, correlation_id)

        expected_positions = {event_type: idx for idx, event_type in enumerate(expected_sequence)}
        breaks: List[Dict[str, Any]] = []
        prev_idx = -1
        prev_event = None

        for row in rows:
            current = row["event_type"]
            if current not in expected_positions:
                continue

            current_idx = expected_positions[current]
            if current_idx < prev_idx:
                breaks.append(
                    {
                        "previous_event": prev_event,
                        "current_event": current,
                        "previous_expected_position": prev_idx,
                        "current_expected_position": current_idx,
                        "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
                    }
                )

            prev_idx = max(prev_idx, current_idx)
            prev_event = current

        return breaks
    except Exception as e:
        logger.error(f"Database error while detecting correlation chain breaks: {e}")
        return []


async def record_integrity_alert(
    db_pool,
    alert_id: str,
    correlation_id: str,
    issue_type: str,
    message: str,
    details: Dict[str, Any],
    severity: str = "warning",
) -> bool:
    """
    Records an integrity alert for a correlation.
    """
    query = """
    INSERT INTO integrity_alerts (alert_id, correlation_id, issue_type, message, details, severity, status, is_resolved, timestamp, updated_at)
    VALUES ($1, $2, $3, $4, $5, $6, 'open', FALSE, timezone('utc', now()), timezone('utc', now()))
    ON CONFLICT (alert_id) DO NOTHING;
    """
    try:
        async with db_pool.acquire() as connection:
            result = await connection.execute(
                query,
                alert_id,
                correlation_id,
                issue_type,
                message,
                json.dumps(details),
                severity,
            )
            return result.endswith("1")
    except Exception as e:
        logger.error(f"Failed to record integrity alert {alert_id}: {e}")
        raise


async def list_integrity_alerts(
    db_pool,
    status: str | None = None,
    severity: str | None = None,
    correlation_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[List[Dict[str, Any]], int]:
    """Lists integrity alerts with optional filters and pagination."""
    bounded_limit = max(1, min(limit, 500))
    bounded_offset = max(0, offset)

    conditions: List[str] = []
    params: List[Any] = []

    if status:
        params.append(status)
        conditions.append(f"status = ${len(params)}")
    if severity:
        params.append(severity)
        conditions.append(f"severity = ${len(params)}")
    if correlation_id:
        params.append(correlation_id)
        conditions.append(f"correlation_id = ${len(params)}")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    count_query = f"SELECT COUNT(*) FROM integrity_alerts {where_clause};"
    list_query = f"""
        SELECT alert_id, correlation_id, issue_type, message, details, severity, status, is_resolved,
               acknowledged_at, resolved_at, timestamp, updated_at, created_at
        FROM integrity_alerts
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2};
    """

    try:
        async with db_pool.acquire() as connection:
            total = await connection.fetchval(count_query, *params)
            rows = await connection.fetch(list_query, *(params + [bounded_limit, bounded_offset]))
            return ([_normalize_event_row(row) for row in rows], total)
    except Exception as e:
        logger.error(f"Database error while listing integrity alerts: {e}")
        return ([], 0)


async def get_integrity_alert(db_pool, alert_id: str) -> Dict[str, Any] | None:
    """Returns one integrity alert by ID."""
    query = """
        SELECT alert_id, correlation_id, issue_type, message, details, severity, status, is_resolved,
               acknowledged_at, resolved_at, timestamp, updated_at, created_at
        FROM integrity_alerts
        WHERE alert_id = $1;
    """
    try:
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(query, alert_id)
            return _normalize_event_row(row) if row else None
    except Exception as e:
        logger.error(f"Database error while fetching alert {alert_id}: {e}")
        return None


async def update_integrity_alert_status(db_pool, alert_id: str, target_status: str) -> Dict[str, Any] | None:
    """Updates alert status for acknowledge/resolve transitions."""
    if target_status not in {"acknowledged", "resolved"}:
        raise ValueError("target_status must be 'acknowledged' or 'resolved'")

    if target_status == "acknowledged":
        query = """
            UPDATE integrity_alerts
            SET status = 'acknowledged', acknowledged_at = timezone('utc', now()), updated_at = timezone('utc', now())
            WHERE alert_id = $1 AND status IN ('open', 'acknowledged')
            RETURNING alert_id, correlation_id, issue_type, message, details, severity, status, is_resolved,
                      acknowledged_at, resolved_at, timestamp, updated_at, created_at;
        """
    else:
        query = """
            UPDATE integrity_alerts
            SET status = 'resolved', is_resolved = TRUE, resolved_at = timezone('utc', now()), updated_at = timezone('utc', now())
            WHERE alert_id = $1 AND status IN ('open', 'acknowledged', 'resolved')
            RETURNING alert_id, correlation_id, issue_type, message, details, severity, status, is_resolved,
                      acknowledged_at, resolved_at, timestamp, updated_at, created_at;
        """

    try:
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(query, alert_id)
            return _normalize_event_row(row) if row else None
    except Exception as e:
        logger.error(f"Database error while updating alert {alert_id} status: {e}")
        return None


async def archive_integrity_alert(db_pool, alert_id: str) -> bool:
    """Archives an alert by setting status to archived."""
    query = """
        UPDATE integrity_alerts
        SET status = 'archived', updated_at = timezone('utc', now())
        WHERE alert_id = $1
    """
    try:
        async with db_pool.acquire() as connection:
            result = await connection.execute(query, alert_id)
            return result.endswith("1")
    except Exception as e:
        logger.error(f"Database error while archiving alert {alert_id}: {e}")
        return False


# ============ METRICS QUERY METHODS ============

async def get_events_for_metrics(db_pool, correlation_id: str | None = None) -> Dict[str, Any]:
    """
    Retrieves aggregated event counts grouped by event_type for KPI calculation.
    Optionally filtered by correlation_id.
    """
    if correlation_id:
        query = """
            SELECT event_type, COUNT(*) as count
            FROM events
            WHERE correlation_id = $1
            GROUP BY event_type;
        """
        params = [correlation_id]
    else:
        query = """
            SELECT event_type, COUNT(*) as count
            FROM events
            GROUP BY event_type;
        """
        params = []
    
    try:
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, *params)
            return {row['event_type']: row['count'] for row in rows}
    except Exception as e:
        logger.error(f"Database error while fetching metrics: {e}")
        return {}


# ============ PHASE 2: OUTCOME AGGREGATION METHODS ============

async def get_outcome_statistics(db_pool, correlation_id: str | None = None) -> Dict[str, int]:
    """
    Retrieves outcome statistics grouped by outcome_type.
    If correlation_id is provided, stats are scoped to that correlation.
    """
    if correlation_id:
        query = """
            SELECT outcome_type, COUNT(*) as count
            FROM outcomes
            WHERE correlation_id = $1
            GROUP BY outcome_type;
        """
        params = [correlation_id]
    else:
        query = """
            SELECT outcome_type, COUNT(*) as count
            FROM outcomes
            GROUP BY outcome_type;
        """
        params = []

    try:
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, *params)
            return {row["outcome_type"]: row["count"] for row in rows}
    except Exception as e:
        logger.error(f"Database error while fetching outcome statistics: {e}")
        return {}


async def list_outcomes(
    db_pool,
    correlation_id: str | None = None,
    outcome_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[List[Dict[str, Any]], int]:
    """Lists outcomes with optional filters and returns (items, total)."""
    bounded_limit = max(1, min(limit, 500))
    bounded_offset = max(0, offset)

    conditions: List[str] = []
    params: List[Any] = []

    if correlation_id:
        params.append(correlation_id)
        conditions.append(f"correlation_id = ${len(params)}")
    if outcome_type:
        params.append(outcome_type)
        conditions.append(f"outcome_type = ${len(params)}")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    count_query = f"SELECT COUNT(*) FROM outcomes {where_clause};"
    list_query = f"""
        SELECT outcome_id, correlation_id, linked_event_id, outcome_type, value, timestamp
        FROM outcomes
        {where_clause}
        ORDER BY timestamp DESC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2};
    """

    try:
        async with db_pool.acquire() as connection:
            total = await connection.fetchval(count_query, *params)
            rows = await connection.fetch(list_query, *(params + [bounded_limit, bounded_offset]))
            return ([_normalize_event_row(row) for row in rows], total)
    except Exception as e:
        logger.error(f"Database error while listing outcomes: {e}")
        return ([], 0)


async def get_outcome_by_id(db_pool, outcome_id: str) -> Dict[str, Any] | None:
    """Retrieves one outcome by its ID."""
    query = """
        SELECT outcome_id, correlation_id, linked_event_id, outcome_type, value, timestamp
        FROM outcomes
        WHERE outcome_id = $1;
    """
    try:
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(query, outcome_id)
            return _normalize_event_row(row) if row else None
    except Exception as e:
        logger.error(f"Database error while fetching outcome {outcome_id}: {e}")
        return None


async def correlate_events_to_outcomes(db_pool, correlation_id: str) -> Dict[str, Any]:
    """Builds an event->outcomes map for a correlation timeline."""
    query = """
        SELECT
            e.event_id,
            e.event_type,
            e.timestamp AS event_timestamp,
            ARRAY_AGG(
                JSON_BUILD_OBJECT(
                    'outcome_id', o.outcome_id,
                    'outcome_type', o.outcome_type,
                    'timestamp', o.timestamp,
                    'value', o.value
                )
            ) FILTER (WHERE o.outcome_id IS NOT NULL) AS outcomes
        FROM events e
        LEFT JOIN outcomes o ON e.event_id = o.linked_event_id
        WHERE e.correlation_id = $1
        GROUP BY e.event_id, e.event_type, e.timestamp
        ORDER BY e.timestamp ASC;
    """
    try:
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, correlation_id)

        result: Dict[str, Any] = {}
        for row in rows:
            event_id = str(row["event_id"])
            outcomes = row["outcomes"] or []
            result[event_id] = {
                "event_id": event_id,
                "event_type": row["event_type"],
                "event_timestamp": row["event_timestamp"].isoformat() if row["event_timestamp"] else None,
                "outcomes": outcomes,
            }
        return result
    except Exception as e:
        logger.error(f"Database error while correlating events to outcomes: {e}")
        return {}


async def get_total_correlations(db_pool) -> int:
    """Returns count of distinct correlations observed in events."""
    query = "SELECT COUNT(DISTINCT correlation_id) FROM events;"
    try:
        async with db_pool.acquire() as connection:
            return await connection.fetchval(query)
    except Exception as e:
        logger.error(f"Database error while counting correlations: {e}")
        return 0


async def record_graph_sync_checkpoint(
    db_pool,
    correlation_id: str,
    last_event_id: str | None,
    last_event_timestamp: str | None,
    projected_nodes: int,
    projected_edges: int,
    sync_status: str = "synced",
) -> bool:
    """Records or updates a replay-safe graph sync checkpoint."""
    query = """
        INSERT INTO graph_sync_checkpoints (
            correlation_id,
            last_event_id,
            last_event_timestamp,
            projected_nodes,
            projected_edges,
            sync_status,
            synced_at,
            updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, timezone('utc', now()), timezone('utc', now()))
        ON CONFLICT (correlation_id) DO UPDATE SET
            last_event_id = EXCLUDED.last_event_id,
            last_event_timestamp = EXCLUDED.last_event_timestamp,
            projected_nodes = EXCLUDED.projected_nodes,
            projected_edges = EXCLUDED.projected_edges,
            sync_status = EXCLUDED.sync_status,
            synced_at = timezone('utc', now()),
            updated_at = timezone('utc', now());
    """
    try:
        async with db_pool.acquire() as connection:
            result = await connection.execute(
                query,
                correlation_id,
                last_event_id,
                _coerce_datetime(last_event_timestamp) if last_event_timestamp is not None else None,
                projected_nodes,
                projected_edges,
                sync_status,
            )
            return result.startswith("INSERT") or result.startswith("UPDATE")
    except Exception as e:
        logger.error(f"Database error while recording graph sync checkpoint: {e}")
        return False


async def get_graph_sync_checkpoint(db_pool, correlation_id: str) -> Dict[str, Any] | None:
    """Returns the latest graph sync checkpoint for a correlation."""
    query = """
        SELECT correlation_id, last_event_id, last_event_timestamp, projected_nodes, projected_edges,
               sync_status, synced_at, updated_at, created_at
        FROM graph_sync_checkpoints
        WHERE correlation_id = $1;
    """
    try:
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(query, correlation_id)
            return _normalize_event_row(row) if row else None
    except Exception as e:
        logger.error(f"Database error while fetching graph sync checkpoint: {e}")
        return None


async def verify_graph_parity(db_pool, graph_adapter, correlation_id: str) -> Dict[str, Any]:
    """Compares Postgres-derived counts with graph trace counts for a correlation."""
    events = await get_events_by_correlation_id(db_pool, correlation_id)
    outcomes = await get_outcomes_by_correlation_id(db_pool, correlation_id)

    postgres_nodes = 1 + len(events) + len(outcomes)
    postgres_edges = len(events) + len(outcomes)

    if graph_adapter and getattr(graph_adapter, "available", False):
        trace = await graph_adapter.trace_correlation(correlation_id)
        graph_nodes = len(trace.get("nodes", []))
        graph_edges = len(trace.get("relationships", []))
        graph_available = True
    else:
        graph_nodes = postgres_nodes
        graph_edges = postgres_edges
        graph_available = False

    return {
        "correlation_id": correlation_id,
        "graph_available": graph_available,
        "postgres_nodes": postgres_nodes,
        "postgres_edges": postgres_edges,
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
        "is_parity_ok": postgres_nodes == graph_nodes and postgres_edges == graph_edges,
    }


async def create_optimization_recommendation(
    db_pool,
    recommendation_id: str,
    recommendation_type: str,
    summary: str,
    payload: Dict[str, Any],
    confidence: float = 0.5,
    correlation_id: str | None = None,
) -> bool:
    """Stores an optimization recommendation in proposed state."""
    query = """
        INSERT INTO optimization_recommendations (
            recommendation_id,
            correlation_id,
            recommendation_type,
            summary,
            payload,
            confidence,
            status,
            updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, 'proposed', timezone('utc', now()))
        ON CONFLICT (recommendation_id) DO NOTHING;
    """
    try:
        async with db_pool.acquire() as connection:
            result = await connection.execute(
                query,
                recommendation_id,
                correlation_id,
                recommendation_type,
                summary,
                json.dumps(payload),
                confidence,
            )
            return result.endswith("1")
    except Exception as e:
        logger.error(f"Database error while creating optimization recommendation: {e}")
        return False


async def list_optimization_recommendations(
    db_pool,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[List[Dict[str, Any]], int]:
    """Returns optimization recommendations with optional status filter."""
    bounded_limit = max(1, min(limit, 500))
    bounded_offset = max(0, offset)

    params: List[Any] = []
    where_clause = ""
    if status:
        params.append(status)
        where_clause = f"WHERE status = ${len(params)}"

    count_query = f"SELECT COUNT(*) FROM optimization_recommendations {where_clause};"
    list_query = f"""
         SELECT recommendation_id, correlation_id, recommendation_type, summary, payload, confidence,
             status, approved_by, approved_at, rejected_by, rejected_at, applied_by, applied_at,
             rolled_back_by, rolled_back_at,
             created_at, updated_at
        FROM optimization_recommendations
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2};
    """

    try:
        async with db_pool.acquire() as connection:
            total = await connection.fetchval(count_query, *params)
            rows = await connection.fetch(list_query, *(params + [bounded_limit, bounded_offset]))
            return ([_normalize_event_row(row) for row in rows], total)
    except Exception as e:
        logger.error(f"Database error while listing optimization recommendations: {e}")
        return ([], 0)


async def get_optimization_recommendation(db_pool, recommendation_id: str) -> Dict[str, Any] | None:
    """Returns one optimization recommendation by id."""
    query = """
         SELECT recommendation_id, correlation_id, recommendation_type, summary, payload, confidence,
               status, approved_by, approved_at, rejected_by, rejected_at, applied_by, applied_at,
               rolled_back_by, rolled_back_at,
             created_at, updated_at
        FROM optimization_recommendations
        WHERE recommendation_id = $1;
    """
    try:
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(query, recommendation_id)
            return _normalize_event_row(row) if row else None
    except Exception as e:
        logger.error(f"Database error while fetching optimization recommendation {recommendation_id}: {e}")
        return None


async def approve_optimization_recommendation(
    db_pool,
    recommendation_id: str,
    approved_by: str | None = None,
) -> Dict[str, Any] | None:
    """Approves a recommendation without applying changes to upstream modules."""
    query = """
        UPDATE optimization_recommendations
        SET status = 'approved',
            approved_by = COALESCE($2, approved_by),
            approved_at = timezone('utc', now()),
            updated_at = timezone('utc', now())
        WHERE recommendation_id = $1
                    AND status IN ('proposed', 'approved')
        RETURNING recommendation_id, correlation_id, recommendation_type, summary, payload, confidence,
                                    status, approved_by, approved_at, rejected_by, rejected_at, applied_by, applied_at,
                                    rolled_back_by, rolled_back_at,
                                    created_at, updated_at;
    """
    try:
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(query, recommendation_id, approved_by)
            return _normalize_event_row(row) if row else None
    except Exception as e:
        logger.error(f"Database error while approving optimization recommendation {recommendation_id}: {e}")
        return None


async def reject_optimization_recommendation(
    db_pool,
    recommendation_id: str,
    rejected_by: str | None = None,
) -> Dict[str, Any] | None:
    """Rejects a recommendation without applying changes upstream."""
    query = """
        UPDATE optimization_recommendations
        SET status = 'rejected',
            rejected_by = COALESCE($2, rejected_by),
            rejected_at = timezone('utc', now()),
            updated_at = timezone('utc', now())
        WHERE recommendation_id = $1
          AND status IN ('proposed', 'rejected')
        RETURNING recommendation_id, correlation_id, recommendation_type, summary, payload, confidence,
                                    status, approved_by, approved_at, rejected_by, rejected_at, applied_by, applied_at,
                                    rolled_back_by, rolled_back_at,
                  created_at, updated_at;
    """
    try:
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(query, recommendation_id, rejected_by)
            return _normalize_event_row(row) if row else None
    except Exception as e:
        logger.error(f"Database error while rejecting optimization recommendation {recommendation_id}: {e}")
        return None


async def rollback_optimization_recommendation(
    db_pool,
    recommendation_id: str,
    rolled_back_by: str | None = None,
) -> Dict[str, Any] | None:
    """Marks an approved recommendation as rolled back for audit/control."""
    query = """
        UPDATE optimization_recommendations
        SET status = 'rolled_back',
            rolled_back_by = COALESCE($2, rolled_back_by),
            rolled_back_at = timezone('utc', now()),
            updated_at = timezone('utc', now())
        WHERE recommendation_id = $1
                    AND status IN ('approved', 'applied', 'rolled_back')
        RETURNING recommendation_id, correlation_id, recommendation_type, summary, payload, confidence,
                                    status, approved_by, approved_at, rejected_by, rejected_at, applied_by, applied_at,
                                    rolled_back_by, rolled_back_at,
                  created_at, updated_at;
    """
    try:
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(query, recommendation_id, rolled_back_by)
            return _normalize_event_row(row) if row else None
    except Exception as e:
        logger.error(f"Database error while rolling back optimization recommendation {recommendation_id}: {e}")
        return None


async def apply_optimization_recommendation(
    db_pool,
    recommendation_id: str,
    applied_by: str | None = None,
) -> Dict[str, Any] | None:
    """Marks an approved recommendation as applied (idempotent)."""
    query = """
        UPDATE optimization_recommendations
        SET status = 'applied',
            applied_by = COALESCE($2, applied_by),
            applied_at = timezone('utc', now()),
            updated_at = timezone('utc', now())
        WHERE recommendation_id = $1
          AND status IN ('approved', 'applied')
        RETURNING recommendation_id, correlation_id, recommendation_type, summary, payload, confidence,
                  status, approved_by, approved_at, rejected_by, rejected_at, applied_by, applied_at,
                  rolled_back_by, rolled_back_at, created_at, updated_at;
    """
    try:
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(query, recommendation_id, applied_by)
            return _normalize_event_row(row) if row else None
    except Exception as e:
        logger.error(f"Database error while applying optimization recommendation {recommendation_id}: {e}")
        return None


async def is_recommendation_type_in_cooldown(
    db_pool,
    recommendation_type: str,
    cooldown_hours: int,
    correlation_id: str | None = None,
) -> bool:
    """Checks whether a recommendation type was recently emitted inside cooldown window."""
    bounded_cooldown = max(0, cooldown_hours)
    if bounded_cooldown == 0:
        return False

    if correlation_id:
        query = """
            SELECT 1
            FROM optimization_recommendations
            WHERE recommendation_type = $1
              AND correlation_id = $2
                            AND status IN ('proposed', 'approved', 'applied')
              AND created_at >= (timezone('utc', now()) - make_interval(hours => $3::int))
            LIMIT 1;
        """
        params: List[Any] = [recommendation_type, correlation_id, bounded_cooldown]
    else:
        query = """
            SELECT 1
            FROM optimization_recommendations
            WHERE recommendation_type = $1
                            AND status IN ('proposed', 'approved', 'applied')
              AND created_at >= (timezone('utc', now()) - make_interval(hours => $2::int))
            LIMIT 1;
        """
        params = [recommendation_type, bounded_cooldown]

    try:
        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(query, *params)
            return row is not None
    except Exception as e:
        logger.error(f"Database error while checking recommendation cooldown: {e}")
        return False


async def list_optimization_audit_events(
    db_pool,
    recommendation_id: str | None = None,
    correlation_id: str | None = None,
    approved_by: str | None = None,
    status: str | None = None,
    event_type: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[List[Dict[str, Any]], int]:
    """Lists optimization approval audit events from the canonical events table."""
    bounded_limit = max(1, min(limit, 500))
    bounded_offset = max(0, offset)

    allowed_event_types = {
        "optimization_recommendation_approved",
        "optimization_recommendation_rejected",
        "optimization_recommendation_dry_run",
        "optimization_recommendation_applied",
        "optimization_recommendation_rolled_back",
        "optimization_apply_allowed",
        "optimization_apply_blocked",
    }

    normalized_event_type = event_type if event_type in allowed_event_types else None

    params: List[Any] = [normalized_event_type] if normalized_event_type else [list(allowed_event_types)]
    conditions = ["event_type = $1" if normalized_event_type else "event_type = ANY($1::text[])"]

    if recommendation_id:
        params.append(recommendation_id)
        conditions.append(f"payload->>'recommendation_id' = ${len(params)}")

    if correlation_id:
        params.append(correlation_id)
        conditions.append(f"correlation_id = ${len(params)}")

    if approved_by:
        params.append(approved_by)
        conditions.append(
            f"COALESCE(metadata->>'approved_by', metadata->>'rejected_by', metadata->>'rolled_back_by', metadata->>'applied_by', metadata->>'acted_by') = ${len(params)}"
        )

    if status:
        params.append(status)
        conditions.append(f"payload->>'status' = ${len(params)}")

    if start_time:
        params.append(start_time)
        conditions.append(f"timestamp >= ${len(params)}::timestamptz")

    if end_time:
        params.append(end_time)
        conditions.append(f"timestamp <= ${len(params)}::timestamptz")

    where_clause = "WHERE " + " AND ".join(conditions)

    count_query = f"SELECT COUNT(*) FROM events {where_clause};"
    list_query = f"""
        SELECT event_id, correlation_id, module, event_type, timestamp, payload, metadata, created_at
        FROM events
        {where_clause}
        ORDER BY timestamp DESC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2};
    """

    try:
        async with db_pool.acquire() as connection:
            total = await connection.fetchval(count_query, *params)
            rows = await connection.fetch(list_query, *(params + [bounded_limit, bounded_offset]))
            return ([_normalize_event_row(row) for row in rows], total)
    except Exception as e:
        logger.error(f"Database error while listing optimization audit events: {e}")
        return ([], 0)


# ============ GLOBAL CONFIGURATION METHODS ============

async def get_global_config(db_pool) -> Dict[str, Any]:
    """
    Fetches the current global configuration state.
    Returns a dictionary of key -> value.
    """
    query = "SELECT config_key, config_value FROM global_config;"
    try:
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query)
            return {row["config_key"]: json.loads(row["config_value"]) if isinstance(row["config_value"], str) else row["config_value"] for row in rows}
    except asyncpg.exceptions.UndefinedTableError:
        logger.error("The 'global_config' table does not exist. Creating it now.")
        await create_events_table(db_pool)
        return {}
    except Exception as e:
        logger.error(f"Database error while fetching global config: {e}")
        return {}

async def update_global_config(db_pool, updates: Dict[str, Any]) -> bool:
    """
    Updates or inserts global configuration keys.
    """
    query = """
    INSERT INTO global_config (config_key, config_value, updated_at)
    VALUES ($1, $2, timezone('utc', now()))
    ON CONFLICT (config_key) DO UPDATE
    SET config_value = EXCLUDED.config_value, updated_at = EXCLUDED.updated_at;
    """
    try:
        async with db_pool.acquire() as connection:
            async with connection.transaction():
                for key, value in updates.items():
                    await connection.execute(query, key, json.dumps(value))
            return True
    except asyncpg.exceptions.UndefinedTableError:
        logger.error("The 'global_config' table does not exist. Creating it now.")
        await create_events_table(db_pool)
        return await update_global_config(db_pool, updates)
    except Exception as e:
        logger.error(f"Database error while updating global config: {e}")
        return False
