import os

from langgraph.checkpoint.sqlite import SqliteSaver


def create_checkpointer(sqlite_path: str) -> SqliteSaver:
    """Create a SqliteSaver checkpointer, ensuring the parent directory exists."""
    os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
    return SqliteSaver.from_conn_string(sqlite_path)


def update_shared_context(state: dict, agent_name: str, findings_summary: str) -> dict:
    """Append an agent's findings summary to the shared context dict."""
    return {
        "shared_context": {
            **state.get("shared_context", {}),
            agent_name: findings_summary,
        }
    }


def record_agent_latency(state: dict, agent_name: str, elapsed_ms: int) -> dict:
    """Record elapsed milliseconds for a named agent into agent_latencies."""
    return {
        "agent_latencies": {
            **state.get("agent_latencies", {}),
            agent_name: elapsed_ms,
        }
    }
