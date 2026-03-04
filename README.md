# Data Quality & Observability Intelligence Platform

A multi-agent AI system that automatically investigates data quality alerts, diagnoses root causes, assesses business impact, and produces remediation plans — all driven by a 7-node LangGraph workflow connected to real tooling via MCP.

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
                      business_context       OpenAI API
                                           (GPT-4o / mini)
```

**Key design principles:**
- **Severity-gated routing** — Diagnosis only runs when an anomaly is detected; Remediation only runs for `critical`/`high` severity
- **RAG-augmented agents** — every agent enriches LLM context with semantically retrieved historical anomalies, playbooks, and business rules
- **Two-layer memory** — LangGraph session checkpoints (short-term) + SQLite decision history with user feedback (long-term learning)
- **Single-call MCP tools** — no polling loops; each tool call returns a complete result

---

## Prerequisites

| Requirement | Version |
|---|---|
| Docker Desktop (or Engine + Compose plugin) | 4.x+ |
| RAM allocated to Docker | ≥ 4 GB |
| OpenAI API key | GPT-4o and GPT-4o-mini access |

---

## Quickstart

```bash
# 1. Clone and configure
git clone <repo-url>
cd AI-assisted-data-quality
cp .env.example .env
# Edit .env — set OPENAI_API_KEY=sk-...

# 2. Build and start all 6 services
docker compose up -d

# 3. Seed the knowledge base (run once after first start)
docker compose exec app python scripts/seed_demo_data.py
```

Wait ~30 seconds for healthchecks to pass, then open **http://localhost:3000**.

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

- **Validation Agent** (GPT-4o-mini) calls the GX MCP server: creates an expectation suite, runs a checkpoint, and retrieves results. Finds 5% null rate in `customer_id` (500 / 10,000 rows) — a clear `expect_column_values_to_not_be_null` failure.
- **Detection Agent** (GPT-4o-mini) calls the Monte Carlo mock for table health + recent anomalies. Queries the `anomaly_patterns` RAG collection and surfaces `DQ-2026-0001` (a similar historical null spike, resolved in 2.5h). Emits `anomaly_detected=True, confidence=0.91`.

Phase progress updates live in the UI. After Detection, `current_phase=detection_complete, severity=high`.

#### Step 3 — Phase 2: Diagnosis (automatic)

The Orchestrator routes to the Diagnosis pipeline because an anomaly was detected.

- **Diagnosis Agent** (GPT-4o) synthesizes GX failures, Monte Carlo anomalies, and the RAG-retrieved historical case. Determines `root_cause="Upstream API deployment returning null customer_id values"`, `confidence=0.87`.
- **Lineage Agent** (GPT-4o-mini) calls `analyze_data_lineage(orders, depth=3)`. Finds 4 downstream consumers (`revenue_report`, `customer_segment_model`, `marketing_pipeline`, `finance_dashboard`), `impact_radius=7`, `critical_path_breached=True`.

After Lineage, `current_phase=diagnosis_complete, severity=high`.

#### Step 4 — Phase 3: Remediation (automatic)

The Orchestrator routes to Remediation because `severity=high`.

- **Business Impact Agent** (GPT-4o) calls `assess_business_impact`. Determines `escalation_required=True`, with `revenue_report` approaching its 2h SLA.
- **Repair Agent** (GPT-4o-mini) retrieves playbook `PB-ROLLBACK-001` from RAG, calls `get_similar_anomalies` to find `DQ-2026-0001`'s resolution, then calls `apply_remediation(dry_run=True)`. Produces a 6-step rollback + backfill plan.

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

## Reset to Clean State

To wipe all data and start fresh (useful between demo runs):

```bash
bash scripts/reset_demo.sh
```

This stops all containers, clears `data/chroma/` and `data/sqlite/`, restarts services, waits 45 seconds for healthchecks, then re-seeds all 4 Chroma collections automatically.

---

## Configuration

All configuration is via environment variables in `.env`. Copy `.env.example` to get started.

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | **Required.** GPT-4o and GPT-4o-mini access |
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
├── Dockerfile                   # Python 3.11-slim; CPU-only torch
└── .env.example                 # All 17 env vars with defaults
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Agent framework | LangGraph (StateGraph, conditional routing, SQLite checkpoints) |
| LLM | GPT-4o (reasoning agents), GPT-4o-mini (structured + simple agents) |
| Embeddings | `text-embedding-3-large` (3072 dimensions) |
| RAG retrieval | BM25 + Chroma vector ensemble → MiniLM-L-6-v2 cross-encoder reranker |
| RAG indexing | LlamaIndex semantic splitter → ChromaDB |
| MCP servers | FastMCP (Streamable HTTP) |
| REST API | FastAPI + uvicorn |
| Demo UI | Streamlit |
| Vector DB | ChromaDB (HNSW) |
| Memory | SQLite (LangGraph checkpoints + agent decision history) |
| Deployment | Docker Compose (6 containers) |
