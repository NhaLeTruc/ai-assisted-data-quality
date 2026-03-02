# Implementation Plan: Data Quality & Observability Intelligence Platform

## Context

The repository contains only documentation — 9 ADRs and `docs/SPEC.md` (1,615 lines). No implementation code exists. This plan breaks the full build into 6 sequential phases with clear phase-gate verification at each step. The canonical deliverable is a one-command Docker Compose stack that can run the "Null Spike Investigation" demo scenario end-to-end.

**Source documents:** `docs/SPEC.md` (authoritative), `docs/adr/0002` through `0009`

---

## Dependency Order

```
Phase 0 (Scaffold) → Phase 1 (Schemas) → Phase 2 (Data + MCP + RAG) → Phase 3 (Agents) → Phase 4 (API) → Phase 5 (UI) → Phase 6 (Polish)
```

Parallel opportunities:
- Phase 2A (demo data JSON/CSV) can run alongside Phase 2B (MCP servers) and Phase 2C (RAG)
- Phase 5 (Streamlit skeleton) can start while Phase 4 API is being built

**Minimum viable demo path** (must work for the null spike scenario):
`orders.csv` + seed data seeded in Chroma + 3 MCP servers running + 7 agents compiling + `POST /api/v1/investigations` returns `remediation_complete`

---

## Phase 0 — Project Scaffold

**Goal:** `docker compose build` succeeds. No source code yet.

### Files to create

| File | Notes |
|---|---|
| `.gitignore` | Include `data/`, `*.pyc`, `__pycache__/`, `.env` |
| `.env.example` | All 17 env vars from SPEC §4 with defaults |
| `requirements.txt` | From SPEC §14 — use `>=` pins, not exact |
| `Dockerfile` | `python:3.11-slim`, installs requirements, COPY src/ + scripts/ + demo-data/, CMD uvicorn |
| `docker-compose.yml` | 6 services from SPEC §14; all with healthchecks; `condition: service_healthy` for app dependencies |
| `mcp-servers/great-expectations/Dockerfile` | Standard slim python pattern, `EXPOSE 8081` |
| `mcp-servers/great-expectations/requirements.txt` | `fastmcp`, `great-expectations`, `pandas`, `fastapi`, `uvicorn` |
| `mcp-servers/monte-carlo-mock/Dockerfile` | `EXPOSE 8082` |
| `mcp-servers/monte-carlo-mock/requirements.txt` | `fastmcp`, `fastapi`, `uvicorn` |
| `mcp-servers/custom/Dockerfile` | `EXPOSE 8083` |
| `mcp-servers/custom/requirements.txt` | `fastmcp`, `fastapi`, `uvicorn`, `chromadb`, `httpx` |
| `ui/Dockerfile` | `pip install streamlit httpx`, `EXPOSE 8501`, CMD streamlit run app.py |
| `src/__init__.py` | Empty |
| `src/agents/__init__.py` | Empty |
| `src/memory/__init__.py` | Empty |
| `src/rag/__init__.py` | Empty |
| `src/api/__init__.py` | Empty |
| `data/chroma/.gitkeep` | Ensures volume mount directory exists in git |
| `data/sqlite/.gitkeep` | Same |

**Critical docker-compose.yml details:**
- Chroma healthcheck URL: `http://localhost:8000/api/v1/heartbeat` (internal port 8000, host-mapped to 8001)
- demo-ui port mapping: `3000:8501` (Streamlit internal port is 8501)
- All MCP servers health endpoints: `curl http://localhost:<port>/health`
- Add `ANONYMIZED_TELEMETRY=false` env var to Chroma service

### Phase 0 Gate
```bash
docker compose build          # All 6 images build without errors
docker compose up -d chroma
curl http://localhost:8001/api/v1/heartbeat
# Expected: {"nanosecond heartbeat": <number>}
```

---

## Phase 1 — Core Schemas and Configuration

**Goal:** `from src.config import MODELS` succeeds. All TypedDicts and Pydantic models defined.

### Files to create

**`src/config.py`** — imported by every other module; implement first
- `load_dotenv()` at module level
- `MODELS` dict: `tier1_reasoning` (gpt-4o, temp=0.1, max_tokens=4096, timeout=60), `tier2_structured` (gpt-4o-mini, temp=0.0, max_tokens=2048, timeout=30), `tier3_simple` (gpt-4o-mini, temp=0.0, max_tokens=1024, timeout=15), `embeddings` (text-embedding-3-large, dimensions=3072)
- `CostTracker` class with `PRICING` dict, `record(model, investigation_id, input_tokens, output_tokens)`, `report()` → `{session_total_usd, investigation_count, avg_per_investigation_usd}`
- `invoke_with_retry()` async fn: `@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=4, max=60))`
- Module-level singleton: `cost_tracker = CostTracker()`
- All env var constants with `os.getenv()` and defaults

**`src/agents/workflow.py`** — schemas only (graph construction added in Phase 3)
- `DataQualityState` TypedDict (20 fields from SPEC §5.1)
- `WorkflowMemory` TypedDict (6 fields from SPEC §5.2)

**`src/agents/orchestrator.py`** — Pydantic models + routing stub
- All 8 Pydantic output models from SPEC §5.4: `InvestigationTrigger`, `ValidationResult`, `DetectionResult`, `DiagnosisResult`, `LineageResult`, `BusinessImpactResult`, `RemediationPlan`, `RemediationOutcome`
- `route_from_orchestrator()` — pure function, no LLM, returns `Literal["validation","diagnosis","business_impact","complete"]` (stub body with `NotImplementedError` until Phase 3)

**`src/memory/short_term.py`** — full implementation
- `create_checkpointer(sqlite_path)` → `SqliteSaver`; add `os.makedirs(dirname, exist_ok=True)` guard
- `update_shared_context(state, agent_name, findings_summary)` → partial state dict
- `record_agent_latency(state, agent_name, elapsed_ms)` → partial state dict

**`src/memory/long_term.py`** — full implementation
- `AgentDecision` dataclass (9 fields from SPEC §5.3)
- `LongTermMemory.__init__(db_path, rag_retriever=None)`: creates SQLite table + indexes on init
- SQLite DDL exactly as in SPEC §9.2 (table + 2 indexes)
- `record_decision(decision)`, `get_similar_decisions(agent_name, decision_type, input_desc, k=5)` (returns `[]` if `rag_retriever is None`), `record_feedback(investigation_id, was_resolved, notes)` → int, `cleanup_old_memory(days=90)` → int

### Phase 1 Gate
```bash
python -c "
from src.config import MODELS, CostTracker, cost_tracker
from src.agents.workflow import DataQualityState
from src.agents.orchestrator import InvestigationTrigger, DetectionResult
from src.memory.short_term import create_checkpointer
from src.memory.long_term import LongTermMemory, AgentDecision
print('Phase 1 imports OK')
"
```

---

## Phase 2 — Demo Data, MCP Servers, and RAG

**All three sub-phases can run in parallel.**

### Phase 2A — Demo Data Files

**`demo-data/sample_datasets/orders.csv`** — 10,000 rows
- Columns: `order_id` (UUID), `customer_id` (UUID, **5% null = ~500 rows**), `product_id` (UUID), `order_date` (ISO date, last 90 days), `amount` (float, $0.01-$5000), `status` (pending/processing/shipped/delivered/cancelled), `region` (US/EU/APAC/LATAM)
- Generate programmatically with Python's `uuid`, `random`, `csv` modules

**`demo-data/sample_datasets/customers.csv`** — 5,000 rows
- `phone` column intentionally mixes 10-char and 15-char values (schema drift scenario)

**`demo-data/sample_datasets/products.csv`** — 1,000 rows, clean data

**`demo-data/seed_data/anomalies.json`** — 20 records

Required coverage matrix:
| `anomaly_type` | Severity distribution | Count |
|---|---|---|
| `null_spike` | 2 critical, 2 warning | 4 |
| `schema_drift` | 1 critical, 2 warning, 1 info | 4 |
| `volume_drop` | 2 critical, 2 warning | 4 |
| `freshness_lag` | 1 critical, 3 warning | 4 |
| `duplicate_records` | 1 high, 2 warning, 1 info | 4 |

**Critical:** `DQ-2026-0001` must be the canonical null_spike/critical record for `orders.customer_id` — it is referenced by name in the demo scenario. All metadata list fields **must be comma-separated strings** (not JSON arrays) — Chroma does not support `List[str]` metadata.

**`demo-data/seed_data/playbooks.json`** — 10 records
- Required types: `rollback`, `backfill`, `quarantine`, `notify`, `schema_fix`, `pipeline_restart`
- `PB-ROLLBACK-001` must be the canonical rollback playbook (referenced in demo scenario)
- `applicable_anomaly_types` field: comma-separated string

**`demo-data/seed_data/business_context.json`** — 10 records
- Must include: `orders`, `customers`, `products`, `revenue_report`, `customer_segment_model`, `marketing_pipeline`, `finance_dashboard` (+ 3 more)
- `orders` record: `sla_hours=2.0`, `criticality=critical`
- `downstream_consumers` field: comma-separated string

### Phase 2B — MCP Servers

All three follow the same pattern: `from fastmcp import FastMCP`, mount at `/mcp` inside a FastAPI wrapper that also exposes `GET /health`. Return types from tools must be plain `dict`/`list` (not Pydantic models) for MCP JSON serialization.

**`mcp-servers/great-expectations/server.py`** — port 8081
- Initialize a GX FileSystem context at module startup
- `load_dataset(dataset_id, file_path)` → `{"dataset_id", "row_count", "columns", "loaded"}`
- `create_expectation_suite(dataset_id, suite_name, auto_generate=True)` — naming convention: `{dataset_id}_suite`; use GX DataAssistant for auto-generation → `{"suite_name", "expectation_count", "created"}`
- `run_checkpoint(dataset_id, suite_name)` → `{"success", "result_url", "statistics": {"evaluated", "successful", "unsuccessful"}}`
- `get_validation_results(dataset_id, suite_name)` → full GX result JSON with `"failed_expectations"` list
- Reads from `GX_DATA_DIR` env var (default `/demo-data`)

**`mcp-servers/monte-carlo-mock/server.py`** — port 8082
- Load `anomalies.json` at startup for deterministic mock responses
- `get_table_health("orders")` must return `volume_change_pct=-0.2`, `status="degraded"` (drives demo)
- `get_anomalies("orders", 24)` must return the null_spike anomaly record matching `DQ-2026-0001`
- `get_lineage(table_name, depth)` → `{"upstream": [...], "downstream": [...], "graph": {}}`
- `query_catalog(search_term, limit)` → list of catalog entries

**`mcp-servers/custom/server.py`** — port 8083
- Initialize `chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)` at startup
- `analyze_data_lineage("orders", depth=3)` must return: `upstream=["api_gateway","user_service"]`, `downstream=["revenue_report","customer_segment_model","marketing_pipeline","finance_dashboard"]`, `impact_radius=7`, `critical_consumers=["revenue_report"]`
- `assess_business_impact(table_name, anomaly_type, severity)` → SLA and team impact from seed data
- `apply_remediation(anomaly_id, action, dry_run=True)` — default `dry_run=True` ALWAYS; when dry_run returns `{"status":"dry_run","records_affected":500,"rollback_available":true}`
- `get_similar_anomalies(description, anomaly_type, limit=5)` — calls Chroma `anomaly_patterns` collection via `collection.query()`

### Phase 2C — RAG Layer

**`src/rag/indexer.py`**
- `DataQualityIndexer.__init__(chroma_host, chroma_port)`: `chromadb.HttpClient`, `OpenAIEmbedding(model="text-embedding-3-large")`, `SemanticSplitterNodeParser(buffer_size=1, breakpoint_percentile_threshold=95, embed_model=...)`
- `index_documents(collection_name, documents)` → int: chunks via splitter, upserts to Chroma; add `lists_to_strings(metadata)` utility to enforce comma-separated constraint
- `upsert_document(collection_name, doc_id, content, metadata)` → None
- `get_collection_stats()` → `{collection_name: count}` for all 4 collections
- Note: short seed docs (2-5 sentences) may not split — the splitter returns a single node; this is fine

**`src/rag/retriever.py`**
- `DataQualityRetriever.__init__(chroma_host, chroma_port, embeddings)`: build one `EnsembleRetriever([vector_retriever, bm25_retriever], weights=[0.7, 0.3])` wrapped in `ContextualCompressionRetriever(CrossEncoderReranker(HuggingFaceCrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2"), top_n=5))` per collection
- **BM25 initialization**: call `collection.get(include=["documents","metadatas"])` at init to build BM25 corpus; **initialize lazily** (first query, not at FastAPI startup) to avoid empty-corpus failures before seeding
- 4 query methods: `retrieve_similar_anomalies(query, anomaly_type=None, severity=None, days_lookback=90)`, `retrieve_playbook(query, anomaly_type)`, `retrieve_business_context(table_name)`, `retrieve_dq_rules(table_name, rule_type=None)`

**`scripts/seed_demo_data.py`** — 8-step sequence:
1. Connect to Chroma
2. Delete and recreate all 4 collections (clean slate)
3. Index `anomalies.json` → `anomaly_patterns`
4. Index `playbooks.json` → `remediation_playbooks`
5. Index `business_context.json` → `business_context`
6. Programmatically generate ≥10 DQ rules → index into `dq_rules`
7. Print collection document counts
8. `sys.exit(0)` on success, `sys.exit(1)` on any exception

**`scripts/reset_demo.sh`** — with `set -e` at top:
```bash
docker compose down
rm -rf ./data/chroma/* ./data/sqlite/*
docker compose up -d
sleep 30
docker compose exec app python scripts/seed_demo_data.py
```

### Phase 2 Gate
```bash
docker compose up -d chroma mcp-gx mcp-mc mcp-custom
curl http://localhost:8081/health   # {"status":"ok","server":"great-expectations"}
curl http://localhost:8082/health   # {"status":"ok","server":"monte-carlo-mock"}
curl http://localhost:8083/health   # {"status":"ok","server":"custom"}

OPENAI_API_KEY=sk-... CHROMA_HOST=localhost CHROMA_PORT=8001 \
  python scripts/seed_demo_data.py
# Expected output: all 4 collections show > 0 documents
```

---

## Phase 3 — Agent Implementations

**Goal:** All 7 agent node functions implemented. LangGraph `StateGraph` compiles.

**Dependencies:** Phase 1 (config + schemas) and Phase 2 (MCP servers + RAG) must be complete.

### `safe_agent_node` wrapper — implement in `src/agents/workflow.py` first

```python
def safe_agent_node(agent_fn):
    @wraps(agent_fn)
    async def wrapped(state: DataQualityState) -> dict:
        start = time.monotonic()
        try:
            result = await agent_fn(state)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            latencies = dict(state.get("agent_latencies", {}))
            latencies[agent_fn.__name__] = elapsed_ms
            return {**result, "agent_latencies": latencies}
        except Exception as e:
            logger.error(f"{agent_fn.__name__} failed: {e}", exc_info=True)
            return {"errors": state.get("errors", []) + [f"{agent_fn.__name__}: {str(e)}"]}
    return wrapped
```

### MCP client initialization — module-level in `src/agents/workflow.py`
```python
mcp_toolkit = MCPToolkit(servers={
    "gx":     os.getenv("MCP_GX_URL",     "http://mcp-gx:8081/mcp"),
    "mc":     os.getenv("MCP_MC_URL",     "http://mcp-mc:8082/mcp"),
    "custom": os.getenv("MCP_CUSTOM_URL", "http://mcp-custom:8083/mcp"),
})
gx_tools = mcp_toolkit.get_tools(server="gx")
mc_tools = mcp_toolkit.get_tools(server="mc")
custom_tools = mcp_toolkit.get_tools(server="custom")
```

### Memory-aware agent pattern (required for all 6 non-orchestrator agents)
1. `past = long_term_memory.get_similar_decisions(agent_name, decision_type, description)`
2. Build prompt with `past` as historical context
3. `result = await invoke_with_retry(MODELS["tier_N"], prompt)` with `PydanticOutputParser`
4. `long_term_memory.record_decision(AgentDecision(...))`
5. Return `{result_field: result.model_dump(), "current_phase": "...", ...}`

### Agent file list

| File | LLM | MCP tools | RAG collection | Output | Sets phase |
|---|---|---|---|---|---|
| `src/agents/orchestrator.py` | tier1 | — | `business_context` | routing | all transitions |
| `src/agents/validation.py` | tier3 | gx: `create_expectation_suite`, `run_checkpoint`, `get_validation_results` | `dq_rules` | `ValidationResult` | — |
| `src/agents/detection.py` | tier2 | mc: `get_table_health`, `get_anomalies` | `anomaly_patterns` | `DetectionResult` | `detection_complete` |
| `src/agents/diagnosis.py` | tier1 | mc: `get_anomalies` | `anomaly_patterns`, `remediation_playbooks` | `DiagnosisResult` | — |
| `src/agents/lineage.py` | tier2 | custom: `analyze_data_lineage` | `business_context` | `LineageResult` | `diagnosis_complete` |
| `src/agents/business_impact.py` | tier1 | custom: `assess_business_impact` | `business_context` | `BusinessImpactResult` | — |
| `src/agents/repair.py` | tier2 | custom: `apply_remediation`, `get_similar_anomalies` | `remediation_playbooks` | `RemediationPlan` + `RemediationOutcome` | `remediation_complete` + `workflow_complete=True` |

**Repair agent note:** Only pass `dry_run=False` to `apply_remediation` when `state["should_auto_remediate"] is True AND risk_level == "low"`. The demo always has `should_auto_remediate=False`.

### `src/agents/workflow.py` — complete the `build_workflow()` function

```python
def build_workflow(sqlite_path: str) -> CompiledGraph:
    memory = SqliteSaver.from_conn_string(sqlite_path)
    graph = StateGraph(DataQualityState)

    graph.add_node("orchestrator",    safe_agent_node(orchestrator_node))
    graph.add_node("validation",      safe_agent_node(validation_node))
    graph.add_node("detection",       safe_agent_node(detection_node))
    graph.add_node("diagnosis",       safe_agent_node(diagnosis_node))
    graph.add_node("lineage",         safe_agent_node(lineage_node))
    graph.add_node("business_impact", safe_agent_node(business_impact_node))
    graph.add_node("repair",          safe_agent_node(repair_node))

    graph.set_entry_point("orchestrator")
    graph.add_conditional_edges("orchestrator", route_from_orchestrator, {
        "validation":      "validation",
        "diagnosis":       "diagnosis",
        "business_impact": "business_impact",
        "complete":        END,
    })
    graph.add_edge("validation",      "detection")
    graph.add_edge("detection",       "orchestrator")
    graph.add_edge("diagnosis",       "lineage")
    graph.add_edge("lineage",         "orchestrator")
    graph.add_edge("business_impact", "repair")
    graph.add_edge("repair",          "orchestrator")

    return graph.compile(checkpointer=memory)
```

**Critical:** `route_from_orchestrator` return values must exactly match the keys in the mapping dict above — `KeyError` at runtime if any value is missing.

### Phase 3 Gate
```bash
# Test graph compilation
python -c "
from src.agents.workflow import build_workflow
import os; os.makedirs('/tmp/test_sqlite', exist_ok=True)
app = build_workflow('/tmp/test_sqlite/test.db')
print(app.get_graph().draw_mermaid())
"
# Verify 7 nodes and correct edges in the Mermaid output

# Single-agent smoke test (requires OPENAI_API_KEY + running MCP servers)
python -c "
import asyncio
from src.agents.validation import validation_node
state = {
    'investigation_id': 'test-001', 'triggered_at': '2026-03-02T10:00:00Z',
    'trigger': {'dataset_id': 'orders_2026_03', 'table_name': 'orders',
                'alert_type': 'null_spike', 'description': 'High null rate'},
    'current_phase': 'initial', 'should_auto_remediate': False,
    'workflow_complete': False, 'errors': [], 'agent_latencies': {},
    'validation_result': None, 'detection_result': None, 'diagnosis_result': None,
    'lineage_result': None, 'business_impact': None,
    'remediation_plan': None, 'remediation_result': None, 'severity': None,
}
print(asyncio.run(validation_node(state)))
"
```

---

## Phase 4 — FastAPI Application

**Goal:** All 7 REST endpoints work. Full end-to-end investigation runs via curl.

### Files to create

**`src/api/health.py`**
- `GET /health`: probe all 5 dependencies concurrently via `asyncio.gather` with 5s timeout each
- Chroma: `GET http://{CHROMA_HOST}:{CHROMA_PORT}/api/v1/heartbeat`
- MCP servers: replace `/mcp` with `/health` in each URL
- Include `cost_tracker.report()` in response as `"cost_session"`
- Return `{"status": "healthy"|"degraded", "checks": {...}, "cost_session": {...}}`

**`src/api/routes.py`**
- `POST /api/v1/investigations` (202): generate UUID4, build initial `DataQualityState`, launch via FastAPI `BackgroundTasks`, return immediately
- `GET /api/v1/investigations/{id}` (200/404): `workflow_app.get_state({"configurable": {"thread_id": id}})` → `.values` for state dict; handle missing checkpoint → 404
- `POST /api/v1/investigations/{id}/feedback` (200): call `long_term_memory.record_feedback()`
- `GET /api/v1/investigations` (200): query `decisions.db` for distinct `investigation_id` with optional `severity` filter
- `POST /api/v1/rag/query` (200): call appropriate `DataQualityRetriever` method based on `collection` field
- `POST /api/v1/rag/index` (200): call `DataQualityIndexer.index_documents()`
- Access singletons via `request.app.state.workflow`, `request.app.state.long_term_memory`, etc.

**`src/main.py`**
- FastAPI app with title, version, description
- Mount routes at `/api/v1` and health at `/`
- `@app.on_event("startup")`: `os.makedirs` for sqlite dir, call `build_workflow()`, init `LongTermMemory`, init `DataQualityRetriever`, init `DataQualityIndexer`, store all on `app.state`
- Add CORS middleware (`allow_origins=["*"]` for demo)

### Phase 4 Gate
```bash
docker compose up -d chroma mcp-gx mcp-mc mcp-custom app
docker compose ps    # wait for app to be healthy

curl http://localhost:8000/health | python3 -m json.tool
# Expected: {"status":"healthy", all checks healthy}

# Trigger investigation
RESP=$(curl -s -X POST http://localhost:8000/api/v1/investigations \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"orders_2026_03","table_name":"orders","alert_type":"null_spike","description":"High null rate in customer_id"}')
echo $RESP
ID=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['investigation_id'])")

# Poll (takes 30-90s)
curl http://localhost:8000/api/v1/investigations/$ID | python3 -m json.tool
# Expected: "current_phase":"remediation_complete", "severity":"high"

# RAG query test
curl -s -X POST http://localhost:8000/api/v1/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query":"null spike customer_id","collection":"anomaly_patterns","k":3}' \
  | python3 -m json.tool
```

---

## Phase 5 — Streamlit Demo UI

**Goal:** Full demo scenario runs from the browser. All 3 tabs functional.

### `ui/app.py`

**Sidebar:**
- `st.cache_data(ttl=5)` for `/health` polling
- API status badge (green/red `st.markdown()`)
- Session cost display from `cost_session.session_total_usd`
- "Reset Demo" button

**Tab 1 — Run Investigation:**
- `st.form()` for trigger input: `dataset_id`, `table_name`, `alert_type` (selectbox), `description` (text_area)
- On submit: `POST /api/v1/investigations`, store ID in `st.session_state["active_id"]`
- Polling pattern: `while not complete: time.sleep(2); st.rerun()` — DO NOT use bare `while True`; use `st.session_state` to persist state across reruns
- Phase progress: 3 expanders (Detection, Diagnosis, Remediation) that fill in as phases complete
- Severity badge: HTML-colored via `st.markdown()` — red=critical, orange=high, yellow=warning, blue=info
- Agent latencies: `st.bar_chart()` after completion

**Tab 2 — Investigation History:**
- `GET /api/v1/investigations?limit=20`
- `st.dataframe()` — clicking row shows full investigation in `st.expander()`
- "Mark Resolved" / "Mark Unresolved" buttons → `POST /api/v1/investigations/{id}/feedback`

**Tab 3 — Knowledge Base:**
- Text input + collection `selectbox` + k `slider` (1–10)
- "Search" button → `POST /api/v1/rag/query`
- Results as `st.expander()` cards with content, metadata table, score

### Phase 5 Gate
```bash
docker compose up -d
docker compose exec app python scripts/seed_demo_data.py

# Open http://localhost:3000 and walk through all 6 steps of SPEC §15 demo scenario
# Verify: trigger → phases fill in → remediation_complete → severity=high → feedback submitted
```

---

## Phase 6 — Integration Polish

**Goal:** System handles errors gracefully and survives a 30-minute live demo.

### Items

1. **Reset script validation** — run `scripts/reset_demo.sh` end-to-end; increase `sleep` to 45s if healthchecks are slow on demo hardware

2. **Error path testing:**
   - Stop `mcp-gx`, trigger investigation → verify `errors` list is populated, workflow continues to detection (degraded mode)
   - Query table not in seed data → verify RAG returns empty list gracefully, agents do not crash

3. **BM25 empty-corpus guard** — verify retriever handles the case where `DataQualityRetriever` is initialized before seeding (lazy initialization pattern)

4. **Docker image size** — add CPU-only PyTorch install to Dockerfile to reduce image from ~4GB to ~1.5GB:
   ```dockerfile
   RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
   RUN pip install -r requirements.txt
   ```

5. **Feedback loop verification** — run two consecutive null spike investigations; verify the second investigation's `DetectionResult.similar_past_anomalies` includes the first investigation's resolved outcome

6. **SqliteSaver thread safety** — add `check_same_thread=False` to the connection string in `create_checkpointer()` if concurrent investigations cause SQLite errors

---

## Critical Files (by importance)

| File | Why Critical |
|---|---|
| `src/config.py` | Imported by every other module; implement first |
| `src/agents/workflow.py` | Contains both `DataQualityState` (imported everywhere) and the LangGraph graph wiring; routing function exhaustiveness is the most failure-prone integration point |
| `src/rag/retriever.py` | Most architecturally complex; dependency of all agents and `LongTermMemory.get_similar_decisions()` |
| `mcp-servers/custom/server.py` | Only MCP server with Chroma dependency; called by 3 agents (Lineage, Business Impact, Repair) |
| `demo-data/seed_data/anomalies.json` | `DQ-2026-0001` record must exist and match exactly for demo scenario to work |
| `docker-compose.yml` | Service health dependency chain; wrong healthcheck URLs block `app` startup |

---

## Phase Summary

| Phase | Key deliverable | Gate command |
|---|---|---|
| 0 — Scaffold | `docker compose build` | `docker compose build` |
| 1 — Schemas | `from src.config import MODELS` | `python -c "from src.config import MODELS"` |
| 2A — Demo Data | 3 CSVs + 3 JSONs | File existence + valid JSON/CSV format |
| 2B — MCP Servers | 3 `/health` endpoints | `curl localhost:808{1,2,3}/health` |
| 2C — RAG | Seeded Chroma + working retriever | `seed_demo_data.py` + retriever returns docs |
| 3 — Agents | Graph compiles + single agent test | `draw_mermaid()` + validation_node test |
| 4 — FastAPI | End-to-end curl investigation | `remediation_complete` in response |
| 5 — UI | Browser demo | Full 6-step scenario walks through |
| 6 — Polish | Error paths + reset | Reset + second investigation has learning |
