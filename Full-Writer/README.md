# Full-Writer

Two independent modules for B2B outreach automation.

| Module | What it does | Entry point |
|---|---|---|
| `ai-outreach-writer-module-master` | Multi-agent pipeline that writes, validates, and sends personalised outreach messages | FastAPI on port 8003 |
| `prospect_strategy_engine` | Finds a decision-maker for a domain, researches them, and generates a sequenced contact plan | Streamlit UI or Temporal worker |

The two modules are designed to work together: the Strategy Engine calls the Writer's MCP endpoint to generate the actual message after it has built the contact plan.

---

## ai-outreach-writer-module-master

### How it works

A request arrives with a prospect, channel, offer, and sender personality. Five agents run in sequence inside a LangGraph pipeline:

```
Planner → Researcher → Strategist → Writer → Critic
                                         ↑         |
                                         └─REVISING─┘
```

1. **Planner** — inspects state and decides the next step; no LLM call, pure routing logic
2. **Researcher** — loads prospect memory, hard-stops on `do_not_contact`, fetches LinkedIn posts / company news / CRM history (mock by default; real Detective enrichment data used when provided)
3. **Strategist** — two Gemini calls: pick the best hook from signals, then build a full strategy; avoids hooks and angles already used with this prospect
4. **Writer** — one Gemini call to write the message; supports revision mode where it receives the previous draft and specific feedback; hard-trims output if the LLM overshoots the character limit
5. **Critic** — deterministic rule checks first (length, banned phrases, placeholder text, attachment references), then one Gemini call to score 0–100; loops back to Writer with feedback if the message fails

If `ENABLE_HUMAN_REVIEW=true`, the pipeline pauses after the Critic approves and waits for a human decision before sending.

### Project structure

```
ai-outreach-writer-module-master/
├── app/
│   ├── main.py          # FastAPI endpoints + human review routes + MCP SSE mount
│   ├── models.py        # All Pydantic models and enums
│   ├── config.py        # Settings from .env; supports hot-reload from Worker module
│   ├── agents.py        # Agent logic: Planner, Researcher, Strategist, Writer, Critic
│   ├── orchestrator.py  # Builds initial AgentState, delegates to LangGraph
│   ├── graph.py         # LangGraph StateGraph — wires agents and conditional routing
│   ├── llm_service.py   # All Gemini calls: retry, fallback model, json5 parsing
│   ├── tools.py         # Research tools (mock + Detective enrichment integration)
│   ├── memory.py        # Per-prospect + global learning memory (Redis or in-memory)
│   ├── send_tools.py    # Email (Gmail SMTP) and LinkedIn (Unipile) sending
│   ├── event_emitter.py # Publishes message_generated / message_sent events to Redis
│   ├── subscriber.py    # Redis subscriber for hot-reloading config from Worker
│   └── mcp_server.py    # MCP server exposing the pipeline as tools
├── Dockerfile
├── docker-compose.yml
├── .env
└── requirements.txt
```

### Quickstart

**Docker (recommended)**
```bash
cp .env.example .env
# Set GOOGLE_API_KEY in .env
docker-compose up --build
```

**Local**
```bash
pip install -r requirements.txt
cp .env.example .env
# Set GOOGLE_API_KEY in .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8003
```

API: `http://localhost:8003`  
Swagger: `http://localhost:8003/docs`

### Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_API_KEY` | yes | — | Gemini API key |
| `GEMINI_MODEL` | no | `gemini-2.5-flash-lite-preview-06-17` | Primary model |
| `GEMINI_FALLBACK_MODEL` | no | `models/gemma-3-27b-it` | Used automatically if primary fails |
| `GEMINI_TEMPERATURE` | no | `0.7` | LLM temperature |
| `GEMINI_MAX_TOKENS` | no | `2048` | Max output tokens per call |
| `MIN_QUALITY_SCORE` | no | `80` | Minimum Critic score for a message to pass |
| `MAX_ITERATIONS` | no | `3` | Max Writer→Critic revision cycles before giving up |
| `USE_MOCK_DATA` | no | `true` | Use fake LinkedIn/news/CRM data |
| `ENABLE_HUMAN_REVIEW` | no | `false` | Pause pipeline for human approval before sending |
| `REDIS_URL` | no | — | e.g. `redis://localhost:6379/0` — enables persistent memory, event publishing, and config hot-reload; falls back to in-process dict if not set |
| `WORKER_URL` | no | `http://api:8000` | Worker module URL for config sync on startup |
| `LINKEDIN_API_KEY` | no | — | Reserved for future real LinkedIn integration |
| `NEWS_API_KEY` | no | — | Reserved for future real News API integration |
| `CRM_DATABASE_URL` | no | — | Reserved for future real CRM integration |
| `GMAIL_ADDRESS` | for email send | — | Your Gmail address |
| `GMAIL_APP_PASSWORD` | for email send | — | Gmail App Password (not your account password) |
| `UNIPILE_API_KEY` | for LinkedIn send | — | From your Unipile dashboard |
| `UNIPILE_DSN` | for LinkedIn send | — | e.g. `api4.unipile.com:13465` |
| `UNIPILE_DEFAULT_ACCOUNT_ID` | for LinkedIn send | — | Your connected LinkedIn account ID |

### API endpoints

**Generate a message**

```
POST /api/generate/simple
```

Returns the final message and score. If `ENABLE_HUMAN_REVIEW=true`, returns a `review_url` instead.

```json
{
  "target_prospect": "Sarah Chen",
  "target_company": "Ramp",
  "prospect_role": "VP of Sales",
  "channel": "linkedin_dm",
  "stage": "first_touch",
  "intent": "direct_outreach",
  "personality": {
    "base_template": "soft_sell",
    "personality_traits": ["curious", "direct"],
    "never_use_phrases": ["synergies", "circle back"],
    "touchdowns_per_message": 2,
    "urgency_level": 2,
    "humor_sarcasm": 3,
    "voice_samples": [
      "Hey John, saw your post about the Q3 push — respect. Curious if a quick chat makes sense?"
    ]
  },
  "company_details": {
    "company_name": "SalesForce AI",
    "elevator_pitch": "We help SDR teams double their reply rates using AI personalization.",
    "social_proof": ["Used by 500+ sales teams"]
  },
  "selected_offer": {
    "offer_name": "SDR Efficiency Audit",
    "solution_summary": "A diagnostic of your SDR workflow with a prioritized action plan.",
    "proof_points": ["Teams saw 40% more meetings in 30 days"],
    "cta": "Open to a quick 15-min chat?"
  }
}
```

```
POST /api/generate        — same pipeline, returns full step-by-step state history
GET  /                    — health check + config info
```

**Human review** (when `ENABLE_HUMAN_REVIEW=true`)

```
GET  /api/review/{task_id}            — view the draft waiting for approval
POST /api/review/{task_id}/decision   — approve or reject
```

Approve and send via email:
```json
{ "approved": true, "prospect_email": "sarah@ramp.com" }
```

Approve and send via LinkedIn:
```json
{ "approved": true, "prospect_linkedin_id": "ACoAAA..." }
```

Reject with feedback (triggers a targeted rewrite):
```json
{ "approved": false, "feedback": "Too formal, make it more casual and shorter" }
```

### Channels and character limits

| Channel | Min | Max |
|---|---|---|
| `linkedin_dm` | 50 | 300 |
| `linkedin_inmail` | 100 | 600 |
| `email` | 100 | 800 |
| `twitter_dm` | 20 | 280 |
| `sms` | 20 | 160 |

### Critic validation — two passes

**Pass 1 — deterministic (no LLM, no token cost)**
- Message outside channel length limits → immediate fail, LLM skipped
- Banned phrases present → immediate fail
- Placeholder text like `[Company]`, `[Name]` → score penalty
- Attachment/link references ("I've attached", "see attached") → score penalty
- Overpersonalization patterns → score penalty

**Pass 2 — LLM scoring** (only when pass 1 succeeds)
- Gemini scores 0–100 on CTA clarity, touchdown count, authenticity, required phrases
- Score below `MIN_QUALITY_SCORE` forces `valid=false`

On failure: if fixable suggestions exist and retries remain → `REVISING` → Writer gets the previous draft + specific feedback. If retries exhausted → `FAILED`.

### LLM reliability

All Gemini calls go through `LLMService`:
- **Exponential backoff** via `tenacity` — up to 4 attempts, 20–120s wait on 429/quota errors
- **Automatic fallback** to `GEMINI_FALLBACK_MODEL` if the primary model fails on any error
- **`json5` parsing** — tolerates trailing commas, single quotes, and other sloppy LLM JSON
- **Hard trim** in `write_message` — if the LLM overshoots the character limit, the body is cut at the last sentence boundary within the limit

### Memory system

Three stores, all backed by Redis (persistent) with an in-process dict fallback when `REDIS_URL` is not set:

| Store | What it tracks |
|---|---|
| `ProspectMemoryService` | Contact history, hooks used, angles tried, do-not-contact flag, last message sent |
| `LearningMemoryService` | Global stats: avg quality score, channel/stage/template reply rates, best/worst hooks |
| `OfferMemoryService` | Per-offer usage count, avg score, best channels, best angles, best prospect roles |

Memory is read at the **Researcher** step and written at the **Critic** step (only on success).

`mark_replied` exists on `ProspectMemoryService` and feeds back into `LearningMemoryService` — but nothing in the pipeline calls it yet. Reply tracking requires an external trigger (e.g. a webhook from your email/LinkedIn tool).

### Sender voice emulation

Pass `voice_samples` in the `personality` block — 3 to 5 real messages you've written before. The Writer analyzes sentence rhythm, vocabulary, punctuation habits, and opening/closing patterns, then writes in your voice instead of a generic AI tone.

### Detective module integration

When the request includes a `detective_context` field, the Researcher uses real enrichment data instead of mock data:

- `intent_signals.recent_news` → company news signals
- `intent_signals.technology_changes` → tech stack signals
- `intent_signals.job_postings_count` → hiring signals
- `selected_persona.email` → informs the Strategist's channel sequence plan

`detective_context` also carries a `correlation_id` used for telemetry events.

### Worker module integration

On startup, the Writer fetches dynamic config from `WORKER_URL/v1/config` and applies `MIN_QUALITY_SCORE` and `ENABLE_HUMAN_REVIEW` to local settings.

If `REDIS_URL` is set, a background subscriber listens on the `config_updated` Redis channel and hot-reloads settings without a restart.

### Event telemetry

Two events are published after key pipeline moments:

| Event | When | Payload |
|---|---|---|
| `message_generated` | Critic approves a message | body, subject, quality_score, channel, prospect_name, company_name |
| `message_sent` | Human review endpoint sends a message | channel, recipient, send_result |

Events go to Redis pub/sub first, with HTTP POST to `WORKER_URL/v1/events/ingest` as fallback. Events are silently skipped when no `correlation_id` is present (direct API calls without Detective context).

### MCP — agent-to-agent

The pipeline is exposed as an MCP server at `/mcp` (SSE transport). Any MCP-compatible agent can connect and call:

- `generate_outreach` — run the full pipeline
- `check_prospect` — look up prospect memory
- `mark_do_not_contact` — flag a prospect as DNC

```json
{
  "mcpServers": {
    "agentic-outreach": {
      "url": "http://localhost:8003/mcp",
      "transport": "sse"
    }
  }
}
```

### Email setup (Gmail SMTP — free)

1. Enable 2FA on your Google account
2. Go to `myaccount.google.com` → Security → App Passwords
3. Generate a password for "Mail"
4. Set `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` in `.env`

### LinkedIn setup (Unipile)

1. Sign up at [unipile.com](https://unipile.com)
2. Connect your LinkedIn account
3. Copy your DSN, API key, and account ID into `.env`

### What's stubbed / not yet wired

| Feature | Status |
|---|---|
| Real LinkedIn API | Stub — path exists, logs a warning if `USE_MOCK_DATA=false` + key set, falls back to mock |
| Real News API | Same |
| Real CRM database | Same |
| Reply tracking (`mark_replied`) | Method exists and is wired to `LearningMemoryService`; nothing calls it externally yet |
| `_pending_review` persistence | In-process dict wrapped in `_PendingReviewStore` — lost on restart; swap the class for a Redis implementation to make it persistent |

---

## prospect_strategy_engine

A standalone prospect research tool. Given a company domain, it finds the decision-maker, researches them on the web, generates a sequenced outreach plan, and produces a personalised message.

### How it works

```
Domain input
    │
    ▼
Hunter.io → finds decision-maker (name, email, title, LinkedIn)
    │
    ▼
Tavily → searches web for professional context and LinkedIn activity
    │
    ▼
Strategy agent (LangGraph + OpenAI-compatible chat model)
  → generates a sequenced action plan (channel, timing, action, justification per step)
    │
    ▼
Writer MCP → generates personalised outreach message
  (falls back to the OpenAI-compatible API if Writer MCP is unavailable)
```

### Project structure

```
prospect_strategy_engine/
├── app.py                    # Streamlit UI — main entry point
├── config.py                 # All env vars in one place
├── worker.py                 # Temporal worker entry point
├── agents/
│   ├── graph.py              # LangGraph strategy agent (OpenAI-first structured output)
│   └── state.py              # AgentState, ActionPlan, StrategyOutput models
├── tools/
│   ├── hunter_client.py      # Hunter.io domain-search API
│   ├── tavily_client.py      # Tavily web search API
│   └── outreach_mcp.py       # Writer MCP client + OpenAI-compatible fallback
├── workflows/
│   ├── activities.py         # Temporal activity wrapping the strategy agent
│   └── workflow.py           # Temporal workflow definition
└── requirements.txt
```

### Quickstart

```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file:
```
HUNTER_API_KEY=your_hunter_key
TAVILY_API_KEY=your_tavily_key

# OpenAI-compatible API used by the strategy agent and message fallback
OPENAI_API_KEY=your_openai_key
OPENAI_BASE_URL=https://your-openai-compatible-endpoint
OPENAI_MODEL=hosted_vllm/Llama-3.1-70B-Instruct

# Optional Ollama fallback settings (kept for backwards compatibility)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral
OLLAMA_STRATEGY_MODEL=llama3.1:8b
OUTREACH_MCP_URL=http://localhost:8003/mcp
SENDER_COMPANY_NAME=Your Company
OFFER_NAME=Your Offer
ELEVATOR_PITCH=One sentence about what you do.
CTA=Open to a quick call?
```

Run the Streamlit UI:
```bash
streamlit run app.py
```

Run the smoke test (no UI):
```bash
python test_engine.py
```

Recommended local setup:
```powershell
cd Full-Writer\prospect_strategy_engine
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `HUNTER_API_KEY` | — | Hunter.io API key (required) |
| `TAVILY_API_KEY` | — | Tavily API key (required) |
| `OPENAI_BASE_URL` | — | OpenAI-compatible API base URL used by the strategy agent and message fallback |
| `OPENAI_API_KEY` | — | API key for the OpenAI-compatible endpoint |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model used for the OpenAI-compatible strategy agent and fallback message generation |
| `OPENAI_TIMEOUT` | `45` | Seconds before an OpenAI-compatible request times out |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Optional Ollama server URL for legacy fallback |
| `OLLAMA_MODEL` | `mistral` | Optional Ollama message model for legacy fallback |
| `OLLAMA_STRATEGY_MODEL` | `llama3.1:8b` | Optional Ollama strategy model for legacy fallback |
| `OLLAMA_TIMEOUT` | `45` | Seconds before an Ollama request times out |
| `OUTREACH_MCP_URL` | `http://localhost:8003/mcp` | Writer MCP endpoint |
| `OUTREACH_MCP_TOOL_NAME` | `generate_outreach` | MCP tool name to call |
| `SENDER_COMPANY_NAME` | `Prospect Strategy Engine` | Sender company passed to Writer |
| `OFFER_NAME` | `Personalised B2B Prospecting Strategy` | Offer name passed to Writer |
| `ELEVATOR_PITCH` | (see config.py) | Elevator pitch passed to Writer |
| `SOLUTION_SUMMARY` | (see config.py) | Solution summary passed to Writer |
| `CTA` | `Reply to schedule a quick call...` | CTA passed to Writer |

### Strategy agent

The strategy agent (`agents/graph.py`) uses an OpenAI-compatible chat model with `with_structured_output(StrategyOutput)` to produce a typed `StrategyOutput` containing a list of `ActionPlan` steps. If `OPENAI_BASE_URL` and `OPENAI_API_KEY` are not configured, it can still fall back to Ollama.

Each step has: `step` (int), `channel` (str), `recommended_action` (str), `timing` (str), `justification` (str).

Decision rules baked into the system prompt:
- Phone available → include SMS or Call
- Email only → Email + LinkedIn sequence
- Neither → LinkedIn only
- Casual/emoji posts → relaxed tone
- No posts or formal profile → corporate tone

### Temporal worker (optional)

The Temporal integration wraps the strategy agent in a durable, retryable workflow. Use this if you want to run strategy generation as a background job with automatic retries and observability.

```bash
# Start Temporal server (download temporal CLI and run)
temporal server start-dev

# Start the worker
python worker.py
```

The worker listens on the `strategy-task-queue` task queue. `StrategyWorkflow` calls `generate_strategy_activity` with a 5-minute timeout.

### MCP + API fallback

The `outreach_mcp.py` tool tries the Writer MCP endpoint first. If it's unavailable (connection error, tool not found, any exception), it falls back to the OpenAI-compatible API using `OPENAI_BASE_URL` and `OPENAI_MODEL`. Ollama is retained only as a legacy option.

---

## Running both modules together

1. Start the Writer module: `docker-compose up --build` (or `uvicorn app.main:app --port 8003`)
2. Configure `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL` in `prospect_strategy_engine/.env`
3. Start the Strategy Engine: `streamlit run app.py` (from `prospect_strategy_engine/`)

The Strategy Engine will call the Writer's MCP endpoint at `http://localhost:8003/mcp` to generate the final message. If the Writer isn't running, it falls back to the OpenAI-compatible API automatically.
