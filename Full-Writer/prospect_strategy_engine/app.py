"""Streamlit UI for the Prospect Strategy Engine.

Flow:
  1. User enters a company domain.
  2. Hunter.io finds the decision-maker (name, email, title, LinkedIn).
  3. Tavily searches the web for context on that person.
  4. The strategy agent (agents/graph.py) generates a sequenced action plan.
  5. The outreach message is generated via the Writer MCP endpoint
     (falls back to Ollama/Mistral if MCP is unavailable).
"""

import streamlit as st
from tools.hunter_client import find_decision_maker
from tools.tavily_client import search_prospect_context
from tools.outreach_mcp import generate_outreach_message
from agents.graph import app as strategy_agent
from config import settings

st.set_page_config(page_title="Prospect Strategy Engine", layout="wide", page_icon="🚀")
st.title("🚀 Prospect Strategy Engine — B2B Sales Intelligence")

domain = st.text_input(
    "Enter the company domain (e.g. gomycode.com)",
    placeholder="domain.com",
)

if st.button("Run Analysis 🧠"):
    if not domain:
        st.error("Please enter a domain.")
    else:
        with st.spinner("Researching prospect..."):
            # Step 1: Find decision-maker via Hunter
            contact = find_decision_maker(domain)

            # Step 2: Search web context via Tavily
            prospect_name = contact.get("name") if contact.get("name") else f"CEO of {domain}"
            web_context = search_prospect_context(prospect_name, domain)

            # Step 3: Generate strategy plan via LangGraph agent
            agent_input = {
                "prospect_name": prospect_name,
                "has_email": bool(contact.get("email")),
                "has_phone": False,  # Hunter doesn't return phone numbers
                "recent_posts_context": web_context.get("profile_summary", "No context found."),
            }
            agent_result = strategy_agent.invoke(agent_input)
            plan = agent_result.get("final_plan")

            # Step 4: Generate outreach message via Writer MCP (Ollama fallback)
            try:
                message = generate_outreach_message(
                    target_prospect=prospect_name,
                    target_company=contact.get("company", domain),
                    prospect_role=contact.get("title"),
                    has_email=bool(contact.get("email")),
                )
            except Exception as exc:
                message = f"⚠️ Could not generate message: {exc}"

        # --- Display results ---
        display_name = contact.get("name") or "Decision-maker (identified by AI)"

        st.header(f"🎯 Target: {display_name}")

        col1, col2 = st.columns(2)
        with col1:
            st.success(f"**📧 Email:** {contact.get('email', 'Not found publicly')}")
            st.info(f"**💼 Title:** {contact.get('title', 'Executive / Manager')}")
        with col2:
            st.info(f"**🏢 Company:** {contact.get('company', domain).upper()}")
            if contact.get("linkedin_url"):
                st.link_button("🔗 LinkedIn Profile", contact.get("linkedin_url"))
            else:
                st.warning("⚠️ LinkedIn: Manual search required")

        st.divider()

        if plan:
            st.subheader("🛡️ Strategic Action Plan")
            for step in plan.sequence:
                with st.expander(f"Step {step.step} — {step.channel} ({step.timing})"):
                    st.write(f"**Action:** {step.recommended_action}")
                    st.write(f"**Why:** {step.justification}")

        st.divider()
        st.subheader("✉️ Generated Outreach Message")
        st.markdown(message)

st.sidebar.markdown("### 🛠️ Tool Status")
st.sidebar.write("✅ Hunter API" if settings.HUNTER_API_KEY else "❌ Hunter API (key missing)")
st.sidebar.write("✅ Tavily Search" if settings.TAVILY_API_KEY else "❌ Tavily Search (key missing)")
st.sidebar.write(f"🤖 LLM: {settings.OLLAMA_MODEL} via Ollama")
st.sidebar.write(f"📡 Writer MCP: {settings.OUTREACH_MCP_URL}")
