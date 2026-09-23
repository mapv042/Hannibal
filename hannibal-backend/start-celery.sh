#!/bin/bash
set -e

# Beat is the clock that fires the periodic sweeps. The simulator supplies its
# own clock — advancing it runs the sweep synchronously and reports what it
# dispatched — so a beat there would fire a second, real-time sweep underneath
# and make the run report reminders the operator never triggered.
#
# CELERY_BEAT=0 turns it off; everywhere else it stays on.
if [ "${CELERY_BEAT:-1}" = "0" ]; then
  echo "Starting Celery worker (no beat)..."
  exec celery -A celery_app worker --loglevel=info --concurrency=2
fi

echo "Starting Celery worker + beat..."
exec celery -A celery_app worker --beat --loglevel=info --concurrency=2
