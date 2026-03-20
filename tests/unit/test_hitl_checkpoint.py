"""Unit tests for HITL checkpoint store."""

from __future__ import annotations

from typing import cast

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from deep_agent.hitl.checkpoint import Checkpoint, CheckpointStore, InMemoryCheckpointStore
from deep_agent.models.hitl import FieldSpec, HumanInteractionRequest


@pytest.mark.asyncio
async def test_checkpoint_store_save_load_roundtrip() -> None:
    store = InMemoryCheckpointStore()
    checkpoint = Checkpoint(
        run_id="run-1",
        session_id="session-1",
        conversation_history=[{"type": "human", "data": {"content": "hello"}}],
        pending_interaction=HumanInteractionRequest(kind="clarify", question="Which portfolio?"),
        skill_id="risk/portfolio-var",
        tool_call_id="call-1",
        env_snapshot={"A": "1"},
        scripts_dirs=["/tmp/scripts"],
        created_at=123.0,
    )

    await store.save(checkpoint)
    loaded = await store.load("run-1")

    assert loaded == checkpoint


@pytest.mark.asyncio
async def test_checkpoint_store_delete_removes_checkpoint() -> None:
    store = InMemoryCheckpointStore()
    checkpoint = Checkpoint(
        run_id="run-2",
        session_id="session-2",
        conversation_history=[],
        pending_interaction=HumanInteractionRequest(kind="approve", action_description="Execute?"),
        created_at=1.0,
    )

    await store.save(checkpoint)
    await store.delete("run-2")

    assert await store.load("run-2") is None


def test_checkpoint_model_dump_is_json_serializable_shape() -> None:
    checkpoint = Checkpoint(
        run_id="run-3",
        session_id="session-3",
        conversation_history=[],
        pending_interaction=HumanInteractionRequest(
            kind="collect", fields=[FieldSpec(name="ticker", type="string")]
        ),
        created_at=2.0,
    )
    dumped = checkpoint.model_dump()

    assert dumped["run_id"] == "run-3"
    assert dumped["pending_interaction"]["kind"] == "collect"


def test_checkpoint_message_helpers_roundtrip() -> None:
    messages: list[BaseMessage] = [HumanMessage(content="hello"), AIMessage(content="hi there")]
    checkpoint = Checkpoint.from_messages(
        run_id="run-m",
        session_id="session-m",
        messages=messages,
        pending_interaction=HumanInteractionRequest(kind="clarify", question="Which?"),
        created_at=10.0,
    )

    rehydrated = checkpoint.to_messages()

    assert len(rehydrated) == 2
    assert cast(HumanMessage, rehydrated[0]).content == "hello"
    assert cast(AIMessage, rehydrated[1]).content == "hi there"


def test_in_memory_checkpoint_store_implements_protocol() -> None:
    store: CheckpointStore = InMemoryCheckpointStore()
    assert isinstance(store, InMemoryCheckpointStore)
