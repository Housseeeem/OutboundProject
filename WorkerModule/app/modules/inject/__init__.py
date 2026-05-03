"""
Inject module – data ingestion
Fetches enriched company intelligence from Neo4j.

On-demand persona discovery: when Neo4j returns 0 personas for a domain,
the module automatically calls search_and_enrich() from inject_collect_project
to discover personas live, writes them back to Neo4j, and returns them.
"""

import os
import sys
import json
import logging
from pathlib import Path
from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

# Environment-based connection parameters
# Supports both GRAPH_DB_* (WorkerModule convention) and NEO4J_* (legacy)
_NEO4J_URI = (
    os.environ.get("NEO4J_URI")
    or os.environ.get("GRAPH_DB_URL")
    or "bolt://neo4j:7687"
)
_NEO4J_USER = (
    os.environ.get("NEO4J_USER")
    or os.environ.get("GRAPH_DB_USER")
    or "neo4j"
)
_NEO4J_PASSWORD = (
    os.environ.get("NEO4J_PASSWORD")
    or os.environ.get("GRAPH_DB_PASSWORD")
    or "password"
)

# ---------------------------------------------------------------------------
# Lazy import helper for inject_collect_project.persona_search_enrich
# The package lives in a sibling directory; we add it to sys.path on first use.
# ---------------------------------------------------------------------------
_WORKSPACE_ROOT = Path(__file__).resolve().parents[4]  # …/OutboundProject


def _get_search_and_enrich():
    """
    Return the search_and_enrich function from inject_collect_project,
    adding the workspace root to sys.path if needed.
    Returns None if the import fails (so callers can degrade gracefully).
    """
    # Try Docker volume mount path first (/inject_collect_project),
    # then fall back to the local workspace sibling directory.
    candidate_paths = ["/", str(_WORKSPACE_ROOT)]
    for path in candidate_paths:
        if path not in sys.path:
            sys.path.insert(0, path)
    try:
        from inject_collect_project.persona_search_enrich import search_and_enrich
        return search_and_enrich
    except Exception as exc:
        logger.warning("Could not import search_and_enrich: %s", exc)
        return None

# Module-level driver (lazy initialization)
_driver = None


class InjectModuleError(Exception):
    """Raised when the inject module encounters a fatal error."""


def _get_driver():
    """Return the module-level Neo4j driver, creating it on first call."""
    global _driver
    if _driver is not None:
        return _driver

    uri = _NEO4J_URI
    user = _NEO4J_USER
    password = _NEO4J_PASSWORD

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        _driver = driver
        logger.info("Neo4j driver initialized and connectivity verified.")
        return _driver
    except Exception as exc:
        logger.error("Failed to connect to Neo4j at %s: %s", uri, exc)
        raise InjectModuleError(
            f"Cannot connect to Neo4j at '{uri}': {exc}"
        ) from exc


def close():
    """Close the module-level Neo4j driver."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("Neo4j driver closed.")


def _write_personas_to_neo4j(personas: list, domain: str) -> None:
    """
    Write a list of persona dicts to Neo4j, linking them to the Company node
    identified by *domain*.  Mirrors the logic in
    inject_collect_project/database_manager.py::import_personas().
    """
    if not personas:
        return

    processed = []
    for p in personas:
        p_clean = dict(p)
        # Normalise key fields so the Cypher query always has something to work with
        p_clean["full_name"] = (
            p_clean.get("full_name")
            or p_clean.get("clean_name_used")
            or "Inconnu"
        )
        p_clean["title"] = (
            p_clean.get("title")
            or p_clean.get("job_title_role")
            or "Non trouvé"
        )
        # Neo4j cannot store list/dict properties directly — serialise them
        for field in ("education", "experience", "skills", "emails",
                      "aeroleads_raw_data", "interests"):
            if field in p_clean and isinstance(p_clean[field], (list, dict)):
                p_clean[field] = json.dumps(p_clean[field], ensure_ascii=False)
        processed.append(p_clean)

    query = """
    UNWIND $batch AS p_data
    MATCH (c:Company {domain: $domain})
    MERGE (p:Persona {linkedin_url: COALESCE(p_data.linkedin_url, p_data.full_name + '_' + $domain)})
    SET p += p_data,
        p.last_updated = datetime()
    MERGE (p)-[:WORKS_AT]->(c)
    """
    try:
        driver = _get_driver()
        with driver.session() as session:
            session.run(query, batch=processed, domain=domain)
        logger.info(
            "Wrote %d persona(s) to Neo4j for domain='%s'", len(processed), domain
        )
    except Exception as exc:
        logger.warning(
            "Failed to write personas to Neo4j for domain='%s': %s", domain, exc
        )


def _discover_personas_live(domain: str, company_profile: dict) -> list:
    """
    Trigger on-demand persona discovery via search_and_enrich() when Neo4j
    has no personas for *domain*.

    Infers the best location from the company profile so the Serper/LinkedIn
    query is geographically relevant.

    Returns a list of normalised persona dicts (may be empty on failure).
    """
    search_and_enrich = _get_search_and_enrich()
    if search_and_enrich is None:
        logger.warning(
            "search_and_enrich unavailable — skipping live persona discovery for '%s'",
            domain,
        )
        return []

    # Derive location: prefer city, fall back to country, then empty string
    location = (
        company_profile.get("city")
        or company_profile.get("country")
        or ""
    )

    logger.info(
        "No personas in Neo4j for domain='%s' — running live discovery (location='%s')",
        domain,
        location,
    )
    try:
        raw_personas = search_and_enrich(domain=domain, location=location, role="Sales")
        if not raw_personas:
            logger.info("Live discovery returned 0 personas for domain='%s'", domain)
            return []

        logger.info(
            "Live discovery found %d persona(s) for domain='%s'",
            len(raw_personas),
            domain,
        )

        # Persist to Neo4j so subsequent calls are instant
        _write_personas_to_neo4j(raw_personas, domain)

        # Normalise to the same shape that the Neo4j query returns
        normalised = []
        for p in raw_personas:
            normalised.append({
                "full_name": p.get("full_name") or p.get("clean_name_used") or "",
                "title": p.get("title") or p.get("job_title_role") or "",
                "email": p.get("email") or "",
                "phone": p.get("phone") or "",
                "linkedin_url": p.get("linkedin_url") or "",
            })
        return normalised

    except Exception as exc:
        logger.warning(
            "Live persona discovery failed for domain='%s': %s", domain, exc
        )
        return []


def fetch_company_intelligence(domain: str) -> dict:
    """
    Query Neo4j for enriched company data.

    If the company exists in Neo4j but has no linked Persona nodes, the
    function automatically triggers a live persona discovery via
    search_and_enrich() (Serper → Hunter → Snov.io → Tomba → AeroLeads),
    writes the results back to Neo4j, and returns them — so subsequent calls
    for the same domain are served entirely from the graph.

    Returns a dict with keys:
        status              – "ok" | "not_found" | "error"
        company_profile     – dict of company attributes
        personas            – list of persona dicts
        funding_events      – list of funding event dicts
        news_articles       – list of news article dicts
        personas_discovered – bool  (True when live discovery was triggered)
        error               – str   (only present when status == "error")
    """
    _empty = {
        "company_profile": {},
        "personas": [],
        "funding_events": [],
        "news_articles": [],
        "personas_discovered": False,
    }

    # --- 1. Validate domain ---
    if not isinstance(domain, str) or not domain.strip():
        return {
            "status": "error",
            "error": "domain must be a non-empty string",
            **_empty,
        }

    domain = domain.strip()
    logger.info("fetch_company_intelligence called for domain='%s'", domain)

    try:
        driver = _get_driver()

        with driver.session() as session:

            # --- 2a. Company profile ---
            profile_result = session.run(
                "MATCH (c:Company {domain: $domain})-[:CURRENT]->(v:Version) RETURN v",
                domain=domain,
            )
            profile_record = profile_result.single()

            if profile_record is None:
                logger.info(
                    "No company found in Neo4j for domain='%s' — attempting live persona discovery",
                    domain,
                )
                # Company not yet in Neo4j (never pre-ingested).
                # Build a minimal profile from the domain name and run live discovery
                # so the agent still gets usable personas.
                minimal_profile = {
                    "name": domain.split(".")[0].capitalize(),
                    "domain": domain,
                    "industry": None,
                    "founded_year": None,
                    "annual_revenue": None,
                    "estimated_num_employees": None,
                    "city": None,
                    "country": None,
                    "technologies": [],
                    "funding_events": [],
                    "suborganizations": [],
                }
                live_personas = _discover_personas_live(domain, minimal_profile)
                personas_discovered = bool(live_personas)
                logger.info(
                    "fetch_company_intelligence domain='%s' (not_found): %d persona(s) discovered",
                    domain,
                    len(live_personas),
                )
                return {
                    "status": "not_found",
                    "company_profile": minimal_profile,
                    "personas": live_personas,
                    "funding_events": [],
                    "news_articles": [],
                    "personas_discovered": personas_discovered,
                }

            v = profile_record["v"]

            # Deserialize JSON string fields
            def _deserialize(value, field_name):
                if isinstance(value, str):
                    try:
                        return json.loads(value)
                    except json.JSONDecodeError as exc:
                        logger.error(
                            "JSON decode error for field '%s' on domain='%s': %s",
                            field_name, domain, exc,
                        )
                        return []
                return value if value is not None else []

            company_profile = {
                "name": v.get("name"),
                "industry": v.get("industry"),
                "founded_year": v.get("founded_year"),
                "annual_revenue": v.get("annual_revenue"),
                "estimated_num_employees": v.get("estimated_num_employees"),
                "city": v.get("city"),
                "country": v.get("country"),
                "technologies": _deserialize(v.get("technologies"), "technologies"),
                "funding_events": _deserialize(v.get("funding_events"), "funding_events"),
                "suborganizations": _deserialize(v.get("suborganizations"), "suborganizations"),
            }

            # --- 2b. Personas ---
            personas_result = session.run(
                """
                MATCH (p:Persona)-[:WORKS_AT]->(c:Company {domain: $domain})
                RETURN p.full_name AS full_name,
                       p.title AS title,
                       p.email AS email,
                       p.phone AS phone,
                       p.linkedin_url AS linkedin_url
                """,
                domain=domain,
            )
            personas = [
                {
                    "full_name": r["full_name"],
                    "title": r["title"],
                    "email": r["email"],
                    "phone": r["phone"],
                    "linkedin_url": r["linkedin_url"],
                }
                for r in personas_result
            ]

            # --- 2c. Funding events ---
            funding_result = session.run(
                "MATCH (c:Company {domain: $domain})-[:HAS_FUNDING]->(fe:FundingEvent) RETURN fe",
                domain=domain,
            )
            funding_events = []
            for r in funding_result:
                fe = r["fe"]
                funding_events.append({
                    "title": fe.get("title"),
                    "date": fe.get("date"),
                    "investor": fe.get("investor") if fe.get("investor") is not None else "Non renseigné",
                    "amount": fe.get("amount") if fe.get("amount") is not None else "Non renseigné",
                    "source": fe.get("source"),
                    "url": fe.get("url"),
                    "event_confidence": fe.get("event_confidence"),
                })

            # --- 2d. News articles ---
            news_result = session.run(
                "MATCH (c:Company {domain: $domain})-[:HAS_NEWS]->(na:NewsArticle) RETURN na",
                domain=domain,
            )
            news_articles = []
            for r in news_result:
                na = r["na"]
                news_articles.append({
                    "title": na.get("title"),
                    "date": na.get("date") if na.get("date") is not None else "Non renseigné",
                    "source": na.get("source"),
                    "url": na.get("url"),
                    "event_confidence": na.get("event_confidence"),
                })

        # --- 3. On-demand persona discovery ---
        # If Neo4j has no personas for this domain, trigger live discovery now.
        # The results are written back to Neo4j so future calls are instant.
        personas_discovered = False
        if not personas:
            logger.info(
                "0 personas in Neo4j for domain='%s' — triggering live discovery",
                domain,
            )
            personas = _discover_personas_live(domain, company_profile)
            personas_discovered = bool(personas)

        logger.info(
            "fetch_company_intelligence domain='%s': %d persona(s) "
            "(discovered=%s), %d funding event(s), %d news article(s)",
            domain,
            len(personas),
            personas_discovered,
            len(funding_events),
            len(news_articles),
        )

        return {
            "status": "ok",
            "company_profile": company_profile,
            "personas": personas,
            "funding_events": funding_events,
            "news_articles": news_articles,
            "personas_discovered": personas_discovered,
        }

    except InjectModuleError:
        raise
    except Exception as exc:
        logger.error(
            "Neo4j query failed for domain='%s': %s", domain, exc, exc_info=True
        )
        return {
            "status": "error",
            "error": str(exc),
            **_empty,
        }
