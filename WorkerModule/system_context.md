# 🧩 AgenticOutbound — System Context (Production Architecture)

## 🎯 System Objective
Build an end-to-end AI outbound engine that:
1. Collects and enriches B2B leads (Inject)
2. Filters, scores, and builds relationships (Detective)
3. Plans and executes outreach campaigns (Writer)
4. Tracks outcomes and optimizes decisions (Worker)

The system is event-driven, traceable, and outcome-optimized.

---

# 🏗️ MODULE ARCHITECTURE

## 1. Inject / Collect Module (Data Factory)
Role:
Asynchronous pipeline that ingests, validates, enriches, and versions lead data.

Key Capabilities:
- Multi-source ingestion
- Validation & enrichment
- Persona extraction
- Versioning system (PostgreSQL)
- Intent scoring
- Output trigger → sends qualified leads to Detective

---

## 2. Detective Module (Lead Intelligence Engine)
Role:
Filters, scores, and builds relationship graphs.

Key Capabilities:
- ICP definition + AI weighting
- Rule-based filtering
- Weighted scoring
- Relationship graph (Neo4j)

---

## 3. Writer Module (AI Outreach Engine)
Role:
Plans and executes outbound campaigns using multiple agents.

Sub-agents:
- Path Finder
- Strategy
- Message
- Quality
- Execution

Infrastructure:
- LangGraph
- Temporal
- Redis
- PostgreSQL + pgvector
- Neo4j

---

## 4. Worker Module (Telemetry, Feedback & Optimization Engine)

Role:
System observability, traceability, and optimization backbone.

---

# 🧠 WORKER MODULE RESPONSIBILITIES

## 1. Event Logging Infrastructure
- Capture all events across modules
- Store in structured schema
- Ensure real-time ingestion & no data loss

Event Types:
- lead_ingested
- lead_scored
- message_generated
- message_sent
- reply_received
- conversion

---

## 2. Correlation & Traceability
- Use correlation_id across all modules
- Reconstruct full workflow per lead

---

## 3. Outcome Linking
- Link decisions → actions → outcomes
- Store outcomes and update metrics

KPIs:
- Reply rate
- Conversion rate
- Strategy performance

---

## 4. Dashboard Integration
- Provide real-time metrics and traces

---

## 5. Alerts & Data Integrity
- Detect missing or inconsistent events
- Trigger alerts

---

# 🔄 DATA FLOW

Inject → Detective → Writer → Worker → Metrics → Optimization

---

# 🧱 CORE DATA MODELS

## Event
{
  "event_id": "uuid",
  "correlation_id": "uuid",
  "module": "inject | detective | writer | worker",
  "event_type": "...",
  "timestamp": "...",
  "payload": {},
  "metadata": {}
}

## Outcome
{
  "outcome_id": "uuid",
  "correlation_id": "uuid",
  "linked_event_id": "...",
  "type": "reply | conversion | ignore",
  "timestamp": "...",
  "value": {}
}

---

# ⚠️ MODULE BOUNDARIES

Worker DOES:
- Log
- Trace
- Link
- Analyze

Worker DOES NOT:
- Generate leads
- Score leads
- Generate messages
- Execute campaigns

---

# 🔥 DESIGN PRINCIPLES

- Event-driven architecture
- Full traceability
- Outcome-driven optimization
- Loose coupling
