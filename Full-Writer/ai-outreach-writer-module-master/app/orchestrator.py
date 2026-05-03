from typing import List, Optional
import uuid
import logging

from .models import (
    AgentState, Status, Personality, CompanyDetails,
    SelectedOffer, Channel, Intent, Stage
)
from .graph import run_pipeline
from .config import settings

logger = logging.getLogger("app.orchestrator")


class PipelineOrchestrator:
    """
    Public interface unchanged — main.py calls this exactly as before.
    Internally delegates to the LangGraph pipeline (graph.py) instead
    of the old manual while-loop.
    """

    def __init__(
        self,
        target_prospect: str,
        target_company: str,
        prospect_role: Optional[str],
        channel: Channel,
        intent: Intent,
        stage: Stage,
        personality: Personality,
        company_details: CompanyDetails,
        selected_offer: SelectedOffer
    ):
        self.initial_state = AgentState(
            task_id=str(uuid.uuid4()),
            target_prospect=target_prospect,
            target_company=target_company,
            prospect_role=prospect_role,
            channel=channel,
            intent=intent,
            stage=stage,
            personality=personality,
            company_details=company_details,
            selected_offer=selected_offer,
            status=Status.PLANNING,
            iteration_count=0,
            max_iterations=settings.MAX_ITERATIONS
        )

    def run_full_pipeline(self) -> List[AgentState]:
        """Run the LangGraph pipeline and return the full step history.

        If the pipeline fails but the critic produced actionable suggested_fixes
        (for example 'Too short'), attempt automated revisions up to
        `max_iterations` to try and produce a valid draft before returning.
        """
        history = run_pipeline(self.initial_state)

        # Inspect the final state and, if applicable, perform automated revision loops
        final = history[-1]
        attempts = 0
        # Use the configured max iterations from the state (copied from settings)
        max_iter = getattr(self.initial_state, "max_iterations", 3) or 3

        # Allow automated revision if the final state either failed or explicitly requested revising.
        while (
            final.status in (Status.FAILED, Status.REVISING)
            and getattr(final, "validation", None)
            and final.validation.suggested_fixes
            and getattr(final, "iteration_count", 0) <= max_iter  # Changed from < to <= to allow orchestrator revisions after graph looping
            and attempts < max_iter
        ):
            attempts += 1
            # Prepare a revision start state using the final state's data
            revised = final.model_copy(deep=True)
            revised.status = Status.REVISING
            revised.next_action = {
                "type": "retry",
                "reason": "Automated revision requested",
                "feedback": final.validation.suggested_fixes,
            }
            # Keep iteration_count so the critic/writer can use it
            revised.iteration_count = getattr(final, "iteration_count", 0)

            # Run pipeline from the revised state and append history (skip duplicate initial snapshot)
            new_history = run_pipeline(revised)
            # Append all snapshots except the first (which duplicates the revised initial state)
            history.extend(new_history[1:])
            final = history[-1]
        
        pass

        return history
