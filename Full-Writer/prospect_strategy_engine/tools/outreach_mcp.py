"""Outreach MCP client — calls the Writer module's generate_outreach tool.

Falls back to a local Ollama prompt if the MCP endpoint is unavailable.
All URLs, model names, and default parameters are read from config.py.
"""

import asyncio
import json
import logging
import requests
from typing import Any, Optional

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from config import settings

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# MCP path
# ------------------------------------------------------------------

async def _call_mcp(payload: dict) -> Any:
    client = MultiServerMCPClient(
        {"outreach": {"url": settings.OUTREACH_MCP_URL, "transport": "sse"}}
    )
    async with client.session("outreach") as session:
        tools = await load_mcp_tools(session)
        tool = next((t for t in tools if t.name == settings.OUTREACH_MCP_TOOL_NAME), None)
        if tool is None:
            raise RuntimeError(
                f"MCP tool '{settings.OUTREACH_MCP_TOOL_NAME}' not found at {settings.OUTREACH_MCP_URL}"
            )
        return await tool.ainvoke(payload)


def _extract_message(data: Any) -> str:
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            return str(parsed.get("message", data))
        except json.JSONDecodeError:
            return data
    if isinstance(data, dict):
        return str(data.get("message", json.dumps(data, ensure_ascii=False)))
    if isinstance(data, list) and len(data) == 1:
        return _extract_message(data[0])
    if hasattr(data, "text"):
        return _extract_message(data.text)
    return str(data)


# ------------------------------------------------------------------
# OpenAI-compatible HTTP fallback
# ------------------------------------------------------------------

def _call_openai_fallback(
    prospect_name: str,
    company: str,
    prospect_role: Optional[str],
    has_email: bool,
    web_context: str = "",
) -> str:
    """
    Generate a short outreach message via an OpenAI-compatible HTTP endpoint.
    Falls back to a descriptive error string on failure.
    """
    channel = "email" if has_email else "LinkedIn DM"
    prompt = (
        f"You are a B2B sales expert. Write a short, personalised outreach message.\n\n"
        f"PROSPECT: {prospect_name} ({prospect_role or 'Decision-maker'}) at {company}\n"
        f"CHANNEL: {channel}\n"
        f"CONTEXT: {web_context or 'No additional context available.'}\n\n"
        f"Rules:\n"
        f"- Keep it under 300 characters for LinkedIn DM, under 600 for email\n"
        f"- Be human, not salesy\n"
        f"- End with a soft question as CTA\n\n"
        f"Write the message only, no explanation."
    )

    base = settings.OPENAI_BASE_URL.rstrip("/") if settings.OPENAI_BASE_URL else ""
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"} if settings.OPENAI_API_KEY else {}

    # Try standard Chat Completions endpoint first
    endpoints = []
    if base:
        endpoints.append(f"{base}/v1/chat/completions")
        endpoints.append(f"{base}/v1/completions")
        endpoints.append(f"{base}/generate")

    # Default direct prompt payload
    payload = {
        "model": settings.OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 256,
        "temperature": 0.6,
    }

    for url in endpoints:
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=settings.OPENAI_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            # OpenAI-style response
            if isinstance(data, dict):
                # Chat completions
                choices = data.get("choices") or []
                if choices:
                    first = choices[0]
                    # Chat message
                    if isinstance(first.get("message"), dict):
                        return first["message"]["content"].strip()
                    # Text completions
                    text = first.get("text")
                    if text:
                        return text.strip()
                # Some proxies return top-level 'output' or 'content'
                if "output" in data:
                    return str(data["output"]).strip()
                if "content" in data:
                    return str(data["content"]).strip()
            # Fallback: return raw text
            return resp.text.strip()
        except Exception as exc:
            logger.warning("OpenAI-compatible fallback at %s failed: %s", url, exc)

    logger.error("All OpenAI fallback endpoints failed; returning error message")
    return f"⚠️ Both MCP and OpenAI fallback are unavailable. Check OPENAI_BASE_URL/OPENAI_API_KEY."


# ------------------------------------------------------------------
# Public function
# ------------------------------------------------------------------

def generate_outreach_message(
    target_prospect: str,
    target_company: str,
    prospect_role: Optional[str] = None,
    has_email: bool = False,
    web_context: str = "",
) -> str:
    """Generate an outreach message via Writer MCP, with Ollama as fallback.

    Args:
        target_prospect: Full name of the prospect.
        target_company: Prospect's company name.
        prospect_role: Job title (optional).
        has_email: True if an email address is available — determines channel.
        web_context: Optional web research context for the Ollama fallback prompt.
    """
    channel = "email" if has_email else "linkedin_dm"
    payload = {
        "target_prospect": target_prospect,
        "target_company": target_company,
        "prospect_role": prospect_role or "Decision-maker",
        "channel": channel,
        "stage": "first_touch",
        "intent": "direct_outreach",
        "company_name": settings.SENDER_COMPANY_NAME,
        "elevator_pitch": settings.ELEVATOR_PITCH,
        "offer_name": settings.OFFER_NAME,
        "solution_summary": settings.SOLUTION_SUMMARY,
        "cta": settings.CTA,
    }

    try:
        logger.info("Calling Writer MCP at %s", settings.OUTREACH_MCP_URL)
        result = asyncio.run(_call_mcp(payload))
        return _extract_message(result)
    except Exception as exc:
        logger.warning("MCP unavailable (%s), falling back to Ollama", exc)
        return _call_openai_fallback(
            target_prospect, target_company, prospect_role, has_email, web_context
        )
