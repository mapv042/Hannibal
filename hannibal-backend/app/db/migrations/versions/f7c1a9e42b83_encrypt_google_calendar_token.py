"""Encrypt offices.google_calendar_token at rest (JSONB -> encrypted Text).

The column held OAuth access + refresh tokens in plaintext JSONB. Convert it
to Text so the EncryptedJSON type can store the Fernet ciphertext. Existing
rows are converted to their JSON text representation; EncryptedJSON reads that
legacy plaintext transparently and re-encrypts it on the next write.

Revision ID: f7c1a9e42b83
Revises: e5b7d3a1c9f2
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f7c1a9e42b83"
down_revision = "e5b7d3a1c9f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "offices",
        "google_calendar_token",
        existing_type=postgresql.JSONB(),
        type_=sa.Text(),
        existing_nullable=True,
        postgresql_using="google_calendar_token::text",
    )


def downgrade() -> None:
    # Only reversible for rows still in plaintext JSON; encrypted rows won't
    # cast back to JSONB (acceptable — downgrade is a dev-only escape hatch).
    op.alter_column(
        "offices",
        "google_calendar_token",
        existing_type=sa.Text(),
        type_=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using="google_calendar_token::jsonb",
    )
