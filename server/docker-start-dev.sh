#!/usr/bin/dumb-init /bin/sh
set -e
cd /opt/app

alembic upgrade head

echo "Starting Lithica API on ${HOST:-::} port ${PORT} - ${THREADS} threads, reloading on changes"
# uvicorn serving lithica.app:app; reads HOST and PORT. One process,
# restarted when a source file changes
exec python -m lithica.serve --reload
