"""Unit tests for orchestrator_node, terminal_node, route_from_orchestrator, safe_agent_node."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# terminal_node
# ---------------------------------------------------------------------------


async def test_terminal_node_sets_workflow_complete():
    from src.agents.orchestrator import terminal_node

    result = await terminal_node({})
    assert result == {"workflow_complete": True}


async def test_terminal_node_ignores_state_content():
    from src.agents.orchestrator import terminal_node

    result = await terminal_node({"some_key": "some_value", "workflow_complete": False})
    assert result["workflow_complete"] is True


# ---------------------------------------------------------------------------
# orchestrator_node
# ---------------------------------------------------------------------------


async def test_orchestrator_node_initial_phase_queries_business_context(
    minimal_state, mock_retriever
):
    from src.agents.orchestrator import orchestrator_node

    with patch("src.agents.orchestrator.get_retriever", return_value=mock_retriever):
        result = await orchestrator_node(minimal_state)

    mock_retriever.retrieve_business_context.assert_called_once_with("orders")
    assert result == {}


async def test_orchestrator_node_non_initial_phase_skips_retriever(minimal_state, mock_retriever):
    from src.agents.orchestrator import orchestrator_node

    state = {**minimal_state, "current_phase": "detection_complete"}
    with patch("src.agents.orchestrator.get_retriever", return_value=mock_retriever):
        result = await orchestrator_node(state)

    mock_retriever.retrieve_business_context.assert_not_called()
    assert result == {}


async def test_orchestrator_node_retriever_exception_is_swallowed(minimal_state):
    from src.agents.orchestrator import orchestrator_node

    broken = MagicMock()
    broken.retrieve_business_context.side_effect = RuntimeError("chroma down")
    with patch("src.agents.orchestrator.get_retriever", return_value=broken):
        result = await orchestrator_node(minimal_state)

    assert result == {}


# ---------------------------------------------------------------------------
# route_from_orchestrator
# ---------------------------------------------------------------------------


def test_route_initial_goes_to_validation():
    from src.agents.orchestrator import route_from_orchestrator

    assert route_from_orchestrator({"current_phase": "initial"}) == "validation"


def test_route_detection_complete_anomaly_detected_goes_to_diagnosis():
    from src.agents.orchestrator import route_from_orchestrator

    state = {
        "current_phase": "detection_complete",
        "detection_result": {"anomaly_detected": True},
    }
    assert route_from_orchestrator(state) == "diagnosis"


def test_route_detection_complete_no_anomaly_goes_to_complete():
    from src.agents.orchestrator import route_from_orchestrator

    state = {
        "current_phase": "detection_complete",
        "detection_result": {"anomaly_detected": False},
    }
    assert route_from_orchestrator(state) == "complete"


def test_route_detection_complete_missing_detection_result_goes_to_complete():
    from src.agents.orchestrator import route_from_orchestrator

    state = {"current_phase": "detection_complete", "detection_result": None}
    assert route_from_orchestrator(state) == "complete"


def test_route_diagnosis_complete_critical_goes_to_business_impact():
    from src.agents.orchestrator import route_from_orchestrator

    state = {"current_phase": "diagnosis_complete", "severity": "critical"}
    assert route_from_orchestrator(state) == "business_impact"


def test_route_diagnosis_complete_high_goes_to_business_impact():
    from src.agents.orchestrator import route_from_orchestrator

    state = {"current_phase": "diagnosis_complete", "severity": "high"}
    assert route_from_orchestrator(state) == "business_impact"


def test_route_diagnosis_complete_warning_goes_to_complete():
    from src.agents.orchestrator import route_from_orchestrator

    state = {"current_phase": "diagnosis_complete", "severity": "warning"}
    assert route_from_orchestrator(state) == "complete"


def test_route_diagnosis_complete_info_goes_to_complete():
    from src.agents.orchestrator import route_from_orchestrator

    state = {"current_phase": "diagnosis_complete", "severity": "info"}
    assert route_from_orchestrator(state) == "complete"


def test_route_remediation_complete_goes_to_complete():
    from src.agents.orchestrator import route_from_orchestrator

    state = {"current_phase": "remediation_complete"}
    assert route_from_orchestrator(state) == "complete"


def test_route_unknown_phase_goes_to_complete():
    from src.agents.orchestrator import route_from_orchestrator

    assert route_from_orchestrator({"current_phase": "unexpected"}) == "complete"


# ---------------------------------------------------------------------------
# safe_agent_node
# ---------------------------------------------------------------------------


async def test_safe_agent_node_records_latency(minimal_state):
    from src.agents.orchestrator import safe_agent_node

    async def _dummy(state):
        return {"foo": "bar"}

    wrapped = safe_agent_node(_dummy)
    result = await wrapped(minimal_state)

    assert "agent_latencies" in result
    assert "_dummy" in result["agent_latencies"]
    assert isinstance(result["agent_latencies"]["_dummy"], int)
    assert result["foo"] == "bar"


async def test_safe_agent_node_accumulates_latencies(minimal_state):
    from src.agents.orchestrator import safe_agent_node

    state_with_latencies = {**minimal_state, "agent_latencies": {"prior_node": 100}}

    async def _second(state):
        return {}

    wrapped = safe_agent_node(_second)
    result = await wrapped(state_with_latencies)

    assert "prior_node" in result["agent_latencies"]
    assert "_second" in result["agent_latencies"]


async def test_safe_agent_node_captures_exception_as_error(minimal_state):
    from src.agents.orchestrator import safe_agent_node

    async def _boom(state):
        raise ValueError("something went wrong")

    wrapped = safe_agent_node(_boom)
    result = await wrapped(minimal_state)

    assert "errors" in result
    assert len(result["errors"]) == 1
    assert "something went wrong" in result["errors"][0]


async def test_safe_agent_node_appends_to_existing_errors(minimal_state):
    from src.agents.orchestrator import safe_agent_node

    state_with_error = {**minimal_state, "errors": ["prior error"]}

    async def _boom(state):
        raise RuntimeError("new error")

    wrapped = safe_agent_node(_boom)
    result = await wrapped(state_with_error)

    assert len(result["errors"]) == 2
    assert "prior error" in result["errors"]


# ---------------------------------------------------------------------------
# call_mcp_tool session caching
# ---------------------------------------------------------------------------


async def test_call_mcp_tool_caches_session_id():
    """Second call to the same server reuses the cached session ID."""
    from src.agents.orchestrator import _mcp_sessions, call_mcp_tool

    _mcp_sessions.clear()

    init_resp = MagicMock()
    init_resp.status_code = 200
    init_resp.headers = {"mcp-session-id": "sess-abc123"}
    init_resp.raise_for_status = MagicMock()
    init_resp.text = '{"jsonrpc":"2.0","id":0,"result":{}}'

    tool_resp = MagicMock()
    tool_resp.status_code = 200
    tool_resp.raise_for_status = MagicMock()
    tool_resp.text = (
        'event: message\ndata: {"jsonrpc":"2.0","id":1,'
        '"result":{"content":[{"type":"text","text":"{}"}]}}\n'
    )

    with patch("src.agents.orchestrator.httpx.AsyncClient") as MockClient:
        mock_instance = MagicMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_instance.post = AsyncMock(side_effect=[init_resp, tool_resp, tool_resp])
        MockClient.return_value = mock_instance

        await call_mcp_tool("http://fake-mcp/mcp", "some_tool", {})
        assert _mcp_sessions.get("http://fake-mcp/mcp") == "sess-abc123"

    _mcp_sessions.clear()


@pytest.mark.parametrize(
    "sse_text,expected",
    [
        (
            'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"key":"val"}}\n',
            {"key": "val"},
        ),
        ('{"jsonrpc":"2.0","id":1,"result":{"key":"val"}}', {"key": "val"}),
    ],
)
def test_parse_sse(sse_text, expected):
    from src.agents.orchestrator import _parse_sse

    data = _parse_sse(sse_text)
    assert data.get("result") == expected
