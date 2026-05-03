"""State definitions for the strategy agent."""

from typing import TypedDict, List, Optional
from pydantic import BaseModel, Field


class ActionPlan(BaseModel):
    step: int = Field(description="Chronological step number (1, 2, 3, ...)")
    channel: str = Field(description="Channel to use (LinkedIn, Email, SMS, Skip)")
    recommended_action: str = Field(
        description="Specific action to take (e.g. 'Like their last post and send a connection request')"
    )
    timing: str = Field(description="When to execute this step (e.g. 'Day 0', 'Day +2')")
    justification: str = Field(
        description="Why this channel and action were chosen for this specific prospect"
    )


class StrategyOutput(BaseModel):
    sequence: List[ActionPlan] = Field(description="Ordered list of prospecting steps")


class AgentState(TypedDict):
    # Inputs
    prospect_name: str
    has_email: bool
    has_phone: bool
    recent_posts_context: str  # Summary of the prospect's recent LinkedIn activity

    # Output
    final_plan: Optional[StrategyOutput]
