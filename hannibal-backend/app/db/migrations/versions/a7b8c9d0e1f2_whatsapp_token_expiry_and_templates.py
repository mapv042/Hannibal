"""whatsapp token expiry and per-WABA template status

Embedded Signup issues 60-day tokens and connects the doctor's own WABA, which
starts with none of our templates. The office now records when its token
expires (to refresh it in time) and the status of each template on its WABA.

Revision ID: a7b8c9d0e1f2
Revises: f4a5b6c7d8e9
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "offices",
        sa.Column("whatsapp_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "offices",
        sa.Column("whatsapp_token_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("offices", sa.Column("whatsapp_token_error", sa.Text(), nullable=True))
    op.add_column(
        "offices",
        sa.Column("whatsapp_templates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "offices",
        sa.Column("whatsapp_templates_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("offices", "whatsapp_templates_synced_at")
    op.drop_column("offices", "whatsapp_templates")
    op.drop_column("offices", "whatsapp_token_error")
    op.drop_column("offices", "whatsapp_token_checked_at")
    op.drop_column("offices", "whatsapp_token_expires_at")
