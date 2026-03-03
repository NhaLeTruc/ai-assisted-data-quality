import logging
import uuid
from datetime import UTC, datetime

from langchain_core.output_parsers import PydanticOutputParser

from src.agents.orchestrator import (
    RemediationOutcome,
    RemediationPlan,
    call_mcp_tool,
    get_long_term_memory,
    get_retriever,
)
from src.config import MCP_CUSTOM_URL, MODELS, invoke_with_retry
from src.memory.long_term import AgentDecision

logger = logging.getLogger(__name__)

_plan_parser = PydanticOutputParser(pydantic_object=RemediationPlan)
_outcome_parser = PydanticOutputParser(pydantic_object=RemediationOutcome)


def _build_plan_prompt(
    table_name: str,
    anomaly_type: str,
    severity: str,
    diagnosis_summary: str,
    similar_resolutions: str,
    playbooks: str,
) -> str:
    return (
        "You are a data quality remediation planning agent.\n"
        "Create a concrete, safe remediation plan for the detected anomaly.\n\n"
        f"Table: {table_name}  Anomaly: {anomaly_type}  Severity: {severity}\n\n"
        f"Diagnosis:\n{diagnosis_summary}\n\n"
        f"Similar past resolutions:\n{similar_resolutions}\n\n"
        f"Applicable playbooks:\n{playbooks}\n\n"
        f"{_plan_parser.get_format_instructions()}"
    )


async def repair_node(state: dict) -> dict:
    """Plan and apply (dry-run) remediation using playbooks and similar resolutions."""
    trigger = state.get("trigger") or {}
    table_name = trigger.get("table_name", "unknown")
    description = trigger.get("description", "")
    investigation_id = state.get("investigation_id", "")
    severity = state.get("severity") or "info"
    should_auto_remediate = state.get("should_auto_remediate", False)
    detection_result = state.get("detection_result") or {}
    diagnosis_result = state.get("diagnosis_result") or {}
    anomaly_type = detection_result.get("anomaly_type") or trigger.get("alert_type", "manual")

    # MCP: find similar anomalies for resolution context
    similar_anomalies: list = []
    try:
        similar_anomalies = await call_mcp_tool(  # type: ignore[assignment]
            MCP_CUSTOM_URL,
            "get_similar_anomalies",
            {
                "description": description or f"{anomaly_type} in {table_name}",
                "anomaly_type": anomaly_type,
                "limit": 3,
            },
        )
    except Exception as e:
        logger.warning("Similar anomalies MCP call failed: %s", e)

    # RAG: remediation playbooks
    playbook_summaries = ""
    playbook_id: str | None = None
    try:
        retriever = get_retriever()
        query = description or f"{anomaly_type} in {table_name}"
        playbook_docs = retriever.retrieve_playbook(query, anomaly_type)
        if playbook_docs:
            playbook_summaries = "\n".join(d.page_content[:300] for d in playbook_docs[:3])
            playbook_id = playbook_docs[0].metadata.get("playbook_id")
    except Exception as e:
        logger.warning("Playbook retrieval failed: %s", e)

    # LLM: generate remediation plan
    model = MODELS["tier2_structured"]
    plan_prompt = _build_plan_prompt(
        table_name,
        anomaly_type,
        severity,
        diagnosis_result.get("summary", "")[:500],
        str(similar_anomalies)[:500],
        playbook_summaries,
    )
    try:
        response = await invoke_with_retry(model, plan_prompt)
        plan = _plan_parser.parse(response.content)
        if playbook_id and not plan.playbook_reference:
            plan = plan.model_copy(update={"playbook_reference": playbook_id})
    except Exception as e:
        logger.warning("Remediation plan LLM failed: %s", e)
        plan = RemediationPlan(
            recommended_action=f"Investigate {anomaly_type} in {table_name}",
            action_type="manual_review",
            steps=["Alert on-call engineer", "Review pipeline logs", "Validate source data"],
            dry_run_safe=True,
            estimated_duration_minutes=30,
            risk_level="medium",
            playbook_reference=playbook_id,
            alternative_actions=["notify", "quarantine"],
        )

    # MCP: apply remediation (always dry_run in demo unless auto-remediate + low risk)
    dry_run = not (should_auto_remediate and plan.risk_level == "low")
    anomaly_id = detection_result.get("anomaly_type", "unknown")
    apply_result: dict = {}
    try:
        apply_result = await call_mcp_tool(  # type: ignore[assignment]
            MCP_CUSTOM_URL,
            "apply_remediation",
            {
                "anomaly_id": anomaly_id,
                "action": plan.action_type,
                "dry_run": dry_run,
            },
        )
    except Exception as e:
        logger.warning("Apply remediation MCP call failed: %s", e)

    # Build outcome
    status = apply_result.get("status", "dry_run" if dry_run else "failed")
    outcome = RemediationOutcome(
        status=status,
        action_taken=plan.action_type,
        records_affected=apply_result.get("records_affected"),
        rollback_available=apply_result.get("rollback_available", True),
        outcome_summary=(
            f"{status.upper()}: {plan.action_type} for {table_name} "
            f"({'dry run' if dry_run else 'applied'})"
        ),
    )

    # Record decisions
    try:
        memory = get_long_term_memory()
        now = datetime.now(tz=UTC)
        memory.record_decision(
            AgentDecision(
                decision_id=str(uuid.uuid4()),
                investigation_id=investigation_id,
                agent_name="repair_agent",
                decision_type="repair",
                input_summary=f"table={table_name} type={anomaly_type}",
                output_summary=f"plan={plan.action_type} risk={plan.risk_level}"[:500],
                confidence=0.8,
                was_correct=None,
                created_at=now,
            )
        )
    except Exception as e:
        logger.warning("Could not record decision: %s", e)

    return {
        "remediation_plan": plan.model_dump(),
        "remediation_result": outcome.model_dump(),
        "current_phase": "remediation_complete",
        "workflow_complete": True,
    }
