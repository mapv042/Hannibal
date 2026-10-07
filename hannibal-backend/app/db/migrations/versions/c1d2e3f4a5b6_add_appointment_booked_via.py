"""add appointments.booked_via

Which channel wrote each appointment (patient assistant, doctor assistant,
dashboard, urgency), so the dashboard can show how much of the agenda the
assistant filled on its own. Existing rows stay NULL (unknown).

Revision ID: c1d2e3f4a5b6
Revises: b8d2e6f1a3c7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b8d2e6f1a3c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("appointments", sa.Column("booked_via", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("appointments", "booked_via")
