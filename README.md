# Agentic B2B Outreach Suite

> **Topics:** `python`, `artificial-intelligence`, `machine-learning`, `multi-agent-systems`, `data-analysis`, `automation`, `web-development`, `api`, `data-processing`

## Overview

This project, **Agentic B2B Outreach Suite**, was developed as part of the coursework **CS503 - Full-Stack Development** at **Esprit School of Engineering**, and as a partnership with **Addvocate AI**, a Tunisian startup. It explores real-time B2B data processing, automated lead generation, multi-agent orchestration, and personalized outreach using large language models.

This project was completed under the guidance of the following professors at **Esprit School of Engineering**:

- Pr. [Sonia Mesbeh](mailto:sonia.mesbeh@Esprit.tn)
- Pr. [Jihene Jebri](mailto:Jihene.Jebri@esprit.tn)
- Pr. [Wided Askri](mailto:Wided.Askri@esprit.tn)

The ecosystem is built upon a highly modular architecture comprising **six distinct autonomous systems**. Together, they automate the entire sales intelligence and outreach pipeline—from discovering leads to generating highly personalized, multi-channel messaging strategies.

---

## The 6 Core Modules

### 1. `detective` (Agentic Lead Generation)
An LLM-powered ReAct agent designed to dynamically extract Ideal Customer Profiles (ICPs) and build target company lists.
- **Dynamic Routing**: Replaces hardcoded pipelines with an LLM that autonomously decides which tools to execute and in what order.
- **Robust Recovery**: Features automatic retry logic (up to 3 times per tool) with semantic broadening (e.g., expanding industry terms) for empty results.
- **Integration**: Exposes Model Context Protocol (MCP) tools for external orchestrators to run full pipelines and access an auditable `agent_scratchpad`.

### 2. `intent` (Agentic Intent System)
An intelligent clustering and explainability engine that monitors company signals.
- **Signal Extraction**: Analyzes company funding and news events using DuckDuckGo for live data gathering.
- **Explainable AI (XAI)**: Provides an XAI engine to clearly justify event clustering decisions, source reliability, and confidence scores.
- **Performance Evaluation**: Built-in metrics collection and system performance evaluator.

### 3. `inject collect` (Discovery & Scraping)
An advanced enterprise data aggregation and warehousing system.
- **API Discovery**: Automates the discovery of companies and leads using the Apollo.io API based on location and industry filters.
- **Smart Scraping**: Combines Playwright-based dynamic website scraping with Google Gemini AI to extract technical fingerprints and product summaries.
- **Data Merging**: Merges multi-source data with confidence scoring and stores versioned profiles in a Neo4j AuraDB graph database.

### 4. `writer` (Message Generator Pipeline)
A multi-agent LangGraph pipeline that writes, validates, and refines personalized sales outreach messages.
- **5-Step Flow**: Orchestrates `Planner → Researcher → Strategist → Writer → Critic`.
- **Constraint Enforcement**: Dynamically fetches CRM history, enforces hard constraints (character limits, banned phrases), and uses the Critic agent to bounce bad drafts back to the Writer.
- **Human-in-the-Loop**: Can pause after the Critic approves a message, waiting for a human decision before dispatching via Email or LinkedIn.

### 5. `strategist` (Sequence Generator)
A dedicated orchestration module for building multi-step outreach sequences.
- **UI & Workflows**: Provides a Streamlit user interface and utilizes Temporal workers to map out a sequenced outreach strategy.
- **Decision Engine**: Finds decision-makers, researches them, and plans the sequence timing across channels before delegating the actual content drafting to the `writer` module.

### 6. `worker` (Telemetry & Optimization Backend)
The central nervous system acting as the telemetry, traceability, and continuous optimization spine.
- **Architecture**: Built on FastAPI and PostgreSQL (`asyncpg`) with a Redis subscriber operating in the background.
- **Event Tracking**: Automatically creates worker tables to persist events, detect near-duplicates, and link outcomes (e.g., replies, clicks) to specific outreach generations.
- **Autonomous Optimization**: Runs an autonomous background loop based on `feedback_submitted` events to continuously refine the system's targeting and messaging rules.

---

## 🏗️ System Architecture & Data Flow

```text
┌─────────────────┐      ┌─────────────────┐      ┌──────────────────┐
│ 3. inject collect│─────▶│  1. detective   │─────▶│    2. intent     │
│ (Data Aggregator)│      │ (Targeting LLM) │      │ (News & Funding) │
└─────────────────┘      └────────┬────────┘      └────────┬─────────┘
                                  │                        │
                                  ▼                        ▼
┌─────────────────┐      ┌─────────────────┐      ┌──────────────────┐
│   5. strategist │◀─────│    4. writer    │◀─────│    6. worker     │
│(Sequence & UI)  │─────▶│(LangGraph Gen)  │─────▶│ (Telemetry DB)   │
└─────────────────┘      └─────────────────┘      └──────────────────┘
```

---

## Tech Stack

### Frontend & Workflows
- **Streamlit**: For the `strategist` Prospect Strategy Engine UI.
- **React.js & Material-UI**: Scalable web interfaces for general monitoring.
- **Temporal**: Durable, retryable background workflows for sequence timing.

### Backend & Orchestration
- **Python 3.11+**
- **FastAPI**: Backend framework for the `worker` and `writer` APIs.
- **LangGraph & LangChain**: Sequential multi-agent routing.
- **Model Context Protocol (FastMCP)**: Standardized Agent-to-Agent communication.

### Data & AI Tools
- **Databases**: PostgreSQL (Relational Telemetry), Redis (Message Queues), Neo4j AuraDB (Graph Profiles).
- **AI Models**: Google Gemini Pro/Flash, Groq (Llama-3 8b-instant).
- **Automation**: Playwright (Web scraping), Apollo.io API (Lead intelligence), Docker & Docker Compose.

---

## Directory Structure

```text
agentic-b2b-suite/
├── detective/                      # ReAct agent, MCP tools, and scratchpad
├── intent/                         # XAI, Funding/News clustering LangGraph
├── inject_collect/                 # Apollo discovery & AI Playwright scraper
├── writer/                         # 5-Agent message generator & validation
├── strategist/                     # Sequence builder, Temporal worker, Streamlit UI
├── worker/                         # Telemetry API, Postgres tables, Redis subscriber
└── README.md
```

---

## Getting Started

### Prerequisites
- **Python** 3.8+ (3.11 highly recommended)
- **Docker** & **Docker Compose**
- API Keys for **Google Gemini**, **Groq**, and **Apollo.io**.
- (Optional) OpenRouteService key for geo-filtering in `detective`.

### Installation Setup

1. **Clone the Repository**
   ```bash
   git clone https://github.com/your-username/agentic-b2b-suite.git
   cd agentic-b2b-suite
   ```

2. **Configure Environment Variables**
   Create a `.env` file at the root or within specific module directories:
   ```env
   GROQ_API_KEY=your_groq_key
   GEMINI_API_KEY=your_gemini_key
   APOLLO_API_KEY=your_apollo_key
   DATABASE_URL=postgres://user:pass@localhost:5432/db
   REDIS_URL=redis://localhost:6379/0
   GRAPH_DB_URL=neo4j+s://...
   ```

3. **Run the Full Ecosystem with Docker**
   Launch the multi-agent pipelines and telemetry backends simultaneously:
   ```bash
   docker-compose up --build
   ```

4. **Run Individual Modules (Example: Writer)**
   ```bash
   cd writer
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8003
   ```

---

## Acknowledgments

This extensive multi-agent project was developed under the guidance of the faculty at **Esprit School of Engineering**. It serves as an exploration into the bleeding edge of artificial intelligence, multi-agent automated data analysis, Explainable AI, and scalable enterprise telemetry architectures.
