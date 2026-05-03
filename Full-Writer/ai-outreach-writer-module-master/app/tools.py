import random
import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta
from .models import Signal
from .config import settings
import httpx

logger = logging.getLogger(__name__)


class ResearchTools:
    """Research tools.

    Real API integrations are stubbed — set USE_MOCK_DATA=false and supply the
    relevant API key to enable each one. Until then, mock data is returned and
    a warning is logged so it's never silently invisible.
    """

    @staticmethod
    def fetch_linkedin_posts(name: str, company: str, detective_context: dict = None) -> List[Signal]:
        """Fetch LinkedIn posts.

        Priority order:
        1. Detective enrichment data (when detective_context is provided)
        2. Real LinkedIn API (when USE_MOCK_DATA=false and LINKEDIN_API_KEY is set) — NOT YET IMPLEMENTED
        3. Mock data fallback
        """
        # 1. Use real Detective enrichment data if available
        if detective_context:
            signals = []
            intent_signals = detective_context.get("intent_signals", {})

            for news in intent_signals.get("recent_news", []):
                signals.append(Signal(
                    type="company_news",
                    content=news.get("title", f"Recent development at {company}"),
                    strength="high",
                    source_url=news.get("url", ""),
                    why_relevant="Real data from Detective enrichment pipeline",
                ))

            tech_changes = intent_signals.get("technology_changes", [])
            if tech_changes:
                signals.append(Signal(
                    type="technology_change",
                    content=f"{company} is adopting new technologies: {', '.join(tech_changes)}",
                    strength="medium",
                    why_relevant="Technology stack changes indicate growth and investment",
                ))

            job_count = intent_signals.get("job_postings_count", 0)
            if job_count > 0:
                signals.append(Signal(
                    type="hiring_signal",
                    content=f"{company} has {job_count} open job postings, indicating active growth",
                    strength="high" if job_count > 10 else "medium",
                    why_relevant="Active hiring signals growth and budget availability",
                ))

            if signals:
                return signals

        # 2. Real LinkedIn API — not yet implemented
        if not settings.USE_MOCK_DATA and settings.LINKEDIN_API_KEY:
            logger.warning(
                "USE_MOCK_DATA=false and LINKEDIN_API_KEY is set, but real LinkedIn API "
                "integration is not yet implemented. Falling back to mock data."
            )

        # 3. Mock fallback
        logger.debug("fetch_linkedin_posts: returning mock data for %s @ %s", name, company)
        mock_posts = [
            {
                "content": f"Just hit a major milestone at {company} — our team doubled revenue this quarter through a new SDR pod approach.",
                "strength": "high",
                "timestamp": (datetime.now() - timedelta(days=2)).isoformat(),
            },
            {
                "content": f"Excited to share that {company} is hiring! Looking for talented folks who want to scale with us.",
                "strength": "medium",
                "timestamp": (datetime.now() - timedelta(days=5)).isoformat(),
            },
            {
                "content": "Really interesting article about AI in sales. The future is here.",
                "strength": "low",
                "timestamp": (datetime.now() - timedelta(days=10)).isoformat(),
            },
        ]
        selected = random.sample(mock_posts, k=random.randint(1, 2))
        return [
            Signal(
                type="linkedin_post",
                content=post["content"],
                strength=post["strength"],
                timestamp=post["timestamp"],
                source_url=f"https://linkedin.com/posts/{name.lower().replace(' ', '-')}-{random.randint(1000, 9999)}",
                why_relevant="Recent professional activity showing current priorities and interests",
            )
            for post in selected
        ]

    @staticmethod
    def fetch_company_news(company: str) -> List[Signal]:
        """Fetch company news.

        Real News API integration is not yet implemented.
        Set USE_MOCK_DATA=false and NEWS_API_KEY to enable it when ready.
        """
        if not settings.USE_MOCK_DATA and settings.NEWS_API_KEY:
            logger.warning(
                "USE_MOCK_DATA=false and NEWS_API_KEY is set, but real News API "
                "integration is not yet implemented. Falling back to mock data."
            )

        logger.debug("fetch_company_news: returning mock data for %s", company)
        mock_news = [
            {
                "content": f"{company} announces new AI-powered product features to streamline customer workflows",
                "strength": "high",
                "timestamp": (datetime.now() - timedelta(days=1)).isoformat(),
            },
            {
                "content": f"{company} raises Series B funding to expand into European markets",
                "strength": "medium",
                "timestamp": (datetime.now() - timedelta(days=7)).isoformat(),
            },
            {
                "content": f"{company} named one of the fastest-growing companies in their sector",
                "strength": "medium",
                "timestamp": (datetime.now() - timedelta(days=14)).isoformat(),
            },
        ]
        selected = random.choice(mock_news)
        return [
            Signal(
                type="company_news",
                content=selected["content"],
                strength=selected["strength"],
                timestamp=selected["timestamp"],
                source_url=f"https://techcrunch.com/2024/01/15/{company.lower()}-news",
                why_relevant="Recent company developments showing growth trajectory and strategic focus",
            )
        ]

    @staticmethod
    def get_crm_history(name: str) -> Dict[str, Any]:
        """Get CRM history.

        Real CRM integration is not yet implemented.
        Set USE_MOCK_DATA=false and CRM_DATABASE_URL to enable it when ready.
        """
        if not settings.USE_MOCK_DATA and settings.CRM_DATABASE_URL:
            logger.warning(
                "USE_MOCK_DATA=false and CRM_DATABASE_URL is set, but real CRM "
                "integration is not yet implemented. Falling back to mock data."
            )

        logger.debug("get_crm_history: returning mock data for %s", name)
        has_history = random.random() > 0.7  # 30% chance of past contact
        return {
            "past_contact": has_history,
            "last_contact_date": (
                (datetime.now() - timedelta(days=random.randint(30, 180))).isoformat()
                if has_history
                else None
            ),
            "last_seen_topic": "product demo" if has_history else None,
            "replied_before": has_history and random.random() > 0.5,
            "engagement_score": random.randint(1, 10) if has_history else 0,
        }

class ReasoningTools:
    """Deterministic helpers used by the Critic for rule-based checks."""

    @staticmethod
    def detect_placeholder_text(message: str) -> bool:
        """Detect unfilled placeholder tokens like [Company], [Name], [Result], etc."""
        import re
        return bool(re.search(r'\[.{1,40}\]', message))

    @staticmethod
    def detect_overpersonalization(message: str) -> bool:
        """Detect phrases that would feel intrusive or creepy to a prospect."""
        creepy_phrases = [
            "i saw your house",
            "i know where you live",
            "i noticed your kids",
            "i saw your family",
            "i know your address",
            "i've been watching",
            "i followed you",
            "stalking your profile",
        ]
        message_lower = message.lower()
        return any(phrase in message_lower for phrase in creepy_phrases)