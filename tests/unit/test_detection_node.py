"""Unit tests for detection_node."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import CANNED_DETECTION_JSON

_PATCHES = {
    "invoke": "src.agents.detection.invoke_with_retry",
    "mcp": "src.agents.detection.call_mcp_tool",
    "retriever": "src.agents.detection.get_retriever",
    "memory": "src.agents.detection.get_long_term_memory",
}


def _make_ai_msg(content: str):
    from langchain_core.messages import AIMessage

    return AIMessage(content=content)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_detection_node_returns_detection_result(minimal_state, mock_retriever):
    from src.agents.detection import detection_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_DETECTION_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await detection_node(minimal_state)

    assert "detection_result" in result
    assert "current_phase" in result
    assert result["current_phase"] == "detection_complete"


async def test_detection_node_sets_severity_for_anomaly(minimal_state, mock_retriever):
    from src.agents.detection import detection_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_DETECTION_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await detection_node(minimal_state)

    # CANNED has anomaly_type="null_spike" → severity="critical"
    assert result["severity"] == "critical"


async def test_detection_node_no_anomaly_severity_is_none(minimal_state, mock_retriever):
    from src.agents.detection import detection_node

    no_anomaly = json.loads(CANNED_DETECTION_JSON)
    no_anomaly["anomaly_detected"] = False
    no_anomaly["anomaly_type"] = None

    with (
        patch(
            _PATCHES["invoke"],
            new=AsyncMock(return_value=_make_ai_msg(json.dumps(no_anomaly))),
        ),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await detection_node(minimal_state)

    assert result["severity"] is None


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------


async def _run_with_anomaly_type(minimal_state, mock_retriever, anomaly_type: str) -> dict:
    from src.agents.detection import detection_node

    payload = json.loads(CANNED_DETECTION_JSON)
    payload["anomaly_type"] = anomaly_type
    payload["anomaly_detected"] = True
    with (
        patch(
            _PATCHES["invoke"],
            new=AsyncMock(return_value=_make_ai_msg(json.dumps(payload))),
        ),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        return await detection_node(minimal_state)


async def test_severity_null_spike_is_critical(minimal_state, mock_retriever):
    result = await _run_with_anomaly_type(minimal_state, mock_retriever, "null_spike")
    assert result["severity"] == "critical"


async def test_severity_volume_drop_is_high(minimal_state, mock_retriever):
    result = await _run_with_anomaly_type(minimal_state, mock_retriever, "volume_drop")
    assert result["severity"] == "high"


async def test_severity_freshness_lag_is_warning(minimal_state, mock_retriever):
    result = await _run_with_anomaly_type(minimal_state, mock_retriever, "freshness_lag")
    assert result["severity"] == "warning"


async def test_severity_manual_is_info(minimal_state, mock_retriever):
    result = await _run_with_anomaly_type(minimal_state, mock_retriever, "manual")
    assert result["severity"] == "info"


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


async def test_detection_node_mcp_failure_still_calls_llm(minimal_state, mock_retriever):
    from src.agents.detection import detection_node

    invoke_mock = AsyncMock(return_value=_make_ai_msg(CANNED_DETECTION_JSON))
    with (
        patch(_PATCHES["invoke"], new=invoke_mock),
        patch(_PATCHES["mcp"], new=AsyncMock(side_effect=RuntimeError("MC down"))),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await detection_node(minimal_state)

    invoke_mock.assert_called_once()
    assert "detection_result" in result


async def test_detection_node_llm_failure_uses_fallback(minimal_state, mock_retriever):
    from src.agents.detection import detection_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(side_effect=RuntimeError("LLM down"))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await detection_node(minimal_state)

    assert "detection_result" in result
    assert "fallback" in result["detection_result"]["summary"]


async def test_detection_node_retriever_failure_still_returns(minimal_state):
    from src.agents.detection import detection_node

    broken = MagicMock()
    broken.retrieve_similar_anomalies.side_effect = RuntimeError("chroma down")
    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_DETECTION_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=broken),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await detection_node(minimal_state)

    assert "detection_result" in result


async def test_detection_node_memory_failure_still_returns(minimal_state, mock_retriever):
    from src.agents.detection import detection_node

    broken_mem = MagicMock()
    broken_mem.record_decision.side_effect = RuntimeError("db down")
    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_DETECTION_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=broken_mem),
    ):
        result = await detection_node(minimal_state)

    assert "detection_result" in result
