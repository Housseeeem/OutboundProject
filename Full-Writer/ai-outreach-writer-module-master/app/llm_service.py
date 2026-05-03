import google.generativeai as genai
from typing import Optional, Dict, Any, List
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception
from .config import settings
from .models import (
    Signal, Strategy, Personality, CompanyDetails,
    SelectedOffer, Channel, Intent, Stage
)


class LLMService:
    """All Gemini API calls for the outreach pipeline.

    Reliability features:
    - Exponential backoff retry (tenacity) on 429 / quota errors
    - Automatic fallback to GEMINI_FALLBACK_MODEL if primary fails
    - json5 parsing for tolerance against sloppy LLM JSON output
    - Hard trim in write_message if LLM overshoots character limit
    """

    def __init__(self):
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        model_config = {
            "temperature": settings.GEMINI_TEMPERATURE,
            "max_output_tokens": settings.GEMINI_MAX_TOKENS,
        }
        self.model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            generation_config=model_config,
        )
        self.fallback_model = genai.GenerativeModel(
            model_name=settings.GEMINI_FALLBACK_MODEL,
            generation_config=model_config,
        )

    @retry(
        retry=retry_if_exception(
            lambda e: "429" in str(e)
            or "quota" in str(e).lower()
            or "resource_exhausted" in str(e).lower()
        ),
        wait=wait_exponential(multiplier=1, min=20, max=120),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _call_llm(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Call primary model; fall back to fallback_model on any error."""
        full_prompt = f"{system_instruction}\n\n{prompt}" if system_instruction else prompt
        try:
            return self.model.generate_content(full_prompt).text
        except Exception as primary_err:
            try:
                return self.fallback_model.generate_content(full_prompt).text
            except Exception as fallback_err:
                raise Exception(
                    f"Both models failed. "
                    f"Primary ({settings.GEMINI_MODEL}): {primary_err} | "
                    f"Fallback ({settings.GEMINI_FALLBACK_MODEL}): {fallback_err}"
                )

    def _parse_json(self, raw: str) -> dict:
        """Parse LLM output with json5 — tolerates trailing commas, single quotes, etc."""
        import json5

        cleaned = raw.strip()
        for fence in ("```json", "```"):
            if cleaned.startswith(fence):
                cleaned = cleaned[len(fence):]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json5.loads(cleaned)
        except Exception as e:
            raise ValueError(
                f"Failed to parse LLM response even with json5. "
                f"Error: {e}. Raw: <<< {raw} >>>"
            )

    # ------------------------------------------------------------------
    # Prompt-building helpers
    # ------------------------------------------------------------------

    def _build_personality_block(self, personality: Personality, stage: Stage) -> str:
        stage_override = personality.stage_instructions.get(stage.value, "")
        lines = [f"BASE STYLE: {personality.base_template.value}"]
        if personality.custom_template_description:
            lines.append(f"CUSTOM STYLE DESCRIPTION: {personality.custom_template_description}")
        if personality.personality_traits:
            lines.append(f"PERSONALITY TRAITS: {', '.join(personality.personality_traits)}")
        if personality.always_include_phrases:
            lines.append(f"MUST INCLUDE THESE PHRASES (use naturally): {', '.join(personality.always_include_phrases)}")
        if personality.never_use_phrases:
            lines.append(f"NEVER USE THESE PHRASES: {', '.join(personality.never_use_phrases)}")
        lines.append(f"TOUCHDOWNS PER MESSAGE: Hit exactly {personality.touchdowns_per_message} distinct value or hook points")
        if personality.enabled_hook_types:
            lines.append(f"ALLOWED HOOK TYPES: {', '.join(personality.enabled_hook_types)}")
        lines.append(f"URGENCY LEVEL: {personality.urgency_level}/10 (1=no urgency, 10=extremely urgent)")
        lines.append(f"SELF DEPRECATION: {personality.self_deprecation}/10 (1=none, 10=a lot)")
        lines.append(f"HUMOR/SARCASM: {personality.humor_sarcasm}/10 (1=very serious, 10=very funny)")
        if stage_override:
            lines.append(f"STAGE SPECIFIC INSTRUCTION: {stage_override}")
        return "\n".join(lines)

    def _build_company_block(self, company: CompanyDetails) -> str:
        lines = [f"SENDER COMPANY: {company.company_name}"]
        if company.website:
            lines.append(f"WEBSITE: {company.website}")
        if company.industry:
            lines.append(f"INDUSTRY: {company.industry}")
        if company.elevator_pitch:
            lines.append(f"ELEVATOR PITCH: {company.elevator_pitch}")
        if company.value_props:
            lines.append("VALUE PROPS:\n" + "\n".join(f"  - {v}" for v in company.value_props))
        if company.social_proof:
            lines.append("SOCIAL PROOF:\n" + "\n".join(f"  - {s}" for s in company.social_proof))
        return "\n".join(lines)

    def _build_offer_block(self, offer: SelectedOffer) -> str:
        lines = [f"OFFER: {offer.offer_name}"]
        if offer.pain_points:
            lines.append("PAIN POINTS IT SOLVES:\n" + "\n".join(f"  - {p}" for p in offer.pain_points))
        if offer.solution_summary:
            lines.append(f"SOLUTION SUMMARY: {offer.solution_summary}")
        if offer.proof_points:
            lines.append("PROOF POINTS:\n" + "\n".join(f"  - {p}" for p in offer.proof_points))
        if offer.cta:
            lines.append(f"CALL TO ACTION TO USE: {offer.cta}")
        return "\n".join(lines)

    def _build_channel_instructions(self, channel: Channel, stage: Stage, intent: Intent) -> str:
        channel_rules = {
            Channel.LINKEDIN_DM: "Short, conversational, peer-like.",
            Channel.LINKEDIN_INMAIL: "Semi-formal, subject line matters.",
            Channel.EMAIL: "Professional but warm, subject is critical.",
            Channel.TWITTER_DM: "Very short, casual.",
            Channel.SMS: "Ultra short, direct.",
        }
        stage_rules = {
            Stage.FIRST_TOUCH: "Build curiosity, be human.",
            Stage.SECOND_TOUCH: "Reference first message, add new value.",
            Stage.THIRD_TOUCH: "Be more direct.",
            Stage.BREAKUP: "Light, leave door open.",
            Stage.NURTURE: "No ask, pure value.",
        }
        intent_rules = {
            Intent.DIRECT_OUTREACH: "Respect their time.",
            Intent.FOLLOW_UP: "Reference past interaction.",
            Intent.REFERRAL: "Lead with mutual connection.",
            Intent.RE_ENGAGEMENT: "Acknowledge the gap.",
            Intent.EVENT_BASED: "Reference the trigger.",
        }
        return "\n".join([
            f"CHANNEL RULES: {channel_rules.get(channel, '')}",
            f"STAGE RULES: {stage_rules.get(stage, '')}",
            f"INTENT RULES: {intent_rules.get(intent, '')}",
        ])

    def _build_voice_block(self, voice_samples: List[str]) -> str:
        """Build a voice-matching block from the sender's past messages."""
        if not voice_samples:
            return ""
        samples_text = "\n".join(
            f'  Sample {i + 1}: "{s.strip()}"'
            for i, s in enumerate(voice_samples[:5])
        )
        return (
            "SENDER VOICE — CRITICAL: Study these real messages written by the sender "
            "and match their style exactly.\n"
            f"{samples_text}\n"
            "Extract and replicate:\n"
            "- Their sentence length and rhythm (short punchy vs longer flowing)\n"
            "- Punctuation habits (em dashes, ellipses, exclamation marks?)\n"
            "- Vocabulary level (casual slang, professional, technical?)\n"
            "- How they open (jump straight in or warm up first?)\n"
            "- How they close (soft question, direct ask, statement?)\n"
            "- Any recurring phrases or patterns unique to them\n"
            "The final message must sound like IT WAS WRITTEN BY THIS SPECIFIC PERSON, "
            "not a generic AI copywriter."
        )

    def _build_memory_block(
        self, times_contacted_before: int, last_message_sent: Optional[str]
    ) -> str:
        lines = []
        if times_contacted_before > 0:
            lines.append(
                f"PREVIOUS CONTACT: This prospect has been contacted "
                f"{times_contacted_before} time(s) before."
            )
        else:
            lines.append("PREVIOUS CONTACT: This is the first time contacting this prospect.")
        if last_message_sent:
            lines.append(f'LAST MESSAGE SENT TO THEM:\n  "{last_message_sent}"')
            lines.append("IMPORTANT: Your new message must be clearly different from the last one sent.")
        return "\n".join(lines) if lines else "NO PRIOR CONTACT HISTORY"

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def analyze_research_signals(
        self,
        signals: List[Signal],
        prospect_name: str,
        company: str,
        personality: Personality,
        hooks_already_used: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if hooks_already_used is None:
            hooks_already_used = []

        filtered_signals = signals
        if personality.enabled_hook_types:
            filtered_signals = (
                [s for s in signals if s.type in personality.enabled_hook_types] or signals
            )

        signals_text = "\n".join(
            f"- [{s.strength.upper()}] {s.type}: {s.content} (Why relevant: {s.why_relevant})"
            for s in filtered_signals
        )
        memory_context = ""
        if hooks_already_used:
            memory_context = (
                "\n\nHOOKS ALREADY USED (do NOT pick these again):\n"
                + "\n".join(f"  - {h}" for h in hooks_already_used)
            )

        prompt = (
            f"You are a sales strategy expert analyzing research signals about "
            f"{prospect_name} at {company}.\n"
            f"RESEARCH SIGNALS:\n{signals_text}\n"
            f"ALLOWED HOOK TYPES: "
            f"{', '.join(personality.enabled_hook_types) if personality.enabled_hook_types else 'All types allowed'}"
            f"{memory_context}\n"
            "Your task:\n"
            "1. Identify the BEST primary hook (most timely, relevant, personal)\n"
            "2. Identify a good secondary hook\n"
            "3. Explain your reasoning\n"
            'Return JSON: {"primary_hook": "...", "secondary_hook": "...", "reasoning": "...", "confidence": "..."}'
        )
        try:
            response = self._call_llm(
                prompt,
                system_instruction=(
                    "You are an expert sales strategist. Always return valid JSON only. "
                    "All JSON string values must be properly escaped. No markdown."
                ),
            )
            return self._parse_json(response)
        except Exception as e:
            return {
                "primary_hook": signals[0].content if signals else "General interest",
                "secondary_hook": signals[1].content if len(signals) > 1 else "Industry trends",
                "reasoning": f"Fallback due to error: {e}",
                "confidence": "low",
            }

    def create_strategy(
        self,
        primary_hook: str,
        secondary_hook: str,
        prospect_name: str,
        company: str,
        prospect_role: Optional[str],
        personality: Personality,
        company_details: CompanyDetails,
        selected_offer: SelectedOffer,
        channel: Channel,
        intent: Intent,
        stage: Stage,
        angles_already_tried: Optional[List[str]] = None,
    ) -> Strategy:
        if angles_already_tried is None:
            angles_already_tried = []

        role_context = f"({prospect_role})" if prospect_role else ""
        memory_context = ""
        if angles_already_tried:
            memory_context = (
                "\n\nANGLES ALREADY TRIED (use a DIFFERENT angle):\n"
                + "\n".join(f"  - {a}" for a in angles_already_tried)
            )

        prompt = (
            f"You are a sales messaging strategist.\n"
            f"TARGET: {prospect_name} {role_context} at {company}\n"
            f"PRIMARY HOOK: {primary_hook}\n"
            f"SECONDARY HOOK: {secondary_hook}\n"
            f"STYLE: {personality.base_template.value} | CHANNEL: {channel.value} | STAGE: {stage.value}\n"
            f"SENDER: {company_details.company_name}"
            f"{f' — {company_details.elevator_pitch}' if company_details.elevator_pitch else ''}\n"
            f"OFFER: {selected_offer.offer_name}"
            f"{f' — {selected_offer.solution_summary}' if selected_offer.solution_summary else ''}\n"
            f"{self._build_channel_instructions(channel, stage, intent)}"
            f"{memory_context}\n"
            "Return a concise strategy. Reasoning must be under 80 words.\n"
            'Return JSON: {"angle": "...", "reasoning": "..."}'
        )
        try:
            response = self._call_llm(
                prompt,
                system_instruction=(
                    "You are a sales strategy expert. Always return valid JSON only. "
                    "All JSON string values must be properly escaped. No markdown."
                ),
            )
            result = self._parse_json(response)
            return Strategy(
                primary_hook=primary_hook,
                secondary_hook=secondary_hook,
                angle=result.get("angle", "Peer-to-peer"),
                tone=personality.base_template.value,
                cta_style=selected_offer.cta or "soft_question",
                reasoning=result.get("reasoning", ""),
            )
        except Exception as e:
            return Strategy(
                primary_hook=primary_hook,
                secondary_hook=secondary_hook,
                angle="Peer-to-peer",
                tone=personality.base_template.value,
                cta_style=selected_offer.cta or "soft_question",
                reasoning=f"Fallback strategy: {e}",
            )

    def write_message(
        self,
        strategy: Strategy,
        prospect_name: str,
        company: str,
        prospect_role: Optional[str],
        personality: Personality,
        company_details: CompanyDetails,
        selected_offer: SelectedOffer,
        channel: Channel,
        intent: Intent,
        stage: Stage,
        times_contacted_before: int = 0,
        last_message_sent: Optional[str] = None,
        is_revision: bool = False,
        previous_draft: Optional[str] = None,
        feedback_from_critic: Optional[str] = None,
    ) -> Dict[str, Any]:
        channel_limits = {
            Channel.LINKEDIN_DM: (50, 300),
            Channel.LINKEDIN_INMAIL: (100, 600),
            Channel.EMAIL: (100, 800),
            Channel.TWITTER_DM: (20, 280),
            Channel.SMS: (20, 160),
        }
        min_len, max_len = channel_limits.get(channel, (50, 300))
        include_subject = channel in (Channel.LINKEDIN_INMAIL, Channel.EMAIL)
        role_context = f"({prospect_role})" if prospect_role else ""

        memory_block = self._build_memory_block(times_contacted_before, last_message_sent)
        voice_block = self._build_voice_block(personality.voice_samples)

        # Local mock fallback when no external LLM is configured (useful for dev/test)
        if not settings.GOOGLE_API_KEY:
            # If we're doing a revision for 'too short', heuristically expand the previous draft
            if is_revision and previous_draft and feedback_from_critic and ("too short" in feedback_from_critic.lower() or "add at least" in feedback_from_critic.lower()):
                body = previous_draft
                # Append templated value points until we reach min_len
                add_text = " We help companies like yours scale faster by improving conversion, reducing churn, and accelerating onboarding. Schedule a quick 15 min call to explore."
                while len(body) < min_len:
                    body = (body + add_text)[:max_len]
                return {"body": body, "subject": None, "sentence_breakdown": [{"text": body, "purpose": "expanded", "driven_by": ["mock_expand"]}]}

        revision_block = ""
        if is_revision and previous_draft and feedback_from_critic:
            fb_lower = (feedback_from_critic or "").lower()
            # If the critic specifically flagged length, encourage expansion rather than a minimal edit
            if "too short" in fb_lower or "add at least" in fb_lower:
                # Calculate how many chars to add if the feedback mentions a number
                # Fallback instruction: expand to min_len and add concrete value points + CTA
                revision_block = (
                    f"REVISION REQUIRED — your previous draft was rejected for length.\n"
                    f'PREVIOUS DRAFT ({len(previous_draft)} chars): "{previous_draft}"\n'
                    f"FEEDBACK: {feedback_from_critic}\n"
                    f"Instruction: Expand the message to be at least {min_len} characters. Keep the original hook and tone, but add 1-2 concrete value points specific to the company and end with a clear CTA (for example: 'Schedule 15 min call'). You may add sentences but do not change the original hook sentence."
                )
            else:
                revision_block = (
                    f"REVISION REQUIRED — your previous draft was rejected.\n"
                    f'PREVIOUS DRAFT ({len(previous_draft)} chars): "{previous_draft}"\n'
                    f"FEEDBACK: {feedback_from_critic}\n"
                    "Fix exactly what the feedback says. Do not change anything else. "
                    "Do not rewrite from scratch."
                )

        social_proof_line = (
            f"SOCIAL PROOF (use these exact names/numbers, never invent placeholders): "
            f"{' | '.join(company_details.social_proof)}"
            if company_details.social_proof
            else (
                "NO SOCIAL PROOF PROVIDED — do not invent company names, results, or "
                "placeholders like [Similar Company] or [Client Name]. "
                "Omit social proof entirely if you have none."
            )
        )
        subject_str = '"..."' if include_subject else "null"

        prompt = (
            f"Write a personalized outreach message.\n"
            f"{revision_block}\n"
            f"{voice_block}\n"
            f"TARGET: {prospect_name} {role_context} at {company}\n"
            f"HOOK: {strategy.primary_hook} | ANGLE: {strategy.angle}\n"
            f"STYLE: {personality.base_template.value} | "
            f"URGENCY: {personality.urgency_level}/10 | "
            f"HUMOR: {personality.humor_sarcasm}/10\n"
            + (f"TRAITS: {', '.join(personality.personality_traits)}\n" if personality.personality_traits else "")
            + (f"MUST USE: {', '.join(personality.always_include_phrases)}\n" if personality.always_include_phrases else "")
            + (f"NEVER USE: {', '.join(personality.never_use_phrases)}\n" if personality.never_use_phrases else "")
            + f"SENDER: {company_details.company_name}"
            + (f" — {company_details.elevator_pitch}" if company_details.elevator_pitch else "")
            + f"\nOFFER: {selected_offer.offer_name}"
            + (f" — {selected_offer.solution_summary}" if selected_offer.solution_summary else "")
            + f"\n{social_proof_line}\n"
            f"CTA: {selected_offer.cta or 'soft question'}\n"
            f"CHANNEL: {channel.value} | STAGE: {stage.value}\n"
            f"{self._build_channel_instructions(channel, stage, intent)}\n"
            f"{memory_block}\n"
            f"HARD REQUIREMENTS:\n"
            f"- Length: {min_len}-{max_len} characters (STRICT — the message will be "
            f"AUTOMATICALLY REJECTED if it exceeds {max_len} chars. When in doubt, write shorter.)\n"
            f"- Exactly {personality.touchdowns_per_message} distinct touchpoints\n"
            "- NEVER use placeholder text like [Company], [Name], [Result], or any bracketed stand-ins.\n"
            "- NEVER say \"I've attached\", \"see attached\", \"I'm sending\", \"I'll send\", "
            "\"check out the link\", or imply you are sending files, links, or attachments.\n"
            + ("- Include a subject line\n" if include_subject else "- No subject line\n")
            + f'Return JSON: {{"body": "...", "subject": {subject_str}, '
            f'"sentence_breakdown": [{{"text": "...", "purpose": "hook|credibility|value|cta", "driven_by": [...]}}]}}'
        )

        try:
            response = self._call_llm(
                prompt,
                system_instruction=(
                    "You are an expert sales copywriter. Write authentic human messages. "
                    "Always return valid JSON only. All JSON string values must be properly escaped. "
                    "No markdown."
                ),
            )
            result = self._parse_json(response)

            # Hard trim: if LLM still overshoots, cut at last sentence boundary within limit
            body = result.get("body", "")
            if len(body) > max_len:
                trimmed = body[:max_len]
                for punct in ("?", "!", "."):
                    last = trimmed.rfind(punct)
                    if last > min_len:
                        trimmed = trimmed[: last + 1]
                        break
                result["body"] = trimmed

            return result
        except Exception as e:
            fallback = f"Hi {prospect_name}, came across your work at {company} and wanted to connect. I know you are busy, but I would love to hear your thoughts on this. Would you be open to a quick call to discuss further?"
            return {
                "body": fallback,
                "subject": None,
                "sentence_breakdown": [{"text": fallback, "purpose": "general", "driven_by": ["fallback"]}],
                "error": str(e),
            }

    def validate_message(
        self,
        message: str,
        prospect_name: str,
        channel: Channel,
        personality: Personality,
    ) -> Dict[str, Any]:
        channel_limits = {
            Channel.LINKEDIN_DM: (50, 300),
            Channel.LINKEDIN_INMAIL: (100, 600),
            Channel.EMAIL: (100, 800),
            Channel.TWITTER_DM: (20, 280),
            Channel.SMS: (20, 160),
        }
        min_len, max_len = channel_limits.get(channel, (50, 300))
        char_count = len(message)

        # Pass 1: deterministic checks — skip LLM entirely if these fail
        hard_failures: List[str] = []
        if char_count > max_len:
            hard_failures.append(
                f"Too long: {char_count} chars, max is {max_len}. "
                f"Shorten by {char_count - max_len} characters."
            )
        if char_count < min_len:
            hard_failures.append(
                f"Too short: {char_count} chars, min is {min_len}. "
                f"Add at least {min_len - char_count} characters."
            )
        for phrase in personality.never_use_phrases:
            if phrase.lower() in message.lower():
                hard_failures.append(f"Banned phrase used: '{phrase}'. Remove it.")

        if hard_failures:
            penalty = min(len(hard_failures) * 20, 60)
            return {
                "score": max(0, 100 - penalty),
                "warnings": hard_failures,
                "suggested_fixes": " | ".join(hard_failures),
                "valid": False,
            }

        # Pass 2: LLM scoring (only when hard rules pass)
        banned = ", ".join(personality.never_use_phrases) if personality.never_use_phrases else "none"
        required = ", ".join(personality.always_include_phrases) if personality.always_include_phrases else "none"

        prompt = (
            f"Evaluate this outreach message for quality.\n"
            f"MESSAGE: {message}\n"
            f"CHANNEL: {channel.value} | CHAR COUNT: {char_count} | REQUIRED: {min_len}-{max_len} chars\n"
            f"BANNED PHRASES: {banned} | REQUIRED PHRASES: {required} | "
            f"TOUCHDOWNS REQUIRED: {personality.touchdowns_per_message}\n"
            "Check ONLY: missing required phrases, CTA clarity, authenticity, correct touchdown count.\n"
            "Do NOT flag: length (already verified), style preferences, word choice, tone subjectivity.\n"
            "Only flag issues that would make a real sales rep embarrassed to send this message.\n"
            f"IMPORTANT: If score >= {settings.MIN_QUALITY_SCORE}, you MUST set valid to true. "
            "Only set valid to false if there is a concrete, fixable problem.\n"
            "Score 0-100.\n"
            'Return JSON: {"score": 85, "warnings": ["concrete issues only, empty list if none"], '
            '"suggested_fixes": "one concise actionable sentence, or null if none", "valid": true}'
        )

        try:
            response = self._call_llm(
                prompt,
                system_instruction="You are a message quality expert. Return valid JSON only. No markdown.",
            )
            result = self._parse_json(response)
            if result.get("score", 0) < settings.MIN_QUALITY_SCORE:
                result["valid"] = False
            return result
        except Exception as e:
            return {
                "score": 80,
                "warnings": [f"Validation LLM failed: {e}"],
                "suggested_fixes": "Manual review needed",
                "valid": True,
            }


llm_service = LLMService()
