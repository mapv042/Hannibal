#!/usr/bin/env python3
"""Seed the single office the conversation simulator runs against.

A thin command line over `app.modules.sim.seed`, which the reset endpoint uses
too — one definition of what the simulator's practice looks like, so the button
and the command can never drift apart.

Usage:
    python scripts/seed_sim_office.py             # seed, or complain if already seeded
    python scripts/seed_sim_office.py --if-empty  # seed only if empty, never complain
    python scripts/seed_sim_office.py --reset     # wipe and reseed

`--if-empty` is what the container runs at boot: it makes the throwaway database
genuinely throwaway, since destroying it and restarting brings the office back
with no one having to remember a command. It exits 0 when there was nothing to
do, so only a real failure stops the boot — and a simulator with no office is
useless, so failing loudly there is right.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Running this as `python scripts/seed_sim_office.py` puts `scripts/` at the
# front of sys.path, not the backend root, so `app` wouldn't import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.config import settings
from app.db.base import dispose_engine, get_async_session_maker
from app.db.models import ReminderRule, TimeBlock


def _refuse_in_production() -> None:
    """Never let this run against a real database."""
    if settings.is_production:
        raise SystemExit(
            "refusing to run: ENVIRONMENT=production. This script wipes and "
            "reseeds an entire database."
        )
    if not settings.simulation_mode:
        raise SystemExit(
            "refusing to run: SIMULATION_MODE is off. Set it so this cannot be "
            "pointed at a normal environment by accident."
        )


async def main(do_reset: bool, if_empty: bool) -> int:
    _refuse_in_production()

    # Imported after the guard so a production run fails on the guard, not here.
    from app.modules.sim import seed as sim_seed

    async with get_async_session_maker()() as db:
        existing = await sim_seed.existing_offices(db)

        if existing and not do_reset:
            if if_empty:
                print(f"{len(existing)} office(s) already present — nothing to do.")
                await dispose_engine()
                return 0
            print(
                f"{len(existing)} office(s) already present — pass --reset to wipe "
                "and reseed. Doing nothing."
            )
            await dispose_engine()
            return 1

        if existing:
            await sim_seed.wipe_all(db)
            print("  wiped every table")

        office = await sim_seed.seed_office(db)

        rules = len(
            (
                await db.execute(
                    select(ReminderRule).where(ReminderRule.office_id == office.id)
                )
            ).scalars().all()
        )
        blocks = len(
            (
                await db.execute(
                    select(TimeBlock).where(TimeBlock.office_id == office.id)
                )
            ).scalars().all()
        )
        recap = sim_seed.summary(office, rules, blocks)

    await dispose_engine()

    print("\n" + recap)
    print(
        "\n  pendiente: apunta office.google_calendar_id a un calendario "
        "secundario desechable"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="wipe every table first (the simulator's database is disposable)",
    )
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="seed only when the database is empty, and exit 0 either way",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.reset, args.if_empty)))
