import logging
import os

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_community.embeddings import HuggingFaceEmbeddings
from tenacity import retry, stop_after_attempt, wait_exponential

load_dotenv()

# ---------------------------------------------------------------------------
# Environment variable constants
# ---------------------------------------------------------------------------

CHROMA_HOST: str = os.getenv("CHROMA_HOST", "chroma")
CHROMA_PORT: int = int(os.getenv("CHROMA_PORT", "8000"))
MCP_GX_URL: str = os.getenv("MCP_GX_URL", "http://mcp-gx:8081/mcp")
MCP_MC_URL: str = os.getenv("MCP_MC_URL", "http://mcp-mc:8082/mcp")
MCP_CUSTOM_URL: str = os.getenv("MCP_CUSTOM_URL", "http://mcp-custom:8083/mcp")
SQLITE_PATH: str = os.getenv("SQLITE_PATH", "/data/sqlite/checkpoints.db")
DECISIONS_DB_PATH: str = os.getenv("DECISIONS_DB_PATH", "/data/sqlite/decisions.db")
CHROMA_DATA_PATH: str = os.getenv("CHROMA_DATA_PATH", "/data/chroma")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
COST_TRACKING_ENABLED: bool = os.getenv("COST_TRACKING_ENABLED", "true").lower() == "true"
COST_ALERT_THRESHOLD: float = float(os.getenv("COST_ALERT_THRESHOLD", "5.00"))
MAX_REQUESTS_PER_MINUTE: int = int(os.getenv("MAX_REQUESTS_PER_MINUTE", "60"))
MEMORY_RETENTION_DAYS: int = int(os.getenv("MEMORY_RETENTION_DAYS", "90"))

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))

# ---------------------------------------------------------------------------
# LLM model configuration
# ---------------------------------------------------------------------------

MODELS: dict = {
    "tier1_reasoning": ChatAnthropic(
        model="claude-opus-4-6",
        temperature=0.1,
        max_tokens=4096,
        timeout=60,
    ),
    "tier2_structured": ChatAnthropic(
        model="claude-sonnet-4-6",
        temperature=0.0,
        max_tokens=2048,
        timeout=30,
    ),
    "tier3_simple": ChatAnthropic(
        model="claude-haiku-4-5-20251001",
        temperature=0.0,
        max_tokens=1024,
        timeout=15,
    ),
    "embeddings": HuggingFaceEmbeddings(
        model_name="BAAI/bge-base-en-v1.5",
    ),
}

# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {"input": 0.015, "output": 0.075},
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
    "claude-haiku-4-5-20251001": {"input": 0.0008, "output": 0.004},
}


class CostTracker:
    def __init__(self) -> None:
        self._session_cost: float = 0.0
        self._investigation_costs: dict[str, float] = {}

    def record(
        self,
        model: str,
        investigation_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Record token usage and return cost for this call."""
        if model not in PRICING:
            return 0.0
        price = PRICING[model]
        cost = (input_tokens / 1000) * price["input"] + (output_tokens / 1000) * price["output"]
        self._session_cost += cost
        self._investigation_costs[investigation_id] = (
            self._investigation_costs.get(investigation_id, 0.0) + cost
        )
        if COST_TRACKING_ENABLED and self._session_cost > COST_ALERT_THRESHOLD:
            logging.getLogger(__name__).warning(
                "Session cost $%.4f exceeds alert threshold $%.2f",
                self._session_cost,
                COST_ALERT_THRESHOLD,
            )
        return cost

    def report(self) -> dict:
        """Return session cost summary."""
        count = len(self._investigation_costs)
        avg = self._session_cost / count if count > 0 else 0.0
        return {
            "session_total_usd": self._session_cost,
            "investigation_count": count,
            "avg_per_investigation_usd": avg,
        }


# ---------------------------------------------------------------------------
# Retry-wrapped LLM invocation
# ---------------------------------------------------------------------------


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    reraise=True,
)
async def invoke_with_retry(model, prompt):
    """Invoke an LLM with exponential-backoff retry on transient errors."""
    return await model.ainvoke(prompt)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

cost_tracker = CostTracker()
