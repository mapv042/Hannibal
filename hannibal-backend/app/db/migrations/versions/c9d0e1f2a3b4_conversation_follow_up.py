"""conversation follow-up

One nudge, at most once a day per conversation, when a patient goes quiet with
offered slots or a booking summary in hand. The conversation carries when it is
due, when the last one went out, and what was pending; the office can turn it
off.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("follow_up_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("follow_up_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("follow_up_context", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "ix_conversations_follow_up_due_at", "conversations", ["follow_up_due_at"]
    )
    op.add_column(
        "offices",
        sa.Column("follow_up_enabled", sa.Boolean(), server_default="true", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("offices", "follow_up_enabled")
    op.drop_index("ix_conversations_follow_up_due_at", table_name="conversations")
    op.drop_column("conversations", "follow_up_context")
    op.drop_column("conversations", "follow_up_sent_at")
    op.drop_column("conversations", "follow_up_due_at")
