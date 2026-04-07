#!/bin/bash
set -e

echo "Starting Celery worker + beat..."
exec celery -A celery_app worker --beat --loglevel=info --concurrency=2
