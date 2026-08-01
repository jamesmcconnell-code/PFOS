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
temporary_output="${output}.partial"
mkdir -p "$backup_dir"
umask 077

trap 'rm -f "$temporary_output"' EXIT
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-pfos}" -Fc "${POSTGRES_DB:-pfos}" | age -r "$BACKUP_RECIPIENT" -o "$temporary_output"
mv "$temporary_output" "$output"
trap - EXIT
echo "Encrypted PFOS backup created: $output"
