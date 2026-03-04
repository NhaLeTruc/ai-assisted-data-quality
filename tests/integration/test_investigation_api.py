"""Integration tests for the investigation API.

Uses a lightweight test FastAPI app that shares the real routers but has
mock app.state (workflow, retriever, memory, indexer) injected directly,
avoiding startup/shutdown lifecycle complexity and external service deps.

The mock Anthropic server (started in conftest.py) is already running, so
ChatAnthropic calls resolve correctly if any real LLM path is exercised.
"""

import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.conftest import (
    CANNED_BUSINESS_IMPACT_JSON,
    CANNED_DETECTION_JSON,
    CANNED_DIAGNOSIS_JSON,
    CANNED_LINEAGE_JSON,
    CANNED_REMEDIATION_JSON,
    CANNED_VALIDATION_JSON,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decisions_db(path: str) -> None:
    """Create the agent_decisions table used by GET /api/v1/investigations."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_decisions (
            decision_id       TEXT PRIMARY KEY,
            investigation_id  TEXT NOT NULL,
            agent_name        TEXT NOT NULL,
            decision_type     TEXT NOT NULL,
            input_summary     TEXT,
            output_summary    TEXT,
            confidence        REAL DEFAULT 0.5,
            was_correct       INTEGER,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def _make_snapshot(investigation_id: str) -> MagicMock:
    """Return a mock that mimics a LangGraph state snapshot with values."""
    import json

    snap = MagicMock()
    snap.values = {
        "investigation_id": investigation_id,
        "current_phase": "detection_complete",
        "workflow_complete": True,
        "validation_result": json.loads(CANNED_VALIDATION_JSON),
        "detection_result": json.loads(CANNED_DETECTION_JSON),
        "diagnosis_result": json.loads(CANNED_DIAGNOSIS_JSON),
        "lineage_result": json.loads(CANNED_LINEAGE_JSON),
        "business_impact": json.loads(CANNED_BUSINESS_IMPACT_JSON),
        "remediation_plan": json.loads(CANNED_REMEDIATION_JSON),
        "severity": "critical",
        "errors": [],
    }
    return snap


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def test_app(tmp_path):
    """Minimal FastAPI test app with mocked state — no startup events."""
    from src.api.health import router as health_router
    from src.api.routes import router as api_router

    app = FastAPI(title="Test App")
    app.include_router(health_router)
    app.include_router(api_router)

    # Decisions DB (real SQLite — list_investigations reads it directly)
    db_path = str(tmp_path / "decisions.db")
    _make_decisions_db(db_path)

    # Mock workflow — astream is used with `async for` (not awaited), so it must
    # be a callable that returns an async generator, not an AsyncMock.
    mock_workflow = MagicMock()
    mock_workflow.astream = _async_empty_gen
    mock_workflow.aget_state = AsyncMock(return_value=None)  # default: not found

    # Mock memory
    mock_memory = MagicMock()
    mock_memory._db_path = db_path
    mock_memory.record_feedback.return_value = 1

    app.state.workflow = mock_workflow
    app.state.retriever = MagicMock()
    app.state.long_term_memory = mock_memory
    app.state.indexer = MagicMock()
    app.state.indexer.index_documents.return_value = 0

    return app


async def _async_empty_gen(*args, **kwargs):
    """Async generator that yields nothing (simulates completed workflow stream)."""
    return
    yield  # pragma: no cover — makes this an async generator


@pytest.fixture()
async def api_client(test_app):
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        yield client, test_app


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


async def test_health_returns_app_healthy(api_client):
    client, _ = api_client
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["checks"]["app"] == "healthy"
    assert "status" in body


# ---------------------------------------------------------------------------
# POST /api/v1/investigations
# ---------------------------------------------------------------------------


async def test_start_investigation_returns_202(api_client):
    client, _ = api_client
    payload = {
        "dataset_id": "orders_2026_03",
        "table_name": "orders",
        "alert_type": "null_spike",
        "description": "High null rate detected",
        "context": {},
    }
    resp = await client.post("/api/v1/investigations", json=payload)
    assert resp.status_code == 202


async def test_start_investigation_returns_investigation_id(api_client):
    client, _ = api_client
    payload = {
        "dataset_id": "orders_2026_03",
        "table_name": "orders",
        "alert_type": "null_spike",
        "description": "High null rate",
        "context": {},
    }
    resp = await client.post("/api/v1/investigations", json=payload)
    body = resp.json()
    assert "investigation_id" in body
    assert "status" in body
    assert body["status"] == "started"
    assert "triggered_at" in body


async def test_start_investigation_background_task_uses_trigger_data(api_client):
    """The workflow.aget_state is available and investigation_id is a UUID string."""
    client, _ = api_client
    payload = {
        "dataset_id": "orders_2026_03",
        "table_name": "orders",
        "alert_type": "null_spike",
        "description": "High null rate",
        "context": {},
    }
    resp = await client.post("/api/v1/investigations", json=payload)
    body = resp.json()
    # investigation_id must look like a UUID (8-4-4-4-12)
    import re

    assert re.match(r"[0-9a-f-]{36}", body["investigation_id"])


async def test_start_investigation_missing_required_fields_returns_422(api_client):
    client, _ = api_client
    resp = await client.post("/api/v1/investigations", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/investigations
# ---------------------------------------------------------------------------


async def test_list_investigations_empty_db_returns_empty_list(api_client):
    client, _ = api_client
    resp = await client.get("/api/v1/investigations")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_investigations_returns_investigation_ids(api_client, tmp_path):
    client, app = api_client
    db_path = app.state.long_term_memory._db_path
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO agent_decisions VALUES "
        "('dec-1','inv-abc','detection_agent','detection','t','t',0.9,NULL,'2026-03-04')"
    )
    conn.commit()
    conn.close()

    resp = await client.get("/api/v1/investigations")
    assert resp.status_code == 200
    body = resp.json()
    assert any(row["investigation_id"] == "inv-abc" for row in body)


# ---------------------------------------------------------------------------
# GET /api/v1/investigations/{id}
# ---------------------------------------------------------------------------


async def test_get_investigation_not_found_returns_404(api_client):
    client, _ = api_client
    resp = await client.get("/api/v1/investigations/nonexistent-id")
    assert resp.status_code == 404


async def test_get_investigation_returns_state_values(api_client):
    client, app = api_client
    inv_id = "test-inv-001"
    app.state.workflow.aget_state.return_value = _make_snapshot(inv_id)

    resp = await client.get(f"/api/v1/investigations/{inv_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["investigation_id"] == inv_id
    assert body["workflow_complete"] is True
    assert "detection_result" in body


async def test_get_investigation_workflow_exception_returns_404(api_client):
    client, app = api_client
    app.state.workflow.aget_state.side_effect = RuntimeError("checkpoint not found")

    resp = await client.get("/api/v1/investigations/boom-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/investigations/{id}/feedback
# ---------------------------------------------------------------------------


async def test_submit_feedback_returns_updated_true(api_client):
    client, _ = api_client
    resp = await client.post(
        "/api/v1/investigations/test-inv-001/feedback",
        json={"was_resolved": True, "resolution_notes": "Fixed upstream API"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated"] is True


# ---------------------------------------------------------------------------
# POST /api/v1/rag/query
# ---------------------------------------------------------------------------


async def test_rag_query_anomaly_patterns_returns_results(api_client):
    client, app = api_client
    doc = MagicMock()
    doc.page_content = "Historical null spike in orders table"
    doc.metadata = {"relevance_score": 0.9}
    app.state.retriever.retrieve_similar_anomalies.return_value = [doc]

    resp = await client.post(
        "/api/v1/rag/query",
        json={"query": "null spike", "collection": "anomaly_patterns"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["content"] == "Historical null spike in orders table"


async def test_rag_query_unknown_collection_returns_400(api_client):
    client, _ = api_client
    resp = await client.post(
        "/api/v1/rag/query",
        json={"query": "test", "collection": "nonexistent_collection"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v1/rag/index
# ---------------------------------------------------------------------------


async def test_rag_index_returns_indexed_count(api_client):
    client, app = api_client
    app.state.indexer.index_documents.return_value = 3

    resp = await client.post(
        "/api/v1/rag/index",
        json={
            "collection": "anomaly_patterns",
            "documents": [
                {"id": "1", "content": "doc1", "metadata": {}},
                {"id": "2", "content": "doc2", "metadata": {}},
                {"id": "3", "content": "doc3", "metadata": {}},
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["indexed"] == 3
