import logging
import uuid
from datetime import UTC, datetime

from langchain_core.output_parsers import PydanticOutputParser

from src.agents.orchestrator import (
    ValidationResult,
    call_mcp_tool,
    get_long_term_memory,
    get_retriever,
)
from src.config import MCP_GX_URL, MODELS, invoke_with_retry
from src.memory.long_term import AgentDecision

logger = logging.getLogger(__name__)

_parser = PydanticOutputParser(pydantic_object=ValidationResult)


def _build_prompt(
    investigation_id: str,
    table_name: str,
    dataset_id: str,
    alert_type: str,
    dq_rules: str,
    gx_results: str,
) -> str:
    return (
        "You are a data quality validation agent.\n"
        "Analyze the GX validation results and DQ rules, then produce a report.\n\n"
        f"Investigation ID: {investigation_id}\n"
        f"Table: {table_name}  Dataset: {dataset_id}  Alert: {alert_type}\n\n"
        f"DQ Rules from knowledge base:\n{dq_rules}\n\n"
        f"GX Validation results:\n{gx_results}\n\n"
        f"{_parser.get_format_instructions()}"
    )


async def validation_node(state: dict) -> dict:
    """Validate the dataset with GX and RAG-retrieved DQ rules."""
    trigger = state.get("trigger") or {}
    table_name = trigger.get("table_name", "unknown")
    dataset_id = trigger.get("dataset_id", table_name)
    alert_type = trigger.get("alert_type", "manual")
    investigation_id = state.get("investigation_id", "")

    # RAG: retrieve DQ rules for this table
    dq_rules = "No rules found."
    try:
        retriever = get_retriever()
        rules_docs = retriever.retrieve_dq_rules(table_name)
        if rules_docs:
            dq_rules = "\n".join(d.page_content for d in rules_docs)
    except Exception as e:
        logger.warning("DQ rules retrieval failed: %s", e)

    # MCP: run GX validation pipeline
    suite_name = f"{dataset_id}_suite"
    gx_result: dict = {}
    try:
        await call_mcp_tool(
            MCP_GX_URL,
            "create_expectation_suite",
            {"dataset_id": dataset_id, "suite_name": suite_name},
        )
        await call_mcp_tool(
            MCP_GX_URL,
            "run_checkpoint",
            {"dataset_id": dataset_id, "suite_name": suite_name},
        )
        gx_result = await call_mcp_tool(  # type: ignore[assignment]
            MCP_GX_URL,
            "get_validation_results",
            {"dataset_id": dataset_id, "suite_name": suite_name},
        )
    except Exception as e:
        logger.warning("GX MCP call failed: %s", e)

    # LLM synthesis
    model = MODELS["tier3_simple"]
    prompt = _build_prompt(
        investigation_id,
        table_name,
        dataset_id,
        alert_type,
        dq_rules,
        str(gx_result)[:2000],
    )
    try:
        response = await invoke_with_retry(model, prompt)
        result = _parser.parse(response.content)
    except Exception as e:
        logger.warning("Validation LLM failed: %s", e)
        failed = gx_result.get("failed_expectations") or []
        result = ValidationResult(
            passed=not bool(failed),
            failed_expectations=failed,
            total_expectations=gx_result.get("statistics", {}).get("evaluated", 0),
            failure_count=len(failed),
            details=gx_result,
            summary=f"Validation for {table_name}: {alert_type} (fallback)",
        )

    # Record decision
    try:
        memory = get_long_term_memory()
        memory.record_decision(
            AgentDecision(
                decision_id=str(uuid.uuid4()),
                investigation_id=investigation_id,
                agent_name="validation_agent",
                decision_type="validation",
                input_summary=f"table={table_name} alert={alert_type}",
                output_summary=result.summary[:500],
                confidence=0.8 if result.passed else 0.6,
                was_correct=None,
                created_at=datetime.now(tz=UTC),
            )
        )
    except Exception as e:
        logger.warning("Could not record decision: %s", e)

    return {"validation_result": result.model_dump()}
