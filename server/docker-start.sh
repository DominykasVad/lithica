#!/usr/bin/dumb-init /bin/sh
set -e
cd /opt/app

alembic upgrade head

echo "Starting Lithica API on ${HOST:-::} port ${PORT} - ${WORKERS} process(es), ${THREADS} threads each"
# uvicorn serving lithica.app:app; reads HOST, PORT and WORKERS
exec python -m lithica.serve
