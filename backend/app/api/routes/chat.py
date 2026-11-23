import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import WorkflowState, run_workflow
from app.ai.model_router import resolve_model
from app.ai.openrouter import OpenRouterClient, OpenRouterError
from app.core.security import get_current_user
from app.database import get_db
from app.database.models import (
    AgentCheckpoint,
    AgentEvent,
    AgentRun,
    Approval,
    Conversation,
    Message,
    ToolExecution,
    User,
)
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationRead,
    MessageRead,
    RunRedirectRequest,
)
from app.services.memory import retrieve_relevant_memories
from app.services.workflow import emit_assistant_delta, emit_event

router = APIRouter(prefix="/api/v1", tags=["chat"])
openrouter = OpenRouterClient()
MAX_CONTEXT_MESSAGES = 20


@router.post("/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Conversation:
    conversation = Conversation(
        id=str(uuid4()),
        user_id=user.id,
        title=payload.title,
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


def provider_http_status(error: OpenRouterError) -> int:
    if error.code == "configuration_error":
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if error.code == "browser_unavailable":
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if error.code == "invalid_api_key":
        return status.HTTP_502_BAD_GATEWAY
    if error.code == "rate_limited":
        return status.HTTP_429_TOO_MANY_REQUESTS
    if error.code == "timeout":
        return status.HTTP_504_GATEWAY_TIMEOUT
    if error.code == "model_unavailable":
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if error.code in {"provider_unavailable", "invalid_response", "provider_error"}:
        return status.HTTP_502_BAD_GATEWAY
    return status.HTTP_502_BAD_GATEWAY


@router.post("/chat", response_model=ChatResponse)
async def send_chat_message(
    payload: ChatRequest,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    if payload.conversation_id is None:
        conversation = Conversation(
            id=str(uuid4()),
            user_id=user.id,
            title=payload.message.strip().splitlines()[0][:80] or "New conversation",
        )
        session.add(conversation)
        await session.flush()
    else:
        result = await session.execute(
            select(Conversation).where(
                Conversation.id == str(payload.conversation_id),
                Conversation.user_id == user.id,
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    history_result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(MAX_CONTEXT_MESSAGES)
    )
    history = list(reversed(history_result.scalars().all()))
    now = datetime.now(timezone.utc)
    user_message = Message(
        id=str(uuid4()),
        conversation_id=conversation.id,
        role="user",
        content=payload.message,
        created_at=now,
    )
    session.add(user_message)

    model_messages: list[dict] = [
        {
            "role": message.role,
            "content": message.content,
            **(
                {"reasoning_details": message.metadata_json["reasoning_details"]}
                if message.role == "assistant"
                and message.metadata_json
                and "reasoning_details" in message.metadata_json
                else {}
            ),
        }
        for message in history
    ]
    model_messages.append({"role": "user", "content": payload.message})
    memories = await retrieve_relevant_memories(
        session,
        user_id=user.id,
        query=payload.message,
    )
    model_id = resolve_model(payload.model_role)
    run = AgentRun(
        id=str(uuid4()),
        conversation_id=conversation.id,
        user_id=user.id,
        status="running",
        selected_agent="aether_core",
        model_id=model_id,
        state_snapshot={
            "run_id": "",
            "conversation_id": conversation.id,
            "user_id": user.id,
            "request": payload.message,
            "model_role": payload.model_role,
            "messages": model_messages,
            "memories": [memory.content for memory in memories],
            "step_count": 0,
            "model_calls": 0,
            "tool_calls": 0,
            "reported_cost_usd": 0.0,
        },
    )
    run.state_snapshot["run_id"] = run.id
    session.add(run)
    await session.commit()

    state: WorkflowState = {
        "run_id": run.id,
        "conversation_id": conversation.id,
        "user_id": user.id,
        "request": payload.message,
        "model_role": payload.model_role,
        "messages": model_messages,
        "memories": [memory.content for memory in memories],
        "step_count": 0,
        "model_calls": 0,
        "tool_calls": 0,
        "reported_cost_usd": 0.0,
    }
    await emit_event(
        session,
        run_id=run.id,
        agent_name="aether_core",
        event_type="agent.started",
        payload={"agent": "aether_core", "status": "started"},
    )
    try:
        completion = await run_workflow(
            session=session,
            client=openrouter,
            run=run,
            state=state,
            on_text_delta=lambda text: emit_assistant_delta(session, run_id=run.id, text=text),
        )
    except OpenRouterError as exc:
        raise HTTPException(
            status_code=provider_http_status(exc),
            detail=exc.user_message,
        ) from None

    assistant_message = Message(
        id=str(uuid4()),
        conversation_id=conversation.id,
        role="assistant",
        content=completion["answer"],
        metadata_json={
            "model": completion["model_id"],
            "reasoning_details": completion.get("reasoning_details"),
            "usage": completion.get("usage"),
            "agent": completion["selected_agent"],
            "agent_run_id": run.id,
            "pending_approval_id": completion.get("pending_approval_id"),
        },
        created_at=datetime.now(timezone.utc),
    )
    conversation.updated_at = datetime.now(timezone.utc)
    session.add(assistant_message)
    is_waiting_approval = completion.get("pending_approval_id") is not None
    is_cancelled = bool(completion.get("cancelled"))
    is_limited = bool(completion.get("limit_reached"))
    run.status = (
        "waiting_approval" if is_waiting_approval else
        "paused" if completion.get("paused") else
        "cancelled" if is_cancelled else
        "limit_reached" if is_limited else
        "completed"
    )
    await session.commit()
    if not is_waiting_approval and not completion.get("paused") and not is_cancelled and not is_limited:
        await emit_event(
            session,
            run_id=run.id,
            agent_name="aether_core",
            event_type="workflow.completed",
            payload={
                "status": "completed",
                "model": completion["model_id"],
                "selected_agent": completion["selected_agent"],
            },
        )

    return ChatResponse(
        conversation_id=conversation.id,
        reply=assistant_message.content,
        model=completion["model_id"],
        created_at=assistant_message.created_at,
        run_id=run.id,
        selected_agent=completion["selected_agent"],
        pending_approval_id=completion.get("pending_approval_id"),
    )


@router.post("/agents/runs/{run_id}/pause", status_code=status.HTTP_202_ACCEPTED)
async def pause_agent_run(
    run_id: str,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    result = await session.execute(
        select(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.user_id == user.id)
        .with_for_update()
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    if run.status in {"pause_requested", "paused"}:
        return {"status": run.status}
    if run.status != "running":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent run is not running")
    run.status = "pause_requested"
    await session.commit()
    await emit_event(
        session,
        run_id=run.id,
        agent_name="aether_core",
        event_type="workflow.pause_requested",
        payload={"status": "pause_requested"},
    )
    return {"status": "pause_requested"}


@router.post("/agents/runs/{run_id}/redirect", response_model=ChatResponse)
async def redirect_agent_run(
    run_id: str,
    payload: RunRedirectRequest,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    run_result = await session.execute(
        select(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.user_id == user.id)
        .with_for_update()
    )
    previous_run = run_result.scalar_one_or_none()
    if previous_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    if previous_run.status not in {"running", "pause_requested", "paused", "cancel_requested", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent run cannot be redirected")

    redirected_while_running = previous_run.status != "paused"
    if previous_run.status in {"running", "pause_requested"}:
        previous_run.status = "cancel_requested"
        await session.commit()
        await emit_event(
            session,
            run_id=previous_run.id,
            agent_name="aether_core",
            event_type="workflow.stop_requested",
            payload={"status": "cancel_requested", "reason": "redirect"},
        )
        for _ in range(300):
            await asyncio.sleep(0.1)
            await session.refresh(previous_run)
            if previous_run.status != "cancel_requested":
                break
        if previous_run.status == "cancel_requested":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The current run is still stopping. Try redirecting again shortly.",
            )
        if previous_run.status != "cancelled":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The current run did not stop cleanly; redirect was not started.",
            )
    elif previous_run.status == "cancel_requested":
        for _ in range(300):
            await asyncio.sleep(0.1)
            await session.refresh(previous_run)
            if previous_run.status != "cancel_requested":
                break
        if previous_run.status != "cancelled":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The current run did not stop cleanly; redirect was not started.",
            )

    conversation_result = await session.execute(
        select(Conversation).where(
            Conversation.id == previous_run.conversation_id,
            Conversation.user_id == user.id,
        )
    )
    conversation = conversation_result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    if redirected_while_running:
        assistant_saved = False
        for _ in range(100):
            assistant_messages = await session.scalars(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.role == "assistant",
                )
            )
            assistant_saved = any(
                message.metadata_json
                and message.metadata_json.get("agent_run_id") == previous_run.id
                for message in assistant_messages.all()
            )
            if assistant_saved:
                break
            await asyncio.sleep(0.05)
        if not assistant_saved:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The previous run stopped, but its final message is not yet available.",
            )

    checkpoint_result = await session.execute(
        select(AgentCheckpoint).where(
            AgentCheckpoint.agent_run_id == previous_run.id,
            AgentCheckpoint.checkpoint_key.in_(("worker-completed", "paused")),
        )
    )
    previous_states = [checkpoint.state_data for checkpoint in checkpoint_result.scalars().all()]
    previous_state = max(previous_states, key=lambda item: item.get("step_index", 0), default=previous_run.state_snapshot)
    completed_steps = previous_state.get("step_results", [])

    history_result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(MAX_CONTEXT_MESSAGES)
    )
    history = list(reversed(history_result.scalars().all()))
    model_messages = [
        {"role": message.role, "content": message.content}
        for message in history
        if not (
            message.role == "assistant"
            and message.metadata_json
            and message.metadata_json.get("agent_run_id") == previous_run.id
        )
    ]
    if completed_steps:
        completed_context = "\n".join(
            f"- {item['description']}: {item['result'][:1200]}"
            for item in completed_steps
            if isinstance(item, dict)
            and isinstance(item.get("description"), str)
            and isinstance(item.get("result"), str)
        )
        model_messages.append(
            {
                "role": "assistant",
                "content": f"Completed work from the redirected run, provided as context:\n{completed_context}",
            }
        )

    now = datetime.now(timezone.utc)
    redirect_message = payload.message.strip()
    model_messages.append({"role": "user", "content": redirect_message})
    session.add(
        Message(
            id=str(uuid4()),
            conversation_id=conversation.id,
            role="user",
            content=redirect_message,
            created_at=now,
        )
    )
    memories = await retrieve_relevant_memories(session, user_id=user.id, query=redirect_message)
    saved_model_role = previous_run.state_snapshot.get("model_role")
    model_role = (
        saved_model_role
        if saved_model_role in {"general", "coding"}
        else "coding" if previous_run.model_id == resolve_model("coding") else "general"
    )
    redirected_run = AgentRun(
        id=str(uuid4()),
        conversation_id=conversation.id,
        user_id=user.id,
        status="running",
        selected_agent="aether_core",
        model_id=resolve_model(model_role),
        state_snapshot={},
    )
    state: WorkflowState = {
        "run_id": redirected_run.id,
        "conversation_id": conversation.id,
        "user_id": user.id,
        "request": redirect_message,
        "model_role": model_role,
        "messages": model_messages,
        "memories": [memory.content for memory in memories],
        "step_count": 0,
        "model_calls": 0,
        "tool_calls": 0,
        "reported_cost_usd": 0.0,
        "redirected_from": previous_run.id,
    }
    redirected_run.state_snapshot = state
    session.add(redirected_run)
    conversation.updated_at = now
    await session.commit()
    await emit_event(
        session,
        run_id=redirected_run.id,
        agent_name="aether_core",
        event_type="workflow.redirected",
        payload={"status": "started", "previous_run_id": previous_run.id},
    )
    await emit_event(
        session,
        run_id=redirected_run.id,
        agent_name="aether_core",
        event_type="agent.started",
        payload={"agent": "aether_core", "status": "started"},
    )
    try:
        completion = await run_workflow(
            session=session,
            client=openrouter,
            run=redirected_run,
            state=state,
            on_text_delta=lambda text: emit_assistant_delta(
                session,
                run_id=redirected_run.id,
                text=text,
            ),
        )
    except OpenRouterError as exc:
        raise HTTPException(
            status_code=provider_http_status(exc),
            detail=exc.user_message,
        ) from None

    assistant_message = Message(
        id=str(uuid4()),
        conversation_id=conversation.id,
        role="assistant",
        content=completion["answer"],
        metadata_json={
            "model": completion["model_id"],
            "reasoning_details": completion.get("reasoning_details"),
            "usage": completion.get("usage"),
            "agent": completion["selected_agent"],
            "agent_run_id": redirected_run.id,
            "redirected_from": previous_run.id,
        },
        created_at=datetime.now(timezone.utc),
    )
    session.add(assistant_message)
    conversation.updated_at = datetime.now(timezone.utc)
    is_waiting_approval = completion.get("pending_approval_id") is not None
    is_paused = bool(completion.get("paused"))
    is_cancelled = bool(completion.get("cancelled"))
    is_limited = bool(completion.get("limit_reached"))
    redirected_run.status = (
        "waiting_approval" if is_waiting_approval else
        "paused" if is_paused else
        "cancelled" if is_cancelled else
        "limit_reached" if is_limited else
        "completed"
    )
    await session.commit()
    if not is_waiting_approval and not is_paused and not is_cancelled and not is_limited:
        await emit_event(
            session,
            run_id=redirected_run.id,
            agent_name="aether_core",
            event_type="workflow.completed",
            payload={
                "status": "completed",
                "model": completion["model_id"],
                "selected_agent": completion["selected_agent"],
            },
        )
    return ChatResponse(
        conversation_id=conversation.id,
        reply=assistant_message.content,
        model=completion["model_id"],
        created_at=assistant_message.created_at,
        run_id=redirected_run.id,
        selected_agent=completion["selected_agent"],
        pending_approval_id=completion.get("pending_approval_id"),
    )


@router.post("/agents/runs/{run_id}/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_agent_run(
    run_id: str,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    result = await session.execute(
        select(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.user_id == user.id)
        .with_for_update()
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    if run.status == "cancel_requested":
        return {"status": "cancel_requested"}
    if run.status not in {"running", "pause_requested"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent run is not running")
    run.status = "cancel_requested"
    await session.commit()
    await emit_event(
        session,
        run_id=run.id,
        agent_name="aether_core",
        event_type="workflow.stop_requested",
        payload={"status": "cancel_requested"},
    )
    return {"status": "cancel_requested"}


@router.get("/conversations", response_model=list[ConversationRead])
async def list_conversations(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Conversation]:
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    )
    return list(result.scalars().all())


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageRead])
async def list_conversation_messages(
    conversation_id: str,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Message]:
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    messages = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    )
    return list(messages.scalars().all())


@router.get("/agents")
async def list_agents() -> list[dict[str, str]]:
    from app.ai.agents.supervisor import AGENT_DESCRIPTIONS

    return [{"name": name, "description": description} for name, description in AGENT_DESCRIPTIONS.items()]


@router.get("/agents/runs/{run_id}/events")
async def list_agent_run_events(
    run_id: str,
    after: int = 0,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    result = await session.execute(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    events = await session.execute(
        select(AgentEvent)
        .where(AgentEvent.agent_run_id == run_id, AgentEvent.sequence > after)
        .order_by(AgentEvent.sequence)
    )
    return [
        {
            "event_id": event.id,
            "sequence": event.sequence,
            "type": event.event_type,
            "conversation_id": run.conversation_id,
            "run_id": run_id,
            "created_at": event.created_at,
            "data": {"agent": event.agent_name, **event.payload},
        }
        for event in events.scalars().all()
    ]


@router.post("/agents/runs/{run_id}/resume", response_model=ChatResponse)
async def resume_agent_run(
    run_id: str,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    result = await session.execute(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user.id)
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    if run.status not in {"running", "failed", "paused"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent run is not resumable")

    conversation_result = await session.execute(
        select(Conversation).where(
            Conversation.id == run.conversation_id,
            Conversation.user_id == user.id,
        )
    )
    conversation = conversation_result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    checkpoint_result = await session.execute(
        select(AgentCheckpoint).where(
            AgentCheckpoint.agent_run_id == run.id,
            AgentCheckpoint.checkpoint_key == "worker-completed",
        )
    )
    completed_checkpoint = checkpoint_result.scalar_one_or_none()
    completed_state = completed_checkpoint.state_data if completed_checkpoint is not None else None
    if completed_state is None:
        paused_checkpoint_result = await session.execute(
            select(AgentCheckpoint).where(
                AgentCheckpoint.agent_run_id == run.id,
                AgentCheckpoint.checkpoint_key == "paused",
            )
        )
        paused_checkpoint = paused_checkpoint_result.scalar_one_or_none()
        paused_state = paused_checkpoint.state_data if paused_checkpoint is not None else None
        pending_checkpoint_result = await session.execute(
            select(AgentCheckpoint).where(
                AgentCheckpoint.agent_run_id == run.id,
                AgentCheckpoint.checkpoint_key == "approval-pending",
            )
        )
        pending_checkpoint = pending_checkpoint_result.scalar_one_or_none()
        pending_state = pending_checkpoint.state_data if pending_checkpoint is not None else None
        approved_state: WorkflowState | None = None
        if pending_state and paused_state is None:
            approval_result = await session.execute(
                select(Approval).where(
                    Approval.id == pending_state.get("pending_approval_id"),
                    Approval.agent_run_id == run.id,
                    Approval.status == "approved",
                )
            )
            approval = approval_result.scalar_one_or_none()
            if approval is not None:
                execution_result = await session.execute(
                    select(ToolExecution).where(
                        ToolExecution.agent_run_id == run.id,
                        ToolExecution.tool_name == approval.tool_name,
                        ToolExecution.status == "completed",
                    )
                )
                execution = next(
                    (
                        item
                        for item in execution_result.scalars().all()
                        if item.input_data == approval.tool_arguments and item.output_data is not None
                    ),
                    None,
                )
                if execution is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Approved tool result is unavailable",
                    )
                continuation_messages = pending_state.get("continuation_messages")
                if not isinstance(continuation_messages, list):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Approval continuation is unavailable",
                    )
                approved_state = {
                    **pending_state,
                    "resume_messages": [
                        *continuation_messages,
                        {
                            "role": "tool",
                            "tool_call_id": approval.tool_call_id,
                            "content": json.dumps(execution.output_data, ensure_ascii=True),
                        },
                    ],
                }
                approved_state.pop("pending_approval_id", None)
                approved_state.pop("pending_tool_call", None)
                approved_state.pop("continuation_messages", None)

        if paused_state is not None:
            state = {key: value for key, value in paused_state.items() if key != "paused"}
        elif approved_state is not None:
            state = approved_state
        else:
            worker_checkpoint_result = await session.execute(
                select(AgentCheckpoint).where(
                    AgentCheckpoint.agent_run_id == run.id,
                    AgentCheckpoint.checkpoint_key == "worker-start",
                )
            )
            worker_checkpoint = worker_checkpoint_result.scalar_one_or_none()
            progress_checkpoint_result = await session.execute(
                select(AgentCheckpoint).where(
                    AgentCheckpoint.agent_run_id == run.id,
                    AgentCheckpoint.checkpoint_key == "tool-progress",
                )
            )
            progress_checkpoint = progress_checkpoint_result.scalar_one_or_none()
            budget_checkpoint_result = await session.execute(
                select(AgentCheckpoint).where(
                    AgentCheckpoint.agent_run_id == run.id,
                    AgentCheckpoint.checkpoint_key == "workflow-budget",
                )
            )
            budget_checkpoint = budget_checkpoint_result.scalar_one_or_none()
            worker_state = worker_checkpoint.state_data if worker_checkpoint is not None else None
            progress_state = progress_checkpoint.state_data if progress_checkpoint is not None else None
            budget_state = budget_checkpoint.state_data if budget_checkpoint is not None else None
            completed_steps_result = await session.execute(
                select(AgentCheckpoint).where(
                    AgentCheckpoint.agent_run_id == run.id,
                    AgentCheckpoint.checkpoint_key.like("plan-step-%-completed"),
                )
            )
            candidates = [
                (worker_state, 1),
                (progress_state, 2),
                (budget_state, 4),
                *[
                    (item.state_data, 3)
                    for item in completed_steps_result.scalars().all()
                ],
            ]
            resumable_states = [(item, priority) for item, priority in candidates if item is not None]
            if resumable_states:
                state = max(
                    resumable_states,
                    key=lambda item: (item[0].get("step_index", 0), item[1]),
                )[0]
            else:
                state = run.state_snapshot
        if not state or not state.get("messages"):
            history_result = await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(MAX_CONTEXT_MESSAGES)
            )
            history = list(reversed(history_result.scalars().all()))
            last_user_message = next((message for message in reversed(history) if message.role == "user"), None)
            if last_user_message is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No user message to resume")
            model_role = "coding" if run.model_id == resolve_model("coding") else "general"
            state = {
                "run_id": run.id,
                "conversation_id": conversation.id,
                "user_id": user.id,
                "request": last_user_message.content,
                "model_role": model_role,
                "messages": [{"role": message.role, "content": message.content} for message in history],
                "step_count": 0,
            }

    run.status = "running"
    await session.commit()
    await emit_event(
        session,
        run_id=run.id,
        agent_name="aether_core",
        event_type="agent.status",
        payload={"status": "resuming"},
    )
    if completed_state is None:
        try:
            completed_state = await run_workflow(
                session=session,
                client=openrouter,
                run=run,
                state=state,
                on_text_delta=lambda text: emit_assistant_delta(session, run_id=run.id, text=text),
            )
        except OpenRouterError as exc:
            raise HTTPException(
                status_code=provider_http_status(exc),
                detail=exc.user_message,
            ) from None

    existing_messages = await session.execute(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.role == "assistant",
        )
    )
    assistant_message = next(
        (
            message
            for message in existing_messages.scalars().all()
            if message.metadata_json and message.metadata_json.get("agent_run_id") == run.id
        ),
        None,
    )
    now = datetime.now(timezone.utc)
    metadata = {
        "model": completed_state["model_id"],
        "reasoning_details": completed_state.get("reasoning_details"),
        "usage": completed_state.get("usage"),
        "agent": completed_state["selected_agent"],
        "agent_run_id": run.id,
    }
    if completed_state.get("pending_approval_id"):
        metadata["pending_approval_id"] = completed_state["pending_approval_id"]
    if assistant_message is None:
        assistant_message = Message(
            id=str(uuid4()),
            conversation_id=conversation.id,
            role="assistant",
            content=completed_state["answer"],
            metadata_json=metadata,
            created_at=now,
        )
        session.add(assistant_message)
    else:
        assistant_message.content = completed_state["answer"]
        assistant_message.metadata_json = metadata
    conversation.updated_at = now
    is_waiting_approval = completed_state.get("pending_approval_id") is not None
    is_paused = bool(completed_state.get("paused"))
    is_cancelled = bool(completed_state.get("cancelled"))
    is_limited = bool(completed_state.get("limit_reached"))
    run.status = (
        "waiting_approval" if is_waiting_approval else
        "paused" if is_paused else
        "cancelled" if is_cancelled else
        "limit_reached" if is_limited else
        "completed"
    )
    await session.commit()
    if not is_waiting_approval and not is_paused and not is_cancelled and not is_limited:
        await emit_event(
            session,
            run_id=run.id,
            agent_name="aether_core",
            event_type="workflow.completed",
            payload={
                "status": "completed",
                "model": completed_state["model_id"],
                "selected_agent": completed_state["selected_agent"],
                "resumed": True,
            },
        )
    return ChatResponse(
        conversation_id=conversation.id,
        reply=completed_state["answer"],
        model=completed_state["model_id"],
        created_at=now,
        run_id=run.id,
        selected_agent=completed_state["selected_agent"],
        pending_approval_id=completed_state.get("pending_approval_id"),
    )
