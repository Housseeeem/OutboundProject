from typing import List, Dict, Any
import uuid
from .models import (
    AgentState, Status, Strategy, MessageDraft,
    SentenceAttribution, Validation, Signal, ActionType
)
from .tools import ResearchTools, ReasoningTools
from .llm_service import llm_service
from .config import settings
from .memory import MemoryService   # NEW

class AgentNodes:

    @staticmethod
    def planner(state: AgentState) -> AgentState:
        """Decides what step to run next based on what's missing"""
        needs_research = not state.research_signals
        needs_strategy = state.research_signals and not state.strategy
        needs_draft = state.strategy and not state.draft
        needs_validation = state.draft and not state.validation

        if needs_research:
            state.status = Status.RESEARCHING
            state.next_action = {
                "step": "research",
                "reason": "No research signals yet"
            }
        elif needs_strategy:
            state.status = Status.STRATEGIZING
            state.next_action = {
                "step": "strategize",
                "reason": "Research done, building strategy"
            }
        elif needs_draft:
            state.status = Status.WRITING
            state.next_action = {
                "step": "write",
                "reason": "Strategy ready, writing message"
            }
        elif needs_validation:
            state.status = Status.VALIDATING
            state.next_action = {
                "step": "validate",
                "reason": "Draft ready, validating quality"
            }
        else:
            state.status = Status.COMPLETE

        return state

    @staticmethod
    def researcher(state: AgentState) -> AgentState:
        """Gathers research signals and loads prospect memory"""

        # --- NEW: Load prospect memory ---
        prospect_memory = MemoryService.prospects.get_or_create(
            name=state.target_prospect,
            company=state.target_company,
            role=state.prospect_role
        )

        # --- NEW: Hard stop if do not contact ---
        if prospect_memory.do_not_contact:
            state.status = Status.FAILED
            state.next_action = {
                "type": ActionType.ABORT,
                "reason": f"{state.target_prospect} is marked as do not contact"
            }
            return state

        # --- NEW: Store memory context so strategist and writer can use it ---
        state.memory["prospect_record"] = prospect_memory.model_dump()
        state.memory["hooks_already_used"] = prospect_memory.hooks_used
        state.memory["angles_already_tried"] = prospect_memory.angles_tried
        state.memory["times_contacted_before"] = prospect_memory.times_contacted
        state.memory["ever_replied"] = prospect_memory.ever_replied

        # --- UNCHANGED: Normal research flow ---
        # NEW: Pass Detective enrichment data if available
        detective_ctx = state.memory.get("detective_context")

        linkedin_signals = ResearchTools.fetch_linkedin_posts(
            state.target_prospect,
            state.target_company,
            detective_context=detective_ctx
        )

        company_signals = ResearchTools.fetch_company_news(
            state.target_company
        )

        crm_data = ResearchTools.get_crm_history(
            state.target_prospect
        )

        state.research_signals = linkedin_signals + company_signals
        state.memory["crm_history"] = crm_data
        state.memory["total_signals_found"] = len(state.research_signals)
        state.status = Status.STRATEGIZING

        return state

    @staticmethod
    def strategist(state: AgentState) -> AgentState:
        """Uses LLM to pick hooks and build strategy"""

        if not state.research_signals:
            state.strategy = Strategy(
                primary_hook=f"Your work at {state.target_company}",
                secondary_hook="Industry developments",
                angle="General professional connection",
                tone=state.personality.base_template.value,
                cta_style=state.selected_offer.cta if state.selected_offer else "soft_question",
                reasoning="No research signals available"
            )
            state.status = Status.WRITING
            return state

        try:
            # NEW: Merge the Strategy Engine's channel sequencing logic
            detective_ctx = state.memory.get("detective_context", {})
            persona = detective_ctx.get("selected_persona", {})
            has_email = bool(persona.get("email"))
            has_phone = False  # Not captured in current persona schema
            
            sequence_plan = []
            if has_phone:
                sequence_plan = [
                    {"step": 1, "channel": "call", "timing": "Day 1"},
                    {"step": 2, "channel": "linkedin", "timing": "Day 2"},
                    {"step": 3, "channel": "email", "timing": "Day 4"}
                ]
            elif has_email:
                sequence_plan = [
                    {"step": 1, "channel": "email", "timing": "Day 1"},
                    {"step": 2, "channel": "linkedin", "timing": "Day 3"},
                    {"step": 3, "channel": "email", "timing": "Day 7"}
                ]
            else:
                sequence_plan = [
                    {"step": 1, "channel": "linkedin", "timing": "Day 1"},
                    {"step": 2, "channel": "linkedin", "timing": "Day 4"}
                ]
            state.memory["sequence_plan"] = sequence_plan

            # Step 1: Analyze signals
            analysis = llm_service.analyze_research_signals(
                signals=state.research_signals,
                prospect_name=state.target_prospect,
                company=state.target_company,
                personality=state.personality,
                # NEW: Pass what hooks we have already used so LLM avoids repeating them
                hooks_already_used=state.memory.get("hooks_already_used", [])
            )

            state.llm_calls.append({
                "step": "strategist",
                "purpose": "analyze_research_signals",
                "output": analysis
            })

            # Step 2: Build full strategy
            strategy = llm_service.create_strategy(
                primary_hook=analysis.get("primary_hook"),
                secondary_hook=analysis.get("secondary_hook"),
                prospect_name=state.target_prospect,
                company=state.target_company,
                prospect_role=state.prospect_role,
                personality=state.personality,
                company_details=state.company_details,
                selected_offer=state.selected_offer,
                channel=state.channel,
                intent=state.intent,
                stage=state.stage,
                # NEW: Pass what angles we have already tried so LLM avoids repeating them
                angles_already_tried=state.memory.get("angles_already_tried", [])
            )

            state.llm_calls.append({
                "step": "strategist",
                "purpose": "create_strategy",
                "output": strategy.dict()
            })

            state.strategy = strategy

        except Exception as e:
            state.strategy = Strategy(
                primary_hook=state.research_signals[0].content,
                secondary_hook=state.research_signals[1].content if len(state.research_signals) > 1 else "",
                angle="Professional connection",
                tone=state.personality.base_template.value,
                cta_style=state.selected_offer.cta if state.selected_offer else "soft_question",
                reasoning=f"Fallback due to error: {str(e)}"
            )
            state.memory["strategist_error"] = str(e)

        state.status = Status.WRITING
        return state

    @staticmethod
    def writer(state: AgentState) -> AgentState:
        """Uses LLM to write the message, or revise it based on feedback."""

        if not state.strategy:
            state.status = Status.PLANNING
            return state

        # --- NEW: Check if this is a revision call and get the feedback ---
        is_revision = state.status == Status.REVISING
        # When entering REVISING state from critic, increment iteration_count
        # so that internal graph loops are counted against max_iterations
        if is_revision:
            state.iteration_count += 1
        
        previous_draft = state.draft.body if is_revision and state.draft else None
        feedback = state.next_action.get("feedback") if is_revision and state.next_action else None

        try:
            message_data = llm_service.write_message(
                strategy=state.strategy,
                prospect_name=state.target_prospect,
                company=state.target_company,
                prospect_role=state.prospect_role,
                personality=state.personality,
                company_details=state.company_details,
                selected_offer=state.selected_offer,
                channel=state.channel,
                intent=state.intent,
                stage=state.stage,
                times_contacted_before=state.memory.get("times_contacted_before", 0),
                last_message_sent=state.memory.get("prospect_record", {}).get("last_message_sent"),
                
                # --- NEW: Pass the revision context to the LLM service ---
                is_revision=is_revision,
                previous_draft=previous_draft,
                feedback_from_critic=feedback
            )

            state.llm_calls.append({
                "step": "writer",
                "purpose": "write_message (revision)" if is_revision else "write_message (first_draft)",
                "output": message_data
            })

            attributions = [
                SentenceAttribution(
                    text=item.get("text", ""),
                    driven_by=item.get("driven_by", []),
                    purpose=item.get("purpose", "unknown")
                )
                for item in message_data.get("sentence_breakdown", [])
            ]

            state.draft = MessageDraft(
                body=message_data.get("body", ""),
                subject=message_data.get("subject"),
                sentence_attribution=attributions
            )

        except Exception as e:
            fallback = f"Hi {state.target_prospect}, came across your work at {state.target_company} and wanted to connect. I know you are busy, but I would love to hear your thoughts on this. Would you be open to a quick call to discuss further?"
            state.draft = MessageDraft(
                body=fallback,
                subject=None,
                sentence_attribution=[
                    SentenceAttribution(
                        text=fallback,
                        driven_by=["fallback"],
                        purpose="complete_message"
                    )
                ]
            )
            state.memory["writer_error"] = str(e)

        state.status = Status.VALIDATING
        return state

    # --- UPDATED critic FUNCTION ---
    @staticmethod
    def critic(state: AgentState) -> AgentState:
        """Uses LLM to validate the message and decides on refinement."""
        if not state.draft:
            state.status = Status.PLANNING
            return state

        try:
            validation_result = llm_service.validate_message(
                message=state.draft.body,
                prospect_name=state.target_prospect,
                channel=state.channel,
                personality=state.personality
            )
            state.llm_calls.append({"step": "critic", "purpose": "validate_message", "output": validation_result})

            # Post-LLM rule checks — these are deterministic and override the LLM
            extra_issues: List[str] = []
            if ReasoningTools.detect_overpersonalization(state.draft.body):
                extra_issues.append("Remove overly personal references that may feel intrusive.")
                validation_result["score"] = max(0, validation_result["score"] - 20)
            for phrase in state.personality.never_use_phrases:
                if phrase.lower() in state.draft.body.lower():
                    extra_issues.append(f"Remove banned phrase: '{phrase}'.")
                    validation_result["score"] = max(0, validation_result["score"] - 10)
            if ReasoningTools.detect_placeholder_text(state.draft.body):
                extra_issues.append("Remove all placeholder text like [Company], [Name], [Result] — use only real data or omit entirely.")
                validation_result["score"] = max(0, validation_result["score"] - 40)

            # Detect hallucinated attachment/link references
            attachment_phrases = ["i've attached", "i have attached", "see attached", "i'm sending", "i'll send", "check out the link", "i sent you"]
            if any(p in state.draft.body.lower() for p in attachment_phrases):
                extra_issues.append("Remove attachment/link references — this is a plain text message, you cannot attach or send files.")
                validation_result["score"] = max(0, validation_result["score"] - 30)

            if extra_issues:
                validation_result["warnings"].extend(extra_issues)
                validation_result["valid"] = False
                # Append to suggested_fixes so the writer knows what to fix
                existing_fixes = validation_result.get("suggested_fixes") or ""
                combined = (existing_fixes + " " + " | ".join(extra_issues)).strip()
                validation_result["suggested_fixes"] = combined

            # Final safety: if score is below threshold, force valid=False
            if validation_result.get("score", 0) < settings.MIN_QUALITY_SCORE:
                validation_result["valid"] = False

            state.validation = Validation(**validation_result)
            # If the critic warned the draft is "Too short", provide an explicit
            # suggested_fixes entry so the orchestrator will go into REVISING mode
            # and the writer will receive revision instructions.
            warnings_lower = " ".join([w.lower() for w in (validation_result.get("warnings") or [])])
            if "too short" in warnings_lower and not state.validation.suggested_fixes:
                min_len_note = f"Please expand the message to meet the minimum length requirement (add more value points, examples, and a clear CTA)."
                # Append or set suggested_fixes so the critic -> revising flow triggers
                state.validation.suggested_fixes = (
                    (state.validation.suggested_fixes or "") + " " + min_len_note
                ).strip()
        except Exception as e:
            state.validation = Validation(valid=False, score=0, warnings=[f"Validation failed: {str(e)}"], suggested_fixes="Rewrite the message from scratch.")
            state.memory["critic_error"] = str(e)

        # --- UPDATED: Refinement Logic ---

        # Case 1: Validation passed
        if state.validation.valid:
            # NEW: Emit message_generated event to Worker telemetry
            try:
                from .event_emitter import get_writer_emitter
                emitter = get_writer_emitter()
                emitter.emit_message_generated(
                    correlation_id=state.memory.get("correlation_id", ""),
                    message_body=state.draft.body if state.draft else "",
                    subject=state.draft.subject if state.draft else None,
                    quality_score=state.validation.score,
                    channel=state.channel.value if state.channel else "",
                    prospect_name=state.target_prospect,
                    company_name=state.target_company,
                )
            except Exception as e:
                state.memory["event_emit_error"] = str(e)

            # If human review is enabled, pause here instead of completing
            if settings.ENABLE_HUMAN_REVIEW:
                state.status = Status.AWAITING_HUMAN
                state.next_action = {
                    "type": ActionType.HUMAN_REVIEW,
                    "reason": f"Message approved by critic (score: {state.validation.score}). Awaiting human decision."
                }
            else:
                state.status = Status.COMPLETE
                state.next_action = {"type": ActionType.SAVE_DRAFT, "reason": f"Score: {state.validation.score}"}

            # Record everything in memory regardless
            MemoryService.prospects.record_outreach(name=state.target_prospect, company=state.target_company, channel=state.channel.value, stage=state.stage.value, hook_used=state.strategy.primary_hook if state.strategy else "", angle_used=state.strategy.angle if state.strategy else "", offer_name=state.selected_offer.offer_name if state.selected_offer else "", message_sent=state.draft.body if state.draft else "")
            MemoryService.learning.record_generation(quality_score=state.validation.score, channel=state.channel.value, stage=state.stage.value, template=state.personality.base_template.value)
            if state.selected_offer:
                MemoryService.offers.record_usage(offer_name=state.selected_offer.offer_name, channel=state.channel.value, angle=state.strategy.angle if state.strategy else "", prospect_role=state.prospect_role, quality_score=state.validation.score)

        # Case 2: Validation failed, but we have specific fixes to try (and haven't exhausted retries)
        # NOTE: Check iteration_count to limit internal graph loops, but don't increment it here —
        # the orchestrator manages overall iteration count across pipeline runs.
        elif state.validation.suggested_fixes and state.iteration_count < state.max_iterations:
            state.status = Status.REVISING  # Tell the graph to route back to the writer
            state.next_action = {
                "type": ActionType.RETRY,
                "reason": f"Validation failed (score: {state.validation.score}). Attempting revision.",
                "feedback": state.validation.suggested_fixes # This is the crucial part
            }
            # We do NOT clear state.draft, the writer needs it to revise

        # Case 3: Validation failed badly, or we're out of retries. Start over from scratch.
        else:
            state.status = Status.FAILED
            state.next_action = {"type": ActionType.ABORT, "reason": f"Validation failed (score {state.validation.score}), no fixable suggestions or retries exhausted."}

        return state