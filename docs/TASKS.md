# Implementation Tasks: Data Quality & Observability Intelligence Platform

> Derived from `docs/PLAN.md`. Check off tasks as completed. Each task maps to one or more files and includes an acceptance criterion.
>
> **Status legend:** `[ ]` pending · `[x]` done · `[~]` in progress · `[!]` blocked

---

## Phase 0 — Project Scaffold

> **Gate:** `docker compose build` succeeds and Chroma heartbeat responds.

### T-00 · Directory skeleton and gitkeep files

- [x] Create `data/chroma/.gitkeep`
- [x] Create `data/sqlite/.gitkeep`
- [x] Create `src/__init__.py` (empty)
- [x] Create `src/agents/__init__.py` (empty)
- [x] Create `src/memory/__init__.py` (empty)
- [x] Create `src/rag/__init__.py` (empty)
- [x] Create `src/api/__init__.py` (empty)
- [x] Create `mcp-servers/great-expectations/` directory
- [x] Create `mcp-servers/monte-carlo-mock/` directory
- [x] Create `mcp-servers/custom/` directory

**Verify:** `git status` shows all files tracked; `ls data/chroma data/sqlite` succeeds.

---

### T-01 · `.gitignore` and `.env.example`

**Files:** `.gitignore`, `.env.example`

- [x] `.gitignore` — entries: `data/`, `.env`, `*.pyc`, `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `gx/`, `great_expectations/uncommitted/`
- [x] `.env.example` — all 17 variables from SPEC §4 with defaults filled in; `OPENAI_API_KEY=sk-...` as the only required placeholder

**Verify:** `.env` is absent from `git status` after `cp .env.example .env`.

---

### T-02 · `requirements.txt`

**File:** `requirements.txt`

- [x] All packages from SPEC §14 with `>=` minimum version pins
- [x] Exact list: `langgraph>=0.2.0`, `langchain-core>=0.3.0`, `langchain>=0.3.0`, `langchain-openai>=0.2.0`, `langchain-chroma>=0.1.0`, `langchain-community>=0.3.0`, `langchain-mcp`, `llama-index>=0.11.0`, `llama-index-embeddings-openai>=0.2.0`, `chromadb>=0.5.0`, `sentence-transformers>=3.0.0`, `fastmcp`, `fastapi`, `uvicorn[standard]`, `httpx`, `pydantic>=2.0`, `tenacity`, `tiktoken`, `streamlit`, `python-dotenv`

**Verify:** `pip install --dry-run -r requirements.txt` exits 0.

---

### T-03 · `Dockerfile` (main app)

**File:** `Dockerfile`

- [x] Base: `python:3.11-slim`
- [x] CPU-only PyTorch first (reduces image size): `RUN pip install torch --index-url https://download.pytorch.org/whl/cpu`
- [x] Then: `COPY requirements.txt .` → `RUN pip install --no-cache-dir -r requirements.txt`
- [x] `COPY src/ ./src/`
- [x] `COPY scripts/ ./scripts/`
- [x] `COPY demo-data/ ./demo-data/`
- [x] `EXPOSE 8000`
- [x] Health check: `CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]`

**Verify:** `docker build -t dq-app .` succeeds (no source files needed yet — build will succeed, startup will fail).

---

### T-04 · MCP server `Dockerfile` and `requirements.txt` files

**Files:** `mcp-servers/great-expectations/Dockerfile`, `mcp-servers/great-expectations/requirements.txt`, `mcp-servers/monte-carlo-mock/Dockerfile`, `mcp-servers/monte-carlo-mock/requirements.txt`, `mcp-servers/custom/Dockerfile`, `mcp-servers/custom/requirements.txt`, `ui/Dockerfile`

- [x] **GX** (`requirements.txt`): `fastmcp`, `great-expectations`, `pandas`, `fastapi`, `uvicorn`; Dockerfile: `python:3.11-slim`, `EXPOSE 8081`, CMD `python server.py`
- [x] **MC mock** (`requirements.txt`): `fastmcp`, `fastapi`, `uvicorn`; Dockerfile: `EXPOSE 8082`, CMD `python server.py`
- [x] **Custom** (`requirements.txt`): `fastmcp`, `fastapi`, `uvicorn`, `chromadb`, `httpx`; Dockerfile: `EXPOSE 8083`, CMD `python server.py`
- [x] **UI** (`ui/Dockerfile`): `pip install streamlit httpx`, `EXPOSE 8501`, CMD `streamlit run app.py --server.port=8501 --server.address=0.0.0.0`

**Verify:** Each image builds (even without `server.py` present, the requirements install step must succeed).

---

### T-05 · `docker-compose.yml`

**File:** `docker-compose.yml`

- [x] `version: "3.8"`
- [x] **`app`** service: build `.`, ports `8000:8000`, all env vars, volumes `./data:/data` and `./demo-data:/demo-data:ro`, depends_on chroma/mcp-gx/mcp-mc/mcp-custom with `condition: service_healthy`, healthcheck `curl -f http://localhost:8000/health`
- [x] **`chroma`** service: `image: chromadb/chroma:latest`, ports `8001:8000`, volume `./data/chroma:/chroma/chroma`, env `ANONYMIZED_TELEMETRY=false`, healthcheck `curl -f http://localhost:8000/api/v1/heartbeat`
- [x] **`mcp-gx`** service: build `./mcp-servers/great-expectations`, ports `8081:8081`, volume `./demo-data:/demo-data:ro`, env `GX_DATA_DIR=/demo-data`, healthcheck `curl -f http://localhost:8081/health`
- [x] **`mcp-mc`** service: build `./mcp-servers/monte-carlo-mock`, ports `8082:8082`, volume `./demo-data:/demo-data:ro`, healthcheck `curl -f http://localhost:8082/health`
- [x] **`mcp-custom`** service: build `./mcp-servers/custom`, ports `8083:8083`, env `CHROMA_HOST=chroma CHROMA_PORT=8000`, depends_on chroma healthy, healthcheck `curl -f http://localhost:8083/health`
- [x] **`demo-ui`** service: build `./ui`, ports `3000:8501`, env `API_URL=http://app:8000`, depends_on app healthy
- [x] `networks: default: name: demo-network`

**Verify (Phase 0 Gate):**
```bash
docker compose build
docker compose up -d chroma
curl http://localhost:8001/api/v1/heartbeat
# Expected: {"nanosecond heartbeat": <number>}
```

---

## Phase 1 — Core Schemas and Configuration

> **Gate:** `python -c "from src.config import MODELS; print('OK')"` succeeds with `OPENAI_API_KEY` set.
> **Dependency:** Phase 0 complete.

### T-10 · `src/config.py`

**File:** `src/config.py`

- [x] `from dotenv import load_dotenv; load_dotenv()` at module top
- [x] All env var constants: `CHROMA_HOST`, `CHROMA_PORT`, `MCP_GX_URL`, `MCP_MC_URL`, `MCP_CUSTOM_URL`, `SQLITE_PATH`, `DECISIONS_DB_PATH`, `CHROMA_DATA_PATH`, `LOG_LEVEL`, `COST_TRACKING_ENABLED`, `COST_ALERT_THRESHOLD`, `MAX_REQUESTS_PER_MINUTE`, `MEMORY_RETENTION_DAYS`
- [x] `MODELS` dict with 4 entries: `tier1_reasoning` (gpt-4o, temp=0.1, max_tokens=4096, timeout=60), `tier2_structured` (gpt-4o-mini, temp=0.0, max_tokens=2048, timeout=30), `tier3_simple` (gpt-4o-mini, temp=0.0, max_tokens=1024, timeout=15), `embeddings` (text-embedding-3-large, dimensions=3072)
- [x] `PRICING` dict: `{"gpt-4o": {"input": 0.0025, "output": 0.010}, "gpt-4o-mini": {"input": 0.00015, "output": 0.0006}, "text-embedding-3-large": {"input": 0.00013, "output": 0.0}}`
- [x] `CostTracker` class: `__init__` sets `_session_cost=0.0`, `_investigation_costs={}`; `record(model, investigation_id, input_tokens, output_tokens) -> float`; `report() -> dict` with `session_total_usd`, `investigation_count`, `avg_per_investigation_usd`
- [x] `invoke_with_retry` async fn with `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=60), reraise=True)`
- [x] Module-level singleton: `cost_tracker = CostTracker()`

**Verify:** `from src.config import MODELS, cost_tracker, invoke_with_retry` imports without error.

---

### T-11 · `src/agents/workflow.py` — state schemas only

**File:** `src/agents/workflow.py`

- [x] `DataQualityState` TypedDict — all 20 fields from SPEC §5.1: `investigation_id`, `triggered_at`, `trigger`, `validation_result`, `detection_result`, `diagnosis_result`, `lineage_result`, `business_impact`, `remediation_plan`, `remediation_result`, `current_phase`, `severity`, `should_auto_remediate`, `workflow_complete`, `errors`, `agent_latencies`
  *(Note: `agent_latencies` is field 16; SPEC lists 20 fields total — count carefully)*
- [x] `WorkflowMemory` TypedDict — 6 fields: `investigation_id`, `started_at`, `shared_context`, `agent_messages`, `decisions`, `agent_latencies`
- [x] No `build_workflow()` yet — that is added in T-31 (Phase 3)

**Verify:** `from src.agents.workflow import DataQualityState, WorkflowMemory` imports cleanly.

---

### T-12 · `src/agents/orchestrator.py` — Pydantic models and routing stub

**File:** `src/agents/orchestrator.py`

- [x] All 8 Pydantic v2 models from SPEC §5.4:
  - `InvestigationTrigger` (5 fields)
  - `ValidationResult` (6 fields)
  - `DetectionResult` (10 fields including `similar_past_anomalies: List[dict]`)
  - `DiagnosisResult` (8 fields)
  - `LineageResult` (7 fields)
  - `BusinessImpactResult` (7 fields)
  - `RemediationPlan` (8 fields)
  - `RemediationOutcome` (5 fields)
- [x] `route_from_orchestrator(state: DataQualityState) -> Literal["validation","diagnosis","business_impact","complete"]` — stub body `raise NotImplementedError` (replaced in T-30)

**Verify:** `from src.agents.orchestrator import InvestigationTrigger, RemediationPlan` and `t = InvestigationTrigger(dataset_id="x", table_name="t", alert_type="null_spike", description="test")` both succeed.

---

### T-13 · `src/memory/short_term.py`

**File:** `src/memory/short_term.py`

- [x] `create_checkpointer(sqlite_path: str) -> SqliteSaver`: calls `os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)` then `SqliteSaver.from_conn_string(sqlite_path)`
- [x] `update_shared_context(state: dict, agent_name: str, findings_summary: str) -> dict`: returns `{"shared_context": {**state.get("shared_context", {}), agent_name: findings_summary}}`
- [x] `record_agent_latency(state: dict, agent_name: str, elapsed_ms: int) -> dict`: returns `{"agent_latencies": {**state.get("agent_latencies", {}), agent_name: elapsed_ms}}`

**Verify:** `from src.memory.short_term import create_checkpointer` imports; calling `create_checkpointer("/tmp/test/ckpt.db")` creates the parent directory and returns a `SqliteSaver` instance.

---

### T-14 · `src/memory/long_term.py`

**File:** `src/memory/long_term.py`

- [x] `AgentDecision` dataclass with 9 fields: `decision_id`, `investigation_id`, `agent_name`, `decision_type`, `input_summary`, `output_summary`, `confidence`, `was_correct: Optional[bool]`, `created_at: datetime`
- [x] `LongTermMemory.__init__(db_path: str, rag_retriever=None)`: calls `os.makedirs` guard, opens SQLite connection with `check_same_thread=False`, creates `agent_decisions` table and 2 indexes (DDL from SPEC §9.2)
- [x] `record_decision(decision: AgentDecision) -> None`: INSERT into `agent_decisions`
- [x] `get_similar_decisions(agent_name, decision_type, input_description, k=5) -> List[dict]`: returns `[]` if `self.rag_retriever is None`; otherwise SQL filter by `agent_name`+`decision_type` then RAG semantic search on `input_description`
- [x] `record_feedback(investigation_id, was_resolved: bool, resolution_notes: str) -> int`: UPDATE `was_correct` for all decisions with matching `investigation_id`; returns row count
- [x] `cleanup_old_memory(days_to_keep: int = 90) -> int`: DELETE decisions older than cutoff where `was_correct != 1`; returns row count

**Verify (Phase 1 Gate):**
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

## Phase 2A — Demo Data Files

> **Gate:** All 6 data files present and valid. `python -c "import json,csv; ..."` parses each without error.
> **Dependency:** Phase 0 complete. Runs in parallel with 2B and 2C.

### T-20 · Sample dataset CSV files

**Files:** `demo-data/sample_datasets/orders.csv`, `demo-data/sample_datasets/customers.csv`, `demo-data/sample_datasets/products.csv`

- [x] **`orders.csv`** — 10,000 rows; columns: `order_id` (UUID4), `customer_id` (UUID4, **exactly 500 rows = null**), `product_id` (UUID4), `order_date` (ISO date, random within last 90 days), `amount` (2dp float, $0.01–$5000.00), `status` (weighted random: mostly shipped/delivered), `region` (US/EU/APAC/LATAM)
- [x] **`customers.csv`** — 5,000 rows; `phone` column: 60% are 10-char strings like `"5551234567"`, 40% are 15-char strings like `"+15551234567890"` — intentional schema drift trigger
- [x] **`products.csv`** — 1,000 rows; clean reference data, no nulls, no defects; columns: `product_id`, `name`, `category`, `price`, `inventory_count`, `last_updated`
- [x] Generate all three with a standalone Python script (not checked in — just run once)

**Verify:** `wc -l demo-data/sample_datasets/orders.csv` = 10001 (header + 10000 rows); `python -c "import csv; rows=list(csv.DictReader(open('demo-data/sample_datasets/orders.csv'))); nulls=sum(1 for r in rows if not r['customer_id']); print(nulls)"` prints a value between 480–520.

---

### T-21 · `demo-data/seed_data/anomalies.json`

**File:** `demo-data/seed_data/anomalies.json`

- [x] JSON array of exactly 20 objects, each with `"id"`, `"content"` (full narrative text), and `"metadata"` object
- [x] **`DQ-2026-0001`** is present, `anomaly_type=null_spike`, `severity=critical`, `affected_tables="orders"`, `root_cause=upstream_api_failure`, `resolution=rollback_and_backfill`, `resolution_time_hours=2.5`
- [x] Coverage: 4 null_spike (2 critical, 2 warning), 4 schema_drift (1 critical, 2 warning, 1 info), 4 volume_drop (2 critical, 2 warning), 4 freshness_lag (1 critical, 3 warning), 4 duplicate_records (1 high, 2 warning, 1 info)
- [x] All metadata list fields are **comma-separated strings**, not JSON arrays (e.g., `"affected_tables": "orders,revenue_report"` not `["orders","revenue_report"]`)
- [x] `detected_at` values are valid ISO 8601 strings; `resolution_time_hours` is a float

**Verify:** `python -c "import json; d=json.load(open('demo-data/seed_data/anomalies.json')); assert len(d)==20; assert any(r['id']=='DQ-2026-0001' for r in d); print('OK')"`.

---

### T-22 · `demo-data/seed_data/playbooks.json` and `business_context.json`

**Files:** `demo-data/seed_data/playbooks.json`, `demo-data/seed_data/business_context.json`

- [x] **`playbooks.json`** — 10 records; `PB-ROLLBACK-001` must be present with `playbook_type=rollback`; all 6 types covered: `rollback`, `backfill`, `quarantine`, `notify`, `schema_fix`, `pipeline_restart`; `applicable_anomaly_types` is a comma-separated string
- [x] **`business_context.json`** — 10 records; must include `orders` (`sla_hours=2.0`, `criticality=critical`), `customers`, `products`, `revenue_report`, `customer_segment_model`, `marketing_pipeline`, `finance_dashboard`, plus 3 additional tables; `downstream_consumers` is a comma-separated string

**Verify:** `python -c "import json; p=json.load(open('demo-data/seed_data/playbooks.json')); assert len(p)==10; assert any(r['id']=='PB-ROLLBACK-001' for r in p); b=json.load(open('demo-data/seed_data/business_context.json')); assert any(r['metadata']['table_name']=='orders' for r in b); print('OK')"`.

---

## Phase 2B — MCP Servers

> **Gate:** `curl http://localhost:808{1,2,3}/health` all return `{"status":"ok"}`.
> **Dependency:** Phase 0 complete. Runs in parallel with 2A and 2C.

### T-23 · `mcp-servers/great-expectations/server.py`

**File:** `mcp-servers/great-expectations/server.py`

- [x] FastAPI app wrapping FastMCP; MCP mounted at `/mcp`; `GET /health` → `{"status":"ok","server":"great-expectations"}`
- [x] GX FileSystem context initialized at module startup using `GX_DATA_DIR` env var
- [x] `load_dataset(dataset_id: str, file_path: str) -> dict`: loads CSV from `GX_DATA_DIR/file_path`; returns `{"dataset_id", "row_count", "columns", "loaded": True}`
- [x] `create_expectation_suite(dataset_id: str, suite_name: str, auto_generate: bool = True) -> dict`: creates `{dataset_id}_suite`; uses GX Onboarding DataAssistant for auto-generation; returns `{"suite_name", "expectation_count", "created": True}`
- [x] `run_checkpoint(dataset_id: str, suite_name: str) -> dict`: runs GX validation; returns `{"success": bool, "result_url": str, "statistics": {"evaluated", "successful", "unsuccessful"}}`
- [x] `get_validation_results(dataset_id: str, suite_name: str) -> dict`: returns full GX result including `"failed_expectations": [str]`
- [x] All tool functions return plain `dict`, not Pydantic models

**Verify:** `docker compose up -d mcp-gx && curl http://localhost:8081/health` → `{"status":"ok","server":"great-expectations"}`.

---

### T-24 · `mcp-servers/monte-carlo-mock/server.py`

**File:** `mcp-servers/monte-carlo-mock/server.py`

- [x] FastAPI app wrapping FastMCP; `GET /health` → `{"status":"ok","server":"monte-carlo-mock"}`
- [x] Loads `DEMO_DATA_DIR/seed_data/anomalies.json` at startup for deterministic responses
- [x] `get_table_health(table_name: str) -> dict`: for `orders` returns `{"table":"orders","freshness_hours":1.2,"row_count":10000,"volume_change_pct":-0.2,"status":"degraded"}`; all other tables return healthy baseline
- [x] `get_anomalies(table_name: str, hours_lookback: int = 24) -> list`: for `orders` returns `[{"anomaly_id":"DQ-2026-0001","type":"null_spike","severity":"critical","detected_at":"<now-1h>","metric":0.05,"baseline":0.001}]`; empty list for unknown tables
- [x] `get_lineage(table_name: str, depth: int = 2) -> dict`: returns `{"upstream":[...],"downstream":[...],"graph":{}}`
- [x] `query_catalog(search_term: str, limit: int = 10) -> list`: returns matching entries from a hardcoded catalog

**Verify:** `docker compose up -d mcp-mc && curl http://localhost:8082/health` → `{"status":"ok","server":"monte-carlo-mock"}`.

---

### T-25 · `mcp-servers/custom/server.py`

**File:** `mcp-servers/custom/server.py`

- [x] FastAPI app wrapping FastMCP; `GET /health` → `{"status":"ok","server":"custom-tools"}`
- [x] `chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)` initialized at startup
- [x] `analyze_data_lineage(table_name: str, depth: int = 3) -> dict`: for `orders` returns `{"table":"orders","upstream":["api_gateway","user_service"],"downstream":["revenue_report","customer_segment_model","marketing_pipeline","finance_dashboard"],"impact_radius":7,"critical_consumers":["revenue_report"]}`; other tables return shallow mock lineage
- [x] `assess_business_impact(table_name: str, anomaly_type: str, severity: str) -> dict`: returns `{"affected_slas":[...],"teams":[...],"estimated_delay_hours":float,"escalation_required":bool}` sourced from business context data
- [x] `apply_remediation(anomaly_id: str, action: str, dry_run: bool = True) -> dict`: **default `dry_run=True` always**; dry run returns `{"status":"dry_run","action":action,"records_affected":500,"rollback_available":True}`; non-dry-run returns `{"status":"applied",...}`
- [x] `get_similar_anomalies(description: str, anomaly_type: str, limit: int = 5) -> list`: calls `chroma_client.get_collection("anomaly_patterns").query(query_texts=[description], n_results=limit)`; returns `[{"anomaly_id","similarity","resolution","resolution_time_hours"}]`

**Verify (Phase 2B Gate):**
```bash
docker compose up -d chroma mcp-gx mcp-mc mcp-custom
curl http://localhost:8081/health
curl http://localhost:8082/health
curl http://localhost:8083/health
```

---

## Phase 2C — RAG Layer

> **Gate:** `seed_demo_data.py` runs successfully; all 4 Chroma collections have `> 0` documents; `DataQualityRetriever` returns results for a test query.
> **Dependency:** Phase 0 complete. Runs in parallel with 2A and 2B. Requires Chroma running.

### T-26 · `src/rag/indexer.py`

**File:** `src/rag/indexer.py`

- [x] `DataQualityIndexer.__init__(chroma_host: str, chroma_port: int)`: creates `chromadb.HttpClient`, instantiates `OpenAIEmbedding(model="text-embedding-3-large")`, instantiates `SemanticSplitterNodeParser(buffer_size=1, breakpoint_percentile_threshold=95, embed_model=self.embed_model)`
- [x] `lists_to_strings(metadata: dict) -> dict`: converts any `list` value to `", ".join(str(x) for x in v)` — enforces Chroma's no-list-metadata constraint
- [x] `index_documents(collection_name: str, documents: list) -> int`: gets-or-creates Chroma collection, iterates documents (each has `"id"`, `"content"`, `"metadata"`), runs content through `SemanticSplitterNodeParser`, calls `lists_to_strings` on metadata, upserts to Chroma; returns count of documents indexed
- [x] `upsert_document(collection_name: str, doc_id: str, content: str, metadata: dict) -> None`: single-document upsert using `collection.upsert()`
- [x] `get_collection_stats() -> dict`: returns `{name: collection.count()}` for all 4 collections: `anomaly_patterns`, `dq_rules`, `remediation_playbooks`, `business_context`

**Verify:** `from src.rag.indexer import DataQualityIndexer` imports; instantiating with `localhost:8001` (Chroma running) succeeds.

---

### T-27 · `src/rag/retriever.py`

**File:** `src/rag/retriever.py`

- [x] `DataQualityRetriever.__init__(chroma_host, chroma_port, embeddings)`: stores params; sets `self._retrievers = {}` (lazy-init dict); stores embeddings model
- [x] `_build_retriever(collection_name: str)` (private): loads all docs from Chroma collection (`collection.get(include=["documents","metadatas"])`), builds `BM25Retriever.from_documents(docs)`, builds `Chroma` LangChain wrapper + vector retriever, builds `EnsembleRetriever([vector, bm25], weights=[0.7, 0.3])`, wraps in `ContextualCompressionRetriever(CrossEncoderReranker(HuggingFaceCrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2"), top_n=5))`, caches in `self._retrievers[collection_name]`
- [x] `_get_retriever(collection_name: str)`: returns cached or calls `_build_retriever` — **lazy initialization, not called at startup**
- [x] `retrieve_similar_anomalies(query, anomaly_type=None, severity=None, days_lookback=90) -> List[Document]`: uses `anomaly_patterns` retriever; passes `where` filter if `anomaly_type` or `severity` provided
- [x] `retrieve_playbook(query, anomaly_type) -> List[Document]`: uses `remediation_playbooks` retriever; filter by `applicable_anomaly_types` containing `anomaly_type`
- [x] `retrieve_business_context(table_name) -> List[Document]`: uses `business_context` retriever; filter `{"table_name": table_name}`
- [x] `retrieve_dq_rules(table_name, rule_type=None) -> List[Document]`: uses `dq_rules` retriever; filter by `applies_to` matching `table_name` or `"*"`

**Verify:** After seeding, `r.retrieve_similar_anomalies("null values in customer_id column", anomaly_type="null_spike")` returns at least 1 document.

---

### T-28 · `scripts/seed_demo_data.py` and `scripts/reset_demo.sh`

**Files:** `scripts/seed_demo_data.py`, `scripts/reset_demo.sh`

- [x] **`seed_demo_data.py`** — 8 sequential steps:
  1. Connect to Chroma via `CHROMA_HOST`/`CHROMA_PORT` env vars
  2. Delete and recreate all 4 collections (ensures clean slate on re-seed)
  3. Load + index `demo-data/seed_data/anomalies.json` → `anomaly_patterns`
  4. Load + index `demo-data/seed_data/playbooks.json` → `remediation_playbooks`
  5. Load + index `demo-data/seed_data/business_context.json` → `business_context`
  6. Programmatically generate ≥10 DQ rules (one per expectation type per key table) → index into `dq_rules`
  7. Print collection document counts
  8. `sys.exit(0)` on success, `sys.exit(1)` on any exception
- [x] **`reset_demo.sh`** — `#!/bin/bash`, `set -e`, sequence: `docker compose down`, `rm -rf ./data/chroma/* ./data/sqlite/*`, `docker compose up -d`, `sleep 30`, `docker compose exec app python scripts/seed_demo_data.py`; `chmod +x scripts/reset_demo.sh`

**Verify (Phase 2 Gate):**
```bash
OPENAI_API_KEY=sk-... CHROMA_HOST=localhost CHROMA_PORT=8001 \
  python scripts/seed_demo_data.py
# Expected: "anomaly_patterns: 20", "remediation_playbooks: 10", etc.
```

---

## Phase 3 — Agent Implementations

> **Gate:** `build_workflow()` compiles; `draw_mermaid()` shows 7 nodes; single-agent smoke test passes.
> **Dependency:** Phase 1 AND Phase 2 (all sub-phases) complete.

### T-30 · `src/agents/orchestrator.py` — complete implementation

**File:** `src/agents/orchestrator.py` (extends T-12)

- [x] Add `orchestrator_node(state: DataQualityState) -> dict` async function: queries `business_context` RAG for the table being investigated; logs phase transition; returns `{}` (state is managed by phase fields set by other agents — orchestrator is primarily a routing node)
- [x] Replace `route_from_orchestrator` stub with full implementation:
  ```python
  def route_from_orchestrator(state):
      phase = state["current_phase"]
      if phase == "initial": return "validation"
      if phase == "detection_complete":
          return "diagnosis" if state.get("detection_result", {}).get("anomaly_detected") else "complete"
      if phase == "diagnosis_complete":
          return "business_impact" if state.get("severity") in ("critical","high") else "complete"
      return "complete"
  ```
- [x] Add `safe_agent_node(agent_fn)` wrapper function (PLAN §Phase 3); import `time`, `logging`, `functools.wraps`
- [x] Add module-level MCP toolkit initialization (PLAN §Phase 3): `mcp_toolkit`, `gx_tools`, `mc_tools`, `custom_tools`

**Verify:** `from src.agents.orchestrator import route_from_orchestrator, safe_agent_node, orchestrator_node` imports; calling `route_from_orchestrator({"current_phase":"initial"})` returns `"validation"`.

---

### T-31 · `src/agents/workflow.py` — complete `build_workflow()`

**File:** `src/agents/workflow.py` (extends T-11)

- [x] Add imports: `StateGraph`, `END` from `langgraph.graph`; `SqliteSaver` from `langgraph.checkpoint.sqlite`; all 7 agent node functions
- [x] `build_workflow(sqlite_path: str) -> CompiledGraph`: creates `SqliteSaver`, builds full `StateGraph(DataQualityState)`, registers all 7 nodes with `safe_agent_node`, sets entry point, adds all conditional and fixed edges, returns `graph.compile(checkpointer=memory)`
- [x] Graph edges exactly as in PLAN §Phase 3: `validation→detection→orchestrator`, `diagnosis→lineage→orchestrator`, `business_impact→repair→orchestrator`
- [x] Conditional edge mapping is exhaustive: `{"validation","diagnosis","business_impact","complete":END}`

**Verify:**
```bash
python -c "
from src.agents.workflow import build_workflow
import os; os.makedirs('/tmp/test_sqlite', exist_ok=True)
app = build_workflow('/tmp/test_sqlite/test.db')
print(app.get_graph().draw_mermaid())
"
# Must show 7 nodes
```

---

### T-32 · `src/agents/validation.py`

**File:** `src/agents/validation.py`

- [x] Uses `MODELS["tier3_simple"]` (gpt-4o-mini)
- [x] Retrieves `dq_rules` from RAG for the trigger's `table_name`
- [x] Gets past decisions from `long_term_memory.get_similar_decisions("validation_agent", "validation", description)`
- [x] Calls MCP tools in sequence: `create_expectation_suite(dataset_id, f"{dataset_id}_suite")` → `run_checkpoint(dataset_id, suite_name)` → `get_validation_results(dataset_id, suite_name)`
- [x] LLM synthesizes GX results + RAG rules → emits `ValidationResult` via `PydanticOutputParser`
- [x] Records `AgentDecision` in `long_term_memory`
- [x] Returns `{"validation_result": result.model_dump()}`; does **not** set `current_phase`

**Verify:** Smoke test with mock state and running MCP server returns a dict with `"validation_result"` key.

---

### T-33 · `src/agents/detection.py`

**File:** `src/agents/detection.py`

- [x] Uses `MODELS["tier2_structured"]` (gpt-4o-mini)
- [x] Calls MCP: `get_table_health(table_name)` then `get_anomalies(table_name, 24)`
- [x] Queries `anomaly_patterns` RAG: `retrieve_similar_anomalies(description, anomaly_type=trigger["alert_type"])`; stores top 3 as `similar_past_anomalies` in `DetectionResult`
- [x] LLM synthesizes validation result + MC anomalies + RAG matches → emits `DetectionResult`
- [x] Sets initial `severity` from anomaly type if anomaly detected
- [x] Returns `{"detection_result": result.model_dump(), "current_phase": "detection_complete", "severity": ...}`
- [x] Records `AgentDecision`

**Verify:** Returns dict with `"detection_result"` and `"current_phase": "detection_complete"`.

---

### T-34 · `src/agents/diagnosis.py`

**File:** `src/agents/diagnosis.py`

- [x] Uses `MODELS["tier1_reasoning"]` (gpt-4o)
- [x] Calls MCP: `get_anomalies(table_name, 48)` for extended lookback
- [x] Queries RAG: `retrieve_similar_anomalies(description)` and `retrieve_playbook(description, anomaly_type)`
- [x] Prompt includes full `validation_result`, `detection_result`, similar historical anomalies with root causes
- [x] LLM emits `DiagnosisResult` with `severity`, `root_cause`, `root_cause_category`, `confidence`
- [x] Does **not** set `current_phase` (Lineage agent does)
- [x] Returns `{"diagnosis_result": result.model_dump()}`
- [x] Records `AgentDecision`

**Verify:** Returns dict with `"diagnosis_result"` key containing a `severity` field.

---

### T-35 · `src/agents/lineage.py`

**File:** `src/agents/lineage.py`

- [x] Uses `MODELS["tier2_structured"]` (gpt-4o-mini)
- [x] Calls MCP: `analyze_data_lineage(table_name, depth=3)`
- [x] Queries RAG: `retrieve_business_context(table_name)`
- [x] LLM synthesizes lineage graph + business context → emits `LineageResult`
- [x] Sets `current_phase = "diagnosis_complete"` and propagates `severity` from `diagnosis_result["severity"]` (overrides detection's placeholder)
- [x] Returns `{"lineage_result": result.model_dump(), "current_phase": "diagnosis_complete", "severity": diagnosis_severity}`
- [x] Records `AgentDecision`

**Verify:** Returns dict with `"lineage_result"` and `"current_phase": "diagnosis_complete"`.

---

### T-36 · `src/agents/business_impact.py`

**File:** `src/agents/business_impact.py`

- [x] Uses `MODELS["tier1_reasoning"]` (gpt-4o)
- [x] Calls MCP: `assess_business_impact(table_name, anomaly_type, severity)`
- [x] Queries RAG: `retrieve_business_context(table_name)`
- [x] Prompt includes lineage result (downstream tables) + business context + SLA data
- [x] LLM emits `BusinessImpactResult` with `affected_slas`, `business_criticality`, `escalation_required`
- [x] Does **not** set `current_phase`
- [x] Returns `{"business_impact": result.model_dump()}`
- [x] Records `AgentDecision`

**Verify:** Returns dict with `"business_impact"` key containing `escalation_required` bool.

---

### T-37 · `src/agents/repair.py`

**File:** `src/agents/repair.py`

- [x] Uses `MODELS["tier2_structured"]` (gpt-4o-mini)
- [x] Calls MCP: `get_similar_anomalies(description, anomaly_type, limit=3)` then `apply_remediation(anomaly_id, recommended_action, dry_run=True)` *(only `dry_run=False` when `state["should_auto_remediate"] and risk_level == "low"` — demo always uses True)*
- [x] Queries RAG: `retrieve_playbook(description, anomaly_type)`
- [x] LLM synthesizes matched playbook + similar resolutions → emits `RemediationPlan`; `playbook_reference` field populated from RAG match
- [x] Calls `apply_remediation` with the plan's `action_type`; parses response into `RemediationOutcome`
- [x] Sets `current_phase = "remediation_complete"` and `workflow_complete = True`
- [x] Returns `{"remediation_plan": plan.model_dump(), "remediation_result": outcome.model_dump(), "current_phase": "remediation_complete", "workflow_complete": True}`
- [x] Records `AgentDecision` for both plan and outcome

**Verify (Phase 3 Gate):**
```bash
python -c "
from src.agents.workflow import build_workflow
import os; os.makedirs('/tmp/test_sqlite', exist_ok=True)
app = build_workflow('/tmp/test_sqlite/test.db')
mermaid = app.get_graph().draw_mermaid()
assert 'orchestrator' in mermaid
assert 'validation' in mermaid
assert 'repair' in mermaid
print('Graph OK')
"
```

---

## Phase 4 — FastAPI Application

> **Gate:** `GET /health` returns `{"status":"healthy"}`; full investigation via curl reaches `remediation_complete`.
> **Dependency:** Phase 3 complete.

### T-40 · `src/api/health.py`

**File:** `src/api/health.py`

- [x] `APIRouter` with `GET /health`
- [x] Probes 5 services concurrently via `asyncio.gather` with 5s timeout per service:
  - Chroma: `GET http://{CHROMA_HOST}:{CHROMA_PORT}/api/v1/heartbeat`
  - mcp-gx: replace `/mcp` → `/health` in `MCP_GX_URL`
  - mcp-mc: replace `/mcp` → `/health` in `MCP_MC_URL`
  - mcp-custom: replace `/mcp` → `/health` in `MCP_CUSTOM_URL`
  - app itself: always `"healthy"` (self-check)
- [x] Returns `{"status": "healthy" if all pass else "degraded", "checks": {name: "healthy"|"degraded"}, "cost_session": cost_tracker.report()}`
- [x] Uses `httpx.AsyncClient` for async HTTP calls

**Verify:** `curl http://localhost:8000/health` returns JSON with `"status":"healthy"` when all services are up.

---

### T-41 · `src/api/routes.py`

**File:** `src/api/routes.py`

- [x] `APIRouter(prefix="/api/v1")`
- [x] **`POST /investigations`** (202): validate body as `InvestigationTrigger`; generate `investigation_id = str(uuid4())`; build full initial `DataQualityState` with all Optional fields = `None`, `current_phase="initial"`, `errors=[]`, `agent_latencies={}`, `should_auto_remediate=False`, `workflow_complete=False`; add to `BackgroundTasks`; return `{"investigation_id", "status":"started", "triggered_at"}`
- [x] **`GET /investigations/{investigation_id}`** (200/404): load checkpoint via `request.app.state.workflow.get_state({"configurable":{"thread_id":id}})`; return `.values` as response dict; 404 if no checkpoint found
- [x] **`POST /investigations/{investigation_id}/feedback`** (200): call `request.app.state.long_term_memory.record_feedback(id, was_resolved, notes)`; return `{"updated":True,"decisions_updated":int}`
- [x] **`GET /investigations`** (200): query `decisions.db` SQLite directly for distinct `investigation_id` values; support `limit`, `offset`, optional `severity` filter
- [x] **`POST /rag/query`** (200): route to correct `DataQualityRetriever` method based on `collection` field; return `{"results":[{"content","metadata","score"}]}`
- [x] **`POST /rag/index`** (200): call `request.app.state.indexer.index_documents(collection, documents)`; return `{"indexed":int}`

**Verify:** All 6 endpoints return expected status codes; `POST /api/v1/rag/query` returns results after seeding.

---

### T-42 · `src/main.py`

**File:** `src/main.py`

- [x] `FastAPI(title="Data Quality Intelligence API", version="1.0.0")`
- [x] `CORSMiddleware` with `allow_origins=["*"]` for demo
- [x] Include routers: `health_router` (no prefix), `api_router` (prefix `/api/v1`)
- [x] `@app.on_event("startup")` handler:
  1. `os.makedirs` for `SQLITE_PATH` and `DECISIONS_DB_PATH` parent dirs
  2. `app.state.workflow = build_workflow(SQLITE_PATH)`
  3. `app.state.indexer = DataQualityIndexer(CHROMA_HOST, int(CHROMA_PORT))`
  4. `app.state.retriever = DataQualityRetriever(CHROMA_HOST, int(CHROMA_PORT), MODELS["embeddings"])`
  5. `app.state.long_term_memory = LongTermMemory(DECISIONS_DB_PATH, app.state.retriever)`

**Verify (Phase 4 Gate):**
```bash
docker compose up -d chroma mcp-gx mcp-mc mcp-custom app
curl http://localhost:8000/health | python3 -m json.tool
# All checks healthy

RESP=$(curl -s -X POST http://localhost:8000/api/v1/investigations \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"orders_2026_03","table_name":"orders","alert_type":"null_spike","description":"High null rate in customer_id"}')
ID=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['investigation_id'])")
# Poll until complete (30-90s)
curl http://localhost:8000/api/v1/investigations/$ID | python3 -m json.tool
# Expected: "current_phase":"remediation_complete", "severity":"high"
```

---

## Phase 5 — Streamlit Demo UI

> **Gate:** Full 6-step demo scenario from SPEC §15 completes in the browser without errors.
> **Dependency:** Phase 4 complete.

### T-50 · `ui/app.py`

**File:** `ui/app.py`

- [x] `st.set_page_config(page_title="Data Quality Intelligence Platform", layout="wide")`
- [x] **Sidebar:** `@st.cache_data(ttl=5)` health check fn; green/red status badge via `st.markdown()`; session cost `st.metric()`; "Reset Demo" button
- [x] **Tab 1 — Run Investigation:**
  - `st.form()` with fields: `dataset_id` text, `table_name` text, `alert_type` selectbox, `description` text_area
  - On submit: `POST /api/v1/investigations`, save `investigation_id` to `st.session_state["active_id"]`
  - Polling: check `st.session_state["active_id"]`; if set, poll `GET /api/v1/investigations/{id}` every 2s using `time.sleep(2); st.rerun()` pattern
  - Phase progress containers: 3 `st.empty()` blocks that update as `current_phase` advances
  - Severity badge: `st.markdown(f'<span style="color:{color}">■ {severity.upper()}</span>', unsafe_allow_html=True)`
  - Agent latencies: `st.bar_chart(state["agent_latencies"])` after `workflow_complete`
- [x] **Tab 2 — Investigation History:**
  - `GET /api/v1/investigations?limit=20` on tab render
  - `st.dataframe()` with rows; selected row shown in `st.expander()`
  - `st.button("Mark Resolved")` → `POST .../feedback` with `{"was_resolved":True,"resolution_notes":""}`
- [x] **Tab 3 — Knowledge Base:**
  - `st.text_input("Query")`, `st.selectbox("Collection", [...])`, `st.slider("Results", 1, 10, 3)`
  - `st.button("Search")` → `POST /api/v1/rag/query`
  - Results as `st.expander(f"Result {i+1} (score: {score:.3f})")` with `st.json(metadata)` inside

**Verify (Phase 5 Gate):**
```bash
docker compose up -d
docker compose exec app python scripts/seed_demo_data.py
# Open http://localhost:3000
# Walk through SPEC §15 steps 1-6 end-to-end
```

---

## Phase 6 — Integration Polish

> **Goal:** System survives a 30-minute live demo; all error paths are graceful.
> **Dependency:** Phase 5 complete.

### T-60 · Validate reset script end-to-end

- [x] Run `bash scripts/reset_demo.sh` from a fully running stack
- [x] Confirm: containers stop, data dirs cleared, containers restart, seed script runs, Chroma collections re-populated
- [x] If healthchecks time out, increase `sleep` from 30 to 45 in `reset_demo.sh`
- [x] Run the demo scenario once after reset to confirm clean-slate behaviour

**Verify:** Post-reset `GET /health` is healthy and `GET /api/v1/investigations` returns empty list.

---

### T-61 · Docker image size optimisation

**File:** `Dockerfile`

- [x] Confirm `RUN pip install torch --index-url https://download.pytorch.org/whl/cpu` precedes `pip install -r requirements.txt`
- [x] `docker images dq-app` shows image size < 2GB
- [x] If still large: add `--no-cache-dir` to all pip install calls; consider `.dockerignore` to exclude `demo-data/`, `docs/`, `data/`

**Verify:** `docker images | grep dq-app` shows compressed size ≤ 2GB.

---

### T-62 · Graceful degradation — MCP server down

- [x] Stop `mcp-gx` (`docker compose stop mcp-gx`), trigger an investigation
- [x] Verify: `errors` list in state is non-empty; `validation_result` is absent or has `"degraded":True`; workflow continues to Detection (which may also degrade)
- [x] `GET /health` shows `mcp_gx: "degraded"` while `status` is `"degraded"`
- [x] Restart `mcp-gx` (`docker compose start mcp-gx`); next investigation runs cleanly

**Verify:** Investigation triggered with mcp-gx down returns a response (not a 500) with `errors` populated.

---

### T-63 · Graceful degradation — unknown table

- [x] Trigger investigation with `table_name="nonexistent_table"`
- [x] Verify: RAG returns empty list for all 4 queries; agents handle empty RAG results without crashing; investigation still completes (may reach `detection_complete` with `anomaly_detected=False`)
- [x] No unhandled exceptions in `docker compose logs app`

**Verify:** `GET /api/v1/investigations/{id}` returns a valid (possibly shallow) state for the nonexistent-table investigation.

---

### T-64 · BM25 empty-corpus guard

- [x] `docker compose exec app python -c "from src.rag.retriever import DataQualityRetriever; from src.config import MODELS; r = DataQualityRetriever('chroma',8000,MODELS['embeddings']); print(r.retrieve_similar_anomalies('test'))"`
- [x] If Chroma is empty (before seeding), the above must return `[]` without raising — confirms lazy init works
- [x] After seeding, the same call returns documents

**Verify:** No `IndexError` or `ValueError` when retriever is called on empty collection.

---

### T-65 · Feedback learning loop end-to-end

- [x] Trigger investigation #1 (null spike); wait for `remediation_complete`
- [x] Submit feedback: `POST /api/v1/investigations/{id1}/feedback` with `{"was_resolved":true,"resolution_notes":"Rolled back API"}`
- [x] Trigger investigation #2 (same null spike trigger)
- [x] Check that `detection_result.similar_past_anomalies` in investigation #2 includes a reference to investigation #1's resolved outcome
- [x] Verify `decisions.db`: `SELECT COUNT(*) FROM agent_decisions WHERE was_correct=1` > 0

**Verify:** Investigation #2's `DetectionResult` shows at least 1 `similar_past_anomaly` with `resolution` populated.

---

### T-66 · SqliteSaver thread safety check

- [x] Trigger 3 investigations simultaneously (3 concurrent `curl -X POST` in background)
- [x] Check `docker compose logs app` for any `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread`
- [x] If errors appear: update `create_checkpointer` to use `sqlite3.connect(path, check_same_thread=False)` pattern compatible with `SqliteSaver`

**Verify:** All 3 concurrent investigations complete without SQLite errors in logs.

---

## Task Summary

| Phase | Tasks | Key gate |
|---|---|---|
| 0 — Scaffold | T-00 → T-05 (6 tasks) | `docker compose build` |
| 1 — Schemas | T-10 → T-14 (5 tasks) | `from src.config import MODELS` |
| 2A — Demo Data | T-20 → T-22 (3 tasks) | 6 data files valid |
| 2B — MCP Servers | T-23 → T-25 (3 tasks) | 3 `/health` endpoints respond |
| 2C — RAG | T-26 → T-28 (3 tasks) | Chroma seeded, retriever returns docs |
| 3 — Agents | T-30 → T-37 (8 tasks) | Graph compiles, smoke test passes |
| 4 — FastAPI | T-40 → T-42 (3 tasks) | End-to-end investigation via curl |
| 5 — UI | T-50 (1 task) | 6-step demo scenario in browser |
| 6 — Polish | T-60 → T-66 (7 tasks) | Reset + concurrent + feedback loop |
| **Total** | **43 tasks** | |

### Parallel build order

```
Phase 0 (T-00 to T-05) — must complete first
    │
    ├── Phase 1 (T-10 to T-14)
    │       │
    │   ┌───┴──────────────────────────┐
    │   │                              │
    │   Phase 2A (T-20 to T-22)    Phase 2B (T-23 to T-25)
    │   Phase 2C (T-26 to T-28)        │
    │   └───────────────┬──────────────┘
    │                   │
    │           Phase 3 (T-30 to T-37)
    │                   │
    │           Phase 4 (T-40 to T-42)
    │                   │
    └───────────Phase 5 (T-50)
                        │
                Phase 6 (T-60 to T-66)
```
