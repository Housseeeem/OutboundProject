from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import Request

try:
    from neo4j import AsyncGraphDatabase
except Exception:  # pragma: no cover - dependency may be missing in some environments
    AsyncGraphDatabase = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


class GraphAdapter:
    """
    Neo4j-backed graph adapter used for Worker traceability reads/writes.
    """

    def __init__(self, url: str, user: str, password: str) -> None:
        self.url = url
        self.user = user
        self.password = password
        self._driver = None
        self._available = False

    async def connect(self) -> None:
        if self._driver is not None:
            self._available = True
            return
        if AsyncGraphDatabase is None:
            self._available = False
            raise RuntimeError("neo4j driver is not installed")
        try:
            self._driver = AsyncGraphDatabase.driver(
                self.url,
                auth=(self.user, self.password),
            )
            await self._driver.verify_connectivity()
            self._available = True
        except Exception as exc:
            self._driver = None
            self._available = False
            raise RuntimeError(f"neo4j unavailable: {exc}") from exc

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    @staticmethod
    def _sanitize_token(value: str, default: str = "GraphEntity") -> str:
        token = re.sub(r"[^A-Za-z0-9_]", "_", value or default).strip("_")
        return token or default

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {str(key): GraphAdapter._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [GraphAdapter._json_safe(item) for item in value]
        return str(value)

    async def _ensure_driver(self) -> None:
        if self._driver is None:
            await self.connect()
        if not self._available or self._driver is None:
            raise RuntimeError("neo4j graph adapter is unavailable")

    async def add_node(self, node_type: str, properties: dict) -> None:
        await self._ensure_driver()
        assert self._driver is not None

        node_id = str(properties.get("node_id") or properties.get("event_id") or properties.get("outcome_id") or properties.get("correlation_id"))
        safe_properties = self._json_safe(properties)
        safe_properties.setdefault("node_id", node_id)
        safe_properties.setdefault("entity_type", node_type)

        query = """
        MERGE (n:GraphEntity {node_id: $node_id})
        SET n += $properties
        RETURN n.node_id AS node_id
        """

        async with self._driver.session() as session:
            await session.run(query, node_id=node_id, properties=safe_properties)

    async def add_edge(
        self,
        from_node: str,
        to_node: str,
        relation_type: str,
        weight: float = 1.0,
        properties: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self._ensure_driver()
        assert self._driver is not None

        relation_label = self._sanitize_token(relation_type, default="RELATED_TO").upper()
        safe_properties = self._json_safe(properties or {})
        safe_properties.setdefault("relation_type", relation_type)
        safe_properties.setdefault("weight", weight)

        query = f"""
        MERGE (a:GraphEntity {{node_id: $from_node}})
        SET a.entity_type = coalesce(a.entity_type, 'graph_entity')
        MERGE (b:GraphEntity {{node_id: $to_node}})
        SET b.entity_type = coalesce(b.entity_type, 'graph_entity')
        MERGE (a)-[r:{relation_label}]->(b)
        SET r += $properties
        RETURN type(r) AS relation_type
        """

        async with self._driver.session() as session:
            await session.run(
                query,
                from_node=str(from_node),
                to_node=str(to_node),
                properties=safe_properties,
            )

    async def trace_correlation(self, correlation_id: str) -> Dict[str, Any]:
        await self._ensure_driver()
        assert self._driver is not None

        query = """
        MATCH p=(c:GraphEntity {node_id: $correlation_id})-[*0..4]-()
        WITH collect(p) AS paths
        UNWIND paths AS path
        UNWIND nodes(path) AS node
        UNWIND relationships(path) AS rel
        RETURN collect(DISTINCT node) AS nodes, collect(DISTINCT rel) AS relationships
        """

        async with self._driver.session() as session:
            result = await session.run(query, correlation_id=str(correlation_id))
            record = await result.single()

        if not record:
            return {"nodes": [], "relationships": []}

        return {
            "nodes": [self._record_to_dict(node) for node in record["nodes"] if node is not None],
            "relationships": [self._record_to_dict(rel) for rel in record["relationships"] if rel is not None],
        }

    async def trace_lead(self, lead_id: str) -> Dict[str, Any]:
        await self._ensure_driver()
        assert self._driver is not None

        query = """
        MATCH p=(l:GraphEntity {entity_type: 'lead', lead_id: $lead_id})-[*0..4]-()
        WITH collect(p) AS paths
        UNWIND paths AS path
        UNWIND nodes(path) AS node
        UNWIND relationships(path) AS rel
        RETURN collect(DISTINCT node) AS nodes, collect(DISTINCT rel) AS relationships
        """

        async with self._driver.session() as session:
            result = await session.run(query, lead_id=str(lead_id))
            record = await result.single()

        if not record:
            return {"nodes": [], "relationships": []}

        return {
            "nodes": [self._record_to_dict(node) for node in record["nodes"] if node is not None],
            "relationships": [self._record_to_dict(rel) for rel in record["relationships"] if rel is not None],
        }

    async def trace_impact(self, metric: str, window: str) -> Dict[str, Any]:
        await self._ensure_driver()
        assert self._driver is not None

        query = """
        MATCH p=(m:GraphEntity {entity_type: 'business_metric', metric: $metric, window: $window})-[*0..4]-()
        WITH collect(p) AS paths
        UNWIND paths AS path
        UNWIND nodes(path) AS node
        UNWIND relationships(path) AS rel
        RETURN collect(DISTINCT node) AS nodes, collect(DISTINCT rel) AS relationships
        """

        async with self._driver.session() as session:
            result = await session.run(query, metric=metric, window=window)
            record = await result.single()

        if not record:
            return {"nodes": [], "relationships": []}

        return {
            "nodes": [self._record_to_dict(node) for node in record["nodes"] if node is not None],
            "relationships": [self._record_to_dict(rel) for rel in record["relationships"] if rel is not None],
        }

    @staticmethod
    def _record_to_dict(record: Any) -> Dict[str, Any]:
        data = dict(record)
        return {key: GraphAdapter._json_safe(value) for key, value in data.items()}


async def get_db_pool(request: Request):
    """FastAPI dependency to access the shared asyncpg pool."""
    return request.app.state.db_pool


async def get_graph_adapter(request: Request) -> GraphAdapter:
    """FastAPI dependency to access the shared graph adapter."""
    return request.app.state.graph_adapter
