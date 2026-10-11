#!/usr/bin/dumb-init /bin/sh
set -e
cd /opt/app

alembic upgrade head

echo "Starting Lithica API on port ${PORT} - ${THREADS} threads, reloading on changes"
# one process, restarted when a source file changes
exec uvicorn lithica.app:app --host 0.0.0.0 --port "${PORT}" --no-access-log --reload
