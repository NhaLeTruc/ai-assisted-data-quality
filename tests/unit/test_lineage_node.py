"""Unit tests for lineage_node."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import CANNED_LINEAGE_JSON

_PATCHES = {
    "invoke": "src.agents.lineage.invoke_with_retry",
    "mcp": "src.agents.lineage.call_mcp_tool",
    "retriever": "src.agents.lineage.get_retriever",
    "memory": "src.agents.lineage.get_long_term_memory",
}


def _make_ai_msg(content: str):
    from langchain_core.messages import AIMessage

    return AIMessage(content=content)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_lineage_node_returns_lineage_result(state_after_detection, mock_retriever):
    from src.agents.lineage import lineage_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_LINEAGE_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await lineage_node(state_after_detection)

    assert "lineage_result" in result
    lr = result["lineage_result"]
    expected = json.loads(CANNED_LINEAGE_JSON)
    assert lr["impact_radius"] == expected["impact_radius"]
    assert lr["critical_path_breached"] == expected["critical_path_breached"]


async def test_lineage_node_sets_diagnosis_complete_phase(state_after_detection, mock_retriever):
    from src.agents.lineage import lineage_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_LINEAGE_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await lineage_node(state_after_detection)

    assert result["current_phase"] == "diagnosis_complete"


async def test_lineage_node_propagates_diagnosis_severity(mock_retriever):
    """severity in output comes from diagnosis_result, not detection state."""
    from src.agents.lineage import lineage_node

    state = {
        "trigger": {"table_name": "orders"},
        "investigation_id": "test-001",
        "diagnosis_result": {"severity": "high", "summary": "root cause found"},
        "severity": "critical",  # should be overridden by diagnosis
    }
    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_LINEAGE_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await lineage_node(state)

    assert result["severity"] == "high"


async def test_lineage_node_calls_rag_for_business_context(state_after_detection, mock_retriever):
    from src.agents.lineage import lineage_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_LINEAGE_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        await lineage_node(state_after_detection)

    mock_retriever.retrieve_business_context.assert_called_once_with("orders")


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


async def test_lineage_node_mcp_failure_still_calls_llm(state_after_detection, mock_retriever):
    from src.agents.lineage import lineage_node

    invoke_mock = AsyncMock(return_value=_make_ai_msg(CANNED_LINEAGE_JSON))
    with (
        patch(_PATCHES["invoke"], new=invoke_mock),
        patch(_PATCHES["mcp"], new=AsyncMock(side_effect=RuntimeError("custom MCP down"))),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await lineage_node(state_after_detection)

    invoke_mock.assert_called_once()
    assert "lineage_result" in result


async def test_lineage_node_llm_failure_uses_fallback(state_after_detection, mock_retriever):
    from src.agents.lineage import lineage_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(side_effect=RuntimeError("LLM down"))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await lineage_node(state_after_detection)

    assert "lineage_result" in result
    assert "fallback" in result["lineage_result"]["lineage_summary"]


async def test_lineage_node_retriever_failure_still_returns(state_after_detection):
    from src.agents.lineage import lineage_node

    broken = MagicMock()
    broken.retrieve_business_context.side_effect = RuntimeError("chroma down")
    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_LINEAGE_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=broken),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await lineage_node(state_after_detection)

    assert "lineage_result" in result
