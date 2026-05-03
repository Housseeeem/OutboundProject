"""Centralised configuration for the Prospect Strategy Engine.

All environment variables are loaded here. No hardcoded URLs, keys, or model
names anywhere else in the codebase — import from this module instead.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # API keys
    HUNTER_API_KEY: str = os.getenv("HUNTER_API_KEY", "")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

    # Ollama (local LLM fallback)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "mistral")
    OLLAMA_STRATEGY_MODEL: str = os.getenv("OLLAMA_STRATEGY_MODEL", "llama3.1:8b")
    OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT", "45"))

    # OpenAI-compatible HTTP endpoint (used as fallback instead of Ollama)
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_TIMEOUT: int = int(os.getenv("OPENAI_TIMEOUT", "45"))
    # Writer MCP endpoint
    OUTREACH_MCP_URL: str = os.getenv("OUTREACH_MCP_URL", "http://localhost:8003/mcp")
    OUTREACH_MCP_TOOL_NAME: str = os.getenv("OUTREACH_MCP_TOOL_NAME", "generate_outreach")

    # Default outreach parameters (used when calling the Writer MCP)
    SENDER_COMPANY_NAME: str = os.getenv("SENDER_COMPANY_NAME", "Prospect Strategy Engine")
    OFFER_NAME: str = os.getenv("OFFER_NAME", "Personalised B2B Prospecting Strategy")
    ELEVATOR_PITCH: str = os.getenv(
        "ELEVATOR_PITCH",
        "We generate hyper-personalised B2B outreach messages that get replies from decision-makers.",
    )
    SOLUTION_SUMMARY: str = os.getenv(
        "SOLUTION_SUMMARY",
        "A commercial engagement service that turns prospect analysis into tailored contact messages.",
    )
    CTA: str = os.getenv("CTA", "Reply to schedule a quick call and see how we can work together.")


settings = Settings()
