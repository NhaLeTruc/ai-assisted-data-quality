import logging
import uuid
from datetime import UTC, datetime

from langchain_core.output_parsers import PydanticOutputParser

from src.agents.orchestrator import (
    DiagnosisResult,
    call_mcp_tool,
    get_long_term_memory,
    get_retriever,
)
from src.config import MCP_MC_URL, MODELS, invoke_with_retry
from src.memory.long_term import AgentDecision

logger = logging.getLogger(__name__)

_parser = PydanticOutputParser(pydantic_object=DiagnosisResult)


def _build_prompt(
    table_name: str,
    anomaly_type: str,
    validation_summary: str,
    detection_summary: str,
    mc_anomalies: str,
    similar_anomalies: str,
    playbooks: str,
) -> str:
    return (
        "You are a senior data quality diagnosis agent with deep reasoning capability.\n"
        "Identify the root cause, severity, and recommended next steps.\n\n"
        f"Table: {table_name}  Anomaly type: {anomaly_type}\n\n"
        f"Validation result:\n{validation_summary}\n\n"
        f"Detection result:\n{detection_summary}\n\n"
        f"Extended anomaly history (48h):\n{mc_anomalies}\n\n"
        f"Similar historical anomalies with root causes:\n{similar_anomalies}\n\n"
        f"Applicable remediation playbooks:\n{playbooks}\n\n"
        f"{_parser.get_format_instructions()}"
    )


async def diagnosis_node(state: dict) -> dict:
    """Diagnose the root cause using tier-1 reasoning with extended context."""
    trigger = state.get("trigger") or {}
    table_name = trigger.get("table_name", "unknown")
    description = trigger.get("description", "")
    investigation_id = state.get("investigation_id", "")

    detection_result = state.get("detection_result") or {}
    validation_result = state.get("validation_result") or {}
    anomaly_type = detection_result.get("anomaly_type") or trigger.get("alert_type", "manual")

    # MCP: extended anomaly lookback (48h)
    mc_anomalies: list = []
    try:
        mc_anomalies = await call_mcp_tool(  # type: ignore[assignment]
            MCP_MC_URL,
            "get_anomalies",
            {"table_name": table_name, "hours_lookback": 48},
        )
    except Exception as e:
        logger.warning("MC MCP call failed: %s", e)

    # RAG: similar anomalies and applicable playbooks
    similar_summaries = ""
    playbook_summaries = ""
    try:
        retriever = get_retriever()
        query = description or f"{anomaly_type} in {table_name}"
        similar_docs = retriever.retrieve_similar_anomalies(query)
        similar_summaries = "\n".join(d.page_content[:300] for d in similar_docs[:3])
        playbook_docs = retriever.retrieve_playbook(query, anomaly_type)
        playbook_summaries = "\n".join(d.page_content[:300] for d in playbook_docs[:3])
    except Exception as e:
        logger.warning("RAG retrieval failed: %s", e)

    # LLM synthesis (tier1 - gpt-4o reasoning)
    model = MODELS["tier1_reasoning"]
    prompt = _build_prompt(
        table_name,
        anomaly_type,
        validation_result.get("summary", "")[:500],
        detection_result.get("summary", "")[:500],
        str(mc_anomalies)[:600],
        similar_summaries,
        playbook_summaries,
    )
    try:
        response = await invoke_with_retry(model, prompt)
        result = _parser.parse(response.content)
    except Exception as e:
        logger.warning("Diagnosis LLM failed: %s", e)
        result = DiagnosisResult(
            severity=state.get("severity") or "warning",
            root_cause=f"Unable to determine root cause for {anomaly_type} in {table_name}",
            root_cause_category="unknown",
            confidence=0.4,
            supporting_evidence=[detection_result.get("summary", "")],
            recommended_next_steps=["Manual investigation required"],
            summary=f"Diagnosis for {table_name}: {anomaly_type} (fallback)",
        )

    # Record decision
    try:
        memory = get_long_term_memory()
        memory.record_decision(
            AgentDecision(
                decision_id=str(uuid.uuid4()),
                investigation_id=investigation_id,
                agent_name="diagnosis_agent",
                decision_type="diagnosis",
                input_summary=f"table={table_name} type={anomaly_type}",
                output_summary=result.summary[:500],
                confidence=result.confidence,
                was_correct=None,
                created_at=datetime.now(tz=UTC),
            )
        )
    except Exception as e:
        logger.warning("Could not record decision: %s", e)

    return {"diagnosis_result": result.model_dump()}
