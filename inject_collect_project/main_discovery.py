import asyncio
import logging
import os
import json
import uuid
import urllib.parse
from datetime import datetime, timezone
from apollo_scraper import ApolloScraper
from database_manager import Neo4jManager
from apify_enricher import ApifyEnricher
from intent_collector import IntentCollector
from detective_formatter import DetectiveFormatter
from event_emitter import EventEmitter
from a2a_client import A2AClient
from persona_search_enrich import search_and_enrich
from dqs_calculator import compute_dqs
from processing_log import make_log_entry
from smart_scraper_ai import SmartScraperAI

logger = logging.getLogger(__name__)

# Ta clé API
APOLLO_KEY = os.getenv("APOLLO_API_KEY", "")


async def _gate_entity_validation(
    domain: str,
    company_name: str,
    apify_enricher: ApifyEnricher,
    processing_log: list,
) -> str:
    """
    Gate 1 — Entity Validation.
    Detect synthetic domains and attempt web-based correction via news search.
    Returns corrected domain (or original if no correction possible).
    Only appends to processing_log if the gate actually triggers (synthetic domain).
    """
    # Gate only triggers for synthetic domains with a valid company name
    if not domain.startswith("unknown_"):
        return domain
    if company_name in ("unknown", "", None):
        return domain

    # Synthetic domain + valid name: attempt correction
    try:
        results = await apify_enricher.search_news(company_name)
        if results and isinstance(results, list) and len(results) > 0 and results[0].get("url"):
            candidate = urllib.parse.urlparse(results[0].get("url", "")).netloc
            if candidate and not candidate.startswith("unknown_"):
                processing_log.append(make_log_entry(
                    "entity_validation", "domain_corrected", 0.0,
                    trigger="synthetic_domain", result=candidate,
                ))
                logger.info(
                    "Gate 1 [entity_validation]: %s → corrected domain: %s",
                    company_name, candidate,
                )
                print(f"🔍 Gate 1: Domaine synthétique corrigé pour {company_name} → {candidate}")
                return candidate
            else:
                processing_log.append(make_log_entry(
                    "entity_validation", "correction_failed", 0.0,
                    trigger="synthetic_domain", result=domain,
                ))
                logger.info(
                    "Gate 1 [entity_validation]: %s → no valid candidate found, retaining %s",
                    company_name, domain,
                )
                return domain
        else:
            processing_log.append(make_log_entry(
                "entity_validation", "correction_failed", 0.0,
                trigger="synthetic_domain", result=domain,
            ))
            logger.info(
                "Gate 1 [entity_validation]: %s → search returned no results, retaining %s",
                company_name, domain,
            )
            return domain
    except Exception as e:
        logger.warning("Gate 1 [entity_validation] error for %s: %s", company_name, e)
        processing_log.append(make_log_entry(
            "entity_validation", "search_failed", 0.0,
            trigger="synthetic_domain", result=domain, error=str(e),
        ))
        return domain


def _merge_ai_result(merged_profile: dict, ai_json_path: str) -> None:
    """
    Load Apollo Mirror JSON from ai_json_path and merge non-empty fields
    into merged_profile in-place.
    Only overwrites fields where existing value is None, "", or "Non renseigné".
    Extracts .value sub-field from confidence-scored objects.
    """
    _ABSENT = {None, "", "Non renseigné"}

    try:
        with open(ai_json_path, "r", encoding="utf-8") as f:
            ai_data = json.load(f)

        # Apollo Mirror flattening table: (nested path parts, flat key)
        mappings = [
            (["identity", "name"], "name"),
            (["identity", "industry"], "industry"),
            (["identity", "founded_year"], "founded_year"),
            (["identity", "short_description"], "short_description"),
            (["performance", "annual_revenue"], "annual_revenue"),
            (["performance", "estimated_num_employees"], "estimated_num_employees"),
            (["contact_social", "linkedin_url"], "linkedin_url"),
            (["contact_social", "twitter_url"], "twitter_url"),
            (["contact_social", "phone"], "phone"),
            (["location_detailed", "city"], "city"),
            (["location_detailed", "country"], "country"),
            (["keywords"], "keywords"),
        ]

        for path_parts, flat_key in mappings:
            # Navigate nested path
            node = ai_data
            for part in path_parts:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(part)

            if node is None:
                continue

            # Extract .value sub-field from confidence-scored objects
            if isinstance(node, dict):
                value = node.get("value")
            else:
                value = node

            # Only overwrite if AI value is non-empty and existing value is absent
            if value not in _ABSENT and merged_profile.get(flat_key) in _ABSENT:
                merged_profile[flat_key] = value

        # Technologies: list, no .value extraction
        technologies = ai_data.get("technologies")
        if (
            isinstance(technologies, list)
            and len(technologies) > 0
            and merged_profile.get("technologies") in (None, [], "Non renseigné", "")
        ):
            merged_profile["technologies"] = technologies

    except Exception as e:
        logger.warning("_merge_ai_result failed for %s: %s", ai_json_path, e)


async def _gate_data_quality(
    merged_profile: dict,
    domain: str,
    target_location: str,
    smart_scraper: SmartScraperAI,
    processing_log: list,
) -> dict:
    """
    Gate 2 — Data Quality.
    Evaluate DQS after merge and route to deep_scrape / flag_for_review / proceed_normal.
    Returns (possibly enriched) merged_profile.
    """
    try:
        dqs_before = compute_dqs(merged_profile)
        merged_profile["data_quality_score"] = dqs_before

        if domain.startswith("unknown_"):
            path_taken = "proceed_normal"
            worker_review_flag = False
            dqs_after = dqs_before
            logger.info(
                "Gate 2 [data_quality]: %s → synthetic domain, skipping SmartScraperAI (DQS=%.2f)",
                domain, dqs_before,
            )
            print(f"⚡ Gate 2: Domaine synthétique {domain}, SmartScraperAI ignoré (DQS={dqs_before:.2f})")

        elif dqs_before < 0.5:
            path_taken = "deep_scrape"
            worker_review_flag = False
            logger.info(
                "Gate 2 [data_quality]: %s → DQS=%.2f < 0.5, invoking SmartScraperAI",
                domain, dqs_before,
            )
            print(f"🧠 Gate 2: DQS={dqs_before:.2f} < 0.5 pour {domain} → SmartScraperAI activé")

            try:
                ai_json_path = await asyncio.wait_for(
                    asyncio.to_thread(
                        smart_scraper.scrape_and_save,
                        f"https://{domain}",
                        target_location,
                    ),
                    timeout=120.0,
                )
                if ai_json_path is not None and os.path.exists(ai_json_path):
                    _merge_ai_result(merged_profile, ai_json_path)
                    dqs_after = compute_dqs(merged_profile)
                    merged_profile["data_quality_score"] = dqs_after
                    logger.info(
                        "Gate 2 [data_quality]: %s → SmartScraperAI enriched, DQS %.2f → %.2f",
                        domain, dqs_before, dqs_after,
                    )
                    print(f"✅ Gate 2: SmartScraperAI enrichi {domain} (DQS {dqs_before:.2f} → {dqs_after:.2f})")
                else:
                    dqs_after = dqs_before
                    logger.warning(
                        "Gate 2 [data_quality]: SmartScraperAI returned no result for %s", domain
                    )
                    print(f"⚠️ Gate 2: SmartScraperAI n'a retourné aucun résultat pour {domain}")
                    processing_log.append(make_log_entry(
                        "data_quality", "scraper_empty", dqs_before,
                        dqs_before=dqs_before, path_taken=path_taken,
                        dqs_after=dqs_after, worker_review_flag=worker_review_flag,
                    ))
                    return merged_profile

            except asyncio.TimeoutError:
                dqs_after = dqs_before
                logger.warning(
                    "Gate 2 [data_quality]: SmartScraperAI timed out for %s after 120s", domain
                )
                print(f"⏱️ Gate 2: SmartScraperAI timeout pour {domain} (120s)")
                processing_log.append(make_log_entry(
                    "data_quality", "scraper_timeout", dqs_before,
                    dqs_before=dqs_before, path_taken=path_taken,
                    dqs_after=dqs_after, worker_review_flag=worker_review_flag,
                ))
                return merged_profile

            except Exception as e:
                dqs_after = dqs_before
                logger.warning(
                    "Gate 2 [data_quality]: SmartScraperAI failed for %s: %s", domain, e
                )
                print(f"⚠️ Gate 2: SmartScraperAI erreur pour {domain}: {e}")
                processing_log.append(make_log_entry(
                    "data_quality", "scraper_empty", dqs_before,
                    dqs_before=dqs_before, path_taken=path_taken,
                    dqs_after=dqs_after, worker_review_flag=worker_review_flag,
                    error=str(e),
                ))
                return merged_profile

        elif dqs_before < 0.75:
            path_taken = "flag_for_review"
            worker_review_flag = True
            dqs_after = dqs_before
            logger.info(
                "Gate 2 [data_quality]: %s → DQS=%.2f in [0.5, 0.75), flagging for Worker review",
                domain, dqs_before,
            )
            print(f"🟡 Gate 2: DQS={dqs_before:.2f} pour {domain} → flagué pour révision Worker")

        else:
            path_taken = "proceed_normal"
            worker_review_flag = False
            dqs_after = dqs_before
            logger.info(
                "Gate 2 [data_quality]: %s → DQS=%.2f >= 0.75, proceeding normally",
                domain, dqs_before,
            )
            print(f"✅ Gate 2: DQS={dqs_before:.2f} pour {domain} → qualité suffisante, traitement normal")

        merged_profile["data_quality_score"] = dqs_after
        processing_log.append(make_log_entry(
            "data_quality", path_taken, dqs_after,
            dqs_before=dqs_before, path_taken=path_taken,
            dqs_after=dqs_after, worker_review_flag=worker_review_flag,
        ))
        return merged_profile

    except Exception as e:
        logger.warning("Gate 2 [data_quality] error for %s: %s", domain, e)
        processing_log.append(make_log_entry(
            "data_quality", "gate_error", 0.0,
            error=str(e),
        ))
        return merged_profile


def _gate_persona_worthiness(
    merged_profile: dict,
    intent_signals: dict,
    dqs: float,
    processing_log: list,
) -> bool:
    """
    Gate 3 — Persona Worthiness.
    Evaluate whether the company has sufficient signal to justify persona discovery.
    Returns True if persona cascade should run, False to skip.
    """
    try:
        job_postings_count = intent_signals.get("job_postings_count", 0) or 0
        has_news = bool(intent_signals.get("recent_news"))
        has_employee_count = bool(
            merged_profile.get("estimated_num_employees")
            not in (None, "", "Non renseigné", 0, "0")
        )
        domain = merged_profile.get("domain", "unknown")

        if dqs >= 0.5 and (job_postings_count > 0 or has_news or has_employee_count):
            decision = "run_personas"
            logger.info(
                "Gate 3 [persona_worthiness]: %s → run_personas (DQS=%.2f, jobs=%d, news=%s, employees=%s)",
                domain, dqs, job_postings_count, has_news, has_employee_count,
            )
            print(f"👤 Gate 3: {domain} → personas activés (DQS={dqs:.2f})")
            result = True
        else:
            decision = "skip_personas"
            reason = "dqs_too_low" if dqs < 0.5 else "no_signals"
            logger.info(
                "Gate 3 [persona_worthiness]: %s → skip_personas (DQS=%.2f, reason=%s)",
                domain, dqs, reason,
            )
            print(f"⏩ Gate 3: {domain} → personas ignorés (DQS={dqs:.2f}, raison={reason})")
            result = False

        processing_log.append(make_log_entry(
            "persona_worthiness", decision, dqs,
            dqs=dqs, job_postings_count=job_postings_count,
            has_news=has_news, has_employee_count=has_employee_count,
            decision=decision,
        ))
        return result

    except Exception as e:
        logger.warning("Gate 3 [persona_worthiness] error: %s", e)
        processing_log.append(make_log_entry(
            "persona_worthiness", "gate_error", 0.0,
            error=str(e),
        ))
        return False


async def _process_company(
    company,
    scraper,
    db,
    apify_enricher,
    intent_collector,
    detective_formatter,
    event_emitter,
    target_location,
    smart_scraper,
    on_company_ready=None,
    a2a_client=None,
):
    """Process a single company through the full agentic enrichment pipeline."""
    # --- INITIALISATION DU PROCESSING LOG ---
    processing_log: list = []

    # --- RÉCUPÉRATION DU DOMAINE ---
    domain = company.get("domain")
    company_name = company.get("name", "unknown")
    valid_domain = domain and domain != "Non renseigné" and domain != ""

    full_data = company

    # --- (a) ENRICHISSEMENT APOLLO ---
    if valid_domain:
        print(f"💎 Tentative d'enrichissement pour le domaine : {domain}...")
        try:
            enriched_data = await asyncio.to_thread(
                scraper.enrich_organization, domain=domain, target_location=target_location
            )
            if enriched_data:
                full_data = enriched_data
            else:
                print(f"🟠 Fallback : Enrichissement échoué. Utilisation des données basiques.")
        except Exception as e:
            print(f"⚠️ Erreur API lors de l'enrichissement : {e}")
            print(f"🟠 Fallback : Utilisation des données basiques.")
    else:
        print(f"⏩ Aucun domaine pour {company_name}. Enrichissement Apollo ignoré.")

    # --- (b) ANTI-COLLISION ---
    current_domain = full_data.get("domain")
    current_id = full_data.get("apollo_id")
    if (not current_domain or current_domain in ("Non renseigné", "")) and (
        not current_id or current_id == "Non renseigné"
    ):
        safe_name = str(full_data.get("name", "unknown")).replace(" ", "_").lower()
        full_data["domain"] = f"unknown_{safe_name}"
        print(f"🔧 Correction Anti-Collision : domaine fictif -> {full_data['domain']}")

    domain = full_data.get("domain", domain)

    # --- [GATE 1] ENTITY VALIDATION ---
    domain = await _gate_entity_validation(domain, company_name, apify_enricher, processing_log)
    full_data["domain"] = domain

    # --- (c) APIFY WEBSITE CRAWL ---
    apify_data = {}
    if domain and not domain.startswith("unknown_"):
        try:
            apify_data = await apify_enricher.crawl_website(domain)
        except Exception as e:
            print(f"⚠️ Apify crawl failed for {domain}: {e}")
            apify_data = {}

    # --- (d) INTENT SIGNALS ---
    intent_signals = {}
    try:
        intent_signals = await intent_collector.collect(domain, company_name)
    except Exception as e:
        print(f"⚠️ Intent collection failed for {domain}: {e}")
        intent_signals = {"recent_news": [], "job_postings_count": 0, "technology_changes": []}

    # --- (e) BUILD MERGED PROFILE (Apollo takes precedence over Apify) ---
    merged_profile = {**apify_data, **full_data}

    # --- [GATE 2] DATA QUALITY ---
    merged_profile = await _gate_data_quality(
        merged_profile, domain, target_location, smart_scraper, processing_log
    )

    # --- (f) NEO4J WRITE ---
    injected_domain = None
    try:
        db.import_merged_profiles([merged_profile])
        injected_domain = merged_profile.get("domain")
        print(f"💾 Injection immédiate de : {merged_profile.get('name', 'Compagnie inconnue')}")
    except Exception as e:
        print(f"❌ Erreur lors de l'injection de {merged_profile.get('name')}: {e}")
        # Fallback to bulk_import_companies
        try:
            db.bulk_import_companies([full_data])
            injected_domain = full_data.get("domain")
        except Exception as e2:
            print(f"❌ Fallback injection also failed: {e2}")

    # --- [GATE 3] PERSONA WORTHINESS ---
    dqs = merged_profile.get("data_quality_score", 0.0)
    run_personas = _gate_persona_worthiness(merged_profile, intent_signals, dqs, processing_log)

    # --- (g) PERSONA CASCADE (conditional) ---
    personas_found = []
    if run_personas and injected_domain:
        company_country = merged_profile.get("country")
        if not company_country or company_country == "Non renseigné":
            company_country = merged_profile.get("location", {}).get("country", target_location)
        print(f"👤 Lancement de la recherche de personas (Sales) pour {domain} en {company_country}...")
        try:
            personas_found = search_and_enrich(domain=domain, location=company_country, role="Sales") or []
            if personas_found:
                print(f"👥 {len(personas_found)} personas découverts.")
                db.import_personas(personas_found, injected_domain)
            else:
                print(f"ℹ️ Aucun persona trouvé pour {domain}.")
        except Exception as e:
            print(f"❌ Erreur lors de la recherche des personas : {e}")
    else:
        logger.info("Persona cascade skipped for %s (run_personas=%s)", domain, run_personas)

    # --- (h) DETECTIVE FORMAT ---
    payload = detective_formatter.format(
        merged_profile, personas_found, intent_signals, processing_log=processing_log
    )

    # --- (i) EVENT EMIT ---
    envelope = None
    try:
        envelope = {
            "event_id": str(uuid.uuid4()),
            "correlation_id": payload["correlation_id"],
            "module": "inject",
            "event_type": payload["event_type"],
            "timestamp": payload["timestamp"],
            "payload": payload,
            "metadata": {"processing_log": processing_log},
        }
        await a2a_client.send_lead_ingested(envelope)
    except Exception as e:
        print(f"⚠️ Event emission failed for {domain}: {e}")

    # --- (i-bis) DETECTIVE SCORING ---
    try:
        if envelope:
            scored_result = await a2a_client.send_to_detective(envelope)
            if scored_result and scored_result.get("qualified_for_outreach"):
                print(f"✅ Detective: {domain} qualified (score={scored_result.get('final_score', 0):.2f})")
            elif scored_result:
                print(f"⏩ Detective: {domain} below threshold (score={scored_result.get('final_score', 0):.2f})")
            else:
                print(f"⚠️ Detective: no scoring result for {domain}")
    except Exception as e:
        print(f"⚠️ Detective scoring failed for {domain}: {e}")

    # --- BACKWARD COMPAT: on_company_ready callback ---
    if on_company_ready and injected_domain:
        on_company_ready(injected_domain)

    # --- (j) RETURN PAYLOAD ---
    return payload


async def discover_and_inject(
    industry: str = "IT",
    location: str = "France",
    limit: int = 10,
    on_company_ready=None,
):
    # --- CONFIGURATION DYNAMIQUE ---
    TARGET_INDUSTRY = industry
    TARGET_LOCATION = location
    MAX_COMPANIES_TO_GET = limit

    scraper = ApolloScraper(APOLLO_KEY)
    db = Neo4jManager()

    apify_enricher = ApifyEnricher()
    intent_collector = IntentCollector(apify_enricher)
    detective_formatter = DetectiveFormatter()
    event_emitter = EventEmitter()
    a2a_client = A2AClient(
        worker_url=os.environ.get("WORKER_A2A_URL", "http://api:8000"),
        event_emitter=event_emitter,
    )
    smart_scraper = SmartScraperAI()  # Instantiated once — shared across all company tasks

    # 1. PHASE DE DÉCOUVERTE (SEARCH)
    print(f"🔎 Recherche initiale de {MAX_COMPANIES_TO_GET} entreprises en {TARGET_LOCATION}...")
    basic_companies = scraper.search_companies(
        industries=[TARGET_INDUSTRY],
        locations=[TARGET_LOCATION],
        limit=MAX_COMPANIES_TO_GET,
    )

    if not basic_companies:
        print("❌ Résultats de recherche vides. Vérifiez les filtres ou la clé API.")
        db.close()
        return []

    print(f"💎 Enrichissement profond de {len(basic_companies)} entreprises...")

    # 2. ASYNC GATHER — process all companies concurrently
    tasks = [
        asyncio.create_task(
            _process_company(
                c,
                scraper,
                db,
                apify_enricher,
                intent_collector,
                detective_formatter,
                event_emitter,
                TARGET_LOCATION,
                smart_scraper,
                on_company_ready,
                a2a_client,
            )
        )
        for c in basic_companies
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    db.close()
    print("✅ Processus complet terminé avec succès.")

    # Return only successful Detective payloads (filter out exceptions)
    return [r for r in results if isinstance(r, dict)]


if __name__ == "__main__":
    asyncio.run(discover_and_inject())
