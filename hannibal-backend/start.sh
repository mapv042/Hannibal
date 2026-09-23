#!/bin/bash
set -e

echo "Running database migrations..."
alembic upgrade head

# The simulator's database is disposable by design — resetting a scenario means
# destroying and reseeding — so it has to be able to come back from nothing
# without anyone remembering a command. `--if-empty` exits 0 when an office is
# already there, so this is a no-op on every boot but the first; a genuine
# failure still stops the boot, which is right, because a simulator with no
# office is useless.
#
# Guarded by the flag, so no other environment ever runs it. The script itself
# also refuses when ENVIRONMENT=production or SIMULATION_MODE is off.
if [ "${SIMULATION_MODE:-0}" = "1" ]; then
  echo "Seeding the simulator office (if empty)..."
  python scripts/seed_sim_office.py --if-empty
fi

echo "Starting Hannibal backend..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
