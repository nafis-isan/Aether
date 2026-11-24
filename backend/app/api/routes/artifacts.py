from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.database.models import Artifact, User

router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])


class ArtifactCreate(BaseModel):
    conversation_id: str
    agent_run_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="document", max_length=40)
    mime_type: str = Field(default="text/plain", max_length=120)
    content: str = Field(default="", max_length=5_000_000)
    metadata: dict = Field(default_factory=dict)


class ArtifactRead(BaseModel):
    id: str
    conversation_id: str
    agent_run_id: str | None
    title: str
    kind: str
    mime_type: str
    content: str
    metadata: dict = Field(validation_alias="metadata_json", serialization_alias="metadata")
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ArtifactRead])
async def list_artifacts(
    conversation_id: str | None = None,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Artifact]:
    statement = select(Artifact).where(Artifact.user_id == user.id)
    if conversation_id:
        statement = statement.where(Artifact.conversation_id == conversation_id)
    result = await session.execute(statement.order_by(Artifact.created_at.desc(), Artifact.id))
    return list(result.scalars().all())


@router.post("", response_model=ArtifactRead, status_code=201)
async def create_artifact(
    payload: ArtifactCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Artifact:
    artifact = Artifact(
        id=str(uuid4()),
        user_id=user.id,
        conversation_id=payload.conversation_id,
        agent_run_id=payload.agent_run_id,
        title=payload.title,
        kind=payload.kind,
        mime_type=payload.mime_type,
        content=payload.content,
        metadata_json=payload.metadata,
    )
    session.add(artifact)
    await session.commit()
    await session.refresh(artifact)
    return artifact


@router.delete("/{artifact_id}", status_code=204)
async def delete_artifact(
    artifact_id: str,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    artifact = await session.scalar(select(Artifact).where(Artifact.id == artifact_id, Artifact.user_id == user.id))
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    await session.delete(artifact)
    await session.commit()
