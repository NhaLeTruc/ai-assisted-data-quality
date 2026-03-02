from typing import TypedDict


class DataQualityState(TypedDict):
    # Investigation identity
    investigation_id: str  # UUID4, generated at API layer
    triggered_at: str  # ISO 8601 datetime string

    # Input trigger (serialized InvestigationTrigger)
    trigger: dict

    # Phase 1 — Detection
    validation_result: dict | None  # Serialized ValidationResult
    detection_result: dict | None  # Serialized DetectionResult

    # Phase 2 — Diagnosis
    diagnosis_result: dict | None  # Serialized DiagnosisResult
    lineage_result: dict | None  # Serialized LineageResult

    # Phase 3 — Remediation
    business_impact: dict | None  # Serialized BusinessImpactResult
    remediation_plan: dict | None  # Serialized RemediationPlan
    remediation_result: dict | None  # Serialized RemediationOutcome

    # Control flow
    current_phase: str  # "initial"|"detection_complete"|"diagnosis_complete"|"remediation_complete"
    severity: str | None  # "critical"|"high"|"warning"|"info"
    should_auto_remediate: bool  # True when severity in [critical,high] AND confidence > 0.8
    workflow_complete: bool  # Terminal flag; set before routing to END
    errors: list[str]  # Accumulated error strings; agents append, never replace
    agent_latencies: dict  # {agent_name: elapsed_ms}


class WorkflowMemory(TypedDict):
    investigation_id: str
    started_at: str  # ISO 8601
    shared_context: dict  # {agent_name: findings_summary}
    agent_messages: list[dict]  # [{"from": str, "timestamp": str, "content": dict}]
    decisions: list[dict]  # [{"agent": str, "decision": str, "rationale": str, "timestamp": str}]
    agent_latencies: dict  # {agent_name: elapsed_ms}
