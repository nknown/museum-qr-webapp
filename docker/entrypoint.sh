#!/bin/sh
set -eu

if [ "${DB_TYPE:-postgres}" = "postgres" ]; then
  echo "Waiting for PostgreSQL at ${POSTGRES_DB_HOST:-db}:${POSTGRES_DB_PORT:-5432}..."
  while ! nc -z "${POSTGRES_DB_HOST:-db}" "${POSTGRES_DB_PORT:-5432}"; do
    sleep 1
  done
fi

exec "$@"
