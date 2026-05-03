"""Phase 5 optimization recommendation helpers (dry-run only)."""

from __future__ import annotations

from typing import Any, Dict, List


def _bounded_pct(value: float, max_abs_pct: float) -> float:
    """Bounds percentage recommendations to guardrail limits."""
    cap = abs(max_abs_pct)
    return max(-cap, min(cap, value))


def build_dry_run_recommendations(
    event_counts: Dict[str, int],
    outcome_counts: Dict[str, int],
    max_change_pct: float = 10.0,
    cooldown_hours: int = 24,
) -> List[Dict[str, Any]]:
    """Builds deterministic recommendations from telemetry without applying them."""
    message_sent = float(event_counts.get("message_sent", 0))
    replies = float(outcome_counts.get("reply", 0))
    conversions = float(outcome_counts.get("conversion", 0))

    reply_rate = replies / message_sent if message_sent > 0 else 0.0
    conversion_rate = conversions / replies if replies > 0 else 0.0

    recommendations: List[Dict[str, Any]] = []

    if message_sent == 0:
        return recommendations

    if reply_rate < 0.15:
        recommended_shift = _bounded_pct(8.0, max_change_pct)
        recommendations.append(
            {
                "recommendation_type": "message_experiment",
                "summary": "Low reply rate detected; increase exploratory message variants.",
                "confidence": 0.72,
                "payload": {
                    "signal": "reply_rate_low",
                    "current_reply_rate": round(reply_rate, 4),
                    "proposed_actions": [
                        {
                            "action": "increase_variant_share",
                            "target_segment": "all",
                            "delta_pct": recommended_shift,
                        },
                        {
                            "action": "refresh_subject_lines",
                            "count": 3,
                        },
                    ],
                    "guardrails": {
                        "max_change_pct": max_change_pct,
                        "cooldown_hours": cooldown_hours,
                        "mode": "dry_run",
                    },
                },
            }
        )

    if reply_rate >= 0.15 and conversion_rate < 0.20:
        recommended_shift = _bounded_pct(-6.0, max_change_pct)
        recommendations.append(
            {
                "recommendation_type": "qualification_tuning",
                "summary": "Replies are healthy but conversion is weak; tighten downstream qualification.",
                "confidence": 0.66,
                "payload": {
                    "signal": "conversion_rate_low",
                    "current_reply_rate": round(reply_rate, 4),
                    "current_conversion_rate": round(conversion_rate, 4),
                    "proposed_actions": [
                        {
                            "action": "adjust_followup_threshold",
                            "delta_pct": recommended_shift,
                        },
                        {
                            "action": "prioritize_high_intent_segments",
                            "window": "14d",
                        },
                    ],
                    "guardrails": {
                        "max_change_pct": max_change_pct,
                        "cooldown_hours": cooldown_hours,
                        "mode": "dry_run",
                    },
                },
            }
        )

    return recommendations


def evaluate_apply_policy(
    payload: Dict[str, Any],
    max_change_pct: float,
    allowed_actions: List[str],
    allowed_target_scopes: List[str],
) -> List[Dict[str, Any]]:
    """Returns policy violations for apply-mode recommendations."""
    violations: List[Dict[str, Any]] = []
    actions = payload.get("proposed_actions")

    if not isinstance(actions, list):
        return [
            {
                "code": "INVALID_PROPOSED_ACTIONS",
                "message": "payload.proposed_actions must be a list",
                "field": "payload.proposed_actions",
            }
        ]

    action_allowlist = set(allowed_actions)
    scope_allowlist = set(allowed_target_scopes)
    max_delta = abs(max_change_pct)

    for idx, action_item in enumerate(actions):
        if not isinstance(action_item, dict):
            violations.append(
                {
                    "code": "INVALID_ACTION_ITEM",
                    "message": "Each proposed action must be an object",
                    "field": f"payload.proposed_actions[{idx}]",
                }
            )
            continue

        action_name = action_item.get("action")
        if not isinstance(action_name, str) or action_name not in action_allowlist:
            violations.append(
                {
                    "code": "DISALLOWED_ACTION",
                    "message": f"Action '{action_name}' is not allowed for apply",
                    "field": f"payload.proposed_actions[{idx}].action",
                    "allowed_actions": sorted(action_allowlist),
                }
            )

        if "delta_pct" in action_item:
            try:
                delta_pct = float(action_item["delta_pct"])
            except (TypeError, ValueError):
                violations.append(
                    {
                        "code": "INVALID_DELTA_PCT",
                        "message": "delta_pct must be numeric",
                        "field": f"payload.proposed_actions[{idx}].delta_pct",
                    }
                )
            else:
                if abs(delta_pct) > max_delta:
                    violations.append(
                        {
                            "code": "MAX_CHANGE_EXCEEDED",
                            "message": f"delta_pct {delta_pct} exceeds max allowed {max_delta}",
                            "field": f"payload.proposed_actions[{idx}].delta_pct",
                            "max_change_pct": max_delta,
                        }
                    )

        for scope_key in ("target_segment", "target_scope"):
            if scope_key in action_item:
                scope_value = action_item.get(scope_key)
                if not isinstance(scope_value, str) or scope_value not in scope_allowlist:
                    violations.append(
                        {
                            "code": "DISALLOWED_TARGET_SCOPE",
                            "message": f"{scope_key} '{scope_value}' is not allowed",
                            "field": f"payload.proposed_actions[{idx}].{scope_key}",
                            "allowed_target_scopes": sorted(scope_allowlist),
                        }
                    )

    return violations
