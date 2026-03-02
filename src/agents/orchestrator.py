from typing import Any, Literal

from pydantic import BaseModel


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
    anomaly_type: str | None = None  # "null_spike"|"schema_drift"|"volume_drop"|"freshness_lag"
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
    critical_path_breached: bool  # True if any SLA-critical downstream table is affected
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


def route_from_orchestrator(
    state: dict,
) -> Literal["validation", "diagnosis", "business_impact", "complete"]:
    """Route to the next pipeline stage. Replaced by full implementation in T-30."""
    raise NotImplementedError
