#!/usr/bin/env python3
"""Clear an office's volatile Redis state between manual test scenarios.

Testing runs a month of appointments through one office in an afternoon, which
leaves short-lived keys behind that are correct in production and pure noise in
a test session: a slot lock from a booking cancelled thirty seconds ago, a
conversation history carrying ten scenarios' worth of stale statements, a
session still pointing at an appointment from the last scenario.

Deliberately does NOT clear:
  - wamsg_dedup:*   webhook idempotency; clearing it lets a Meta retry replay a
                    message you already answered, which is a bug you would then
                    spend the afternoon chasing.
  - anything in Postgres. Appointments are the thing under test.

Usage:
    python scripts/reset_test_state.py <office_id>
    python scripts/reset_test_state.py <office_id> --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Running this as `python scripts/reset_test_state.py` puts `scripts/` at the
# front of sys.path, not the backend root, so `app` wouldn't import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import redis.asyncio as aioredis

from app.config import settings

# Patterns cleared per office. `{office_id}` is substituted; `*` matches the
# per-patient part of a key whose office is in the suffix.
OFFICE_PATTERNS = [
    "whatsapp:bot_paused:{office_id}",
    "doctor_session:{office_id}",
    "doctor_last_inbound:{office_id}",
    "doctor_msg_drafts:{office_id}",
    "avail_cache:{office_id}:*",
    "slot_lock:{office_id}:*",
    "conv_lock:{office_id}:*",
    "session:*:{office_id}",
    "unconfirmed_summary_sent:{office_id}:*",
]

# Audit alerts are keyed by appointment, not by office, so they can't be scoped
# the same way. They are cleared wholesale — a test environment has no alert
# worth preserving, and the dedup only exists to avoid nagging a real doctor.
GLOBAL_PATTERNS = [
    "audit_alert:*",
]


async def reset(office_id: str, dry_run: bool) -> int:
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    total = 0
    try:
        patterns = [p.format(office_id=office_id) for p in OFFICE_PATTERNS]
        patterns += GLOBAL_PATTERNS

        for pattern in patterns:
            keys = [key async for key in client.scan_iter(match=pattern, count=500)]
            if not keys:
                continue
            total += len(keys)
            print(f"{'would delete' if dry_run else 'deleted':>12}  {len(keys):>4}  {pattern}")
            if not dry_run:
                await client.delete(*keys)

        if total == 0:
            print("nothing to clear")
    finally:
        await client.aclose()
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("office_id", help="Office UUID to reset")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be deleted without deleting it",
    )
    args = parser.parse_args()

    total = asyncio.run(reset(args.office_id, args.dry_run))
    print(f"\n{total} key(s) {'matched' if args.dry_run else 'cleared'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
