#!/bin/bash
# Production startup script for Railway
# Runs migrations, collectstatic, worker, and gunicorn

set -e

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting opportunities worker in background..."
python manage.py opportunities_worker --poll-interval=3 &
WORKER_PID=$!
echo "Worker started with PID $WORKER_PID"

echo "Starting gunicorn..."
exec gunicorn kairo.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 2 \
    --threads 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
