"""Custom SQLAlchemy column types."""

from __future__ import annotations

import json

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.security import decrypt_data, encrypt_data


class EncryptedText(TypeDecorator):
    """Text column encrypted at rest with the app ENCRYPTION_KEY (Fernet).

    Values are encrypted on write and decrypted on read, so application code
    keeps working with plaintext. Legacy rows written before encryption was
    enabled fail Fernet decryption and are returned as-is; they get encrypted
    the next time the row is written.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_data(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return decrypt_data(value)
        except Exception:
            # Legacy plaintext row (pre-encryption) — pass through.
            return value


class EncryptedJSON(TypeDecorator):
    """A dict/JSON column encrypted at rest (Fernet), stored as Text.

    The value is JSON-serialized then encrypted on write, and decrypted then
    parsed on read — so callers keep working with plain dicts. Used for OAuth
    token bundles (access + refresh tokens). Legacy rows stored as plaintext
    JSON (or a JSONB column pre-migration) are parsed as-is and get encrypted
    on the next write.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_data(json.dumps(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        # Already a dict (e.g. a JSONB column read before the type migration).
        if isinstance(value, dict):
            return value
        try:
            return json.loads(decrypt_data(value))
        except Exception:
            # Legacy plaintext JSON string — parse directly.
            try:
                return json.loads(value)
            except Exception:
                return None
