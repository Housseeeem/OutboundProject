"""Temporal activity — wraps the LangGraph strategy agent."""

from temporalio import activity
from agents.graph import app as strategy_agent


@activity.defn
async def generate_strategy_activity(input_data: dict) -> dict:
    """Run the strategy agent and return the plan as a plain dict.

    input_data must contain:
        prospect_name (str)
        has_email (bool)
        has_phone (bool)
        recent_posts_context (str)
    """
    try:
        result = strategy_agent.invoke(input_data)
        plan = result.get("final_plan")
        if plan:
            return plan.model_dump()
        return {"error": "Agent returned no plan."}
    except Exception as exc:
        return {"error": str(exc)}
