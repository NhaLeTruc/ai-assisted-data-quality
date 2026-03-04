"""Unit tests for validation_node."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import CANNED_VALIDATION_JSON

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATCHES = {
    "invoke": "src.agents.validation.invoke_with_retry",
    "mcp": "src.agents.validation.call_mcp_tool",
    "retriever": "src.agents.validation.get_retriever",
    "memory": "src.agents.validation.get_long_term_memory",
}


def _make_ai_msg(content: str):
    from langchain_core.messages import AIMessage

    return AIMessage(content=content)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_validation_node_returns_validation_result(minimal_state, mock_retriever):
    from src.agents.validation import validation_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_VALIDATION_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await validation_node(minimal_state)

    assert "validation_result" in result
    vr = result["validation_result"]
    assert vr["passed"] is False
    assert vr["failure_count"] == 1
    assert "summary" in vr


async def test_validation_node_calls_three_mcp_tools(minimal_state, mock_retriever):
    from src.agents.validation import validation_node

    mcp_mock = AsyncMock(return_value={})
    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_VALIDATION_JSON))),
        patch(_PATCHES["mcp"], new=mcp_mock),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        await validation_node(minimal_state)

    # create_expectation_suite, run_checkpoint, get_validation_results
    assert mcp_mock.call_count == 3


async def test_validation_node_uses_table_name_for_rag(minimal_state, mock_retriever):
    from src.agents.validation import validation_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_VALIDATION_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        await validation_node(minimal_state)

    mock_retriever.retrieve_dq_rules.assert_called_once_with("orders")


# ---------------------------------------------------------------------------
# Fallback (LLM failure)
# ---------------------------------------------------------------------------


async def test_validation_node_llm_failure_returns_fallback(minimal_state, mock_retriever):
    from src.agents.validation import validation_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(side_effect=RuntimeError("LLM down"))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await validation_node(minimal_state)

    assert "validation_result" in result
    assert "fallback" in result["validation_result"]["summary"]


# ---------------------------------------------------------------------------
# Resilience to subsidiary failures
# ---------------------------------------------------------------------------


async def test_validation_node_mcp_failure_still_calls_llm(minimal_state, mock_retriever):
    from src.agents.validation import validation_node

    invoke_mock = AsyncMock(return_value=_make_ai_msg(CANNED_VALIDATION_JSON))
    with (
        patch(_PATCHES["invoke"], new=invoke_mock),
        patch(_PATCHES["mcp"], new=AsyncMock(side_effect=RuntimeError("MCP down"))),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await validation_node(minimal_state)

    invoke_mock.assert_called_once()
    assert "validation_result" in result


async def test_validation_node_retriever_failure_still_calls_llm(minimal_state):
    from src.agents.validation import validation_node

    broken_retriever = MagicMock()
    broken_retriever.retrieve_dq_rules.side_effect = RuntimeError("chroma down")
    invoke_mock = AsyncMock(return_value=_make_ai_msg(CANNED_VALIDATION_JSON))
    with (
        patch(_PATCHES["invoke"], new=invoke_mock),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=broken_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await validation_node(minimal_state)

    invoke_mock.assert_called_once()
    assert "validation_result" in result


async def test_validation_node_memory_failure_still_returns_result(minimal_state, mock_retriever):
    from src.agents.validation import validation_node

    broken_memory = MagicMock()
    broken_memory.record_decision.side_effect = RuntimeError("db down")
    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_VALIDATION_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=broken_memory),
    ):
        result = await validation_node(minimal_state)

    assert "validation_result" in result


# ---------------------------------------------------------------------------
# State key assertions
# ---------------------------------------------------------------------------


async def test_validation_node_result_matches_pydantic_schema(minimal_state, mock_retriever):
    from src.agents.validation import validation_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_VALIDATION_JSON))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await validation_node(minimal_state)

    vr = result["validation_result"]
    expected = json.loads(CANNED_VALIDATION_JSON)
    assert vr["passed"] == expected["passed"]
    assert vr["failed_expectations"] == expected["failed_expectations"]
    assert vr["total_expectations"] == expected["total_expectations"]
