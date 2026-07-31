#!/usr/bin/env bash
# Restore an encrypted backup. This replaces data in the selected PFOS database.
set -euo pipefail

backup_file="${1:-}"
if [[ -z "$backup_file" || ! -f "$backup_file" ]]; then
  echo "Usage: BACKUP_IDENTITY_FILE=/path/to/key.txt PFOS_RESTORE_CONFIRM=RESTORE $0 backups/pfos-<timestamp>.dump.age" >&2
  exit 1
fi
if ! command -v age >/dev/null 2>&1 || [[ -z "${BACKUP_IDENTITY_FILE:-}" ]]; then
  echo "age and BACKUP_IDENTITY_FILE are required." >&2
  exit 1
fi
if [[ "${PFOS_RESTORE_CONFIRM:-}" != "RESTORE" ]]; then
  echo "Refusing to restore without PFOS_RESTORE_CONFIRM=RESTORE." >&2
  exit 1
fi

age -d -i "$BACKUP_IDENTITY_FILE" "$backup_file" | docker compose exec -T db pg_restore -U "${POSTGRES_USER:-pfos}" -d "${POSTGRES_DB:-pfos}" --clean --if-exists --no-owner
echo "PFOS database restored from $backup_file"
