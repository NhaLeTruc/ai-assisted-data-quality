import os
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph as CompiledGraph

from src.agents.business_impact import business_impact_node
from src.agents.detection import detection_node
from src.agents.diagnosis import diagnosis_node
from src.agents.lineage import lineage_node
from src.agents.orchestrator import (
    orchestrator_node,
    route_from_orchestrator,
    safe_agent_node,
)
from src.agents.repair import repair_node
from src.agents.validation import validation_node


class DataQualityState(TypedDict):
    # Investigation identity
    investigation_id: str  # UUID4, generated at API layer
    triggered_at: str  # ISO 8601 datetime string

    # Input trigger (serialized InvestigationTrigger)
    trigger: dict

    # Phase 1 - Detection
    validation_result: dict | None  # Serialized ValidationResult
    detection_result: dict | None  # Serialized DetectionResult

    # Phase 2 - Diagnosis
    diagnosis_result: dict | None  # Serialized DiagnosisResult
    lineage_result: dict | None  # Serialized LineageResult

    # Phase 3 - Remediation
    business_impact: dict | None  # Serialized BusinessImpactResult
    remediation_plan: dict | None  # Serialized RemediationPlan
    remediation_result: dict | None  # Serialized RemediationOutcome

    # Control flow
    current_phase: str  # "initial"|"detection_complete"|"diagnosis_complete"|...
    severity: str | None  # "critical"|"high"|"warning"|"info"
    should_auto_remediate: bool  # True when severity in [critical,high] AND conf > 0.8
    workflow_complete: bool  # Terminal flag; set before routing to END
    errors: list[str]  # Accumulated error strings; agents append, never replace
    agent_latencies: dict  # {agent_name: elapsed_ms}


class WorkflowMemory(TypedDict):
    investigation_id: str
    started_at: str  # ISO 8601
    shared_context: dict  # {agent_name: findings_summary}
    agent_messages: list[dict]  # [{"from": str, "timestamp": str, "content": dict}]
    decisions: list[dict]  # [{"agent": str, "decision": str, "rationale": str, ...}]
    agent_latencies: dict  # {agent_name: elapsed_ms}


def build_workflow(sqlite_path: str) -> CompiledGraph:
    """Build and compile the full LangGraph data-quality investigation workflow."""
    os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
    memory = SqliteSaver.from_conn_string(sqlite_path)

    graph: StateGraph = StateGraph(DataQualityState)

    graph.add_node("orchestrator", safe_agent_node(orchestrator_node))
    graph.add_node("validation", safe_agent_node(validation_node))
    graph.add_node("detection", safe_agent_node(detection_node))
    graph.add_node("diagnosis", safe_agent_node(diagnosis_node))
    graph.add_node("lineage", safe_agent_node(lineage_node))
    graph.add_node("impact_agent", safe_agent_node(business_impact_node))
    graph.add_node("repair", safe_agent_node(repair_node))

    graph.set_entry_point("orchestrator")

    graph.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {
            "validation": "validation",
            "diagnosis": "diagnosis",
            "business_impact": "impact_agent",
            "complete": END,
        },
    )

    # Phase 1 chain: validation → detection → orchestrator
    graph.add_edge("validation", "detection")
    graph.add_edge("detection", "orchestrator")

    # Phase 2 chain: diagnosis → lineage → orchestrator
    graph.add_edge("diagnosis", "lineage")
    graph.add_edge("lineage", "orchestrator")

    # Phase 3 chain: business_impact → repair → orchestrator
    graph.add_edge("impact_agent", "repair")
    graph.add_edge("repair", "orchestrator")

    return graph.compile(checkpointer=memory)
