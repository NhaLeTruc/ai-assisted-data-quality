# Data Quality & Observability Intelligence Platform — Technical Specification

**Status:** Active | **Version:** 1.0 | **Date:** 2026-03-02

> This document is the authoritative technical specification for the Data Quality and Observability Intelligence Platform tech demo. All architectural decisions are codified in [`docs/adr/`](adr/README.md). Read this document instead of (or alongside) the ADRs when building the system.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Technology Stack](#2-technology-stack)
3. [Repository Layout](#3-repository-layout)
4. [Environment Variables](#4-environment-variables)
5. [Data Contracts and Core Schemas](#5-data-contracts-and-core-schemas)
6. [Agent Architecture and Workflow](#6-agent-architecture-and-workflow)
7. [MCP Server Specifications](#7-mcp-server-specifications)
8. [RAG Architecture](#8-rag-architecture)
9. [Memory Architecture](#9-memory-architecture)
10. [LLM Configuration](#10-llm-configuration)
11. [FastAPI REST Endpoints](#11-fastapi-rest-endpoints)
12. [Seed Data Specifications](#12-seed-data-specifications)
13. [Demo UI (Streamlit)](#13-demo-ui-streamlit)
14. [Deployment Guide](#14-deployment-guide)
15. [Demo Scenario](#15-demo-scenario)
16. [Verification Steps](#16-verification-steps)
17. [Production Evolution Notes](#17-production-evolution-notes)

---

## 1. System Overview

The Data Quality & Observability Intelligence Platform ingests a data alert trigger (via REST API or Streamlit UI), routes it through a 7-node LangGraph multi-agent workflow, queries MCP-connected tools (Great Expectations for validation, Monte Carlo mock for observability, and custom tools for lineage and remediation), enriches context from a RAG knowledge base of historical anomalies and playbooks, and produces a structured remediation plan with business impact assessment. The system learns from outcomes via a two-layer memory architecture (session checkpoints + persistent agent decision history).

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ENTRY POINTS                                  │
│   Streamlit UI :3000          FastAPI REST :8000                     │
│        │                             │                               │
└────────┼─────────────────────────────┼───────────────────────────────┘
         │                             │
         └──────────────┬──────────────┘
                        ▼
┌───────────────────────────────────────────────────────────────────────┐
│                    LangGraph Workflow (src/agents/)                    │
│                                                                        │
│  ┌─────────────┐                                                       │
│  │ Orchestrator│─────────────┐                                         │
│  └─────────────┘             │                                         │
│         ▲                    │ Phase routing (severity-gated)          │
│         │              ┌─────▼──────────────────────┐                 │
│         │              │  Phase 1: Detection         │                 │
│         │              │  Validation → Detection     │                 │
│         │              └─────────────────────────────┘                 │
│         │              ┌─────────────────────────────┐                 │
│         │              │  Phase 2: Diagnosis          │                 │
│         │              │  Diagnosis → Lineage         │                 │
│         │              └─────────────────────────────┘                 │
│         │              ┌─────────────────────────────┐                 │
│         └──────────────│  Phase 3: Remediation        │                │
│                        │  BusinessImpact → Repair     │                │
│                        └─────────────────────────────┘                 │
└───────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────┐    ┌──────────────────┐    ┌───────────────┐
│  MCP Servers │    │   Chroma :8001   │    │ SQLite Files  │
│  GX    :8081 │    │ 4 collections:   │    │checkpoints.db │
│  MC    :8082 │    │ anomaly_patterns │    │decisions.db   │
│  Custom:8083 │    │ dq_rules         │    └───────────────┘
└─────────────┘    │ rem_playbooks    │
                   │ business_context │           ▼
                   └──────────────────│    ┌───────────────┐
                                      │    │  OpenAI API   │
                                      │    │ GPT-4o        │
                                      │    │ GPT-4o-mini   │
                                      │    │ text-emb-3-lg │
                                      │    └───────────────┘
```

**Three key design principles:**
1. **Single-call MCP tools** — every MCP tool completes its operation in one call; no polling loops
2. **Severity-gated phases** — Diagnosis only runs if `anomaly_detected=True`; Remediation only runs if `severity` is `critical` or `high`
3. **Two-layer memory** — short-term LangGraph session checkpoints + long-term SQLite/RAG decision history with a feedback loop

---

## 2. Technology Stack

| Component | Library / Tool | Min Version | Role |
|---|---|---|---|
| Agent framework | `langgraph` | `0.2.0` | Multi-agent state machine, conditional routing |
| Agent nodes | `langchain-core` | `0.3.0` | Prompt templates, output parsers |
| LLM API | `langchain-openai` | `0.2.0` | `ChatOpenAI`, `OpenAIEmbeddings` |
| RAG indexing | `llama-index` | `0.11.0` | Document loading, semantic chunking |
| RAG indexing (OAI) | `llama-index-embeddings-openai` | `0.2.0` | Embedding model for LlamaIndex |
| RAG retrieval | `langchain` | `0.3.0` | `EnsembleRetriever`, `ContextualCompressionRetriever` |
| Vector DB client | `langchain-chroma` | `0.1.0` | LangChain ↔ Chroma adapter |
| Community tools | `langchain-community` | `0.3.0` | BM25 retriever |
| MCP client | `langchain-mcp` | latest | MCP tool discovery and invocation |
| Vector DB | `chromadb` | `0.5.0` | Persistent embedding store (HNSW) |
| Cross-encoder | `sentence-transformers` | `3.0.0` | MiniLM-L-6-v2 re-ranking |
| MCP servers | `fastmcp` | latest | Streamable HTTP MCP protocol handler |
| REST API | `fastapi` | latest | Main application API |
| ASGI server | `uvicorn[standard]` | latest | FastAPI runtime |
| Demo UI | `streamlit` | latest | Dashboard for live demo |
| Retry logic | `tenacity` | latest | Exponential backoff on OpenAI calls |
| Data validation | `pydantic` | `2.0` | Structured agent outputs |
| Async HTTP | `httpx` | latest | Async HTTP client for MCP calls |
| Token counting | `tiktoken` | latest | Cost estimation |
| Env management | `python-dotenv` | latest | `.env` file loading |
| LLM: reasoning | `gpt-4o` | — | Tier 1 agents |
| LLM: structured | `gpt-4o-mini` | — | Tier 2 and 3 agents |
| Embeddings | `text-embedding-3-large` | — | All RAG indexing and retrieval |
| Deployment | Docker Compose | `3.8` | Local single-command startup |
| Runtime | Python | `3.11` | Application runtime |

---

## 3. Repository Layout

```
AI-assisted-data-quality/
│
├── docker-compose.yml          # Defines all 6 services; single-command startup
├── Dockerfile                  # Python 3.11 image for the `app` service
├── .env.example                # Template; copy to .env and fill OPENAI_API_KEY
├── requirements.txt            # All Python dependencies (see Section 14)
│
├── src/                        # Main application source
│   ├── main.py                 # FastAPI app factory; mounts routers; startup event
│   ├── config.py               # MODELS dict, env var loading, CostTracker
│   │
│   ├── agents/
│   │   ├── workflow.py         # StateGraph definition; all nodes; compile()
│   │   ├── orchestrator.py     # Orchestrator node; route_from_orchestrator()
│   │   ├── validation.py       # Validation node; calls mcp-gx tools; emits ValidationResult
│   │   ├── detection.py        # Detection node; calls mcp-mc tools; emits DetectionResult
│   │   ├── diagnosis.py        # Diagnosis node; GPT-4o root cause; emits DiagnosisResult
│   │   ├── lineage.py          # Lineage node; calls analyze_data_lineage; emits LineageResult
│   │   ├── business_impact.py  # Impact node; calls assess_business_impact; emits BusinessImpactResult
│   │   └── repair.py           # Repair node; calls apply_remediation; emits RemediationPlan + Outcome
│   │
│   ├── memory/
│   │   ├── short_term.py       # SqliteSaver setup; WorkflowMemory TypedDict; latency helpers
│   │   └── long_term.py        # LongTermMemory class; AgentDecision dataclass; SQLite DDL
│   │
│   ├── rag/
│   │   ├── indexer.py          # DataQualityIndexer; SemanticSplitter; upsert to Chroma
│   │   └── retriever.py        # DataQualityRetriever; EnsembleRetriever; 4 query methods
│   │
│   └── api/
│       ├── routes.py           # /api/v1/ investigation and RAG endpoints (7 routes)
│       └── health.py           # GET /health; checks all 5 service dependencies
│
├── mcp-servers/
│   ├── great-expectations/
│   │   ├── server.py           # FastMCP server on port 8081; 4 GX tools
│   │   └── requirements.txt    # great-expectations, fastmcp, etc.
│   ├── monte-carlo-mock/
│   │   ├── server.py           # FastMCP server on port 8082; 4 mock MC tools
│   │   └── requirements.txt
│   └── custom/
│       ├── server.py           # FastMCP server on port 8083; 4 custom tools
│       └── requirements.txt
│
├── ui/
│   └── app.py                  # Streamlit dashboard; 3 tabs; polls /api/v1/investigations
│
├── demo-data/
│   ├── sample_datasets/
│   │   ├── orders.csv          # 10,000 rows; 5% null customer_id (triggers null_spike)
│   │   ├── customers.csv       # 5,000 rows; mixed phone lengths (schema drift scenario)
│   │   └── products.csv        # 1,000 rows; clean reference data
│   └── seed_data/
│       ├── anomalies.json      # 20 historical anomaly records for anomaly_patterns collection
│       ├── playbooks.json      # 10 remediation playbooks for remediation_playbooks collection
│       └── business_context.json # 10 table business context records
│
├── data/                       # Persistent volumes (gitignored)
│   ├── chroma/                 # Chroma vector store files
│   └── sqlite/                 # checkpoints.db and decisions.db
│
├── scripts/
│   ├── seed_demo_data.py       # Indexes all seed_data/ files into Chroma
│   └── reset_demo.sh           # Stops containers, wipes data/, restarts, re-seeds
│
└── docs/
    ├── SPEC.md                 # This document
    └── adr/                    # Architecture Decision Records (0001–0009)
```

---

## 4. Environment Variables

Copy `.env.example` to `.env` before starting. Only `OPENAI_API_KEY` is strictly required; all others have defaults tuned for the Docker Compose setup.

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | **Yes** | — | OpenAI API key with GPT-4o access. Nothing works without this. |
| `CHROMA_HOST` | No | `chroma` | Docker service hostname for Chroma container |
| `CHROMA_PORT` | No | `8000` | Internal Chroma port (container-to-container; host maps to 8001) |
| `MCP_GX_URL` | No | `http://mcp-gx:8081/mcp` | Streamable HTTP URL for Great Expectations MCP server |
| `MCP_MC_URL` | No | `http://mcp-mc:8082/mcp` | Streamable HTTP URL for Monte Carlo mock MCP server |
| `MCP_CUSTOM_URL` | No | `http://mcp-custom:8083/mcp` | Streamable HTTP URL for Custom Tools MCP server |
| `GX_MCP_TOKEN` | No | `""` | Bearer token for GX MCP server auth (leave blank for local demo) |
| `SQLITE_PATH` | No | `/data/sqlite/checkpoints.db` | LangGraph checkpoint SQLite database path |
| `DECISIONS_DB_PATH` | No | `/data/sqlite/decisions.db` | Long-term AgentDecision SQLite database path |
| `CHROMA_DATA_PATH` | No | `/data/chroma` | Filesystem path for Chroma persistent storage |
| `LOG_LEVEL` | No | `INFO` | Python logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `COST_TRACKING_ENABLED` | No | `true` | Toggle per-investigation API cost logging |
| `COST_ALERT_THRESHOLD` | No | `5.00` | Log warning when session cost exceeds this USD amount |
| `MAX_REQUESTS_PER_MINUTE` | No | `60` | Guard against accidental OpenAI rate-limit spikes |
| `API_URL` | No | `http://app:8000` | Used by Streamlit (`demo-ui` container) to reach FastAPI |
| `DEMO_DATA_DIR` | No | `/demo-data` | Mount point for CSV and JSON seed files inside containers |
| `MEMORY_RETENTION_DAYS` | No | `90` | Days to keep agent decisions before cleanup |

---

## 5. Data Contracts and Core Schemas

### 5.1 DataQualityState

The LangGraph state object passed between all nodes. Defined in `src/agents/workflow.py`.

```python
from typing import TypedDict, List, Optional

class DataQualityState(TypedDict):
    # Investigation identity
    investigation_id: str           # UUID4, generated at API layer before ainvoke()
    triggered_at: str               # ISO 8601 datetime string

    # Input trigger (serialized InvestigationTrigger)
    trigger: dict

    # Phase 1 — Detection
    validation_result: Optional[dict]    # Serialized ValidationResult
    detection_result: Optional[dict]     # Serialized DetectionResult

    # Phase 2 — Diagnosis
    diagnosis_result: Optional[dict]     # Serialized DiagnosisResult
    lineage_result: Optional[dict]       # Serialized LineageResult

    # Phase 3 — Remediation
    business_impact: Optional[dict]      # Serialized BusinessImpactResult
    remediation_plan: Optional[dict]     # Serialized RemediationPlan
    remediation_result: Optional[dict]   # Serialized RemediationOutcome

    # Control flow
    current_phase: str              # "initial" | "detection_complete" | "diagnosis_complete" | "remediation_complete"
    severity: Optional[str]         # "critical" | "high" | "warning" | "info" | None
    should_auto_remediate: bool     # True when severity in [critical,high] AND confidence > 0.8
    workflow_complete: bool         # Terminal flag; set by orchestrator before routing to END
    errors: List[str]               # Accumulated error strings; agents append, never replace
```

### 5.2 WorkflowMemory

Short-term session memory stored in LangGraph SQLite checkpoint. Defined in `src/memory/short_term.py`.

```python
class WorkflowMemory(TypedDict):
    investigation_id: str
    started_at: str                 # ISO 8601
    shared_context: dict            # {agent_name: str -> findings_summary: str}
    agent_messages: List[dict]      # [{"from": str, "timestamp": str, "content": dict}]
    decisions: List[dict]           # [{"agent": str, "decision": str, "rationale": str, "timestamp": str}]
    agent_latencies: dict           # {agent_name: int}  — milliseconds per agent
```

### 5.3 AgentDecision

Long-term structured memory record. Defined in `src/memory/long_term.py`.

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class AgentDecision:
    decision_id: str                # UUID4
    investigation_id: str           # Links to investigation
    agent_name: str                 # e.g. "detection_agent"
    decision_type: str              # "validation" | "detection" | "diagnosis" | "lineage" | "business_impact" | "repair"
    input_summary: str              # Max 500 chars
    output_summary: str             # Max 500 chars
    confidence: float               # 0.0 – 1.0
    was_correct: Optional[bool]     # None until feedback; True/False after
    created_at: datetime
```

### 5.4 Pydantic Structured Outputs

Each model is returned by the corresponding LangGraph agent node via `PydanticOutputParser`. All fields must be serializable to `dict` for storage in `DataQualityState`.

**InvestigationTrigger** — request body for `POST /api/v1/investigations`:

```python
from pydantic import BaseModel
from typing import Dict, Any

class InvestigationTrigger(BaseModel):
    dataset_id: str         # e.g. "orders_2026_03"
    table_name: str         # e.g. "orders"
    alert_type: str         # "null_spike" | "volume_drop" | "schema_drift" | "freshness" | "manual"
    description: str        # Human-readable description of the suspected issue
    context: Dict[str, Any] = {}  # Optional additional metadata
```

**ValidationResult** — emitted by Validation Agent:

```python
class ValidationResult(BaseModel):
    passed: bool
    failed_expectations: List[str]  # e.g. ["expect_column_values_to_not_be_null"]
    total_expectations: int
    failure_count: int
    details: dict                   # Raw GX result JSON from mcp-gx
    summary: str
```

**DetectionResult** — emitted by Detection Agent:

```python
class DetectionResult(BaseModel):
    anomaly_detected: bool
    anomaly_type: Optional[str]         # "null_spike" | "schema_drift" | "volume_drop" | "freshness_lag"
    confidence: float                   # 0.0 – 1.0
    affected_tables: List[str]
    affected_columns: List[str]
    baseline_metric: Optional[float]
    observed_metric: Optional[float]
    deviation_percent: Optional[float]
    similar_past_anomalies: List[dict]  # Top 3 from RAG anomaly_patterns query
    summary: str
```

**DiagnosisResult** — emitted by Diagnosis Agent (GPT-4o):

```python
class DiagnosisResult(BaseModel):
    severity: str                   # "critical" | "high" | "warning" | "info"
    root_cause: str                 # Human-readable root cause hypothesis
    root_cause_category: str        # "upstream_failure" | "schema_change" | "data_volume" | "pipeline_delay" | "unknown"
    confidence: float
    supporting_evidence: List[str]
    recommended_next_steps: List[str]
    estimated_impact_records: Optional[int]
    summary: str
```

**LineageResult** — emitted by Lineage Agent:

```python
class LineageResult(BaseModel):
    upstream_tables: List[str]
    downstream_tables: List[str]
    upstream_pipelines: List[str]
    downstream_consumers: List[str]     # Services/teams consuming the affected table
    impact_radius: int                  # Total downstream nodes affected
    critical_path_breached: bool        # True if any SLA-critical downstream table is affected
    lineage_summary: str
```

**BusinessImpactResult** — emitted by Business Impact Agent (GPT-4o):

```python
class BusinessImpactResult(BaseModel):
    affected_slas: List[dict]           # [{"table": str, "sla_hours": float, "breached": bool}]
    business_criticality: str           # "critical" | "high" | "medium" | "low"
    estimated_financial_impact: Optional[str]  # e.g. "$50K/hour revenue at risk"
    affected_teams: List[str]
    escalation_required: bool
    escalation_contacts: List[str]
    business_summary: str
```

**RemediationPlan** — emitted by Repair Agent:

```python
class RemediationPlan(BaseModel):
    recommended_action: str             # Primary action description
    action_type: str                    # "rollback" | "backfill" | "quarantine" | "notify" | "manual_review"
    steps: List[str]                    # Ordered step-by-step instructions
    dry_run_safe: bool                  # True if auto-application is safe
    estimated_duration_minutes: int
    risk_level: str                     # "low" | "medium" | "high"
    playbook_reference: Optional[str]   # Matched playbook ID from RAG
    alternative_actions: List[str]
```

**RemediationOutcome** — result of `apply_remediation` MCP call:

```python
class RemediationOutcome(BaseModel):
    status: str                         # "applied" | "dry_run" | "skipped" | "failed"
    action_taken: str
    records_affected: Optional[int]
    rollback_available: bool
    outcome_summary: str
```

---

## 6. Agent Architecture and Workflow

### 6.1 Graph Construction (`src/agents/workflow.py`)

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from .orchestrator import orchestrator_node
from .validation import validation_node
from .detection import detection_node
from .diagnosis import diagnosis_node
from .lineage import lineage_node
from .business_impact import business_impact_node
from .repair import repair_node

def build_workflow(sqlite_path: str) -> CompiledGraph:
    memory = SqliteSaver.from_conn_string(sqlite_path)
    graph = StateGraph(DataQualityState)

    # Register nodes (all wrapped with safe_agent_node)
    graph.add_node("orchestrator",     safe_agent_node(orchestrator_node))
    graph.add_node("validation",       safe_agent_node(validation_node))
    graph.add_node("detection",        safe_agent_node(detection_node))
    graph.add_node("diagnosis",        safe_agent_node(diagnosis_node))
    graph.add_node("lineage",          safe_agent_node(lineage_node))
    graph.add_node("business_impact",  safe_agent_node(business_impact_node))
    graph.add_node("repair",           safe_agent_node(repair_node))

    # Entry point
    graph.set_entry_point("orchestrator")

    # Orchestrator routes to pipelines or END
    graph.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {
            "validation":       "validation",
            "diagnosis":        "diagnosis",
            "business_impact":  "business_impact",
            "complete":         END,
        },
    )

    # Detection pipeline: validation → detection → back to orchestrator
    graph.add_edge("validation", "detection")
    graph.add_edge("detection",  "orchestrator")

    # Diagnosis pipeline: diagnosis → lineage → back to orchestrator
    graph.add_edge("diagnosis",  "lineage")
    graph.add_edge("lineage",    "orchestrator")

    # Remediation pipeline: business_impact → repair → back to orchestrator
    graph.add_edge("business_impact", "repair")
    graph.add_edge("repair",          "orchestrator")

    return graph.compile(checkpointer=memory)
```

### 6.2 Routing Functions

**`route_from_orchestrator`** — the central routing function called after every orchestrator invocation:

```python
from typing import Literal

def route_from_orchestrator(state: DataQualityState) -> Literal[
    "validation", "diagnosis", "business_impact", "complete"
]:
    phase = state["current_phase"]

    if phase == "initial":
        return "validation"                     # Always start with detection pipeline

    if phase == "detection_complete":
        detection = state.get("detection_result", {})
        if detection.get("anomaly_detected"):
            return "diagnosis"                  # Escalate to diagnosis pipeline
        return "complete"                       # No anomaly; done

    if phase == "diagnosis_complete":
        severity = state.get("severity")
        if severity in ("critical", "high"):
            return "business_impact"            # Escalate to remediation pipeline
        return "complete"                       # Low severity; done

    if phase == "remediation_complete":
        return "complete"                       # Full workflow done

    # Fallback
    return "complete"
```

### 6.3 Error Handling Wrapper

All nodes registered in the graph **must** be wrapped with `safe_agent_node`. This prevents any single agent failure from halting the workflow.

```python
import logging
from functools import wraps

logger = logging.getLogger(__name__)

def safe_agent_node(agent_fn):
    @wraps(agent_fn)
    async def wrapped(state: DataQualityState) -> dict:
        start = time.monotonic()
        try:
            result = await agent_fn(state)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            agent_latencies = dict(state.get("agent_latencies", {}))
            agent_latencies[agent_fn.__name__] = elapsed_ms
            return {**result, "agent_latencies": agent_latencies}
        except Exception as e:
            logger.error(f"Agent {agent_fn.__name__} failed: {e}", exc_info=True)
            return {
                "errors": state.get("errors", []) + [f"{agent_fn.__name__}: {str(e)}"],
            }
    return wrapped
```

### 6.4 MCP Client Initialization

Initialized once at startup in `src/agents/workflow.py` (or `src/config.py`) and passed to agent constructors:

```python
from langchain_mcp import MCPToolkit
import os

mcp = MCPToolkit(servers={
    "gx":     os.getenv("MCP_GX_URL",     "http://mcp-gx:8081/mcp"),
    "mc":     os.getenv("MCP_MC_URL",     "http://mcp-mc:8082/mcp"),
    "custom": os.getenv("MCP_CUSTOM_URL", "http://mcp-custom:8083/mcp"),
})

gx_tools     = mcp.get_tools(server="gx")
mc_tools     = mcp.get_tools(server="mc")
custom_tools = mcp.get_tools(server="custom")
```

### 6.5 Per-Agent Specification

| Agent | File | LLM Tier | MCP Tools | RAG Collection | Output Model | Sets `current_phase` |
|---|---|---|---|---|---|---|
| Orchestrator | `orchestrator.py` | GPT-4o (T1) | — | `business_context` | routing only | manages all transitions |
| Validation | `validation.py` | GPT-4o-mini (T3) | gx: `create_expectation_suite`, `run_checkpoint`, `get_validation_results` | `dq_rules` | `ValidationResult` | — |
| Detection | `detection.py` | GPT-4o-mini (T2) | mc: `get_table_health`, `get_anomalies` | `anomaly_patterns` | `DetectionResult` | `detection_complete` |
| Diagnosis | `diagnosis.py` | GPT-4o (T1) | mc: `get_anomalies` | `anomaly_patterns`, `remediation_playbooks` | `DiagnosisResult` | — |
| Lineage | `lineage.py` | GPT-4o-mini (T2) | custom: `analyze_data_lineage` | `business_context` | `LineageResult` | `diagnosis_complete` |
| Business Impact | `business_impact.py` | GPT-4o (T1) | custom: `assess_business_impact` | `business_context` | `BusinessImpactResult` | — |
| Repair | `repair.py` | GPT-4o-mini (T2) | custom: `apply_remediation`, `get_similar_anomalies` | `remediation_playbooks` | `RemediationPlan` + `RemediationOutcome` | `remediation_complete` |

**Memory-aware agent pattern** — all non-orchestrator agents must follow this sequence:

```python
async def detection_node(state: DataQualityState) -> dict:
    # 1. Retrieve relevant historical decisions
    past = long_term_memory.get_similar_decisions("detection_agent", "detection", state["trigger"]["description"])

    # 2. Build prompt with historical context
    prompt = build_detection_prompt(state, past_decisions=past)

    # 3. Invoke LLM with retry
    result: DetectionResult = await invoke_with_retry(MODELS["tier2_structured"], prompt)

    # 4. Record decision for future learning
    long_term_memory.record_decision(AgentDecision(
        decision_id=str(uuid4()),
        investigation_id=state["investigation_id"],
        agent_name="detection_agent",
        decision_type="detection",
        input_summary=state["trigger"]["description"][:500],
        output_summary=result.summary[:500],
        confidence=result.confidence,
        was_correct=None,
        created_at=datetime.utcnow(),
    ))

    # 5. Return state updates
    return {
        "detection_result": result.model_dump(),
        "severity": result.anomaly_type and "high" or None,  # detection sets initial severity
        "current_phase": "detection_complete",
    }
```

---

## 7. MCP Server Specifications

All three MCP servers use `fastmcp` with Streamable HTTP transport, mounted at `/mcp`. Each exposes a `GET /health` endpoint returning `{"status": "ok", "server": "<name>"}`.

### 7.1 Great Expectations MCP Server

**File:** `mcp-servers/great-expectations/server.py`
**Port:** `8081`
**Env vars read:** `GX_DATA_DIR` (defaults to `/demo-data`), `GX_MCP_TOKEN`

```python
from fastmcp import FastMCP

mcp = FastMCP("great-expectations")

@mcp.tool()
async def load_dataset(dataset_id: str, file_path: str) -> dict:
    """Load a CSV dataset for validation. Returns row count and column list."""
    # Returns: {"dataset_id": str, "row_count": int, "columns": List[str], "loaded": bool}

@mcp.tool()
async def create_expectation_suite(
    dataset_id: str,
    suite_name: str,
    auto_generate: bool = True
) -> dict:
    """Create a GX expectation suite. suite_name convention: {dataset_id}_suite.
    Returns: {"suite_name": str, "expectation_count": int, "created": bool}"""

@mcp.tool()
async def run_checkpoint(dataset_id: str, suite_name: str) -> dict:
    """Run GX validation checkpoint against loaded dataset.
    Returns: {"success": bool, "result_url": str, "statistics": {"evaluated": int, "successful": int, "unsuccessful": int}}"""

@mcp.tool()
async def get_validation_results(dataset_id: str, suite_name: str) -> dict:
    """Retrieve full validation results including all failed expectations.
    Returns: full GX ValidationResult JSON with "failed_expectations" list"""
```

### 7.2 Monte Carlo Mock MCP Server

**File:** `mcp-servers/monte-carlo-mock/server.py`
**Port:** `8082`
**Data source:** Deterministic mock responses seeded from `demo-data/seed_data/anomalies.json`

```python
@mcp.tool()
async def get_table_health(table_name: str) -> dict:
    """Get table health metrics from Monte Carlo.
    Returns: {"table": str, "freshness_hours": float, "row_count": int,
              "volume_change_pct": float, "status": "healthy"|"degraded"|"critical"}"""

@mcp.tool()
async def get_anomalies(table_name: str, hours_lookback: int = 24) -> list:
    """Get detected anomalies for a table within the lookback window.
    Returns: [{"anomaly_id": str, "type": str, "severity": str,
               "detected_at": str, "metric": float, "baseline": float}]"""

@mcp.tool()
async def get_lineage(table_name: str, depth: int = 2) -> dict:
    """Get upstream/downstream lineage graph from Monte Carlo catalog.
    Returns: {"upstream": List[str], "downstream": List[str], "graph": dict}"""

@mcp.tool()
async def query_catalog(search_term: str, limit: int = 10) -> list:
    """Search the Monte Carlo data catalog.
    Returns: [{"table": str, "description": str, "owner": str, "sla_hours": float}]"""
```

### 7.3 Custom Tools MCP Server

**File:** `mcp-servers/custom/server.py`
**Port:** `8083`
**Special:** `get_similar_anomalies` internally calls Chroma using `CHROMA_HOST`/`CHROMA_PORT`

```python
@mcp.tool()
async def analyze_data_lineage(table_name: str, depth: int = 3) -> dict:
    """Trace full data lineage for a table.
    Returns: {"table": str, "upstream": List[str], "downstream": List[str],
              "impact_radius": int, "critical_consumers": List[str]}"""

@mcp.tool()
async def assess_business_impact(
    table_name: str,
    anomaly_type: str,
    severity: str
) -> dict:
    """Assess business impact of an anomaly.
    Returns: {"affected_slas": [{"table": str, "sla_hours": float, "breached": bool}],
              "teams": List[str], "estimated_delay_hours": float, "escalation_required": bool}"""

@mcp.tool()
async def apply_remediation(
    anomaly_id: str,
    action: str,
    dry_run: bool = True
) -> dict:
    """Apply or simulate a remediation action. Defaults to dry_run=True.
    Returns: {"status": "applied"|"dry_run", "action": str,
              "records_affected": int, "rollback_available": bool}"""

@mcp.tool()
async def get_similar_anomalies(
    description: str,
    anomaly_type: str,
    limit: int = 5
) -> list:
    """Find historically similar anomalies using vector similarity search.
    Calls Chroma anomaly_patterns collection internally.
    Returns: [{"anomaly_id": str, "similarity": float,
               "resolution": str, "resolution_time_hours": float}]"""
```

---

## 8. RAG Architecture

### 8.1 Chroma Collection Schemas

> **Important:** Chroma does not support `List[str]` metadata values. Any list field must be stored as a **comma-separated string** and split on retrieval.

**`anomaly_patterns`** — historical anomaly records:

```
document content: Full text description of the anomaly, root cause, and resolution
metadata fields:
  anomaly_id: str               # "DQ-2026-NNNN"
  anomaly_type: str             # "null_spike" | "schema_drift" | "volume_drop" | "freshness_lag" | "duplicate_records"
  severity: str                 # "critical" | "high" | "warning" | "info"
  affected_tables: str          # comma-separated table names
  root_cause: str               # "upstream_api_failure" | "schema_change" | "data_volume" | "pipeline_delay" | "unknown"
  resolution: str               # "rollback_and_backfill" | "schema_revert" | "pipeline_restart" | etc.
  detected_at: str              # ISO 8601 datetime
  resolution_time_hours: float
```

**`dq_rules`** — data quality rule definitions:

```
document content: Full rule description and enforcement criteria
metadata fields:
  rule_id: str
  rule_type: str                # "completeness" | "uniqueness" | "validity" | "consistency" | "timeliness"
  applies_to: str               # table name or "*" for global rules
  owner_team: str
  created_at: str               # ISO 8601
  gx_expectation: str           # e.g. "expect_column_values_to_not_be_null"
```

**`remediation_playbooks`** — fix procedures:

```
document content: Step-by-step remediation instructions
metadata fields:
  playbook_id: str
  playbook_type: str            # "rollback" | "backfill" | "quarantine" | "notify" | "schema_fix" | "pipeline_restart"
  automation_level: str         # "full" | "semi" | "manual"
  estimated_duration_minutes: int
  applicable_anomaly_types: str # comma-separated
```

**`business_context`** — table metadata and ownership:

```
document content: Table description, business purpose, consumer information
metadata fields:
  table_name: str
  owner_team: str
  sla_hours: float
  criticality: str              # "critical" | "high" | "medium" | "low"
  downstream_consumers: str     # comma-separated service/team names
```

### 8.2 DataQualityIndexer (`src/rag/indexer.py`)

```python
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.embeddings.openai import OpenAIEmbedding
import chromadb

class DataQualityIndexer:
    def __init__(self, chroma_host: str, chroma_port: int):
        self.client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        self.embed_model = OpenAIEmbedding(model="text-embedding-3-large")
        self.splitter = SemanticSplitterNodeParser(
            buffer_size=1,
            breakpoint_percentile_threshold=95,
            embed_model=self.embed_model,
        )

    def index_documents(self, collection_name: str, documents: list) -> int:
        """Index a list of {"id": str, "content": str, "metadata": dict} dicts.
        Returns count of documents indexed."""

    def upsert_document(
        self, collection_name: str, doc_id: str, content: str, metadata: dict
    ) -> None:
        """Upsert a single document. Use for incremental updates after new anomaly resolution."""

    def get_collection_stats(self) -> dict:
        """Returns {collection_name: document_count} for all 4 collections."""
```

### 8.3 DataQualityRetriever (`src/rag/retriever.py`)

```python
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever, ContextualCompressionRetriever
from langchain.retrievers.document_compressors import CrossEncoderReranker
from sentence_transformers import CrossEncoder

ENSEMBLE_WEIGHTS = [0.7, 0.3]          # vector, BM25
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANKER_TOP_N = 5

class DataQualityRetriever:
    def __init__(self, chroma_host: str, chroma_port: int, embeddings):
        # Build one EnsembleRetriever + CrossEncoderReranker per collection
        ...

    def retrieve_similar_anomalies(
        self,
        query: str,
        anomaly_type: str = None,
        severity: str = None,
        days_lookback: int = 90,
    ) -> List[Document]:
        """Query anomaly_patterns. Filters by anomaly_type and severity if provided."""

    def retrieve_playbook(self, query: str, anomaly_type: str) -> List[Document]:
        """Query remediation_playbooks filtered by applicable_anomaly_types."""

    def retrieve_business_context(self, table_name: str) -> List[Document]:
        """Query business_context filtered by table_name metadata."""

    def retrieve_dq_rules(
        self, table_name: str, rule_type: str = None
    ) -> List[Document]:
        """Query dq_rules filtered by applies_to (table_name or '*') and optionally rule_type."""
```

---

## 9. Memory Architecture

### 9.1 Short-Term Memory (`src/memory/short_term.py`)

```python
from langgraph.checkpoint.sqlite import SqliteSaver

def create_checkpointer(sqlite_path: str) -> SqliteSaver:
    return SqliteSaver.from_conn_string(sqlite_path)

# Invocation pattern (in src/api/routes.py)
config = {"configurable": {"thread_id": investigation_id}}
result = await workflow_app.ainvoke(initial_state, config=config)

# Retrieval pattern (for GET /api/v1/investigations/{id})
checkpoint = workflow_app.get_state({"configurable": {"thread_id": investigation_id}})
```

Helper utilities in `short_term.py`:
- `update_shared_context(state, agent_name, findings_summary)` — appends to `shared_context`
- `record_agent_latency(state, agent_name, elapsed_ms)` — updates `agent_latencies`

### 9.2 Long-Term Memory (`src/memory/long_term.py`)

**SQLite schema for `decisions.db`:**

```sql
CREATE TABLE IF NOT EXISTS agent_decisions (
    decision_id       TEXT PRIMARY KEY,
    investigation_id  TEXT NOT NULL,
    agent_name        TEXT NOT NULL,
    decision_type     TEXT NOT NULL,
    input_summary     TEXT,
    output_summary    TEXT,
    confidence        REAL DEFAULT 0.5,
    was_correct       INTEGER,          -- NULL=unknown, 1=correct, 0=incorrect
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_decisions_agent
    ON agent_decisions(agent_name, decision_type);

CREATE INDEX IF NOT EXISTS idx_decisions_investigation
    ON agent_decisions(investigation_id);
```

**`LongTermMemory` class API:**

```python
class LongTermMemory:
    def __init__(self, db_path: str, rag_retriever: DataQualityRetriever):
        ...

    def record_decision(self, decision: AgentDecision) -> None:
        """Persist an AgentDecision to SQLite."""

    def get_similar_decisions(
        self,
        agent_name: str,
        decision_type: str,
        input_description: str,
        k: int = 5,
    ) -> List[dict]:
        """Retrieve k most similar past decisions via RAG semantic search,
        filtered by agent_name and decision_type in SQL."""

    def record_feedback(
        self,
        investigation_id: str,
        was_resolved: bool,
        resolution_notes: str,
    ) -> int:
        """Mark all decisions for an investigation as correct (True) or incorrect (False).
        Returns count of decisions updated."""

    def cleanup_old_memory(self, days_to_keep: int = 90) -> int:
        """Delete agent decisions older than days_to_keep where was_correct != 1.
        Returns count deleted."""
```

---

## 10. LLM Configuration

### 10.1 Model Initialization (`src/config.py`)

```python
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

MODELS = {
    "tier1_reasoning": ChatOpenAI(
        model="gpt-4o",
        temperature=0.1,
        max_tokens=4096,
        timeout=60,
    ),
    "tier2_structured": ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.0,
        max_tokens=2048,
        timeout=30,
    ),
    "tier3_simple": ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.0,
        max_tokens=1024,
        timeout=15,
    ),
    "embeddings": OpenAIEmbeddings(
        model="text-embedding-3-large",
        dimensions=3072,
    ),
}
```

**Agent → model tier mapping:**
- Tier 1 (GPT-4o): Orchestrator, Diagnosis, Business Impact
- Tier 2 (GPT-4o-mini): Detection, Lineage, Repair
- Tier 3 (GPT-4o-mini, shorter): Validation

### 10.2 Retry Decorator

All agent LLM calls must use this decorator:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    reraise=True,
)
async def invoke_with_retry(model, prompt):
    return await model.ainvoke(prompt)
```

### 10.3 CostTracker

```python
PRICING = {
    "gpt-4o":                 {"input": 0.0025,  "output": 0.010},   # per 1K tokens
    "gpt-4o-mini":            {"input": 0.00015, "output": 0.0006},
    "text-embedding-3-large": {"input": 0.00013, "output": 0.0},
}

class CostTracker:
    def __init__(self):
        self._session_cost = 0.0
        self._investigation_costs: dict[str, float] = {}

    def record(
        self,
        model: str,
        investigation_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Record token usage and return cost for this call."""

    def report(self) -> dict:
        """Return {"session_total_usd": float, "investigation_count": int,
                   "avg_per_investigation_usd": float}"""
```

`CostTracker` is instantiated globally in `src/config.py`. The `/health` endpoint exposes `cost_tracker.report()`.

---

## 11. FastAPI REST Endpoints

Base URL: `http://localhost:8000`
All endpoints under `/api/v1/` are defined in `src/api/routes.py`.

### `POST /api/v1/investigations`

Trigger a new investigation.

- **Request body:** `InvestigationTrigger`
- **Response (202 Accepted):**
  ```json
  {"investigation_id": "uuid4", "status": "started", "triggered_at": "ISO8601"}
  ```
- **Behavior:** Generates UUID, builds initial `DataQualityState`, invokes `workflow_app.ainvoke()` asynchronously (background task); returns immediately.

### `GET /api/v1/investigations/{investigation_id}`

Get current or final state of an investigation.

- **Response (200 OK):**
  ```json
  {
    "investigation_id": "...",
    "status": "complete" | "in_progress" | "error",
    "current_phase": "...",
    "severity": "...",
    "validation_result": {...},
    "detection_result": {...},
    "diagnosis_result": {...},
    "lineage_result": {...},
    "business_impact": {...},
    "remediation_plan": {...},
    "remediation_result": {...},
    "errors": [],
    "agent_latencies": {"validation_node": 1200, ...},
    "triggered_at": "...",
    "completed_at": "..."
  }
  ```
- **Response (404 Not Found):** `{"detail": "Investigation not found"}`
- **Behavior:** Loads LangGraph checkpoint synchronously (returns partial state during execution).

### `POST /api/v1/investigations/{investigation_id}/feedback`

Submit resolution feedback to improve future investigations.

- **Request body:** `{"was_resolved": bool, "resolution_notes": str}`
- **Response (200 OK):** `{"updated": true, "decisions_updated": int}`
- **Behavior:** Calls `long_term_memory.record_feedback()`.

### `GET /api/v1/investigations`

List recent investigations.

- **Query params:** `limit=20`, `offset=0`, `severity=critical` (optional filter)
- **Response:** `{"investigations": [...], "total": int}`
- **Behavior:** Queries `agent_decisions` for distinct `investigation_id` values.

### `POST /api/v1/rag/query`

Query the RAG knowledge base directly (useful for live demo).

- **Request body:**
  ```json
  {
    "query": "null values in customer_id",
    "collection": "anomaly_patterns",
    "filters": {"anomaly_type": "null_spike"},
    "k": 3
  }
  ```
- **Response:** `{"results": [{"content": str, "metadata": dict, "score": float}]}`

### `POST /api/v1/rag/index`

Index new documents into a collection.

- **Request body:**
  ```json
  {
    "collection": "anomaly_patterns",
    "documents": [{"content": str, "metadata": dict, "id": str}]
  }
  ```
- **Response:** `{"indexed": int}`

### `GET /health`

Check health of all dependent services.

- **Response:**
  ```json
  {
    "status": "healthy" | "degraded",
    "checks": {
      "app": "healthy",
      "chroma": "healthy",
      "mcp_gx": "healthy",
      "mcp_mc": "healthy",
      "mcp_custom": "healthy"
    },
    "cost_session": {"session_total_usd": 0.42, "investigation_count": 4, "avg_per_investigation_usd": 0.105}
  }
  ```

---

## 12. Seed Data Specifications

### 12.1 Sample Datasets (`demo-data/sample_datasets/`)

**`orders.csv`** — 10,000 rows:

| Column | Type | Constraints | Demo Purpose |
|---|---|---|---|
| `order_id` | UUID | Unique, no nulls | Primary key |
| `customer_id` | UUID | **5% null rate** | Triggers `null_spike` detection |
| `product_id` | UUID | No nulls | Foreign key |
| `order_date` | ISO date | Within last 90 days | Freshness check |
| `amount` | float | $0.01 – $5,000.00 | Value validation |
| `status` | enum | `pending\|processing\|shipped\|delivered\|cancelled` | Validity check |
| `region` | enum | `US\|EU\|APAC\|LATAM` | Consistency check |

**`customers.csv`** — 5,000 rows:

| Column | Type | Constraints | Demo Purpose |
|---|---|---|---|
| `customer_id` | UUID | Unique, no nulls | Primary key |
| `name` | string | No nulls | Completeness check |
| `email` | string | Valid email format | Format validation |
| `phone` | string | **Mix: 10-char and 15-char** | Triggers `schema_drift` scenario |
| `created_at` | ISO datetime | — | Timeliness check |
| `tier` | enum | `free\|basic\|premium\|enterprise` | Validity check |

**`products.csv`** — 1,000 rows, clean reference data (no intentional defects):

| Column | Type |
|---|---|
| `product_id` | UUID, unique |
| `name` | string |
| `category` | string |
| `price` | float |
| `inventory_count` | int |
| `last_updated` | ISO datetime |

### 12.2 Anomaly Seed Data (`demo-data/seed_data/anomalies.json`)

Minimum 20 records. Each record structure:

```json
{
  "id": "DQ-2026-0001",
  "content": "Detected 45% null spike in orders.customer_id column on 2026-02-15. Normal null rate 0.1%. Root cause: upstream API deployment v2.3.1 returned null customer_id for all new orders during a 3-hour window. Resolution: rolled back API to v2.3.0 and backfilled 12,000 affected records. Total resolution time: 2.5 hours.",
  "metadata": {
    "anomaly_id": "DQ-2026-0001",
    "anomaly_type": "null_spike",
    "severity": "critical",
    "affected_tables": "orders",
    "root_cause": "upstream_api_failure",
    "resolution": "rollback_and_backfill",
    "detected_at": "2026-02-15T10:30:00Z",
    "resolution_time_hours": 2.5
  }
}
```

**Required coverage (at minimum):**

| `anomaly_type` | Severity distribution | Count |
|---|---|---|
| `null_spike` | 2 critical, 2 warning | 4 |
| `schema_drift` | 1 critical, 2 warning, 1 info | 4 |
| `volume_drop` | 2 critical, 2 warning | 4 |
| `freshness_lag` | 1 critical, 3 warning | 4 |
| `duplicate_records` | 1 high, 2 warning, 1 info | 4 |

### 12.3 Playbooks Seed Data (`demo-data/seed_data/playbooks.json`)

Minimum 10 records. Required `playbook_type` coverage: `rollback`, `backfill`, `quarantine`, `notify`, `schema_fix`, `pipeline_restart`. Example:

```json
{
  "id": "PB-ROLLBACK-001",
  "content": "Rollback and Backfill Playbook: Step 1: Identify the last known good state via git log or deployment history. Step 2: Roll back the upstream service or pipeline to the last good version. Step 3: Quarantine affected records by adding a 'quarantined=true' flag. Step 4: Run backfill job to reprocess affected records from source of truth. Step 5: Validate backfilled data with GX checkpoint. Step 6: Remove quarantine flag and notify downstream consumers.",
  "metadata": {
    "playbook_id": "PB-ROLLBACK-001",
    "playbook_type": "rollback",
    "automation_level": "semi",
    "estimated_duration_minutes": 90,
    "applicable_anomaly_types": "null_spike,volume_drop,duplicate_records"
  }
}
```

### 12.4 Business Context Seed Data (`demo-data/seed_data/business_context.json`)

Minimum 10 records — one per key table (orders, customers, products) plus downstream tables referenced in lineage. Example:

```json
{
  "id": "BC-ORDERS",
  "content": "orders table owned by the Data Engineering team. Critical transactional table feeding revenue reporting, customer segmentation, and the marketing attribution pipeline. SLA: data must be available and valid within 2 hours of the close of each business day. Any quality issues impact real-time dashboards and next-day reporting.",
  "metadata": {
    "table_name": "orders",
    "owner_team": "data-engineering",
    "sla_hours": 2.0,
    "criticality": "critical",
    "downstream_consumers": "revenue_report,customer_segment_model,marketing_pipeline,finance_dashboard"
  }
}
```

### 12.5 Seed Script (`scripts/seed_demo_data.py`)

Execution sequence:

1. Connect to Chroma via `CHROMA_HOST`/`CHROMA_PORT`
2. Delete and recreate all 4 collections (clean slate)
3. Load and index `anomalies.json` → `anomaly_patterns`
4. Load and index `playbooks.json` → `remediation_playbooks`
5. Load and index `business_context.json` → `business_context`
6. Programmatically generate DQ rules (one per GX expectation type per table) → index into `dq_rules`
7. Print collection document counts
8. Exit `0` on success, `1` on any error

---

## 13. Demo UI (Streamlit)

**File:** `ui/app.py`
**Port:** `3000` (mapped from container port `8501`)
**Polls:** `GET /api/v1/investigations/{id}` every 2 seconds

### Layout

**Sidebar:**
- Title: "Data Quality Intelligence Platform"
- API status indicator badge (green/red, from `GET /health`)
- Session cost display (USD, from `/health` response)
- "Reset Demo" button (triggers `reset_demo.sh` via subprocess or calls a reset endpoint)

**Tab 1 — Run Investigation:**
- Form fields: `dataset_id` (text), `table_name` (text), `alert_type` (selectbox: null_spike / volume_drop / schema_drift / freshness / manual), `description` (text_area)
- "Run Investigation" button → `POST /api/v1/investigations`
- Phase progress display (updates every 2s):
  - Phase 1: Detection (Validation Agent, Detection Agent — check marks on completion)
  - Phase 2: Diagnosis (Diagnosis Agent, Lineage Agent)
  - Phase 3: Remediation (Business Impact Agent, Repair Agent)
- Final results panel:
  - Severity badge (color-coded: red=critical, orange=high, yellow=warning, blue=info)
  - Root cause text
  - Expandable per-agent result sections
  - Remediation plan steps

**Tab 2 — Investigation History:**
- `st.dataframe` of recent investigations (ID, severity, alert_type, triggered_at, status)
- Clicking a row expands to show full investigation details
- Feedback buttons: "Mark Resolved" / "Mark Unresolved" → `POST /api/v1/investigations/{id}/feedback`

**Tab 3 — Knowledge Base:**
- Query text input + collection selectbox (`anomaly_patterns`, `dq_rules`, `remediation_playbooks`, `business_context`) + k slider (1–10)
- "Search Knowledge Base" button → `POST /api/v1/rag/query`
- Results displayed as `st.expander` cards (content + metadata + score)

---

## 14. Deployment Guide

### Prerequisites

- Docker Desktop 4.x+ (or Docker Engine + Compose plugin on Linux)
- Minimum 4 GB RAM allocated to Docker
- `OPENAI_API_KEY` with GPT-4o and GPT-4o-mini access

### First-Time Setup

```bash
git clone <repo-url>
cd AI-assisted-data-quality
cp .env.example .env
# Edit .env: set OPENAI_API_KEY=sk-...

docker compose build          # First build: 5–10 minutes
docker compose up -d          # Start all 6 services
# Wait ~30 seconds for health checks to pass
docker compose exec app python scripts/seed_demo_data.py
```

### Service Access

| Service | Host URL | Purpose |
|---|---|---|
| FastAPI app | http://localhost:8000 | Main REST API |
| Swagger UI | http://localhost:8000/docs | Interactive API docs |
| Health check | http://localhost:8000/health | All service statuses |
| Demo UI | http://localhost:3000 | Streamlit dashboard |
| Chroma | http://localhost:8001 | Vector DB (internal) |
| GX MCP | http://localhost:8081/mcp | Great Expectations (internal) |
| MC MCP | http://localhost:8082/mcp | Monte Carlo mock (internal) |
| Custom MCP | http://localhost:8083/mcp | Custom tools (internal) |

### `docker-compose.yml`

```yaml
version: "3.8"

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - CHROMA_HOST=chroma
      - CHROMA_PORT=8000
      - MCP_GX_URL=http://mcp-gx:8081/mcp
      - MCP_MC_URL=http://mcp-mc:8082/mcp
      - MCP_CUSTOM_URL=http://mcp-custom:8083/mcp
      - SQLITE_PATH=/data/sqlite/checkpoints.db
      - DECISIONS_DB_PATH=/data/sqlite/decisions.db
      - CHROMA_DATA_PATH=/data/chroma
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - COST_TRACKING_ENABLED=true
    volumes:
      - ./data:/data
      - ./demo-data:/demo-data:ro
    depends_on:
      chroma:
        condition: service_healthy
      mcp-gx:
        condition: service_healthy
      mcp-mc:
        condition: service_healthy
      mcp-custom:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  chroma:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
    volumes:
      - ./data/chroma:/chroma/chroma
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/heartbeat"]
      interval: 30s
      timeout: 10s
      retries: 3

  mcp-gx:
    build: ./mcp-servers/great-expectations
    ports:
      - "8081:8081"
    volumes:
      - ./demo-data:/demo-data:ro
    environment:
      - GX_DATA_DIR=/demo-data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8081/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  mcp-mc:
    build: ./mcp-servers/monte-carlo-mock
    ports:
      - "8082:8082"
    volumes:
      - ./demo-data:/demo-data:ro
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8082/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  mcp-custom:
    build: ./mcp-servers/custom
    ports:
      - "8083:8083"
    environment:
      - CHROMA_HOST=chroma
      - CHROMA_PORT=8000
    depends_on:
      chroma:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8083/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  demo-ui:
    build:
      context: .
      dockerfile: ui/Dockerfile
    ports:
      - "3000:8501"
    environment:
      - API_URL=http://app:8000
    depends_on:
      app:
        condition: service_healthy

networks:
  default:
    name: demo-network
```

### `requirements.txt`

```
langgraph>=0.2.0
langchain-core>=0.3.0
langchain>=0.3.0
langchain-openai>=0.2.0
langchain-chroma>=0.1.0
langchain-community>=0.3.0
langchain-mcp
llama-index>=0.11.0
llama-index-embeddings-openai>=0.2.0
chromadb>=0.5.0
sentence-transformers>=3.0.0
fastmcp
fastapi
uvicorn[standard]
httpx
pydantic>=2.0
tenacity
tiktoken
streamlit
python-dotenv
```

### Demo Reset

```bash
docker compose down
rm -rf ./data/chroma/* ./data/sqlite/*
docker compose up -d
sleep 30
docker compose exec app python scripts/seed_demo_data.py
```

---

## 15. Demo Scenario

### "The Null Spike Investigation"

This is the canonical demo scenario. Walk through it to demonstrate all 7 agents, MCP tools, RAG retrieval, and the memory system in a single 5-minute flow.

**Pre-demo state:** All services healthy, Chroma seeded with 20 historical anomalies (including `DQ-2026-0001`: a prior null_spike on `orders.customer_id`). The `orders.csv` dataset is accessible to the GX MCP server.

---

**Step 1 — Trigger the investigation**

Navigate to `http://localhost:3000`, Tab 1 "Run Investigation". Fill in:

| Field | Value |
|---|---|
| `dataset_id` | `orders_2026_03` |
| `table_name` | `orders` |
| `alert_type` | `null_spike` |
| `description` | `Noticed customer_id column has unusually high null rate this morning` |

Click "Run Investigation". The UI displays the investigation ID and begins polling.

---

**Step 2 — Phase 1: Detection**

- **Validation Agent** calls `create_expectation_suite(orders_2026_03, orders_2026_03_suite)` → GX auto-generates expectations including `expect_column_values_to_not_be_null` for `customer_id`. Runs `run_checkpoint` → returns `success=False`, `failure_count=1`. GX result shows 5.0% null rate (500/10,000 rows).
- **Detection Agent** calls `get_table_health(orders)` → `volume_change_pct=-0.2%` (normal), then `get_anomalies(orders, 24)` → returns anomaly: `type=null_spike`, `severity=high`, `metric=0.05`, `baseline=0.001`, deviation 4,900%. Queries RAG `anomaly_patterns` → finds `DQ-2026-0001` (45% null spike, 85% similarity). Emits `DetectionResult(anomaly_detected=True, confidence=0.91)`.
- State: `current_phase=detection_complete`, `severity=high`

---

**Step 3 — Phase 2: Diagnosis**

Orchestrator routes to Diagnosis pipeline (anomaly detected).

- **Diagnosis Agent** (GPT-4o) synthesizes GX failure, MC anomaly, and RAG historical match. Determines: `root_cause="Upstream API deployment returning null customer_id values"`, `root_cause_category=upstream_failure`, `severity=high`, `confidence=0.87`, `estimated_impact_records=500`.
- **Lineage Agent** calls `analyze_data_lineage(orders, depth=3)` → returns: `upstream=[api_gateway, user_service]`, `downstream=[revenue_report, customer_segment_model, marketing_pipeline, finance_dashboard]`, `impact_radius=7`, `critical_path_breached=True` (revenue_report SLA=2h).
- State: `current_phase=diagnosis_complete`, `severity=high`

---

**Step 4 — Phase 3: Remediation**

Orchestrator routes to Remediation pipeline (severity=high).

- **Business Impact Agent** (GPT-4o) calls `assess_business_impact(orders, null_spike, high)` → `affected_slas=[{table: revenue_report, sla_hours: 2.0, breached: False (1.2h delayed)}, {table: marketing_pipeline, sla_hours: 6.0, breached: False}]`. Determines: `business_criticality=high`, `escalation_required=True`, `escalation_contacts=[data-engineering@company.com, data-sre@company.com]`.
- **Repair Agent** retrieves `PB-ROLLBACK-001` from RAG `remediation_playbooks` (90% match). Calls `get_similar_anomalies("null spike customer_id", "null_spike", 3)` → returns `DQ-2026-0001` (resolved in 2.5h). Calls `apply_remediation(anomaly_id, "rollback_and_backfill", dry_run=True)` → `status=dry_run`, `records_affected=500`. Emits `RemediationPlan(action_type=rollback, steps=[...], estimated_duration_minutes=90, risk_level=medium)`.
- State: `current_phase=remediation_complete`

---

**Step 5 — Final display**

The UI shows:
- Severity badge: **HIGH** (orange)
- Root cause: "Upstream API deployment returning null customer_id values"
- Confidence: 87%
- Affected records: ~500
- Downstream impact: revenue_report, customer_segment_model, marketing_pipeline, finance_dashboard (7 nodes)
- SLA risk: revenue_report (2h SLA, currently 1.2h delayed — approaching breach)
- Historical match: DQ-2026-0001 (85% similar, resolved in 2.5h)
- Remediation plan: 6-step rollback + backfill (dry run confirmed safe)
- Escalation: Required — contacts listed

---

**Step 6 — Submit feedback**

Navigate to Tab 2 "Investigation History". Find the investigation. Click "Mark Resolved". `POST /api/v1/investigations/{id}/feedback` with `{"was_resolved": true, "resolution_notes": "Rolled back API v2.3.1 to v2.3.0 and backfilled 500 records"}`. The long-term memory records this outcome for future learning.

---

## 16. Verification Steps

Run these commands after first-time setup to confirm each component is working.

**1. Service health:**
```bash
curl http://localhost:8000/health | python3 -m json.tool
# Expected: {"status": "healthy", "checks": {"app": "healthy", "chroma": "healthy", "mcp_gx": "healthy", "mcp_mc": "healthy", "mcp_custom": "healthy"}}
```

**2. Chroma collection counts:**
```bash
docker compose exec app python3 -c "
import chromadb, os
c = chromadb.HttpClient(host='chroma', port=8000)
for col in ['anomaly_patterns', 'dq_rules', 'remediation_playbooks', 'business_context']:
    print(f'{col}: {c.get_collection(col).count()} documents')
"
# Expected: all collections show > 0 documents
```

**3. MCP server health:**
```bash
curl http://localhost:8081/health
curl http://localhost:8082/health
curl http://localhost:8083/health
# Expected: {"status": "ok", "server": "<name>"} from each
```

**4. Full investigation (end-to-end):**
```bash
# Trigger
RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/investigations \
  -H "Content-Type: application/json" \
  -d '{"dataset_id":"orders_2026_03","table_name":"orders","alert_type":"null_spike","description":"Test null spike investigation"}')
echo $RESPONSE
ID=$(echo $RESPONSE | python3 -c "import sys,json; print(json.load(sys.stdin)['investigation_id'])")

# Poll until complete (retry manually until status=complete)
curl http://localhost:8000/api/v1/investigations/$ID | python3 -m json.tool
# Expected: "severity": "high" or "critical", "current_phase": "remediation_complete"
```

**5. RAG retrieval:**
```bash
curl -s -X POST http://localhost:8000/api/v1/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query":"null values in customer_id column","collection":"anomaly_patterns","k":3}' \
  | python3 -m json.tool
# Expected: results array with >= 1 document having anomaly_type=null_spike
```

**6. Long-term memory persistence:**
```bash
docker compose exec app python3 -c "
import sqlite3, os
conn = sqlite3.connect(os.getenv('DECISIONS_DB_PATH', '/data/sqlite/decisions.db'))
count = conn.execute('SELECT COUNT(*) FROM agent_decisions').fetchone()[0]
print(f'Decisions recorded: {count}')
conn.close()
"
# Expected: count > 0 after running at least one investigation
```

---

## 17. Production Evolution Notes

All demo decisions have a clear production upgrade path. The LangChain/LangGraph abstraction layers allow most swaps without rewriting agent logic.

| Component | Demo Approach | Production Path |
|---|---|---|
| LangGraph checkpointing | SQLite local file | PostgreSQL (`AsyncPostgresSaver`) or Redis |
| Vector DB | Chroma (file-based) | Weaviate (knowledge graphs, sharding, multi-tenancy) |
| MCP deployment | Docker Compose single instance | Cloud Run / Lambda, auto-scaling per server |
| Agent execution | Single-process, sequential pipelines | Distributed async via Celery or Temporal; Diagnosis + Lineage can run in parallel |
| LLM provider | Single OpenAI key | LiteLLM proxy with fallback providers (Claude, Gemini) |
| Cost control | Logging + alerts | Hard per-tenant limits, Redis token bucket rate limiting |
| Secrets management | `.env` file | HashiCorp Vault / AWS Secrets Manager |
| Monitoring | Docker logs + CostTracker | OpenTelemetry → Grafana + LangSmith tracing |
| MCP auth | Bearer token / env | OAuth 2.0 via API Gateway |
| Parallel agent execution | Sequential within pipelines | Parallel LangGraph branches (Diagnosis ∥ Lineage) |
| Memory cleanup | On-demand script | Scheduled cron job with configurable retention |
