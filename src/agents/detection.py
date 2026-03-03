import logging
import uuid
from datetime import UTC, datetime

from langchain_core.output_parsers import PydanticOutputParser

from src.agents.orchestrator import (
    DetectionResult,
    call_mcp_tool,
    get_long_term_memory,
    get_retriever,
)
from src.config import MCP_MC_URL, MODELS, invoke_with_retry
from src.memory.long_term import AgentDecision

logger = logging.getLogger(__name__)

_parser = PydanticOutputParser(pydantic_object=DetectionResult)

_SEVERITY_MAP = {
    "null_spike": "critical",
    "volume_drop": "high",
    "schema_drift": "high",
    "freshness_lag": "warning",
    "manual": "info",
}


def _build_prompt(
    table_name: str,
    alert_type: str,
    validation_summary: str,
    table_health: str,
    mc_anomalies: str,
    rag_anomalies: str,
) -> str:
    return (
        "You are a data quality anomaly detection agent.\n"
        "Analyze the metrics and historical patterns to detect anomalies.\n\n"
        f"Table: {table_name}  Alert type: {alert_type}\n\n"
        f"Validation summary:\n{validation_summary}\n\n"
        f"Table health from Monte Carlo:\n{table_health}\n\n"
        f"Recent anomalies from Monte Carlo:\n{mc_anomalies}\n\n"
        f"Similar historical anomalies:\n{rag_anomalies}\n\n"
        f"{_parser.get_format_instructions()}"
    )


async def detection_node(state: dict) -> dict:
    """Detect anomalies using Monte Carlo metrics and RAG historical patterns."""
    trigger = state.get("trigger") or {}
    table_name = trigger.get("table_name", "unknown")
    alert_type = trigger.get("alert_type", "manual")
    description = trigger.get("description", "")
    investigation_id = state.get("investigation_id", "")
    validation_result = state.get("validation_result") or {}

    # MCP: get table health and recent anomalies
    table_health: dict = {}
    mc_anomalies: list = []
    try:
        table_health = await call_mcp_tool(  # type: ignore[assignment]
            MCP_MC_URL, "get_table_health", {"table_name": table_name}
        )
        mc_anomalies = await call_mcp_tool(  # type: ignore[assignment]
            MCP_MC_URL,
            "get_anomalies",
            {"table_name": table_name, "hours_lookback": 24},
        )
    except Exception as e:
        logger.warning("MC MCP call failed: %s", e)

    # RAG: retrieve similar historical anomalies
    rag_docs: list = []
    try:
        retriever = get_retriever()
        rag_docs = retriever.retrieve_similar_anomalies(
            description or table_name, anomaly_type=alert_type
        )
    except Exception as e:
        logger.warning("RAG retrieval failed: %s", e)

    rag_summaries = [d.page_content[:300] for d in rag_docs[:3]]
    past_anomalies = [
        {
            "content": d.page_content[:200],
            "metadata": d.metadata,
        }
        for d in rag_docs[:3]
    ]

    # LLM synthesis
    model = MODELS["tier2_structured"]
    prompt = _build_prompt(
        table_name,
        alert_type,
        validation_result.get("summary", "")[:500],
        str(table_health)[:500],
        str(mc_anomalies)[:500],
        "\n".join(rag_summaries),
    )
    try:
        response = await invoke_with_retry(model, prompt)
        result = _parser.parse(response.content)
    except Exception as e:
        logger.warning("Detection LLM failed: %s", e)
        anomaly_detected = bool(mc_anomalies) or not validation_result.get("passed", True)
        result = DetectionResult(
            anomaly_detected=anomaly_detected,
            anomaly_type=alert_type if anomaly_detected else None,
            confidence=0.7 if anomaly_detected else 0.5,
            affected_tables=[table_name],
            affected_columns=[],
            similar_past_anomalies=past_anomalies,
            summary=f"Detection for {table_name}: {alert_type} (fallback)",
        )

    severity = _SEVERITY_MAP.get(result.anomaly_type or alert_type, "info")

    # Record decision
    try:
        memory = get_long_term_memory()
        memory.record_decision(
            AgentDecision(
                decision_id=str(uuid.uuid4()),
                investigation_id=investigation_id,
                agent_name="detection_agent",
                decision_type="detection",
                input_summary=f"table={table_name} alert={alert_type}",
                output_summary=result.summary[:500],
                confidence=result.confidence,
                was_correct=None,
                created_at=datetime.now(tz=UTC),
            )
        )
    except Exception as e:
        logger.warning("Could not record decision: %s", e)

    return {
        "detection_result": result.model_dump(),
        "current_phase": "detection_complete",
        "severity": severity if result.anomaly_detected else None,
    }
