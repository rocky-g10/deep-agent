"""WebSocket chat endpoint handler."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from deep_agent.api.config_loader import build_tenant_context, load_agent_bindings
from deep_agent.api.schemas import SessionStartedMessage, UserMessage
from deep_agent.api.session import SessionManager
from deep_agent.models.context import TenantContext
from deep_agent.models.events import ErrorEvent
from deep_agent.models.skills import AgentSkillBindings
from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator
from deep_agent.skills.engine import SkillEngine

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/chat")
async def ws_chat(
    websocket: WebSocket,
    tenant_id: str = Query(default="default"),
    agent_id: str = Query(default=""),
) -> None:
    """Handle a WebSocket chat connection.

    Query params:
        tenant_id: Tenant identifier (default: "default").
        agent_id: Agent identifier for skill bindings (default: "" → bind all skills).
    """
    await websocket.accept()

    orchestrator: AgentOrchestrator = websocket.app.state.orchestrator
    session_manager: SessionManager = websocket.app.state.session_manager
    skill_engine: SkillEngine = websocket.app.state.skill_engine
    config_root: Path = websocket.app.state.config_root

    # Resolve tenant context
    try:
        tenant = build_tenant_context(
            tenant_id=tenant_id,
            config_root=config_root,
        )
    except Exception as exc:
        logger.warning("Failed to build tenant context for '%s': %s", tenant_id, exc)
        tenant = TenantContext.default()

    # Resolve agent skill bindings
    bindings = _resolve_bindings(agent_id, config_root, skill_engine)

    # Create session
    session = session_manager.create(tenant=tenant, bindings=bindings)

    # Send session_started
    started = SessionStartedMessage(session_id=session.session_id)
    await websocket.send_text(started.model_dump_json())

    try:
        while True:
            raw = await websocket.receive_text()
            await _handle_client_message(
                raw=raw,
                websocket=websocket,
                orchestrator=orchestrator,
                session_manager=session_manager,
                session_id=session.session_id,
            )
    except WebSocketDisconnect:
        logger.debug("Client disconnected (session %s)", session.session_id)
    except Exception as exc:
        logger.exception("WebSocket error (session %s)", session.session_id)
        try:
            error = ErrorEvent(code="WS_ERROR", message=str(exc))
            await websocket.send_text(error.model_dump_json())
        except Exception:
            pass
    finally:
        session_manager.delete(session.session_id)


async def _handle_client_message(
    raw: str,
    websocket: WebSocket,
    orchestrator: AgentOrchestrator,
    session_manager: SessionManager,
    session_id: str,
) -> None:
    """Parse and process a single client message."""
    # Parse JSON
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        error = ErrorEvent(code="INVALID_JSON", message=f"Malformed JSON: {exc}")
        await websocket.send_text(error.model_dump_json())
        return

    # Validate message type
    msg_type = data.get("type")
    if msg_type != "user_message":
        error = ErrorEvent(code="UNKNOWN_MESSAGE_TYPE", message=f"Unknown type: {msg_type}")
        await websocket.send_text(error.model_dump_json())
        return

    # Validate schema
    try:
        user_msg = UserMessage.model_validate(data)
    except ValidationError as exc:
        error = ErrorEvent(code="VALIDATION_ERROR", message=str(exc))
        await websocket.send_text(error.model_dump_json())
        return

    # Look up session
    effective_session_id = user_msg.session_id or session_id
    session = session_manager.get(effective_session_id)
    if session is None:
        error = ErrorEvent(
            code="SESSION_NOT_FOUND",
            message=f"Unknown session: {effective_session_id}",
        )
        await websocket.send_text(error.model_dump_json())
        return

    # Add user message to history
    session.messages.append(HumanMessage(content=user_msg.content))

    # Stream orchestrator events
    summary_parts: list[str] = []
    async for event in orchestrator.handle_message(
        message=user_msg.content,
        context=session.tenant,
        skill_bindings=session.bindings,
        history=session.messages[:-1] if len(session.messages) > 1 else None,
    ):
        await websocket.send_text(event.model_dump_json())
        # Capture AI content for history
        if event.type == "agent_chunk":
            summary_parts.append(event.content)

    # Add AI response to history
    if summary_parts:
        session.messages.append(AIMessage(content="".join(summary_parts)))


def _resolve_bindings(
    agent_id: str,
    config_root: Path,
    skill_engine: SkillEngine,
) -> AgentSkillBindings:
    """Resolve agent skill bindings from config or default to all skills."""
    if agent_id:
        try:
            bindings = load_agent_bindings(agent_id, config_root)
            if bindings is not None:
                return bindings
        except Exception as exc:
            logger.warning("Failed to load agent bindings for '%s': %s", agent_id, exc)

    # Default: bind all discovered skills
    all_skills = skill_engine._scan_filesystem()
    return AgentSkillBindings(
        agent_id=agent_id or "default",
        bound_skill_ids=tuple(all_skills.keys()),
    )
