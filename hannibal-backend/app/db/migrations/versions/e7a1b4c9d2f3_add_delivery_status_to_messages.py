"""add delivery_status to messages

Revision ID: e7a1b4c9d2f3
Revises: d5f8a2b3c6e7
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7a1b4c9d2f3"
down_revision: Union[str, None] = "d5f8a2b3c6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("delivery_status", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "delivery_status")
