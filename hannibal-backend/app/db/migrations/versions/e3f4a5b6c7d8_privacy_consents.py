"""privacy consent evidence and the office's privacy contact

LFPDPPP: health data is sensitive personal data, so a patient accepts the
office's privacy notice before the assistant books. privacy_consents stores
each answer as evidence (per WhatsApp number and notice version);
offices.privacy_contact_email is the ARCO contact shown on the notice.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "offices", sa.Column("privacy_contact_email", sa.String(length=255), nullable=True)
    )
    op.create_table(
        "privacy_consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("office_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("whatsapp_id", sa.String(length=50), nullable=False),
        sa.Column("notice_version", sa.String(length=20), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("evidence_message_id", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "office_id", "whatsapp_id", "notice_version", name="uq_privacy_consent_version"
        ),
    )
    # Patient data: same default as every other table (see project_supabase_rls).
    op.execute("ALTER TABLE privacy_consents ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("privacy_consents")
    op.drop_column("offices", "privacy_contact_email")
