"""Unit tests for diagnosis_node."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import CANNED_DIAGNOSIS_JSON

_PATCHES = {
    "invoke": "src.agents.diagnosis.invoke_with_retry",
    "mcp": "src.agents.diagnosis.call_mcp_tool",
    "retriever": "src.agents.diagnosis.get_retriever",
    "memory": "src.agents.diagnosis.get_long_term_memory",
}


def _make_ai_msg(content: str):
    from langchain_core.messages import AIMessage

    return AIMessage(content=content)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_diagnosis_node_returns_diagnosis_result(state_after_detection, mock_retriever):
    from src.agents.diagnosis import diagnosis_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_DIAGNOSIS_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value=[])),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await diagnosis_node(state_after_detection)

    assert "diagnosis_result" in result
    dr = result["diagnosis_result"]
    expected = json.loads(CANNED_DIAGNOSIS_JSON)
    assert dr["severity"] == expected["severity"]
    assert dr["root_cause_category"] == expected["root_cause_category"]


async def test_diagnosis_node_queries_rag_for_similar_and_playbook(
    state_after_detection, mock_retriever
):
    from src.agents.diagnosis import diagnosis_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_DIAGNOSIS_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value=[])),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        await diagnosis_node(state_after_detection)

    mock_retriever.retrieve_similar_anomalies.assert_called_once()
    mock_retriever.retrieve_playbook.assert_called_once()


async def test_diagnosis_node_uses_48h_lookback(state_after_detection, mock_retriever):
    from src.agents.diagnosis import diagnosis_node

    mcp_mock = AsyncMock(return_value=[])
    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_DIAGNOSIS_JSON))),
        patch(_PATCHES["mcp"], new=mcp_mock),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        await diagnosis_node(state_after_detection)

    call_args = mcp_mock.call_args
    assert call_args[0][2].get("hours_lookback") == 48


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


async def test_diagnosis_node_mcp_failure_still_calls_llm(state_after_detection, mock_retriever):
    from src.agents.diagnosis import diagnosis_node

    invoke_mock = AsyncMock(return_value=_make_ai_msg(CANNED_DIAGNOSIS_JSON))
    with (
        patch(_PATCHES["invoke"], new=invoke_mock),
        patch(_PATCHES["mcp"], new=AsyncMock(side_effect=RuntimeError("MC down"))),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await diagnosis_node(state_after_detection)

    invoke_mock.assert_called_once()
    assert "diagnosis_result" in result


async def test_diagnosis_node_llm_failure_uses_fallback(state_after_detection, mock_retriever):
    from src.agents.diagnosis import diagnosis_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(side_effect=RuntimeError("LLM down"))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value=[])),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await diagnosis_node(state_after_detection)

    assert "diagnosis_result" in result
    assert "fallback" in result["diagnosis_result"]["summary"]


async def test_diagnosis_node_retriever_failure_still_returns(state_after_detection):
    from src.agents.diagnosis import diagnosis_node

    broken = MagicMock()
    broken.retrieve_similar_anomalies.side_effect = RuntimeError("chroma down")
    broken.retrieve_playbook.side_effect = RuntimeError("chroma down")
    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_DIAGNOSIS_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value=[])),
        patch(_PATCHES["retriever"], return_value=broken),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await diagnosis_node(state_after_detection)

    assert "diagnosis_result" in result


async def test_diagnosis_node_memory_failure_still_returns(state_after_detection, mock_retriever):
    from src.agents.diagnosis import diagnosis_node

    broken_mem = MagicMock()
    broken_mem.record_decision.side_effect = RuntimeError("db down")
    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_DIAGNOSIS_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value=[])),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=broken_mem),
    ):
        result = await diagnosis_node(state_after_detection)

    assert "diagnosis_result" in result
