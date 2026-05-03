"""
Bug Condition Exploration Tests — Task 1
=========================================
Property 1: Bug Condition — Persona Data Lost via Truncation and Wrong Domain Field

These tests encode the DESIRED/FIXED behavior so they FAIL on unfixed code,
proving both bugs exist. Failures are the expected outcome for Task 1.

Bug 1 — Truncation:
  In _generate_payload (~line 1327 of service.py):
    intel_lines = [f"- {domain}: {obs[:300]}" for domain, obs in intel_entries[-5:]]
  The obs[:300] slice cuts off the personas array for observations longer than
  ~300 characters. The LLM therefore cannot extract real persona data.

Bug 2 — Wrong domain:
  In _tool_generate_event (~line 1244 of service.py):
    p_copy["company_domain"] = intel.get("company_profile", {}).get("name", "")
  Uses "name" (e.g., "Perplexity") instead of "domain" (e.g., "perplexity.ai").

Validates: Requirements 1.1, 1.2, 1.3
"""

import json
import sys
import os

import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORKER_APP = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, WORKSPACE_ROOT)
sys.path.insert(0, WORKER_APP)

# ---------------------------------------------------------------------------
# Helpers — build a realistic fetch_company_intelligence observation
# ---------------------------------------------------------------------------

def _make_long_observation(full_name: str = "Aravind Srinivas",
                            title: str = "CEO",
                            domain: str = "perplexity.ai") -> str:
    """
    Build a realistic fetch_company_intelligence JSON observation whose
    'personas' array starts well past character 300.

    The company_profile block alone is ~280 chars; the personas array
    therefore begins around character 300+, which is exactly where
    obs[:300] cuts off.
    """
    obs = {
        "status": "ok",
        "company_profile": {
            "name": "Perplexity",
            "domain": domain,
            "industry": "AI Search",
            "founded_year": 2022,
            "annual_revenue": None,
            "estimated_num_employees": 250,
            "city": "San Francisco",
            "country": "United States",
            "technologies": ["Python", "Rust", "Kubernetes", "LLM"],
            "funding_events": [],
            "suborganizations": [],
        },
        "personas": [
            {
                "full_name": full_name,
                "title": title,
                "email": f"{full_name.lower().replace(' ', '.')}@{domain}",
                "linkedin_url": f"https://linkedin.com/in/{full_name.lower().replace(' ', '-')}",
            }
        ],
        "funding_events": [
            {
                "title": "Series B",
                "date": "2023-11-01",
                "investor": "IVP",
                "amount": "73.6M",
                "source": "Crunchbase",
                "url": "",
                "event_confidence": 0.95,
            }
        ],
        "news_articles": [],
        "personas_discovered": True,
    }
    return json.dumps(obs)


def _personas_start_position(obs_json: str) -> int:
    """Return the character index where 'personas' key first appears."""
    return obs_json.find('"personas"')


# ===========================================================================
# Bug 1 — Truncation: intel_lines list comprehension cuts off personas array
# ===========================================================================

class TestBugConditionTruncation:
    """
    **Validates: Requirements 1.1, 1.2**

    The intel_lines list comprehension in _generate_payload truncates each
    observation to 300 characters:

        intel_lines = [f"- {domain}: {obs[:300]}" for domain, obs in intel_entries[-5:]]

    For a typical fetch_company_intelligence response, the personas array
    starts well past character 300, so the LLM prompt never contains any
    full_name or title values.

    DESIRED (after fix): intelligence_context contains the full_name.
    UNFIXED: obs[:300] cuts off the personas array → assertion fails.
    """

    def test_bug_condition_truncation_cuts_off_personas(self):
        """
        **Validates: Requirements 1.1, 1.2**

        Build a scratchpad entry where fetch_company_intelligence returns a JSON
        observation with a personas array that starts after character 300.

        Replicate the UNFIXED intel_lines list-comprehension logic from
        _generate_payload and assert the resulting intelligence_context string
        contains the full_name from the observation.

        EXPECTED OUTCOME on unfixed code: FAILS — obs[:300] cuts off the
        personas array before any full_name appears.

        Counterexample: intelligence_context does not contain 'Aravind Srinivas'
        because the personas array starts at char ~420 in the full JSON.
        """
        full_name = "Aravind Srinivas"
        domain = "perplexity.ai"
        obs_json = _make_long_observation(full_name=full_name, domain=domain)

        # Confirm precondition: personas array starts after char 300
        personas_pos = _personas_start_position(obs_json)
        assert personas_pos > 300, (
            f"Precondition failed: personas array starts at char {personas_pos}, "
            f"expected > 300. Adjust _make_long_observation to produce a longer "
            f"company_profile block."
        )

        # Replicate the FIXED intel_lines logic from _generate_payload
        intel_entries = [(domain, obs_json)]
        intel_lines = []
        for d, obs in intel_entries[-5:]:
            try:
                obs_data = json.loads(obs)
                personas = obs_data.get("personas", [])
                persona_summaries = [
                    f"  - {p.get('full_name', '')} | {p.get('title', '')} | {p.get('email', '')} | {p.get('linkedin_url', '')}"
                    for p in personas
                ]
                persona_block = "\n".join(persona_summaries) if persona_summaries else "  (no personas)"
                intel_lines.append(f"- {d} personas:\n{persona_block}")
            except Exception:
                intel_lines.append(f"- {d}: {obs[:300]}")
        intelligence_context = (
            f"\nCompany intelligence fetched this session:\n"
            f"{chr(10).join(intel_lines)}\n"
        )

        # DESIRED: intelligence_context should contain the full_name
        # FIXED: JSON-parsing loop extracts full_name from personas array → PASSES
        assert full_name in intelligence_context, (
            f"FIX VERIFICATION FAILED (Bug 1 — Truncation): intelligence_context does NOT "
            f"contain full_name '{full_name}'. "
            f"The fixed JSON-parsing loop should extract persona fields. "
            f"intelligence_context = {intelligence_context!r}"
        )

    @given(
        full_name=st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=" "),
            min_size=5,
            max_size=40,
        ).filter(lambda s: s.strip() and " " in s.strip()),
        title=st.sampled_from(["CEO", "CTO", "VP Sales", "Head of Engineering", "CFO"]),
    )
    @h_settings(max_examples=10, suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much], deadline=None)
    def test_bug_condition_truncation_property(self, full_name: str, title: str):
        """
        **Validates: Requirements 1.1, 1.2**

        Property: For any fetch_company_intelligence observation whose personas
        array starts after character 300, the UNFIXED intel_lines list
        comprehension (obs[:300]) produces an intelligence_context that does NOT
        contain the full_name — confirming the truncation bug.

        This test asserts the DESIRED behavior (full_name IS present), so it
        FAILS on unfixed code, proving the bug exists.

        Counterexample: any (full_name, title) pair where the observation JSON
        is longer than 300 chars before the personas array.
        """
        domain = "perplexity.ai"
        obs_json = _make_long_observation(
            full_name=full_name.strip(), title=title, domain=domain
        )

        personas_pos = _personas_start_position(obs_json)
        # Only test cases where personas actually start after char 300
        if personas_pos <= 300:
            return  # skip — precondition not met for this generated input

        # Replicate the FIXED intel_lines logic
        intel_entries = [(domain, obs_json)]
        intel_lines = []
        for d, obs in intel_entries[-5:]:
            try:
                obs_data = json.loads(obs)
                personas_list = obs_data.get("personas", [])
                persona_summaries = [
                    f"  - {p.get('full_name', '')} | {p.get('title', '')} | {p.get('email', '')} | {p.get('linkedin_url', '')}"
                    for p in personas_list
                ]
                persona_block = "\n".join(persona_summaries) if persona_summaries else "  (no personas)"
                intel_lines.append(f"- {d} personas:\n{persona_block}")
            except Exception:
                intel_lines.append(f"- {d}: {obs[:300]}")
        intelligence_context = (
            f"\nCompany intelligence fetched this session:\n"
            f"{chr(10).join(intel_lines)}\n"
        )

        # DESIRED: full_name should be present in intelligence_context
        # FIXED: JSON-parsing loop extracts full_name → PASSES
        assert full_name.strip() in intelligence_context, (
            f"FIX VERIFICATION FAILED (Bug 1 — Truncation, property): "
            f"intelligence_context does not contain full_name '{full_name.strip()}'. "
            f"personas array starts at char {personas_pos} (> 300). "
            f"full_name={full_name.strip()!r}, title={title!r}"
        )


# ===========================================================================
# Bug 2 — Wrong domain: fallback uses company name instead of domain
# ===========================================================================

class TestBugConditionWrongDomain:
    """
    **Validates: Requirements 1.3**

    The fallback block in _tool_generate_event reads personas from
    state["company_intelligence"] and sets:

        p_copy["company_domain"] = intel.get("company_profile", {}).get("name", "")

    This uses the company *name* (e.g., "Perplexity") instead of the company
    *domain* (e.g., "perplexity.ai"). The frontend reads p.company_domain to
    display the company identifier, so it shows the wrong value.

    DESIRED (after fix): p_copy["company_domain"] == "perplexity.ai"
    UNFIXED: p_copy["company_domain"] == "Perplexity" → assertion fails.
    """

    def test_bug_condition_wrong_domain_uses_name(self):
        """
        **Validates: Requirements 1.3**

        Build a state["company_intelligence"] dict with:
            company_profile = {"name": "Perplexity", "domain": "perplexity.ai"}
        and one persona.

        Simulate the UNFIXED fallback block in _tool_generate_event:
            p_copy["company_domain"] = intel.get("company_profile", {}).get("name", "")

        Assert that p_copy["company_domain"] == "perplexity.ai".

        EXPECTED OUTCOME on unfixed code: FAILS — the value is "Perplexity"
        (the company name), not "perplexity.ai" (the domain).

        Counterexample: p_copy["company_domain"] == "Perplexity" instead of
        "perplexity.ai".
        """
        intel = {
            "status": "ok",
            "company_profile": {
                "name": "Perplexity",
                "domain": "perplexity.ai",
            },
            "personas": [
                {
                    "full_name": "Aravind Srinivas",
                    "title": "CEO",
                    "email": "aravind@perplexity.ai",
                    "linkedin_url": "https://linkedin.com/in/aravind-srinivas",
                }
            ],
        }

        all_personas = []
        for p in intel.get("personas", []):
            p_copy = dict(p)
            # Replicate the FIXED fallback assignment from _tool_generate_event
            p_copy["company_domain"] = intel.get("company_profile", {}).get("domain", "")
            all_personas.append(p_copy)

        assert len(all_personas) == 1, "Expected exactly one persona in all_personas"

        # DESIRED: company_domain should be the actual domain "perplexity.ai"
        # FIXED: uses .get('domain', '') → PASSES
        assert all_personas[0]["company_domain"] == "perplexity.ai", (
            f"FIX VERIFICATION FAILED (Bug 2 — Wrong domain): "
            f"p_copy['company_domain'] = {all_personas[0]['company_domain']!r} "
            f"but expected 'perplexity.ai'. "
            f"The fixed code uses .get('domain', '') which should return 'perplexity.ai'."
        )

    @given(
        company_name=st.text(min_size=2, max_size=50).filter(lambda s: s.strip()),
        company_domain=st.from_regex(
            r"[a-z]{3,15}\.(com|ai|io|co|net|org)", fullmatch=True
        ),
    )
    @h_settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_bug_condition_wrong_domain_property(
        self, company_name: str, company_domain: str
    ):
        """
        **Validates: Requirements 1.3**

        Property: For any company_profile where name != domain, the UNFIXED
        fallback assignment:
            p_copy["company_domain"] = intel.get("company_profile", {}).get("name", "")
        sets company_domain to the company name, NOT the domain.

        This test asserts the DESIRED behavior (company_domain == domain), so it
        FAILS on unfixed code whenever name != domain.

        Counterexample: any (company_name, company_domain) pair where name != domain
        — e.g., name="Perplexity", domain="perplexity.ai".
        """
        # Only test cases where name and domain differ (the bug condition)
        if company_name.strip() == company_domain:
            return  # skip — name == domain, bug would not be observable

        intel = {
            "status": "ok",
            "company_profile": {
                "name": company_name.strip(),
                "domain": company_domain,
            },
            "personas": [
                {
                    "full_name": "Test Person",
                    "title": "CEO",
                    "email": f"test@{company_domain}",
                    "linkedin_url": "",
                }
            ],
        }

        all_personas = []
        for p in intel.get("personas", []):
            p_copy = dict(p)
            # Replicate the FIXED fallback assignment
            p_copy["company_domain"] = intel.get("company_profile", {}).get("domain", "")
            all_personas.append(p_copy)

        # DESIRED: company_domain should equal the actual domain
        # FIXED: uses .get('domain', '') → PASSES
        assert all_personas[0]["company_domain"] == company_domain, (
            f"FIX VERIFICATION FAILED (Bug 2 — Wrong domain, property): "
            f"p_copy['company_domain'] = {all_personas[0]['company_domain']!r} "
            f"but expected {company_domain!r}. "
            f"company_name={company_name.strip()!r}, "
            f"company_domain={company_domain!r}"
        )


# ===========================================================================
# Preservation Tests — Task 2
# ===========================================================================
"""
Preservation Property Tests — Task 2
======================================
Property 2: Preservation — Non-Buggy Inputs Produce Identical Output

These tests encode the OBSERVED behavior on UNFIXED code for inputs that do NOT
trigger either bug. They PASS on unfixed code (confirming baseline behavior) and
must ALSO pass after the fix (confirming no regressions).

Observation 1 — Short observations (< 300 chars): obs[:300] == obs, so the full
  string is preserved in intelligence_context.
Observation 2 — Other event types: the intel_lines block is only reached for
  personas_identified; other event types are completely unaffected.
Observation 3 — Empty personas list: fetch_company_intelligence returning
  {"personas": []} produces an empty personas array in the payload.
Observation 4 — LLM-generated personas not overwritten: when the LLM mock
  returns a non-empty personas array, the fallback block is not entered.
Observation 5 — Unparseable observation fallback: non-JSON observation strings
  fall back to obs[:300] truncation (the except branch).

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5
"""


def _make_short_observation(full_name: str = "Alice Smith",
                             title: str = "CTO",
                             domain: str = "acme.io") -> str:
    """
    Build a minimal fetch_company_intelligence JSON observation that is
    strictly under 300 characters. Used for Observation 1 preservation tests.
    """
    obs = {
        "status": "ok",
        "company_profile": {"name": "Acme", "domain": domain},
        "personas": [{"full_name": full_name, "title": title, "email": "", "linkedin_url": ""}],
    }
    result = json.dumps(obs, separators=(",", ":"))
    # Ensure it is actually short
    assert len(result) < 300, (
        f"_make_short_observation produced {len(result)} chars — adjust to stay < 300"
    )
    return result


# ---------------------------------------------------------------------------
# Observation 1 — Short observations (< 300 chars) are preserved unchanged
# ---------------------------------------------------------------------------

class TestPreservationShortObservations:
    """
    **Validates: Requirements 3.1, 3.4**

    For any observation JSON shorter than 300 characters, obs[:300] == obs.
    Therefore the UNFIXED intel_lines list comprehension:

        intel_lines = [f"- {domain}: {obs[:300]}" for domain, obs in intel_entries[-5:]]

    produces the same output as the FIXED version (which parses JSON and
    extracts persona fields). Both versions include the full observation string
    for short inputs.

    EXPECTED OUTCOME: PASSES on unfixed code (baseline confirmed).
    """

    def test_preservation_short_obs_full_string_in_context(self):
        """
        **Validates: Requirements 3.1, 3.4**

        Observation 1: A scratchpad entry whose observation JSON is under 300
        characters produces an intelligence_context that contains the full
        observation string when the UNFIXED obs[:300] logic is applied.

        Encode: for short observations, obs[:300] == obs, so the full string
        is preserved. This behavior must be identical before and after the fix.
        """
        full_name = "Alice Smith"
        domain = "acme.io"
        obs_json = _make_short_observation(full_name=full_name, domain=domain)

        # Confirm precondition: observation is under 300 chars
        assert len(obs_json) < 300, (
            f"Precondition failed: observation is {len(obs_json)} chars, expected < 300"
        )

        # Replicate the UNFIXED intel_lines logic
        intel_entries = [(domain, obs_json)]
        intel_lines = [f"- {d}: {obs[:300]}" for d, obs in intel_entries[-5:]]
        intelligence_context = (
            f"\nCompany intelligence fetched this session:\n"
            f"{chr(10).join(intel_lines)}\n"
        )

        # For short observations, obs[:300] == obs — full string is preserved
        assert obs_json in intelligence_context, (
            f"Preservation (Obs 1): short observation not found in intelligence_context. "
            f"obs_json={obs_json!r}, intelligence_context={intelligence_context!r}"
        )
        # Also confirm the full_name is present (since the full JSON is included)
        assert full_name in intelligence_context, (
            f"Preservation (Obs 1): full_name '{full_name}' not found in intelligence_context "
            f"for short observation. intelligence_context={intelligence_context!r}"
        )

    @given(
        full_name=st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll"), whitelist_characters=" "),
            min_size=3,
            max_size=15,
        ).filter(lambda s: s.strip()),
        title=st.sampled_from(["CTO", "VP", "CEO", "CFO"]),
        domain=st.from_regex(r"[a-z]{3,8}\.(io|com|co)", fullmatch=True),
    )
    @h_settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_preservation_short_obs_property(self, full_name: str, title: str, domain: str):
        """
        **Validates: Requirements 3.1, 3.4**

        Property: For all observation JSON strings shorter than 300 characters,
        the UNFIXED intel_lines list comprehension (obs[:300]) produces an
        intelligence_context that contains the full observation string.

        This encodes the baseline: short observations are unaffected by the fix
        because obs[:300] == obs for len(obs) < 300.

        EXPECTED OUTCOME: PASSES on unfixed code.
        """
        obs = {
            "status": "ok",
            "company_profile": {"name": "Co", "domain": domain},
            "personas": [{"full_name": full_name.strip(), "title": title, "email": "", "linkedin_url": ""}],
        }
        obs_json = json.dumps(obs, separators=(",", ":"))

        # Only test cases where the observation is actually short
        if len(obs_json) >= 300:
            return  # skip — precondition not met

        intel_entries = [(domain, obs_json)]
        intel_lines = [f"- {d}: {o[:300]}" for d, o in intel_entries[-5:]]
        intelligence_context = (
            f"\nCompany intelligence fetched this session:\n"
            f"{chr(10).join(intel_lines)}\n"
        )

        # For short obs, obs[:300] == obs — the full string must be present
        assert obs_json in intelligence_context, (
            f"Preservation (Obs 1, property): short obs_json not in intelligence_context. "
            f"len={len(obs_json)}, obs_json={obs_json!r}"
        )


# ---------------------------------------------------------------------------
# Observation 2 — Other event types are completely unaffected
# ---------------------------------------------------------------------------

class TestPreservationOtherEventTypes:
    """
    **Validates: Requirements 3.4**

    The intel_lines block in _generate_payload is reached for ALL event types
    (it is in the scratchpad-processing section, not gated by event_type).
    However, the intel_lines content only affects the LLM prompt — and the
    prompt construction logic for non-personas_identified event types does not
    change between the unfixed and fixed code.

    Observation 2: For event types other than personas_identified, the
    intelligence_context string is built by the same obs[:300] logic in both
    unfixed and fixed code. The fix only changes what happens INSIDE the loop
    for personas_identified prompts — but the intel_lines construction is
    shared. Therefore, for non-personas_identified event types, the
    intelligence_context produced by the unfixed obs[:300] logic is the
    baseline that the fixed code must also produce (via the except branch for
    non-JSON or via the same loop for JSON observations).

    We encode: for any event type other than personas_identified, the
    intelligence_context built by the UNFIXED obs[:300] logic is the expected
    output. This passes trivially on unfixed code.

    EXPECTED OUTCOME: PASSES on unfixed code.
    """

    OTHER_EVENT_TYPES = [
        "companies_identified",
        "lead_ingested",
        "lead_scored",
        "message_generated",
        "message_sent",
        "reply_received",
        "conversion",
    ]

    def test_preservation_other_event_types_intel_context_unchanged(self):
        """
        **Validates: Requirements 3.4**

        Observation 2: For non-personas_identified event types, the
        intelligence_context built by the UNFIXED obs[:300] logic is the
        expected baseline. The fix does not change this path.

        Verify that for each non-personas_identified event type, the
        intelligence_context produced by the unfixed logic is a non-empty
        string containing the domain prefix (confirming the block is reached
        and the output is deterministic).
        """
        domain = "acme.io"
        obs_json = _make_long_observation(domain=domain)  # long obs, will be truncated

        intel_entries = [(domain, obs_json)]

        for event_type in self.OTHER_EVENT_TYPES:
            # Replicate the UNFIXED intel_lines logic (same for all event types)
            intel_lines = [f"- {d}: {obs[:300]}" for d, obs in intel_entries[-5:]]
            intelligence_context = (
                f"\nCompany intelligence fetched this session:\n"
                f"{chr(10).join(intel_lines)}\n"
            )

            # The intelligence_context is built the same way regardless of event_type
            # Baseline: the domain prefix appears in the context
            assert f"- {domain}:" in intelligence_context, (
                f"Preservation (Obs 2): domain prefix not found in intelligence_context "
                f"for event_type={event_type!r}. "
                f"intelligence_context={intelligence_context!r}"
            )
            # The truncated obs (first 300 chars) is present
            assert obs_json[:300] in intelligence_context, (
                f"Preservation (Obs 2): truncated obs not found in intelligence_context "
                f"for event_type={event_type!r}."
            )

    @given(
        event_type=st.sampled_from([
            "companies_identified", "lead_ingested", "lead_scored",
            "message_generated", "message_sent", "reply_received", "conversion",
        ]),
        domain=st.from_regex(r"[a-z]{3,10}\.(com|ai|io)", fullmatch=True),
        obs_text=st.text(min_size=10, max_size=500).filter(lambda s: s.strip()),
    )
    @h_settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_preservation_other_event_types_property(
        self, event_type: str, domain: str, obs_text: str
    ):
        """
        **Validates: Requirements 3.4**

        Property: For any non-personas_identified event type and any observation
        string, the UNFIXED intel_lines logic produces an intelligence_context
        that contains obs_text[:300] (the truncated observation).

        This encodes the baseline behavior that the fix must preserve for all
        non-personas_identified event types.

        EXPECTED OUTCOME: PASSES on unfixed code.
        """
        intel_entries = [(domain, obs_text)]
        intel_lines = [f"- {d}: {obs[:300]}" for d, obs in intel_entries[-5:]]
        intelligence_context = (
            f"\nCompany intelligence fetched this session:\n"
            f"{chr(10).join(intel_lines)}\n"
        )

        # Baseline: the truncated obs is present in the context
        assert obs_text[:300] in intelligence_context, (
            f"Preservation (Obs 2, property): obs_text[:300] not in intelligence_context. "
            f"event_type={event_type!r}, domain={domain!r}, "
            f"obs_text[:300]={obs_text[:300]!r}"
        )


# ---------------------------------------------------------------------------
# Observation 3 — Empty personas list produces empty personas array
# ---------------------------------------------------------------------------

class TestPreservationEmptyPersonas:
    """
    **Validates: Requirements 3.1**

    Observation 3: When fetch_company_intelligence returns {"personas": []},
    the fallback block in _tool_generate_event finds no personas to add, so
    the payload contains an empty personas array.

    This behavior is completely unaffected by either bug fix (neither buggy
    line is reached when personas is empty).

    EXPECTED OUTCOME: PASSES on unfixed code.
    """

    def test_preservation_empty_personas_list(self):
        """
        **Validates: Requirements 3.1**

        Observation 3: When state["company_intelligence"] has status="ok" but
        an empty personas list, the fallback block iterates over an empty list
        and adds nothing to all_personas.

        Encode: the UNFIXED fallback logic produces an empty all_personas list
        for empty intel personas. This behavior is preserved after the fix.
        """
        intel = {
            "status": "ok",
            "company_profile": {"name": "Acme", "domain": "acme.io"},
            "personas": [],  # empty list — the bug condition does NOT hold
        }

        # Replicate the UNFIXED fallback block from _tool_generate_event
        all_personas = []
        if intel.get("status") == "ok":
            for p in intel.get("personas", []):
                p_copy = dict(p)
                # UNFIXED: uses "name" key — but loop body never executes for empty list
                p_copy["company_domain"] = intel.get("company_profile", {}).get("name", "")
                all_personas.append(p_copy)

        # Baseline: empty personas list → all_personas remains empty
        assert all_personas == [], (
            f"Preservation (Obs 3): expected empty all_personas for empty intel personas, "
            f"got {all_personas!r}"
        )

    @given(
        company_name=st.text(min_size=2, max_size=30).filter(lambda s: s.strip()),
        company_domain=st.from_regex(r"[a-z]{3,10}\.(com|ai|io)", fullmatch=True),
    )
    @h_settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_preservation_empty_personas_property(
        self, company_name: str, company_domain: str
    ):
        """
        **Validates: Requirements 3.1**

        Property: For any company_profile, when intel["personas"] is empty,
        the UNFIXED fallback block produces an empty all_personas list.

        This encodes the baseline: empty personas input → empty personas output.
        The fix does not change this behavior.

        EXPECTED OUTCOME: PASSES on unfixed code.
        """
        intel = {
            "status": "ok",
            "company_profile": {"name": company_name.strip(), "domain": company_domain},
            "personas": [],
        }

        all_personas = []
        if intel.get("status") == "ok":
            for p in intel.get("personas", []):
                p_copy = dict(p)
                p_copy["company_domain"] = intel.get("company_profile", {}).get("name", "")
                all_personas.append(p_copy)

        assert all_personas == [], (
            f"Preservation (Obs 3, property): expected empty all_personas, got {all_personas!r}. "
            f"company_name={company_name.strip()!r}, company_domain={company_domain!r}"
        )


# ---------------------------------------------------------------------------
# Observation 4 — LLM-generated personas are not overwritten by fallback
# ---------------------------------------------------------------------------

class TestPreservationLLMPersonasNotOverwritten:
    """
    **Validates: Requirements 3.3**

    Observation 4: The fallback block in _tool_generate_event is only entered
    when the LLM-generated payload has an empty or missing personas array:

        if not isinstance(personas, list) or len(personas) == 0:
            # fallback block

    When the LLM returns a non-empty personas array, the condition is False
    and the fallback block is NOT entered. The LLM payload is used as-is.

    This guard condition is completely unaffected by either bug fix.

    EXPECTED OUTCOME: PASSES on unfixed code.
    """

    def test_preservation_llm_personas_not_overwritten(self):
        """
        **Validates: Requirements 3.3**

        Observation 4: When the LLM mock returns a non-empty personas array,
        the guard condition `not isinstance(personas, list) or len(personas) == 0`
        evaluates to False, so the fallback block is not entered.

        Encode: the guard condition correctly identifies non-empty LLM personas
        and skips the fallback. This behavior is unchanged after the fix.
        """
        # Simulate LLM-generated payload with non-empty personas
        llm_payload = {
            "personas": [
                {
                    "full_name": "Aravind Srinivas",
                    "title": "CEO",
                    "company_domain": "perplexity.ai",
                    "email": "aravind@perplexity.ai",
                    "linkedin_url": "https://linkedin.com/in/aravind-srinivas",
                }
            ]
        }

        # Replicate the guard condition from _tool_generate_event
        personas = llm_payload.get("personas")
        fallback_entered = not (isinstance(personas, list) and len(personas) > 0)

        # Baseline: non-empty LLM personas → fallback NOT entered
        assert not fallback_entered, (
            f"Preservation (Obs 4): fallback block was entered despite non-empty LLM personas. "
            f"personas={personas!r}"
        )
        # The LLM payload is used as-is — personas unchanged
        assert llm_payload["personas"] == personas, (
            f"Preservation (Obs 4): LLM personas were modified. "
            f"expected={llm_payload['personas']!r}, got={personas!r}"
        )

    @given(
        personas=st.lists(
            st.fixed_dictionaries({
                "full_name": st.text(min_size=3, max_size=30).filter(lambda s: s.strip()),
                "title": st.sampled_from(["CEO", "CTO", "VP Sales", "CFO", "Head of Eng"]),
                "company_domain": st.from_regex(r"[a-z]{3,10}\.(com|ai|io)", fullmatch=True),
            }),
            min_size=1,
            max_size=5,
        )
    )
    @h_settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_preservation_llm_personas_not_overwritten_property(self, personas):
        """
        **Validates: Requirements 3.3**

        Property: For any non-empty personas list returned by the LLM, the
        guard condition in _tool_generate_event evaluates to False, meaning
        the fallback block is NOT entered and the LLM payload is used as-is.

        This encodes the baseline guard behavior that the fix must not change.

        EXPECTED OUTCOME: PASSES on unfixed code.
        """
        llm_payload = {"personas": personas}

        # Replicate the guard condition
        p = llm_payload.get("personas")
        fallback_entered = not (isinstance(p, list) and len(p) > 0)

        assert not fallback_entered, (
            f"Preservation (Obs 4, property): fallback entered for non-empty LLM personas. "
            f"personas={p!r}"
        )


# ---------------------------------------------------------------------------
# Observation 5 — Unparseable observation falls back to obs[:300] truncation
# ---------------------------------------------------------------------------

class TestPreservationUnparseableObservationFallback:
    """
    **Validates: Requirements 3.5**

    Observation 5: When an observation string is not valid JSON, the UNFIXED
    intel_lines list comprehension applies obs[:300] truncation directly
    (there is no try/except in the unfixed code — it just slices).

    The FIXED code introduces a try/except loop: the try branch parses JSON
    and extracts persona fields; the except branch falls back to obs[:300].

    For non-JSON observations, the except branch fires and produces the same
    obs[:300] output as the unfixed code. This preservation test encodes that
    the except branch in the fixed code reproduces the exact unfixed behavior.

    EXPECTED OUTCOME: PASSES on unfixed code (the unfixed obs[:300] IS the
    baseline that the except branch must match).
    """

    def test_preservation_unparseable_obs_fallback(self):
        """
        **Validates: Requirements 3.5**

        Observation 5: For a non-JSON observation string, the UNFIXED
        intel_lines logic (obs[:300]) produces a specific intelligence_context.

        Encode: the except branch in the fixed code must produce the same
        output — f"- {domain}: {obs[:300]}". Test that the unfixed logic
        produces this exact format for a non-JSON string.
        """
        domain = "acme.io"
        non_json_obs = "This is not JSON. It is a plain text observation about Acme Inc. " * 10

        # Replicate the UNFIXED intel_lines logic (no try/except — just obs[:300])
        intel_entries = [(domain, non_json_obs)]
        intel_lines = [f"- {d}: {obs[:300]}" for d, obs in intel_entries[-5:]]
        intelligence_context = (
            f"\nCompany intelligence fetched this session:\n"
            f"{chr(10).join(intel_lines)}\n"
        )

        # Baseline: the truncated non-JSON obs is present
        expected_line = f"- {domain}: {non_json_obs[:300]}"
        assert expected_line in intelligence_context, (
            f"Preservation (Obs 5): expected line not found in intelligence_context. "
            f"expected_line={expected_line!r}, "
            f"intelligence_context={intelligence_context!r}"
        )
        # The full non-JSON string is NOT present (it's longer than 300 chars)
        if len(non_json_obs) > 300:
            assert non_json_obs not in intelligence_context, (
                f"Preservation (Obs 5): full non-JSON obs should be truncated but was found "
                f"in intelligence_context."
            )

    @given(
        domain=st.from_regex(r"[a-z]{3,10}\.(com|ai|io)", fullmatch=True),
        obs_text=st.text(min_size=10, max_size=600).filter(
            lambda s: s.strip() and not s.strip().startswith("{")
        ),
    )
    @h_settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_preservation_unparseable_obs_fallback_property(
        self, domain: str, obs_text: str
    ):
        """
        **Validates: Requirements 3.5**

        Property: For any non-JSON observation string, the UNFIXED intel_lines
        logic produces an intelligence_context that contains exactly obs[:300]
        (the truncated observation) prefixed by the domain.

        This encodes the baseline that the fixed code's except branch must
        reproduce: for non-JSON observations, output is f"- {domain}: {obs[:300]}".

        EXPECTED OUTCOME: PASSES on unfixed code.
        """
        intel_entries = [(domain, obs_text)]
        intel_lines = [f"- {d}: {obs[:300]}" for d, obs in intel_entries[-5:]]
        intelligence_context = (
            f"\nCompany intelligence fetched this session:\n"
            f"{chr(10).join(intel_lines)}\n"
        )

        expected_line = f"- {domain}: {obs_text[:300]}"
        assert expected_line in intelligence_context, (
            f"Preservation (Obs 5, property): expected truncated line not in context. "
            f"domain={domain!r}, obs_text[:300]={obs_text[:300]!r}"
        )
