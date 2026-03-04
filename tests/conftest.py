"""
Shared test fixtures and environment setup for the AI-assisted-data-quality test suite.

IMPORTANT — module-level code runs at pytest collection time, BEFORE any test module
imports src.*. This ensures:

  1. ANTHROPIC_API_KEY and OPENAI_API_KEY are set to dummy values so ChatAnthropic
     does not raise on import.
  2. The mock Anthropic server is running and ANTHROPIC_BASE_URL points to it, so
     ChatAnthropic instances created at config.py import time already use the mock.
  3. langchain_community.embeddings is stubbed so HuggingFaceEmbeddings does NOT
     trigger a ~400 MB model download.
  4. Heavy/broken modules (chromadb, langchain_chroma, etc.) that may not be
     installed in the dev environment are stubbed.

conftest.py is exempt from the 500-line pre-commit hook (EXEMPT_NAMES = {"conftest.py"}).
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# 1. Environment variables — set BEFORE any src.* import so ChatAnthropic
#    reads them at instantiation time (which happens on first config.py import).
# ---------------------------------------------------------------------------

os.environ.setdefault("ANTHROPIC_API_KEY", "test-placeholder")  # pragma: allowlist secret
os.environ.setdefault("OPENAI_API_KEY", "test-placeholder")  # pragma: allowlist secret

# ---------------------------------------------------------------------------
# 2. Start mock Anthropic server and point ANTHROPIC_BASE_URL at it.
#    Must happen before src.config is imported so the ChatAnthropic instances
#    in MODELS use the mock URL.
# ---------------------------------------------------------------------------

from tests.integration.mock_anthropic_server import (
    MOCK_HOST,
    MOCK_PORT,
    ensure_mock_server_running,
    reset_queues,
)

ensure_mock_server_running()
os.environ["ANTHROPIC_BASE_URL"] = f"http://{MOCK_HOST}:{MOCK_PORT}"

# ---------------------------------------------------------------------------
# 3. Stub heavy / broken modules before any src.* import.
#    langchain_community.embeddings wraps HuggingFaceEmbeddings which downloads
#    a 400 MB model. Stubbing it returns a MagicMock instead.
# ---------------------------------------------------------------------------

_STUBS = [
    "langchain_community.embeddings",
    "langchain_community.embeddings.huggingface",
    "langchain_community.cross_encoders",
    "langchain_community.retrievers",
    # langchain.retrievers triggers a broken import chain (langchain_core.memory removed)
    "langchain.retrievers",
    "langchain.retrievers.document_compressors",
    # langchain_chroma requires chromadb HTTP client at import time in some envs
    "langchain_chroma",
]
for _mod in _STUBS:
    sys.modules.setdefault(_mod, MagicMock())

# ---------------------------------------------------------------------------
# 4. pytest fixtures
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_mock_server_queues():
    """Reset mock Anthropic server response queues before every test."""
    reset_queues()
    yield


# ---------------------------------------------------------------------------
# Canned JSON payloads (must match each agent's Pydantic model schema exactly)
# ---------------------------------------------------------------------------

CANNED_VALIDATION_JSON = json.dumps(
    {
        "passed": False,
        "failed_expectations": ["expect_column_values_to_not_be_null"],
        "total_expectations": 5,
        "failure_count": 1,
        "details": {"evaluated": 5, "successful": 4},
        "summary": "Orders table has 1 null violation in customer_id column",
    }
)

CANNED_DETECTION_JSON = json.dumps(
    {
        "anomaly_detected": True,
        "anomaly_type": "null_spike",
        "confidence": 0.91,
        "affected_tables": ["orders"],
        "affected_columns": ["customer_id"],
        "baseline_metric": None,
        "observed_metric": None,
        "deviation_percent": None,
        "similar_past_anomalies": [],
        "summary": "Null spike detected in orders.customer_id",
    }
)

CANNED_DIAGNOSIS_JSON = json.dumps(
    {
        "severity": "high",
        "root_cause": "Upstream API deployment returning null customer_id values",
        "root_cause_category": "upstream_failure",
        "confidence": 0.87,
        "supporting_evidence": ["ETL job logs", "Null spike at 02:00 UTC"],
        "recommended_next_steps": ["Rollback API v2.3.1", "Trigger backfill"],
        "estimated_impact_records": None,
        "summary": "Upstream API deployment caused null spike in orders",
    }
)

CANNED_LINEAGE_JSON = json.dumps(
    {
        "upstream_tables": ["api_gateway", "user_service"],
        "downstream_tables": ["revenue_report", "customer_segment_model"],
        "upstream_pipelines": ["etl_orders"],
        "downstream_consumers": ["analytics_team"],
        "impact_radius": 4,
        "critical_path_breached": True,
        "lineage_summary": "4 downstream nodes affected; SLA at risk",
    }
)

CANNED_BUSINESS_IMPACT_JSON = json.dumps(
    {
        "affected_slas": [{"table": "orders", "sla_hours": 2.0, "breached": True}],
        "business_criticality": "critical",
        "estimated_financial_impact": "$50K/hour revenue at risk",
        "affected_teams": ["data_engineering", "finance"],
        "escalation_required": True,
        "escalation_contacts": ["oncall@company.com"],
        "business_summary": "Critical SLA breach affecting revenue pipeline",
    }
)

CANNED_REMEDIATION_JSON = json.dumps(
    {
        "recommended_action": "Rollback API and backfill null rows",
        "action_type": "rollback",
        "steps": ["Rollback API", "Identify affected rows", "Backfill", "Validate"],
        "dry_run_safe": True,
        "estimated_duration_minutes": 90,
        "risk_level": "low",
        "playbook_reference": "PB-ROLLBACK-001",
        "alternative_actions": ["quarantine", "notify"],
    }
)


# ---------------------------------------------------------------------------
# Shared state fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_state() -> dict:
    """Minimal DataQualityState for node unit tests."""
    return {
        "investigation_id": "test-inv-001",
        "triggered_at": "2026-03-04T00:00:00+00:00",
        "trigger": {
            "dataset_id": "orders_2026_03",
            "table_name": "orders",
            "alert_type": "null_spike",
            "description": "Unusually high null rate in customer_id",
            "context": {},
        },
        "validation_result": None,
        "detection_result": None,
        "diagnosis_result": None,
        "lineage_result": None,
        "business_impact": None,
        "remediation_plan": None,
        "remediation_result": None,
        "current_phase": "initial",
        "severity": None,
        "should_auto_remediate": False,
        "workflow_complete": False,
        "errors": [],
        "agent_latencies": {},
    }


@pytest.fixture()
def state_after_detection(minimal_state) -> dict:
    detection = json.loads(CANNED_DETECTION_JSON)
    return {
        **minimal_state,
        "validation_result": json.loads(CANNED_VALIDATION_JSON),
        "detection_result": detection,
        "current_phase": "detection_complete",
        "severity": "critical",
    }


@pytest.fixture()
def state_after_lineage(state_after_detection) -> dict:
    diagnosis = json.loads(CANNED_DIAGNOSIS_JSON)
    return {
        **state_after_detection,
        "diagnosis_result": diagnosis,
        "lineage_result": json.loads(CANNED_LINEAGE_JSON),
        "current_phase": "diagnosis_complete",
        "severity": diagnosis["severity"],
    }


@pytest.fixture()
def mock_retriever() -> MagicMock:
    r = MagicMock()
    r.retrieve_dq_rules.return_value = []
    r.retrieve_similar_anomalies.return_value = []
    r.retrieve_business_context.return_value = []
    r.retrieve_playbook.return_value = []
    return r


@pytest.fixture()
def mock_memory() -> MagicMock:
    m = MagicMock()
    m.record_decision.return_value = None
    return m


@pytest.fixture()
def ai_message_factory():
    """Return a callable that wraps a JSON string in an AIMessage."""
    from langchain_core.messages import AIMessage

    def _make(json_str: str):
        return AIMessage(content=json_str)

    return _make
