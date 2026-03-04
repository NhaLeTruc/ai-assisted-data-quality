# Data Quality & Observability Intelligence Platform

When something goes wrong with your data — a sudden spike in missing values, an unexpected drop in row counts, a column that has drifted to the wrong format — the usual response is a frantic search across dashboards, log files, Slack threads, and runbooks. This platform replaces that scramble with an AI team that does the investigation automatically, in under two minutes, and hands you a written diagnosis and a step-by-step fix.

Seven specialised AI agents collaborate in a structured pipeline. Each agent focuses on one part of the problem — checking the data rules, detecting the anomaly, finding the root cause, mapping downstream damage, assessing business risk, and drafting the remediation plan. They share findings with each other, look up relevant history from a knowledge base, and call real data-quality tools along the way. A human stays in control: the plan is always presented for review before anything is changed in production.

---

## Who is this for?

| Role | How it helps |
|---|---|
| **Data engineers** | Get a written root-cause report and a concrete fix plan instead of starting blind from a monitoring alert |
| **Analytics engineers** | Understand which downstream models and dashboards are at risk before a broken table reaches a stakeholder |
| **Data team leads** | See the business impact — SLA breach risk, financial exposure, escalation contacts — in the same report as the technical diagnosis |
| **Platform / MLOps teams** | Use the REST API to integrate automated triage into an existing alert pipeline (PagerDuty, Airflow, dbt Cloud, etc.) |
| **AI / LLM engineers** | A reference implementation of a production-quality multi-agent system: LangGraph orchestration, RAG-augmented agents, MCP tool servers, two-layer memory, and tiered Claude model usage |

---

## What it does, in plain language

### Catches and confirms the problem
When an alert fires — a null-value spike, a volume drop, a schema change — the platform first re-checks the data against your defined quality rules using Great Expectations. This separates a genuine problem from a noisy alert before spending any AI budget on it.

### Finds the root cause
A reasoning agent (Claude Opus) reads the validation results alongside 48 hours of historical anomaly data and a library of past incidents. It produces a written root-cause explanation with a confidence score — the same kind of analysis a senior data engineer would write, but in seconds rather than hours.

### Maps the blast radius
A lineage agent traces which upstream pipelines fed the broken table and which downstream tables, reports, and consumers depend on it. You see the full impact radius before deciding how urgently to act.

### Tells you what it means for the business
A business-impact agent translates the technical findings into stakeholder language: which SLAs are at risk of breach, an estimated financial exposure, which teams need to be looped in, and who the on-call escalation contact is.

### Proposes a safe fix
A remediation agent matches the situation against your playbook library, generates a step-by-step repair plan, and runs it in dry-run mode first. The plan is presented for human approval; it is only applied automatically if you explicitly enable auto-remediation and the risk level is rated `low`.

### Gets smarter over time
Every decision the agents make is stored in a local SQLite database. When you mark an investigation as resolved (or not), that outcome is attached to all the agent decisions in that run. Future investigations on similar anomalies retrieve those historical outcomes from the knowledge base and use them to improve their analysis — a lightweight feedback loop that compounds over time.

---

## Possible use cases

**Automated alert triage in a data platform**
Point your monitoring tool (Monte Carlo, Great Expectations Cloud, dbt tests, custom Airflow sensors) at the REST API. When an alert fires, `POST /api/v1/investigations` to kick off an investigation automatically. By the time an engineer looks at the PagerDuty page, the root cause and remediation plan are already written.

**Pre-deployment data validation gate**
Run an investigation against a staging dataset before a pipeline promotion. If the validation or detection agents flag a problem, the deployment is blocked and a written explanation is returned to the CI job.

**Incident retrospective generation**
After a data incident is resolved, retrieve the full investigation state via the API and use it as the raw material for a post-mortem. All agent findings, confidence scores, and latencies are structured JSON — easy to feed into a report template.

**SLA monitoring with impact scoring**
Use the business-impact agent's output to triage incidents by revenue risk rather than alert severity. A low-confidence anomaly in a high-revenue table may deserve faster escalation than a high-confidence anomaly in a cold-path table.

**Knowledge base for on-call engineers**
The three knowledge-base tabs (anomaly patterns, DQ rules, remediation playbooks, business context) can be queried directly via the UI or API without running a full investigation. Useful for looking up "what did we do last time this happened?" during an incident.

**Reference architecture for multi-agent AI systems**
The codebase demonstrates several patterns that are difficult to find in a single working example: severity-gated conditional routing in LangGraph, per-agent RAG context enrichment, Model Context Protocol (MCP) tool servers, tiered LLM usage (Opus for reasoning, Sonnet for structured output, Haiku for fast tasks), session checkpointing, and a two-level mock testing strategy that runs without any external services.

---

## How alerts and data reach this app

### The trigger model — metadata in, not data in

The app does **not** receive raw data files. When something goes wrong, a monitoring tool sends a small JSON payload describing the problem — the table name, the type of alert, and a human-readable description. The agents then go and fetch the actual data themselves by calling the MCP tool servers.

```
Monitoring tool                    This app
────────────────    HTTP POST     ──────────────────────────────────────
Monte Carlo      ──────────────► POST /api/v1/investigations
dbt test failure                  {
Airflow sensor                      "dataset_id": "orders_2026_03",
GE Cloud alert                      "table_name": "orders",
Custom script                       "alert_type": "null_spike",
Manual UI form                      "description": "5% null rate in customer_id",
                                    "context": { ...any extra fields... }
                                  }
```

The five `alert_type` values the agents understand are `null_spike`, `volume_drop`, `schema_drift`, `freshness_lag`, and `manual`. Anything else falls back to `manual` handling.

The `context` field is a free-form dictionary — pass through whatever metadata your monitoring tool provides (row counts, threshold values, pipeline run IDs, etc.) and the agents will include it in their analysis.

### What the agents pull after the trigger

Once triggered, each agent reaches out to the relevant data source via an MCP tool call:

| Agent | Data source | What it fetches |
|---|---|---|
| Validation | GX MCP server (`:8081`) | Runs an expectation suite against the dataset file; returns pass/fail per rule |
| Detection | Monte Carlo MCP (`:8082`) | Table health score, recent anomaly history, statistical metrics |
| Diagnosis | Monte Carlo MCP (`:8082`) | Extended 48-hour anomaly window for trend analysis |
| Lineage | Custom MCP (`:8083`) | Upstream pipelines and downstream consumers to a configurable depth |
| Business impact | Custom MCP (`:8083`) | SLA thresholds, financial impact estimates, escalation contacts |
| Repair | Custom MCP (`:8083`) | Similar past anomalies and their resolutions |

Every agent also queries the **Chroma vector database** for relevant history from previous incidents — this is what gets richer over time as you run more investigations and submit feedback.

The dataset files themselves are mounted into the GX MCP server container at startup via a Docker volume (`./demo-data:/demo-data`). In production you would replace this with a connector to your actual data warehouse — Snowflake, BigQuery, Databricks, etc. — by implementing the MCP tool interface against your warehouse's query API.

### Connecting a real monitoring tool

Because the entry point is a plain HTTP POST, any monitoring tool that supports webhooks can drive an investigation. The pattern is the same in each case: receive the alert from the tool, translate its payload into an `InvestigationTrigger`, and POST it to the app.

**Monte Carlo webhook → investigation:**
```python
# In your Monte Carlo webhook handler
@app.post("/webhooks/monte-carlo")
async def mc_webhook(event: dict):
    await httpx.AsyncClient().post(
        "http://dq-platform:8000/api/v1/investigations",
        json={
            "dataset_id": event["asset_id"],
            "table_name": event["table"],
            "alert_type": event["breach_type"],          # map MC types to ours
            "description": event["message"],
            "context": {"mc_incident_id": event["id"]},
        },
    )
```

**dbt Cloud job failure → investigation:**
```python
# In a dbt Cloud webhook or Airflow callback
def on_dbt_test_failure(run_id, failed_tests):
    for test in failed_tests:
        httpx.post(
            "http://dq-platform:8000/api/v1/investigations",
            json={
                "dataset_id": test["relation"],
                "table_name": test["relation"].split(".")[-1],
                "alert_type": "null_spike" if "not_null" in test["name"] else "manual",
                "description": f"dbt test failed: {test['name']}",
                "context": {"dbt_run_id": run_id, "test_name": test["name"]},
            },
        )
```

**Airflow task sensor:**
```python
# Trigger from a downstream Airflow task that checks data quality
from airflow.operators.python import PythonOperator
import httpx

def trigger_investigation(**context):
    resp = httpx.post(
        "http://dq-platform:8000/api/v1/investigations",
        json={
            "dataset_id": context["params"]["dataset_id"],
            "table_name": context["params"]["table_name"],
            "alert_type": "volume_drop",
            "description": "Row count below expected threshold",
            "context": {"dag_run_id": context["run_id"]},
        },
    )
    # Store investigation_id in XCom for the polling task
    return resp.json()["investigation_id"]
```

The response to every POST is immediate (HTTP 202) with an `investigation_id`. The investigation runs asynchronously in the background. Poll `GET /api/v1/investigations/{id}` until `workflow_complete` is `true`, then read the results.

---

## Throughput and production considerations

### What a single investigation costs in time and money

The workflow runs three phases, each with one or two agent calls. The agents run **sequentially within a phase** (each agent's output feeds the next), but the overall pipeline is asynchronous so the server stays responsive to new requests while one investigation is in flight.

| Phase | Agents | Model | Max timeout |
|---|---|---|---|
| Phase 1 | Validation + Detection | Haiku 4.5 + Sonnet 4.6 | 15 s + 30 s |
| Phase 2 | Diagnosis + Lineage | Opus 4.6 + Sonnet 4.6 | 60 s + 30 s |
| Phase 3 | Business Impact + Repair | Opus 4.6 + Sonnet 4.6 | 60 s + 30 s |

Phases 2 and 3 are **severity-gated** — they only run when an anomaly is detected and its severity is `critical` or `high`. A low-confidence or informational alert completes after Phase 1 alone (under 60 seconds).

Typical observed latency for a full critical-path investigation (all six agents) is **60–120 seconds** under normal Anthropic API response times. The worst-case with retries (three attempts, exponential backoff up to 60 s between attempts) is around six minutes — this only occurs during severe API degradation.

API cost per investigation varies by routing path:

| Path | Agents called | Approximate cost |
|---|---|---|
| Clean data (no anomaly) | Validation + Detection | ~$0.002 |
| Anomaly, warning severity | + Diagnosis + Lineage | ~$0.04 |
| Anomaly, critical/high severity | All six agents | ~$0.08–$0.12 |

Cost tracking is built in — check `GET /health` for the running session total and per-investigation average.

### Concurrency in the current architecture

The app runs as a **single uvicorn process** with a single asyncio event loop. Background investigations share that loop with incoming HTTP requests. Because almost all agent work is I/O-bound (waiting for Claude API responses and MCP HTTP calls), multiple investigations can genuinely overlap — Python's async scheduler interleaves them while each is waiting for a network response.

In practice **3–5 simultaneous investigations** run without noticeable degradation. Beyond that, two bottlenecks emerge:

1. **SQLite write serialisation** — LangGraph checkpoints every state transition to `checkpoints.db`. SQLite allows only one writer at a time; concurrent investigations queue on the write lock rather than fail, but latency climbs.
2. **Anthropic rate limits** — the default `MAX_REQUESTS_PER_MINUTE=60` applies across all in-flight investigations. A burst of ten simultaneous investigations each making six Claude calls would hit this ceiling immediately, causing retries and added latency.

### Adapting for higher throughput

This deployment is designed for **teams running tens of investigations per day** — incident-driven workflows where a human or automated monitor triggers an investigation per alert, not a continuous stream of thousands of events.

If your volume or concurrency requirements exceed that, the following changes address the main constraints — roughly in order of impact:

**Replace SQLite with PostgreSQL for checkpointing**
LangGraph ships `langgraph-checkpoint-postgres` which uses row-level locking instead of a file-wide write lock. This removes the single biggest concurrency bottleneck and allows many investigations to checkpoint simultaneously.

**Move workflow execution to a task queue**
Decouple the HTTP ingest layer from workflow execution with Celery + Redis, or a durable workflow engine like Temporal. The FastAPI app enqueues a job and returns immediately; a pool of worker processes picks up and runs the LangGraph workflow. This lets you scale workers independently of the API tier and survive app restarts mid-investigation.

**Raise the Anthropic API tier**
Anthropic rate limits scale with your usage tier. Tier 4 access provides ~2,000 RPM for Haiku and ~1,000 RPM for Sonnet; Opus limits are lower but still sufficient for hundreds of investigations per hour. Contact Anthropic sales for volume arrangements.

**Scale ChromaDB horizontally**
The current setup runs ChromaDB as a single container. For high read throughput (many agents querying the knowledge base simultaneously), deploy ChromaDB in distributed mode behind a load balancer. The app already uses the HTTP client interface, so no code changes are needed.

**Replace the in-process MCP servers with scaled services**
The three MCP servers are single-process FastAPI apps. For high-volume production, deploy each as a horizontally scaled service behind a load balancer and point `MCP_GX_URL`, `MCP_MC_URL`, `MCP_CUSTOM_URL` at the load balancer addresses.

---

## System architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ENTRY POINTS                                  │
│   Streamlit UI :3000          FastAPI REST :8000                     │
└────────────────────────────┬────────────────────────────────────────┘
                             ▼
┌───────────────────────────────────────────────────────────────────────┐
│                    LangGraph Workflow (7 agents)                       │
│                                                                        │
│  Orchestrator ──► Phase 1: Validation → Detection                     │
│       ▲           Phase 2: Diagnosis  → Lineage          (severity-   │
│       └───────    Phase 3: BusinessImpact → Repair        gated)      │
└───────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
   MCP Servers          Chroma :8001          SQLite Files
   GX    :8081        4 RAG collections     checkpoints.db
   MC    :8082        anomaly_patterns       decisions.db
   Custom:8083        dq_rules
                      rem_playbooks               ▼
                      business_context       Anthropic API
                                           (Claude Opus/Sonnet/Haiku)
```

**Key design principles:**
- **Severity-gated routing** — Diagnosis only runs when an anomaly is detected; Remediation only runs for `critical`/`high` severity, so low-signal alerts don't waste compute or API budget
- **RAG-augmented agents** — every agent retrieves relevant historical anomalies, playbooks, and business rules from the knowledge base before calling the LLM, keeping prompts grounded in your data's actual history
- **Two-layer memory** — LangGraph session checkpoints store the in-flight workflow state; a SQLite decision log stores every agent judgment with feedback, enabling long-term learning across investigations
- **Single-call MCP tools** — agents call Great Expectations, Monte Carlo, and custom lineage/remediation tools via the Model Context Protocol; each call returns a complete result with no polling loops

---

## Prerequisites

| Requirement | Version |
|---|---|
| Docker Desktop (or Engine + Compose plugin) | 4.x+ |
| RAM allocated to Docker | ≥ 4 GB |
| Anthropic API key | Claude Opus/Sonnet/Haiku access |
| Python | 3.11+ (for running tests locally) |
| GNU Make | any recent version |

---

## Quick Reference

```
make quickstart      First-time setup: .env → build → start → seed
make up              Start services (after first build)
make seed            Re-seed the knowledge base
make reset           Full reset: wipe data, restart, re-seed

make test            Run all tests (86 unit + integration)
make test-unit       Unit tests only (no Docker needed)
make test-integration  Integration tests only
make lint            Ruff lint + format check

make down            Stop and remove containers
make stop            Pause containers (resume with: make up)
make clean           Remove containers and delete all persisted data

make logs            Tail logs from all services
make health          Print all service health statuses
make help            List all targets with descriptions
```

---

## Download all wheels (optional, speeds up builds)

Pre-downloading wheels avoids re-fetching large packages (torch ~700 MB) on every build.
The main `Dockerfile` uses `--find-links ./wheels` so it uses local wheels when present and
falls back to the internet for anything missing.

```bash
pip download --dest docker-wheels/ \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    torch==2.10.0 sentence-transformers==5.2.3 \
    langgraph==0.2.55 langchain-core==0.3.83 langchain==0.3.27 \
    langchain-anthropic==0.3.4 langchain-chroma==0.2.6 \
    langchain-community==0.3.31 \
    llama-index-core==0.14.15 llama-index-embeddings-huggingface==0.6.1 \
    chromadb==1.5.2 rank-bm25==0.2.2 fastmcp==3.1.0 \
    fastapi==0.135.1 "uvicorn[standard]==0.41.0" httpx==0.28.1 \
    pydantic==2.12.5 tenacity==9.1.4 python-dotenv==1.2.2 \
    langgraph-checkpoint==2.1.2 langgraph-checkpoint-sqlite==2.0.11
```

To upgrade a package, change its version in `.env` and re-run the command above with the new version, then `make build`.

---

## Quickstart

```bash
git clone <repo-url>
cd AI-assisted-data-quality
make quickstart
```

`make quickstart` will:
1. Create `.env` from `.env.example` (and stop if `ANTHROPIC_API_KEY` is still the placeholder)
2. Build all 6 Docker images
3. Start the full stack (`docker compose up -d`)
4. Wait 45 s for healthchecks to pass
5. Seed all 4 Chroma knowledge-base collections

Then open **http://localhost:3000**.

**Manual equivalent** (if you prefer explicit steps):

```bash
cp .env.example .env          # then edit ANTHROPIC_API_KEY
docker compose build
docker compose up -d
sleep 45
docker compose exec app python scripts/seed_demo_data.py
```

---

## Service URLs

| Service | URL | Purpose |
|---|---|---|
| **Demo UI** | http://localhost:3000 | Streamlit dashboard (start here) |
| **FastAPI** | http://localhost:8000 | REST API |
| **Swagger UI** | http://localhost:8000/docs | Interactive API docs |
| **Health check** | http://localhost:8000/health | All service statuses + cost |
| Chroma | http://localhost:8001 | Vector DB (internal) |
| GX MCP | http://localhost:8081/health | Great Expectations server |
| MC MCP | http://localhost:8082/health | Monte Carlo mock server |
| Custom MCP | http://localhost:8083/health | Lineage & remediation tools |

---

## Demo Walkthrough

### The Canonical Scenario: "Null Spike Investigation"

This 5-minute flow exercises all 7 agents, 3 MCP servers, RAG retrieval, and the memory system.

#### Step 1 — Trigger the investigation

Open http://localhost:3000, go to **Tab 1 "Run Investigation"**, and fill in:

| Field | Value |
|---|---|
| Dataset ID | `orders_2026_03` |
| Table Name | `orders` |
| Alert Type | `null_spike` |
| Description | `Noticed customer_id column has unusually high null rate this morning` |

Click **▶ Run Investigation**. The UI displays the investigation ID and starts polling every 2 seconds.

#### Step 2 — Phase 1: Detection (automatic)

- **Validation Agent** (Claude Haiku 4.5) calls the GX MCP server: creates an expectation suite, runs a checkpoint, and retrieves results. Finds 5% null rate in `customer_id` (500 / 10,000 rows) — a clear `expect_column_values_to_not_be_null` failure.
- **Detection Agent** (Claude Haiku 4.5) calls the Monte Carlo mock for table health + recent anomalies. Queries the `anomaly_patterns` RAG collection and surfaces `DQ-2026-0001` (a similar historical null spike, resolved in 2.5h). Emits `anomaly_detected=True, confidence=0.91`.

Phase progress updates live in the UI. After Detection, `current_phase=detection_complete, severity=high`.

#### Step 3 — Phase 2: Diagnosis (automatic)

The Orchestrator routes to the Diagnosis pipeline because an anomaly was detected.

- **Diagnosis Agent** (Claude Opus 4.6) synthesizes GX failures, Monte Carlo anomalies, and the RAG-retrieved historical case. Determines `root_cause="Upstream API deployment returning null customer_id values"`, `confidence=0.87`.
- **Lineage Agent** (Claude Haiku 4.5) calls `analyze_data_lineage(orders, depth=3)`. Finds 4 downstream consumers (`revenue_report`, `customer_segment_model`, `marketing_pipeline`, `finance_dashboard`), `impact_radius=7`, `critical_path_breached=True`.

After Lineage, `current_phase=diagnosis_complete, severity=high`.

#### Step 4 — Phase 3: Remediation (automatic)

The Orchestrator routes to Remediation because `severity=high`.

- **Business Impact Agent** (Claude Opus 4.6) calls `assess_business_impact`. Determines `escalation_required=True`, with `revenue_report` approaching its 2h SLA.
- **Repair Agent** (Claude Haiku 4.5) retrieves playbook `PB-ROLLBACK-001` from RAG, calls `get_similar_anomalies` to find `DQ-2026-0001`'s resolution, then calls `apply_remediation(dry_run=True)`. Produces a 6-step rollback + backfill plan.

Final state: `current_phase=remediation_complete`.

#### Step 5 — Read the results

The UI displays:
- 🟠 **HIGH** severity badge
- Root cause with 87% confidence
- ~500 affected records
- Downstream impact: 7 nodes including `revenue_report` (SLA risk)
- Historical match: `DQ-2026-0001` — resolved in 2.5h by rollback
- Remediation plan: dry-run confirmed safe, 90-min estimated duration
- Escalation contacts

Per-agent latencies are shown as a bar chart.

#### Step 6 — Submit feedback (closes the learning loop)

Go to **Tab 2 "History"**, find the investigation, click **✅ Mark Resolved**. This records `was_correct=True` in `decisions.db` for all agent decisions in this investigation. The next similar investigation will retrieve this outcome from long-term memory to improve its recommendations.

---

## Demonstrating Individual Features

### RAG Knowledge Base (Tab 3)

Search across any of the 4 Chroma collections without running a full investigation:

| Collection | What it contains | Example query |
|---|---|---|
| `anomaly_patterns` | 20 historical anomaly records with root causes and resolutions | `null spike customer_id` |
| `dq_rules` | Data quality rules per table and expectation type | `orders completeness rules` |
| `remediation_playbooks` | 10 step-by-step fix procedures (rollback, backfill, quarantine…) | `how to rollback pipeline` |
| `business_context` | SLA, criticality, and ownership metadata per table | `revenue_report sla` |

Results are ranked by a BM25 + vector ensemble retriever with cross-encoder reranking (MiniLM-L-6-v2).

### REST API (direct curl)

```bash
# Trigger an investigation
curl -s -X POST http://localhost:8000/api/v1/investigations \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"orders_2026_03","table_name":"orders",
       "alert_type":"null_spike",
       "description":"High null rate in customer_id"}'

# Poll state (replace ID)
curl http://localhost:8000/api/v1/investigations/<id> | python3 -m json.tool

# Submit feedback
curl -s -X POST http://localhost:8000/api/v1/investigations/<id>/feedback \
  -H "Content-Type: application/json" \
  -d '{"was_resolved":true,"resolution_notes":"Rolled back API v2.3.1"}'

# Query knowledge base
curl -s -X POST http://localhost:8000/api/v1/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query":"null spike orders table","collection":"anomaly_patterns","limit":3}' \
  | python3 -m json.tool
```

Interactive docs with request/response schemas: **http://localhost:8000/docs**

### Graceful degradation

Stop a single MCP server mid-demo — the investigation continues with fallback results and no 500 errors:

```bash
docker compose stop mcp-gx

# Trigger an investigation — validation degrades gracefully, detection continues
curl -s -X POST http://localhost:8000/api/v1/investigations \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"orders_2026_03","table_name":"orders",
       "alert_type":"null_spike","description":"Test degraded mode"}'

# Health reflects the outage
curl http://localhost:8000/health | python3 -m json.tool
# "mcp_gx": "degraded", "status": "degraded"

docker compose start mcp-gx  # restore
```

### Long-term memory persistence

After running at least one investigation and submitting feedback:

```bash
docker compose exec app python3 -c "
import sqlite3, os
conn = sqlite3.connect(os.getenv('DECISIONS_DB_PATH', '/data/sqlite/decisions.db'))
rows = conn.execute('''
    SELECT agent_name, decision_type, confidence, was_correct
    FROM agent_decisions LIMIT 10
''').fetchall()
for r in rows:
    print(r)
conn.close()
"
```

### Verify all services and collections

```bash
# Health
curl http://localhost:8000/health | python3 -m json.tool

# Chroma collection counts
docker compose exec app python3 -c "
import chromadb
c = chromadb.HttpClient(host='chroma', port=8000)
for col in ['anomaly_patterns','dq_rules','remediation_playbooks','business_context']:
    print(f'{col}: {c.get_collection(col).count()} docs')
"

# MCP server health
curl http://localhost:8081/health
curl http://localhost:8082/health
curl http://localhost:8083/health
```

---

## Testing

Tests run entirely locally — no Docker required. A mock Anthropic server (started automatically by the test suite) handles all LLM calls, so no real API key is needed.

```bash
make test               # all 86 tests (unit + integration)
make test-unit          # 71 unit tests — agent nodes, routing, MCP session logic
make test-integration   # 15 integration tests — full HTTP API layer
make lint               # ruff lint + format check
```

On first run `make test` creates a `.venv`, installs `requirements.txt` + `requirements-dev.txt`, then runs pytest. Subsequent runs skip the install step unless either requirements file has changed.

**What is tested:**

| Suite | Coverage |
|---|---|
| `tests/unit/test_orchestrator.py` | `terminal_node`, `route_from_orchestrator` (all branches), `safe_agent_node` latency/error tracking, MCP session caching, SSE parsing |
| `tests/unit/test_validation_node.py` | Happy path, 3 MCP tool calls, RAG retrieval, LLM fallback, resilience to each dependency failing |
| `tests/unit/test_detection_node.py` | Severity mapping for all 5 alert types, `anomaly_detected=False` → `severity=None`, resilience |
| `tests/unit/test_diagnosis_node.py` | 48 h Monte Carlo lookback, RAG similar-anomaly + playbook queries, fallback |
| `tests/unit/test_lineage_node.py` | `current_phase` transition, severity propagation from `diagnosis_result`, resilience |
| `tests/unit/test_business_impact_node.py` | Fallback escalation logic for critical/high severity, resilience |
| `tests/unit/test_repair_node.py` | Dry-run default, `auto_remediate + risk_level=low` → live run, medium-risk stays dry |
| `tests/integration/test_investigation_api.py` | All REST endpoints: POST/GET investigations, feedback, RAG query/index, health |

**Mock strategy:** unit tests patch `invoke_with_retry`, `call_mcp_tool`, `get_retriever`, and `get_long_term_memory` at each agent module. Integration tests use a lightweight test FastAPI app with mocked `app.state`, backed by a real in-process mock Anthropic server on port 19876.

---

## Shutdown

```bash
make down       # stop and remove all containers (data in ./data/ is preserved)
make stop       # pause containers — resume later with: make up
make clean      # remove containers AND delete ./data/chroma/ and ./data/sqlite/
```

Use `make clean` when you want a completely fresh start (equivalent to `make reset` but without the automatic restart and re-seed).

---

## Reset to Clean State

To wipe all data and restart with a freshly seeded knowledge base in one step:

```bash
make reset
```

This is equivalent to running `bash scripts/reset_demo.sh`: stops all containers, clears `data/chroma/` and `data/sqlite/`, restarts services, waits 45 seconds for healthchecks, then re-seeds all 4 Chroma collections automatically.

---

## Configuration

All configuration is via environment variables in `.env`. Copy `.env.example` to get started.

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** Claude Opus 4.6, Sonnet 4.6, Haiku 4.5 access |
| `CHROMA_HOST` | `chroma` | Chroma container hostname |
| `CHROMA_PORT` | `8000` | Internal Chroma port |
| `MCP_GX_URL` | `http://mcp-gx:8081/mcp` | Great Expectations MCP endpoint |
| `MCP_MC_URL` | `http://mcp-mc:8082/mcp` | Monte Carlo mock MCP endpoint |
| `MCP_CUSTOM_URL` | `http://mcp-custom:8083/mcp` | Custom tools MCP endpoint |
| `SQLITE_PATH` | `/data/sqlite/checkpoints.db` | LangGraph checkpoint store |
| `DECISIONS_DB_PATH` | `/data/sqlite/decisions.db` | Long-term agent decision store |
| `LOG_LEVEL` | `INFO` | Python log level |
| `COST_TRACKING_ENABLED` | `true` | Track per-investigation API cost |
| `COST_ALERT_THRESHOLD` | `5.00` | USD threshold for cost warning logs |
| `MEMORY_RETENTION_DAYS` | `90` | Days before unresolved decisions are pruned |

---

## Project Layout

```
AI-assisted-data-quality/
│
├── src/
│   ├── main.py                  # FastAPI app factory; startup event
│   ├── config.py                # Env vars, MODELS dict, CostTracker
│   ├── agents/
│   │   ├── workflow.py          # LangGraph StateGraph; build_workflow()
│   │   ├── orchestrator.py      # Routing logic; Pydantic output schemas
│   │   ├── validation.py        # GX validation via MCP
│   │   ├── detection.py         # Monte Carlo anomaly detection + RAG
│   │   ├── diagnosis.py         # GPT-4o root cause analysis
│   │   ├── lineage.py           # Data lineage + downstream impact
│   │   ├── business_impact.py   # SLA and business risk assessment
│   │   └── repair.py            # Playbook matching + dry-run remediation
│   ├── api/
│   │   ├── health.py            # GET /health (concurrent service probes)
│   │   └── routes.py            # /api/v1/* endpoints
│   ├── rag/
│   │   ├── indexer.py           # LlamaIndex semantic chunking → Chroma
│   │   └── retriever.py         # BM25 + vector ensemble + reranker
│   └── memory/
│       ├── short_term.py        # SqliteSaver checkpointer helpers
│       └── long_term.py         # AgentDecision store + feedback loop
│
├── mcp-servers/
│   ├── great-expectations/      # FastMCP server :8081 — 4 GX tools
│   ├── monte-carlo-mock/        # FastMCP server :8082 — 4 MC mock tools
│   └── custom/                  # FastMCP server :8083 — lineage + remediation
│
├── ui/
│   └── app.py                   # Streamlit dashboard (Tab 1/2/3)
│
├── demo-data/
│   ├── sample_datasets/         # orders.csv (10k rows), customers, products
│   └── seed_data/               # anomalies.json, playbooks.json, business_context.json
│
├── scripts/
│   ├── seed_demo_data.py        # Seeds all 4 Chroma collections
│   └── reset_demo.sh            # Full stack reset + reseed
│
├── docs/
│   ├── SPEC.md                  # Full technical specification
│   ├── PLAN.md                  # Architecture plan
│   └── TASKS.md                 # Implementation checklist (all phases complete)
│
├── docker-compose.yml           # 6 services: app, chroma, mcp-gx, mcp-mc, mcp-custom, demo-ui
├── Dockerfile                   # Python 3.11-slim; CPU-only torch; ARG-based version pinning
├── docker-wheels/               # Pre-downloaded wheels (gitignored except .gitkeep)
└── .env.example                 # Runtime env vars + dependency version build args
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Agent framework | LangGraph (StateGraph, conditional routing, SQLite checkpoints) |
| LLM | Claude Opus 4.6 (reasoning agents), Sonnet 4.6 (structured), Haiku 4.5 (simple) |
| Embeddings | `BAAI/bge-base-en-v1.5` via sentence-transformers (local, 768 dimensions) |
| RAG retrieval | BM25 + Chroma vector ensemble → MiniLM-L-6-v2 cross-encoder reranker |
| RAG indexing | LlamaIndex semantic splitter → ChromaDB |
| MCP servers | FastMCP (Streamable HTTP) |
| REST API | FastAPI + uvicorn |
| Demo UI | Streamlit |
| Vector DB | ChromaDB (HNSW) |
| Memory | SQLite (LangGraph checkpoints + agent decision history) |
| Deployment | Docker Compose (6 containers) |
