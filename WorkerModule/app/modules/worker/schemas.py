"""
Event schema registry for WorkerModule.

Defines canonical event payload schemas and a validation API that supports
gradual rollout modes (warn vs enforce) in API handlers.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Canonical event type schemas (v1 — extended in Phase 5)
EVENT_SCHEMAS = {
    "lead_ingested": {
        "company": str,
        "contact": {"name": str, "email": str},
    },
    "lead_scored": {
        "score": int,
        "reason": str,
    },
    "message_generated": {
        "subject": str,
        "body": str,
        "strategy": str,
    },
    "message_sent": {
        "recipient": str,
        "channel": str,
        "timestamp": str,
    },
    "reply_received": {
        "sender": str,
        "body": str,
        "sentiment": str,
    },
    "conversion": {
        "type": str,
        "value": float,
    },
}


def _validate_schema_node(schema_node: Any, value: Any, path: str, errors: List[str]) -> None:
    if isinstance(schema_node, dict):
        if not isinstance(value, dict):
            errors.append(f"{path}: expected object")
            return
        for key, child_schema in schema_node.items():
            child_path = f"{path}.{key}"
            if key not in value:
                errors.append(f"{child_path}: required field missing")
                continue
            _validate_schema_node(child_schema, value[key], child_path, errors)
        return

    if isinstance(schema_node, type):
        # bool is a subclass of int in Python; reject bool for integer fields.
        if schema_node is int and isinstance(value, bool):
            errors.append(f"{path}: expected int, got bool")
            return
        if not isinstance(value, schema_node):
            errors.append(
                f"{path}: expected {schema_node.__name__}, got {type(value).__name__}"
            )
        return

    errors.append(f"{path}: unsupported schema definition")


def validate_event_payload(
    event_type: str,
    payload: Dict[str, Any],
    allow_unknown_event_type: bool = True,
) -> Dict[str, Any]:
    """
    Validate payload against canonical schema.

    Returns:
    - is_valid: bool
    - warnings: list[str]
    - errors: list[str]
    """
    warnings: List[str] = []
    errors: List[str] = []

    if not isinstance(payload, dict):
        errors.append("payload: expected object")
        return {"is_valid": False, "warnings": warnings, "errors": errors}

    schema = EVENT_SCHEMAS.get(event_type)
    if schema is None:
        msg = f"event_type '{event_type}' is not in canonical schema registry"
        if allow_unknown_event_type:
            warnings.append(msg)
            return {"is_valid": True, "warnings": warnings, "errors": errors}
        errors.append(msg)
        return {"is_valid": False, "warnings": warnings, "errors": errors}

    _validate_schema_node(schema, payload, "payload", errors)
    return {"is_valid": len(errors) == 0, "warnings": warnings, "errors": errors}


def get_event_schema(event_type: str) -> Dict[str, Any]:
    """Returns the schema for an event type, or None if not canonical."""
    return EVENT_SCHEMAS.get(event_type)
