import requests
import json
import re
import time
import os

# --- CONFIGURATION API (read from env, with hardcoded fallbacks for local use) ---
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "cc064d59deba3eb973bb6891f6dbe6af5a4a2ce6fc8b5d6f4ad58f03135ce800")
HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "c28d7fe76aeb9acf05f553b5b0976f06f216078f")
SNOVIO_CLIENT_ID = os.environ.get("SNOVIO_CLIENT_ID", "011b92adbfae5af804329bbd5d854110")
SNOVIO_CLIENT_SECRET = os.environ.get("SNOVIO_CLIENT_SECRET", "1415fcaae5046ff72804ec90301f14e3")
TOMBA_API_KEY = os.environ.get("TOMBA_API_KEY", "ta_tpnwwttihx8m76ke2558tjdso9jnds4wk40es")
TOMBA_API_SECRET = os.environ.get("TOMBA_API_SECRET", "ts_282a1b3d-a454-498d-acb3-666ed8f04cb6")
AEROLEADS_API_KEY = os.environ.get("AEROLEADS_API_KEY", "14d7acd6938c24ba059014c50f1eff35")

def clean_linkedin_name(raw_name):
    """Nettoie les scories de LinkedIn pour avoir un nom propre"""
    clean = raw_name.replace('\u200f', '').replace('\u200e', '')
    clean = re.split(r'[|,\-]', clean)[0]
    return clean.strip()

def split_name(full_name):
    """Sépare le prénom et le nom"""
    parts = full_name.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    first_name = parts[0]
    last_name = " ".join(parts[1:])
    return first_name, last_name

def get_hunter_data(first_name, last_name, domain):
    if not first_name or not last_name:
        return "Non trouvé", "Non trouvé"
        
    print(f"   🔍 [Hunter.io] Recherche pour: {first_name} {last_name}...")
    url = f"https://api.hunter.io/v2/email-finder?domain={domain}&first_name={first_name}&last_name={last_name}&api_key={HUNTER_API_KEY}"
    
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json().get("data", {})
            return data.get("email") or "Non trouvé", data.get("position") or "Non trouvé"
    except Exception:
        pass
    return "Non trouvé", "Non trouvé"

def get_snovio_token():
    url = "https://api.snov.io/v1/oauth/access_token"
    data = {"grant_type": "client_credentials", "client_id": SNOVIO_CLIENT_ID, "client_secret": SNOVIO_CLIENT_SECRET}
    try:
        response = requests.post(url, data=data)
        if response.status_code == 200:
            return response.json().get("access_token")
    except Exception:
        pass
    return None

def get_snovio_data(first_name, last_name, domain, token):
    if not token or not first_name or not last_name:
        return "Non trouvé", "Non trouvé"
        
    print(f"   🔄 [Snov.io] Fallback activé pour: {first_name} {last_name}...")
    url = "https://api.snov.io/v1/get-emails-from-names"
    params = {"access_token": token}
    payload = {"firstName": first_name, "lastName": last_name, "domain": domain}
    
    try:
        response = requests.post(url, params=params, json=payload)
        if response.status_code == 200:
            emails = response.json().get("data", {}).get("emails", [])
            if emails:
                return emails[0].get("email", "Non trouvé"), "Non trouvé"
    except Exception:
        pass
    return "Non trouvé", "Non trouvé"

def get_tomba_data(first_name, last_name, domain):
    if not first_name or not last_name:
        return "Non trouvé", "Non trouvé", "Non trouvé"
        
    print(f"   📥 [Tomba.io] Fallback activé pour: {first_name} {last_name}...")
    url = "https://api.tomba.io/v1/email-finder"
    headers = {"X-Tomba-Key": TOMBA_API_KEY, "X-Tomba-Secret": TOMBA_API_SECRET}
    params = {"first_name": first_name, "last_name": last_name, "domain": domain}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json().get("data", {})
            return (data.get("email") or "Non trouvé", 
                    data.get("position") or "Non trouvé", 
                    data.get("phone_number") or "Non trouvé")
    except Exception:
        pass
    return "Non trouvé", "Non trouvé", "Non trouvé"

def get_aeroleads_data(first_name, last_name, company, linkedin_url):
    """Fallback ultime AeroLeads : Teste LinkedIn d'abord, puis Nom/Entreprise et retourne les données brutes"""
    email, position, phone = None, None, None
    raw_data = None
    print(f"   🚀 [AeroLeads] Enrichissement profond activé pour: {first_name} {last_name}...")

    # 1. Tentative via LinkedIn URL
    if linkedin_url:
        print(f"      -> Tentative via API LinkedIn...")
        try:
            resp = requests.get("https://aeroleads.com/api/get_linkedin_details", params={'api_key': AEROLEADS_API_KEY, 'linkedin_url': linkedin_url}, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                raw_data = data # Capture des données brutes
                
                email = data.get('email')
                if not email and data.get('emails'): email = data['emails'][0].get('address')
                phone = data.get('phone_number') or data.get('phone')
                if not phone and data.get('phone_numbers'): phone = data['phone_numbers'][0]
                position = data.get('title') or data.get('designation')
        except Exception:
            pass

    # 2. Tentative via Nom/Entreprise si toujours incomplet
    if not email or not phone or not raw_data:
        print(f"      -> Données manquantes. Tentative via API Nom/Entreprise...")
        try:
            resp = requests.get("https://aeroleads.com/api/get_email_details", params={'api_key': AEROLEADS_API_KEY, 'first_name': first_name, 'last_name': last_name, 'company': company}, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                raw_data = data # Capture des données brutes
                
                e_fall = data.get('email')
                if not e_fall and data.get('emails'): e_fall = data['emails'][0].get('address')
                if e_fall and not email: email = e_fall
                
                p_fall = data.get('phone_number') or data.get('phone')
                if not p_fall and data.get('phone_numbers'): p_fall = data['phone_numbers'][0]
                if p_fall and not phone: phone = p_fall
                
                pos_fall = data.get('title') or data.get('designation')
                if pos_fall and not position: position = pos_fall
        except Exception:
            pass

    return email or "Non trouvé", position or "Non trouvé", phone or "Non trouvé", raw_data


# ============================================================================
# DOMAIN SEARCH FUNCTIONS — Find ALL people at a domain (no name required)
# ============================================================================

def hunter_domain_search(domain):
    """Hunter.io Domain Search — returns all emails+names+positions for a domain."""
    print(f"   🔍 [Hunter.io] Domain search for {domain}...")
    url = f"https://api.hunter.io/v2/domain-search?domain={domain}&api_key={HUNTER_API_KEY}&limit=10&type=personal"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json().get("data", {})
            emails = data.get("emails", [])
            results = []
            for e in emails:
                first = e.get("first_name", "")
                last = e.get("last_name", "")
                if first and last:
                    results.append({
                        "full_name": f"{first} {last}",
                        "email": e.get("value", ""),
                        "title": e.get("position", "") or "",
                        "linkedin_url": e.get("linkedin", "") or "",
                        "source": "Hunter.io Domain Search",
                    })
            print(f"   ✅ [Hunter.io] Found {len(results)} person(s)")
            return results
        else:
            print(f"   ⚠️ [Hunter.io] HTTP {response.status_code}")
    except Exception as exc:
        print(f"   ⚠️ [Hunter.io Domain Search] Error: {exc}")
    return []


def snovio_domain_search(domain, role="Sales"):
    """Snov.io Domain Search — async 2-step: start prospects search → poll result."""
    print(f"   🔄 [Snov.io] Domain search for {domain} (role={role})...")
    token = get_snovio_token()
    if not token:
        print(f"   ⚠️ [Snov.io] Could not get auth token")
        return []
    headers = {"Authorization": f"Bearer {token}"}
    # Step 1: Start search
    try:
        resp = requests.post(
            "https://api.snov.io/v2/domain-search/prospects/start",
            params={"domain": domain, "positions[]": [role]},
            headers=headers, timeout=15,
        )
        if resp.status_code != 200:
            print(f"   ⚠️ [Snov.io] Start HTTP {resp.status_code}")
            return []
        start_data = resp.json()
        result_url = start_data.get("links", {}).get("result", "")
        task_hash = start_data.get("meta", {}).get("task_hash", "")
        if not task_hash and result_url:
            task_hash = result_url.split("/")[-1]
        if not task_hash:
            print(f"   ⚠️ [Snov.io] No task_hash returned")
            return []
    except Exception as exc:
        print(f"   ⚠️ [Snov.io Domain Search] Start error: {exc}")
        return []

    # Step 2: Poll result (wait for async processing)
    time.sleep(3)
    try:
        resp = requests.get(
            f"https://api.snov.io/v2/domain-search/prospects/result/{task_hash}",
            headers=headers, timeout=15,
        )
        if resp.status_code != 200:
            print(f"   ⚠️ [Snov.io] Result HTTP {resp.status_code}")
            return []
        result = resp.json()
        prospects = result.get("data", [])
        results = []
        for p in prospects:
            first = p.get("first_name", "")
            last = p.get("last_name", "")
            if first and last:
                results.append({
                    "full_name": f"{first} {last}",
                    "email": "",  # email requires separate search in Snov.io
                    "title": p.get("position", "") or "",
                    "linkedin_url": p.get("source_page", "") or "",
                    "source": "Snov.io Domain Search",
                })
        print(f"   ✅ [Snov.io] Found {len(results)} prospect(s)")
        return results
    except Exception as exc:
        print(f"   ⚠️ [Snov.io Domain Search] Result error: {exc}")
    return []


def tomba_domain_search(domain):
    """Tomba.io Domain Search — returns all emails found for a domain."""
    print(f"   📥 [Tomba.io] Domain search for {domain}...")
    url = "https://api.tomba.io/v1/domain-search"
    headers = {"X-Tomba-Key": TOMBA_API_KEY, "X-Tomba-Secret": TOMBA_API_SECRET}
    try:
        response = requests.get(url, headers=headers, params={"domain": domain}, timeout=15)
        if response.status_code == 200:
            data = response.json().get("data", {})
            emails = data.get("emails", [])
            results = []
            for e in emails:
                first = e.get("first_name", "")
                last = e.get("last_name", "")
                if first and last:
                    results.append({
                        "full_name": f"{first} {last}",
                        "email": e.get("email", ""),
                        "title": e.get("position", "") or "",
                        "linkedin_url": e.get("linkedin", "") or "",
                        "source": "Tomba.io Domain Search",
                    })
            print(f"   ✅ [Tomba.io] Found {len(results)} person(s)")
            return results
        else:
            print(f"   ⚠️ [Tomba.io] HTTP {response.status_code}")
    except Exception as exc:
        print(f"   ⚠️ [Tomba Domain Search] Error: {exc}")
    return []


# ============================================================================
# MAIN FUNCTION — Two-tier persona discovery + enrichment cascade
# ============================================================================

def search_and_enrich(domain, location, role="Sales"):
    """
    Two-tier persona discovery + cascade enrichment.

    Tier 1: Domain Search APIs (Hunter, Snov.io, Tomba) — find people at domain
             without needing any prior knowledge of who works there.
    Tier 2: Google/LinkedIn scraping via Serper — fallback if Tier 1 finds nothing.
    Then:   Email enrichment cascade on all discovered people.
    """
    company_name = domain.split('.')[0].capitalize()
    snovio_token = None
    final_profiles = []

    # ========== TIER 1: DOMAIN SEARCH APIs ==========
    print(f"📡 Tier 1: Domain Search APIs for {domain}...")

    all_discovered = []
    seen_names = set()

    # Hunter.io Domain Search
    hunter_results = hunter_domain_search(domain)
    for p in hunter_results:
        name_key = p["full_name"].lower().strip()
        if name_key not in seen_names:
            seen_names.add(name_key)
            all_discovered.append(p)

    # Snov.io Domain Search (with role filter)
    snovio_results = snovio_domain_search(domain, role=role)
    for p in snovio_results:
        name_key = p["full_name"].lower().strip()
        if name_key not in seen_names:
            seen_names.add(name_key)
            all_discovered.append(p)

    # Tomba.io Domain Search
    tomba_results = tomba_domain_search(domain)
    for p in tomba_results:
        name_key = p["full_name"].lower().strip()
        if name_key not in seen_names:
            seen_names.add(name_key)
            all_discovered.append(p)

    print(f"   ✅ Tier 1 total: {len(all_discovered)} unique person(s)")

    # ========== TIER 2: SERPER/LINKEDIN FALLBACK ==========
    if not all_discovered:
        print(f"📡 Tier 2: Serper/LinkedIn fallback for {domain}...")
        dynamic_query = f'site:linkedin.com/in/ "{company_name}" "{location}" "{role}"'
        url = "https://google.serper.dev/search"
        payload = json.dumps({"q": dynamic_query, "gl": "tn", "hl": "fr", "num": 3})
        headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}

        try:
            response = requests.post(url, headers=headers, data=payload)
            if response.status_code == 200:
                results = response.json()
                organic_results = results.get("organic", [])
                for item in organic_results[:3]:
                    title_raw = item.get("title", "")
                    link = item.get("link", "")
                    raw_full_name = title_raw.split(" - ")[0]
                    clean_full_name = clean_linkedin_name(raw_full_name)
                    if clean_full_name and clean_full_name.lower().strip() not in seen_names:
                        seen_names.add(clean_full_name.lower().strip())
                        all_discovered.append({
                            "full_name": clean_full_name,
                            "email": "",
                            "title": "",
                            "linkedin_url": link,
                            "source": "Serper LinkedIn",
                        })
                print(f"   ✅ Tier 2 found {len(all_discovered)} person(s) via LinkedIn")
            else:
                print(f"   ⚠️ Serper HTTP {response.status_code}")
        except Exception as e:
            print(f"   ⚠️ Serper error: {e}")

    if not all_discovered:
        print(f"❌ No personas found for {domain} across all tiers.")
        return []

    # ========== TIER 3: ENRICHMENT CASCADE ==========
    print(f"📡 Enrichment cascade for {len(all_discovered)} discovered person(s)...")

    for person in all_discovered[:5]:  # Cap at 5 to avoid rate limits
        full_name = person.get("full_name", "")
        first_name, last_name = split_name(full_name)
        linkedin_url = person.get("linkedin_url", "")

        # Start with what we already know from domain search
        final_email = person.get("email", "") or "Non trouvé"
        final_position = person.get("title", "") or "Non trouvé"
        final_phone = "Non trouvé"
        final_aeroleads_raw_data = None
        source_used = person.get("source", "Domain Search")

        # Only run enrichment if we're missing data
        if final_email == "Non trouvé" or not final_email:
            final_email = "Non trouvé"

            # --- Hunter email finder ---
            h_email, h_position = get_hunter_data(first_name, last_name, domain)
            if h_email != "Non trouvé" or h_position != "Non trouvé":
                if h_email != "Non trouvé": final_email = h_email
                if h_position != "Non trouvé" and final_position in ("Non trouvé", ""): final_position = h_position
                source_used += " + Hunter.io"

            # --- Snov.io email finder ---
            if final_email == "Non trouvé":
                if not snovio_token: snovio_token = get_snovio_token()
                snov_email, snov_position = get_snovio_data(first_name, last_name, domain, snovio_token)
                if snov_email != "Non trouvé": final_email = snov_email; source_used += " + Snov.io"
                if snov_position != "Non trouvé" and final_position in ("Non trouvé", ""): final_position = snov_position

            # --- Tomba email finder ---
            if final_email == "Non trouvé":
                tomba_email, tomba_position, tomba_phone = get_tomba_data(first_name, last_name, domain)
                if tomba_email != "Non trouvé": final_email = tomba_email; source_used += " + Tomba.io"
                if tomba_position != "Non trouvé" and final_position in ("Non trouvé", ""): final_position = tomba_position
                if tomba_phone != "Non trouvé": final_phone = tomba_phone

        # --- AeroLeads deep enrichment ---
        aero_email, aero_position, aero_phone, aero_raw = get_aeroleads_data(first_name, last_name, company_name, linkedin_url)
        final_aeroleads_raw_data = aero_raw
        if final_email == "Non trouvé" and aero_email != "Non trouvé": final_email = aero_email; source_used += " + AeroLeads"
        if final_position in ("Non trouvé", "") and aero_position != "Non trouvé": final_position = aero_position
        if final_phone == "Non trouvé" and aero_phone != "Non trouvé": final_phone = aero_phone

        # --- Build flattened profile ---
        profile_data = {}
        if isinstance(final_aeroleads_raw_data, dict):
            if "raw_data" in final_aeroleads_raw_data and isinstance(final_aeroleads_raw_data["raw_data"], dict):
                profile_data.update(final_aeroleads_raw_data["raw_data"])
            elif "data" in final_aeroleads_raw_data and isinstance(final_aeroleads_raw_data["data"], dict):
                profile_data.update(final_aeroleads_raw_data["data"])
            else:
                profile_data.update(final_aeroleads_raw_data)

        profile_data["clean_name_used"] = full_name
        profile_data["linkedin_url"] = linkedin_url
        profile_data["company"] = company_name
        profile_data["email"] = final_email
        profile_data["title"] = final_position
        profile_data["phone"] = final_phone
        profile_data["source"] = source_used

        final_profiles.append(profile_data)
        time.sleep(1)  # Rate limit safety

    # --- Save results ---
    output_dir = "personas_discovered"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    safe_domain = domain.replace('.', '_')
    output_file = os.path.join(output_dir, f"{safe_domain}_personas.json")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_profiles, f, indent=4, ensure_ascii=False)

    print(f"✅ Terminé ! {len(final_profiles)} profils testés et sauvegardés.")
    print(f"💾 Regarde le résultat dans : {output_file}")

    return final_profiles

if __name__ == "__main__":
    TARGET_DOMAIN = "Tesla.com"
    TARGET_LOCATION = "USA"
    TARGET_ROLE = "IT"

    profiles = search_and_enrich(TARGET_DOMAIN, TARGET_LOCATION, TARGET_ROLE)
    print(f"Profils retournés : {len(profiles)}")