import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from google import genai
from google.genai import types
from openai import AsyncOpenAI

from app.config import settings
from app.modules.agent.evaluator import evaluate_agent_run
from app.modules.agent.rag import AgentKnowledgeBase
from app.modules.worker.storage import get_events_by_correlation_id, save_event, create_events_table
from app.modules.inject import fetch_company_intelligence as _fetch_company_intelligence

logger = logging.getLogger(__name__)


EVENT_SEQUENCE: List[tuple[str, str]] = [
    ("inject", "companies_identified"),
    ("inject", "lead_ingested"),
    ("detective", "lead_scored"),
    ("writer", "message_generated"),
    ("writer", "message_sent"),
    ("worker", "reply_received"),
    ("worker", "conversion"),
]

# Events the agent is allowed to auto-generate. message_sent requires user
# approval, and reply_received / conversion should only come from real
# interactions (webhooks, mailbox scanning, etc.).
AUTO_GEN_SEQUENCE: List[tuple[str, str]] = [
    ("inject", "companies_identified"),
    ("inject", "lead_ingested"),
    ("detective", "personas_identified"),
    ("detective", "lead_scored"),
    ("writer", "message_generated"),
]

# The events that trigger a pause for human approval.
PAUSE_AFTER_EVENTS = {"companies_identified", "personas_identified", "message_generated"}

TOOL_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "generate_and_ingest_event": {
        "description": "Generate canonical event payload and persist it to Worker event storage.",
        "required_fields": [],
        "optional_fields": ["reason"],
    },
    "sql_query": {
        "description": "Execute allowlisted SQL query with optional parameters.",
        "required_fields": ["query"],
        "optional_fields": ["params", "reason"],
    },
    "search_knowledge": {
        "description": "Semantic search over worker domain documentation and event schemas.",
        "required_fields": ["query"],
        "optional_fields": ["reason"],
    },
    "fetch_company_intelligence": {
        "description": "Fetch enriched company intelligence from Neo4j: profile, personas, funding events, and news articles.",
        "required_fields": ["domain"],
        "optional_fields": ["reason"],
    },
    "search_web": {
        "description": "Search the internet for external data, news, or company domains.",
        "required_fields": ["query"],
        "optional_fields": ["reason"],
    },
}


class AgentServiceError(Exception):
    pass


class AgentTimeoutError(AgentServiceError):
    """Raised when an agent run exceeds its wall-clock time limit."""
    pass



class AgentService:
    """LLM-backed agent orchestrator with tool registry and persistent run memory."""

    async def _tool_sql_query(self, query: str, params: Optional[list[Any]] = None) -> Dict[str, Any]:
        """Executes an allowed SQL query with optional parameters."""
        allowlist = set(settings.AGENT_SQL_ALLOWLIST)
        if query not in allowlist:
            raise AgentServiceError(f"Query not allowed: {query}")
        async with self.db_pool.acquire() as connection:
            try:
                rows = await connection.fetch(query, *(params or []))
                return {"status": "ok", "rows": [dict(row) for row in rows]}
            except Exception as exc:
                logger.error(f"SQL tool error: {exc}")
                return {"status": "error", "error": str(exc)}

    # Ordered pipeline: (event_type, module) pairs the agent must emit in sequence.
    _PIPELINE_ORDER: List[tuple[str, str]] = [
        ("companies_identified", "inject"),
        ("lead_ingested",        "inject"),
        ("personas_identified",  "detective"),
        ("lead_scored",          "detective"),
        ("message_generated",    "writer"),
    ]

    def _enforce_pipeline_order(
        self,
        action: Dict[str, Any],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Hard-enforce the pipeline sequence.

        If the LLM proposes generating an event that has already been sent,
        or skips a required event, replace the action with the correct next
        pipeline step.  This is deterministic and cannot be bypassed by the LLM.
        """
        if action.get("tool") != "generate_and_ingest_event":
            return action  # non-event actions are not subject to ordering

        sent_types = {e.get("event_type") for e in state.get("sent_events", [])}

        # Find the next event in the pipeline that hasn't been sent yet
        next_event: Optional[tuple[str, str]] = None
        for et, mod in self._PIPELINE_ORDER:
            if et not in sent_types:
                next_event = (et, mod)
                break

        if next_event is None:
            # All pipeline events sent — agent should finish, not generate more
            logger.info("All pipeline events sent; converting generate action to finish")
            return {"tool": "finish", "reason": "All pipeline events have been sent."}

        required_et, required_mod = next_event
        proposed_et = action.get("event_type", "")

        if proposed_et != required_et:
            logger.warning(
                "Pipeline order violation: agent proposed '%s' but next required is '%s/%s'. Overriding.",
                proposed_et, required_mod, required_et,
            )
            return {
                "tool": "generate_and_ingest_event",
                "module": required_mod,
                "event_type": required_et,
                "reason": f"Pipeline enforced: {required_et} is the next required step.",
            }

        return action  # proposed event is correct

    def _normalize_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Keep tool actions safe; preserve module/event_type chosen by the model."""
        tool = action.get("tool")
        _allowed_modules = {"inject", "detective", "writer", "worker"}
        _allowed_event_types = {et for _, et in EVENT_SEQUENCE}

        # Canonical module for each event type — the LLM sometimes picks the wrong one
        _event_module_map = {
            "companies_identified": "inject",
            "lead_ingested": "inject",
            "personas_identified": "detective",
            "lead_scored": "detective",
            "message_generated": "writer",
            "message_sent": "writer",
        }

        if tool == "generate_and_ingest_event":
            module = action.get("module", "worker")
            event_type = action.get("event_type", "lead_ingested")
            if module not in _allowed_modules:
                module = "worker"
            if event_type not in _allowed_event_types:
                event_type = "lead_ingested"
            # Always enforce the canonical module for the event type
            canonical_module = _event_module_map.get(event_type)
            if canonical_module and module != canonical_module:
                logger.warning(
                    "Correcting module for event_type='%s': '%s' → '%s'",
                    event_type, module, canonical_module,
                )
                module = canonical_module
            return {
                "tool": "generate_and_ingest_event",
                "module": module,
                "event_type": event_type,
                "reason": action.get("reason", "model selected event generation"),
            }

        if tool == "finish":
            return {"tool": "finish", "reason": action.get("reason", "objective complete")}

        if tool == "sql_query":
            query = action.get("query")
            params = action.get("params", [])
            if not isinstance(query, str) or query not in set(settings.AGENT_SQL_ALLOWLIST):
                logger.warning("Model returned disallowed SQL; downgrading to generate_and_ingest_event")
                return {
                    "tool": "generate_and_ingest_event",
                    "module": "worker",
                    "event_type": "lead_ingested",
                    "reason": "downgraded: model proposed disallowed SQL",
                }
            if not isinstance(params, list):
                params = []
            return {
                "tool": "sql_query",
                "query": query,
                "params": params,
                "reason": action.get("reason", "model selected allowlisted SQL"),
            }

        if tool == "search_knowledge":
            query = action.get("query", "")
            return {
                "tool": "search_knowledge",
                "query": str(query),
                "reason": action.get("reason", "model selected semantic search"),
            }

        if tool == "search_web":
            query = action.get("query", "")
            return {
                "tool": "search_web",
                "query": str(query),
                "reason": action.get("reason", "model selected web search"),
            }

        if tool == "fetch_company_intelligence":
            domain = action.get("domain", "")
            if not isinstance(domain, str) or not domain.strip():
                logger.warning("fetch_company_intelligence called with invalid domain; downgrading to generate_and_ingest_event")
                return {
                    "tool": "generate_and_ingest_event",
                    "module": "worker",
                    "event_type": "lead_ingested",
                    "reason": "downgraded: invalid domain for fetch_company_intelligence",
                }
            return {
                "tool": "fetch_company_intelligence",
                "domain": domain.strip(),
                "reason": action.get("reason", "model selected company intelligence fetch"),
            }

        logger.warning("Model returned unsupported tool '%s'; downgrading to generate_and_ingest_event", tool)
        return {
            "tool": "generate_and_ingest_event",
            "module": "worker",
            "event_type": "lead_ingested",
            "reason": "downgraded: unsupported tool",
        }

    def __init__(self, db_pool: Any) -> None:
        self.db_pool = db_pool
        self.model_name = settings.AGENT_MODEL
        self.openai_base_url = settings.OPENAI_BASE_URL.rstrip("/")
        self.openai_model = settings.OPENAI_MODEL
        self.openai_api_key = settings.OPENAI_API_KEY
        self.openai_verify_tls = settings.OPENAI_VERIFY_TLS
        self.generation_config = types.GenerateContentConfig(
            temperature=0.3,
            top_p=1.0,
            max_output_tokens=1024,
            response_mime_type="application/json",
        )
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None
        self._gemini_quota_exhausted = False
        # Initialize OpenAI client once at startup (mirrors working pattern)
        if settings.OPENAI_API_KEY and settings.OPENAI_BASE_URL and settings.OPENAI_MODEL:
            self.openai_client = AsyncOpenAI(
                api_key=self.openai_api_key,
                base_url=self.openai_base_url,
                timeout=8.0,
                max_retries=0,
            )
            logger.info("OpenAI client initialized: base_url=%s model=%s", self.openai_base_url, self.openai_model)
        else:
            self.openai_client = None
            logger.warning("OpenAI fallback not configured (missing key/url/model)")
        self.knowledge_base = AgentKnowledgeBase()
        self.tool_registry = {
            "generate_and_ingest_event": self._execute_generate_and_ingest_event,
            "sql_query": self._execute_sql_query,
            "search_knowledge": self._execute_search_knowledge,
            "fetch_company_intelligence": self._execute_fetch_company_intelligence,
            "search_web": self._execute_search_web,
        }

    def get_tool_contracts(self) -> Dict[str, Dict[str, Any]]:
        return TOOL_CONTRACTS

    def _create_tool_log(
        self,
        *,
        tool: str,
        status: str,
        started_at: datetime,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        finished_at = datetime.now(timezone.utc)
        log_entry: Dict[str, Any] = {
            "tool": tool,
            "status": status,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
        }
        if result is not None:
            log_entry["result"] = result
        if error is not None:
            log_entry["error"] = error
        if metadata:
            log_entry.update(metadata)
        return log_entry

    async def _execute_generate_and_ingest_event(
        self,
        *,
        action: Dict[str, Any],
        correlation_id: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        # module and event_type are now chosen by the model and carried in the action dict
        module = str(action.get("module", "worker"))
        event_type = str(action.get("event_type", "lead_ingested"))
        event = await self._tool_generate_event(
            event_type=event_type,
            module=module,
            correlation_id=correlation_id,
            previous_events=state["sent_events"],
            state=state,
        )
        ingest_res = await self._tool_ingest_event(event)
        return {
            "event": event,
            "log_result": ingest_res,
            "log_metadata": {
                "event_type": event_type,
                "module": module,
            },
        }

    async def _execute_sql_query(
        self,
        *,
        action: Dict[str, Any],
        correlation_id: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        query = action.get("query")
        params = action.get("params", [])
        sql_res = await self._tool_sql_query(query, params)
        return {
            "log_result": sql_res,
            "log_metadata": {
                "query": query,
                "params": params,
            },
        }

    async def _execute_search_knowledge(
        self,
        *,
        action: Dict[str, Any],
        correlation_id: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        if self.knowledge_base.vectorstore is None:
            # Build lazily on first access to avoid synchronous blocking on module load.
            # We use asyncio.to_thread because HuggingFaceEmbeddings might download a model
            # on first use, which takes ~95s and would completely block the event loop.
            await asyncio.to_thread(self.knowledge_base.build)
        
        query = action.get("query", "")
        # Run synchronous FAISS search in a thread so it doesn't block polling endpoints
        result_text = await asyncio.to_thread(self.knowledge_base.search, query)
        
        return {
            "log_result": {"search_results": result_text},
            "log_metadata": {"query": query},
        }

    async def _execute_search_web(
        self,
        *,
        action: Dict[str, Any],
        correlation_id: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        query = action.get("query", "")
        
        def _do_search():
            try:
                from ddgs import DDGS
                results = list(DDGS().text(query, max_results=3))
                return results
            except Exception as e:
                logger.error("Web search failed: %s", e)
                return [{"error": str(e)}]
                
        results = await asyncio.to_thread(_do_search)
        
        return {
            "log_result": {"web_results": results},
            "log_metadata": {"query": query},
        }

    async def _execute_fetch_company_intelligence(
        self,
        *,
        action: Dict[str, Any],
        correlation_id: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        domain = action.get("domain", "")
        started_at = datetime.now(timezone.utc)
        logger.info("fetch_company_intelligence tool starting for domain='%s'", domain)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _fetch_company_intelligence, domain)

        state["company_intelligence"] = result

        personas_count = len(result.get("personas", []))
        funding_count = len(result.get("funding_events", []))
        news_count = len(result.get("news_articles", []))

        duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
        logger.info(
            "fetch_company_intelligence completed for domain='%s': status=%s, %d persona(s), %d funding event(s), %d news article(s), duration=%dms",
            domain, result.get("status"), personas_count, funding_count, news_count, duration_ms,
        )

        return {
            "log_result": result,
            "log_metadata": {
                "domain": domain,
                "personas_count": personas_count,
                "funding_count": funding_count,
                "news_count": news_count,
            },
        }

    async def _dispatch_tool(
        self,
        *,
        action: Dict[str, Any],
        correlation_id: str,
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        tool = action.get("tool")
        if tool not in self.tool_registry:
            raise AgentServiceError(f"Unsupported tool requested by model: {tool}")

        started_at = datetime.now(timezone.utc)
        try:
            execution = await self.tool_registry[tool](
                action=action,
                correlation_id=correlation_id,
                state=state,
            )
            log_entry = self._create_tool_log(
                tool=tool,
                status="ok",
                started_at=started_at,
                result=execution.get("log_result"),
                metadata=execution.get("log_metadata"),
            )
            return {
                "event": execution.get("event"),
                "log_entry": log_entry,
            }
        except Exception as exc:
            log_entry = self._create_tool_log(
                tool=tool or "unknown",
                status="error",
                started_at=started_at,
                error=str(exc),
            )
            state["tool_log"].append(log_entry)
            raise

    def _has_openai_fallback(self) -> bool:
        return bool(self.openai_api_key and self.openai_base_url and self.openai_model)

    def provider_status(self) -> str:
        has_gemini = bool(self.client)
        has_openai = self._has_openai_fallback()

        if has_gemini and has_openai:
            return "gemini_primary_openai_fallback"
        if has_gemini:
            return "gemini_only"
        if has_openai:
            return "openai_only"
        return "deterministic_only"

    async def _openai_generate_json(self, prompt: str, max_tokens: int = 512) -> Dict[str, Any]:
        api_key = os.getenv("OPENAI_API_KEY") or self.openai_api_key
        base_url = os.getenv("OPENAI_BASE_URL") or self.openai_base_url
        model = os.getenv("OPENAI_MODEL") or self.openai_model

        if not api_key or not base_url or not model:
            raise AgentServiceError("OpenAI fallback is not configured")

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            timeout=60.0,
            max_retries=0,
        )

        try:
            logger.info("OpenAI call starting: base_url=%s model=%s max_tokens=%d", base_url, model, max_tokens)
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Return valid JSON exactly, with no markdown fences or preambles."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=max_tokens,
            )
            logger.info("OpenAI call completed successfully")
        except Exception as exc:
            logger.error("OpenAI call failed: %s", exc)
            raise AgentServiceError(f"OpenAI native client failed: {exc}")

        choices = response.choices
        if not choices:
            raise AgentServiceError("OpenAI fallback returned no choices")
        message = choices[0].message
        content = message.content
        if not isinstance(content, str) or not content.strip():
            raise AgentServiceError("OpenAI fallback returned empty content")

        json_text = self._extract_json_object(content)
        return json.loads(json_text)

    async def ensure_tables(self) -> None:
        # Initialize Worker schema tables (events, outcomes, integrity_alerts)
        await create_events_table(self.db_pool)
        
        # Initialize agent_runs table
        query = """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id SERIAL PRIMARY KEY,
            run_id UUID UNIQUE NOT NULL,
            correlation_id UUID NOT NULL,
            objective TEXT NOT NULL,
            status VARCHAR(32) NOT NULL,
            state JSONB NOT NULL,
            created_at TIMESTAMPTZ DEFAULT timezone('utc', now()),
            updated_at TIMESTAMPTZ DEFAULT timezone('utc', now())
        );
        CREATE INDEX IF NOT EXISTS idx_agent_runs_run_id ON agent_runs (run_id);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_correlation_id ON agent_runs (correlation_id);
        """
        async with self.db_pool.acquire() as connection:
            await connection.execute(query)

    async def _load_session_memory(self, correlation_id: str, k: int = 5) -> list[dict]:
        """Load last k scratchpad entries from prior runs for this correlation."""
        query = """
        SELECT state
        FROM agent_runs
        WHERE correlation_id = $1 AND status = 'completed'
        ORDER BY updated_at DESC
        LIMIT $2
        """
        async with self.db_pool.acquire() as conn:
            # We already cast correlation_id to UUID in Postgres string literals if necessary,
            # but asyncpg requires exact types. The DB schema uses UUID type.
            # correlation_id is a string, so we'll let asyncpg handle parsing or explicit cast.
            rows = await conn.fetch(query, correlation_id, k)

        memory = []
        for row in reversed(rows):  # oldest first
            state_data = json.loads(row["state"])
            scratchpad = state_data.get("scratchpad", [])
            # take the last 2 entries from each past run to keep context window reasonable
            if scratchpad:
                memory.extend(scratchpad[-2:])
            
        return memory

    async def run_objective(
        self,
        objective: str,
        correlation_id: Optional[str] = None,
        max_steps: int = 20,
        external_enrichment_url: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        run_id = run_id or str(uuid.uuid4())
        effective_correlation_id = correlation_id or str(uuid.uuid4())
        
        # Load past session memory
        session_memory = await self._load_session_memory(effective_correlation_id)

        state: Dict[str, Any] = {
            "run_id": run_id,
            "objective": objective,
            "correlation_id": effective_correlation_id,
            "step": 0,
            "status": "running",
            "sent_events": [],
            "tool_log": [],
            "scratchpad": session_memory,
            "errors": [],
            "external_context": {},
        }

        await self._upsert_run(state)
        return await self._execute_agent_loop(state, max_steps, external_enrichment_url)

    async def _execute_agent_loop(self, state: Dict[str, Any], max_steps: int, external_enrichment_url: Optional[str] = None) -> Dict[str, Any]:
        run_id = state["run_id"]
        effective_correlation_id = state["correlation_id"]
        objective = state["objective"]

        try:
            # Wall-clock guard: ensures the endpoint always returns within 600 s.
            async with asyncio.timeout(600):
                if external_enrichment_url and not state.get("external_context"):
                    enrich_res = await self._tool_external_api_call(external_enrichment_url)
                    state["external_context"] = enrich_res
                    state["tool_log"].append({"tool": "external_api_call", "result": enrich_res})

                # Dynamic ReAct loop: Thought -> Action -> Observation
                while state["step"] < max_steps:
                    logger.info("Agent step %d/%d starting", state["step"] + 1, max_steps)
                    thought, action = await self._react_think(
                        objective=objective,
                        state=state,
                    )

                    if action.get("tool") == "finish":
                        logger.info(
                            "Agent declared objective complete at step %d (reason: %s)",
                            state["step"],
                            action.get("reason", ""),
                        )
                        state["scratchpad"].append({
                            "thought": thought,
                            "action": action,
                            "observation": "Objective completed."
                        })
                        break

                    execution = await self._dispatch_tool(
                        action=action,
                        correlation_id=effective_correlation_id,
                        state=state,
                    )
                    event = execution.get("event")
                    if event:
                        state["sent_events"].append(event)
                    
                    log_entry = execution["log_entry"]
                    state["tool_log"].append(log_entry)
                    
                    # Define observation for the scratchpad
                    obs_data = log_entry.get("result") if log_entry.get("status") == "ok" else log_entry.get("error")
                    observation = json.dumps(obs_data, default=str)
                    
                    state["scratchpad"].append({
                        "thought": thought,
                        "action": action,
                        "observation": observation,
                    })

                    state["step"] += 1
                    await self._upsert_run(state)

                    # --- Human-in-the-loop gate ---
                    # If we just generated an event that requires human approval/interaction
                    if event and event.get("event_type") in PAUSE_AFTER_EVENTS:
                        event_type = event.get("event_type")
                        logger.info(
                            "Pipeline paused after %s — awaiting user approval",
                            event_type,
                        )
                        state["status"] = "awaiting_approval"
                        state["scratchpad"].append({
                            "thought": f"{event_type} generated. Pausing for human review.",
                            "action": {"tool": "pause", "reason": f"Awaiting user interaction for {event_type}"},
                            "observation": f"Pipeline paused. User must interact to continue.",
                        })
                        await self._upsert_run(state)
                        return {
                            "run_id": run_id,
                            "correlation_id": effective_correlation_id,
                            "status": "awaiting_approval",
                            "events_sent": len(state["sent_events"]),
                            "tool_log": state["tool_log"],
                        }

                trace = await self._tool_query_trace(effective_correlation_id)
                state["tool_log"].append({"tool": "query_trace", "result": {"count": len(trace)}})
                state["status"] = "completed"
                
                # Evaluate the run before returning
                if self.client or self.openai_client:
                    evaluation_result = await evaluate_agent_run(
                        client=self.client if not self._gemini_quota_exhausted else None,
                        model_name=self.model_name,
                        generation_config=self.generation_config,
                        objective=objective,
                        state=state,
                        openai_client=self.openai_client,
                        openai_model=self.openai_model,
                    )
                    state["evaluation"] = evaluation_result

                await self._upsert_run(state)

                return {
                    "run_id": run_id,
                    "correlation_id": effective_correlation_id,
                    "status": "completed",
                    "events_sent": len(state["sent_events"]),
                    "trace_events": len(trace),
                    "tool_log": state["tool_log"],
                    "evaluation": state.get("evaluation", {"status": "skipped"}),
                }

        except asyncio.TimeoutError:
            state["status"] = "failed"
            state["errors"].append("Agent run exceeded 600s wall-clock timeout")
            await self._upsert_run(state)
            raise AgentTimeoutError("Agent run exceeded time limit (600s); partial results saved.")
        except AgentServiceError:
            raise
        except Exception as exc:
            logger.exception("Agent run failed: %s", exc)
            state["status"] = "failed"
            state["errors"].append(str(exc))
            await self._upsert_run(state)
            raise

    async def resume_run(self, run_id: str, action_type: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Resume a paused run based on user interaction."""
        run = await self.get_run(run_id)
        if not run:
            raise AgentServiceError(f"Run {run_id} not found")

        state_raw = run.get("state")
        if isinstance(state_raw, str):
            state = json.loads(state_raw)
        else:
            state = state_raw or {}

        if state.get("status") != "awaiting_approval":
            raise AgentServiceError(
                f"Run {run_id} is not awaiting approval (status: {state.get('status')})"
            )

        if action_type == "approve_message":
            return await self._handle_message_approval(state)
        elif action_type == "select_companies":
            return await self._handle_company_selection(state, payload)
        elif action_type == "select_personas":
            return await self._handle_persona_selection(state, payload)
        else:
            raise AgentServiceError(f"Unknown action_type: {action_type}")

    async def _handle_message_approval(self, state: Dict[str, Any]) -> Dict[str, Any]:
        run_id = state["run_id"]
        correlation_id = state["correlation_id"]

        # Generate and persist message_sent event
        event = await self._tool_generate_event(
            event_type="message_sent",
            module="writer",
            correlation_id=correlation_id,
            previous_events=state["sent_events"],
            state=state,
        )
        await self._tool_ingest_event(event)
        state["sent_events"].append(event)
        state["step"] += 1

        state["scratchpad"].append({
            "thought": "User approved the generated message. Proceeding to send.",
            "action": {"tool": "generate_and_ingest_event", "module": "writer", "event_type": "message_sent", "reason": "User approved sending"},
            "observation": json.dumps({"status": "accepted", "event_id": str(event["event_id"])}, default=str),
        })

        state["status"] = "completed"
        state["tool_log"].append({
            "tool": "generate_and_ingest_event",
            "status": "ok",
            "event_type": "message_sent",
            "module": "writer",
        })

        # Run evaluation
        if self.client or self.openai_client:
            try:
                from app.modules.agent.evaluator import evaluate_agent_run
                evaluation_result = await evaluate_agent_run(
                    client=self.client if not self._gemini_quota_exhausted else None,
                    model_name=self.model_name,
                    generation_config=self.generation_config,
                    objective=state["objective"],
                    state=state,
                    openai_client=self.openai_client,
                    openai_model=self.openai_model,
                )
                state["evaluation"] = evaluation_result
            except Exception as exc:
                logger.warning("Evaluation failed after approval: %s", exc)

        await self._upsert_run(state)

        return {
            "run_id": run_id,
            "correlation_id": correlation_id,
            "status": "completed",
            "events_sent": len(state["sent_events"]),
        }

    async def _handle_company_selection(self, state: Dict[str, Any], payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        selected = payload.get("selected_companies", []) if payload else []

        # Store selected companies in state so the agent can reference them
        # after resuming. Each entry may be a string (name) or a dict with
        # name/domain — normalise to dicts so the agent has domains to fetch.
        companies_event = next(
            (e for e in reversed(state.get("sent_events", []))
             if e.get("event_type") == "companies_identified"),
            None,
        )
        all_companies: List[Dict[str, Any]] = []
        if companies_event:
            all_companies = companies_event.get("payload", {}).get("companies", [])

        # Build a lookup: name → company dict
        name_to_company: Dict[str, Dict[str, Any]] = {}
        for c in all_companies:
            if isinstance(c, dict):
                name_to_company[c.get("name", "")] = c
            elif isinstance(c, str):
                name_to_company[c] = {"name": c}

        selected_details: List[Dict[str, Any]] = []
        for s in selected:
            if isinstance(s, dict):
                selected_details.append(s)
            else:
                selected_details.append(name_to_company.get(s, {"name": s}))

        state["selected_companies"] = selected_details
        state["status"] = "running"
        state["scratchpad"].append({
            "thought": "User has selected the target companies to focus on.",
            "action": {"tool": "resume", "reason": "User provided company selection"},
            "observation": (
                f"User selected {len(selected_details)} company/companies to proceed with: "
                + json.dumps(selected_details, default=str)
            ),
        })
        await self._upsert_run(state)

        # Resume the agent loop
        return await self._execute_agent_loop(state, 20)

    async def _handle_persona_selection(self, state: Dict[str, Any], payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        selected = payload.get("selected_personas", []) if payload else []

        # Resolve full persona dicts from the personas_identified event payload
        personas_event = next(
            (e for e in reversed(state.get("sent_events", []))
             if e.get("event_type") == "personas_identified"),
            None,
        )
        all_personas: List[Dict[str, Any]] = []
        if personas_event:
            all_personas = personas_event.get("payload", {}).get("personas", [])

        name_to_persona: Dict[str, Dict[str, Any]] = {
            p.get("full_name", ""): p for p in all_personas if isinstance(p, dict)
        }

        # FIX: If user selected none but personas exist, auto-select all
        if not selected and all_personas:
            logger.info("No personas selected by user — auto-selecting all %d available personas", len(all_personas))
            selected_details = list(all_personas)
        else:
            selected_details: List[Dict[str, Any]] = []
            for s in selected:
                if isinstance(s, dict):
                    selected_details.append(s)
                else:
                    selected_details.append(name_to_persona.get(s, {"full_name": s}))

        state["selected_personas"] = selected_details
        state["status"] = "running"
        state["scratchpad"].append({
            "thought": "User has selected the target personas to contact." if selected else "No specific personas selected — using all available personas.",
            "action": {"tool": "resume", "reason": "User provided persona selection"},
            "observation": (
                f"Proceeding with {len(selected_details)} persona(s) to contact: "
                + json.dumps(selected_details, default=str)
            ),
        })
        await self._upsert_run(state)

        return await self._execute_agent_loop(state, 20)

    async def list_runs(self, limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
        bounded_limit = max(1, min(limit, 200))
        params: List[Any] = []
        where_clause = ""

        if status:
            params.append(status)
            where_clause = f"WHERE status = ${len(params)}"

        params.append(bounded_limit)
        query = f"""
        SELECT run_id, correlation_id, objective, status, created_at, updated_at
        FROM agent_runs
        {where_clause}
        ORDER BY updated_at DESC
        LIMIT ${len(params)};
        """

        async with self.db_pool.acquire() as connection:
            rows = await connection.fetch(query, *params)
            return [dict(row) for row in rows]

    async def cleanup_runs(self, older_than_days: Optional[int] = None) -> int:
        retention_days = older_than_days or settings.AGENT_RUN_RETENTION_DAYS
        retention_days = max(1, retention_days)
        query = """
        DELETE FROM agent_runs
        WHERE updated_at < timezone('utc', now()) - ($1::int * interval '1 day');
        """
        async with self.db_pool.acquire() as connection:
            result = await connection.execute(query, retention_days)
            return int(result.split(" ")[-1])

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        query = """
        SELECT run_id, correlation_id, objective, status, state, created_at, updated_at
        FROM agent_runs
        WHERE run_id = $1;
        """
        async with self.db_pool.acquire() as connection:
            row = await connection.fetchrow(query, run_id)
            if not row:
                return None
            result = dict(row)
            state_value = result.get("state")
            if isinstance(state_value, str):
                try:
                    result["state"] = json.loads(state_value)
                except json.JSONDecodeError:
                    logger.warning("Unable to decode run state for run_id=%s", run_id)
            return result

    async def _upsert_run(self, state: Dict[str, Any]) -> None:
        query = """
        INSERT INTO agent_runs (run_id, correlation_id, objective, status, state, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5::jsonb, timezone('utc', now()), timezone('utc', now()))
        ON CONFLICT (run_id)
        DO UPDATE SET
            status = EXCLUDED.status,
            state = EXCLUDED.state,
            updated_at = timezone('utc', now());
        """
        async with self.db_pool.acquire() as connection:
            await connection.execute(
                query,
                state["run_id"],
                state["correlation_id"],
                state["objective"],
                state["status"],
                json.dumps(state, default=str),
            )

    async def _react_think(
        self,
        objective: str,
        state: Dict[str, Any],
    ) -> tuple[str, Dict[str, Any]]:
        """Ask model to explicitly print a thought and freely choose the next action; fallback: Gemini -> OpenAI -> deterministic."""
        allowed_tools = ["generate_and_ingest_event", "sql_query", "search_knowledge", "search_web", "fetch_company_intelligence", "finish"]
        allowed_modules = ["inject", "detective", "writer", "worker"]
        # Only allow auto-generatable event types — message_sent, reply_received,
        # and conversion require human action and should not be auto-generated.
        allowed_event_types = [et for _, et in AUTO_GEN_SEQUENCE]

        sent_summary = [
            f"{e.get('module')}/{e.get('event_type')}" for e in state.get("sent_events", [])
        ]

        # Determine the next required pipeline event so the agent has no ambiguity
        sent_event_types = {e.get("event_type") for e in state.get("sent_events", [])}
        next_pipeline_step = ""
        if "companies_identified" not in sent_event_types:
            next_pipeline_step = "Next required event: inject/companies_identified"
        elif "lead_ingested" not in sent_event_types:
            next_pipeline_step = "Next required event: inject/lead_ingested  (one per selected company)"
        elif "personas_identified" not in sent_event_types:
            next_pipeline_step = "Next required event: detective/personas_identified  ← USE MODULE='detective'"
        elif "lead_scored" not in sent_event_types:
            next_pipeline_step = "Next required event: detective/lead_scored  ← USE MODULE='detective'"
        elif "message_generated" not in sent_event_types:
            next_pipeline_step = "Next required event: writer/message_generated  ← USE MODULE='writer'"

        # Surface selected companies explicitly so the agent knows what to work on
        selected_companies = state.get("selected_companies", [])
        selected_companies_text = ""
        if selected_companies:
            selected_companies_text = (
                f"\nUser-selected companies to process: {json.dumps(selected_companies, default=str)}\n"
                "You MUST fetch intelligence for each of these companies and generate lead_ingested events for them.\n"
            )

        # Surface selected personas so the agent knows who to message
        selected_personas = state.get("selected_personas", [])
        selected_personas_text = ""
        if selected_personas:
            selected_personas_text = (
                f"\nUser-selected personas to contact: {json.dumps(selected_personas, default=str)}\n"
                "Generate lead_scored, then message_generated with per-persona per-channel messages.\n"
            )

        scratchpad_text = json.dumps(state.get("scratchpad", []), indent=2, default=str)

        prompt = f"""
You are an AI outbound agent orchestrator using a ReAct (Reasoning and Acting) loop.

Objective: {objective}
Step: {state['step']}
Events sent so far: {sent_summary or 'none'}
{next_pipeline_step}
{selected_companies_text}{selected_personas_text}
Scratchpad (History of Thoughts, Actions, and Observations):
{scratchpad_text}

Think about the objective, the current scratchpad, and what you need to do next. Then pick ONE tool.
If the objective is fully achieved (all necessary events have been sent), use the "finish" tool.
Allowed tools: {allowed_tools}
Allowed modules: {allowed_modules}
Allowed event_types: {allowed_event_types}

MANDATORY PIPELINE — you MUST complete ALL steps in order. Do NOT call "finish" until step 7 is done.

PIPELINE EVENT → MODULE MAPPING (CRITICAL — always use the correct module):
  companies_identified  → module: "inject"
  lead_ingested         → module: "inject"
  personas_identified   → module: "detective"   ← NEVER use "inject" for this
  lead_scored           → module: "detective"
  message_generated     → module: "writer"

STEP 1 — DISCOVERY (if companies_identified NOT yet sent):
  - Search the web for companies matching the objective
  - Generate companies_identified event with ALL companies found as a "companies" array (name + domain per entry)
  - Extract domains from article CONTENT (e.g. "Sennder raised funding" → sennder.com), NOT from the article site itself
  - Pipeline pauses here for user to select companies

STEP 2 — ENRICHMENT (after user selects companies, companies_identified IS sent, lead_ingested NOT yet sent):
  - For EACH company in "User-selected companies": call fetch_company_intelligence with its domain
  - Then generate ONE lead_ingested event per selected company
  - Do NOT generate a second companies_identified event

STEP 3 — PERSONAS (after all lead_ingested sent, personas_identified NOT yet sent):
  - Generate personas_identified event
  - Payload MUST be {{"personas": [{{"full_name": "...", "title": "...", "email": "...", "linkedin_url": "...", "company_domain": "..."}}]}}
  - Use personas from the fetch_company_intelligence observations in the scratchpad
  - Pipeline pauses here for user to select personas

STEP 4 — SCORING (after user selects personas, personas_identified IS sent, lead_scored NOT yet sent):
  - Generate lead_scored event with a score and reasoning based on the selected companies and personas

STEP 5 — MESSAGES (after lead_scored sent, message_generated NOT yet sent):
  - Generate message_generated event
  - Payload MUST be {{"messages": [{{"persona_name": "...", "company": "...", "channel": "email", "subject": "...", "body": "..."}}, {{"persona_name": "...", "company": "...", "channel": "linkedin", "body": "..."}}]}}
  - Generate one email + one LinkedIn message per selected persona
  - Pipeline pauses here for user to approve

STEP 6 — SEND (after user approves message_generated):
  - message_sent is generated automatically by the system — you do NOT need to generate it

STEP 7 — FINISH: Only call "finish" after message_generated has been sent AND the user has approved it (message_sent will appear in sent events).

CURRENT PIPELINE STATE — check "Events sent so far" and follow the correct step above.

Response shape MUST be EXACTLY ONE JSON object matching one of the following tool forms:

For generate_and_ingest_event:
{{
  "thought": "step-by-step reasoning about why this event is next",
  "tool": "generate_and_ingest_event",
  "module": "<one of {allowed_modules}>",
  "event_type": "<one of {allowed_event_types}>",
  "reason": "short explanation for auditing"
}}

For sql_query:
{{
  "thought": "step-by-step reasoning about why we need to query data",
  "tool": "sql_query",
  "query": "<MUST be one of the allowed queries listed below>",
  "params": [...],
  "reason": "short explanation for auditing"
}}

Allowed SQL queries (use EXACTLY as written):
{json.dumps(settings.AGENT_SQL_ALLOWLIST, indent=2)}

For search_knowledge:
{{
  "thought": "step-by-step reasoning about why semantic search is needed",
  "tool": "search_knowledge",
  "query": "search terms or question",
  "reason": "short explanation for auditing"
}}

For search_web:
{{
  "thought": "step-by-step reasoning about why searching the public internet is needed (e.g. to find domains)",
  "tool": "search_web",
  "query": "search terms for duckduckgo",
  "reason": "short explanation for auditing"
}}

For fetch_company_intelligence:
{{
  "thought": "step-by-step reasoning about why company intelligence is needed",
  "tool": "fetch_company_intelligence",
  "domain": "company domain (e.g. tesla.com)",
  "reason": "short explanation for auditing"
}}

For finish:
{{
  "thought": "reasoning confirming that the objective is fully met",
  "tool": "finish",
  "reason": "summary of what was accomplished"
}}
"""

        if self.client and not self._gemini_quota_exhausted:
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=self.generation_config,
                )
                text = self._extract_json_object(response.text or "{}")
                parsed = json.loads(text)
                if "tool" not in parsed:
                    raise ValueError("Model response missing tool field")
                thought = parsed.get("thought", "Implicit thought step completed.")
                return thought, self._enforce_pipeline_order(self._normalize_action(parsed), state)
            except Exception as exc:
                if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                    logger.warning("Gemini quota exhausted, switching to OpenAI for this run.")
                    self._gemini_quota_exhausted = True
                else:
                    logger.warning("Gemini reasoning failed, trying OpenAI fallback: %s", exc)

        if self._has_openai_fallback():
            try:
                parsed = await self._openai_generate_json(prompt, max_tokens=512)
                if "tool" not in parsed:
                    raise ValueError("OpenAI fallback response missing tool field")
                thought = parsed.get("thought", "Implicit thought step completed.")
                return thought, self._enforce_pipeline_order(self._normalize_action(parsed), state)
            except Exception as exc:
                logger.warning("OpenAI reasoning fallback failed, using deterministic action: %s", exc)

        # Deterministic fallback: cycle through AUTO_GEN_SEQUENCE only
        # (excludes message_sent, reply_received, conversion — those require human action).
        sent_types = {e.get("event_type") for e in state.get("sent_events", [])}
        for fb_module, fb_event_type in AUTO_GEN_SEQUENCE:
            if fb_event_type not in sent_types:
                action = {
                    "tool": "generate_and_ingest_event",
                    "module": fb_module,
                    "event_type": fb_event_type,
                    "reason": f"Fallback: cycling through canonical sequence ({fb_event_type}).",
                }
                return f"Fallback thought: need to ingest {fb_event_type}", action

        # All auto-gen event types covered — declare done.
        return "Fallback thought: all steps complete.", {"tool": "finish", "reason": "Fallback: all auto-generatable event types sent."}

    async def _tool_generate_event(
        self,
        event_type: str,
        module: str,
        correlation_id: str,
        previous_events: List[Dict[str, Any]],
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = await self._generate_payload(event_type, correlation_id, module, previous_events, scratchpad=state.get("scratchpad") if state else None, state=state)

        # For companies_identified: ensure the payload has a non-empty "companies"
        # array built from real search results extracted from the scratchpad.
        if event_type == "companies_identified" and state is not None:
            companies = payload.get("companies")
            if not isinstance(companies, list) or len(companies) == 0:
                # Build the list from fetch_company_intelligence actions in the scratchpad
                scratchpad = state.get("scratchpad", [])
                seen_domains: set = set()
                companies = []
                for entry in scratchpad:
                    action = entry.get("action", {})
                    if isinstance(action, dict) and action.get("tool") == "fetch_company_intelligence":
                        domain = action.get("domain", "")
                        if domain and domain not in seen_domains:
                            seen_domains.add(domain)
                            name = domain.split(".")[0].capitalize()
                            companies.append({"name": name, "domain": domain})
                if companies:
                    payload["companies"] = companies

        # For personas_identified: build the personas list from all intelligence fetched
        if event_type == "personas_identified" and state is not None:
            personas = payload.get("personas")
            if not isinstance(personas, list) or len(personas) == 0:
                # Collect personas from all company_intelligence stored across the run
                all_personas: List[Dict[str, Any]] = []
                scratchpad = state.get("scratchpad", [])
                for entry in scratchpad:
                    action = entry.get("action", {})
                    if isinstance(action, dict) and action.get("tool") == "fetch_company_intelligence":
                        domain = action.get("domain", "")
                        # Try to parse the observation for personas
                        try:
                            obs = json.loads(entry.get("observation", "{}"))
                            for p in obs.get("personas", []):
                                p_copy = dict(p)
                                p_copy["company_domain"] = domain
                                all_personas.append(p_copy)
                        except Exception:
                            pass
                # Also check current company_intelligence in state
                # FIX: Accept both "ok" and "not_found" — live discovery returns
                # personas even when the company profile came from web, not Neo4j
                intel = state.get("company_intelligence", {})
                if intel.get("status") in ("ok", "not_found"):
                    for p in intel.get("personas", []):
                        p_copy = dict(p)
                        p_copy["company_domain"] = intel.get("company_profile", {}).get("domain", "")
                        all_personas.append(p_copy)
                if all_personas:
                    payload["personas"] = all_personas

        # Enrich lead_ingested payload with company intelligence summary if available
        if event_type == "lead_ingested" and state is not None:
            intelligence = state.get("company_intelligence")
            if intelligence and intelligence.get("status") == "ok":
                payload["intelligence_summary"] = self._build_intelligence_summary(intelligence)
                # Also surface the company name/domain from intelligence
                profile = intelligence.get("company_profile", {})
                if profile.get("name") and "company" not in payload:
                    payload["company"] = profile["name"]

        metadata: Dict[str, Any] = {"tenant_id": "tenant-123", "agent_generated": True}

        # Add personas count to metadata if intelligence available
        if event_type == "lead_ingested" and state is not None:
            intelligence = state.get("company_intelligence")
            if intelligence and intelligence.get("status") == "ok":
                metadata["personas_count"] = len(intelligence.get("personas", []))

        return {
            "event_id": uuid.uuid4(),
            "correlation_id": uuid.UUID(correlation_id),
            "module": module,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc),
            "payload": payload,
            "metadata": metadata,
        }

    async def _tool_ingest_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        await save_event(self.db_pool, event)
        return {"status": "accepted", "event_id": event["event_id"]}

    async def _tool_query_trace(self, correlation_id: str) -> List[Dict[str, Any]]:
        return await get_events_by_correlation_id(self.db_pool, correlation_id)

    async def _tool_external_api_call(self, url: str) -> Dict[str, Any]:
        timeout = httpx.Timeout(10.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                body: Any = resp.json()
            else:
                body = {"text": resp.text[:500]}
            return {"status": resp.status_code, "url": url, "body": body}

    async def _generate_payload(
        self,
        event_type: str,
        correlation_id: str,
        module: str,
        previous_events: List[Dict[str, Any]],
        scratchpad: Optional[List[Dict[str, Any]]] = None,
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # Extract web search observations from the scratchpad so the LLM can use
        # real company names/domains instead of inventing fictional ones.
        search_context = ""
        intelligence_context = ""
        if scratchpad:
            web_observations = [
                entry.get("observation", "")
                for entry in scratchpad
                if isinstance(entry.get("action"), dict)
                and entry["action"].get("tool") == "search_web"
            ]
            if web_observations:
                search_context = f"\nWeb search results from this session (use these for real company data):\n{chr(10).join(web_observations[-3:])}\n"

            # Also extract company intelligence observations
            intel_entries = [
                (entry["action"].get("domain", ""), entry.get("observation", ""))
                for entry in scratchpad
                if isinstance(entry.get("action"), dict)
                and entry["action"].get("tool") == "fetch_company_intelligence"
            ]
            if intel_entries:
                intel_lines = []
                for domain, obs in intel_entries[-5:]:
                    try:
                        obs_data = json.loads(obs)
                        personas = obs_data.get("personas", [])
                        persona_summaries = [
                            f"  - {p.get('full_name', '')} | {p.get('title', '')} | {p.get('email', '')} | {p.get('linkedin_url', '')}"
                            for p in personas
                        ]
                        persona_block = "\n".join(persona_summaries) if persona_summaries else "  (no personas)"
                        intel_lines.append(f"- {domain} personas:\n{persona_block}")
                    except Exception:
                        intel_lines.append(f"- {domain}: {obs[:300]}")
                intelligence_context = f"\nCompany intelligence fetched this session:\n{chr(10).join(intel_lines)}\n"

        companies_rule = ""
        if event_type == "companies_identified":
            companies_rule = (
                '\nCRITICAL: For companies_identified, the payload MUST be a JSON object with a "companies" key '
                'containing an array of objects. Each object must have at minimum: "name" (string) and "domain" (string). '
                'Use ONLY real companies found in the search results and intelligence above. Example structure:\n'
                '{"companies": [{"name": "Sennder", "domain": "sennder.com", "industry": "Logistics", "funding": "Series D"}, ...]}'
            )
        if event_type == "personas_identified":
            companies_rule = (
                '\nCRITICAL: For personas_identified, the payload MUST be a JSON object with a "personas" key '
                'containing an array of objects. Each object must have: "full_name", "title", "company_domain". '
                'Include "email" and "linkedin_url" if available from intelligence. '
                'Use ONLY real personas from the company intelligence fetched above. Example structure:\n'
                '{"personas": [{"full_name": "Anna Müller", "title": "VP Sales", "email": "a.mueller@sennder.com", "linkedin_url": "https://linkedin.com/in/anna", "company_domain": "sennder.com"}, ...]}'
            )
        if event_type == "message_generated":
            selected_personas_ctx = state.get("selected_personas", []) if state else []
            # FIX: Fallback — if no personas were selected, use all from personas_identified
            if not selected_personas_ctx and state:
                p_evt = next(
                    (e for e in reversed(state.get("sent_events", []))
                     if e.get("event_type") == "personas_identified"),
                    None,
                )
                if p_evt:
                    selected_personas_ctx = p_evt.get("payload", {}).get("personas", [])
                    logger.info("message_generated: using %d personas from personas_identified event (fallback)", len(selected_personas_ctx))
            if selected_personas_ctx:
                companies_rule = (
                    f'\nCRITICAL: For message_generated, generate personalised outreach messages for EACH of these personas: '
                    f'{json.dumps(selected_personas_ctx, default=str)}. '
                    'The payload MUST be: {"messages": [{"persona_name": "...", "company": "...", "channel": "email", "subject": "...", "body": "..."}, '
                    '{"persona_name": "...", "company": "...", "channel": "linkedin", "body": "..."}]}. '
                    'Make each message specific to the persona\'s title and company. Keep email body under 150 words, LinkedIn under 80 words.'
                )
        prompt = f"""
You generate strictly valid JSON for event payloads.
Event type: {event_type}
Correlation id: {correlation_id}
Module: {module}
Previous events count: {len(previous_events)}
{search_context}{intelligence_context}{companies_rule}
Rules:
- Return JSON object only.
- Use double-quoted keys and strings.
- Keep payload concise and realistic.
- If web search results are provided above, use REAL company names and domains from those results. Do NOT invent fictional companies.
"""

        if self.client and not self._gemini_quota_exhausted:
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=self.generation_config,
                )
                json_text = self._extract_json_object(response.text or "{}")
                return json.loads(json_text)
            except Exception as exc:
                if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                    logger.warning("Gemini quota exhausted during payload generation, switching to OpenAI.")
                    self._gemini_quota_exhausted = True
                else:
                    logger.warning("Gemini payload generation failed for %s, trying OpenAI fallback: %s", event_type, exc)

        if self._has_openai_fallback():
            try:
                return await self._openai_generate_json(prompt, max_tokens=400)
            except Exception as exc:
                logger.warning("OpenAI payload fallback failed for %s: %s", event_type, exc)

        return self._fallback_payload(event_type)

    @staticmethod
    def _extract_json_object(text: str) -> str:
        cleaned = text.strip().replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{[\s\S]*\}", cleaned)
        return match.group(0) if match else cleaned

    @staticmethod
    def _build_intelligence_summary(intelligence: Dict[str, Any]) -> Dict[str, Any]:
        """Build a concise intelligence summary for event payload enrichment."""
        profile = intelligence.get("company_profile", {})
        funding_events = intelligence.get("funding_events", [])
        news_articles = intelligence.get("news_articles", [])
        personas = intelligence.get("personas", [])

        # Most recent funding event by date
        recent_funding = None
        if funding_events:
            valid_funding = [f for f in funding_events if f.get("date") and f.get("date") != "Non renseigné"]
            if valid_funding:
                recent_funding = max(valid_funding, key=lambda f: f.get("date", ""))
            else:
                recent_funding = funding_events[0] if funding_events else None

        # Most recent news article by date
        recent_news = None
        if news_articles:
            valid_news = [n for n in news_articles if n.get("date") and n.get("date") != "Non renseigné"]
            if valid_news:
                recent_news = max(valid_news, key=lambda n: n.get("date", ""))
            else:
                recent_news = news_articles[0] if news_articles else None

        return {
            "company_name": profile.get("name"),
            "industry": profile.get("industry"),
            "employee_count": profile.get("estimated_num_employees"),
            "recent_funding": recent_funding,
            "recent_news": recent_news,
            "personas_count": len(personas),
        }

    @staticmethod
    def _fallback_payload(event_type: str) -> Dict[str, Any]:
        defaults: Dict[str, Dict[str, Any]] = {
            "lead_ingested": {
                "company": "Acme Robotics",
                "contact": {"name": "Sam Carter", "email": "sam.carter@acme.io"},
            },
            "companies_identified": {
                "companies": [
                    {"name": "Sennder", "domain": "sennder.com", "industry": "Logistics"},
                    {"name": "Forto", "domain": "forto.com", "industry": "Logistics"},
                ]
            },
            "personas_identified": {
                "personas": [
                    {"full_name": "Anna Müller", "title": "VP Sales", "email": "a.mueller@example.com", "linkedin_url": "", "company_domain": "example.com"},
                    {"full_name": "Thomas Becker", "title": "Head of Operations", "email": "t.becker@example.com", "linkedin_url": "", "company_domain": "example.com"},
                ]
            },
            "lead_scored": {"score": 78, "reason": "good fit and active hiring"},
            "message_generated": {"messages": [
                {"persona_name": "Anna Müller", "company": "Acme Robotics", "channel": "email", "subject": "Quick idea for Acme Robotics", "body": "Hi Anna, can we share a 15-min workflow demo? Would love to show you what we've built."},
                {"persona_name": "Anna Müller", "company": "Acme Robotics", "channel": "linkedin", "body": "Hi Anna, I'd love to connect and share a quick idea that could help your team at Acme Robotics."},
            ]},
            "message_sent": {"channel": "email", "status": "sent"},
            "reply_received": {"sentiment": "neutral", "message": "Interested, send details."},
            "conversion": {"outcome": "demo booked", "date": datetime.now(timezone.utc).date().isoformat()},
        }
        return defaults.get(event_type, {"note": "fallback payload"})
