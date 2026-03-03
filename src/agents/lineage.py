import logging
import uuid
from datetime import UTC, datetime

from langchain_core.output_parsers import PydanticOutputParser

from src.agents.orchestrator import (
    LineageResult,
    call_mcp_tool,
    get_long_term_memory,
    get_retriever,
)
from src.config import MCP_CUSTOM_URL, MODELS, invoke_with_retry
from src.memory.long_term import AgentDecision

logger = logging.getLogger(__name__)

_parser = PydanticOutputParser(pydantic_object=LineageResult)


def _build_prompt(
    table_name: str,
    lineage_data: str,
    business_context: str,
    diagnosis_summary: str,
) -> str:
    return (
        "You are a data lineage analysis agent.\n"
        "Map the impact of the anomaly across upstream and downstream systems.\n\n"
        f"Table: {table_name}\n\n"
        f"Lineage graph:\n{lineage_data}\n\n"
        f"Business context:\n{business_context}\n\n"
        f"Diagnosis summary:\n{diagnosis_summary}\n\n"
        f"{_parser.get_format_instructions()}"
    )


async def lineage_node(state: dict) -> dict:
    """Map data lineage and propagate confirmed severity from diagnosis."""
    trigger = state.get("trigger") or {}
    table_name = trigger.get("table_name", "unknown")
    investigation_id = state.get("investigation_id", "")
    diagnosis_result = state.get("diagnosis_result") or {}
    diagnosis_severity = diagnosis_result.get("severity", state.get("severity") or "info")

    # MCP: analyze lineage
    lineage_data: dict = {}
    try:
        lineage_data = await call_mcp_tool(  # type: ignore[assignment]
            MCP_CUSTOM_URL,
            "analyze_data_lineage",
            {"table_name": table_name, "depth": 3},
        )
    except Exception as e:
        logger.warning("Lineage MCP call failed: %s", e)

    # RAG: business context for impact assessment
    biz_context = ""
    try:
        retriever = get_retriever()
        biz_docs = retriever.retrieve_business_context(table_name)
        biz_context = "\n".join(d.page_content[:300] for d in biz_docs[:3])
    except Exception as e:
        logger.warning("Business context retrieval failed: %s", e)

    # LLM synthesis
    model = MODELS["tier2_structured"]
    prompt = _build_prompt(
        table_name,
        str(lineage_data)[:800],
        biz_context,
        diagnosis_result.get("summary", "")[:500],
    )
    try:
        response = await invoke_with_retry(model, prompt)
        result = _parser.parse(response.content)
    except Exception as e:
        logger.warning("Lineage LLM failed: %s", e)
        upstream = lineage_data.get("upstream") or []
        downstream = lineage_data.get("downstream") or []
        result = LineageResult(
            upstream_tables=upstream,
            downstream_tables=downstream,
            upstream_pipelines=[],
            downstream_consumers=[],
            impact_radius=lineage_data.get("impact_radius", len(downstream)),
            critical_path_breached=diagnosis_severity in ("critical", "high"),
            lineage_summary=f"Lineage for {table_name}: {len(downstream)} downstream (fallback)",
        )

    # Record decision
    try:
        memory = get_long_term_memory()
        memory.record_decision(
            AgentDecision(
                decision_id=str(uuid.uuid4()),
                investigation_id=investigation_id,
                agent_name="lineage_agent",
                decision_type="lineage",
                input_summary=f"table={table_name} severity={diagnosis_severity}",
                output_summary=result.lineage_summary[:500],
                confidence=0.8,
                was_correct=None,
                created_at=datetime.now(tz=UTC),
            )
        )
    except Exception as e:
        logger.warning("Could not record decision: %s", e)

    return {
        "lineage_result": result.model_dump(),
        "current_phase": "diagnosis_complete",
        "severity": diagnosis_severity,
    }
