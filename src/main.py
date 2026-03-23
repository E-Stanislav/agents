from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.config import settings
from src.observability.tracing import setup_tracing

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Multi-Agent Project Generator",
    description="Generate complete projects from Markdown requirements using AI agents",
    version="0.1.0",
)

# Setup Langfuse tracing
setup_tracing()

# API routes
from src.api.routes import router as api_router
from src.api.websocket import ws_router

app.include_router(api_router)
app.include_router(ws_router)

# Serve static web UI
app.mount("/static", StaticFiles(directory="src/web"), name="static")


@app.get("/")
async def root():
    return FileResponse("src/web/index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.on_event("startup")
async def startup():
    logger.info("Starting Multi-Agent Project Generator")
    # Validate LLM config on startup
    try:
        from src.llm import registry
        registry._load_config()
        logger.info("LLM config validated successfully")
    except Exception as e:
        logger.error("LLM config validation failed: %s", e)
