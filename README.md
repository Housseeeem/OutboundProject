# AgenticOutbound

An end-to-end AI-powered B2B outbound engine. The system collects and enriches leads, scores and graphs relationships, plans and executes outreach campaigns, and tracks outcomes — all connected through an event-driven architecture with full traceability.

---

## Architecture Overview

```
Inject → Detective → Writer → Worker → Metrics → Optimization
```

| Module | Role |
|---|---|
| **Inject** | Collects, enriches, and versions B2B lead data; emits `lead_ingested` events |
| **Detective** | Filters, scores leads, and builds relationship graphs |
| **Writer** | Plans and executes AI-driven outreach campaigns |
| **Worker** | Telemetry, traceability, outcome linking, and optimization |

All modules communicate via a canonical `EventEnvelope` published to Redis pub/sub and consumed by Worker's background subscriber.

---

## Repository Structure

```
OutboundProject/
├── inject_collect_project/     # Module 1 — data collection & enrichment pipeline
│   ├── main_discovery.py       # Pipeline entry point
│   ├── event_emitter.py        # Redis pub/sub emission with in-memory fallback
│   ├── apollo_scraper.py       # Apollo.io search + enrich
│   ├── apify_enricher.py       # Apify website crawler + news scraper
│   ├── intent_collector.py     # Intent signals (news, jobs, tech changes)
│   ├── detective_formatter.py  # Formats payload for downstream modules
│   ├── persona_search_enrich.py# Persona discovery + contact enrichment
│   ├── database_manager.py     # Neo4j versioned storage
│   └── documentation/
│       ├── README_HighLevel.md
│       └── README_technical.md
│
├── WorkerModule/               # Module 4 — telemetry, integrity, graph trace, optimization, agent runtime
│   ├── app/
│   │   ├── main.py             # FastAPI app, DB lifecycle, Redis subscriber + optimizer background tasks
│   │   ├── subscriber.py       # Redis pub/sub ingestion on canonical event channels
│   │   ├── optimizer.py        # Autonomous config tuning loop from feedback events
│   │   ├── config.py           # Runtime settings and guardrails
│   │   ├── routers/
│   │   │   ├── ingest.py       # /v1/events*, /v1/outcomes/link
│   │   │   ├── trace.py        # /v1/metrics, /v1/kpis, /v1/integrity, graph + optimization APIs
│   │   │   ├── agent.py        # /v1/agent/*
│   │   │   ├── a2a.py          # /.well-known/agent.json, /tasks/send, /tasks/sendSubscribe
│   │   │   ├── config.py       # /v1/config*
│   │   │   └── feedback.py     # /v1/feedback
│   │   └── modules/worker/
│   │       ├── storage.py      # Events/outcomes/integrity/optimization persistence
│   │       ├── schemas.py      # Canonical payload schema validation
│   │       ├── sync.py         # Postgres->graph projection + parity/checkpoints
│   │       ├── graph.py        # Graph node/edge builders
│   │       ├── integrity.py    # Integrity checking helpers
│   │       └── kpi.py          # KPI computation helpers
│   └── tests/
│       ├── test_bug_condition.py
│       └── test_preservation.py
│
├── frontend/                   # Control Plane dashboard (Next.js App Router)
│   ├── src/app/                # UI routes: dashboard, mission control, traces, settings
│   ├── src/components/         # Mission control UI components
│   ├── src/lib/useAgentRun.ts  # Agent run polling + resume logic
│   ├── next.config.ts          # Next.js standalone output for Docker
│   └── Dockerfile              # Production container build
│
└── docker-compose.yml          # Shared stack: Redis, Postgres, Neo4j, API, Inject
```

---

## Quick Start

### Prerequisites
- Docker Desktop running

### Start the full stack

```bash
docker-compose up -d
```

This starts:
- `redis` — shared message broker (port 6379)
- `postgres` — Worker event store (port 5433)
- `neo4j` — Inject graph database (ports 7475, 7688)
- `api` — WorkerModule FastAPI service (port 8000)
- `inject_collector` — Inject pipeline container
- `frontend` — Control Plane dashboard (port 3000)

### Verify everything is healthy

```bash
curl.exe http://localhost:8000/health
# {"status":"ok"}
```

---

## Event Flow

### How a lead_ingested event travels end-to-end

1. Inject processes a company and calls `emit_lead_ingested(payload)`
2. `event_emitter.py` wraps the payload in a canonical `EventEnvelope` and publishes it to the Redis `lead_ingested` channel
3. Worker's `subscriber.py` background task receives the message, validates the envelope, and calls `save_event()` directly
4. The event is stored in Postgres and immediately queryable via the trace API

```bash
# Query the event timeline for a correlation ID
curl.exe http://localhost:8000/v1/events/trace/{correlation_id}
```

### EventEnvelope schema

```json
{
  "event_id":       "uuid",
  "correlation_id": "uuid",
  "module":         "inject | detective | writer | worker",
  "event_type":     "lead_ingested | lead_scored | message_sent | ...",
  "timestamp":      "ISO 8601",
  "payload":        {},
  "metadata":       {}
}
```

---

## Worker API

Base URL: `http://localhost:8000`

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/ready` | Readiness check |
| `POST` | `/v1/events/ingest` | Ingest one canonical event with idempotency + duplicate-window safeguards |
| `GET` | `/v1/events` | List events with optional filters |
| `GET` | `/v1/events/trace/{correlation_id}` | Correlation timeline (chronological event list) |
| `POST` | `/v1/outcomes/link` | Link an outcome to a decision event |
| `GET` | `/v1/metrics` | Correlation or global metrics (reply/conversion rates, counts) |
| `GET` | `/v1/kpis` | System KPI summary |
| `GET` | `/v1/integrity/audit` | Detect missing/duplicate/orphan/chain-break issues |
| `GET` | `/v1/trace/correlation/{correlation_id}` | Graph-oriented correlation trace (with fallback path) |
| `POST` | `/v1/optimization/run` | Generate dry-run recommendations |
| `GET` | `/v1/optimization/recommendations` | Recommendation history |
| `POST` | `/v1/optimization/recommendations/{id}/approve` | Approve recommendation |
| `POST` | `/v1/optimization/recommendations/{id}/execute` | Execute dry-run/apply with policy guardrails |
| `POST` | `/v1/optimization/recommendations/{id}/reject` | Reject recommendation |
| `POST` | `/v1/optimization/recommendations/{id}/rollback` | Roll back recommendation |
| `POST` | `/v1/agent/runs` | Launch synchronous agent run |
| `POST` | `/v1/agent/runs/async` | Launch asynchronous agent run |
| `GET` | `/.well-known/agent.json` | A2A agent card |
| `POST` | `/tasks/send` | A2A task endpoint |
| `POST` | `/tasks/sendSubscribe` | A2A SSE endpoint |

---

## Frontend (Control Plane Dashboard)

The frontend is a Next.js (App Router) control plane located in `frontend/`. It renders a dashboard and mission-control experience for running agent workflows and inspecting pipeline telemetry.

### What the UI actually does

- **Dashboard** (`/`) fetches recent events from `GET /v1/events?limit=20` and summarizes lead ingestion, scoring, and message generation.
- **Mission Control** (`/mission`) launches and monitors agent runs via `POST /v1/agent/runs/async`, polls `GET /v1/agent/runs/{id}`, and resumes human approvals with `POST /v1/agent/runs/{id}/resume`.
- **Pipeline Traces** (`/traces`) queries `GET /v1/events/trace/{correlation_id}`.
- **Settings & Config** (`/settings`) loads `GET /v1/config` and persists updates to `POST /v1/config/update`.

### Local development

```bash
cd frontend
npm install
npm run dev
```

The UI expects the Worker API at `http://localhost:8000` and will require CORS for local development.


## Configuration

### WorkerModule (`WorkerModule/.env`)

```env
DATABASE_URL=postgresql://user:password@localhost:5433/agentic
REDIS_URL=redis://redis:6379
GRAPH_DB_URL=neo4j+s://your-instance.databases.neo4j.io
GRAPH_DB_USER=your_user
GRAPH_DB_PASSWORD=your_password
GEMINI_API_KEY=your_key
OPENAI_API_KEY=your_key
```

### Inject (`inject_collect_project/.env`)

```env
APOLLO_API_KEY=your_key
APIFY_API_KEY=your_key
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USER=your_user
NEO4J_PASSWORD=your_password
REDIS_URL=redis://redis:6379
```

---

## Running Tests

```bash
# Unit + property-based tests (no Docker required)
python -m pytest WorkerModule/tests/ -v
```

17 tests covering:
- Subscriber existence and startup wiring
- Redis message → `save_event()` call path
- Docker network and Redis service sharing
- Envelope field preservation across all generated payloads
- HTTP ingest endpoint regression (202 Accepted)
- In-memory fallback when Redis is unavailable

---

## Manual End-to-End Test

Publish a test event from inside the API container (avoids PowerShell quoting issues):

```bash
docker exec outboundproject-api-1 python3 -c "
import asyncio, redis.asyncio as r, json
asyncio.run(r.from_url('redis://redis:6379').publish('lead_ingested', json.dumps({
    'event_id': '00000000-0000-0000-0000-000000000001',
    'correlation_id': '00000000-0000-0000-0000-000000000002',
    'module': 'inject',
    'event_type': 'lead_ingested',
    'timestamp': '2026-04-25T10:00:00+00:00',
    'payload': {'company_id': 'test'},
    'metadata': {}
})))
"

curl.exe http://localhost:8000/v1/events/trace/00000000-0000-0000-0000-000000000002
```

Expected response: the stored event JSON.

---

## Design Principles

- **Event-driven** — all inter-module communication via Redis pub/sub `EventEnvelope`
- **Full traceability** — every lead carries a `correlation_id` from ingestion to outcome
- **Outcome-driven optimization** — Worker links decisions to outcomes and computes KPIs
- **Loose coupling** — modules share only the event schema, not code or databases
- **Graceful degradation** — Inject falls back to in-memory queue when Redis is unavailable
