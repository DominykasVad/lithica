#!/usr/bin/dumb-init /bin/sh
set -e
cd /opt/app

alembic upgrade head

echo "Starting Lithica API on port ${PORT}"
exec hupper -m uvicorn lithica.app:app --host 0.0.0.0 --port "${PORT}" --no-access-log
