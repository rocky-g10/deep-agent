"""REST endpoints for run-level operations."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from deep_agent.api.schemas import RunRespondRequest, RunRespondResult
from deep_agent.api.session import SessionManager
from deep_agent.orchestrator.agent_orchestrator import AgentOrchestrator

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


@router.post("/{run_id}/respond", response_model=RunRespondResult)
async def respond_to_run(
    run_id: str,
    body: RunRespondRequest,
    request: Request,
) -> RunRespondResult:
    """Submit a human response to resume a suspended run."""
    orchestrator: AgentOrchestrator = request.app.state.orchestrator
    session_manager: SessionManager = request.app.state.session_manager

    run_info = orchestrator.run_state_manager.get_run(run_id)
    if run_info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown run_id: {run_id}",
        )
    if run_info.state.value != "suspended":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run {run_id} is not suspended",
        )

    session = session_manager.get(run_info.session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session for run {run_id} not found",
        )

    async for event in orchestrator.resume_run(run_id, body.response):
        await session.resume_queue.put(event)

    return RunRespondResult(run_id=run_id, status="resumed")
