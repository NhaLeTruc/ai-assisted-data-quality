import json
import logging
import time
from functools import wraps
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from src.config import CHROMA_HOST, CHROMA_PORT, DECISIONS_DB_PATH, MODELS
from src.memory.long_term import LongTermMemory
from src.rag.retriever import DataQualityRetriever

logger = logging.getLogger(__name__)

# Module-level MCP toolkit placeholders (tools are called via call_mcp_tool helper)
gx_tools: list = []
mc_tools: list = []
custom_tools: list = []


# ---------------------------------------------------------------------------
# Pydantic models (SPEC §5.4)
# ---------------------------------------------------------------------------


class InvestigationTrigger(BaseModel):
    dataset_id: str  # e.g. "orders_2026_03"
    table_name: str  # e.g. "orders"
    alert_type: str  # "null_spike"|"volume_drop"|"schema_drift"|"freshness"|"manual"
    description: str  # Human-readable description of the suspected issue
    context: dict[str, Any] = {}  # Optional additional metadata


class ValidationResult(BaseModel):
    passed: bool
    failed_expectations: list[str]  # e.g. ["expect_column_values_to_not_be_null"]
    total_expectations: int
    failure_count: int
    details: dict  # Raw GX result JSON from mcp-gx
    summary: str


class DetectionResult(BaseModel):
    anomaly_detected: bool
    anomaly_type: str | None = None  # "null_spike"|"schema_drift"|"volume_drop"|...
    confidence: float  # 0.0 - 1.0
    affected_tables: list[str]
    affected_columns: list[str]
    baseline_metric: float | None = None
    observed_metric: float | None = None
    deviation_percent: float | None = None
    similar_past_anomalies: list[dict]  # Top 3 from RAG anomaly_patterns query
    summary: str


class DiagnosisResult(BaseModel):
    severity: str  # "critical"|"high"|"warning"|"info"
    root_cause: str
    root_cause_category: str  # "upstream_failure"|"schema_change"|"data_volume"|...
    confidence: float
    supporting_evidence: list[str]
    recommended_next_steps: list[str]
    estimated_impact_records: int | None = None
    summary: str


class LineageResult(BaseModel):
    upstream_tables: list[str]
    downstream_tables: list[str]
    upstream_pipelines: list[str]
    downstream_consumers: list[str]  # Services/teams consuming the affected table
    impact_radius: int  # Total downstream nodes affected
    critical_path_breached: bool  # True if any SLA-critical downstream table affected
    lineage_summary: str


class BusinessImpactResult(BaseModel):
    affected_slas: list[dict]  # [{"table": str, "sla_hours": float, "breached": bool}]
    business_criticality: str  # "critical"|"high"|"medium"|"low"
    estimated_financial_impact: str | None = None  # e.g. "$50K/hour revenue at risk"
    affected_teams: list[str]
    escalation_required: bool
    escalation_contacts: list[str]
    business_summary: str


class RemediationPlan(BaseModel):
    recommended_action: str
    action_type: str  # "rollback"|"backfill"|"quarantine"|"notify"|"manual_review"
    steps: list[str]
    dry_run_safe: bool
    estimated_duration_minutes: int
    risk_level: str  # "low"|"medium"|"high"
    playbook_reference: str | None = None  # Matched playbook ID from RAG
    alternative_actions: list[str]


class RemediationOutcome(BaseModel):
    status: str  # "applied"|"dry_run"|"skipped"|"failed"
    action_taken: str
    records_affected: int | None = None
    rollback_available: bool
    outcome_summary: str


# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_long_term_memory: LongTermMemory | None = None
_retriever: DataQualityRetriever | None = None


def get_long_term_memory() -> LongTermMemory:
    global _long_term_memory
    if _long_term_memory is None:
        _long_term_memory = LongTermMemory(db_path=DECISIONS_DB_PATH)
    return _long_term_memory


def get_retriever() -> DataQualityRetriever:
    global _retriever
    if _retriever is None:
        _retriever = DataQualityRetriever(
            chroma_host=CHROMA_HOST,
            chroma_port=CHROMA_PORT,
            embeddings=MODELS["embeddings"],
        )
    return _retriever


# ---------------------------------------------------------------------------
# MCP helper
# ---------------------------------------------------------------------------


async def call_mcp_tool(server_url: str, tool_name: str, arguments: dict) -> dict | list:
    """Call a single MCP tool via HTTP JSON-RPC. Returns {} on any failure."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(server_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("result", {}).get("content", [])
            if content and isinstance(content, list):
                first = content[0]
                text = first.get("text", "{}") if isinstance(first, dict) else "{}"
                return json.loads(text)
            return data.get("result", {})
    except Exception as e:
        logger.warning("MCP call %s.%s failed: %s", server_url, tool_name, e)
    return {}


# ---------------------------------------------------------------------------
# Agent wrapper
# ---------------------------------------------------------------------------


def safe_agent_node(agent_fn):
    """Wrap an async agent function to capture latency and errors."""

    @wraps(agent_fn)
    async def wrapped(state: dict) -> dict:
        start = time.monotonic()
        try:
            result = await agent_fn(state)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            latencies = dict(state.get("agent_latencies") or {})
            latencies[agent_fn.__name__] = elapsed_ms
            return {**result, "agent_latencies": latencies}
        except Exception as e:
            logger.error("%s failed: %s", agent_fn.__name__, e, exc_info=True)
            errors = list(state.get("errors") or [])
            return {"errors": [*errors, f"{agent_fn.__name__}: {e!s}"]}

    return wrapped


# ---------------------------------------------------------------------------
# Orchestrator node
# ---------------------------------------------------------------------------


async def orchestrator_node(state: dict) -> dict:
    """Routing node: queries business context and logs phase transition."""
    phase = state.get("current_phase", "initial")
    trigger = state.get("trigger") or {}
    table_name = trigger.get("table_name", "unknown")
    investigation_id = state.get("investigation_id", "")

    logger.info(
        "Orchestrator [%s]: phase=%s table=%s",
        investigation_id,
        phase,
        table_name,
    )

    if phase == "initial":
        try:
            retriever = get_retriever()
            docs = retriever.retrieve_business_context(table_name)
            logger.debug("Business context: %d docs for %s", len(docs), table_name)
        except Exception as e:
            logger.warning("Business context unavailable: %s", e)

    return {}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def route_from_orchestrator(
    state: dict,
) -> Literal["validation", "diagnosis", "business_impact", "complete"]:
    """Route to the next pipeline stage based on current_phase."""
    phase = state.get("current_phase", "initial")
    if phase == "initial":
        return "validation"
    if phase == "detection_complete":
        detection = state.get("detection_result") or {}
        return "diagnosis" if detection.get("anomaly_detected") else "complete"
    if phase == "diagnosis_complete":
        severity = state.get("severity")
        return "business_impact" if severity in ("critical", "high") else "complete"
    return "complete"
