"""Unit tests for repair_node."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import CANNED_REMEDIATION_JSON

_PATCHES = {
    "invoke": "src.agents.repair.invoke_with_retry",
    "mcp": "src.agents.repair.call_mcp_tool",
    "retriever": "src.agents.repair.get_retriever",
    "memory": "src.agents.repair.get_long_term_memory",
}


def _make_ai_msg(content: str):
    from langchain_core.messages import AIMessage

    return AIMessage(content=content)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_repair_node_returns_plan_and_outcome(state_after_lineage, mock_retriever):
    from src.agents.repair import repair_node

    with (
        patch(
            _PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_REMEDIATION_JSON))
        ),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await repair_node(state_after_lineage)

    assert "remediation_plan" in result
    assert "remediation_result" in result
    plan = result["remediation_plan"]
    expected = json.loads(CANNED_REMEDIATION_JSON)
    assert plan["action_type"] == expected["action_type"]
    assert plan["dry_run_safe"] == expected["dry_run_safe"]


async def test_repair_node_sets_remediation_complete_phase(state_after_lineage, mock_retriever):
    from src.agents.repair import repair_node

    with (
        patch(
            _PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_REMEDIATION_JSON))
        ),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await repair_node(state_after_lineage)

    assert result["current_phase"] == "remediation_complete"
    assert result["workflow_complete"] is True


# ---------------------------------------------------------------------------
# Dry-run behaviour
# ---------------------------------------------------------------------------


async def test_repair_node_defaults_to_dry_run(state_after_lineage, mock_retriever):
    """With should_auto_remediate=False the apply_remediation call uses dry_run=True."""
    from src.agents.repair import repair_node

    mcp_mock = AsyncMock(return_value={})
    state = {**state_after_lineage, "should_auto_remediate": False}
    with (
        patch(
            _PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_REMEDIATION_JSON))
        ),
        patch(_PATCHES["mcp"], new=mcp_mock),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        await repair_node(state)

    # find the apply_remediation call
    apply_call = next((c for c in mcp_mock.call_args_list if c[0][1] == "apply_remediation"), None)
    assert apply_call is not None
    assert apply_call[0][2]["dry_run"] is True


async def test_repair_node_applies_when_auto_remediate_and_low_risk(
    state_after_lineage, mock_retriever
):
    """dry_run=False only when should_auto_remediate=True AND plan.risk_level='low'."""
    from src.agents.repair import repair_node

    low_risk_plan = json.loads(CANNED_REMEDIATION_JSON)
    low_risk_plan["risk_level"] = "low"

    mcp_mock = AsyncMock(return_value={})
    state = {**state_after_lineage, "should_auto_remediate": True}
    with (
        patch(
            _PATCHES["invoke"],
            new=AsyncMock(return_value=_make_ai_msg(json.dumps(low_risk_plan))),
        ),
        patch(_PATCHES["mcp"], new=mcp_mock),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        await repair_node(state)

    apply_call = next((c for c in mcp_mock.call_args_list if c[0][1] == "apply_remediation"), None)
    assert apply_call is not None
    assert apply_call[0][2]["dry_run"] is False


async def test_repair_node_stays_dry_run_when_risk_is_medium_even_if_auto_remediate(
    state_after_lineage, mock_retriever
):
    from src.agents.repair import repair_node

    medium_risk = json.loads(CANNED_REMEDIATION_JSON)
    medium_risk["risk_level"] = "medium"

    mcp_mock = AsyncMock(return_value={})
    state = {**state_after_lineage, "should_auto_remediate": True}
    with (
        patch(
            _PATCHES["invoke"],
            new=AsyncMock(return_value=_make_ai_msg(json.dumps(medium_risk))),
        ),
        patch(_PATCHES["mcp"], new=mcp_mock),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        await repair_node(state)

    apply_call = next((c for c in mcp_mock.call_args_list if c[0][1] == "apply_remediation"), None)
    assert apply_call is not None
    assert apply_call[0][2]["dry_run"] is True


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


async def test_repair_node_llm_failure_uses_fallback(state_after_lineage, mock_retriever):
    from src.agents.repair import repair_node

    with (
        patch(_PATCHES["invoke"], new=AsyncMock(side_effect=RuntimeError("LLM down"))),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await repair_node(state_after_lineage)

    assert "remediation_plan" in result
    assert result["remediation_plan"]["action_type"] == "manual_review"
    assert result["current_phase"] == "remediation_complete"


async def test_repair_node_mcp_failure_still_returns(state_after_lineage, mock_retriever):
    from src.agents.repair import repair_node

    with (
        patch(
            _PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_REMEDIATION_JSON))
        ),
        patch(_PATCHES["mcp"], new=AsyncMock(side_effect=RuntimeError("custom MCP down"))),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await repair_node(state_after_lineage)

    assert "remediation_plan" in result
    assert "remediation_result" in result


async def test_repair_node_retriever_failure_still_returns(state_after_lineage):
    from src.agents.repair import repair_node

    broken = MagicMock()
    broken.retrieve_playbook.side_effect = RuntimeError("chroma down")
    with (
        patch(
            _PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_REMEDIATION_JSON))
        ),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=broken),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await repair_node(state_after_lineage)

    assert "remediation_plan" in result


async def test_repair_node_outcome_contains_summary(state_after_lineage, mock_retriever):
    from src.agents.repair import repair_node

    with (
        patch(
            _PATCHES["invoke"], new=AsyncMock(return_value=_make_ai_msg(CANNED_REMEDIATION_JSON))
        ),
        patch(_PATCHES["mcp"], new=AsyncMock(return_value={})),
        patch(_PATCHES["retriever"], return_value=mock_retriever),
        patch(_PATCHES["memory"], return_value=MagicMock()),
    ):
        result = await repair_node(state_after_lineage)

    assert "outcome_summary" in result["remediation_result"]
