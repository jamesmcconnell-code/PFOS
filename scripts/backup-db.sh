#!/usr/bin/env bash
# Create an encrypted PostgreSQL backup. Requires Docker Compose and age.
set -euo pipefail

if ! command -v age >/dev/null 2>&1; then
  echo "age is required. Install it, then set BACKUP_RECIPIENT to an age public key." >&2
  exit 1
fi
if [[ -z "${BACKUP_RECIPIENT:-}" ]]; then
  echo "Set BACKUP_RECIPIENT to your age public key (age1...)." >&2
  exit 1
fi

backup_dir="${BACKUP_DIR:-./backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="${backup_dir}/pfos-${timestamp}.dump.age"
mkdir -p "$backup_dir"
umask 077

docker compose exec -T db pg_dump -U "${POSTGRES_USER:-pfos}" -Fc "${POSTGRES_DB:-pfos}" | age -r "$BACKUP_RECIPIENT" -o "$output"
echo "Encrypted PFOS backup created: $output"
