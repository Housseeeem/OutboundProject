"""
KPI Computation Service for WorkerModule.

Computes reply rates, conversion rates, and strategy performance metrics.
"""

import logging
from typing import Dict, Any, Optional

from app.modules.worker.storage import get_outcome_statistics

logger = logging.getLogger(__name__)


async def compute_reply_rate(db_pool, correlation_id: str) -> float:
    """
    Computes reply rate for a correlation.
    reply_rate = (count of reply_received outcomes) / (count of message_sent events)
    """
    try:
        query_sent = "SELECT COUNT(*) as count FROM events WHERE correlation_id = $1 AND event_type = 'message_sent';"

        async with db_pool.acquire() as connection:
            sent_count = await connection.fetchval(query_sent, correlation_id)

        outcome_counts = await get_outcome_statistics(db_pool, correlation_id)
        reply_count = outcome_counts.get("reply", 0)

        if sent_count == 0:
            return 0.0

        return reply_count / sent_count
    except Exception as e:
        logger.error(f"Failed to compute reply rate for {correlation_id}: {e}")
        return 0.0


async def compute_conversion_rate(db_pool, correlation_id: str) -> float:
    """
    Computes conversion rate for a correlation.
    conversion_rate = (count of conversion outcomes) / (count of reply_received outcomes)
    """
    try:
        outcome_counts = await get_outcome_statistics(db_pool, correlation_id)
        reply_count = outcome_counts.get("reply", 0)
        conversion_count = outcome_counts.get("conversion", 0)

        if reply_count == 0:
            return 0.0

        return conversion_count / reply_count
    except Exception as e:
        logger.error(f"Failed to compute conversion rate for {correlation_id}: {e}")
        return 0.0


async def compute_module_metrics(db_pool, module: str) -> Dict[str, int]:
    """
    Computes event count metrics for a module.
    Returns event counts grouped by event_type.
    """
    try:
        query = "SELECT event_type, COUNT(*) as count FROM events WHERE module = $1 GROUP BY event_type;"
        
        async with db_pool.acquire() as connection:
            rows = await connection.fetch(query, module)
        
        return {row['event_type']: row['count'] for row in rows}
    except Exception as e:
        logger.error(f"Failed to compute module metrics for {module}: {e}")
        return {}


async def compute_system_kpis(db_pool) -> Dict[str, Any]:
    """
    Computes system-wide KPI summary.
    """
    try:
        query_total_events = "SELECT COUNT(*) as count FROM events;"
        query_by_type = "SELECT event_type, COUNT(*) as count FROM events GROUP BY event_type;"
        query_correlations = "SELECT COUNT(DISTINCT correlation_id) as count FROM events;"
        
        async with db_pool.acquire() as connection:
            total_events = await connection.fetchval(query_total_events)
            event_types = await connection.fetch(query_by_type)
            total_correlations = await connection.fetchval(query_correlations)
        
        event_dist = {row['event_type']: row['count'] for row in event_types}
        
        return {
            "total_events": total_events,
            "total_correlations": total_correlations,
            "event_distribution": event_dist,
        }
    except Exception as e:
        logger.error(f"Failed to compute system KPIs: {e}")
        return {}
