from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AgentCheckpoint, AgentEvent, AgentRun


async def persist_checkpoint(
    session: AsyncSession,
    *,
    run_id: str,
    key: str,
    state: dict[str, Any],
) -> None:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise LookupError("Agent run not found while saving checkpoint")
    run.state_snapshot = state
    result = await session.execute(
        select(AgentCheckpoint).where(
            AgentCheckpoint.agent_run_id == run_id,
            AgentCheckpoint.checkpoint_key == key,
        )
    )
    checkpoint = result.scalar_one_or_none()
    if checkpoint is None:
        checkpoint = AgentCheckpoint(
            agent_run_id=run_id,
            checkpoint_key=key,
            adapter="mysql-json",
            state_data=state,
        )
        session.add(checkpoint)
    else:
        checkpoint.state_data = state
        checkpoint.created_at = datetime.now(timezone.utc)
    await session.commit()


async def emit_event(
    session: AsyncSession,
    *,
    run_id: str,
    agent_name: str,
    event_type: str,
    payload: dict[str, Any],
) -> AgentEvent:
    updated = await session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id)
        .values(last_sequence=AgentRun.last_sequence + 1)
    )
    if updated.rowcount != 1:
        raise LookupError("Agent run not found while emitting event")
    sequence = await session.scalar(
        select(AgentRun.last_sequence).where(AgentRun.id == run_id)
    )
    if sequence is None:
        raise LookupError("Agent run not found while emitting event")
    event = AgentEvent(
        agent_run_id=run_id,
        sequence=sequence,
        agent_name=agent_name,
        event_type=event_type,
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )
    session.add(event)
    await session.commit()
    return event


async def emit_assistant_delta(
    session: AsyncSession,
    *,
    run_id: str,
    text: str,
) -> None:
    await emit_event(
        session,
        run_id=run_id,
        agent_name="aether_core",
        event_type="assistant.delta",
        payload={"text": text},
    )
