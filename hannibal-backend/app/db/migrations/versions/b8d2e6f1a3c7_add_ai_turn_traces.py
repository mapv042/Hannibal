"""add ai_turn_traces table

One row per assistant turn (patient or doctor channel): tool calls with their
arguments and results, reply-validator findings, the final reply, latency and
tokens. Diagnosis data for "why did the bot say that", scoped by office.

Revision ID: b8d2e6f1a3c7
Revises: a7e3d91c4b02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8d2e6f1a3c7"
down_revision: Union[str, None] = "a7e3d91c4b02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_turn_traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("office_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("whatsapp_id", sa.String(length=50), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("reasoning_effort", sa.String(length=20), nullable=True),
        sa.Column("user_text", sa.Text(), nullable=True),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=True),
        sa.Column("grounding_violations", postgresql.JSONB(), nullable=True),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(length=20), server_default=sa.text("'ok'"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("llm_calls", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_input", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tokens_output", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ai_turn_traces_office_created", "ai_turn_traces", ["office_id", "created_at"]
    )
    op.create_index(
        "ix_ai_turn_traces_conversation", "ai_turn_traces", ["conversation_id"]
    )
    # Patient data: close it to Supabase's public roles like every other table.
    # The backend connects as the table owner and is unaffected.
    op.execute("ALTER TABLE ai_turn_traces ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_ai_turn_traces_conversation", table_name="ai_turn_traces")
    op.drop_index("ix_ai_turn_traces_office_created", table_name="ai_turn_traces")
    op.drop_table("ai_turn_traces")
