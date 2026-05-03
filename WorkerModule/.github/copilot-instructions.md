# Copilot Instructions

## Purpose
This workspace uses two reference projects to guide Worker implementation:
- [tech_journalist_demo-main/README.md](../../tech_journalist_demo-main/README.md): multi-agent orchestration patterns (LangGraph, MCP, A2A, conflict detection).
- [atelier3/agent.py](../../atelier3/agent.py): compact ReAct + tool loop + memory + fallback/evaluation patterns.

Use these as design references only. Apply them inside Worker operational boundaries.

## Start Here
When asked to "apply agentic logic" in Worker, inspect in this order:
1. [tech_journalist_demo-main/orchestration/contracts.py](../../tech_journalist_demo-main/orchestration/contracts.py)
2. [tech_journalist_demo-main/orchestration/langgraph_orchestrator.py](../../tech_journalist_demo-main/orchestration/langgraph_orchestrator.py)
3. [tech_journalist_demo-main/orchestration/agents/scout_agent.py](../../tech_journalist_demo-main/orchestration/agents/scout_agent.py)
4. [tech_journalist_demo-main/orchestration/agents/analyst_agent.py](../../tech_journalist_demo-main/orchestration/agents/analyst_agent.py)
5. [atelier3/agent.py](../../atelier3/agent.py)
6. [WorkerModule/app/modules/agent/service.py](../app/modules/agent/service.py)
7. [WorkerModule/app/routers](../app/routers)

## Build and Test Commands
Run commands from the project you are changing.

Worker:
- docker compose up --build
- python tests/smoke_test.py
- curl http://localhost:8000/health
- curl http://localhost:8000/ready

Tech demo:
- uv sync
- uv run python backend/manage.py migrate
- uv run python scripts/seed_world.py
- uv run python backend/mcp_server/internal_scout.py
- uv run python scripts/mock_analyst.py
- uv run python backend/manage.py runserver 8000

Frontend demo (only if UI changes are requested):
- cd frontend && npm install && npm run dev

## Agentic Logic Mapping (Source -> Worker)
Use explicit mapping in change summaries and PR descriptions.

- Typed graph state and structured handoff:
	[tech_journalist_demo-main/orchestration/contracts.py](../../tech_journalist_demo-main/orchestration/contracts.py)
	-> Worker run state and persistence in [WorkerModule/app/modules/agent/service.py](../app/modules/agent/service.py).

- Orchestrator routing and specialist nodes (triage/scout/analyst/detector/editor):
	[tech_journalist_demo-main/orchestration/langgraph_orchestrator.py](../../tech_journalist_demo-main/orchestration/langgraph_orchestrator.py)
	-> Worker tool-dispatch loop and state transitions in [WorkerModule/app/modules/agent/service.py](../app/modules/agent/service.py).

- Dynamic tool discovery and execution plan (MCP scout):
	[tech_journalist_demo-main/orchestration/agents/scout_agent.py](../../tech_journalist_demo-main/orchestration/agents/scout_agent.py)
	-> Worker tool contracts/registry with policy guards in [WorkerModule/app/modules/agent/service.py](../app/modules/agent/service.py).

- Remote capability handshake before full task dispatch (A2A analyst):
	[tech_journalist_demo-main/orchestration/agents/analyst_agent.py](../../tech_journalist_demo-main/orchestration/agents/analyst_agent.py)
	-> Worker external enrichment gating and fail-safe behavior in [WorkerModule/app/modules/agent/service.py](../app/modules/agent/service.py).

- ReAct format discipline, bounded iteration, memory, and fallback answer/evaluation:
	[atelier3/agent.py](../../atelier3/agent.py)
	-> Worker deterministic fallback path, bounded steps, and tool log transparency in [WorkerModule/app/modules/agent/service.py](../app/modules/agent/service.py).

## Worker Boundary Rules (Do Not Violate)
- Worker is observability, traceability, KPI, integrity, and optimization only.
- Worker must not own lead generation, lead scoring, messaging generation, or campaign execution.
- Preserve canonical event envelope behavior and idempotency semantics.
- Preserve correlation continuity: HTTP header X-Correlation-ID and payload correlation_id.
- Keep SQL execution restricted to AGENT_SQL_ALLOWLIST.

## Common Pitfalls
- Do not bypass action normalization before tool dispatch.
- Do not allow raw model-proposed SQL beyond allowlist.
- Keep run state append-only enough for auditability (tool_log, sent_events, errors).
- Avoid duplicate adapter method names that can silently override real implementations.

## Documentation Links (Link, Do Not Duplicate)
- Worker architecture and boundaries: [WorkerModule/system_context.md](../system_context.md)
- Worker implementation notes: [WorkerModule/summary.md](../summary.md)
- Worker bootstrap and contract overview: [WorkerModule/README.md](../README.md)
- Worker go/no-go checklist: [WorkerModule/docs/phase6-go-no-go-checklist.md](../docs/phase6-go-no-go-checklist.md)
- Demo setup and workflow: [tech_journalist_demo-main/README.md](../../tech_journalist_demo-main/README.md)
- Demo API test runbook: [tech_journalist_demo-main/api_testing_guide.md](../../tech_journalist_demo-main/api_testing_guide.md)