#!/usr/bin/env bash
set -euo pipefail

if [[ "${RESTORE_CONFIRM:-}" != "YES" ]]; then
  echo "Set RESTORE_CONFIRM=YES to allow destructive restore" >&2
  exit 2
fi

resolve_database_url() {
  if [[ -n "${DATABASE_URL:-}" && -n "${DATABASE_URL_FILE:-}" ]]; then
    echo "DATABASE_URL and DATABASE_URL_FILE cannot both be set" >&2
    exit 2
  fi

  local url=""
  if [[ -n "${DATABASE_URL_FILE:-}" ]]; then
    url="$(cat "$DATABASE_URL_FILE")"
  else
    url="${DATABASE_URL:-}"
  fi

  if [[ -z "$url" ]]; then
    echo "DATABASE_URL or DATABASE_URL_FILE is required" >&2
    exit 2
  fi

  printf '%s' "${url/postgresql+psycopg:/postgresql:}"
}

DATABASE_DSN="$(resolve_database_url)"
BACKUP_FILE="${1:-${BACKUP_FILE:-backup.dump}}"

case "$DATABASE_DSN" in
  postgresql://*) ;;
  *)
    echo "PostgreSQL database URL required" >&2
    exit 2
    ;;
esac

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 2
fi

if [[ -f "$BACKUP_FILE.sha256" ]]; then
  (
    cd "$(dirname "$BACKUP_FILE")"
    sha256sum --check "$(basename "$BACKUP_FILE").sha256"
  )
else
  echo "Warning: checksum file is missing" >&2
fi

pg_restore   --clean   --if-exists   --no-owner   --no-acl   --exit-on-error   --single-transaction   --dbname="$DATABASE_DSN"   "$BACKUP_FILE"

echo "restore_complete=$BACKUP_FILE"
