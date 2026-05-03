"""Hunter.io client — finds the decision-maker for a given company domain."""

import requests
import logging
from typing import Optional
from config import settings

logger = logging.getLogger(__name__)


def find_decision_maker(domain: str, title_keyword: str = "CEO") -> dict:
    """Search for a company's decision-maker via the Hunter.io domain-search API.

    Returns a dict with keys: name, title, email, linkedin_url, company.
    Returns an empty dict (with an 'error' key) on failure.

    Args:
        domain: Company domain, e.g. "doctolib.fr"
        title_keyword: Job title to prioritise, e.g. "CEO". Falls back to the
                       first contact found if no match.
    """
    if not settings.HUNTER_API_KEY:
        logger.error("HUNTER_API_KEY is not set in .env")
        return {"error": "HUNTER_API_KEY not configured"}

    try:
        response = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": settings.HUNTER_API_KEY, "limit": 10},
            timeout=10,
        )
        if not response.ok:
            logger.warning("Hunter API error %s: %s", response.status_code, response.text)
            return {"error": f"Hunter API error {response.status_code}"}

        data = response.json().get("data", {})
        emails = data.get("emails", [])
        company_name = data.get("organization", domain)

        if not emails:
            logger.info("No public emails found for domain: %s", domain)
            return {"error": f"No public emails found for {domain}"}

        # Prefer the contact whose title matches title_keyword
        target = next(
            (c for c in emails if title_keyword.lower() in (c.get("position") or "").lower()),
            emails[0],  # fallback to first contact
        )

        first = target.get("first_name") or ""
        last = target.get("last_name") or ""
        full_name = f"{first} {last}".strip() or f"Head of {target.get('position', 'Strategy')}"

        return {
            "name": full_name,
            "title": target.get("position", "Unknown title"),
            "email": target.get("value"),
            "linkedin_url": target.get("linkedin"),
            "company": company_name,
        }

    except Exception as exc:
        logger.exception("Unexpected error in find_decision_maker")
        return {"error": str(exc)}


if __name__ == "__main__":
    import json
    result = find_decision_maker("actia.com")
    print(json.dumps(result, indent=2, ensure_ascii=False))
