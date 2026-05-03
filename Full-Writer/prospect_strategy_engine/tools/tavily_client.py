"""Tavily client — searches the web for context on a prospect."""

import requests
import logging
from config import settings

logger = logging.getLogger(__name__)


def search_prospect_context(prospect_name: str, company: str) -> dict:
    """Search the web for professional context on a prospect.

    Returns a dict with keys: profile_summary, raw_sources.
    Returns an empty dict (with an 'error' key) on failure.

    Args:
        prospect_name: Full name of the prospect, or a fallback like "CEO of Acme".
        company: Company name or domain.
    """
    if not settings.TAVILY_API_KEY:
        logger.error("TAVILY_API_KEY is not set in .env")
        return {"error": "TAVILY_API_KEY not configured"}

    # Build a query that targets professional activity and LinkedIn presence
    if not prospect_name or "None" in str(prospect_name):
        query = (
            f"Who leads {company}? Professional summary, LinkedIn activity level, "
            "and publication habits."
        )
    else:
        query = (
            f"Web and LinkedIn profile of {prospect_name} at {company}. "
            "Professional summary, recent posts, social media activity patterns, "
            "and LinkedIn engagement level."
        )

    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.TAVILY_API_KEY,
                "query": query,
                "search_depth": "advanced",
                "include_answer": True,
                "max_results": 3,
            },
            timeout=15,
        )
        if not response.ok:
            logger.warning("Tavily API error %s", response.status_code)
            return {"error": f"Tavily API error {response.status_code}"}

        data = response.json()
        summary = data.get("answer", "No automatic summary available.")

        raw_sources = ""
        for source in data.get("results", []):
            content = source.get("content", "")[:1500]
            raw_sources += f"- Source ({source.get('url')}): {content}\n\n"

        return {
            "profile_summary": f"PROFILE SUMMARY:\n{summary}\n\nWEB EXCERPTS:\n{raw_sources}",
            "raw_sources": raw_sources,
        }

    except Exception as exc:
        logger.exception("Unexpected error in search_prospect_context")
        return {"error": str(exc)}


if __name__ == "__main__":
    result = search_prospect_context("Yosr Ghozzi", "Esprit")
    if "error" not in result:
        print(result["profile_summary"].split("WEB EXCERPTS")[0])
    else:
        print(f"Error: {result['error']}")
