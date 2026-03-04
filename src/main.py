import os

import aiosqlite
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# aiosqlite 0.20+ changed Connection to not inherit from Thread, removing is_alive().
# langgraph-checkpoint-sqlite 2.0.x still calls conn.is_alive() — patch it back.
if not hasattr(aiosqlite.Connection, "is_alive"):
    aiosqlite.Connection.is_alive = lambda self: self._thread.is_alive()

from src.api.health import router as health_router
from src.api.routes import router as api_router
from src.config import (
    CHROMA_HOST,
    CHROMA_PORT,
    DECISIONS_DB_PATH,
    MODELS,
    SQLITE_PATH,
)

app = FastAPI(title="Data Quality Intelligence API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(api_router)


@app.on_event("startup")
async def startup() -> None:
    from src.agents.workflow import build_workflow
    from src.memory.long_term import LongTermMemory
    from src.rag.indexer import DataQualityIndexer
    from src.rag.retriever import DataQualityRetriever

    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(DECISIONS_DB_PATH), exist_ok=True)

    # Enter the async SQLite checkpointer and keep it alive for the app lifetime
    _cm = AsyncSqliteSaver.from_conn_string(SQLITE_PATH)
    checkpointer = await _cm.__aenter__()
    app.state._checkpointer_cm = _cm

    app.state.workflow = build_workflow(checkpointer)
    app.state.indexer = DataQualityIndexer(CHROMA_HOST, int(CHROMA_PORT))
    app.state.retriever = DataQualityRetriever(CHROMA_HOST, int(CHROMA_PORT), MODELS["embeddings"])
    app.state.long_term_memory = LongTermMemory(DECISIONS_DB_PATH, app.state.retriever)


@app.on_event("shutdown")
async def shutdown() -> None:
    if hasattr(app.state, "_checkpointer_cm"):
        await app.state._checkpointer_cm.__aexit__(None, None, None)
