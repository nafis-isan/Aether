from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261124_0005"
down_revision: Union[str, None] = "20261031_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("agent_run_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_artifacts_user_id", "artifacts", ["user_id"], unique=False)
    op.create_index("ix_artifacts_conversation_id", "artifacts", ["conversation_id"], unique=False)
    op.create_index("ix_artifacts_agent_run_id", "artifacts", ["agent_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_artifacts_agent_run_id", table_name="artifacts")
    op.drop_index("ix_artifacts_conversation_id", table_name="artifacts")
    op.drop_index("ix_artifacts_user_id", table_name="artifacts")
    op.drop_table("artifacts")
