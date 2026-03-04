"""Unit tests for business_impact_node."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import CANNED_BUSINESS_IMPACT_JSON

_PATCHES = {
    "invoke": "src.agents.business_impact.invoke_with_retry",
    "mcp": "src.agents.business_impact.call_mcp_tool",
    "retriever": "src.agents.business_impact.get_retriever",
    "memory": "src.agents.business_impact.get_long_term_memory",
}


def _make_ai_msg(content: str):
    from langchain_core.messages import AIMessage

    return AIMessage(content=content)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_business_impact_node_returns_business_impact(state_after_lineage, mock_retriever):
    from src.agents.business_impact import business_impact_node

    with (
        patch(
            _PATCHES["invoke"],
            new=AsyncMock(return_value=_make_ai_msg(CANNED_BUSINESS_IMPACT_JSON)),
        ),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await business_impact_node(state_after_lineage)

    assert "business_impact" in result
    bi = result["business_impact"]
    expected = json.loads(CANNED_BUSINESS_IMPACT_JSON)
    assert bi["escalation_required"] == expected["escalation_required"]
    assert bi["business_criticality"] == expected["business_criticality"]


async def test_business_impact_node_calls_rag_for_business_context(
    state_after_lineage, mock_retriever
):
    from src.agents.business_impact import business_impact_node

    with (
        patch(
            _PATCHES["invoke"],
            new=AsyncMock(return_value=_make_ai_msg(CANNED_BUSINESS_IMPACT_JSON)),
        ),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        await business_impact_node(state_after_lineage)

    mock_retriever.retrieve_business_context.assert_called_once_with("orders")


async def test_business_impact_node_calls_assess_business_impact_mcp(
    state_after_lineage, mock_retriever
):
    from src.agents.business_impact import business_impact_node

    mcp_mock = AsyncMock(return_value={})
    with (
        patch(
            _PATCHES["invoke"],
            new=AsyncMock(return_value=_make_ai_msg(CANNED_BUSINESS_IMPACT_JSON)),
        ),
        patch(_PATCHES["mcp"], new=mcp_mock),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        await business_impact_node(state_after_lineage)

    tool_names = [call[0][1] for call in mcp_mock.call_args_list]
    assert "assess_business_impact" in tool_names


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


async def test_business_impact_node_mcp_failure_still_calls_llm(
    state_after_lineage, mock_retriever
):
    from src.agents.business_impact import business_impact_node

    invoke_mock = AsyncMock(return_value=_make_ai_msg(CANNED_BUSINESS_IMPACT_JSON))
    with (
        patch(_PATCHES["invoke"], new=invoke_mock),
        patch(_PATCHES["mcp"], new=AsyncMock(side_effect=RuntimeError("custom MCP down"))),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await business_impact_node(state_after_lineage)

    invoke_mock.assert_called_once()
    assert "business_impact" in result


async def test_business_impact_node_llm_failure_uses_fallback(state_after_lineage, mock_retriever):
    from src.agents.business_impact import business_impact_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(side_effect=RuntimeError("LLM down"))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await business_impact_node(state_after_lineage)

    assert "business_impact" in result
    # fallback uses severity as criticality
    assert result["business_impact"]["business_criticality"] == state_after_lineage["severity"]


async def test_business_impact_node_fallback_escalates_for_critical(
    state_after_lineage, mock_retriever
):
    from src.agents.business_impact import business_impact_node

    # state_after_lineage has severity="critical"
    with (
        patch(_PATCHES["invoke"], new=AsyncMock(side_effect=RuntimeError("LLM down"))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await business_impact_node(state_after_lineage)

    assert result["business_impact"]["escalation_required"] is True


async def test_business_impact_node_retriever_failure_still_returns(state_after_lineage):
    from src.agents.business_impact import business_impact_node

    broken = MagicMock()
    broken.retrieve_business_context.side_effect = RuntimeError("chroma down")
    with (
        patch(
            _PATCHES["invoke"],
            new=AsyncMock(return_value=_make_ai_msg(CANNED_BUSINESS_IMPACT_JSON)),
        ),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=broken),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await business_impact_node(state_after_lineage)

    assert "business_impact" in result


async def test_business_impact_node_memory_failure_still_returns(
    state_after_lineage, mock_retriever
):
    from src.agents.business_impact import business_impact_node

    broken_mem = MagicMock()
    broken_mem.record_decision.side_effect = RuntimeError("db down")
    with (
        patch(
            _PATCHES["invoke"],
            new=AsyncMock(return_value=_make_ai_msg(CANNED_BUSINESS_IMPACT_JSON)),
        ),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=broken_mem),
    ):
        result = await business_impact_node(state_after_lineage)

    assert "business_impact" in result
