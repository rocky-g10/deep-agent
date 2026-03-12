"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from deep_agent.api.session import SessionManager
from deep_agent.config import AppSettings, get_settings
from deep_agent.mcp.manager import MCPManager
from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator
from deep_agent.runtime.langgraph_adapter import LangGraphAdapter
from deep_agent.runtime.llm_router import LLMRouter
from deep_agent.runtime.protocol import RuntimeAdapter
from deep_agent.sandbox.subprocess_sandbox import PythonSubprocessSandbox
from deep_agent.skills.engine import SkillEngine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown lifecycle for the FastAPI app."""
    logger.info("Deep Agent API starting up")
    yield
    logger.info("Deep Agent API shutting down")
    # Cleanup MCP manager if attached
    mcp: MCPManager | None = getattr(app.state, "mcp_manager", None)
    if mcp is not None:
        await mcp.disconnect()


def create_app(
    settings: AppSettings | None = None,
    config_root: Path | None = None,
    runtime: RuntimeAdapter | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Override application settings (default: from environment).
        config_root: Root directory for agent/tenant configs (default: "config/").
        runtime: Override the runtime adapter (useful for testing with fake LLMs).
    """
    resolved_settings = settings or get_settings()
    resolved_config_root = config_root or Path("config/")
    resolved_runtime = runtime or LangGraphAdapter()

    app = FastAPI(title="Deep Agent", version="0.1.0", lifespan=_lifespan)

    # Initialize subsystems
    skill_engine = SkillEngine(
        skills_root=resolved_settings.skills_root,
        cache_ttl=resolved_settings.cache_ttl_seconds,
    )
    llm_router = LLMRouter(resolved_settings)
    sandbox = PythonSubprocessSandbox()
    session_manager = SessionManager()

    orchestrator = AgentOrchestrator(
        skill_engine=skill_engine,
        llm_router=llm_router,
        runtime=resolved_runtime,
        sandbox=sandbox,
    )

    # Store on app.state for access in route handlers
    app.state.orchestrator = orchestrator
    app.state.skill_engine = skill_engine
    app.state.session_manager = session_manager
    app.state.config_root = resolved_config_root
    app.state.settings = resolved_settings

    # Health endpoint
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Register WebSocket route
    from deep_agent.api.ws_chat import router as ws_router

    app.include_router(ws_router)

    return app
