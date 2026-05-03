import json
import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def evaluate_agent_run(
    client: Any,
    model_name: str,
    generation_config: Any,
    objective: str,
    state: Dict[str, Any],
    openai_client: Any = None,
    openai_model: str = "",
) -> Dict[str, Any]:
    """
    Evaluates the quality of an agent's run on 3 criteria.
    Returns a dict with scores and feedback.
    """
    if not client and not openai_client:
        return {"status": "skipped", "reason": "No LLM client configured"}

    scratchpad = json.dumps(state.get("scratchpad", []), default=str)
    
    eval_prompt = f"""
You are an expert evaluator for an AI agent. Assess the agent's execution of the objective.

OBJECTIVE : {objective}
FINAL STATUS : {state.get("status")}
SCRATCHPAD (Execution History) : {scratchpad}

Score each criterion from 1 (very poor) to 5 (excellent):
1. Relevance (Did the agent take actions directly related to the objective?)
2. Accuracy (Were the tool calls and parameters correct?)
3. Completeness (Did the agent fully cover all required steps to achieve the objective?)

You MUST respond ONLY with a JSON object exactly matching this structure:
{{
  "relevance": <int>,
  "accuracy": <int>,
  "completeness": <int>,
  "feedback": "<string: brief summary of why these scores were given>",
  "global_score": <int: average of the three rounded to nearest int>
}}
""".strip()

    raw = None
    if client:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=eval_prompt,
                config=generation_config,
            )
            raw = response.text or "{}"
        except Exception as exc:
            logger.warning("Gemini evaluation failed, trying OpenAI: %s", exc)

    if raw is None and openai_client and openai_model:
        try:
            response = await openai_client.chat.completions.create(
                model=openai_model,
                messages=[
                    {"role": "system", "content": "Return valid JSON only, no markdown."},
                    {"role": "user", "content": eval_prompt},
                ],
                temperature=0.2,
                max_tokens=256,
            )
            raw = response.choices[0].message.content or "{}"
        except Exception as exc:
            logger.warning("OpenAI evaluation failed: %s", exc)
            return {"status": "failed", "reason": str(exc)}

    if raw is None:
        return {"status": "failed", "reason": "All evaluation providers failed"}

    # Clean markdown blocks
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
        data["status"] = "completed"
        return data
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                data = json.loads(match.group(0))
                data["status"] = "completed"
                return data
            except json.JSONDecodeError:
                pass

        logger.warning("Agent evaluation failed to parse JSON: %s", raw)
        return {
            "status": "failed",
            "reason": "Invalid JSON format generated",
            "raw_output": raw
        }
