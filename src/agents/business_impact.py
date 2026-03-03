import logging
import uuid
from datetime import UTC, datetime

from langchain_core.output_parsers import PydanticOutputParser

from src.agents.orchestrator import (
    BusinessImpactResult,
    call_mcp_tool,
    get_long_term_memory,
    get_retriever,
)
from src.config import MCP_CUSTOM_URL, MODELS, invoke_with_retry
from src.memory.long_term import AgentDecision

logger = logging.getLogger(__name__)

_parser = PydanticOutputParser(pydantic_object=BusinessImpactResult)


def _build_prompt(
    table_name: str,
    severity: str,
    anomaly_type: str,
    impact_data: str,
    business_context: str,
    lineage_summary: str,
) -> str:
    return (
        "You are a business impact assessment agent.\n"
        "Assess SLA risk, financial exposure, and escalation requirements.\n\n"
        f"Table: {table_name}  Severity: {severity}  Anomaly: {anomaly_type}\n\n"
        f"Business impact data:\n{impact_data}\n\n"
        f"Business context:\n{business_context}\n\n"
        f"Lineage / downstream exposure:\n{lineage_summary}\n\n"
        f"{_parser.get_format_instructions()}"
    )


async def business_impact_node(state: dict) -> dict:
    """Assess SLA breaches, financial impact, and escalation requirements."""
    trigger = state.get("trigger") or {}
    table_name = trigger.get("table_name", "unknown")
    investigation_id = state.get("investigation_id", "")
    severity = state.get("severity") or "info"
    detection_result = state.get("detection_result") or {}
    lineage_result = state.get("lineage_result") or {}
    anomaly_type = detection_result.get("anomaly_type") or trigger.get("alert_type", "manual")

    # MCP: assess business impact
    impact_data: dict = {}
    try:
        impact_data = await call_mcp_tool(  # type: ignore[assignment]
            MCP_CUSTOM_URL,
            "assess_business_impact",
            {
                "table_name": table_name,
                "anomaly_type": anomaly_type,
                "severity": severity,
            },
        )
    except Exception as e:
        logger.warning("Business impact MCP call failed: %s", e)

    # RAG: business context
    biz_context = ""
    try:
        retriever = get_retriever()
        biz_docs = retriever.retrieve_business_context(table_name)
        biz_context = "\n".join(d.page_content[:300] for d in biz_docs[:3])
    except Exception as e:
        logger.warning("Business context retrieval failed: %s", e)

    # LLM synthesis (tier1 - gpt-4o)
    model = MODELS["tier1_reasoning"]
    prompt = _build_prompt(
        table_name,
        severity,
        anomaly_type,
        str(impact_data)[:800],
        biz_context,
        lineage_result.get("lineage_summary", "")[:500],
    )
    try:
        response = await invoke_with_retry(model, prompt)
        result = _parser.parse(response.content)
    except Exception as e:
        logger.warning("Business impact LLM failed: %s", e)
        escalation_required = severity in ("critical", "high")
        downstream = lineage_result.get("downstream_tables") or []
        result = BusinessImpactResult(
            affected_slas=[{"table": table_name, "sla_hours": 2.0, "breached": True}],
            business_criticality=severity,
            estimated_financial_impact=None,
            affected_teams=impact_data.get("teams") or [],
            escalation_required=escalation_required,
            escalation_contacts=[],
            business_summary=(
                f"Business impact for {table_name}: "
                f"{len(downstream)} downstream tables affected (fallback)"
            ),
        )

    # Record decision
    try:
        memory = get_long_term_memory()
        memory.record_decision(
            AgentDecision(
                decision_id=str(uuid.uuid4()),
                investigation_id=investigation_id,
                agent_name="business_impact_agent",
                decision_type="business_impact",
                input_summary=f"table={table_name} severity={severity}",
                output_summary=result.business_summary[:500],
                confidence=0.75,
                was_correct=None,
                created_at=datetime.now(tz=UTC),
            )
        )
    except Exception as e:
        logger.warning("Could not record decision: %s", e)

    return {"business_impact": result.model_dump()}
