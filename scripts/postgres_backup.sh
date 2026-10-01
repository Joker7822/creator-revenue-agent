#!/usr/bin/env bash
set -euo pipefail
umask 077

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

mkdir -p "$(dirname "$BACKUP_FILE")"

pg_dump   --format=custom   --no-owner   --no-acl   --file="$BACKUP_FILE"   "$DATABASE_DSN"

sha256sum "$BACKUP_FILE" > "$BACKUP_FILE.sha256"

echo "backup_file=$BACKUP_FILE"
echo "checksum_file=$BACKUP_FILE.sha256"
