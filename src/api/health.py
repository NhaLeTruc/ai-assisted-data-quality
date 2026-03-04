import asyncio

import httpx
from fastapi import APIRouter

from src.config import (
    CHROMA_HOST,
    CHROMA_PORT,
    MCP_CUSTOM_URL,
    MCP_GX_URL,
    MCP_MC_URL,
    cost_tracker,
)

router = APIRouter()


async def _probe(client: httpx.AsyncClient, name: str, url: str) -> tuple[str, str]:
    try:
        resp = await client.get(url, timeout=5.0)
        resp.raise_for_status()
        return name, "healthy"
    except Exception:
        return name, "degraded"


def _mcp_health_url(mcp_url: str) -> str:
    """Replace trailing /mcp path segment with /health."""
    if mcp_url.endswith("/mcp"):
        return mcp_url[: -len("/mcp")] + "/health"
    return mcp_url.rstrip("/") + "/health"


@router.get("/health")
async def health_check() -> dict:
    chroma_url = f"http://{CHROMA_HOST}:{CHROMA_PORT}/api/v1/heartbeat"
    gx_url = _mcp_health_url(MCP_GX_URL)
    mc_url = _mcp_health_url(MCP_MC_URL)
    custom_url = _mcp_health_url(MCP_CUSTOM_URL)

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            _probe(client, "chroma", chroma_url),
            _probe(client, "mcp_gx", gx_url),
            _probe(client, "mcp_mc", mc_url),
            _probe(client, "mcp_custom", custom_url),
            return_exceptions=False,
        )

    checks: dict[str, str] = dict(results)
    checks["app"] = "healthy"

    overall = "healthy" if all(v == "healthy" for v in checks.values()) else "degraded"

    return {
        "status": overall,
        "checks": checks,
        "cost_session": cost_tracker.report(),
    }
