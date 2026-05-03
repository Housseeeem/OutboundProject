# WorkerModule (Etat Reel du Code)

WorkerModule est le backend FastAPI qui sert de colonne vertebrale de telemetry, traceability, integrity et optimization pour AgenticOutbound.
Pour une vue d'ensemble plus professionnelle de l'architecture, voir [docs/architecture.md](docs/architecture.md).

Ce document decrit ce qui est effectivement implemente dans le code aujourd'hui.

## Ce qui est vraiment implemente

- API FastAPI avec middleware `X-Correlation-ID` et CORS permissif
- Pool Postgres `asyncpg` initialise au startup
- Creation automatique des tables Worker au demarrage (`events`, `outcomes`, `integrity_alerts`, `graph_sync_checkpoints`, `optimization_recommendations`, `global_config`)
- Subscriber Redis en tache de fond (`app/subscriber.py`) qui ecoute et persiste des evenements sans passer par HTTP
- Boucle d'optimisation autonome en tache de fond (`app/optimizer.py`) basee sur les evenements `feedback_submitted`
- Adaptateur graphe (Neo4j) avec fallback si indisponible
- Service agent et API agent pour lancer/reprendre des runs
- Endpoint A2A (`/.well-known/agent.json`, `/tasks/send`, `/tasks/sendSubscribe`)

## Contrat EventEnvelope effectivement applique

Le subscriber Redis et l'endpoint d'ingestion HTTP travaillent tous les deux sur un envelope canonique:

- `event_id`
- `correlation_id`
- `module` (`inject|detective|writer|worker`)
- `event_type`
- `timestamp`
- `payload`
- `metadata`

Canaux Redis souscrits nativement:
- `lead_ingested`
- `lead_scored`
- `message_generated`
- `message_sent`
- `reply_received`
- `conversion`

## Endpoints exposes actuellement

### Base
- `GET /health`
- `GET /ready`

### Events et outcomes
- `POST /v1/events/ingest`
- `GET /v1/events`
- `GET /v1/events/trace/{correlation_id}`
- `POST /v1/outcomes/link`
- `GET /v1/outcomes`
- `GET /v1/outcomes/{outcome_id}`
- `GET /v1/events_outcomes/{correlation_id}`

### Metrics, integrity, graph
- `GET /v1/metrics`
- `GET /v1/kpis`
- `GET /v1/integrity/audit`
- `GET /v1/alerts`
- `POST /v1/alerts/{alert_id}/acknowledge`
- `POST /v1/alerts/{alert_id}/resolve`
- `DELETE /v1/alerts/{alert_id}`
- `GET /v1/trace/correlation/{correlation_id}`
- `GET /v1/trace/correlation/{correlation_id}/checkpoint`
- `GET /v1/trace/lead/{lead_id}`
- `GET /v1/trace/impact`

### Optimisation
- `POST /v1/optimization/run` (dry-run de recommandations)
- `GET /v1/optimization/recommendations`
- `GET /v1/optimization/audit`
- `POST /v1/optimization/recommendations/{recommendation_id}/approve`
- `POST /v1/optimization/recommendations/{recommendation_id}/execute`
- `POST /v1/optimization/recommendations/{recommendation_id}/reject`
- `POST /v1/optimization/recommendations/{recommendation_id}/rollback`

### Agent runtime
- `POST /v1/agent/runs`
- `POST /v1/agent/runs/async`
- `POST /v1/agent/runs/{run_id}/resume`
- `GET /v1/agent/runs/{run_id}`
- `GET /v1/agent/runs/{run_id}/evaluation`
- `GET /v1/agent/runs`
- `GET /v1/agent/tools`
- `POST /v1/agent/runs/cleanup`

### A2A et configuration
- `GET /.well-known/agent.json`
- `POST /tasks/send`
- `POST /tasks/sendSubscribe` (SSE)
- `GET /v1/config`
- `POST /v1/config/update`
- `POST /v1/feedback`

## Comportements importants en production

- Ingestion HTTP:
  - idempotence sur `event_id` (insert conflict -> no-op)
  - detection de near-duplicate dans une fenetre temporelle configurable
  - validation de schema en mode `warn` ou `enforce`
  - backpressure (HTTP 429) si semaphore de concurrence sature
- Outcome linking:
  - peut exiger l'existence de l'evenement lie via `OUTCOME_LINK_REQUIRES_EVENT`
  - sinon accepte l'outcome et garde la trace d'integrite
- Graph trace:
  - projection et checkpoint si graphe disponible
  - fallback Postgres si Neo4j indisponible

## Variables d'environnement utiles

- `DATABASE_URL`
- `REDIS_URL`
- `GRAPH_DB_URL`
- `GRAPH_DB_USER`
- `GRAPH_DB_PASSWORD`
- `EVENT_SCHEMA_VALIDATION_MODE`
- `EVENT_SCHEMA_ALLOW_UNKNOWN_TYPES`
- `INGEST_MAX_INFLIGHT`
- `INGEST_DUPLICATE_WINDOW_SECONDS`
- `INGEST_DB_TIMEOUT_SECONDS`
- `OUTCOME_LINK_REQUIRES_EVENT`
- `OPTIMIZATION_APPLY_ENABLED`
- `OPTIMIZATION_APPLY_MAX_CHANGE_PCT`

## Demarrage local

```bash
docker compose up --build
```

Verification minimale:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```
