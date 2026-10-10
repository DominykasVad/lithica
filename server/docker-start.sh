#!/usr/bin/dumb-init /bin/sh
set -e
cd /opt/app

alembic upgrade head

echo "Starting Lithica API on port ${PORT} - Running on ${THREADS} threads"
exec waitress-serve-3 --listen "*:${PORT}" --threads ${THREADS} lithica.facade:app
