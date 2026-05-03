"""Strategy agent — generates a sequenced outreach action plan for a prospect.

Uses Ollama (llama3.1:8b by default) with structured output to produce an
ActionPlan sequence. Model and base URL are read from config.py.
"""

import sys
import os

# Allow running this file directly from the agents/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from langchain_core.prompts import ChatPromptTemplate
from config import settings

# Import available LLM providers
try:
    from langchain_ollama import ChatOllama  # type: ignore
    _HAS_OLLAMA = True
except ImportError:
    _HAS_OLLAMA = False

try:
    from langchain_openai import ChatOpenAI  # type: ignore
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False
    try:
        # Fallback: set env vars and try generic import
        if settings.OPENAI_API_KEY:
            os.environ.setdefault("OPENAI_API_KEY", settings.OPENAI_API_KEY)
        if settings.OPENAI_BASE_URL:
            os.environ.setdefault("OPENAI_API_BASE", settings.OPENAI_BASE_URL)
        from langchain.chat_models import ChatOpenAI  # type: ignore
        _HAS_OPENAI = True
    except Exception:
        _HAS_OPENAI = False

from langgraph.graph import StateGraph, END
from agents.state import AgentState, StrategyOutput


# ------------------------------------------------------------------
# LLM setup — reads model name and base URL from config
# ------------------------------------------------------------------

# Priority: OpenAI (if configured) > Ollama (if available) > Error
_use_openai = bool(settings.OPENAI_BASE_URL and settings.OPENAI_API_KEY)

if _use_openai and _HAS_OPENAI:
    llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0.1)
elif _HAS_OLLAMA and settings.OLLAMA_BASE_URL:
    llm = ChatOllama(
        model=settings.OLLAMA_STRATEGY_MODEL,
        base_url=settings.OLLAMA_BASE_URL,
        temperature=0.1,
    )
else:
    # No LLM provider available — raise on use
    class _MissingLLM:
        def with_structured_output(self, *a, **k):
            raise RuntimeError(
                "No LLM provider configured. Set OPENAI_BASE_URL + OPENAI_API_KEY, or configure Ollama."
            )

    llm = _MissingLLM()

structured_llm = llm.with_structured_output(StrategyOutput)


# ------------------------------------------------------------------
# Strategy node
# ------------------------------------------------------------------

def generate_strategy(state: AgentState) -> dict:
    """Generate a sequenced outreach plan based on prospect data."""

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            """You are a B2B Growth Hacking expert specialising in outreach sequences.
Your role is to analyse prospect data and generate a strict action plan.

DECISION RULES (follow these exactly):
1. CHANNELS:
   - If the prospect has a phone (has_phone=True), include SMS or Call in the sequence.
   - If they only have email (has_email=True) and no phone, focus on Email and LinkedIn.
   - If neither, use LinkedIn only.
2. TONE:
   - If recent posts use emojis and casual language, recommend a relaxed approach.
   - If no recent posts or very formal tone, recommend a corporate approach.
3. TIMING:
   - Space actions out (Day 0, Day +2, Day +5, ...).

Do NOT write the messages themselves. Generate only the sequence of strategic actions
and justify each choice based on the prospect's profile. Reply in English.""",
        ),
        (
            "user",
            """Prospect data:
- Name: {prospect_name}
- Email available: {has_email}
- Phone available: {has_phone}
- Recent activity context: {recent_posts_context}

Generate the optimal action plan following the rules above.""",
        ),
    ])

    chain = prompt | structured_llm

    result = chain.invoke({
        "prospect_name": state["prospect_name"],
        "has_email": state["has_email"],
        "has_phone": state["has_phone"],
        "recent_posts_context": state["recent_posts_context"],
    })

    return {"final_plan": result}


# ------------------------------------------------------------------
# Graph
# ------------------------------------------------------------------

workflow = StateGraph(AgentState)
workflow.add_node("strategist", generate_strategy)
workflow.set_entry_point("strategist")
workflow.add_edge("strategist", END)

app = workflow.compile()
